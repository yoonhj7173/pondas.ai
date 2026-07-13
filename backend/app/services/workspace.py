"""WorkspaceService — 프로젝트 워크스페이스 수명주기(item 15, D29).

Track 1이 보는 유일한 실행 인터페이스(tech-design §10). SandboxProvider 위에서 프로젝트당
샌드박스 1개를 lazy 생성·재개·일시정지·파기하고 projects.sandbox_id/status를 관리한다.

- ensure_running(project): 첫 dev/design task에 lazy 생성, paused면 resume, 죽었으면 recreate.
  boot/resume 실패 → sandbox_status='error' + WorkspaceError(호출부가 task를 clean fail).
- pause_if_idle(project): 진행 중 agent_sdk task가 없으면 pause(과금 정지).
- kill_current(project): 실행 중 명령 종료(E2B 의미, Local best-effort) — Stop 훅(item 8/18).
- destroy(project): 샌드박스 파기 + 북킹 초기화(프로젝트 삭제 시).

run_dev_task / collect_outputs는 item 16/17에서 추가된다.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import Project, Task
from app.services.sandbox import SandboxProvider, get_provider

log = logging.getLogger("app.workspace")

# 프로젝트 워크스페이스 런타임 이미지(Node 22 + Python 3.12 + Playwright, §10/D31).
WORKSPACE_RUNTIME = "node22-playwright"


class WorkspaceError(Exception):
    """샌드박스 boot/resume 실패 — 호출부는 task를 clean fail 시킨다."""


class WorkspaceService:
    def __init__(self, provider: SandboxProvider | None = None):
        self.provider = provider or get_provider()

    def _alive(self, sandbox_id: str) -> bool:
        try:
            self.provider.exec(sandbox_id, "true", timeout=10)
            return True
        except Exception:  # noqa: BLE001
            return False

    def ensure_running(self, db: Session, project: Project) -> str:
        """샌드박스 켜기 보장 — 코딩에 쓸 가상 컴퓨터를 '지금 돌아가는 상태'로 만들어준다.

        PM 한 줄: 샌드박스(E2B = 안전하게 코드를 돌릴 수 있는 일회용 리눅스 컴퓨터)는 프로젝트당 1개.
            비용 때문에 평소엔 꺼두거나 재워두고, 개발·디자인 작업이 처음 필요할 때 그때 켠다(lazy).
        무슨 일을 하나: 이미 켜져 있고 살아있으면 그대로, 재워뒀으면 깨우고(resume), 없거나 죽었으면 새로 만든다.
            켜기/깨우기 실패 시 sandbox_status='error' + WorkspaceError를 던져 호출부가 작업을 깔끔히 실패시킨다.
        누가 부르나: _run_dev_task / cma_engine (backend/app/services/worker_core.py, cma_engine.py).
        연결: 실제 컨테이너 조작 → sandbox.py의 프로바이더. 다 쓰면 재우기 → 아래 pause_if_idle.
        """
        # 이미 running이고 살아있으면 그대로.
        if project.sandbox_id and project.sandbox_status == "running" and self._alive(project.sandbox_id):
            return project.sandbox_id

        # paused면 resume 시도.
        if project.sandbox_id and project.sandbox_status == "paused":
            try:
                self.provider.resume(project.sandbox_id)
                if self._alive(project.sandbox_id):
                    project.sandbox_status = "running"
                    db.commit()
                    return project.sandbox_id
            except Exception:  # noqa: BLE001 — resume 실패 → 재생성으로.
                log.warning("resume failed, recreating", extra={"project_id": str(project.id)})

        # 새로 생성(또는 죽은 샌드박스 재생성).
        try:
            sid = self.provider.create(project.id, WORKSPACE_RUNTIME)
        except Exception as exc:  # noqa: BLE001
            project.sandbox_status = "error"
            db.commit()
            raise WorkspaceError(f"sandbox boot failed: {exc}") from exc

        project.sandbox_id = sid
        project.sandbox_status = "running"
        db.commit()
        log.info("workspace running", extra={"project_id": str(project.id), "sandbox_id": sid})
        return sid

    def extend_lifetime(self, sandbox_id: str, seconds: int) -> None:
        """샌드박스 auto-GC 수명을 태스크 예산에 맞춰 연장(P0).

        왜: E2B 샌드박스는 create 시 기본 10분 수명인데 dev/design 태스크 예산은 30분 —
            수명을 안 늘리면 10분 지나 E2B가 샌드박스를 지워 "sandbox not found"로 크래시한다.
        best-effort: 연장 실패해도 태스크는 계속(10분 안에 끝날 수 있음). 실패는 로그만.
        누가 부르나: _run_dev_task — ensure_running 직후, 새 생성/재사용/resume 모든 경로에.
        """
        try:
            self.provider.set_timeout(sandbox_id, seconds)
        except Exception:  # noqa: BLE001
            log.warning("extend_lifetime failed", extra={"sandbox_id": sandbox_id, "seconds": seconds})

    def _has_active_dev_task(self, db: Session, project_id) -> bool:
        return (
            db.query(Task.id)
            .filter(
                Task.project_id == project_id,
                Task.engine == "agent_sdk",
                Task.status.in_(("queued", "working")),
            )
            .first()
            is not None
        )

    def pause_if_idle(self, db: Session, project: Project) -> bool:
        """한가하면 재우기 — 더 돌릴 개발/디자인 작업이 없으면 샌드박스를 일시정지해 돈을 아낀다.

        무슨 일을 하나: 진행 중(queued/working)인 agent_sdk 작업이 하나도 없으면 샌드박스를 pause한다.
            샌드박스는 켜져 있는 동안 과금되므로, 일이 끝나면 바로 재워 비용을 줄인다.
        누가 부르나: 개발/디자인 작업이 끝날 때마다 — _run_dev_task / cma_engine.
        """
        if not project.sandbox_id or project.sandbox_status != "running":
            return False
        if self._has_active_dev_task(db, project.id):
            return False
        try:
            self.provider.pause(project.sandbox_id)
            project.sandbox_status = "paused"
            db.commit()
            return True
        except Exception:  # noqa: BLE001
            log.warning("pause failed", extra={"project_id": str(project.id)})
            return False

    def kill_current(self, db: Session, project: Project) -> None:
        """실행 중 명령 종료(Stop, D16). E2B는 명령 kill, Local은 best-effort."""
        if not project.sandbox_id:
            return
        try:
            # E2B: 실행 중 명령 인터럽트. Local: 모사 한계로 no-op.
            kill = getattr(self.provider, "kill_current", None)
            if callable(kill):
                kill(project.sandbox_id)
        except Exception:  # noqa: BLE001
            log.warning("kill_current failed", extra={"project_id": str(project.id)})

    def destroy(self, db: Session, project: Project) -> None:
        """샌드박스 완전 폐기 — 프로젝트를 지울 때 딸린 가상 컴퓨터도 같이 없애 자원을 정리한다.

        무슨 일을 하나: 샌드박스를 파기하고 프로젝트의 sandbox 기록을 초기화한다.
        누가 부르나: 프로젝트 삭제 — delete_project (backend/app/routers/projects.py)에서 DB cascade 전에.
        """
        if project.sandbox_id:
            try:
                self.provider.destroy(project.sandbox_id)
            except Exception:  # noqa: BLE001
                log.warning("destroy failed", extra={"project_id": str(project.id)})
        project.sandbox_id = None
        project.sandbox_status = "none"


# 프로세스 공유 싱글턴(Local 프로바이더의 dir 매핑을 유지하기 위해 필수).
workspace_service = WorkspaceService()
