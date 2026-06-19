"""ORM models — tech-design §5 Data Model (v3, decision-log D1–D44).

v1의 clusters/units 모델을 폐기하고 v3 모델로 전면 재작성한다(prod 데이터 없음).

구조:
- 소유/격리: user_profiles → projects → (그 아래 모든 행은 project_id로 스코프).
- 템플릿(읽기전용 시드): team_templates + agent_templates(저작된 역할 카탈로그, D41).
  edge_templates는 두지 않는다 — 팀이 에이전트 1개로 시작(D37)하므로 생성 시점에 연결할
  peer가 없다. 역할의 기본 출력은 agent_templates 컬럼으로 들고 모달 프리필에만 쓴다.
- 인스턴스: teams(방, D39) / agents(model_tier, D32) / edges(출력 1개=from_agent_id unique, D38).
- 실행: goals / tasks(7상태 + engine + verification) / outputs(파일당 1행).
- 보조: context_files / agent_memories / orchestrator_messages / notifications / config.

핵심 불변식(§1, §8): tasks.status가 단일 권위 상태다. 저장되는 task는 'queued'에서 시작하고
'idle'은 API 레이어에서만(살아있는 task 없는 agent) 표현된다. enum류 컬럼은 PG 네이티브 enum
대신 text + CHECK로 둔다 — P1에서 값 추가 시 enum 마이그레이션 고통을 피하기 위함(어시스턴트 판단).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import expression

from app.db import Base

# --- enum 허용값 (text + CHECK로 강제; 코드에서도 검증 재사용) ---
ENGINES = ("crew", "agent_sdk")
TIERS = ("strong", "medium", "light")
SANDBOX_STATUSES = ("none", "running", "paused", "error")
EDGE_TYPES = ("handoff", "review_loop")
TASK_STATUSES = ("idle", "queued", "working", "blocked", "needs-input", "done", "failed")
TASK_ORIGINS = ("chat", "edge", "panel")
ORCH_ROLES = ("user", "orchestrator")
# 빌링(D46) — 구독 플랜 + 크레딧 원장 사유. plan=free는 무료크레딧만.
BILLING_PLANS = ("free", "starter", "pro", "studio")
LEDGER_REASONS = (
    "signup_grant",      # 가입 무료 크레딧(1계정 1회)
    "monthly_refill",    # 구독 월 충전
    "topup",             # 크레딧 팩 구매
    "task_charge",       # task 실행 차감(등급 가중)
    "refund_system_failure",  # 시스템 실패 환불(우리 잘못만, D46 B-4)
    "adjustment",        # 수동 보정/지원
)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _fk_uuid(target: str, *, ondelete: str = "CASCADE", nullable: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
    )


def _in_check(column: str, allowed: tuple[str, ...], name: str) -> CheckConstraint:
    """text 컬럼을 허용 집합으로 제한하는 CHECK 제약을 만든다."""
    values = ", ".join(f"'{v}'" for v in allowed)
    return CheckConstraint(f"{column} IN ({values})", name=name)


def _created_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now(), nullable=False)


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ======================================================================
# 소유 / 격리
# ======================================================================


class UserProfile(Base):
    """Clerk user_id를 pk로 하는 사용자 프로필. user_id는 Clerk가 발급한 문자열."""

    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Project(Base):
    """프로젝트 = 오피스 맵 1개. 삭제 시 하위 트리 cascade + 샌드박스 destroy(앱 레벨, D29)."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    paused: Mapped[bool] = mapped_column(
        nullable=False, server_default=expression.false()
    )
    # 워크스페이스(E2B) 상태 — 첫 dev/design task에 lazy 생성(D29).
    sandbox_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    sandbox_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="none"
    )
    # CMA 프로젝트 공유 memory store(회사 기억) — Dev 엔진 파일럿(D45), lazy 생성.
    cma_memory_store_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    teams: Mapped[list["Team"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_projects_user", "user_id"),
        _in_check("sandbox_status", SANDBOX_STATUSES, "ck_projects_sandbox_status"),
    )


# ======================================================================
# 템플릿 (시드, 읽기전용) — D40/D41
# ======================================================================


class TeamTemplate(Base):
    """팀 템플릿 — MVP 4팀(planning/research/design/development). Data는 P1(D44).

    engine은 템플릿 속성(D43): development & design = agent_sdk, 나머지 = crew.
    """

    __tablename__ = "team_templates"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    engine: Mapped[str] = mapped_column(Text, nullable=False)

    agent_templates: Mapped[list["AgentTemplate"]] = relationship(
        back_populates="team_template",
        cascade="all, delete-orphan",
        order_by="AgentTemplate.role_key",
    )

    __table_args__ = (_in_check("engine", ENGINES, "ck_team_templates_engine"),)


class AgentTemplate(Base):
    """역할 카탈로그 1행 — 저작된 역할(role-catalog.md → role_instructions, D41).

    Add-agent 모달이 role_key로 골라 name/role/tier/output을 프리필한다(모두 편집 가능).
    default_output_* 는 그 역할의 추천 출력 연결(D38) — edge_templates 대체.
    is_starter는 팀당 정확히 1개(프로젝트 생성 시 인스턴스화되는 시작 에이전트).
    """

    __tablename__ = "agent_templates"

    id: Mapped[uuid.UUID] = _uuid_pk()
    template_key: Mapped[str] = mapped_column(
        Text, ForeignKey("team_templates.key", ondelete="CASCADE"), nullable=False
    )
    role_key: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    role_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    default_tier: Mapped[str] = mapped_column(Text, nullable=False)
    is_starter: Mapped[bool] = mapped_column(
        nullable=False, server_default=expression.false()
    )
    # 추천 기본 출력(D38) — target은 같은 프로젝트 내 role_key로 해석(앱 레벨, item 7).
    default_output_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_output_target_role_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_max_iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)

    team_template: Mapped["TeamTemplate"] = relationship(
        back_populates="agent_templates"
    )

    __table_args__ = (
        UniqueConstraint("template_key", "role_key", name="uq_agent_templates_role"),
        _in_check("default_tier", TIERS, "ck_agent_templates_tier"),
        CheckConstraint(
            "default_output_type IS NULL OR default_output_type IN ('handoff', 'review_loop')",
            name="ck_agent_templates_output_type",
        ),
    )


