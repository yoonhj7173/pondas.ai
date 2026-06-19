"""크레딧 원장 서비스 테스트 (빌링 D46) — LIVE Postgres.

지갑 lazy 생성, 가입크레딧 멱등, 등급가중 차감, 스펜딩 캡 차단/오버리지, 시스템실패 환불,
그리고 모든 변동이 원장에 balance_after 스냅샷과 함께 남는지 검증한다.
"""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models import CreditLedger
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


def test_charge_deducts_and_writes_ledger(db):
    uid = _uid()
    cs.grant_signup(db, uid, 100)
    after = cs.charge_task(db, uid, None, "medium")   # standard = 3
    assert after == 97
    entry = (
        db.query(CreditLedger)
        .filter_by(user_id=uid, reason="task_charge")
        .one()
    )
    assert entry.delta == -3 and entry.balance_after == 97


def test_charge_is_grade_weighted(db):
    uid = _uid()
    cs.grant_signup(db, uid, 100)
    assert cs.credit_cost("light") == 1
    assert cs.credit_cost("medium") == 3
    assert cs.credit_cost("strong") == 30
    cs.charge_task(db, uid, None, "strong")           # senior = 30
    assert cs.balance(db, uid) == 70


def test_spending_cap_blocks_when_insufficient(db):
    uid = _uid()
    cs.grant_signup(db, uid, 2)                        # cap ON by default
    with pytest.raises(cs.InsufficientCreditsError) as ei:
        cs.charge_task(db, uid, None, "medium")        # needs 3
    assert ei.value.needed == 3 and ei.value.balance == 2
    assert cs.balance(db, uid) == 2                    # 변동 없음(차단)


def test_cap_off_allows_overage(db):
    uid = _uid()
    acct = cs.get_or_create_account(db, uid)
    cs.grant_signup(db, uid, 2)
    acct.spending_cap_enabled = False                  # 후불 허용
    db.flush()
    assert cs.charge_task(db, uid, None, "medium") == -1  # 음수 잔액 허용


def test_refund_system_failure_adds_back(db):
    uid = _uid()
    cs.grant_signup(db, uid, 100)
    cs.charge_task(db, uid, None, "medium")            # -3 → 97
    after = cs.refund_task(db, uid, None, 3)           # +3 → 100
    assert after == 100
    r = db.query(CreditLedger).filter_by(user_id=uid, reason="refund_system_failure").one()
    assert r.delta == 3 and r.balance_after == 100
