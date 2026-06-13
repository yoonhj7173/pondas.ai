"""GET /units/{id} — unit 템플릿 + 현재 사용자의 권위 task 상태 (tech-design §6).

핵심 데이터 흐름(§5):
- unit/cluster는 전역 템플릿이라 누구에게나 동일하다.
- 그 unit 위의 "라이브 상태"는 *이 사용자*의 가장 최근 task에서 파생된다. 따라서 task
  조회는 반드시 user_id로 스코프해야 한다(tenant_scope) — 교차 사용자 상태 누출 방지.

idle 규약(§5, §8): 살아있는 task가 없는 unit은 status 'idle'이다. 'idle'은 저장되는
값이 아니라 API 레이어에서만 표현한다(task row가 없을 때 파생). 따라서 가장 최근 task가
없으면 task=None + status='idle'을 돌려준다.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import TenantScope, tenant_scope
from app.db import get_db
from app.models import Task, Unit
from app.schemas import (
    RESULT_SNIPPET_MAX,
    TaskStateOut,
    UnitDetailOut,
    UnitOut,
)

router = APIRouter(prefix="/api", tags=["units"])

# task row가 없는 unit의 파생 상태. 저장값이 아니라 API 레이어 전용(§5).
IDLE_STATUS = "idle"


def _snippet(markdown: str | None) -> str | None:
    """result_markdown에서 패널용 짧은 발췌만 추린다(§11). 전체는 GET /tasks/{id}."""
    if not markdown:
        return None
    text = markdown.strip()
    if len(text) <= RESULT_SNIPPET_MAX:
        return text
    return text[:RESULT_SNIPPET_MAX].rstrip() + "…"


@router.get("/units/{unit_id}", response_model=UnitDetailOut)
def get_unit_detail(
    unit_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> UnitDetailOut:
    """unit + 이 사용자의 현재 권위 task 상태. task가 없으면 status='idle'."""
    unit = db.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unit not found"
        )

    # 이 사용자의 이 unit에 대한 가장 최근 task. tenant_scope로 user_id 필터를 강제한다 —
    # 교차 사용자 task가 보이는 일이 없도록.
    latest_task = (
        scope.query(db, Task)
        .filter(Task.unit_id == unit_id)
        .order_by(Task.created_at.desc())
        .first()
    )

    if latest_task is None:
        # 살아있는 task 없음 → idle(파생). task=None.
        return UnitDetailOut(
            unit=UnitOut.model_validate(unit),
            status=IDLE_STATUS,
            task=None,
        )

    # task가 있으면 그 status가 권위 상태다(idle은 저장되지 않으므로 이 값은 idle이 아님).
    task_state = TaskStateOut(
        id=latest_task.id,
        status=latest_task.status,
        result_snippet=_snippet(latest_task.result_markdown),
        awaiting_prompt=latest_task.awaiting_prompt,
        error_summary=latest_task.error_summary,
        updated_at=latest_task.updated_at,
    )
    return UnitDetailOut(
        unit=UnitOut.model_validate(unit),
        status=latest_task.status,
        task=task_state,
    )
