"""Clerk Backend API 얇은 래퍼 — 현재는 primary 이메일 조회만.

`CLERK_SECRET_KEY` 미설정이면 no-op(None). 실패해도 예외를 삼켜 본 흐름(온보딩)을
절대 막지 않는다(best-effort). 참고: slack_alerts.py의 opt-in/에러-삼킴 패턴.

주의: Clerk의 WAF는 일부 라이브러리 기본 User-Agent(python-urllib 등)를 403으로 막는다.
그래서 명시적 커스텀 UA를 붙인다.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

log = logging.getLogger("app.clerk")

_API = "https://api.clerk.com/v1"
_UA = "pondas-backend"


def get_user_email(user_id: str) -> str | None:
    """Clerk에서 유저의 primary 이메일을 가져온다. 키 없거나 실패 시 None(본 흐름 안 막음)."""
    key = settings.clerk_secret_key
    if not key:
        return None  # opt-in: 시크릿 미설정이면 조용히 no-op
    try:
        r = httpx.get(
            f"{_API}/users/{user_id}",
            headers={"Authorization": f"Bearer {key}", "User-Agent": _UA},
            timeout=3.0,
        )
        r.raise_for_status()
        u = r.json()
        addrs = u.get("email_addresses", []) or []
        primary_id = u.get("primary_email_address_id")
        # primary 우선, 없으면 첫 이메일 폴백.
        for e in addrs:
            if e.get("id") == primary_id:
                return e.get("email_address")
        return addrs[0].get("email_address") if addrs else None
    except Exception:  # noqa: BLE001 — 이메일 캡처 실패는 온보딩 안 막음
        log.warning("clerk email fetch failed", extra={"user_id": user_id})
        return None
