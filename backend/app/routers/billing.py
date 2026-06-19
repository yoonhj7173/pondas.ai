"""Billing API (빌링 D46) — Embedded Checkout 세션 발급 + Stripe 웹훅 수신.

- POST /billing/checkout : 로그인 유저가 product key로 결제 세션을 받아 모달 안에서 결제(워크스페이스 유지).
- POST /billing/webhook  : Stripe가 결제/구독 이벤트를 쏘는 곳. 서명 검증 후 크레딧 원장에 반영.

체크아웃은 Stripe 키가 설정돼 있으면 동작(미터링 플래그 billing_enabled와 독립 — 결제는 사전 검증 가능).
웹훅은 인증 없음(Stripe가 호출) + 서명으로 진위 확인.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_user
from app.config import settings
from app.db import get_db
from app.logging_config import get_logger
from app.models import CreditAccount
from app.services import stripe_service
from app.services.slack_alerts import send_slack_alert

router = APIRouter(tags=["billing"])
log = get_logger("app.billing")


@router.get("/billing/summary")
def billing_summary(
    user_id: str = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    """treasury 표시용 — 잔액/플랜/월 allowance. 읽기 전용(계정 없으면 기본값, 생성 안 함)."""
    a = db.get(CreditAccount, user_id)
    return {
        "balance": a.balance if a else 0,
        "plan": a.plan if a else "free",
        "monthly_allowance": a.monthly_allowance if a else 0,
    }


class CheckoutBody(BaseModel):
    item: str  # starter | pro | studio | pack_s | pack_m | pack_l
    return_url: str = "https://pondas.ai/billing/return?session_id={CHECKOUT_SESSION_ID}"


class PortalBody(BaseModel):
    return_url: str = "https://pondas.ai/"


@router.post("/billing/checkout")
def create_checkout(
    body: CheckoutBody,
    user_id: str = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    """Embedded Checkout 세션 생성 → client_secret 반환(프론트가 모달에서 결제)."""
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="billing not configured")
    try:
        client_secret = stripe_service.create_checkout_session(db, user_id, body.item, body.return_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"client_secret": client_secret}


@router.post("/billing/portal")
def create_portal(
    body: PortalBody,
    user_id: str = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    """Stripe Customer Portal URL 반환 → 유저가 구독 해지/결제수단 변경(CA ARL click-to-cancel)."""
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="billing not configured")
    try:
        url = stripe_service.create_portal_session(db, user_id, body.return_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"url": url}


@router.post("/billing/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Stripe 웹훅 — 서명 검증 후 크레딧 원장 반영. 위조/검증 실패는 400."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe_service.construct_event(payload, sig)
    except Exception as exc:  # noqa: BLE001 — 서명 실패/파싱 실패 = 거부.
        log.warning("stripe webhook verify failed", extra={"error": str(exc)})
        raise HTTPException(status_code=400, detail="invalid signature")
    try:
        action = stripe_service.handle_event(db, event)
    except Exception as exc:  # noqa: BLE001 — 처리 실패 = 돈 경로 → 알림 + 500(Stripe 재시도 유도).
        db.rollback()
        send_slack_alert(f"stripe webhook failed · {event.get('type')}", f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail="webhook handler error")
    return {"received": True, "action": action}
