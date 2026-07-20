"""Versioning — 프로젝트 파일 상태 갱신 + 버전 스냅샷 커팅(Phase 2, D50).

무슨 일을 하나: dev/design task가 완료되면 그 task가 만든/바꾼 파일(Output 행)을 프로젝트의
    canonical 파일 상태(project_files 매니페스트)에 upsert하고, 그 시점의 전체 상태를 동결한
    버전 스냅샷(workspace_versions, v1·v2·…)을 하나 남긴다. 이게 있어야 Preview가 "최신 버전"을
    서빙하고, 유저의 "고쳐줘"가 파편이 아니라 하나의 진화하는 결과물 위에서 돌아간다.
누가 부르나: worker_core._run_dev_task(E2B) / cma_engine.run_dev_task_cma(CMA) — 둘 다 done 분기에서
    collect_outputs 직후, _finalize_done 전에.
설계 노트(격리): 스냅샷은 _append_memory와 같은 격리 정책 — 실패해도 task를 깨지 않는다. 라이브
    운영에서 버전 스냅샷 버그가 결제까지 얽힌 task 완료/전파를 무너뜨려선 안 된다. 구조상 done 전이와
    Output은 collect_outputs가 이미 commit한 뒤이므로, 여기서 실패해 rollback해도 done은 durable하다
    (버전만 누락 → Preview가 직전 버전을 서빙, 허용 가능한 열화). 그래서 "버전은 done인 task만 갖지만,
    done이 반드시 버전을 갖지는 않는다"가 실제 보장이다.
"""

from __future__ import annotations

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Output, ProjectFile, Task, WorkspaceVersion

log = logging.getLogger("app.versioning")


def snapshot_version(db: Session, task: Task) -> int | None:
    """이 task가 만든 Output들을 프로젝트 파일 상태에 반영하고 버전 스냅샷을 커팅한다.

    반환: 새 version_no(성공) / None(수집 파일 없음 또는 격리된 실패). flush만 하고 commit은
        호출부(_finalize_done)의 commit에 맡긴다 — 같은 커밋 창에서 확정된다.
    """
    try:
        rows = (
            db.query(Output.id, Output.path)
            .filter(Output.task_id == task.id)
            .all()
        )
        if not rows:
            return None  # 텍스트 요약만 있고 파일 없음 → 스냅샷 안 함.

        # 1) 매니페스트 upsert — 같은 path는 최신 output_id로 교체.
        for out_id, path in rows:
            pf = (
                db.query(ProjectFile)
                .filter(ProjectFile.project_id == task.project_id, ProjectFile.path == path)
                .one_or_none()
            )
            if pf is None:
                db.add(ProjectFile(
                    project_id=task.project_id, path=path,
                    output_id=out_id, updated_by_task_id=task.id,
                ))
            else:
                pf.output_id = out_id
                pf.updated_by_task_id = task.id
        db.flush()

        # 2) 현재 전체 상태를 동결 → manifest {path: output_id(str)}.
        manifest = {
            pf.path: str(pf.output_id)
            for pf in db.query(ProjectFile)
            .filter(ProjectFile.project_id == task.project_id)
            .all()
        }

        # 3) 버전 번호 = 프로젝트별 max+1. 유니크 제약(project_id, version_no)이 백스톱.
        #    동시 완료(dev+design 병행)의 희귀 경합은 격리 정책상 1건 누락으로 흡수(허용 가능).
        next_no = (
            db.query(func.max(WorkspaceVersion.version_no))
            .filter(WorkspaceVersion.project_id == task.project_id)
            .scalar()
            or 0
        ) + 1
        version = WorkspaceVersion(
            project_id=task.project_id, version_no=next_no,
            task_id=task.id, manifest=manifest,
        )
        db.add(version)
        db.flush()
        # 사람말 라벨(D61) — light-tier 요약(실패 시 지시문 폴백). 히스토리 UI + 커밋 메시지.
        from app.services import github_service
        changed = [path for _, path in rows]
        version.label = github_service.humanize_label(db, task, changed)
        db.flush()
        # 리포 연결 프로젝트면 비동기 푸시(countdown 5s — 호출부 커밋 이후 발화 보장).
        github_service.enqueue_push(next_no, task.project_id, db)
        return next_no
    except Exception:  # noqa: BLE001 — 격리: 버전 실패가 task를 깨지 않는다.
        log.warning("version snapshot failed", extra={"task_id": str(task.id)})
        db.rollback()
        return None
