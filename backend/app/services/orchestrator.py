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


def _find_agent(ctx: _Ctx, name: str) -> Agent | None:
    return (
        ctx.db.query(Agent)
        .filter(Agent.project_id == ctx.project.id, Agent.name.ilike(name))
        .first()
    )


# --- 도구 실행 ---


def _tool_create_goal(ctx: _Ctx, args: dict) -> dict:
    goal = Goal(project_id=ctx.project.id, title=args.get("title", "Goal"))
    ctx.db.add(goal); ctx.db.flush()
    ctx.current_goal_id = goal.id
    ctx.actions.append({"action": "create_goal", "goal_id": str(goal.id), "title": goal.title})
    return {"goal_id": str(goal.id)}


def _tool_dispatch_task(ctx: _Ctx, args: dict) -> dict:
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
    ctx.enqueue(task.id)
    ctx.actions.append({"action": "dispatch_task", "task_id": str(task.id), "agent": agent.name})
    return {"task_id": str(task.id), "agent": agent.name, "status": "queued"}


def _tool_get_project_status(ctx: _Ctx, args: dict) -> dict:
    status_by = agent_status_map(ctx.db, ctx.project.id)
    agents = ctx.db.query(Agent).filter(Agent.project_id == ctx.project.id).all()
    return {"agents": [{"name": a.name, "status": status_by.get(a.id, "idle")} for a in agents]}


def _tool_resume_task(ctx: _Ctx, args: dict) -> dict:
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
    ctx.enqueue(task.id)
    ctx.actions.append({"action": "resume_task", "task_id": str(task.id), "agent": agent.name})
    return {"resumed": True, "agent": agent.name}


def _tool_list_outputs(ctx: _Ctx, args: dict) -> dict:
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
    fn = _TOOLS.get(call.name)
    if fn is None:
        return {"error": f"unknown tool {call.name}"}
    try:
        return fn(ctx, call.args)
    except Exception as exc:  # noqa: BLE001 — 도구 오류를 결과로 환원(루프가 회복).
        log.warning("tool error", extra={"tool": call.name})
        return {"error": f"{type(exc).__name__}: {exc}"}


def _system_prompt(ctx: _Ctx) -> str:
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


def run_chat(
    db: Session,
    project_id: uuid.UUID,
    user_id: str,
    message: str,
    *,
    client=None,
    enqueue=None,
    max_iters: int = 8,
) -> dict:
    """오케스트레이터 툴루프를 1턴 돌리고 {reply, actions}를 반환한다(히스토리 영속)."""
    project = db.get(Project, project_id)
    if enqueue is None:
        from app.celery_app import enqueue_task as enqueue
    if client is None:
        client = LiteLLMClient(db)

    ctx = _Ctx(db=db, project=project, user_id=user_id, enqueue=enqueue)
    messages = [
        {"role": "system", "content": _system_prompt(ctx)},
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
    return {"reply": reply, "actions": ctx.actions}


# --- 프로덕션 LiteLLM 클라이언트 ---


class LiteLLMClient:
    """litellm.completion 호출(프롬프트 캐싱 passthrough, D26/D32). model 미지정 시 strong."""

    def __init__(self, db: Session, model: str | None = None):
        cfg = load_config(db)
        self.model = model or model_for_tier(cfg, "strong")

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        from litellm import completion

        resp = completion(model=self.model, messages=messages, tools=tools, tool_choice="auto")
        msg = resp.choices[0].message
        tcs = getattr(msg, "tool_calls", None)
        if tcs:
            return LLMResponse(tool_calls=[
                ToolCall(id=tc.id, name=tc.function.name, args=json.loads(tc.function.arguments or "{}"))
                for tc in tcs
            ])
        return LLMResponse(content=msg.content or "")
