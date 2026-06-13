"""FastAPI application factory + app instance.

tech-design §4, §7: stateless FastAPI 앱. 미들웨어(CORS) + 라우터 마운트.
item 2에서는 시스템 라우터(/health, /ready)만 마운트한다. 이후 item들에서
map/units/tasks/notifications/sse/resources 라우터가 추가될 자리다.

라우트 prefix 규칙(tech-design §6): /health, /ready는 prefix 없이 루트에,
나머지 비즈니스 라우터는 /api prefix로 붙는다.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_config import configure_logging, get_logger
from app.routers import auth_demo, map as map_router, system, units

configure_logging(settings.log_level)
log = get_logger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
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


def create_app() -> FastAPI:
    app = FastAPI(title="cursor-pm backend", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 시스템 라우터는 prefix 없이 루트에 마운트(/health, /ready).
    app.include_router(system.router)
    # 인증 보호 라우터(/api/me, /api/whoami). require_user 의존성으로 Clerk JWT 강제.
    app.include_router(auth_demo.router)
    # 토폴로지 read API: GET /api/map, GET /api/units/{id}. 모두 Clerk JWT 필요.
    app.include_router(map_router.router)
    app.include_router(units.router)

    return app


app = create_app()
