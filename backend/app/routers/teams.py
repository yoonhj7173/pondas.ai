"""Team + Agent management API — tech-design §6 (item 7).

- POST   /api/projects/{id}/teams        팀 추가(템플릿 → 방 + starter 1명, D37)
- PATCH  /api/teams/{id}                  이름변경 + 방 좌표 영속(D39)
- DELETE /api/teams/{id}                  팀 삭제(cascade)
- GET    /api/teams/{id}                  팀 패널(D15)
- POST   /api/teams/{id}/agents           에이전트 추가(5캡, 슬롯 배정, 선택 출력 엣지)
- PATCH  /api/agents/{id}                 편집(name/role/tier)
- DELETE /api/agents/{id}                 삭제(working/queued면 409, 엣지 cascade)
- GET    /api/agents/{id}                 에이전트 패널(Flow 4)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import TenantScope, tenant_scope
from app.db import get_db
from app.edge_ops import validate_and_build_edge
from app.models import Agent, Edge, Team, TeamTemplate
from app.ownership import load_owned_agent, load_owned_project, load_owned_team
from app.schemas import (
    AgentCreate,
    AgentPanelOut,
    AgentPatch,
    AgentRowOut,
    EdgeRefOut,
    TeamCreate,
    TeamPanelOut,
    TeamPatch,
)
from app.status_util import agent_status_map, has_active_task

router = APIRouter(prefix="/api", tags=["teams"])

MAX_AGENTS_PER_TEAM = 5  # D37
_TIERS = ("strong", "medium", "light")
_ROOM_COL_W = 480
_ROOM_ROW_H = 420


def _next_free_slot(team: Team) -> int | None:
    """팀에서 가장 낮은 빈 슬롯(0–4). 만석이면 None."""
    used = {a.slot for a in team.agents}
    for s in range(MAX_AGENTS_PER_TEAM):
        if s not in used:
            return s
    return None


def _edge_ref(db: Session, edge: Edge) -> EdgeRefOut:
    to_agent = db.get(Agent, edge.to_agent_id)
    return EdgeRefOut(
        id=edge.id,
        to_agent_id=edge.to_agent_id,
        to_agent_name=to_agent.name if to_agent else "(removed)",
        type=edge.type,
        max_iterations=edge.max_iterations,
    )


# --- Teams ---


@router.post(
    "/projects/{project_id}/teams",
    response_model=TeamPanelOut,
    status_code=status.HTTP_201_CREATED,
)
def add_team(
    project_id: uuid.UUID,
    body: TeamCreate,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> TeamPanelOut:
    """팀 템플릿으로 새 방 + starter 1명 생성(온보딩 클론과 동일, D37)."""
    project = load_owned_project(db, scope, project_id)
    tmpl = db.get(TeamTemplate, body.template_key)
    if tmpl is None:
        raise HTTPException(status_code=400, detail=f"Unknown template: {body.template_key}")

    idx = db.query(Team).filter(Team.project_id == project.id).count()
    team = Team(
        project_id=project.id,
        template_key=tmpl.key,
        name=tmpl.name,
        room_x=(idx % 2) * _ROOM_COL_W,
        room_y=(idx // 2) * _ROOM_ROW_H,
    )
    db.add(team)
    db.flush()

    starter = next((r for r in tmpl.agent_templates if r.is_starter), None)
    if starter is None:
        raise HTTPException(status_code=500, detail="template has no starter role")
    db.add(
        Agent(
            team_id=team.id,
            project_id=project.id,
            name=starter.display_name,
            role_instructions=starter.role_instructions,
            model_tier=starter.default_tier,
            slot=0,
        )
    )
    db.commit()
    db.refresh(team)
    return _team_panel(db, team)


@router.patch("/teams/{team_id}", response_model=TeamPanelOut)
def update_team(
    team_id: uuid.UUID,
    body: TeamPatch,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> TeamPanelOut:
    """이름 변경 + 방 드래그 좌표 영속(D39) — 한 PATCH로."""
    team = load_owned_team(db, scope, team_id)
    if body.name is not None:
        team.name = body.name
    if body.room_x is not None:
        team.room_x = body.room_x
    if body.room_y is not None:
        team.room_y = body.room_y
    db.commit()
    db.refresh(team)
    return _team_panel(db, team)


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(
    team_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    team = load_owned_team(db, scope, team_id)
    db.delete(team)  # agents/edges cascade(FK)
    db.commit()


@router.get("/teams/{team_id}", response_model=TeamPanelOut)
def get_team(
    team_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> TeamPanelOut:
    return _team_panel(db, load_owned_team(db, scope, team_id))


def _team_panel(db: Session, team: Team) -> TeamPanelOut:
    status_by_agent = agent_status_map(db, team.project_id)
    engine = db.get(TeamTemplate, team.template_key)
    agents = sorted(team.agents, key=lambda a: a.slot)
    rows = [
        AgentRowOut(
            id=a.id, name=a.name, model_tier=a.model_tier, slot=a.slot,
            status=status_by_agent.get(a.id, "idle"),
        )
        for a in agents
    ]
    return TeamPanelOut(
        id=team.id,
        name=team.name,
        template_key=team.template_key,
        engine=engine.engine if engine else "crew",
        agent_count=len(agents),
        tokens_total=0,  # 토큰 집계는 item 10/12에서 연결.
        agents=rows,
    )


# --- Agents ---


@router.post(
    "/teams/{team_id}/agents",
    response_model=AgentPanelOut,
    status_code=status.HTTP_201_CREATED,
)
def add_agent(
    team_id: uuid.UUID,
    body: AgentCreate,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> AgentPanelOut:
    """에이전트 추가 — 5캡(409), 슬롯 배정, 선택 출력 엣지 동시 생성(D37/D38)."""
    team = load_owned_team(db, scope, team_id)
    if body.model_tier not in _TIERS:
        raise HTTPException(status_code=422, detail="model_tier must be strong|medium|light")

    slot = _next_free_slot(team)
    if slot is None:
        raise HTTPException(status_code=409, detail="desks are full (max 5 agents per team)")

    # 같은 팀 내 이름 중복(uq_agents_team_name) 사전 체크.
    if any(a.name == body.name for a in team.agents):
        raise HTTPException(status_code=409, detail="an agent with that name already exists in this team")

    agent = Agent(
        team_id=team.id,
        project_id=team.project_id,
        name=body.name,
        role_instructions=body.role_instructions,
        model_tier=body.model_tier,
        slot=slot,
    )
    db.add(agent)
    db.flush()

    if body.output is not None:
        validate_and_build_edge(
            db,
            project_id=team.project_id,
            from_agent=agent,
            to_agent_id=body.output.to_agent_id,
            type=body.output.type,
            max_iterations=body.output.max_iterations,
        )

    db.commit()
    db.refresh(agent)
    return _agent_panel(db, agent)


@router.patch("/agents/{agent_id}", response_model=AgentPanelOut)
def update_agent(
    agent_id: uuid.UUID,
    body: AgentPatch,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> AgentPanelOut:
    agent = load_owned_agent(db, scope, agent_id)
    if body.model_tier is not None:
        if body.model_tier not in _TIERS:
            raise HTTPException(status_code=422, detail="model_tier must be strong|medium|light")
        agent.model_tier = body.model_tier
    if body.name is not None:
        if any(a.name == body.name and a.id != agent.id for a in agent.team.agents):
            raise HTTPException(status_code=409, detail="name already used in this team")
        agent.name = body.name
    if body.role_instructions is not None:
        agent.role_instructions = body.role_instructions
    db.commit()
    db.refresh(agent)
    return _agent_panel(db, agent)


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(
    agent_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    agent = load_owned_agent(db, scope, agent_id)
    # working/queued면 먼저 멈추라고 막는다(D16/Flow 4). item 8 전엔 task 없어 안 걸림.
    if has_active_task(db, agent.id):
        raise HTTPException(status_code=409, detail="stop the task before removing this agent")
    db.delete(agent)  # outgoing/incoming 엣지 cascade(FK)
    db.commit()


@router.get("/agents/{agent_id}", response_model=AgentPanelOut)
def get_agent(
    agent_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> AgentPanelOut:
    return _agent_panel(db, load_owned_agent(db, scope, agent_id))


def _agent_panel(db: Session, agent: Agent) -> AgentPanelOut:
    status_by_agent = agent_status_map(db, agent.project_id)
    outgoing_edge = db.query(Edge).filter(Edge.from_agent_id == agent.id).first()
    incoming_edges = db.query(Edge).filter(Edge.to_agent_id == agent.id).all()
    return AgentPanelOut(
        id=agent.id,
        team_id=agent.team_id,
        name=agent.name,
        role_instructions=agent.role_instructions,
        model_tier=agent.model_tier,
        status=status_by_agent.get(agent.id, "idle"),
        tokens_total=0,  # item 10/12에서 연결.
        outgoing=_edge_ref(db, outgoing_edge) if outgoing_edge else None,
        incoming=[_edge_ref(db, e) for e in incoming_edges],
    )
