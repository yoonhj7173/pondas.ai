"""FastAPI application factory + app instance.

tech-design §4, §7: stateless FastAPI 앱. 미들웨어(CORS) + 라우터 마운트.
item 2에서는 시스템 라우터(/health, /ready)만 마운트한다. 이후 item들에서
map/units/tasks/notifications/sse/resources 라우터가 추가될 자리다.

라우트 prefix 규칙(tech-design §6): /health, /ready는 prefix 없이 루트에,
나머지 비즈니스 라우터는 /api prefix로 붙는다.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.logging_config import configure_logging, get_logger
from app.ratelimit import limiter  # 프록시 뒤 실 IP + Redis 저장소(ABUSE-BUG-3)
from app.routers import (
    auth_demo,
    billing,
    chat,
    context,
    edges,
    memory,
    outputs,
    preview,
    projects,
    realtime,
    system,
    tasks,
    teams,
)

configure_logging(settings.log_level)
log = get_logger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 보안 가드(부팅 거부): 프로덕션에서 E2E auth 우회가 켜져 있으면 시작 금지.
    if settings.e2e_auth_bypass:
        if settings.is_production:
            raise RuntimeError("E2E_AUTH_BYPASS must never be enabled in production.")
        log.warning("⚠️ E2E_AUTH_BYPASS is ON — authentication is bypassed (DEV/TEST ONLY).")
    # 부팅 시 설정 요약을 구조화 로그로 남긴다(시크릿은 절대 찍지 않는다).
    log.info(
        "app starting",
        extra={
            "concurrency_cap": settings.concurrency_cap,
            "model": settings.anthropic_model,
            "log_level": settings.log_level,
        },
    )
    yield
    log.info("app shutdown")


class SafeJSONResponse(JSONResponse):
    """surrogate-safe JSON 렌더(악용 테스트 ABUSE-BUG-2).

    FastAPI 기본 JSONResponse는 `json.dumps(ensure_ascii=False).encode("utf-8")`라, 응답 본문에
    짝 없는 surrogate(\\uD800)가 섞이면 utf-8 인코딩이 터져 500이 된다(특히 4xx 에러가 잘못된
    입력값을 그대로 echo할 때). errors="replace"로 그런 바이트만 �로 치환해 응답이 깨지지 않게 한다.
    """

    def render(self, content: object) -> bytes:
        return json.dumps(
            content, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":")
        ).encode("utf-8", errors="replace")


def _cors_headers(request: Request) -> dict[str, str]:
    """에러 응답에 CORS 헤더를 직접 단다 — catch-all 핸들러는 CORSMiddleware 바깥에서 돌아
    안 그러면 브라우저가 net::ERR_FAILED로 진짜 에러를 가린다(결제 등)."""
    origin = request.headers.get("origin")
    if origin and origin in settings.cors_origin_list:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        }
    return {}


async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 본문이 문제의 입력값을 echo하므로 surrogate-safe 렌더러로 응답(기본 렌더러는 깨짐)."""
    return SafeJSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors())},
        headers=_cors_headers(request),
    )


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """HTTPException(예: 400에 사용자 입력 echo)도 surrogate-safe 렌더 + CORS 유지."""
    return SafeJSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers={**(exc.headers or {}), **_cors_headers(request)},
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """처리되지 않은 서버 에러를 로깅하고 Slack으로 알린 뒤 500 응답(slack 미설정 시 알림만 no-op).

    Slack POST는 동기 httpx라 이벤트 루프 안 막게 스레드풀로 던진다. 알림 실패는 자체 삼킴.
    """
    import traceback

    from app.services.slack_alerts import send_slack_alert

    where = f"{request.method} {request.url.path}"
    log.exception("unhandled error: %s", where)
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    await run_in_threadpool(
        send_slack_alert, f"prod error · {where}", f"{type(exc).__name__}: {exc}\n{tb[-1200:]}"
    )
    # 이 catch-all 핸들러는 CORSMiddleware 바깥(ServerErrorMiddleware)에서 돌아서 500 응답에
    # CORS 헤더가 안 붙는다 → 브라우저엔 net::ERR_FAILED로 보여 진짜 에러를 가린다(특히 결제). 직접 단다.
    return SafeJSONResponse(
        status_code=500, content={"detail": "Internal Server Error"}, headers=_cors_headers(request)
    )


def create_app() -> FastAPI:
    # 기본 응답을 surrogate-safe 렌더러로 — 어떤 응답이든 깨진 바이트에 500 안 나게(ABUSE-BUG-2).
    app = FastAPI(
        title="cursor-pm backend", version="0.1.0", lifespan=lifespan,
        default_response_class=SafeJSONResponse,
    )

    # 4xx 에러 응답도 surrogate-safe + CORS 유지(잘못된 입력값 echo 시 인코딩 크래시 방지).
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)

    # 레이트 리밋(per-IP 전역). 초과 시 429.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # 처리 안 된 서버 에러(500)만 Slack 알림(opt-in). HTTPException/4xx/429는 정상 흐름 → 제외
    # (더 구체적인 핸들러가 우선하므로 여기엔 진짜 unhandled만 옴). 응답은 평소처럼 500.
    app.add_exception_handler(Exception, _unhandled_exception_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,  # 명시적 origin 화이트리스트(와일드카드 아님).
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        # rate-limit 헤더를 브라우저 JS가 읽을 수 있게 노출(없으면 cross-origin에서 가려짐).
        expose_headers=["Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
    )

    # 시스템 라우터는 prefix 없이 루트에 마운트(/health, /ready).
    app.include_router(system.router)
    # 인증 보호 라우터(/api/me, /api/whoami). require_user 의존성으로 Clerk JWT 강제.
    app.include_router(auth_demo.router)
    # Projects API + 템플릿 클로닝 + 맵(item 6).
    app.include_router(projects.router)
    # Team/Agent 관리(item 7).
    app.include_router(teams.router)
    # Edge 관리(item 7).
    app.include_router(edges.router)
    # Context / Outputs / Memory(item 9).
    app.include_router(context.router)
    app.include_router(outputs.router)
    app.include_router(memory.router)
    # SSE / Notifications / Board / Usage(item 12).
    app.include_router(realtime.router)
    # Orchestrator chat(item 13).
    app.include_router(chat.router)
    # Task control: stop / continue(item 18).
    app.include_router(tasks.router)
    # Billing: Stripe checkout + webhook(D46).
    app.include_router(billing.router)

    app.include_router(preview.router)

    return app


app = create_app()
