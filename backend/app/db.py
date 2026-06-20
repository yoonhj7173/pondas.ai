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

# Postgres일 때만 statement_timeout/connect_timeout을 건다(SQLite 등엔 미적용).
_engine_kwargs: dict = {"pool_pre_ping": True, "future": True}
if settings.sqlalchemy_database_url.startswith(("postgresql", "postgres")):
    _engine_kwargs.update(
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,  # 30분마다 커넥션 재생성(프록시가 끊은 좀비 방지).
        pool_timeout=30,
        connect_args={
            # 런어웨이 쿼리가 커넥션을 무한 점유하지 않게 30s 상한(감사 P2) + 연결 타임아웃.
            "options": "-c statement_timeout=30000",
            "connect_timeout": 10,
        },
    )

engine = create_engine(settings.sqlalchemy_database_url, **_engine_kwargs)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

# Redis 클라이언트는 broker(Celery)와 pub/sub(notifications) 양쪽이 공유한다.
# socket timeout 필수 — Redis 행 시 /ready·enqueue가 무한 블록되지 않게(감사 P1).
redis_client = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_timeout=5,
    socket_connect_timeout=5,
    health_check_interval=30,
)


def get_db() -> Generator[Session, None, None]:
    """DB 연결 빌려주기 — API 요청 하나마다 DB 세션을 열어주고, 끝나면 반드시 닫는다.

    PM 한 줄: Spring의 EntityManager/@Transactional처럼 "요청 1건 = 세션 1개" 수명 관리.
        API 함수가 `db: Session = Depends(get_db)`로 주입받아 DB를 만지고, 응답이 나가면
        finally에서 자동으로 닫혀 커넥션 누수를 막는다. (세션 = DB와의 대화 통로 한 개)
    """
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
