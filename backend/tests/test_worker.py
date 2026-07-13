"""Worker / CrewAI runner tests (item 10) — LIVE Postgres + Redis, mocked Claude.

process_task 전체 경로(done/needs-input/failed), 게이트 차단, agent_sdk 스텁, 토큰/비용
기록, 메모리 append, usage 이벤트 publish, reaper, Celery 래퍼를 검증한다.

세션 규약: env 픽스처가 단일 세션을 들고, process_task가 내부에서 commit하므로 테스트는
항상 db.get으로 재조회해 최신 상태를 본다(만료 객체 직접 접근 금지).
"""

from __future__ import annotations

import json
import time
import uuid

import pytest

from app.crews.factory import ScriptedLLM
from app.db import SessionLocal, redis_client
from app.models import Agent, AgentMemory, Output, Project, Task, Team
from app.services import task_service as ts
from app.services import worker_core
from app.services.config_store import cost_usd, load_config, model_for_tier
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
    """단일 세션 + user/project/team(crew)/agent 1세트."""
    db = SessionLocal()
    uid = f"w_{uuid.uuid4().hex[:8]}"
    proj = Project(user_id=uid, name="w")
    db.add(proj); db.flush()
    team = Team(project_id=proj.id, template_key="planning", name="Planning")  # crew engine
    db.add(team); db.flush()
    agent = Agent(team_id=team.id, project_id=proj.id, name="PM", role_instructions="You are a PM.", model_tier="strong", slot=0)
    db.add(agent); db.commit()
    pid, aid = proj.id, agent.id
    yield db, uid, pid, aid
    db.delete(db.get(Project, pid)); db.commit()
    db.close()


def _queued(db, uid, pid, aid, instructions="Summarize the goal.", engine=None) -> uuid.UUID:
    agent = db.get(Agent, aid)
    t = ts.create_task(db, user_id=uid, project_id=pid, agent=agent, instructions=instructions, origin="chat")
    if engine:
        t.engine = engine
    db.commit()
    return t.id


# --- crew end-to-end ---


def test_text_task_done_records_tokens_and_output(env):
    db, uid, pid, aid = env
    tid = _queued(db, uid, pid, aid)
    result = worker_core.process_task(db, tid, llm=ScriptedLLM(["The goal is to validate the MVP. Summary complete."]))
    assert result == "done"
    row = db.get(Task, tid)
    assert row.status == "done" and row.result_markdown
    cfg = load_config(db)
    assert row.model_used == model_for_tier(cfg, "strong") == "claude-opus-4-8"
    assert row.tokens_in > 0 and row.tokens_out > 0
    assert float(row.est_cost_usd) == cost_usd(cfg, row.model_used, row.tokens_in, row.tokens_out) > 0
    assert db.query(Output).filter_by(task_id=tid).count() == 1
    mem = db.get(AgentMemory, aid)
    assert mem is not None and mem.content_md.strip() != ""


def test_needs_input_surfaces_sentinel(env):
    db, uid, pid, aid = env
    tid = _queued(db, uid, pid, aid)
    assert worker_core.process_task(db, tid, llm=ScriptedLLM(["AWAITING_INPUT: which market segment?"])) == "needs-input"
    row = db.get(Task, tid)
    assert row.status == "needs-input" and "market segment" in row.awaiting_prompt


def test_crew_exception_fails(env):
    db, uid, pid, aid = env
    tid = _queued(db, uid, pid, aid)

    class BoomLLM(ScriptedLLM):
        def complete(self, *a, **k):
            raise RuntimeError("llm boom")

    assert worker_core.process_task(db, tid, llm=BoomLLM(["x"])) == "failed"
    assert "boom" in db.get(Task, tid).error_summary.lower()


def test_paused_project_not_dispatched(env):
    db, uid, pid, aid = env
    db.get(Project, pid).paused = True
    db.commit()
    tid = _queued(db, uid, pid, aid)
    assert worker_core.process_task(db, tid, llm=ScriptedLLM(["x"])) == "not_dispatched"
    assert db.get(Task, tid).status == "queued"


def test_usage_event_published(env):
    db, uid, pid, aid = env
    pubsub = redis_client.pubsub()
    pubsub.subscribe(f"project:{pid}")
    try:
        tid = _queued(db, uid, pid, aid)
        worker_core.process_task(db, tid, llm=ScriptedLLM(["done summary"]))
        # 채널엔 task_status/notification/usage가 섞여 옴 → usage를 골라 받는다.
        got = None
        deadline = time.time() + 3
        while time.time() < deadline and got is None:
            msg = pubsub.get_message(timeout=1)
            if msg and msg["type"] == "message":
                data = json.loads(msg["data"])
                if data.get("type") == "usage":
                    got = data
        assert got is not None and got["tokens_in"] > 0
    finally:
        pubsub.close()


def test_reaper_fails_stale_working(env):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    db, uid, pid, aid = env
    tid = _queued(db, uid, pid, aid)
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    db.execute(update(Task).where(Task.id == tid).values(status="working", updated_at=old))
    db.commit()
    assert worker_core.reap_stale_tasks(db, older_than_sec=600) >= 1
    row = db.get(Task, tid)
    assert row.status == "failed" and "reaped" in row.error_summary.lower()


