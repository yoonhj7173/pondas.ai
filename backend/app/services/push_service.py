"""Web Push 서비스(item 39, D56⑤) — 에이전트는 몇 시간 일하고 유저는 자리에 없다.

needs-input/failed/done 종결 알림을 브라우저 푸시(모바일 PWA 포함)로 보낸다.
- 구독은 유저당 여러 개(기기별) — endpoint 유니크.
- 발송은 베스트에포트: 실패해도 인앱 알림 파이프를 절대 깨지 않는다.
- 410/404(구독 만료)는 그 자리에서 구독 삭제(자연 청소).
- VAPID env 미설정 시 전부 no-op.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.models import PushSubscription

log = logging.getLogger("app.push")


def enabled() -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key)


# 테스트 이음새 — pywebpush.webpush를 monkeypatch로 교체한다.
def _send(subscription_info: dict, payload: str) -> None:
    from pywebpush import webpush

    webpush(
        subscription_info=subscription_info,
        data=payload,
        vapid_private_key=settings.vapid_private_key,
        vapid_claims={"sub": settings.vapid_subject},
    )


def send_push(db: Session, user_id: str, *, title: str, body: str, url: str) -> int:
    """유저의 모든 구독 기기에 발송. 반환 = 성공 건수. 예외를 절대 흘리지 않는다."""
    if not enabled():
        return 0
    subs = db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
    sent = 0
    payload = json.dumps({"title": title, "body": body, "url": url})
    for sub in subs:
        try:
            _send({"endpoint": sub.endpoint, "keys": sub.keys}, payload)
            sent += 1
        except Exception as exc:  # noqa: BLE001 — 만료 구독 청소 + 그 외는 로그만.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                db.delete(sub)
                log.info("push subscription expired, removed: %s…", sub.endpoint[:40])
            else:
                log.warning("push send failed: %s", exc)
    return sent
