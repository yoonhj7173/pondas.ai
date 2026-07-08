"""Alembic environment — uses app settings + ORM Base metadata.

alembic.ini의 sqlalchemy.url을 비워두고, 여기서 app.config.settings의 정규화된
DATABASE_URL(postgresql+psycopg2://...)을 주입한다. autogenerate가 모델을 인식하도록
target_metadata에 app.models의 Base.metadata를 연결한다.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context

# app 패키지 import (alembic은 backend/ cwd에서 실행되므로 pythonpath에 "." 포함됨).
from app.config import settings
from app.db import Base
import app.models  # noqa: F401  # 모든 모델을 Base.metadata에 등록하기 위해 import

config = context.config

# alembic.ini에 url을 하드코딩하는 대신 런타임에 정규화된 URL을 주입.
config.set_main_option("sqlalchemy.url", settings.sqlalchemy_database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # 전역 마이그레이션 락 — web/worker preDeploy가 동시에 `alembic upgrade head`를 돌려도
        # (감사 P1) 병렬 DDL 충돌/크래시루프 대신 순차 실행되게 한다. 두 번째는 첫 번째 완료를
        # 기다렸다가 진행(이미 head면 no-op). 세션 종료 시 자동 해제되지만 명시적으로 unlock.
        _LOCK_KEY = 0x70DA5  # "pondas" migration lock.
        connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _LOCK_KEY})
        connection.commit()  # 획득 트랜잭션 닫기 — 세션 락은 유지, alembic이 깨끗한 상태에서 자기 트랜잭션 시작.
        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
