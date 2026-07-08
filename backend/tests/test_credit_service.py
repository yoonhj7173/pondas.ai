"""크레딧 원장 서비스 테스트 (빌링 D46) — LIVE Postgres.

지갑 lazy 생성, 가입크레딧 멱등, 등급가중 차감, 스펜딩 캡 차단/오버리지, 시스템실패 환불,
그리고 모든 변동이 원장에 balance_after 스냅샷과 함께 남는지 검증한다.
"""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models import CreditAccount, CreditLedger
from app.services import credit_service as cs


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


def _uid() -> str:
    return f"cred_{uuid.uuid4().hex[:10]}"


def test_account_lazy_created_and_zero_balance(db):
    uid = _uid()
    assert cs.balance(db, uid) == 0          # 읽기만으론 생성 안 함
    acct = cs.get_or_create_account(db, uid)
    assert acct.balance == 0 and acct.plan == "free"
    assert acct.spending_cap_enabled is True  # D46 B-6 기본 ON
    assert acct.signup_granted is False


def test_signup_grant_is_idempotent(db):
    uid = _uid()
    assert cs.grant_signup(db, uid, 50) == 50
    # 두 번째는 no-op — 1계정 1회(D46 B-5).
    assert cs.grant_signup(db, uid, 50) == 50
    rows = db.query(CreditLedger).filter_by(user_id=uid, reason="signup_grant").all()
    assert len(rows) == 1 and rows[0].balance_after == 50


def test_signup_credits_cover_north_star_loop(db):
    """D52 — 가입 크레딧이 north-star 루프(D48)를 1회 무료 완주시킨다:
    strong dev task 1회 + 최소 1회의 medium 수정 지시까지 커버."""
    assert cs.SIGNUP_CREDITS == 500
    assert cs.SIGNUP_CREDITS >= cs.TIER_CREDIT_COST["strong"] + cs.TIER_CREDIT_COST["medium"]

    # 실제로 가입 → strong task 1회 차감 후에도 medium 1회 여력이 남는지.
    uid = _uid()
    cs.grant_signup(db, uid, cs.SIGNUP_CREDITS)
    cs.charge_task(db, uid, None, "strong")
    assert cs.balance(db, uid) >= cs.TIER_CREDIT_COST["medium"]


def test_charge_deducts_and_writes_ledger(db):
    uid = _uid()
    cost = cs.credit_cost("medium")
    cs.grant_signup(db, uid, 100)
    after = cs.charge_task(db, uid, None, "medium")
    assert after == 100 - cost
    entry = (
        db.query(CreditLedger)
        .filter_by(user_id=uid, reason="task_charge")
        .one()
    )
    assert entry.delta == -cost and entry.balance_after == 100 - cost


def test_charge_is_grade_weighted(db):
    uid = _uid()
    # 비율 junior < standard < senior (D46 B-1).
    assert cs.credit_cost("light") < cs.credit_cost("medium") < cs.credit_cost("strong")
    cs.grant_signup(db, uid, 1000)
    cs.charge_task(db, uid, None, "strong")
    assert cs.balance(db, uid) == 1000 - cs.credit_cost("strong")


def test_spending_cap_blocks_when_insufficient(db):
    uid = _uid()
    cs.grant_signup(db, uid, 5)                        # < medium cost, cap ON by default
    with pytest.raises(cs.InsufficientCreditsError) as ei:
        cs.charge_task(db, uid, None, "medium")
    assert ei.value.needed == cs.credit_cost("medium") and ei.value.balance == 5
    assert cs.balance(db, uid) == 5                    # 변동 없음(차단)


def test_charge_atomic_guard_exact_balance_and_no_partial_debit(db):
    """캡 가드 원자적 차감(TOCTOU 수정, 감사 P0) — 딱 맞으면 0까지 차감, 부족하면 미차감."""
    uid = _uid()
    cost = cs.credit_cost("medium")
    cs.grant_signup(db, uid, cost)                     # 정확히 1회분
    assert cs.charge_task(db, uid, None, "medium") == 0  # 딱 맞게 차감 → 0
    with pytest.raises(cs.InsufficientCreditsError):
        cs.charge_task(db, uid, None, "medium")        # 0 < cost → 차단
    assert cs.balance(db, uid) == 0                    # 부분 차감 없음(음수 방지)


def test_refund_skips_deleted_account(db):
    """계정삭제된 유저의 task 환불 → 지갑 부활 안 함(감사 P1)."""
    uid = _uid()
    assert cs.refund_task(db, uid, None, 30) == 0     # 계정 없음 → no-op
    assert db.get(CreditAccount, uid) is None          # 부활되지 않음
    # 계정이 있으면 정상 환불(회귀).
    cs.grant_signup(db, uid, 0)
    assert cs.refund_task(db, uid, None, 30) == 30


def test_cap_off_allows_overage(db):
    uid = _uid()
    acct = cs.get_or_create_account(db, uid)
    cs.grant_signup(db, uid, 5)
    acct.spending_cap_enabled = False                  # 후불 허용
    db.flush()
    assert cs.charge_task(db, uid, None, "medium") == 5 - cs.credit_cost("medium")  # 음수 허용


def test_refund_system_failure_adds_back(db):
    uid = _uid()
    cost = cs.credit_cost("medium")
    cs.grant_signup(db, uid, 100)
    cs.charge_task(db, uid, None, "medium")            # −cost
    after = cs.refund_task(db, uid, None, cost)        # +cost → 100
    assert after == 100
    r = db.query(CreditLedger).filter_by(user_id=uid, reason="refund_system_failure").one()
    assert r.delta == cost and r.balance_after == 100


def test_topup_adds_credits_with_stripe_ref(db):
    uid = _uid()
    after = cs.topup(db, uid, 1500, stripe_ref="cs_test_123")
    assert after == 1500
    r = db.query(CreditLedger).filter_by(user_id=uid, reason="topup").one()
    assert r.delta == 1500 and r.stripe_ref == "cs_test_123"


def test_subscription_refill_sets_plan_and_adds_allowance(db):
    uid = _uid()
    after = cs.apply_subscription_refill(db, uid, "pro", 8000, stripe_ref="in_test_1")
    assert after == 8000
    acct = cs.get_or_create_account(db, uid)
    assert acct.plan == "pro" and acct.monthly_allowance == 8000
    r = db.query(CreditLedger).filter_by(user_id=uid, reason="monthly_refill").one()
    assert r.delta == 8000 and r.stripe_ref == "in_test_1"
