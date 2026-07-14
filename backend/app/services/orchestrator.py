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
    # 프롬프트 캐시 관측(비용 최적화) — 히트율이 안 보이면 최적화가 됐는지 알 수 없다.
    tokens_cache_read: int = 0
    tokens_cache_write: int = 0


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


# 지휘자 규칙(안정 프리픽스) — 매 턴 동일한 부분만 모아 cache_control 대상이 된다.
# 로스터(에이전트 상태)는 턴마다 변해서 여기 넣으면 캐시가 매번 깨진다 → 별도 블록으로 분리.
_SYSTEM_RULES = (
    "You are the orchestrator of an office-sim of AI agents. The user steers the whole "
    "company through you in freeform chat. Use the tools to create goals and dispatch tasks.\n\n"
    "Rules:\n"
    "- User-drawn edges auto-fire on completion; usually dispatch only the entry agent of a chain.\n"
    "- A chat instruction that routes differently is a ONE-OFF override (override_to_agent_name); "
    "it never changes the saved edges.\n"
    "- Answer status questions from get_project_status (authoritative), never guess.\n"
    "- To answer a blocked/needs-input agent's question, use resume_task.\n"
    "- After acting, reply briefly in plain language describing what you dispatched."
)


def _roster_block(ctx: _Ctx) -> str:
    """현재 에이전트 명단+상태(가변) — 캐시 breakpoint 뒤에 붙는 블록."""
    status_by = agent_status_map(ctx.db, ctx.project.id)
    agents = ctx.db.query(Agent).filter(Agent.project_id == ctx.project.id).all()
    roster = "\n".join(
        f"- {a.name} (status: {status_by.get(a.id, 'idle')})" for a in agents
    ) or "(no agents yet)"
    return f"Current agents:\n{roster}"


def _system_prompt(ctx: _Ctx) -> str:
    """지휘자 지침문(규칙+로스터 합본) — 캐싱이 필요 없는 곳(테스트/단순 호출)용 평문 버전."""
    return _SYSTEM_RULES + "\n\n" + _roster_block(ctx)


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
    #
    # 단, 완전 무기억 마커는 부작용이 있다(QA-05): "디자이너 누가 시켰어?"에 지휘자가 "저는 시킨 적
    # 없다"고 답하는 가스라이팅. 그래서 그 턴의 행동 요약(actions)을 마커 안에 사실로 남긴다 —
    # 여전히 괄호 마커(자연어 답변 아님)라 텍스트-만-답하는 패턴은 재생하지 않는다.
    return [
        {
            "role": "assistant" if m.role == "orchestrator" else "user",
            "content": _history_marker(m) if m.role == "orchestrator" else m.content,
        }
        for m in rows
    ]


_ASSISTANT_HISTORY = "(Acted on the previous request by calling the tools.)"


def _history_marker(m: OrchestratorMessage) -> str:
    """지휘자 과거 턴의 중립 마커 — 행동 요약이 있으면 사실로 포함(기억 유지, QA-05)."""
    if not m.actions:
        return _ASSISTANT_HISTORY
    try:
        acts = json.loads(m.actions)
        parts = [_action_line(a) for a in acts[:5]]
        parts = [p for p in parts if p]
        if not parts:
            return _ASSISTANT_HISTORY
        return f"(Acted by calling tools: {'; '.join(parts)}.)"
    except Exception:  # noqa: BLE001 — 요약 파싱 실패는 기존 마커로 폴백
        return _ASSISTANT_HISTORY


