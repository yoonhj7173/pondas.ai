"""Orchestrator tool-loop tests (item 13) — LIVE Postgres, scripted LLM.

freeform → goal+task 디스패치 + 정확한 reply, status 조회가 DB와 일치, chat-resume(D22)가
needs-input task를 재개, override가 엣지 변경 없이 1회 라우팅을 검증한다.
"""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models import Agent, Edge, Goal, OrchestratorMessage, Project, Task, Team
from app.services import task_service as ts
from app.services.orchestrator import LLMResponse, ToolCall, _load_history, run_chat
from seed import seed


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


@pytest.fixture
def env():
    db = SessionLocal()
    uid = f"o_{uuid.uuid4().hex[:8]}"
    proj = Project(user_id=uid, name="o")
    db.add(proj); db.flush()
    team = Team(project_id=proj.id, template_key="development", name="Development")  # agent_sdk (won't run)
    db.add(team); db.flush()
    swe = Agent(team_id=team.id, project_id=proj.id, name="SWE", role_instructions="swe", model_tier="strong", slot=0)
    qa = Agent(team_id=team.id, project_id=proj.id, name="QA", role_instructions="qa", model_tier="medium", slot=1)
    db.add_all([swe, qa]); db.commit()
    yield db, uid, proj.id, swe.id, qa.id
    db.delete(db.get(Project, proj.id)); db.commit()
    db.close()


class ScriptedClient:
    """미리 정해진 LLMResponse 시퀀스를 순서대로 반환(툴루프 검증용)."""

    def __init__(self, steps: list[LLMResponse]):
        self.steps = list(steps)
        self.i = 0
        self.seen_messages = []

    def complete(self, messages, tools) -> LLMResponse:
        self.seen_messages.append(list(messages))
        resp = self.steps[self.i]
        self.i = min(self.i + 1, len(self.steps) - 1)
        return resp


def _calls(*pairs):
    return LLMResponse(tool_calls=[
        ToolCall(id=f"c{i}", name=name, args=args) for i, (name, args) in enumerate(pairs)
    ])


# --- freeform → goal + dispatch + reply ---


def test_freeform_creates_goal_and_dispatches(env):
    db, uid, pid, swe, qa = env
    collected = []
    client = ScriptedClient([
        _calls(("create_goal", {"title": "Build login"}),
               ("dispatch_task", {"agent_name": "SWE", "instructions": "Implement login"})),
        LLMResponse(content="On it — SWE is implementing login."),
    ])
    result = run_chat(db, pid, uid, "Build a login feature", client=client, enqueue=lambda x: collected.append(x))
    assert "SWE" in result["reply"] or "login" in result["reply"].lower()
    # goal + task 실제 생성.
    assert db.query(Goal).filter_by(project_id=pid).count() == 1
    task = db.query(Task).filter_by(project_id=pid).one()
    assert db.get(Agent, task.agent_id).name == "SWE"
    assert task.goal_id is not None  # goal에 연결
    assert task.origin == "chat"
    assert len(collected) == 1  # enqueue됨
    # 액션 + 히스토리.
    assert any(a["action"] == "dispatch_task" for a in result["actions"])
    assert db.query(OrchestratorMessage).filter_by(project_id=pid).count() == 2


# --- status query matches DB ---


def test_status_query_matches_db(env):
    db, uid, pid, swe, qa = env
    # SWE에 working task를 직접 만들어 상태를 DB에 박는다.
    swe_agent = db.get(Agent, swe)
    t = ts.create_task(db, user_id=uid, project_id=pid, agent=swe_agent, instructions="x", origin="chat")
    t.status = "working"; db.commit()

    captured = {}

    class StatusClient:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return _calls(("get_project_status", {}))
            # 두 번째 호출의 직전 tool 결과를 캡처.
            captured["last_tool"] = messages[-1]["content"]
            return LLMResponse(content="SWE is working; QA is idle.")

    run_chat(db, pid, uid, "status?", client=StatusClient(), enqueue=lambda x: None)
    import json
    status = json.loads(captured["last_tool"])
    smap = {a["name"]: a["status"] for a in status["agents"]}
    assert smap["SWE"] == "working" and smap["QA"] == "idle"


# --- chat resume (D22) ---


def test_chat_resume_continues_needs_input(env):
    db, uid, pid, swe, qa = env
    swe_agent = db.get(Agent, swe)
    t = ts.create_task(db, user_id=uid, project_id=pid, agent=swe_agent, instructions="x", origin="chat")
    t.status = "needs-input"; t.awaiting_prompt = "which DB?"; db.commit()

    collected = []
    client = ScriptedClient([
        _calls(("resume_task", {"agent_name": "SWE", "input": "use Postgres"})),
        LLMResponse(content="Relayed — SWE resumed."),
    ])
    run_chat(db, pid, uid, "tell SWE to use Postgres", client=client, enqueue=lambda x: collected.append(x))
    row = db.get(Task, t.id)
    assert row.status == "queued"          # 재개됨
    assert row.continuations[-1]["text"] == "use Postgres"
    assert row.continuations[-1]["via"] == "chat"
    assert len(collected) == 1


# --- override routes once, edges unchanged (D21) ---


