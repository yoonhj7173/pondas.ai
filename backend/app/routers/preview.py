"""Live Preview API — Phase 2 item 29 (D49).

- POST /api/projects/{id}/preview/start   프리뷰 기동(현재 버전 서빙) → status/url
- POST /api/projects/{id}/preview/stop    프리뷰 pause(과금 정지)
- GET  /api/projects/{id}/preview         현재 상태 폴링(ready면 last_active 갱신 = idle 카운터 리셋)

소유권: 모든 접근은 TenantScope로 확인, 아니면 404. preview_enabled(config) OFF면 start는
status='disabled'를 돌려준다(프론트가 카드/시어터를 숨김). 실제 서빙은 on-demand E2B 샌드박스에서.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import TenantScope, tenant_scope
from app.db import get_db
from app.ownership import load_owned_project
from app.ratelimit import rate_limit
from app.schemas import PreviewOut
from app.services.preview import preview_service

router = APIRouter(prefix="/api", tags=["preview"])


@router.post(
    "/projects/{project_id}/preview/start",
    response_model=PreviewOut,
    dependencies=[Depends(rate_limit("30/minute", "preview_start"))],
)
def start_preview(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> PreviewOut:
    project = load_owned_project(db, scope, project_id)
    return PreviewOut(**preview_service.start(db, project))


@router.post("/projects/{project_id}/preview/stop", response_model=PreviewOut)
def stop_preview(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> PreviewOut:
    project = load_owned_project(db, scope, project_id)
    return PreviewOut(**preview_service.stop(db, project))


@router.get("/projects/{project_id}/preview", response_model=PreviewOut)
def get_preview(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> PreviewOut:
    project = load_owned_project(db, scope, project_id)
    return PreviewOut(**preview_service.status(db, project))
