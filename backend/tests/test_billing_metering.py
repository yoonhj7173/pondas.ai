"""크레딧 미터링 훅 테스트 (빌링 D46) — billing_enabled ON 경로 + OFF 무과금.

등급가중 차감, 잔액부족→blocked(페이월, 컴퓨트 안 태움), 시스템실패(크래시)→환불, OFF면 무과금.
billing_on 픽스처는 config를 켰다가 teardown에서 반드시 끈다(전역 config 누수 방지).
"""

from __future__ import annotations

import uuid

import pytest

from app.crews.factory import ScriptedLLM
from app.db import SessionLocal
from app.models import Agent, Project, Task, Team
from app.services import credit_service as cs
from app.services import task_service as ts
from app.services import worker_core
from app.services.config_store import set_config
from seed import seed


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


@pytest.fixture
def billing_on():
    db = SessionLocal()
    set_config(db, "billing_enabled", "true"); db.commit()
    yield
    set_config(db, "billing_enabled", "false"); db.commit()
    db.close()


@pytest.fixture
def env():
    db = SessionLocal()
    uid = f"bill_{uuid.uuid4().hex[:8]}"
    proj = Project(user_id=uid, name="b"); db.add(proj); db.flush()
    team = Team(project_id=proj.id, template_key="planning", name="Planning")  # crew
    db.add(team); db.flush()
    agent = Agent(team_id=team.id, project_id=proj.id, name="PM",
                  role_instructions="You are a PM.", model_tier="medium", slot=0)
    db.add(agent); db.commit()
    yield db, uid, proj.id, agent.id
    db.delete(db.get(Project, proj.id)); db.commit()
    db.close()


def _queued(db, uid, pid, aid) -> uuid.UUID:
    agent = db.get(Agent, aid)
    t = ts.create_task(db, user_id=uid, project_id=pid, agent=agent, instructions="Summarize.", origin="chat")
    db.commit()
    return t.id


def test_charge_on_successful_task(env, billing_on):
    db, uid, pid, aid = env
    cs.grant_signup(db, uid, 1000); db.commit()
    tid = _queued(db, uid, pid, aid)
    assert worker_core.process_task(db, tid, llm=ScriptedLLM(["done summary."])) == "done"
    assert cs.balance(db, uid) == 1000 - cs.credit_cost("medium")


def test_insufficient_blocks_and_skips_run(env, billing_on, monkeypatch):
    db, uid, pid, aid = env
    cs.grant_signup(db, uid, 5); db.commit()          # < medium cost, cap ON 기본
    paywalls = []
    monkeypatch.setattr(worker_core.events, "emit_paywall", lambda *a, **k: paywalls.append(a))
    tid = _queued(db, uid, pid, aid)
    assert worker_core.process_task(db, tid, llm=ScriptedLLM(["must not run"])) == "insufficient_credits"
    row = db.get(Task, tid)
    assert row.status == "blocked" and row.result_markdown is None  # 실행 안 됨
    assert cs.balance(db, uid) == 5                    # 차감 없음
    assert paywalls                                    # 페이월 신호 발행됨(자동 모달 D46)


def test_system_failure_refunds(env, billing_on):
    db, uid, pid, aid = env
    cs.grant_signup(db, uid, 1000); db.commit()

    class BoomLLM(ScriptedLLM):
        def complete(self, *a, **k):
            raise RuntimeError("llm boom")

    tid = _queued(db, uid, pid, aid)
    assert worker_core.process_task(db, tid, llm=BoomLLM(["x"])) == "failed"
    assert cs.balance(db, uid) == 1000                 # 차감 후 환불 = 순제로


def test_billing_off_does_not_charge(env):
    db, uid, pid, aid = env                             # billing_on 없음 = OFF(기본)
    cs.grant_signup(db, uid, 1000); db.commit()
    tid = _queued(db, uid, pid, aid)
    assert worker_core.process_task(db, tid, llm=ScriptedLLM(["done."])) == "done"
    assert cs.balance(db, uid) == 1000                 # 무과금
