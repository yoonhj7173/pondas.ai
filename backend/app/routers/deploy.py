"""Deploy API(item 37, D56②/D60) — Grand Opening. DEPLOY_ENABLED=false(기본)면 전부 503.

- GET    /api/projects/{id}/deploy            상태(url/domain/status/version)
- POST   /api/projects/{id}/deploy            최신 버전 배포(명시적 유저 액션)
- POST   /api/projects/{id}/deploy/domain     커스텀 도메인 연결(DNS 안내 반환)
- GET    /api/projects/{id}/secrets           키 목록만(값은 절대 반환 안 함)
- PUT    /api/projects/{id}/secrets           {key, value} 저장(암호화 at rest)
- DELETE /api/projects/{id}/secrets/{key}
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import TenantScope, tenant_scope
from app.db import get_db
from app.models import Project, ProjectSecret
from app.ratelimit import rate_limit
from app.services import deploy_service as ds

router = APIRouter(prefix="/api", tags=["deploy"])

_DOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")
_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _guard_enabled() -> None:
    if not ds.enabled():
        raise HTTPException(status_code=503, detail="Deploy is not enabled yet")


def _load_owned_project(db: Session, scope: TenantScope, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None or not scope.owns(project):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/projects/{project_id}/deploy")
def deploy_status(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> dict:
    project = _load_owned_project(db, scope, project_id)
    return {
        "enabled": ds.enabled(),
        "status": project.deploy_status,
        "url": project.deploy_url,
        "domain": project.deploy_domain,
        "version_no": project.deployed_version_no,
    }


@router.post("/projects/{project_id}/deploy",
             dependencies=[Depends(rate_limit("5/minute", "deploy"))])
def deploy_now(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> dict:
    """Grand Opening — 명시적 유저 액션만(자동 배포 없음: 프리뷰가 자동, 배포는 의식)."""
    _guard_enabled()
    project = _load_owned_project(db, scope, project_id)
    try:
        result = ds.deploy_project(db, project)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        db.commit()  # deploy_status=error 반영
        raise HTTPException(status_code=502, detail=str(exc))
    db.commit()
    return result


class DomainIn(BaseModel):
    domain: str = Field(min_length=4, max_length=253)


@router.post("/projects/{project_id}/deploy/domain",
             dependencies=[Depends(rate_limit("5/minute", "deploy_domain"))])
def add_domain(
    project_id: uuid.UUID,
    body: DomainIn,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> dict:
    _guard_enabled()
    project = _load_owned_project(db, scope, project_id)
    domain = body.domain.strip().lower()
    if not _DOMAIN_RE.match(domain):
        raise HTTPException(status_code=422, detail="invalid domain")
    if project.deploy_provider_id is None:
        raise HTTPException(status_code=409, detail="deploy first, then connect a domain")
    try:
        result = ds.get_provider().add_domain(project.deploy_provider_id, domain)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="failed to add domain")
    project.deploy_domain = domain
    db.commit()
    return result


class SecretIn(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=8000)


@router.get("/projects/{project_id}/secrets")
def list_secrets(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> dict:
    """키 목록만 — 값은 어떤 경로로도 반환하지 않는다(D60 신뢰 표면)."""
    project = _load_owned_project(db, scope, project_id)
    rows = db.query(ProjectSecret).filter(ProjectSecret.project_id == project.id).all()
    return {"keys": sorted(r.key for r in rows)}


@router.put("/projects/{project_id}/secrets", status_code=204,
            dependencies=[Depends(rate_limit("20/minute", "secrets"))])
def put_secret(
    project_id: uuid.UUID,
    body: SecretIn,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    project = _load_owned_project(db, scope, project_id)
    if not _KEY_RE.match(body.key):
        raise HTTPException(status_code=422, detail="key must be UPPER_SNAKE_CASE")
    try:
        ds.set_secret(db, project, body.key, body.value)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="secrets storage is not configured")
    db.commit()


@router.delete("/projects/{project_id}/secrets/{key}", status_code=204)
def delete_secret(
    project_id: uuid.UUID,
    key: str,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    project = _load_owned_project(db, scope, project_id)
    db.query(ProjectSecret).filter(
        ProjectSecret.project_id == project.id, ProjectSecret.key == key
    ).delete()
    db.commit()
