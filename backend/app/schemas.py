"""Pydantic request/response schemas — tech-design §6 API Contract (v3).

직렬화 경계를 둬서 ORM 컬럼 변화가 API 계약을 깨지 않도록 한다. item 6은 templates /
projects / map 계약을 담는다. teams/agents/edges 관리(item 7), tasks/board/usage(item 8–13)
스키마는 해당 라우터를 추가할 때 여기에 더해진다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field


def _reject_unsafe_chars(v: object) -> object:
    """사용자 텍스트에서 DB/UTF-8를 깨는 바이트를 입력 경계에서 거부(→422).

    null byte(\\x00)는 Postgres text 컬럼에 저장 불가, 짝 없는 surrogate(\\uD800 등)는 UTF-8
    인코딩 불가 → 그대로 두면 커밋 시점에 미처리 예외 → 500. 여기서 ValueError로 막아 깔끔한 422.
    (악용 테스트 ABUSE-BUG-1/2.)
    """
    if isinstance(v, str):
        if "\x00" in v:
            raise ValueError("must not contain null bytes")
        try:
            v.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("must not contain unpaired surrogate characters")
    return v


def _reject_blank(v: object) -> object:
    """공백만(스페이스/탭/개행)인 값 거부 — min_length=1은 공백을 통과시켜 빈 이름이 저장됨(P2)."""
    if isinstance(v, str) and not v.strip():
        raise ValueError("must not be blank")
    return v


# 사용자 자유입력 문자열에 붙이는 안전 타입 — 길이/필수 제약은 각 필드의 Field()가 담당.
SafeStr = Annotated[str, BeforeValidator(_reject_unsafe_chars)]
# 의미 있는 내용이 필요한 필드(이름/지시문/메시지) — 깨진 바이트 + 공백만 둘 다 거부.
NonBlankStr = Annotated[str, BeforeValidator(_reject_unsafe_chars), AfterValidator(_reject_blank)]


# --- Templates (GET /api/templates) — 역할 카탈로그(D41) ---


class RoleTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role_key: str
    display_name: str
    default_tier: str
    is_starter: bool
    default_output_type: str | None
    default_output_target_role_key: str | None
    default_max_iterations: int | None


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    description: str
    engine: str
    roles: list[RoleTemplateOut]


# --- Projects ---


class ProjectCreate(BaseModel):
    name: NonBlankStr = Field(min_length=1, max_length=200)
    # 선택한 팀 템플릿(최소 1개). 온보딩 Flow 0 step 4.
    # 각 키도 SafeStr — surrogate/null이 DB 쿼리(IN 절)에 닿기 전에 422로 막는다.
    template_keys: list[SafeStr] = Field(min_length=1)
    # 온보딩 step 2의 표시 이름(선택). user_profiles에 upsert.
    display_name: NonBlankStr | None = Field(default=None, max_length=200)


class ProjectPatch(BaseModel):
    name: NonBlankStr = Field(min_length=1, max_length=200)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    paused: bool
    sandbox_status: str


# --- Versions & files (Phase 2, D50) ---


class WorkspaceVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version_no: int
    task_id: uuid.UUID | None
    agent_id: uuid.UUID | None = None  # 그 버전을 만든 task의 에이전트(조인으로 채움)
    file_count: int = 0
    created_at: datetime


class ProjectFileEntry(BaseModel):
    path: str
    output_id: uuid.UUID


class ProjectFilesOut(BaseModel):
    version_no: int | None  # 요청한(또는 최신) 버전; 버전이 없으면 None(빈 프로젝트)
    files: list[ProjectFileEntry]


class PreviewOut(BaseModel):
    """Live Preview 상태(Phase 2, D49). status: disabled|none|starting|ready|error|paused."""
    status: str
    url: str | None = None
    version_no: int | None = None
    detail: str | None = None  # error일 때 짧은 사유(시어터 안내용)


# --- Map (GET /api/projects/{id}/map) ---


class AgentMapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    model_tier: str
    slot: int
    status: str  # idle|queued|working|blocked|needs-input|failed (done→idle)


class TeamMapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    template_key: str
    engine: str
    room_x: int
    room_y: int
    agents: list[AgentMapOut]
    # 카드 오피스(팀 카드)용 — 팀 상태 pill + 최근 활동 1줄 요약(영어, task/goal 파생).
    status: str = "idle"            # idle|working|needs-input|failed|done
    summary: str | None = None


class EdgeMapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_agent_id: uuid.UUID
    to_agent_id: uuid.UUID
    type: str
    max_iterations: int | None


class MapOut(BaseModel):
    project: ProjectOut
    paused: bool
    teams: list[TeamMapOut]
    edges: list[EdgeMapOut]


# --- Team / Agent / Edge management (item 7) ---


class TeamCreate(BaseModel):
    template_key: SafeStr


class TeamPatch(BaseModel):
    name: NonBlankStr | None = Field(default=None, min_length=1, max_length=200)
    room_x: int | None = None
    room_y: int | None = None


class AgentOutputIn(BaseModel):
    """Add-agent의 단일 출력(D38) — Final이면 통째로 생략(null)."""

    type: str  # handoff | review_loop
    to_agent_id: uuid.UUID
    max_iterations: int | None = None


class AgentCreate(BaseModel):
    # role_key는 모달이 프리필에 쓰는 힌트(서버는 최종 name/role/tier/output을 신뢰).
    role_key: str | None = None
    name: NonBlankStr = Field(min_length=1, max_length=200)
    role_instructions: NonBlankStr = Field(min_length=1, max_length=20000)
    model_tier: str
    output: AgentOutputIn | None = None


class AgentPatch(BaseModel):
    name: NonBlankStr | None = Field(default=None, min_length=1, max_length=200)
    role_instructions: NonBlankStr | None = Field(default=None, min_length=1, max_length=20000)
    model_tier: str | None = None


class EdgeCreate(BaseModel):
    from_agent_id: uuid.UUID
    to_agent_id: uuid.UUID
    type: str  # handoff | review_loop
    max_iterations: int | None = None


# --- Panel payloads (D15 / Flow 4) ---


class AgentRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    model_tier: str
    slot: int
    status: str


class TeamPanelOut(BaseModel):
    id: uuid.UUID
    name: str
    template_key: str
    engine: str
    agent_count: int
    tokens_total: int
    agents: list[AgentRowOut]


class EdgeRefOut(BaseModel):
    """패널에 보여줄 연결 한 줄."""

    id: uuid.UUID
    to_agent_id: uuid.UUID
    to_agent_name: str
    type: str
    max_iterations: int | None


class AgentPanelOut(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    name: str
    role_instructions: str
    model_tier: str
    status: str
    tokens_total: int
    # 현재 활성 task(있으면) — Stop/Provide-input 동작에 필요(D16/D22).
    current_task_id: uuid.UUID | None = None
    awaiting_prompt: str | None = None
    error_summary: str | None = None
    # 실패한 최신 task(있으면) — 패널의 Retry 대상.
    failed_task_id: uuid.UUID | None = None
    # 최근 결과 인-플로우(Phase 2, D51) — 완료 직후 패널에서 바로 결과를 렌더.
    last_result_markdown: str | None = None
    last_task_id: uuid.UUID | None = None
    last_output_count: int = 0
    # 출력 연결(최대 1개, D38) + 들어오는 연결(참고용).
    outgoing: EdgeRefOut | None
    incoming: list[EdgeRefOut]


# --- Context / Outputs / Memory (item 9) ---


class ContextFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    mime: str
    size_bytes: int


class OutputFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    path: str
    mime: str
    size_bytes: int


class OutputTaskGroupOut(BaseModel):
    """task별로 묶은 아웃풋(파일 트리). Flow 6."""

    task_id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    file_count: int
    files: list[OutputFileOut]


class OutputPreviewOut(BaseModel):
    id: uuid.UUID
    path: str
    mime: str
    is_binary: bool
    content: str | None  # 텍스트/코드면 내용, 바이너리면 null(다운로드로)


class MemoryOut(BaseModel):
    agent_id: uuid.UUID
    content_md: str


class MemoryPut(BaseModel):
    content_md: str


# --- Notifications / Board / Usage (item 12) ---


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID | None
    task_id: uuid.UUID | None
    type: str
    message: str
    read: bool


class BoardTaskOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    status: str
    instructions: str


class BoardGoalOut(BaseModel):
    id: uuid.UUID | None
    title: str
    tasks: list[BoardTaskOut]


class BoardOut(BaseModel):
    goals: list[BoardGoalOut]


class UsageBucketOut(BaseModel):
    id: uuid.UUID
    name: str
    tokens_in: int
    tokens_out: int
    cost_usd: float


class UsageOut(BaseModel):
    total_tokens_in: int
    total_tokens_out: int
    total_cost_usd: float
    by_team: list[UsageBucketOut]
    by_agent: list[UsageBucketOut]
