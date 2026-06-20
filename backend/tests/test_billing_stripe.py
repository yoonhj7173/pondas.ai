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


def test_invoice_paid_refills_subscription(db):
    # Stripe 신버전 구조: parent.subscription_details.metadata에서 직접 읽는다(retrieve 불필요).
    uid = _uid()
    evt = _evt("invoice.paid", {
        "id": "in_1", "customer": "cus_x",
        "parent": {"subscription_details": {
            "subscription": "sub_1",
            "metadata": {"user_id": uid, "plan": "pro", "credits": "8000"},
        }},
    })
    assert stripe_service.handle_event(db, evt) == "refill"
    acct = cs.get_or_create_account(db, uid)
    assert acct.plan == "pro" and acct.monthly_allowance == 8000 and acct.balance == 8000
    assert acct.stripe_customer_id == "cus_x"


def test_invoice_paid_legacy_subscription_field(db, monkeypatch):
    # 구버전 폴백: parent 없으면 invoice.subscription + Subscription.retrieve.
    uid = _uid()
    monkeypatch.setattr(
        stripe_service.stripe.Subscription, "retrieve",
        lambda sid: {"metadata": {"user_id": uid, "plan": "starter", "credits": "2000"}},
    )
    evt = _evt("invoice.paid", {"id": "in_2", "subscription": "sub_2"})
    assert stripe_service.handle_event(db, evt) == "refill"
    assert cs.get_or_create_account(db, uid).plan == "starter"


def test_subscription_deleted_downgrades_to_free(db):
    uid = _uid()
    cs.apply_subscription_refill(db, uid, "pro", 8000); db.commit()
    evt = _evt("customer.subscription.deleted", {"id": "sub_1", "metadata": {"user_id": uid}})
    assert stripe_service.handle_event(db, evt) == "downgrade"
    acct = cs.get_or_create_account(db, uid)
    assert acct.plan == "free" and acct.monthly_allowance == 0


def test_unknown_event_ignored(db):
    assert stripe_service.handle_event(db, _evt("payment_intent.created", {})) == "ignored:payment_intent.created"


def test_customer_id_captured_on_checkout(db):
    uid = _uid()
    evt = _evt("checkout.session.completed",
               {"id": "cs_3", "mode": "payment", "customer": "cus_abc",
                "metadata": {"user_id": uid, "credits": "500"}})
    stripe_service.handle_event(db, evt)
    acct = cs.get_or_create_account(db, uid)
    assert acct.stripe_customer_id == "cus_abc" and acct.balance == 500


def test_portal_session_created(db, monkeypatch):
    uid = _uid()
    acct = cs.get_or_create_account(db, uid)
    acct.stripe_customer_id = "cus_xyz"; db.commit()
    monkeypatch.setattr(
        stripe_service.stripe.billing_portal.Session, "create",
        lambda customer, return_url: type("S", (), {"url": "https://portal/x"})(),
    )
    assert stripe_service.create_portal_session(db, uid, "https://back") == "https://portal/x"


def test_portal_without_customer_raises(db):
    uid = _uid()
    with pytest.raises(ValueError):
        stripe_service.create_portal_session(db, uid, "https://back")


def test_billing_summary_endpoint(client, auth):
    uid = _uid()
    # 계정 없을 때 기본값(생성 안 함).
    r = client.get("/billing/summary", headers=auth(uid))
    assert r.status_code == 200
    assert r.json() == {"balance": 0, "plan": "free", "monthly_allowance": 0}
    # 탑업 후 반영.
    s = SessionLocal()
    cs.topup(s, uid, 500); s.commit(); s.close()
    assert client.get("/billing/summary", headers=auth(uid)).json()["balance"] == 500


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