# ======================================================================
# 인스턴스 — teams / agents / edges
# ======================================================================


class Team(Base):
    """팀 인스턴스 = 방 1개(D39 드래그 좌표). engine은 template_key에서 유도.

    팀당 에이전트 최대 5명(D37) — DB 제약 대신 agent insert 시 앱 레벨 검증(item 7).
    """

    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _fk_uuid("projects.id")
    template_key: Mapped[str] = mapped_column(
        Text, ForeignKey("team_templates.key"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    room_x: Mapped[int] = mapped_column(Integer, nullable=False, server_default=expression.text("0"))
    room_y: Mapped[int] = mapped_column(Integer, nullable=False, server_default=expression.text("0"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    project: Mapped["Project"] = relationship(back_populates="teams")
    agents: Mapped[list["Agent"]] = relationship(
        back_populates="team", cascade="all, delete-orphan", order_by="Agent.slot"
    )

    __table_args__ = (Index("ix_teams_project", "project_id"),)


class Agent(Base):
    """에이전트 = 방 안의 워커. 5슬롯 중 하나(slot 0–4)를 채운다(D37).

    model_tier(D32)는 템플릿 기본값에서 시작해 유저가 오버라이드 가능.
    """

    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    team_id: Mapped[uuid.UUID] = _fk_uuid("teams.id")
    project_id: Mapped[uuid.UUID] = _fk_uuid("projects.id")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    model_tier: Mapped[str] = mapped_column(Text, nullable=False)
    # CMA Dev 엔진 파일럿(D45) — 에이전트당 영속 agent/session(lazy). null=crew/E2B 경로.
    cma_agent_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    cma_session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # slot: 0–4. 점유 슬롯 바운딩박스를 카펫 중앙 정렬하는 건 프론트(item 21).
    slot: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=expression.text("0"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    team: Mapped["Team"] = relationship(back_populates="agents")
    memory: Mapped["AgentMemory | None"] = relationship(
        back_populates="agent", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        UniqueConstraint("team_id", "name", name="uq_agents_team_name"),
        Index("ix_agents_team", "team_id"),
        Index("ix_agents_project", "project_id"),
        _in_check("model_tier", TIERS, "ck_agents_tier"),
    )


class Edge(Base):
    """연결(D6/D19/D38) — handoff 또는 review_loop. 에이전트당 출력 1개.

    from_agent_id에 unique 인덱스(출력 엣지 1개, D38; Final output = 행 없음).
    self-edge 금지 + (from,to,type) 유니크. handoff가 사이클을 닫는지 검사(D25)는 앱 레벨.
    스키마는 P1 멀티엣지 대비 일반형 유지 — from_agent_id unique만 떼면 됨.
    """

    __tablename__ = "edges"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _fk_uuid("projects.id")
    from_agent_id: Mapped[uuid.UUID] = _fk_uuid("agents.id")
    to_agent_id: Mapped[uuid.UUID] = _fk_uuid("agents.id")
    type: Mapped[str] = mapped_column(Text, nullable=False)
    max_iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        UniqueConstraint("from_agent_id", "to_agent_id", "type", name="uq_edges_triple"),
        # 출력 엣지 최대 1개(D38).
        UniqueConstraint("from_agent_id", name="uq_edges_one_outgoing"),
        Index("ix_edges_project", "project_id"),
        Index("ix_edges_to_agent", "to_agent_id"),
        CheckConstraint("from_agent_id <> to_agent_id", name="ck_edges_no_self"),
        _in_check("type", EDGE_TYPES, "ck_edges_type"),
        CheckConstraint(
            "(type = 'review_loop' AND max_iterations BETWEEN 1 AND 10) "
            "OR (type = 'handoff' AND max_iterations IS NULL)",
            name="ck_edges_max_iterations",
        ),
    )


# ======================================================================
# 실행 — goals / tasks / outputs
# ======================================================================


class Goal(Base):
    """목표(D20) — 보드 = goals × tasks. 챗 지시 1건이 보통 goal 1개로 분해된다."""

    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _fk_uuid("projects.id")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (Index("ix_goals_project", "project_id"),)


class Task(Base):
    """단일 권위 상태(source of truth). 7상태(§8). engine은 생성 시 비정규화(D43).

    provenance(parent_task_id/edge_id)로 그래프 전파를 추적하고, (parent_task_id, edge_id)
    부분 유니크로 엣지 재발화 중복을 막는다(GraphEngine, item 11). verification은 dev/design
    task의 "working as expected" 증적(D31).
    """

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[uuid.UUID] = _fk_uuid("projects.id")
    agent_id: Mapped[uuid.UUID] = _fk_uuid("agents.id")
    goal_id: Mapped[uuid.UUID | None] = _fk_uuid("goals.id", nullable=True)

    origin: Mapped[str] = mapped_column(Text, nullable=False)
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    edge_id: Mapped[uuid.UUID | None] = _fk_uuid("edges.id", ondelete="SET NULL", nullable=True)

    loop_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    override_route: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # D21

    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    engine: Mapped[str] = mapped_column(Text, nullable=False)
    # stopped: 유저 Stop으로 failed가 된 경우 True(에러 failed와 구분 + 전파 억제 belt, D16).
    stopped: Mapped[bool] = mapped_column(
        nullable=False, server_default=expression.false()
    )
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    input_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    continuations: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=expression.text("'[]'::jsonb")
    )
    result_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    awaiting_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=expression.text("0")
    )
    # 비용 집계(D32): model_used × config.model_pricing.
    model_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_in: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=expression.text("0")
    )
    tokens_out: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=expression.text("0")
    )
    # Numeric(12,6): 저가 모델의 마이크로 비용(센트 미만)까지 보존(cost_usd 6자리와 정합).
    est_cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, server_default=expression.text("0")
    )
    # verification: dev/design task의 [{cmd, exit_code, summary}] 명령 로그(D31).
    verification: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    __table_args__ = (
        Index("ix_tasks_project_status", "project_id", "status"),
        Index("ix_tasks_agent_status", "agent_id", "status"),
        Index("ix_tasks_goal", "goal_id"),
        Index("ix_tasks_user_created", "user_id", expression.desc("created_at")),
        # 엣지 재발화 중복 방지(GraphEngine dedup) — 둘 다 not null일 때만.
        Index(
            "uq_tasks_parent_edge",
            "parent_task_id",
            "edge_id",
            unique=True,
            postgresql_where=expression.text(
                "parent_task_id IS NOT NULL AND edge_id IS NOT NULL"
            ),
        ),
        _in_check("status", TASK_STATUSES, "ck_tasks_status"),
        _in_check("origin", TASK_ORIGINS, "ck_tasks_origin"),
        _in_check("engine", ENGINES, "ck_tasks_engine"),
    )


