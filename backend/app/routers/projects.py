"""Projects API + template cloning — tech-design §6 (item 6).

엔드포인트:
- GET  /api/templates                  팀 템플릿 + 역할 카탈로그(D41) 노출(온보딩/Add-agent 프리필)
- POST /api/projects                   트랜잭션 클론: project + 선택 팀마다 starter 1명(D37)
- GET  /api/projects                   유저 프로젝트 목록(스위처)
- GET  /api/projects/{id}              단건
- PATCH/DELETE /api/projects/{id}      이름변경 / 삭제(cascade)
- POST /api/projects/{id}/pause|resume paused 토글(D16)
- GET  /api/projects/{id}/map          맵 투영(teams+agents w/ status+tier, edges, paused)

소유권: 모든 프로젝트 접근은 TenantScope로 user_id를 확인하고, 아니면 404(존재 은폐).
클론은 D37대로 팀당 starter 에이전트 1개만 만든다(혼자라 엣지 없음, D38).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import TenantScope, require_user, tenant_scope
from app.db import get_db
from app.ratelimit import rate_limit
from app.models import (
    Agent,
    Edge,
    Project,
    ProjectFile,
    Task,
    Team,
    TeamTemplate,
    UserProfile,
    WorkspaceVersion,
)
from app.ownership import load_owned_project
from app.status_util import agent_status_map
from app.schemas import (
    AgentMapOut,
    EdgeMapOut,
    MapOut,
    ProjectCreate,
    ProjectFileEntry,
    ProjectFilesOut,
    ProjectOut,
    ProjectPatch,
    RoleTemplateOut,
    TeamMapOut,
    TemplateOut,
    WorkspaceVersionOut,
)

router = APIRouter(prefix="/api", tags=["projects"])

# 계정당 프로젝트 총량 상한(스팸/누적 방어). 일반 사용자에겐 넉넉, 봇 어뷰즈만 차단.
MAX_PROJECTS_PER_USER = 100

# 초기 방 배치(2열 그리드). 이후 드래그로 변경(D39).
_ROOM_COL_W = 480
_ROOM_ROW_H = 420


def _build_map(db: Session, project: Project) -> MapOut:
    """맵 데이터 만들기 — 사무실 화면을 그리는 데 필요한 모든 것을 한 덩어리로 묶어 내보낸다.

    무슨 일을 하나: 프론트의 사무실 맵 화면은 이 한 번의 응답으로 그려진다. 팀(방)들 + 각 방의
        에이전트(자리/상태/모델등급) + 에이전트 사이 연결선(엣지) + 일시정지 여부를 모아 직렬화한다.
        각 에이전트의 현재 상태는 agent_status_map으로 작업 기록에서 계산해 넣는다.
    누가 부르나: GET /api/projects/{id}/map → 아래 get_map. 프론트가 화면 진입 시 가장 먼저 부른다.
    연결: 상태 계산 → status_util.py. 받는 쪽(프론트) → frontend/app/app/[projectId]/page.tsx의 loadMap.
    """
    status_by_agent = agent_status_map(db, project.id)

    teams = (
        db.query(Team)
        .filter(Team.project_id == project.id)
        .order_by(Team.created_at)
        .all()
    )
    template_engine = {
        t.key: t.engine for t in db.query(TeamTemplate).all()
    }

    team_outs: list[TeamMapOut] = []
    for team in teams:
        agent_outs = [
            AgentMapOut(
                id=a.id,
                name=a.name,
                model_tier=a.model_tier,
                slot=a.slot,
                status=status_by_agent.get(a.id, "idle"),
            )
            for a in sorted(team.agents, key=lambda x: x.slot)
        ]
        team_outs.append(
            TeamMapOut(
                id=team.id,
                name=team.name,
                template_key=team.template_key,
                engine=template_engine.get(team.template_key, "crew"),
                room_x=team.room_x,
                room_y=team.room_y,
                agents=agent_outs,
            )
        )

    edges = db.query(Edge).filter(Edge.project_id == project.id).all()
    edge_outs = [EdgeMapOut.model_validate(e) for e in edges]

    return MapOut(
        project=ProjectOut.model_validate(project),
        paused=project.paused,
        teams=team_outs,
        edges=edge_outs,
    )


# --- Templates ---


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(
    user_id: str = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[TemplateOut]:
    """팀 템플릿 + 역할 카탈로그(D41). 앱은 auth-gated(D24) — 세션 필요(내용은 전역 시드로 동일)."""
    templates = db.query(TeamTemplate).order_by(TeamTemplate.key).all()
    out: list[TemplateOut] = []
    for t in templates:
        roles = [
            RoleTemplateOut.model_validate(r)
            for r in sorted(t.agent_templates, key=lambda r: (not r.is_starter, r.role_key))
        ]
        out.append(
            TemplateOut(
                key=t.key,
                name=t.name,
                description=t.description,
                engine=t.engine,
                roles=roles,
            )
        )
    return out


# --- Projects ---


# 무거운 쓰기(팀/에이전트 동시 생성) → 스팸 방어로 분당 30. 추가로 계정당 총량 캡(아래).
@router.post(
    "/projects",
    response_model=ProjectOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("30/minute", "project_create"))],
)
def create_project(
    body: ProjectCreate,
    user_id: str = Depends(require_user),
    db: Session = Depends(get_db),
) -> ProjectOut:
    """프로젝트 생성 — 새 사무실(프로젝트)을 만들고, 고른 팀들을 시작 멤버 1명씩과 함께 채운다.

    무슨 일을 하나: 온보딩에서 사용자가 고른 팀 템플릿(기획/리서치/디자인/개발)들을 바탕으로
        프로젝트 + 각 팀(방) + 각 팀의 '시작 에이전트' 1명을 한꺼번에 만든다.
    누가 부르나: 온보딩 마지막 단계 — frontend/app/onboarding/page.tsx.
    처리 순서:
        1. 고른 template_key들이 실제 존재하는지 검사(없으면 400).
        2. (온보딩이면) 사용자 프로필 이름 저장.
        3. 프로젝트 생성 → 각 팀을 2열 그리드 좌표에 배치 → 팀마다 starter 에이전트 1명 생성.
        4. 전부 한 트랜잭션(전부 성공 아니면 전부 취소하는 묶음)으로 commit. 중간 오류 시 통째 롤백.
    연결: 팀당 시작 1명이라 이 시점엔 연결선(엣지)이 없다. 이후 팀/에이전트 추가 → teams.py.
    """
    # 계정당 프로젝트 총량 캡 — 무한 누적 스팸 방어(rate-limit은 속도만 제한). 일반 사용엔 넉넉.
    if db.query(Project).filter(Project.user_id == user_id).count() >= MAX_PROJECTS_PER_USER:
        raise HTTPException(
            status_code=409, detail=f"project limit reached (max {MAX_PROJECTS_PER_USER})"
        )

    templates = {
        t.key: t for t in db.query(TeamTemplate).filter(TeamTemplate.key.in_(body.template_keys)).all()
    }
    missing = [k for k in body.template_keys if k not in templates]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown template(s): {missing}")

    try:
        # display_name이 오면 user_profile upsert(온보딩 step 2).
        if body.display_name:
            profile = db.get(UserProfile, user_id)
            if profile is None:
                db.add(UserProfile(user_id=user_id, display_name=body.display_name))
            else:
                profile.display_name = body.display_name

        # 가입 무료 크레딧(D46 B-5) — billing ON일 때만, 1계정 1회(grant_signup 멱등).
        from app.services import credit_service
        from app.services.config_store import load_config
        if load_config(db).billing_enabled:
            credit_service.grant_signup(db, user_id, credit_service.SIGNUP_CREDITS)

        project = Project(user_id=user_id, name=body.name)
        db.add(project)
        db.flush()

        # 선택 순서대로 팀을 2열 그리드에 배치.
        for idx, key in enumerate(body.template_keys):
            tmpl = templates[key]
            team = Team(
                project_id=project.id,
                template_key=key,
                name=tmpl.name,
                room_x=(idx % 2) * _ROOM_COL_W,
                room_y=(idx // 2) * _ROOM_ROW_H,
            )
            db.add(team)
            db.flush()

            starter = next((r for r in tmpl.agent_templates if r.is_starter), None)
            if starter is None:  # 시드 불변식 위반 방어(팀당 starter 1개).
                raise HTTPException(status_code=500, detail=f"Template {key} has no starter role")
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
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> list[ProjectOut]:
    """유저 프로젝트 목록(스위처용, 최신순)."""
    rows = (
        scope.query(db, Project).order_by(Project.created_at.desc()).all()
    )
    return [ProjectOut.model_validate(p) for p in rows]


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> ProjectOut:
    return ProjectOut.model_validate(load_owned_project(db, scope, project_id))


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def rename_project(
    project_id: uuid.UUID,
    body: ProjectPatch,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> ProjectOut:
    project = load_owned_project(db, scope, project_id)
    project.name = body.name
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    project = load_owned_project(db, scope, project_id)
    # 샌드박스 파기(D29) — DB cascade 전에 워크스페이스 + 프리뷰 샌드박스 정리.
    from app.services.preview import preview_service
    from app.services.workspace import workspace_service
    workspace_service.destroy(db, project)
    preview_service.destroy(db, project)  # 프리뷰 샌드박스도 파기(D49).
    # FK ON DELETE CASCADE가 teams/agents/edges/tasks/outputs 등 하위를 정리한다.
    db.delete(project)
    db.commit()


@router.post("/projects/{project_id}/pause", response_model=ProjectOut)
def pause_project(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> ProjectOut:
    project = load_owned_project(db, scope, project_id)
    project.paused = True
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.post("/projects/{project_id}/resume", response_model=ProjectOut)
def resume_project(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> ProjectOut:
    project = load_owned_project(db, scope, project_id)
    project.paused = False
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.get("/projects/{project_id}/map", response_model=MapOut)
def get_map(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> MapOut:
    project = load_owned_project(db, scope, project_id)
    return _build_map(db, project)


# --- Project files & version snapshots (Phase 2, D50) ---


@router.get("/projects/{project_id}/versions", response_model=list[WorkspaceVersionOut])
def list_versions(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> list[WorkspaceVersionOut]:
    """버전 스냅샷 목록(최신순, D50) — 시어터의 버전 칩 · Preview가 서빙하는 버전 표시."""
    load_owned_project(db, scope, project_id)  # 소유권(cross-user 404).
    versions = (
        db.query(WorkspaceVersion)
        .filter(WorkspaceVersion.project_id == project_id)
        .order_by(WorkspaceVersion.version_no.desc())
        .all()
    )
    # 버전을 만든 task의 에이전트를 한 번에 조회(칩 라벨용).
    task_ids = [v.task_id for v in versions if v.task_id is not None]
    agent_by_task: dict = {}
    if task_ids:
        for tid, aid in db.query(Task.id, Task.agent_id).filter(Task.id.in_(task_ids)).all():
            agent_by_task[tid] = aid
    return [
        WorkspaceVersionOut(
            version_no=v.version_no,
            task_id=v.task_id,
            agent_id=agent_by_task.get(v.task_id),
            file_count=len(v.manifest or {}),
            created_at=v.created_at,
        )
        for v in versions
    ]


@router.get("/projects/{project_id}/files", response_model=ProjectFilesOut)
def list_project_files(
    project_id: uuid.UUID,
    version: int | None = None,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> ProjectFilesOut:
    """프로젝트 canonical 파일 목록(D50). version 미지정=현재 상태(project_files),
    version 지정=그 스냅샷의 동결 매니페스트. Preview 머티리얼라이즈 · 파일 목록 표시에 사용."""
    load_owned_project(db, scope, project_id)

    if version is not None:
        ver = (
            db.query(WorkspaceVersion)
            .filter(
                WorkspaceVersion.project_id == project_id,
                WorkspaceVersion.version_no == version,
            )
            .one_or_none()
        )
        if ver is None:
            raise HTTPException(status_code=404, detail=f"version {version} not found")
        files = [
            ProjectFileEntry(path=p, output_id=uuid.UUID(oid))
            for p, oid in sorted((ver.manifest or {}).items())
        ]
        return ProjectFilesOut(version_no=ver.version_no, files=files)

    # 현재 상태 = project_files 매니페스트.
    rows = (
        db.query(ProjectFile)
        .filter(ProjectFile.project_id == project_id)
        .order_by(ProjectFile.path)
        .all()
    )
    latest = (
        db.query(func.max(WorkspaceVersion.version_no))
        .filter(WorkspaceVersion.project_id == project_id)
        .scalar()
    )
    return ProjectFilesOut(
        version_no=latest,
        files=[ProjectFileEntry(path=r.path, output_id=r.output_id) for r in rows],
    )