def _action_line(a: dict) -> str:
    kind = a.get("action", "")
    if kind == "dispatch_task":
        return f"dispatched a task to {a.get('agent', 'an agent')}"
    if kind == "resume_task":
        return f"resumed {a.get('agent', 'an agent')}'s task with user input"
    if kind == "create_goal":
        return f"created goal '{a.get('title', '')}'"
    return kind


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
        # 캐싱 필수(비용) — 매 턴 시스템 규칙+툴스키마+히스토리 전액 재전송이 무캐시로 나가면
        # 오케 챗이 토큰을 가장 빨리 태우는 경로가 된다(strong 티어 × 툴루프 최대 8회).
        # max_tokens: 지휘자 답변은 짧은 확인/브리핑 — 텍스트 에이전트와 동일 상한.
        client = LiteLLMClient(db, cache=True, max_tokens=settings.text_agent_max_tokens)

    ctx = _Ctx(db=db, project=project, user_id=user_id, enqueue=enqueue)
    # 과거 대화 이력을 system과 현재 메시지 사이에 끼워, 지휘자가 맥락을 이어가게 한다(stateless 해소).
    history = _load_history(db, project.id, history_limit)
    # Anthropic은 system 다음 첫 메시지가 user여야 한다. limit 절단으로 이력이 assistant로
    # 시작할 수 있으니(턴 중간이 잘림) 선두 assistant를 떨어내 항상 user로 시작하게 한다.
    while history and history[0]["role"] == "assistant":
        history.pop(0)
    messages = [
        # system을 [안정 규칙(cache_control), 가변 로스터] 2블록으로 분리 — 로스터가 턴마다
        # 바뀌어도 규칙+툴스키마 프리픽스는 캐시 히트. (_inject_cache_control은 문자열 content만
        # 감싸므로 이 블록 구조를 건드리지 않고, rolling breakpoint만 마지막 메시지에 붙인다.)
        {"role": "system", "content": [
            {"type": "text", "text": _SYSTEM_RULES, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": _roster_block(ctx)},
        ]},
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

    # 히스토리 영속(유저 + 오케스트레이터 응답). 행동 요약(actions)도 저장 — 다음 턴에서
    # 지휘자가 "내가 뭘 했는지"를 기억하게(QA-05, _history_marker).
    db.add(OrchestratorMessage(project_id=project.id, role="user", content=message))
    db.add(OrchestratorMessage(
        project_id=project.id, role="orchestrator", content=reply,
        actions=json.dumps(ctx.actions) if ctx.actions else None,
    ))
    db.commit()
    # 커밋 이후에 enqueue — 워커가 트랜잭션 커밋 전 task를 집어 not_found를 내고 task가 영원히
    # queued로 남는 레이스를 막는다(E2E BUG-5). 커밋됐으니 워커가 반드시 task를 본다.
    for tid in ctx.to_enqueue:
        enqueue(tid)
    return {"reply": reply, "actions": ctx.actions}


# --- 프로덕션 LiteLLM 클라이언트 ---


def _inject_cache_control(messages: list[dict]) -> list[dict]:
    """프롬프트 캐싱 breakpoint 주입(D26/D32) — dev 툴루프의 반복 재처리 비용 제거.

    Anthropic 정규 순서(tools → system → messages)에서 cache_control은 그 지점까지의 프리픽스를
    캐시한다. ① system 블록(=tools+system 프리픽스: 역할지침+도구스키마, 매 턴 동일) ②
    마지막 문자열-content 메시지(=누적 대화 프리픽스, rolling). 2 breakpoint로 스텝이 쌓여도
    직전까지의 히스토리를 캐시 히트시켜 매 턴 통짜 재처리를 없앤다. content가 None인 assistant
    tool_call 메시지는 건드리지 않는다.
    """
    out = [dict(m) for m in messages]
    for m in out:  # system(있으면 하나)
        if m.get("role") == "system" and isinstance(m.get("content"), str):
            m["content"] = [{"type": "text", "text": m["content"], "cache_control": {"type": "ephemeral"}}]
            break
    for m in reversed(out):  # rolling: 마지막 문자열 content
        if isinstance(m.get("content"), str) and m["content"]:
            m["content"] = [{"type": "text", "text": m["content"], "cache_control": {"type": "ephemeral"}}]
            break
    return out


def _usage_tokens(usage) -> tuple[int, int, int, int]:
    """litellm usage 객체 → (in, out, cache_read, cache_write). 없으면 0들.

    E2B dev 경로가 여태 usage를 안 읽어 태스크 토큰/비용이 전부 0으로 기록됐다(COGS 깜깜이).
    cache_read/write는 캐시 히트율 관측용 — litellm은 Anthropic의 cache_read_input_tokens/
    cache_creation_input_tokens를 usage에 그대로 싣고, OpenAI 규격 미러(prompt_tokens_details
    .cached_tokens)도 채운다. 둘 다 시도한다.
    """
    if usage is None:
        return 0, 0, 0, 0
    ti = int(getattr(usage, "prompt_tokens", 0) or 0)
    to = int(getattr(usage, "completion_tokens", 0) or 0)
    cr = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cw = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    if not cr:
        det = getattr(usage, "prompt_tokens_details", None)
        cr = int(getattr(det, "cached_tokens", 0) or 0)
    return ti, to, cr, cw


def _parse_tool_calls(raw: list[tuple], truncated: bool) -> list[ToolCall]:
    """(id, name, arguments) 목록을 ToolCall로 파싱한다.

    truncated(finish_reason=="length")면 max_tokens에서 응답이 잘린 것 — 마지막 tool-call의
    arguments가 불완전 JSON일 수 있다. 이때 파싱 실패한 콜만 버리고 완성된 콜은 살린다
    (태스크 전체 실패 대신 다음 턴에서 이어감). 잘리지 않았는데 JSON이 깨졌다면 예상 밖
    손상이므로 그대로 예외를 올린다(숨기면 안 되는 버그).
    """
    calls: list[ToolCall] = []
    for tc_id, name, args_raw in raw:
        try:
            args = json.loads(args_raw or "{}")
        except ValueError:
            if truncated:
                continue  # 잘려서 불완전한 마지막 콜 — 완성된 것만 적용
            raise
        calls.append(ToolCall(id=tc_id, name=name, args=args))
    if not calls and raw and truncated:
        # 완성된 콜이 하나도 없이 잘림 — 빈 content로 "done" 처리되는 것보다 명확한 실패가 낫다.
        raise ValueError("LLM output truncated at max_tokens before any complete tool call")
    return calls


class LiteLLMClient:
    """litellm.completion 호출(프롬프트 캐싱 passthrough, D26/D32). model 미지정 시 strong.

    stream/cache는 dev·design 러너 전용 플래그(성능) — 오케스트레이터 챗은 기본값(off)으로 무변경.
    - cache=True: 프롬프트 캐싱 breakpoint 주입 → 긴 툴루프의 매 턴 컨텍스트 재처리 제거.
    - stream=True: 스트리밍 호출 + stream_chunk_builder로 재조립 → 긴 파일 생성이 per-attempt
      타임아웃(120s)에 걸려 재시도로 낭비되던 것 방지 + TTFT 단축.
    """

    def __init__(self, db: Session, model: str | None = None, *, stream: bool = False,
                 cache: bool = False, max_tokens: int | None = None):
        cfg = load_config(db)
        self.model = model or model_for_tier(cfg, "strong")
        self.stream = stream
        self.cache = cache
        # dev/design 전용 출력 상한. None(오케 챗)이면 litellm 기본 캡 유지 — 챗은 짧아서 무관.
        # 미지정 캡에 큰 파일 생성이 걸리면 마지막 tool-call arguments가 잘려 invalid JSON이 됐다.
        self.max_tokens = max_tokens

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        """실제 LLM 1회 호출 — 대화내역+도구목록을 보내고, 도구호출 또는 답변문장을 받아온다.

        무슨 일을 하나: litellm(여러 LLM 제공사를 한 인터페이스로 부르는 라이브러리)로 모델을
            호출한다. 모델이 "도구를 쓰겠다"고 하면 tool_calls를, 그냥 답하면 content를 채워 반환.
        누가 부르나: run_chat의 툴루프 / dev_runner의 코딩루프가 매 반복마다 부른다.
        연결: 반환된 LLMResponse를 호출부가 보고 도구 실행 여부를 결정한다.
        """
        from litellm import completion

        # timeout/num_retries 필수 — 없으면 프로바이더 행이 chat 요청/Celery 워커를 무한 점유(감사 P0).
        kwargs = dict(
            model=self.model,
            messages=_inject_cache_control(messages) if self.cache else messages,
            tools=tools,
            tool_choice="auto",
            timeout=settings.llm_request_timeout_sec,
            num_retries=settings.llm_num_retries,
        )
        if self.max_tokens is not None:
            # 미지정 시 litellm이 Anthropic 기본 저용량 캡 적용 → 큰 파일 생성 턴이 중간에 잘려
            # 마지막 tool-call arguments가 invalid JSON("Expecting ',' delimiter")이 됐다(근본 원인).
            kwargs["max_tokens"] = self.max_tokens
        if self.stream:
            # 스트리밍: 청크를 직접 재조립한다. litellm.stream_chunk_builder는 tool_call arguments
            # 조각을 합칠 때 JSON을 깨뜨려("Expecting ',' delimiter") json.loads가 터졌다(실사례).
            # Anthropic은 arguments 조각들의 단순 연결이 유효한 JSON임을 보장하므로, index별로
            # 직접 이어 붙이면 파싱 위험이 비스트리밍과 동일해진다.
            # include_usage 필수 — 없으면 스트림 청크에 usage가 안 실려 토큰 집계가 0이 된다(실측).
            out = self._collect_stream(list(completion(
                **kwargs, stream=True, stream_options={"include_usage": True})))
            self._log_usage(out)
            return out
        resp = completion(**kwargs)
        choice = resp.choices[0]
        msg = choice.message
        ti, to, cr, cw = _usage_tokens(getattr(resp, "usage", None))
        tcs = getattr(msg, "tool_calls", None)
        if tcs:
            truncated = getattr(choice, "finish_reason", None) == "length"
            calls = _parse_tool_calls(
                [(tc.id, tc.function.name, tc.function.arguments) for tc in tcs], truncated
            )
            if calls:
                out = LLMResponse(tool_calls=calls, tokens_in=ti, tokens_out=to,
                                  tokens_cache_read=cr, tokens_cache_write=cw)
                self._log_usage(out)
                return out
        out = LLMResponse(content=msg.content or "", tokens_in=ti, tokens_out=to,
                          tokens_cache_read=cr, tokens_cache_write=cw)
        self._log_usage(out)
        return out

    def _log_usage(self, resp: LLMResponse) -> None:
        """호출 1건의 토큰/캐시 사용량 로그 — railway 로그로 캐시 히트율·비용을 실측 가능하게."""
        log.info(
            "llm usage model=%s in=%d out=%d cache_read=%d cache_write=%d",
            self.model, resp.tokens_in, resp.tokens_out,
            resp.tokens_cache_read, resp.tokens_cache_write,
        )

    @staticmethod
    def _collect_stream(chunks: list) -> LLMResponse:
        """스트리밍 청크를 직접 재조립 — content는 이어 붙이고, tool_call은 index별로
        id/name/arguments 조각을 모은 뒤 arguments를 마지막에 한 번만 json.loads 한다.
        (litellm.stream_chunk_builder의 tool-call 재조립 버그 회피.)
        """
        content_parts: list[str] = []
        frags: dict[int, dict] = {}  # index -> {"id","name","args"}
        finish_reason = None
        usage = None  # Anthropic 스트림은 마지막 청크에 usage를 싣는다 — 마지막 non-None을 취함.
        for ch in chunks:
            u = getattr(ch, "usage", None)
            if u is not None:
                usage = u
            choices = getattr(ch, "choices", None)
            if not choices:
                continue
            if getattr(choices[0], "finish_reason", None):
                finish_reason = choices[0].finish_reason
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue
            if getattr(delta, "content", None):
                content_parts.append(delta.content)
            for tc in (getattr(delta, "tool_calls", None) or []):
                idx = getattr(tc, "index", 0) or 0
                slot = frags.setdefault(idx, {"id": None, "name": None, "args": ""})
                if getattr(tc, "id", None):
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["args"] += fn.arguments
        ti, to, cr, cw = _usage_tokens(usage)
        calls = _parse_tool_calls(
            [(f["id"] or "", f["name"], f["args"]) for _, f in sorted(frags.items()) if f["name"]],
            truncated=finish_reason == "length",
        )
        if calls:
            return LLMResponse(tool_calls=calls, tokens_in=ti, tokens_out=to,
                               tokens_cache_read=cr, tokens_cache_write=cw)
        return LLMResponse(content="".join(content_parts), tokens_in=ti, tokens_out=to,
                           tokens_cache_read=cr, tokens_cache_write=cw)
