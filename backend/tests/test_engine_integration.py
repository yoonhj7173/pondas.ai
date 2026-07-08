"""Engine integration tests (item 18) — LIVE Postgres + Local sandbox, mocked agents.

agent_sdk task가 워크스페이스+dev-runner로 실제 실행되고, cross-engine 핸드오프(dev→text),
SWE↔QA 리뷰루프(실행 위)가 돌고, stop이 실행을 중단+전파 억제, pause가 dev 디스패치를 막는지
검증한다. (E2B+실 Claude는 동일 경로 + 키 필요.)
"""

from __future__ import annotations

import sys
import uuid

import pytest

from app.crews.factory import ScriptedLLM
from app.db import SessionLocal
from app.models import Agent, Edge, Output, Project, Task, Team
from app.services import task_service as ts
from app.services import worker_core
from app.services.orchestrator import LLMResponse, ToolCall
from app.services.sandbox import LocalSandboxProvider
from app.services.workspace import workspace_service
from seed import seed


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    db = SessionLocal()
    try:
        seed(db)
        # 이 모듈은 mock E2B dev 경로를 검증 → 전역 cma 디폴트와 무관하게 e2b로 핀.
        from app.services.config_store import set_config
        set_config(db, "dev_engine", "e2b")
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _local_provider():
    """워크스페이스 싱글턴을 Local 프로바이더로 고정(테스트 격리)."""
    prev = workspace_service.provider
    workspace_service.provider = LocalSandboxProvider()
    yield
    for sid in list(workspace_service.provider._dirs.keys()):
        workspace_service.provider.destroy(sid)
    workspace_service.provider = prev


@pytest.fixture
def env():
    db = SessionLocal()
    uid = f"ei_{uuid.uuid4().hex[:8]}"
    proj = Project(user_id=uid, name="ei")
    db.add(proj); db.flush()
    dev = Team(project_id=proj.id, template_key="development", name="Dev")   # agent_sdk
    plan = Team(project_id=proj.id, template_key="planning", name="Plan")    # crew
    db.add_all([dev, plan]); db.flush()
    swe = Agent(team_id=dev.id, project_id=proj.id, name="SWE", role_instructions="swe", model_tier="strong", slot=0)
    qa = Agent(team_id=dev.id, project_id=proj.id, name="QA", role_instructions="qa", model_tier="medium", slot=1)
    pm = Agent(team_id=plan.id, project_id=proj.id, name="PM", role_instructions="pm", model_tier="strong", slot=0)
    db.add_all([swe, qa, pm]); db.commit()
    yield db, uid, proj.id, swe.id, qa.id, pm.id
    db.delete(db.get(Project, proj.id)); db.commit()
    db.close()


def _queued(db, uid, pid, aid, engine):
    a = db.get(Agent, aid)
    t = ts.create_task(db, user_id=uid, project_id=pid, agent=a, instructions="build login", origin="chat")
    t.engine = engine; db.commit()
    return t.id


def _dev_calls(*steps):
    """ScriptedAgent 빌더 — (write_file/bash/final) 시퀀스."""
    return ScriptedDevAgent(steps)


class ScriptedDevAgent:
    def __init__(self, steps):
        self.steps = list(steps)
        self.i = 0

    def complete(self, messages, tools):
        r = self.steps[self.i]; self.i = min(self.i + 1, len(self.steps) - 1)
        return r


def _tc(cid, name, args):
    return LLMResponse(tool_calls=[ToolCall(id=cid, name=name, args=args)], tokens_in=10, tokens_out=5)


# --- dev task end-to-end ---


def test_dev_task_runs_and_collects_outputs(env):
    db, uid, pid, swe, qa, pm = env
    tid = _queued(db, uid, pid, swe, "agent_sdk")
    py = sys.executable
    agent = _dev_calls(
        _tc("1", "write_file", {"path": "calc.py", "content": "def add(a,b):\n return a+b\n"}),
        _tc("2", "write_file", {"path": "test_calc.py", "content": "from calc import add\n\ndef test():\n assert add(2,3)==5\n"}),
        _tc("3", "bash", {"cmd": f"{py} -m pytest -q"}),
        LLMResponse(content="Done — add() works, test passes.", tokens_in=20, tokens_out=8),
    )
    result = worker_core.process_task(db, tid, dev_client=agent, enqueue=lambda x: None)
    assert result == "done"
    row = db.get(Task, tid)
    assert row.status == "done"
    # verification에 pytest exit 0.
    assert any("pytest" in v["cmd"] and v["exit_code"] == 0 for v in row.verification)
    # 코드 트리가 아웃풋으로 수집됨.
    paths = {o.path for o in db.query(Output).filter_by(task_id=tid).all()}
    assert {"calc.py", "test_calc.py"} <= paths
    # 워크스페이스는 idle이라 pause됨.
    assert db.get(Project, pid).sandbox_status == "paused"


