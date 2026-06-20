"""Task control API — stop + continue (item 18, tech-design §6, D16/D22).

- POST /api/tasks/{id}/stop      실행 중/대기 task 중단(failed+stopped). dev면 샌드박스 명령 kill.
- POST /api/tasks/{id}/continue  blocked/needs-input task에 입력 전달 재개(패널 경로).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import TenantScope, tenant_scope
from app.db import get_db
from app.models import Project, Task
from app.schemas import SafeStr
from app.services import events
from app.services import task_service as ts

router = APIRouter(prefix="/api", tags=["tasks"])


class ContinueIn(BaseModel):
    input: SafeStr = Field(min_length=1, max_length=8000)


def _load_owned_task(db: Session, scope: TenantScope, task_id: uuid.UUID) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    project = db.get(Project, task.project_id)
    if project is None or not scope.owns(project):
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/tasks/{task_id}/stop", status_code=204)
def stop_task(
    task_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    """작업 멈춤 버튼 — 에이전트 패널의 'Stop'을 눌렀을 때 진행 중인 작업을 강제 종료한다.

    무슨 일을 하나: 작업을 멈추고(failed+stopped), 개발/디자인 작업이면 샌드박스에서 돌던 명령도 죽인다.
    누가 부르나: 에이전트 패널 Stop — frontend/components/panels/PanelController.tsx.
    연결: 멈춤 로직 본체 → stop (backend/app/services/task_service.py).
    """
    task = _load_owned_task(db, scope, task_id)
    project = db.get(Project, task.project_id)

    def kill_hook(t: Task) -> None:
        # dev/design task면 실행 중 샌드박스 명령을 종료(D16).
        from app.services.workspace import workspace_service
        workspace_service.kill_current(db, project)

    ts.stop(db, task, kill_hook=kill_hook)
    db.commit()
    events.emit_status(task)


@router.post("/tasks/{task_id}/continue", status_code=204)
def continue_task(
    task_id: uuid.UUID,
    body: ContinueIn,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    """입력 제공 버튼 — 질문하며 멈춘 에이전트에게 패널에서 직접 답을 주고 작업을 재개한다.

    무슨 일을 하나: blocked/needs-input(입력 대기) 작업에 사용자 입력을 붙이고 다시 큐에 올린다.
        (지휘자 채팅의 resume_task와 같은 일을, 에이전트 패널 UI에서 직접 하는 경로)
    누가 부르나: 에이전트 패널의 입력칸 제출 — frontend/components/panels/PanelController.tsx.
    연결: 입력 붙이기 본체 → request_continue (backend/app/services/task_service.py).
    """
    task = _load_owned_task(db, scope, task_id)
    if task.status not in ("blocked", "needs-input"):
        raise HTTPException(status_code=409, detail="task is not awaiting input")
    ts.request_continue(db, task, body.input, via="panel")
    db.commit()
    events.emit_status(task)
    from app.celery_app import enqueue_task
    enqueue_task(task.id)
