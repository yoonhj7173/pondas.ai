"""Web Push API(item 39, D56⑤) — 구독 등록/해제 + 공개키.

- GET    /api/push/config      VAPID 공개키 + 활성 여부(프론트 구독 UI용)
- POST   /api/push/subscribe   {endpoint, keys{p256dh,auth}} 저장(기기별, upsert)
- DELETE /api/push/subscribe   {endpoint} 삭제
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import TenantScope, tenant_scope
from app.db import get_db
from app.models import PushSubscription
from app.ratelimit import rate_limit
from app.config import settings
from app.services import push_service

router = APIRouter(prefix="/api", tags=["push"])


@router.get("/push/config")
def push_config() -> dict:
    return {"enabled": push_service.enabled(),
            "vapid_public_key": settings.vapid_public_key or None}


class SubscribeIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)
    keys: dict = Field(default_factory=dict)


@router.post("/push/subscribe", status_code=204,
             dependencies=[Depends(rate_limit("10/minute", "push_subscribe"))])
def subscribe(
    body: SubscribeIn,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    """구독 upsert — 같은 endpoint 재구독은 소유자/키만 갱신(브라우저가 키를 회전할 수 있다)."""
    sub = db.query(PushSubscription).filter(PushSubscription.endpoint == body.endpoint).one_or_none()
    if sub is None:
        db.add(PushSubscription(user_id=scope.user_id, endpoint=body.endpoint, keys=body.keys))
    else:
        sub.user_id = scope.user_id
        sub.keys = body.keys
    db.commit()


class UnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)


@router.delete("/push/subscribe", status_code=204)
def unsubscribe(
    body: UnsubscribeIn,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    db.query(PushSubscription).filter(
        PushSubscription.endpoint == body.endpoint,
        PushSubscription.user_id == scope.user_id,  # 남의 구독은 못 지운다
    ).delete()
    db.commit()
