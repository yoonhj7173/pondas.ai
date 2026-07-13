"""CMA Dev-engine tests (D45). Pure parsers/message run in CI; live smoke is key-gated."""
from __future__ import annotations

import os
import types
import uuid

import pytest

from app.db import SessionLocal
from app.models import Agent, Output, Project, Task, Team, WorkspaceVersion
from app.services import cma
from app.services import cma_engine
from app.services import task_service as ts
from app.services.cma import SESSION_OUTPUT_DIR
from app.services.cma_engine import _build_message
from app.services.config_store import load_config
from seed import seed


def _task(**kw):
    base = dict(input_payload=None, edge_id=None, result_markdown=None,
                continuations=None, instructions="Do X")
    base.update(kw)
    return types.SimpleNamespace(**base)


# --- _build_message ---

def test_build_message_basic():
    msg = _build_message(_task())
    assert "Do X" in msg
    assert SESSION_OUTPUT_DIR in msg          # deliverables 디렉토리 안내.
    assert "AWAITING_INPUT" in msg            # needs-input 센티넬 프로토콜.


def test_build_message_input_and_followups():
    msg = _build_message(_task(input_payload="upstream out", edge_id="e1",
                               continuations=[{"text": "more please"}]))
    assert "upstream out" in msg
    assert "delivered from an upstream agent" in msg
    assert "more please" in msg


# --- 이벤트 파서(cma.py) ---

def test_collect_reply_joins_agent_text():
    events = [
        {"type": "agent.message", "content": [{"type": "text", "text": "hello"}]},
        {"type": "span.model_request_end", "model_usage": {}},
        {"type": "agent.message", "content": [{"type": "text", "text": "world"}]},
    ]
    assert cma._collect_reply(events) == "hello\nworld"


def test_collect_tokens_sums_usage_including_cache():
    events = [
        {"type": "span.model_request_end", "model_usage": {
            "input_tokens": 100, "cache_read_input_tokens": 50,
            "cache_creation_input_tokens": 10, "output_tokens": 20}},
        {"type": "span.model_request_end", "model_usage": {"input_tokens": 5, "output_tokens": 3}},
    ]
    assert cma._collect_tokens(events) == (165, 23)


def test_terminal_idle_end_turn():
    events = [{"type": "session.status_running"},
              {"type": "session.status_idle", "stop_reason": {"type": "end_turn"}}]
    assert cma._terminal(events) == ("idle", "end_turn", [])


def test_terminal_requires_action_carries_event_ids():
    events = [{"type": "session.status_idle",
               "stop_reason": {"type": "requires_action", "event_ids": ["e1"]}}]
    assert cma._terminal(events) == ("idle", "requires_action", ["e1"])


def test_terminal_terminated_and_running():
    assert cma._terminal([{"type": "session.status_terminated"}]) == ("terminated", None, [])
    assert cma._terminal([{"type": "session.status_running"}]) is None
    assert cma._terminal([]) is None


# --- run_dev_task_cma 오케스트레이션(회귀: UnboundLocalError로 전 CMA task 크래시했던 버그) ---


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


@pytest.fixture
def dev_env():
    db = SessionLocal()
    uid = f"cma_{uuid.uuid4().hex[:8]}"
    proj = Project(user_id=uid, name="cma"); db.add(proj); db.flush()
    team = Team(project_id=proj.id, template_key="development", name="Development"); db.add(team); db.flush()
    agent = Agent(team_id=team.id, project_id=proj.id, name="SWE",
                  role_instructions="build", model_tier="strong", slot=0)
    db.add(agent); db.commit()
    yield db, uid, proj.id, agent.id
    db.delete(db.get(Project, proj.id)); db.commit()
    db.close()


