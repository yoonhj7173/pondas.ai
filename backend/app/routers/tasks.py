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
from app.ratelimit import rate_limit
from app.models import Project, Task
from app.schemas import NonBlankStr
from app.services import events
from app.services import task_service as ts

router = APIRouter(prefix="/api", tags=["tasks"])


class ContinueIn(BaseModel):
    input: NonBlankStr = Field(min_length=1, max_length=8000)


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
    # 행 잠금 + 최신 상태 재조회 — 워커가 방금 done으로 커밋한 task를 Stop이 failed로 덮어쓰는
    # 레이스를 막는다(감사 P1). 락 획득 시점에 이미 종료면 ts.stop이 그대로 둔다(멱등).
    db.refresh(task, with_for_update=True)
    project = db.get(Project, task.project_id)

    def kill_hook(t: Task) -> None:
        # dev/design task면 실행 중 샌드박스 명령을 종료(D16).
        from app.services.workspace import workspace_service
        workspace_service.kill_current(db, project)

    ts.stop(db, task, kill_hook=kill_hook)
    db.commit()
    events.emit_status(task)


@router.post(
    "/tasks/{task_id}/continue",
    status_code=204,
    dependencies=[Depends(rate_limit("20/minute", "task_continue"))],  # LLM 실행 트리거 → chat과 동급 제한.
)
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


@router.post(
    "/tasks/{task_id}/retry",
    status_code=204,
    dependencies=[Depends(rate_limit("20/minute", "task_retry"))],  # 새 task 생성 + LLM 트리거 → 제한 필수.
)
def retry_task(
    task_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    """다시 시도 버튼 — 실패한 작업을 같은 지시로 새 작업 1건을 만들어 다시 큐에 올린다.

    무슨 일을 하나: 실패(failed) task는 종료 상태라 되살리지 않고, 같은 에이전트·지시·목표로
        '새 작업'을 만들어 재실행한다(실패 이력은 그대로 보존). 크레딧/일시정지 등 실행 가능 여부는
        기존 dispatch 검사(worker)가 그대로 판단한다.
    누가 부르나: 에이전트 패널의 'Retry' 버튼 — frontend/components/panels/PanelController.tsx.
    연결: 작업 생성 → create_task, 처리 → process_task (worker_core.py).
    """
    from app.models import Agent

    task = _load_owned_task(db, scope, task_id)
    if task.status != "failed":
        raise HTTPException(status_code=409, detail="only failed tasks can be retried")
    agent = db.get(Agent, task.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    new = ts.create_task(
        db,
        user_id=task.user_id,
        project_id=task.project_id,
        agent=agent,
        instructions=task.instructions,
        origin=task.origin,
        goal_id=task.goal_id,
        input_payload=task.input_payload,
    )
    db.commit()
    events.emit_status(new)
    from app.celery_app import enqueue_task
    enqueue_task(new.id)


@router.post(
    "/tasks/{task_id}/fix",
    status_code=204,
    dependencies=[Depends(rate_limit("20/minute", "task_fix"))],  # 새 task 생성 + LLM 트리거 → 제한 필수.
)
def fix_task(
    task_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    """고쳐줘 버튼(D56③) — 실패한 작업의 '실패 컨텍스트'를 주입한 디버그 작업을 새로 만든다.

    무슨 일을 하나: retry(같은 지시 재실행)와 달리, 에러 요약 + 마지막 실행 명령/종료코드를
        지시문에 붙여 "원인부터 진단하고 고쳐라"로 보낸다. 워크스페이스는 프로젝트별 영속이라
        직전 시도의 파일 위에서 디버깅이 이어진다(D50).
    누가 부르나: 에이전트 패널 failed 박스의 'Fix it' 버튼 — PanelController.tsx.
    연결: 작업 생성 → create_task, 처리 → process_task (worker_core.py).
    """
    from app.models import Agent

    task = _load_owned_task(db, scope, task_id)
    if task.status != "failed":
        raise HTTPException(status_code=409, detail="only failed tasks can be fixed")
    agent = db.get(Agent, task.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    # 실패 컨텍스트 — 사람말 에러 + 최근 실행 증적 꼬리(디버깅의 출발점).
    recent = (task.verification or [])[-5:]
    cmd_log = "\n".join(
        f"- `{v.get('cmd', '?')}` → exit {v.get('exit_code', '?')}" for v in recent
    ) or "(no commands were recorded)"
    fix_instructions = (
        f"{task.instructions}\n\n"
        "# Previous attempt FAILED — debug before rebuilding\n"
        f"Error: {task.error_summary or 'unknown error'}\n"
        f"Recent commands from the failed attempt:\n{cmd_log}\n\n"
        "The workspace still contains the previous attempt's files. Diagnose the root cause "
        "first (read the relevant files / rerun the failing command), apply a minimal fix, "
        "then verify the original goal end-to-end."
    )
    new = ts.create_task(
        db,
        user_id=task.user_id,
        project_id=task.project_id,
        agent=agent,
        instructions=fix_instructions,
        origin=task.origin,
        goal_id=task.goal_id,
        input_payload=task.input_payload,
    )
    db.commit()
    events.emit_status(new)
    from app.celery_app import enqueue_task
    enqueue_task(new.id)