class Output(Base):
    """아웃풋 파일 — 파일당 1행(dev/design task는 트리=여러 행, D4/D27/D42).

    content(text/code) 또는 content_bytes(바이너리: 디자인 PNG 등) 중 정확히 하나만 채운다.
    FileStore 인터페이스(PostgresFileStore now / S3 P1, D27)를 통해 저장.
    """

    __tablename__ = "outputs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _fk_uuid("projects.id")
    agent_id: Mapped[uuid.UUID] = _fk_uuid("agents.id")
    task_id: Mapped[uuid.UUID] = _fk_uuid("tasks.id")
    path: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        Index("ix_outputs_project", "project_id"),
        Index("ix_outputs_task", "task_id"),
        CheckConstraint(
            "(content IS NOT NULL) <> (content_bytes IS NOT NULL)",
            name="ck_outputs_one_content",
        ),
    )


# ======================================================================
# 보조 — context / memory / orchestrator / notifications / config
# ======================================================================


class ContextFile(Base):
    """프로젝트 컨텍스트 파일(D14) — 원본 + 추출 텍스트. 프롬프트에 풀텍스트 주입(no RAG)."""

    __tablename__ = "context_files"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _fk_uuid("projects.id")
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (Index("ix_context_files_project", "project_id"),)


class AgentMemory(Base):
    """에이전트별 마크다운 스크래치패드(D14) — task 후 auto-append, 다음 task에 주입."""

    __tablename__ = "agent_memories"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    content_md: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    updated_at: Mapped[datetime] = _updated_at()

    agent: Mapped["Agent"] = relationship(back_populates="memory")