def _mock_cma(monkeypatch, reply="Built the Next.js app."):
    """CMA 리소스/클라이언트를 전부 가짜로 — run_dev_task_cma를 라이브 키 없이 done까지 태운다."""
    fake_client = types.SimpleNamespace(
        send_user_message=lambda sid, msg: None,
        poll_until_idle=lambda sid, timeout_sec, on_progress=None, should_stop=None: types.SimpleNamespace(
            status="idle", reply=reply, tokens_in=120, tokens_out=40, stop_reason="end_turn"),
        close=lambda: None,
    )
    monkeypatch.setattr(cma_engine, "CMAClient", lambda: fake_client)
    monkeypatch.setattr(cma_engine, "_ensure_environment", lambda db, cfg, c: "env")
    monkeypatch.setattr(cma_engine, "_ensure_memory_store", lambda db, p, c: "store")
    monkeypatch.setattr(cma_engine, "_ensure_agent", lambda db, a, m, c: None)
    monkeypatch.setattr(cma_engine, "_ensure_session", lambda db, a, e, s, c: "sid")

    def fake_collect(db, task, client, sid):
        db.add(Output(project_id=task.project_id, agent_id=task.agent_id, task_id=task.id,
                      path="app/page.tsx", mime="text/plain", size_bytes=3, content="app"))
        db.commit()
    monkeypatch.setattr(cma_engine, "_collect_outputs", fake_collect)


def test_run_dev_task_cma_reaches_done(dev_env, monkeypatch):
    """전체 CMA dev task를 크래시시켰던 UnboundLocalError('Project')를 잡는 회귀 테스트.

    line 156 `db.get(Project, ...)`가 done 분기의 로컬 import로 shadow돼 터졌었다. 이 테스트는
    run_dev_task_cma를 done까지 태워 그 경로(초반 Project 참조 + 완료 + 버전 스냅샷)를 검증한다.
    """
    db, uid, pid, aid = dev_env
    agent = db.get(Agent, aid)
    task = ts.create_task(db, user_id=uid, project_id=pid, agent=agent,
                          instructions="build app", origin="chat")
    task.status = "working"  # 이미 디스패치된 상태에서 실행.
    db.commit()
    cfg = load_config(db)
    _mock_cma(monkeypatch)

    result = cma_engine.run_dev_task_cma(db, task, agent, "claude-sonnet-5", cfg, lambda x: None)
    assert result == "done"                                  # ← UnboundLocalError면 여기서 터짐.
    assert db.get(Task, task.id).status == "done"
    assert db.query(WorkspaceVersion).filter_by(project_id=pid).count() == 1  # 버전 스냅샷 커팅됨.


# --- 라이브 스모크(키 필요, 토큰 비용) ---

@pytest.mark.skipif(os.getenv("CMA_LIVE") != "1", reason="needs live CMA API + ANTHROPIC_API_KEY")
def test_cma_client_round_trip_live():
    c = cma.CMAClient()
    env = agent = store = sess = None
    try:
        env = c.create_environment("craft-cmatest-env")
        store = c.create_memory_store("craft-cmatest-store", "test")
        agent = c.create_agent("craft-cmatest-agent", "claude-haiku-4-5", "Reply with one word.")
        sess, _ = c.create_session(agent, env, memory_store_id=store)
        c.send_user_message(sess, "Say PONG")
        res = c.poll_until_idle(sess, timeout_sec=120)
        assert res.status == "idle"
        assert res.tokens_in > 0 and res.tokens_out > 0
        assert "PONG" in res.reply.upper()
    finally:
        if sess:
            c.delete_session(sess)
        if agent:
            c.archive_agent(agent)
        if store:
            c._req("DELETE", f"/v1/memory_stores/{store}")
        if env:
            c._req("DELETE", f"/v1/environments/{env}")
        c.close()


# --- Stop 실효성(QA-05a): 폴 루프가 stopped를 감지하고 부분 결과를 들고 나온다 ---


def test_poll_until_idle_returns_stopped(monkeypatch):
    from app.services.cma import CMAClient

    c = CMAClient(api_key="test-key")
    evs = {"data": [
        {"type": "span.model_request_end", "model_usage": {"input_tokens": 70, "output_tokens": 30}},
    ]}
    monkeypatch.setattr(c, "_req", lambda method, path, body=None: evs)
    res = c.poll_until_idle("sess", timeout_sec=60, should_stop=lambda: True)
    assert res.status == "stopped"
    assert (res.tokens_in, res.tokens_out) == (70, 30)  # 중단 시점까지의 부분 토큰
