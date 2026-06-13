"""SQLAlchemy engine/session + Redis client + readiness checks.

tech-design §7: db.py는 엔진/세션을 제공한다. 여기에 더해 /ready 엔드포인트가 쓸
DB·Redis 도달성 점검 헬퍼도 같이 둔다(인프라 클라이언트가 한 곳에 모여 있는 편이 명료).

- 엔진은 pool_pre_ping=True로 stale 커넥션을 자동 폐기한다(서버리스/프록시 환경 대비).
- get_db()는 FastAPI 의존성으로 요청당 세션을 열고 닫는다.
"""

from __future__ import annotations

from collections.abc import Generator

import redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import settings

# 모든 ORM 모델(models.py에서 정의될 clusters/units/tasks 등)이 상속할 베이스.
Base = declarative_base()

engine = create_engine(
    settings.sqlalchemy_database_url,
    pool_pre_ping=True,  # 끊긴 커넥션을 사용 전에 감지
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

# Redis 클라이언트는 broker(Celery)와 pub/sub(notifications) 양쪽이 공유한다.
redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 의존성: 요청 스코프 DB 세션."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db() -> bool:
    """라이브 Postgres에 실제로 연결해 `SELECT 1`을 실행한다. /ready용."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True


def check_redis() -> bool:
    """라이브 Redis에 실제로 PING한다. /ready용."""
    return bool(redis_client.ping())
