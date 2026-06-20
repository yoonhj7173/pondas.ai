"""비용·정합성 하드닝(prod 감사 P0) — cost-cap 폴백, CMA 턴 캡, 원자적 잔액 업데이트."""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models import CreditLedger
from app.services import config_store as cstore
from app.services import credit_service as cs


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


def _uid():
    return f"ci_{uuid.uuid4().hex[:10]}"


def _cfg(pricing):
    return cstore.GuardConfig(
        concurrency_cap=3, daily_cost_cap_usd=10.0, goal_chain_budget=25,
        context_token_budget=100000, dev_task_timeout_min=30, sandbox_idle_pause_sec=120,
        dev_engine="cma", cma_environment_id="", billing_enabled=False,
        stripe_prices={}, tier_models={}, model_pricing=pricing,
    )


def test_cost_usd_falls_back_when_pricing_missing():
    # 가격 미설정 모델이면 0이 아니라 보수적 추정 — 아니면 daily_cost_cap이 무력화(P0).
    c = cstore.cost_usd(_cfg({}), "some-unpriced-model", 1_000_000, 1_000_000)
    assert c > 0  # 0이면 캡이 안 걸린다


def test_cost_usd_uses_pricing_when_present():
    cfg = _cfg({"m": {"in": 1.0, "out": 2.0}})
    assert cstore.cost_usd(cfg, "m", 1_000_000, 1_000_000) == round(1.0 + 2.0, 6)


def test_cma_turn_cap_aborts_runaway(monkeypatch):
    from app.services.cma import MAX_MODEL_REQUESTS, CMAClient

    client = CMAClient.__new__(CMAClient)  # __init__(httpx) 우회.
    # 종료 안 되고 모델요청만 상한 초과로 쌓인 세션을 흉내.
    events = [{"type": "span.model_request_end"} for _ in range(MAX_MODEL_REQUESTS + 1)]
    monkeypatch.setattr(client, "_req", lambda *a, **k: {"data": events})
    res = client.poll_until_idle("sess", timeout_sec=999, interval=0)
    assert res.status == "timeout" and res.stop_reason == "turn_cap"


def test_stripe_ref_unique_index_blocks_double_credit(db):
    # 동시 중복적립 DB 차단(감사 P0) — 같은 stripe_ref로 두 번째 +적립 행은 유니크 인덱스가 막는다.
    import sqlalchemy

    uid = _uid()
    ref = f"evt_{uuid.uuid4().hex}"
    cs.topup(db, uid, 100, stripe_ref=ref)  # 첫 적립(flush됨)
    db.add(CreditLedger(user_id=uid, delta=50, reason="topup", balance_after=150, stripe_ref=ref))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db.flush()  # 같은 stripe_ref + delta>0 → 부분 유니크 인덱스 위반
    db.rollback()


def test_credit_post_atomic_balance(db):
    # 원자적 UPDATE 경로 회귀 — 잔액 합산 + balance_after 정확.
    uid = _uid()
    cs.topup(db, uid, 100)
    cs.topup(db, uid, 50)
    assert cs.balance(db, uid) == 150
    last = (
        db.query(CreditLedger).filter_by(user_id=uid)
        .order_by(CreditLedger.balance_after.desc()).first()
    )
    assert last.balance_after == 150
