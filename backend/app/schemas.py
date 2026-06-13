"""Pydantic 응답 스키마 — tech-design §6 API Contract.

이 모듈은 read API(map/units)의 응답 형태를 고정한다. ORM 모델을 그대로 노출하지 않고
스키마로 직렬화 경계를 둬서, 내부 컬럼 변화가 API 계약을 깨지 않도록 한다.

핵심 규약(§5, §6):
- clusters/units는 전역 템플릿(positions/roles 포함)이라 user 스코프가 없다.
- unit detail의 task 상태는 user 스코프된 권위 상태다. 살아있는 task가 없으면 task=None,
  그리고 unit status는 API 레이어에서만 'idle'로 표현한다(저장된 idle row는 없다).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class UnitOut(BaseModel):
    """맵에 그릴 유닛 템플릿 — 위치(map_x/map_y)와 role 포함."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cluster_id: uuid.UUID
    key: str
    name: str
    role: str
    map_x: int
    map_y: int


class ClusterOut(BaseModel):
    """맵에 그릴 클러스터 템플릿 — anchor 위치 포함."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    map_x: int
    map_y: int


class MapOut(BaseModel):
    """GET /map 응답 — 시드된 전역 토폴로지(clusters + units)."""

    clusters: list[ClusterOut]
    units: list[UnitOut]


# result_markdown 전체는 무거울 수 있어 detail 응답엔 snippet만 싣는다(§11).
# 전체 마크다운은 GET /tasks/{id}(item 9)에서 lazy-load 한다.
RESULT_SNIPPET_MAX = 280


class TaskStateOut(BaseModel):
    """unit detail에 실리는 현재 권위 task 상태(§6).

    살아있는 task가 없으면 이 객체 자체가 None이고, unit status는 'idle'이 된다.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    result_snippet: Optional[str] = None
    awaiting_prompt: Optional[str] = None
    error_summary: Optional[str] = None
    updated_at: datetime


class UnitDetailOut(BaseModel):
    """GET /units/{id} 응답 — unit 템플릿 + 현재 사용자의 권위 task 상태 + 파생 status.

    status는 task가 있으면 그 task.status, 없으면 'idle'(API 레이어 전용).
    """

    unit: UnitOut
    status: str
    task: Optional[TaskStateOut] = None
