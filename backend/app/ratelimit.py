"""레이트 리밋 limiter — 프록시 뒤 실 클라이언트 IP 기준 + Redis 저장소(악용 테스트 ABUSE-BUG-3).

main.py와 라우터가 함께 쓰므로 별도 모듈로 둔다(순환 import 방지).

왜 별도 key_func: Railway 등 프록시 뒤에서는 `request.client.host`(=slowapi 기본 get_remote_address)가
프록시 IP거나 None이라, 모든 요청이 같은/빈 키로 묶여 리밋이 사실상 동작하지 않았다(270 req/26s에
429 0건). 진짜 클라이언트 IP는 프록시가 박는 `X-Forwarded-For`의 첫 항목.

왜 Redis 저장소: 기본 in-memory는 재시작/다중 인스턴스에서 카운트가 날아간다 → Redis로 영속·공유.
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings


def client_ip(request: Request) -> str:
    """프록시 뒤 실 클라이언트 IP — X-Forwarded-For 첫 항목, 없으면 직접 피어 주소."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # "client, proxy1, proxy2" → 맨 앞이 원 클라이언트.
        first = xff.split(",")[0].strip()
        if first:
            return first
    return get_remote_address(request)


# 전역 기본 120/min/IP. Redis 저장소(재시작/다중 인스턴스 공유).
# swallow_errors: Redis가 잠깐 삐끗해도 요청을 막지 않고 통과(fail-open) — 리밋 때문에 서비스가 죽지 않게.
# (per-route 강화는 slowapi @limit 데코레이터가 FastAPI body 파싱을 깨뜨려 follow-up: dependency 방식 필요.)
limiter = Limiter(
    key_func=client_ip,
    default_limits=["120/minute"],
    storage_uri=settings.redis_url,
    headers_enabled=True,  # X-RateLimit-* 응답 헤더 노출(관측/디버그).
    swallow_errors=True,
)