# --- cross-engine handoff (dev → text) ---


def test_cross_engine_handoff_dev_to_text(env):
    db, uid, pid, swe, qa, pm = env
    db.add(Edge(project_id=pid, from_agent_id=swe, to_agent_id=pm, type="handoff"))  # SWE(dev) → PM(text)
    db.commit()
    tid = _queued(db, uid, pid, swe, "agent_sdk")
    collected = []
    dev_agent = _dev_calls(LLMResponse(content="Implemented the API.", tokens_in=15, tokens_out=6))
    worker_core.process_task(db, tid, dev_client=dev_agent, enqueue=lambda x: collected.append(x))
    # PM(text) child가 생성됨.
    assert len(collected) == 1
    pm_task = db.get(Task, collected[0])
    assert pm_task.agent_id == pm and pm_task.engine == "crew"
    assert pm_task.input_payload == "Implemented the API."
    # PM 텍스트 task 실행 → done.
    worker_core.process_task(db, pm_task.id, llm=ScriptedLLM(["PRD drafted from the API."]), enqueue=lambda x: None)
    assert db.get(Task, pm_task.id).status == "done"


# --- SWE <-> QA review loop over real execution ---


def test_review_loop_over_execution_approves(env):
    db, uid, pid, swe, qa, pm = env
    db.add(Edge(project_id=pid, from_agent_id=swe, to_agent_id=qa, type="review_loop", max_iterations=3))
    db.commit()
    tid = _queued(db, uid, pid, swe, "agent_sdk")

    def drive(start):
        queue = [start]; seen = []
        clients = {
            swe: _dev_calls(LLMResponse(content="Implemented feature.", tokens_in=12, tokens_out=4)),
            qa: _dev_calls(LLMResponse(content="Ran it. APPROVED.", tokens_in=12, tokens_out=4)),
        }
        while queue:
            t = queue.pop(0); aid = db.get(Task, t).agent_id
            coll = []
            worker_core.process_task(db, t, dev_client=clients[aid], enqueue=lambda x: coll.append(x))
            seen.append(t); queue.extend(coll)
            if len(seen) > 10: break
        return seen

    seen = drive(tid)
    tasks = db.query(Task).filter_by(project_id=pid).all()
    # SWE 1 + QA 리뷰어 1, 둘 다 done, revision 없음(조기 승인).
    assert len(tasks) == 2 and all(t.status == "done" for t in tasks)
    assert not any((t.loop_state or {}).get("kind") == "revision" for t in tasks)


# --- stop suppresses propagation ---


def test_stop_dev_task_via_api(client, auth, env):
    db, uid, pid, swe, qa, pm = env
    a = db.get(Agent, swe)
    t = ts.create_task(db, user_id=uid, project_id=pid, agent=a, instructions="x", origin="chat")
    t.engine = "agent_sdk"; t.status = "working"; db.commit()
    resp = client.post(f"/api/tasks/{t.id}/stop", headers=auth(uid))
    assert resp.status_code == 204
    db.expire_all()  # stop은 다른 세션에서 커밋됨 — 재조회.
    row = db.get(Task, t.id)
    assert row.status == "failed" and row.stopped is True


def test_retry_failed_task_spawns_new_queued_task(client, auth, env):
    db, uid, pid, swe, qa, pm = env
    a = db.get(Agent, swe)
    t = ts.create_task(db, user_id=uid, project_id=pid, agent=a, instructions="build the widget", origin="chat")
    t.status = "failed"; t.error_summary = "boom"; db.commit()
    resp = client.post(f"/api/tasks/{t.id}/retry", headers=auth(uid))
    assert resp.status_code == 204
    db.expire_all()
    assert db.get(Task, t.id).status == "failed"  # 실패 이력 보존
    fresh = (
        db.query(Task)
        .filter(Task.agent_id == a.id, Task.status == "queued", Task.instructions == "build the widget")
        .order_by(Task.created_at.desc())
        .first()
    )
    assert fresh is not None and fresh.id != t.id  # 같은 지시로 새 큐 작업


def test_retry_rejects_non_failed_task(client, auth, env):
    db, uid, pid, swe, qa, pm = env
    a = db.get(Agent, qa)
    t = ts.create_task(db, user_id=uid, project_id=pid, agent=a, instructions="x", origin="chat")
    db.commit()  # queued
    resp = client.post(f"/api/tasks/{t.id}/retry", headers=auth(uid))
    assert resp.status_code == 409


# --- pause blocks dev dispatch ---


def test_pause_blocks_dev_dispatch(env):
    db, uid, pid, swe, qa, pm = env
    db.get(Project, pid).paused = True
    db.commit()
    tid = _queued(db, uid, pid, swe, "agent_sdk")
    assert worker_core.process_task(db, tid, dev_client=_dev_calls(LLMResponse(content="x")), enqueue=lambda x: None) == "not_dispatched"
    assert db.get(Task, tid).status == "queued"