def test_reaper_reenqueues_stuck_queued(env, monkeypatch):
    """유실/데드락된 queued task를 재큐잉하되 status는 그대로 두고 fail시키지 않는다(#1 Redis 유실 완화)."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    db, uid, pid, aid = env
    sent: list = []
    monkeypatch.setattr("app.celery_app.enqueue_task", lambda tid: sent.append(tid))
    tid = _queued(db, uid, pid, aid)  # status=queued
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    db.execute(update(Task).where(Task.id == tid).values(updated_at=old))
    db.commit()

    assert worker_core._recover_stuck_queued(db) >= 1
    assert tid in sent                                   # 재큐잉됨
    assert db.get(Task, tid).status == "queued"          # fail 아님 — 그대로 대기


def test_celery_run_task_wrapper(env):
    # Celery 래퍼(자체 세션)를 LLM 없이 검증 — paused 프로젝트 → not_dispatched.
    db, uid, pid, aid = env
    db.get(Project, pid).paused = True
    db.commit()
    tid = _queued(db, uid, pid, aid)
    from app.celery_app import run_task
    assert run_task(str(tid)) == "not_dispatched"


# --- Stop 실효성(QA-05): stopped 러너 결과 → 전이 없이 부분 작업물 보존 ---


def test_stop_preserves_partial_work(env, monkeypatch):
    """유저 Stop 시: 상태는 라우트가 만든 failed+stopped 그대로, 파일·버전·토큰은 보존된다.

    실사례(07-13): 22개 파일을 만들던 디자이너 태스크를 Stop → 전부 증발 + 토큰 0 기록.
    이제 러너가 stopped를 반환하면 collect_outputs + snapshot + 부분 토큰 회계가 돈다.
    """
    from app.services import dev_runner
    from app.models import WorkspaceVersion

    db, uid, pid, aid = env
    tid = _queued(db, uid, pid, aid, instructions="build ui", engine="agent_sdk")

    def fake_run(prompt, provider, sandbox_id, *, client, role_instructions="",
                 task_timeout_sec=0, on_step=None, should_stop=None, on_plan=None):
        # 러너가 일부 작업(파일 1개)을 한 뒤 유저가 Stop 누른 상황 재현.
        provider.write_file(sandbox_id, "app/page.tsx", b"partial work")
        t = db.get(Task, tid)
        ts.stop(db, t)          # Stop 라우트가 하는 일(failed+stopped 전이)
        db.commit()
        return dev_runner.DevOutcome(
            status="stopped", error_summary="Stopped by user",
            verification=[{"cmd": "echo hi", "exit_code": 0, "summary": ""}],
            tokens_in=100, tokens_out=40,
        )

    monkeypatch.setattr("app.services.dev_runner.run_dev_task", fake_run)  # lazy import라 소스 모듈 패치
    result = worker_core.process_task(db, tid, dev_client=object(), enqueue=lambda x: None)
    assert result == "stopped"

    t = db.get(Task, tid)
    db.refresh(t)
    assert t.status == "failed" and t.stopped is True          # 라우트 전이 그대로(재전이 없음)
    assert (t.tokens_in, t.tokens_out) == (100, 40)            # 부분 토큰 회계 보존
    assert t.verification                                      # 검증 로그 보존
    outs = db.query(Output).filter_by(task_id=tid).all()
    assert any(o.path == "app/page.tsx" for o in outs)         # 부분 파일 수집됨
    assert db.query(WorkspaceVersion).filter_by(project_id=pid).count() == 1  # 버전 커팅


def test_plan_persisted_and_emitted(env, monkeypatch):
    """update_plan → tasks.plan 영속 + SSE plan 이벤트(QA-06)."""
    from app.services import dev_runner

    db, uid, pid, aid = env
    tid = _queued(db, uid, pid, aid, instructions="design", engine="agent_sdk")
    plan = [{"title": "Scaffold", "done": True}, {"title": "Screens", "done": False}]

    def fake_run(prompt, provider, sandbox_id, *, client, role_instructions="",
                 task_timeout_sec=0, on_step=None, should_stop=None, on_plan=None):
        on_plan(plan)
        return dev_runner.DevOutcome(status="done", output="ok", tokens_in=10, tokens_out=5)

    monkeypatch.setattr("app.services.dev_runner.run_dev_task", fake_run)
    pubsub = redis_client.pubsub()
    pubsub.subscribe(f"project:{pid}")
    try:
        result = worker_core.process_task(db, tid, dev_client=object(), enqueue=lambda x: None)
        assert result == "done"
        t = db.get(Task, tid); db.refresh(t)
        assert t.plan == plan                                   # 영속
        msgs = []
        for _ in range(20):
            m = pubsub.get_message(timeout=0.2)
            if m and m.get("type") == "message":
                msgs.append(json.loads(m["data"]))
        assert any(e.get("type") == "plan" and e.get("steps") == plan for e in msgs)  # SSE
    finally:
        pubsub.close()