class OrchestratorMessage(Base):
    """오케스트레이터 챗 히스토리(D3) — role ∈ {user, orchestrator}."""

    __tablename__ = "orchestrator_messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _fk_uuid("projects.id")
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        Index("ix_orch_messages_project", "project_id", expression.desc("created_at")),
        _in_check("role", ORCH_ROLES, "ck_orch_messages_role"),
    )


class Notification(Base):
    """알림(D5/D23) — done/blocked/needs-input/failed. 클릭 시 agent 포커스."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[uuid.UUID] = _fk_uuid("projects.id")
    agent_id: Mapped[uuid.UUID | None] = _fk_uuid("agents.id", nullable=True)
    task_id: Mapped[uuid.UUID | None] = _fk_uuid("tasks.id", nullable=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    read: Mapped[bool] = mapped_column(
        nullable=False, server_default=expression.false()
    )
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        Index(
            "ix_notifications_user_read_created",
            "user_id",
            "read",
            expression.desc("created_at"),
        ),
        Index("ix_notifications_project", "project_id"),
    )


class Config(Base):
    """key/value 설정 — 배포 없이 튜닝(D32 가격맵/티어맵 포함). 복합값은 JSON 문자열."""

    __tablename__ = "config"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class CreditAccount(Base):
    """유저 1명의 크레딧 지갑 + 구독 상태 (빌링 D46). 키 = Clerk user_id.

    balance = 현재 크레딧(원장 누적 결과의 캐시). 권위는 항상 ledger 합이며 balance는 캐시.
    plan/스트라이프 필드는 구독 증분에서 채워짐(지금은 free + 무료크레딧만).
    spending_cap_enabled = 기본 ON(D46 B-6): 잔액 모자라면 task 차단(폭탄 방지).
    """

    __tablename__ = "credit_accounts"

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    plan: Mapped[str] = mapped_column(Text, nullable=False, server_default="free")
    # 월 충전량 + 다음 리셋 시각(구독 증분에서 사용). free는 0.
    monthly_allowance: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    allowance_resets_at: Mapped[datetime | None] = mapped_column(nullable=True)
    spending_cap_enabled: Mapped[bool] = mapped_column(
        nullable=False, server_default=expression.true()
    )
    signup_granted: Mapped[bool] = mapped_column(
        nullable=False, server_default=expression.false()
    )
    # Stripe 연동(다음 증분). 지금은 null.
    stripe_customer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    __table_args__ = (
        _in_check("plan", BILLING_PLANS, "ck_credit_accounts_plan"),
    )


class CreditLedger(Base):
    """추가-전용(append-only) 크레딧 원장 (D46). 모든 잔액 변동 1줄 = 1엔트리.

    delta = 부호 있는 크레딧 변동(+충전/환불, −차감). balance_after = 그 직후 잔액 스냅샷(감사용).
    task_id = task_charge/refund의 출처. 절대 update/delete 하지 않음(불변 장부).
    """

    __tablename__ = "credit_ledger"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    task_id: Mapped[uuid.UUID | None] = _fk_uuid("tasks.id", nullable=True)
    stripe_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        Index("ix_credit_ledger_user", "user_id", expression.desc("created_at")),
        _in_check("reason", LEDGER_REASONS, "ck_credit_ledger_reason"),
    )
