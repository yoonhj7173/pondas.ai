"""Edge management API — tech-design §6 (item 7).

- POST   /api/projects/{id}/edges   엣지 생성(출력1개/사이클/loop N 검증 — edge_ops 공유)
- DELETE /api/edges/{id}            엣지 삭제

검증 로직은 app/edge_ops.validate_and_build_edge에 모여 있고, 에이전트 추가 시 출력 지정
경로(teams.py)와 동일 규칙을 공유한다.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import TenantScope, tenant_scope
from app.db import get_db
from app.edge_ops import validate_and_build_edge
from app.models import Agent
from app.ownership import load_owned_edge, load_owned_project
from app.schemas import EdgeCreate, EdgeMapOut

router = APIRouter(prefix="/api", tags=["edges"])


@router.post(
    "/projects/{project_id}/edges",
    response_model=EdgeMapOut,
    status_code=status.HTTP_201_CREATED,
)
def create_edge(
    project_id: uuid.UUID,
    body: EdgeCreate,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> EdgeMapOut:
    project = load_owned_project(db, scope, project_id)
    from_agent = db.get(Agent, body.from_agent_id)
    if from_agent is None or from_agent.project_id != project.id:
        raise HTTPException(status_code=400, detail="from agent not in this project")

    edge = validate_and_build_edge(
        db,
        project_id=project.id,
        from_agent=from_agent,
        to_agent_id=body.to_agent_id,
        type=body.type,
        max_iterations=body.max_iterations,
    )
    db.commit()
    db.refresh(edge)
    return EdgeMapOut.model_validate(edge)


@router.delete("/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_edge(
    edge_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    edge = load_owned_edge(db, scope, edge_id)
    db.delete(edge)
    db.commit()
