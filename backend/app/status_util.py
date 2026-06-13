"""Agent live-status derivation — 맵/패널 공유.

에이전트의 표시 상태 = 최신 task 상태(active만), 없으면 idle. terminal(done)은 idle로,
failed는 유지(D23). item 8(TaskService) 전에는 task가 없어 전부 idle이지만 로직은 그대로
정확하다. 맵(projects.py)과 팀/에이전트 패널(teams.py)이 공유한다.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Task

# 맵/패널에 노출하는 활성 상태. done은 idle로 접고 failed는 유지.
ACTIVE_STATUSES = {"queued", "working", "blocked", "needs-input", "failed"}


def agent_status_map(db: Session, project_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """프로젝트 에이전트별 현재 상태 dict(없으면 키 부재 → 호출부에서 idle 기본)."""
    subq = (
        db.query(Task.agent_id, func.max(Task.created_at).label("mx"))
        .filter(Task.project_id == project_id)
        .group_by(Task.agent_id)
        .subquery()
    )
    rows = (
        db.query(Task.agent_id, Task.status)
        .join(
            subq,
            (Task.agent_id == subq.c.agent_id) & (Task.created_at == subq.c.mx),
        )
        .all()
    )
    return {
        agent_id: (status if status in ACTIVE_STATUSES else "idle")
        for agent_id, status in rows
    }


def has_active_task(db: Session, agent_id: uuid.UUID) -> bool:
    """에이전트에 진행 중(queued/working/blocked/needs-input) task가 있는지. remove 게이트용."""
    return (
        db.query(Task.id)
        .filter(
            Task.agent_id == agent_id,
            Task.status.in_(("queued", "working", "blocked", "needs-input")),
        )
        .first()
        is not None
    )
