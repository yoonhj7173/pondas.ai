"""Stripe 결제 레이어 테스트 (빌링 D46) — 웹훅→원장 매핑 + checkout 세션 파라미터.

Stripe SDK 호출은 monkeypatch(라이브 키 없이). 탑업/구독충전/해지 다운그레이드 + 중복방지 검증.
"""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models import CreditLedger
from app.services import credit_service as cs
from app.services import stripe_service


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


def _uid() -> str:
    return f"pay_{uuid.uuid4().hex[:10]}"


def _evt(etype, obj):
    return {"type": etype, "data": {"object": obj}}


def test_topup_on_payment_checkout(db):
    uid = _uid()
    evt = _evt("checkout.session.completed",
               {"id": "cs_1", "mode": "payment", "metadata": {"user_id": uid, "credits": "1500"}})
    assert stripe_service.handle_event(db, evt) == "topup"
    assert cs.balance(db, uid) == 1500
    assert db.query(CreditLedger).filter_by(user_id=uid, reason="topup").one().stripe_ref == "cs_1"


def test_subscription_checkout_is_ignored(db):
    uid = _uid()
    evt = _evt("checkout.session.completed",
               {"id": "cs_2", "mode": "subscription", "metadata": {"user_id": uid, "credits": "2000"}})
    assert stripe_service.handle_event(db, evt) == "ignored:subscription-checkout"
    assert cs.balance(db, uid) == 0                    # invoice.paid가 처리 → 중복 적립 방지


def test_invoice_paid_refills_subscription(db, monkeypatch):
    uid = _uid()
    monkeypatch.setattr(
        stripe_service.stripe.Subscription, "retrieve",
        lambda sid: {"metadata": {"user_id": uid, "plan": "pro", "credits": "8000"}},
    )
    evt = _evt("invoice.paid", {"id": "in_1", "subscription": "sub_1"})
    assert stripe_service.handle_event(db, evt) == "refill"
    acct = cs.get_or_create_account(db, uid)
    assert acct.plan == "pro" and acct.monthly_allowance == 8000 and acct.balance == 8000


def test_subscription_deleted_downgrades_to_free(db):
    uid = _uid()
    cs.apply_subscription_refill(db, uid, "pro", 8000); db.commit()
    evt = _evt("customer.subscription.deleted", {"id": "sub_1", "metadata": {"user_id": uid}})
    assert stripe_service.handle_event(db, evt) == "downgrade"
    acct = cs.get_or_create_account(db, uid)
    assert acct.plan == "free" and acct.monthly_allowance == 0


def test_unknown_event_ignored(db):
    assert stripe_service.handle_event(db, _evt("payment_intent.created", {})) == "ignored:payment_intent.created"


def test_create_checkout_session_sets_metadata(db, monkeypatch):
    uid = _uid()
    captured = {}

    def fake_create(**params):
        captured.update(params)
        return type("S", (), {"client_secret": "cs_secret_123"})()

    monkeypatch.setattr(stripe_service.stripe.checkout.Session, "create", fake_create)

    # 탑업: session metadata에 user_id/credits.
    secret = stripe_service.create_checkout_session(db, uid, "pack_m", "https://x/return")
    assert secret == "cs_secret_123"
    assert captured["mode"] == "payment"
    assert captured["metadata"] == {"user_id": uid, "credits": "1500"}
    assert captured["line_items"][0]["price"].startswith("price_")

    # 구독: subscription_data.metadata에 plan/credits.
    stripe_service.create_checkout_session(db, uid, "pro", "https://x/return")
    assert captured["mode"] == "subscription"
    assert captured["subscription_data"]["metadata"]["plan"] == "pro"
    assert captured["subscription_data"]["metadata"]["credits"] == "8000"
