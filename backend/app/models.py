"""ORM models — tech-design §5 Data Model.

clusters/units는 전역 템플릿(시드, MVP read-only)이고, tasks/notifications는 user_id로
스코프되는 사용자 소유 데이터다. config는 단순 key/value 테이블(동시성 cap·가격 상수).

핵심 불변식(§1, §8): tasks.status가 단일 권위 상태다. 저장되는 task row는 항상 'queued'에서
시작하며 'idle'은 API 레이어에서만 표현된다(살아있는 task가 없는 unit). 그래도 status 컬럼은
PRD §8의 7개 값 전체를 표현할 수 있어야 하므로 텍스트로 두고 transition 검증은 TaskService(item 6)가 맡는다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import expression

from app.db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class Cluster(Base):
    """클러스터 = CrewAI Crew. 시드 데이터, 전역 템플릿."""

    __tablename__ = "clusters"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # key는 pm|swe|qa|devops — seed의 upsert 기준이자 routing 키.
    key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    map_x: Mapped[int] = mapped_column(Integer, nullable=False)
    map_y: Mapped[int] = mapped_column(Integer, nullable=False)

    units: Mapped[list["Unit"]] = relationship(
        back_populates="cluster",
        cascade="all, delete-orphan",
        order_by="Unit.map_x",
    )


class Unit(Base):
    """유닛 = CrewAI Agent. 시드 데이터, 전역 템플릿. task가 unit에 attach된다."""

    __tablename__ = "units"

    id: Mapped[uuid.UUID] = _uuid_pk()
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clusters.id", ondelete="CASCADE"),
        nullable=False,
    )
    # key는 cluster 내에서 유닛을 upsert로 식별 — (cluster_id, key) 유니크.
    key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    map_x: Mapped[int] = mapped_column(Integer, nullable=False)
    map_y: Mapped[int] = mapped_column(Integer, nullable=False)

    cluster: Mapped["Cluster"] = relationship(back_populates="units")

    __table_args__ = (
        UniqueConstraint("cluster_id", "key", name="uq_units_cluster_key"),
    )


class Task(Base):
    """단일 권위 상태(source of truth). user_id로 스코프된다."""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("units.id"),
        nullable=False,
    )
    # cluster_key는 routing/seed용 비정규화 컬럼.
    cluster_key: Mapped[str] = mapped_column(Text, nullable=False)
    # status: idle|queued|working|blocked|needs-input|done|failed. 저장 시작값은 queued.
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="queued"
    )
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    # continuations: continue마다 append되는 {at, text} 순서 리스트.
    continuations: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=expression.text("'[]'::jsonb")
    )
    result_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    awaiting_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # attempt: (re)enqueue마다 증가, (task_id, attempt) idempotency 키의 일부.
    attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=expression.text("0")
    )
    tokens_in: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=expression.text("0")
    )
    tokens_out: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=expression.text("0")
    )
    est_cost_usd: Mapped[float] = mapped_column(
        Numeric(10, 4), nullable=False, server_default=expression.text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        # (user_id, status): 동시성 카운트 + active-task 조회.
        Index("ix_tasks_user_status", "user_id", "status"),
        # (unit_id): 유닛별 최신 task 조회.
        Index("ix_tasks_unit_id", "unit_id"),
        # (user_id, created_at desc): 사용자 task 타임라인.
        Index(
            "ix_tasks_user_created",
            "user_id",
            expression.desc("created_at"),
        ),
    )


class Notification(Base):
    """SSE/notification center용. user_id로 스코프된다."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False
    )
    # unit_id: 알림 클릭 시 맵 포커스 대상.
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)  # done|blocked|needs-input|failed
    message: Mapped[str] = mapped_column(Text, nullable=False)
    read: Mapped[bool] = mapped_column(
        nullable=False, server_default=expression.false()
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # (user_id, read, created_at desc): 미읽음 알림 목록.
        Index(
            "ix_notifications_user_read_created",
            "user_id",
            "read",
            expression.desc("created_at"),
        ),
    )


class Config(Base):
    """key/value 설정 — concurrency_cap, 가격 상수 등. 배포 없이 튜닝 가능."""

    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
