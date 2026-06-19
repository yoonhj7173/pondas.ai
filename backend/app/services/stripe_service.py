"""Stripe 결제 레이어 (빌링 D46) — Embedded Checkout 세션 생성 + 웹훅 처리.

흐름: 프론트가 product key(starter/pro/studio/pack_*)로 /billing/checkout 호출 → 여기서 Stripe
Checkout 세션(embedded) 생성 → client_secret 반환 → 프론트가 모달 안에서 결제(워크스페이스 안 떠남).
결제 완료/구독 갱신은 Stripe가 /billing/webhook으로 이벤트를 쏘고, 여기서 검증 후 크레딧 원장에 반영.

웹훅 → 원장 매핑:
  checkout.session.completed (mode=payment) → topup           (탑업 팩 구매)
  invoice.paid                              → 구독 월 충전     (apply_subscription_refill)
  customer.subscription.deleted             → plan=free        (해지 다운그레이드)
크레딧/플랜은 결제 시점에 우리가 세션·구독 metadata에 박고, 웹훅이 그걸 읽는다(Stripe = 진실의 원천).

테스트: stripe SDK 호출부를 monkeypatch해 라이브 키 없이 핸들러 로직 검증.
"""

from __future__ import annotations

import logging

import stripe

from app.config import settings
from app.services import credit_service
from app.services.config_store import load_config

log = logging.getLogger("app.stripe")

# product key → (Stripe mode, 적립 크레딧, plan|None). 크레딧/plan은 Stripe metadata에 박을 값.
# Stripe price metadata와 동기 유지(가격은 config stripe_prices가 진실, 여기는 적립량).
CATALOG = {
    "starter": ("subscription", 2000, "starter"),
    "pro": ("subscription", 8000, "pro"),
    "studio": ("subscription", 45000, "studio"),
    "pack_s": ("payment", 500, None),
    "pack_m": ("payment", 1500, None),
    "pack_l": ("payment", 5000, None),
}


def _api():
    stripe.api_key = settings.stripe_secret_key
    return stripe


def create_checkout_session(db, user_id: str, item_key: str, return_url: str) -> str:
    """Embedded Checkout 세션 생성 → client_secret 반환. item_key ∈ CATALOG.

    구독: subscription metadata에 user_id/plan/credits를 박아 invoice.paid가 읽게 함.
    탑업: session metadata에 user_id/credits를 박아 checkout.session.completed가 읽게 함.
    """
    if item_key not in CATALOG:
        raise ValueError(f"unknown item '{item_key}'")
    mode, credits, plan = CATALOG[item_key]
    price_id = load_config(db).stripe_prices.get(item_key)
    if not price_id:
        raise ValueError(f"no price configured for '{item_key}'")

    params = {
        "ui_mode": "embedded",
        "mode": mode,
        "line_items": [{"price": price_id, "quantity": 1}],
        "client_reference_id": user_id,
        "return_url": return_url,
    }
    if mode == "subscription":
        params["subscription_data"] = {
            "metadata": {"user_id": user_id, "plan": plan, "credits": str(credits)}
        }
    else:  # payment(탑업)
        params["metadata"] = {"user_id": user_id, "credits": str(credits)}

    session = _api().checkout.Session.create(**params)
    return session.client_secret


def construct_event(payload: bytes, sig_header: str):
    """서명 검증 후 Stripe 이벤트 객체 반환. 위조/실패 시 예외(라우터가 400)."""
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)


def handle_event(db, event) -> str:
    """검증된 Stripe 이벤트를 크레딧 원장에 반영. 처리한 액션 문자열 반환(관측/테스트용)."""
    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        if obj.get("mode") != "payment":
            return "ignored:subscription-checkout"  # 구독은 invoice.paid가 처리(중복 방지)
        md = obj.get("metadata") or {}
        uid, credits = md.get("user_id"), md.get("credits")
        if uid and credits:
            credit_service.topup(db, uid, int(credits), stripe_ref=obj.get("id"))
            db.commit()
            return "topup"

    elif etype == "invoice.paid":
        sub_id = obj.get("subscription")
        if sub_id:
            sub = _api().Subscription.retrieve(sub_id)
            md = sub.get("metadata") or {}
            uid, plan, credits = md.get("user_id"), md.get("plan"), md.get("credits")
            if uid and plan and credits:
                credit_service.apply_subscription_refill(
                    db, uid, plan, int(credits), stripe_ref=obj.get("id")
                )
                db.commit()
                return "refill"

    elif etype == "customer.subscription.deleted":
        md = obj.get("metadata") or {}
        uid = md.get("user_id")
        if uid:
            acct = credit_service.get_or_create_account(db, uid)
            acct.plan = "free"
            acct.monthly_allowance = 0
            db.commit()
            return "downgrade"

    return f"ignored:{etype}"