def test_override_routes_once_without_mutating_edges(env):
    db, uid, pid, swe, qa = env
    # 엣지: SWE -> QA(handoff).
    db.add(Edge(project_id=pid, from_agent_id=swe, to_agent_id=qa, type="handoff"))
    db.commit()
    edge_count_before = db.query(Edge).filter_by(project_id=pid).count()

    client = ScriptedClient([
        _calls(("dispatch_task", {"agent_name": "SWE", "instructions": "do X", "override_to_agent_name": "QA"})),
        LLMResponse(content="Dispatched with a one-off route."),
    ])
    run_chat(db, pid, uid, "have SWE do X but send straight to QA", client=client, enqueue=lambda x: None)
    task = db.query(Task).filter_by(project_id=pid).one()
    assert task.override_route == {"to_agent_id": str(qa)}
    # 엣지는 그대로(불변, D21).
    assert db.query(Edge).filter_by(project_id=pid).count() == edge_count_before


# --- history endpoint via run_chat persistence ---


def test_history_neutralizes_assistant_replies(env):
    """재생 히스토리에서 지휘자(assistant) 과거 답변은 중립 마커로 치환 — user 의도는 유지.

    '툴 없이 텍스트만 답하는' 과거 답변을 그대로 재생하면 모델이 이후 턴에서 dispatch 툴을 안 부르는
    자기강화 실패 루프가 생겨서(라이브로 재현됨), assistant content를 재생 시 중립화한다.
    """
    db, uid, pid, swe, qa = env
    db.add_all([
        OrchestratorMessage(project_id=pid, role="user", content="Write taglines"),
        OrchestratorMessage(project_id=pid, role="orchestrator", content="Dispatched the taglines task to the PM."),
    ])
    db.commit()
    hist = _load_history(db, pid, limit=20)
    user_msgs = [m for m in hist if m["role"] == "user"]
    asst_msgs = [m for m in hist if m["role"] == "assistant"]
    assert any(m["content"] == "Write taglines" for m in user_msgs)      # 사용자 의도 그대로
    assert asst_msgs and all("Dispatched" not in m["content"] for m in asst_msgs)  # 확인문장 안 재생
    assert all("tools" in m["content"] for m in asst_msgs)               # 중립 마커


def test_history_persisted(env):
    db, uid, pid, swe, qa = env
    client = ScriptedClient([LLMResponse(content="Hello, how can I help?")])
    run_chat(db, pid, uid, "hi", client=client, enqueue=lambda x: None)
    msgs = db.query(OrchestratorMessage).filter_by(project_id=pid).order_by(OrchestratorMessage.created_at).all()
    assert [m.role for m in msgs] == ["user", "orchestrator"]
    assert msgs[0].content == "hi"


# --- conversational memory: prior turns are restored into the next call's messages ---


def test_history_loaded_into_next_turn(env):
    db, uid, pid, swe, qa = env
    # 첫 턴 — 대화 한 쌍을 남긴다.
    run_chat(db, pid, uid, "remember X", client=ScriptedClient([LLMResponse(content="noted X")]), enqueue=lambda x: None)
    # 둘째 턴 — 직전 대화가 LLM에 전달되는 messages로 복원돼야 한다.
    c2 = ScriptedClient([LLMResponse(content="sure")])
    run_chat(db, pid, uid, "what did I say?", client=c2, enqueue=lambda x: None)
    first_call = c2.seen_messages[0]
    pairs = [(m["role"], m.get("content")) for m in first_call]
    assert ("user", "remember X") in pairs            # 과거 사용자 발화는 그대로
    # 지휘자 과거 답변은 중립 마커로 치환(툴 미호출 학습 방지) — 원문 'noted X'는 재생되지 않는다.
    asst = [c for (r, c) in pairs if r == "assistant"]
    assert asst and all("noted X" not in (c or "") for c in asst)
    assert first_call[0]["role"] == "system"          # 순서: system → 이력 → 현재
    assert first_call[-1] == {"role": "user", "content": "what did I say?"}  # 현재 메시지가 맨 끝(중복 없음)


def test_history_messages_start_with_user(env):
    # 회귀(BUG-4): 한 턴의 user/orchestrator는 같은 트랜잭션이라 created_at이 동일 → 정렬이 비결정적이면
    # 이력이 assistant로 시작해 Anthropic이 거부(500)했다. system 다음 첫 메시지는 항상 user여야 한다.
    db, uid, pid, swe, qa = env
    run_chat(db, pid, uid, "first", client=ScriptedClient([LLMResponse(content="ok reply")]), enqueue=lambda x: None)
    c2 = ScriptedClient([LLMResponse(content="second")])
    run_chat(db, pid, uid, "dispatch please", client=c2, enqueue=lambda x: None)
    msgs = c2.seen_messages[0]
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"                  # 첫 비-system 메시지는 반드시 user
    assert "assistant" in [m["role"] for m in msgs]   # 직전 지휘자 답변 턴은 여전히 포함(내용은 중립화)
    # user/assistant 교대 순서: 첫 user('first')가 첫 assistant 턴보다 앞.
    roles = [m["role"] for m in msgs]
    assert roles.index("user") < roles.index("assistant")


def test_history_limit_zero_disables(env):
    db, uid, pid, swe, qa = env
    run_chat(db, pid, uid, "earlier", client=ScriptedClient([LLMResponse(content="ok")]), enqueue=lambda x: None)
    c2 = ScriptedClient([LLMResponse(content="hi")])
    run_chat(db, pid, uid, "now", client=c2, enqueue=lambda x: None, history_limit=0)
    # limit=0이면 이력 미주입 → system + 현재 메시지뿐.
    assert c2.seen_messages[0] == [
        c2.seen_messages[0][0],
        {"role": "user", "content": "now"},
    ]
    assert c2.seen_messages[0][0]["role"] == "system"
