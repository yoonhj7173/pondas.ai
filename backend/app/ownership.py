"""Ownership loaders — 소유권 확인 + 404 은폐를 한 곳에 모은다(여러 라우터 재사용).

모든 프로젝트 하위 리소스 접근은 그 리소스가 속한 project의 user_id를 확인한다. 교차
사용자 접근은 존재를 은폐하기 위해 404를 던진다(403 아님). projects/teams/edges 라우터가
공유한다.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth import TenantScope
from app.models import Agent, Edge, Project, Team


def load_owned_project(db: Session, scope: TenantScope, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None or not scope.owns(project):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def load_owned_team(db: Session, scope: TenantScope, team_id: uuid.UUID) -> Team:
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    # 팀의 프로젝트 소유권 확인.
    project = db.get(Project, team.project_id)
    if project is None or not scope.owns(project):
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def load_owned_agent(db: Session, scope: TenantScope, agent_id: uuid.UUID) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    project = db.get(Project, agent.project_id)
    if project is None or not scope.owns(project):
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def load_owned_edge(db: Session, scope: TenantScope, edge_id: uuid.UUID) -> Edge:
    edge = db.get(Edge, edge_id)
    if edge is None:
        raise HTTPException(status_code=404, detail="Edge not found")
    project = db.get(Project, edge.project_id)
    if project is None or not scope.owns(project):
        raise HTTPException(status_code=404, detail="Edge not found")
    return edge
