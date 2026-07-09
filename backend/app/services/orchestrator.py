"""Orchestrator — LiteLLM 기반 툴루프 (item 13, D3/D21/D22/D26).

유저의 freeform 챗을 받아 LLM 툴루프를 돌린다. LLM은 도구로 goal/task를 만들고 상태를
조회하고 blocked 에이전트를 재개시킨다. 권위 상태는 항상 DB이며 도구는 그 위에서 동작한다.

도구:
  create_goal(title)                         보드 goal 생성(이후 dispatch가 자동 연결)
  dispatch_task(agent_name, instructions,    엣지 진입점에 task 디스패치. override_to_agent_name이
               override_to_agent_name?)      있으면 1회 override 라우팅(D21, 엣지 불변)
  get_project_status()                       에이전트별 현재 상태(권위 DB)
  resume_task(agent_name, input)             blocked/needs-input 에이전트에 입력 전달 재개(D22)
  list_outputs()                             최근 아웃풋 요약

LLM 클라이언트는 주입 가능(테스트=스크립트). 프로덕션=LiteLLMClient(strong tier + 캐싱, D26/D32).
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Agent, Goal, Output, OrchestratorMessage, Project, Task
from app.services import task_service as ts
from app.services.config_store import load_config, model_for_tier
from app.status_util import agent_status_map

log = logging.getLogger("app.orchestrator")


# --- 정규화된 LLM 응답 ---


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class LLMResponse:
    tool_calls: list[ToolCall] | None = None
    content: str | None = None
    tokens_in: int = 0   # dev-runner가 스텝별 토큰을 누적(item 16).
    tokens_out: int = 0


# --- 도구 스키마(OpenAI/LiteLLM function-calling 형식) ---

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "create_goal",
        "description": "Create a board goal to group the tasks for this instruction.",
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]},
    }},
    {"type": "function", "function": {
        "name": "dispatch_task",
        "description": "Dispatch a task to an agent by name. Downstream agents fire automatically via edges; usually dispatch only the chain entry agent. Optionally override routing for this one task.",
        "parameters": {"type": "object", "properties": {
            "agent_name": {"type": "string"},
            "instructions": {"type": "string"},
            "override_to_agent_name": {"type": "string", "description": "Optional one-off route target; does not change edges."},
        }, "required": ["agent_name", "instructions"]},
    }},
    {"type": "function", "function": {
        "name": "get_project_status",
        "description": "Get the current status of every agent from authoritative task state.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "resume_task",
        "description": "Provide input to a blocked/needs-input agent and resume its task.",
        "parameters": {"type": "object", "properties": {
            "agent_name": {"type": "string"}, "input": {"type": "string"},
        }, "required": ["agent_name", "input"]},
    }},
    {"type": "function", "function": {
        "name": "list_outputs",
        "description": "List recent output files grouped by task.",
        "parameters": {"type": "object", "properties": {}},
    }},
]


@dataclass
class _Ctx:
    db: Session
    project: Project
    user_id: str
    enqueue: object
    current_goal_id: uuid.UUID | None = None
    actions: list = field(default_factory=list)
    # 디스패치/재개로 만든 task id들 — DB 커밋 후에 enqueue한다(워커 레이스 방지, BUG-5).
    to_enqueue: list = field(default_factory=list)


def _find_agent(ctx: _Ctx, name: str) -> Agent | None:
    return (
        ctx.db.query(Agent)
        .filter(Agent.project_id == ctx.project.id, Agent.name.ilike(name))
        .first()
    )


# --- 도구 실행 ---


def _tool_create_goal(ctx: _Ctx, args: dict) -> dict:
    """[지휘자 도구] 목표 만들기 — 이번 지시로 생길 작업들을 묶을 '목표' 하나를 보드에 만든다.

    무슨 일을 하나: goals 테이블에 목표 1줄을 추가한다. 이후 같은 턴에서 만들어지는 작업들이
        이 목표에 자동으로 묶인다(보드 화면 = 목표 × 작업). 누가 부르나: run_chat 툴루프.
    """
    goal = Goal(project_id=ctx.project.id, title=args.get("title", "Goal"))
    ctx.db.add(goal); ctx.db.flush()
    ctx.current_goal_id = goal.id
    ctx.actions.append({"action": "create_goal", "goal_id": str(goal.id), "title": goal.title})
    return {"goal_id": str(goal.id)}


def _tool_dispatch_task(ctx: _Ctx, args: dict) -> dict:
    """[지휘자 도구] 작업 던지기 — 에이전트 한 명에게 할 일을 줘서 작업 큐에 올린다.

    무슨 일을 하나: 지휘자(LLM)가 "이 사람한테 이 일 시켜" 라고 결정하면 호출된다.
        지목된 에이전트를 이름으로 찾아 task(작업 1건)를 만들고 큐에 넣는다(= 디스패치).
    누가 부르나: run_chat의 툴루프 안에서 LLM이 dispatch_task 도구를 고를 때 _execute가 부른다.
    처리 순서:
        1. _find_agent: 이름으로 에이전트를 찾는다. 없으면 에러를 돌려주고 지휘자가 다시 판단.
        2. override_to_agent_name이 있으면 "이번 한 번만" 다른 사람에게 보내는 우회로 설정(D21).
           — 저장된 연결선(엣지)은 바꾸지 않는다. 일회성 라우팅.
        3. ts.create_task: tasks 테이블에 'queued'(대기) 상태로 작업을 만든다.
        4. ctx.enqueue: 백그라운드 워커(Celery)에게 "이 작업 처리해" 라고 큐에 올린다.
    연결: 만든 작업을 실제로 처리하는 곳 → process_task (backend/app/services/worker_core.py).
        작업 생성 규칙 → create_task (backend/app/services/task_service.py).
    """
    agent = _find_agent(ctx, args.get("agent_name", ""))
    if agent is None:
        return {"error": f"no agent named '{args.get('agent_name')}'"}
    override = None
    ov_name = args.get("override_to_agent_name")
    if ov_name:
        ov = _find_agent(ctx, ov_name)
        if ov is None:
            return {"error": f"no override agent named '{ov_name}'"}
        override = {"to_agent_id": str(ov.id)}
    task = ts.create_task(
        ctx.db, user_id=ctx.user_id, project_id=ctx.project.id, agent=agent,
        instructions=args.get("instructions", ""), origin="chat", goal_id=ctx.current_goal_id,
    )
    if override:
        task.override_route = override
    ctx.db.flush()
    ctx.to_enqueue.append(task.id)  # 커밋 후 run_chat이 enqueue(워커가 미커밋 task를 집어 not_found 내는 레이스 방지)
    ctx.actions.append({"action": "dispatch_task", "task_id": str(task.id), "agent": agent.name})
    return {"task_id": str(task.id), "agent": agent.name, "status": "queued"}


def _tool_get_project_status(ctx: _Ctx, args: dict) -> dict:
    """[지휘자 도구] 현황 조회 — 모든 에이전트의 현재 상태를 DB 기준으로 정확히 읽어온다.

    무슨 일을 하나: "지금 누가 뭐 하고 있어?" 류 질문에 지휘자가 추측하지 않고 사실대로 답하도록,
        에이전트별 상태(idle/working/blocked 등)를 DB에서 그대로 가져온다(권위는 항상 DB).
    누가 부르나: run_chat 툴루프. 연결: 상태 계산 → agent_status_map (backend/app/status_util.py).
    """
    status_by = agent_status_map(ctx.db, ctx.project.id)
    agents = ctx.db.query(Agent).filter(Agent.project_id == ctx.project.id).all()
    return {"agents": [{"name": a.name, "status": status_by.get(a.id, "idle")} for a in agents]}


def _tool_resume_task(ctx: _Ctx, args: dict) -> dict:
    """[지휘자 도구] 멈춘 작업 재개 — 질문하느라 멈춘 에이전트에게 답을 주고 다시 일하게 한다.

    무슨 일을 하나: 어떤 에이전트가 "이거 어떻게 할까요?" 하고 멈춰(blocked/needs-input) 있을 때,
        사용자가 채팅으로 답을 주면 그 답을 작업에 넣어주고 다시 큐에 올려 이어서 일하게 한다.
    누가 부르나: run_chat 툴루프 안에서 LLM이 resume_task 도구를 고를 때.
    처리 순서:
        1. 그 에이전트의 작업 중 'blocked' 또는 'needs-input'(입력 대기) 상태인 가장 최근 것을 찾는다.
        2. ts.request_continue: 사용자가 준 입력(답변)을 작업에 붙인다.
        3. ctx.enqueue: 다시 워커 큐에 올려 이어서 처리하게 한다.
    연결: 입력을 작업에 붙이는 로직 → request_continue (backend/app/services/task_service.py).
    """
    agent = _find_agent(ctx, args.get("agent_name", ""))
    if agent is None:
        return {"error": f"no agent named '{args.get('agent_name')}'"}
    task = (
        ctx.db.query(Task)
        .filter(Task.agent_id == agent.id, Task.status.in_(("blocked", "needs-input")))
        .order_by(Task.created_at.desc())
        .first()
    )
    if task is None:
        return {"error": f"{agent.name} has no task awaiting input"}
    ts.request_continue(ctx.db, task, args.get("input", ""), via="chat")
    ctx.db.flush()
    ctx.to_enqueue.append(task.id)  # 커밋 후 run_chat이 enqueue(워커가 미커밋 task를 집어 not_found 내는 레이스 방지)
    ctx.actions.append({"action": "resume_task", "task_id": str(task.id), "agent": agent.name})
    return {"resumed": True, "agent": agent.name}


def _tool_list_outputs(ctx: _Ctx, args: dict) -> dict:
    """[지휘자 도구] 결과물 목록 — 에이전트들이 만들어낸 최근 산출 파일들을 작업별로 묶어 보여준다.

    무슨 일을 하나: "지금까지 뭐 나왔어?" 류 질문에 답하도록 outputs 테이블에서 최근 50개 파일을
        읽어 task별로 묶어 반환한다. 누가 부르나: run_chat 툴루프.
    """
    rows = ctx.db.query(Output).filter(Output.project_id == ctx.project.id).order_by(Output.created_at.desc()).limit(50).all()
    by_task: dict = {}
    for r in rows:
        by_task.setdefault(str(r.task_id), []).append(r.path)
    return {"outputs": [{"task_id": k, "files": v} for k, v in by_task.items()]}


_TOOLS = {
    "create_goal": _tool_create_goal,
    "dispatch_task": _tool_dispatch_task,
    "get_project_status": _tool_get_project_status,
    "resume_task": _tool_resume_task,
    "list_outputs": _tool_list_outputs,
}


def _execute(ctx: _Ctx, call: ToolCall) -> dict:
    """도구 실행 디스패처 — LLM이 고른 도구 이름을 실제 함수에 연결해 실행하고 결과를 돌려준다.

    무슨 일을 하나: _TOOLS 표에서 이름으로 함수를 찾아 호출한다. 도구가 에러를 내도 예외를 삼켜
        {error: ...} 결과로 바꿔주므로, 툴루프가 죽지 않고 LLM이 그 에러를 보고 회복할 수 있다.
    누가 부르나: run_chat 툴루프.
    """
    fn = _TOOLS.get(call.name)
    if fn is None:
        return {"error": f"unknown tool {call.name}"}
    try:
        return fn(ctx, call.args)
    except Exception as exc:  # noqa: BLE001 — 도구 오류를 결과로 환원(루프가 회복).
        log.warning("tool error", extra={"tool": call.name})
        return {"error": f"{type(exc).__name__}: {exc}"}


def _system_prompt(ctx: _Ctx) -> str:
    """지휘자 지침문 작성 — LLM에게 "넌 사무실 지휘자다 + 지금 직원 명단/상태"를 알려주는 글을 만든다.

    무슨 일을 하나: 시스템 프롬프트(LLM의 역할·규칙을 정하는 첫 지시문)를 만든다. 현재 에이전트
        명단과 각자 상태를 넣어줘서, LLM이 누구에게 일을 시킬 수 있는지 알고 판단하게 한다.
    누가 부르나: run_chat이 루프 시작 전에 한 번.
    """
    status_by = agent_status_map(ctx.db, ctx.project.id)
    agents = ctx.db.query(Agent).filter(Agent.project_id == ctx.project.id).all()
    roster = "\n".join(
        f"- {a.name} (status: {status_by.get(a.id, 'idle')})" for a in agents
    ) or "(no agents yet)"
    return (
        "You are the orchestrator of an office-sim of AI agents. The user steers the whole "
        "company through you in freeform chat. Use the tools to create goals and dispatch tasks.\n\n"
        "Rules:\n"
        "- User-drawn edges auto-fire on completion; usually dispatch only the entry agent of a chain.\n"
        "- A chat instruction that routes differently is a ONE-OFF override (override_to_agent_name); "
        "it never changes the saved edges.\n"
        "- Answer status questions from get_project_status (authoritative), never guess.\n"
        "- To answer a blocked/needs-input agent's question, use resume_task.\n"
        "- After acting, reply briefly in plain language describing what you dispatched.\n\n"
        f"Current agents:\n{roster}"
    )


def _load_history(db: Session, project_id: uuid.UUID, limit: int) -> list[dict]:
    """오케스트레이터 대화 이력을 LLM messages 형태로 복원 — 지휘자가 턴을 넘겨도 맥락을 기억하게.

    무슨 일을 하나: orchestrator_messages에서 최근 limit개를 created_at 순으로 읽어,
        role을 LLM 규약(orchestrator→assistant)으로 매핑해 [{"role","content"}, ...]로 반환한다.
        저장은 run_chat이 끝에서 하므로 이 시점엔 '이번 사용자 메시지'는 아직 없다(중복 없음).
    누가 부르나: run_chat이 messages 조립 직전에 한 번.
    """
    if limit <= 0:
        return []
    rows = (
        db.query(OrchestratorMessage)
        .filter(OrchestratorMessage.project_id == project_id)
        .order_by(OrchestratorMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    # 오래된→최신 정렬. 한 턴의 user/orchestrator는 같은 트랜잭션이라 created_at이 동일할 수 있어
    # (PostgreSQL now()=txn 시작시각) 정렬이 비결정적 → user를 우선해 user→assistant 순서를 보장한다
    # (Anthropic은 user로 시작하는 교대 메시지를 요구). created_at desc로 캡한 뒤 여기서 안정 정렬.
    rows.sort(key=lambda m: (m.created_at, 0 if m.role == "user" else 1))
    # 지휘자(assistant) 과거 답변은 대부분 "Dispatched …" 확인 문장이다. 이 '툴 없이 텍스트만
    # 답하는' 패턴을 그대로 재생하면 모델이 이를 모방해 이후 턴에서 dispatch_task 툴을 안 부르고
    # 확인 문장만 내놓는다(자기강화 실패 루프 — 히스토리가 쌓일수록 dispatch가 조용히 죽음).
    # 라이브로 재현+검증됨. 재생 시 중립 마커로 치환해 패턴을 끊는다(user 의도 히스토리는 유지하고,
    # 현재 상태는 어차피 _system_prompt가 제공). user/assistant 교대 형식도 그대로 보존.
    _ASSISTANT_HISTORY = "(Acted on the previous request by calling the tools.)"
    return [
        {
            "role": "assistant" if m.role == "orchestrator" else "user",
            "content": _ASSISTANT_HISTORY if m.role == "orchestrator" else m.content,
        }
        for m in rows
    ]


def run_chat(
    db: Session,
    project_id: uuid.UUID,
    user_id: str,
    message: str,
    *,
    client=None,
    enqueue=None,
    max_iters: int = 8,
    history_limit: int = 20,
) -> dict:
    """지휘자 두뇌 — 사용자의 한 마디를 받아 LLM '툴루프'를 돌려 실제 일을 시키고 답을 만든다.

    이 함수가 제품의 심장이다. 사용자는 자유 문장으로 회사를 지휘하고, 그걸 받아
    "어떤 에이전트에게 무슨 일을 시킬지"를 LLM이 스스로 판단해 실행한다.

    핵심 개념 — 툴루프(LLM이 도구를 부르고, 도구 결과를 다시 LLM에게 보여주고, 다시 판단하길 반복):
        LLM은 직접 DB를 못 만지므로, create_goal·dispatch_task 같은 '도구'만 호출할 수 있다.
        도구를 실행해주고 그 결과를 다시 LLM에게 돌려주면, LLM이 다음 도구를 부르거나 멈추고
        사용자에게 줄 답변 문장을 내놓는다.

    무슨 일을 하나: 사용자 문장 → (도구 호출 ↔ 결과)를 최대 8번 반복 → 마지막에 사람말 답변 생성.
    누가 부르나: chat 엔드포인트 — backend/app/routers/chat.py.
    처리 순서:
        1. _system_prompt: 지금 어떤 에이전트들이 어떤 상태인지를 LLM에게 알려주는 지침 작성.
        2. for 루프(최대 max_iters=8회): client.complete로 LLM 호출.
           - LLM이 도구를 부르면 → _execute로 실행하고 결과를 messages에 추가 → 다시 LLM에게.
           - LLM이 도구 없이 문장만 내놓으면 → 그게 사용자에게 줄 최종 답변. 루프 종료.
        3. 대화 한 쌍(사용자 메시지 + 지휘자 답변)을 orchestrator_messages 테이블에 저장(history용).
        4. {reply: 답변문장, actions: 이번에 실제로 한 일 목록}을 반환.
    연결: 도구 본체들 → 이 파일 위쪽 _tool_dispatch_task / _tool_resume_task 등.
        실제 LLM을 부르는 부분 → 이 파일 맨 아래 LiteLLMClient.complete.
        (client 인자를 주입하면 테스트에선 가짜 LLM으로 라이브 키 없이 전체 흐름 검증 가능)
    """
    project = db.get(Project, project_id)
    if enqueue is None:
        from app.celery_app import enqueue_task as enqueue
    if client is None:
        client = LiteLLMClient(db)

    ctx = _Ctx(db=db, project=project, user_id=user_id, enqueue=enqueue)
    # 과거 대화 이력을 system과 현재 메시지 사이에 끼워, 지휘자가 맥락을 이어가게 한다(stateless 해소).
    history = _load_history(db, project.id, history_limit)
    # Anthropic은 system 다음 첫 메시지가 user여야 한다. limit 절단으로 이력이 assistant로
    # 시작할 수 있으니(턴 중간이 잘림) 선두 assistant를 떨어내 항상 user로 시작하게 한다.
    while history and history[0]["role"] == "assistant":
        history.pop(0)
    messages = [
        {"role": "system", "content": _system_prompt(ctx)},
        *history,
        {"role": "user", "content": message},
    ]

    reply = ""
    for _ in range(max_iters):
        resp = client.complete(messages, TOOL_SCHEMAS)
        if resp.tool_calls:
            messages.append({
                "role": "assistant", "content": None,
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.name, "arguments": json.dumps(c.args)}}
                    for c in resp.tool_calls
                ],
            })
            for c in resp.tool_calls:
                result = _execute(ctx, c)
                messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result)})
            continue
        reply = resp.content or ""
        break

    # 히스토리 영속(유저 + 오케스트레이터 응답).
    db.add(OrchestratorMessage(project_id=project.id, role="user", content=message))
    db.add(OrchestratorMessage(project_id=project.id, role="orchestrator", content=reply))
    db.commit()
    # 커밋 이후에 enqueue — 워커가 트랜잭션 커밋 전 task를 집어 not_found를 내고 task가 영원히
    # queued로 남는 레이스를 막는다(E2E BUG-5). 커밋됐으니 워커가 반드시 task를 본다.
    for tid in ctx.to_enqueue:
        enqueue(tid)
    return {"reply": reply, "actions": ctx.actions}


# --- 프로덕션 LiteLLM 클라이언트 ---


class LiteLLMClient:
    """litellm.completion 호출(프롬프트 캐싱 passthrough, D26/D32). model 미지정 시 strong."""

    def __init__(self, db: Session, model: str | None = None):
        cfg = load_config(db)
        self.model = model or model_for_tier(cfg, "strong")

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        """실제 LLM 1회 호출 — 대화내역+도구목록을 보내고, 도구호출 또는 답변문장을 받아온다.

        무슨 일을 하나: litellm(여러 LLM 제공사를 한 인터페이스로 부르는 라이브러리)로 모델을
            호출한다. 모델이 "도구를 쓰겠다"고 하면 tool_calls를, 그냥 답하면 content를 채워 반환.
        누가 부르나: run_chat의 툴루프가 매 반복마다 부른다.
        연결: 반환된 LLMResponse를 run_chat이 보고 도구 실행 여부를 결정한다.
        """
        from litellm import completion

        # timeout/num_retries 필수 — 없으면 프로바이더 행이 chat 요청/Celery 워커를 무한 점유(감사 P0).
        resp = completion(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            timeout=settings.llm_request_timeout_sec,
            num_retries=settings.llm_num_retries,
        )
        msg = resp.choices[0].message
        tcs = getattr(msg, "tool_calls", None)
        if tcs:
            return LLMResponse(tool_calls=[
                ToolCall(id=tc.id, name=tc.function.name, args=json.loads(tc.function.arguments or "{}"))
                for tc in tcs
            ])
        return LLMResponse(content=msg.content or "")
