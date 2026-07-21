"""GitHub 소유권 API(item 36, D56①/D61) — 연결·리포 생성·히스토리·Restore.

- GET  /api/github/status                 연결 상태(계정, 기능 활성 여부)
- POST /api/github/install               App 설치 기록(installation_id — 설치 검증 포함)
- POST /api/projects/{id}/repo           유저 계정에 리포 생성 + 기존 버전 백필
- GET  /api/projects/{id}/history        사람말 버전 히스토리(라벨 + 푸시 상태)
- POST /api/projects/{id}/restore/{no}   과거 버전으로 복원 = 새 버전 컷(히스토리 보존)
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import TenantScope, tenant_scope
from app.db import get_db
from app.models import GithubConnection, Project, WorkspaceVersion
from app.ratelimit import rate_limit
from app.services import github_service as gh

router = APIRouter(prefix="/api", tags=["github"])


def _load_owned_project(db: Session, scope: TenantScope, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None or not scope.owns(project):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/github/status")
def github_status(
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> dict:
    """연결 카드용 상태 — 기능 활성 여부(env) + 이 유저의 설치/계정."""
    conn = db.get(GithubConnection, scope.user_id)
    return {
        "enabled": gh.enabled(),
        "install_url": gh.install_url() if gh.enabled() else None,
        # 재인증(user 토큰만 다시 받기) — 기존 설치는 install URL이 code를 안 주므로 OAuth
        # authorize 경로가 따로 필요하다(실측 플로우 갭).
        "authorize_url": gh.authorize_url() if gh.enabled() else None,
        "connected": conn is not None,
        "has_user_token": bool(conn is not None and conn.user_token_encrypted),
        "account_login": conn.account_login if conn else None,
    }


class InstallIn(BaseModel):
    # installation_id 없음 = code-only 재인증(기존 연결에 user 토큰만 갱신).
    installation_id: int | None = Field(default=None, gt=0)
    code: str | None = Field(default=None, max_length=200)  # OAuth during install의 ?code=


@router.post("/github/install", status_code=204,
             dependencies=[Depends(rate_limit("10/minute", "github_install"))])
def github_install(
    body: InstallIn,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    """설치 콜백 기록 — 프론트가 GitHub 설치 리다이렉트의 installation_id를 전달한다.

    위조 방어: get_installation으로 '우리 App의 실존 설치'인지 검증하고 계정 로그인을 저장.
    (설치는 유저 본인 계정에서만 이뤄지므로, 검증 실패 = 404/403 → 400으로 표면화)
    """
    if not gh.enabled():
        raise HTTPException(status_code=503, detail="GitHub integration is not configured")
    if body.installation_id is None:
        # code-only 재인증 — 기존 연결 필수.
        conn = db.get(GithubConnection, scope.user_id)
        if conn is None or not body.code:
            raise HTTPException(status_code=400, detail="nothing to authorize")
        try:
            gh.store_user_token(conn, gh.exchange_oauth_code(body.code))
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger("app.github").warning("reauthorize failed: %s", exc)
            raise HTTPException(status_code=400, detail="authorization failed")
        db.commit()
        return
    try:
        info = gh.get_client().get_installation(body.installation_id)
    except Exception as exc:  # noqa: BLE001 — 존재하지 않거나 우리 App 설치가 아님.
        # 조용한 400 금지(실사고: PEM 포맷 오류가 'invalid installation'로 위장됐다) — 원인 로깅.
        import logging
        logging.getLogger("app.github").warning("install validation failed: %s", exc)
        raise HTTPException(status_code=400, detail="invalid installation")
    conn = db.get(GithubConnection, scope.user_id)
    if conn is None:
        conn = GithubConnection(user_id=scope.user_id, installation_id=body.installation_id,
                                account_login=info["account_login"])
        db.add(conn)
    else:
        conn.installation_id = body.installation_id
        conn.account_login = info["account_login"]
    # user access token(개인 계정 리포 생성용) — code가 오면 교환/저장. 실패해도 연결 자체는 유지
    # (리포 생성 시점에 재연결 안내).
    if body.code:
        try:
            gh.store_user_token(conn, gh.exchange_oauth_code(body.code))
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger("app.github").warning("oauth code exchange failed: %s", exc)
    db.commit()


@router.post("/projects/{project_id}/repo",
             dependencies=[Depends(rate_limit("5/minute", "github_repo"))])
def create_project_repo(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> dict:
    """프로젝트 리포 생성(유저 계정 소유, D61) + 기존 버전 전체 백필."""
    if not gh.enabled():
        raise HTTPException(status_code=503, detail="GitHub integration is not configured")
    project = _load_owned_project(db, scope, project_id)
    if project.repo_full_name:
        return {"repo_full_name": project.repo_full_name, "backfilled": 0}
    conn = db.get(GithubConnection, scope.user_id)
    if conn is None:
        raise HTTPException(status_code=409, detail="connect GitHub first")

    # 리포명 = 프로젝트 슬러그(영숫자/하이픈만 — GitHub 규칙).
    slug = re.sub(r"[^a-zA-Z0-9-]+", "-", project.name).strip("-").lower() or "pondas-project"
    try:
        user_token = gh.get_user_token(db, conn)
    except RuntimeError:
        # 구버전 연결(user 토큰 없음) — 재설치로 code를 받아야 한다.
        raise HTTPException(status_code=409, detail="reconnect GitHub to enable repository creation")
    try:
        full_name = gh.get_client().create_repo(user_token, slug)
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger("app.github").warning("repo creation failed: %s", exc)
        raise HTTPException(status_code=502, detail="failed to create repository")
    project.repo_full_name = full_name
    db.commit()
    backfilled = gh.backfill(db, project)
    return {"repo_full_name": full_name, "backfilled": backfilled}


@router.get("/projects/{project_id}/history")
def project_history(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> dict:
    """사람말 버전 히스토리(D61) — History 패널이 소비. 최신순."""
    project = _load_owned_project(db, scope, project_id)
    versions = (
        db.query(WorkspaceVersion)
        .filter(WorkspaceVersion.project_id == project.id)
        .order_by(WorkspaceVersion.version_no.desc())
        .limit(100)
        .all()
    )
    return {
        "repo_full_name": project.repo_full_name,
        "versions": [
            {
                "version_no": v.version_no,
                "label": v.label or "Workspace update",
                "created_at": v.created_at.isoformat(),
                "pushed": v.pushed_at is not None,
                "commit_sha": v.commit_sha,
                "files": len(v.manifest or {}),
            }
            for v in versions
        ],
    }


@router.post("/projects/{project_id}/restore/{version_no}",
             dependencies=[Depends(rate_limit("10/minute", "github_restore"))])
def restore_project_version(
    project_id: uuid.UUID,
    version_no: int,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> dict:
    """Restore(D61) — 과거 버전 내용으로 '새 버전'을 컷한다(force-push/히스토리 삭제 없음).

    프리뷰가 켜져 있으면 복원된 상태를 즉시 반영한다(D51 iteration과 동일 파이프).
    """
    project = _load_owned_project(db, scope, project_id)
    try:
        new_no = gh.restore_version(db, project, version_no)
    except ValueError:
        raise HTTPException(status_code=404, detail="version not found")
    db.commit()
    gh.enqueue_push(new_no, project.id, db)
    from app.services.preview import preview_service
    preview_service.refresh_if_active(db, project)
    return {"version_no": new_no}
