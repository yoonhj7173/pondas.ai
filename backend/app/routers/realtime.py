"""SSE + Notifications + Board + Usage (item 12, tech-design §6/§12).

- GET  /api/projects/{id}/sse           SSE 스트림(project:{id} 채널 중계 + heartbeat)
- GET  /api/notifications               알림 목록(미읽음 먼저)
- POST /api/notifications/read-all       전체 읽음
- POST /api/notifications/{id}/read      개별 읽음
- GET  /api/projects/{id}/board          goals × tasks 투영(D20)
- GET  /api/projects/{id}/usage          토큰/비용 합계 + 팀별/에이전트별(D12)

SSE 인증은 ?token= 쿼리(EventSource 헤더 제약) — auth.require_user가 지원.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import TenantScope, require_user, tenant_scope
from app.db import get_db, redis_client
from app.models import Agent, Goal, Notification, Task, Team
from app.ownership import load_owned_project
from app.schemas import (
    BoardGoalOut,
    BoardOut,
    BoardTaskOut,
    NotificationOut,
    UsageBucketOut,
    UsageOut,
)

router = APIRouter(prefix="/api", tags=["realtime"])

_HEARTBEAT_SEC = 15


@router.get("/projects/{project_id}/sse")
def sse(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """실시간 스트림(SSE) — 화면을 새로고침 없이 살아있게 만드는 '서버→브라우저' 단방향 통로.

    PM 한 줄: SSE(Server-Sent Events = 서버가 답을 한 번에 안 주고 조각조각 계속 밀어보내는 방식).
        이 연결 하나를 열어두면, 에이전트 상태가 바뀔 때마다 서버가 브라우저로 "방금 누가 일 시작했어"
        같은 이벤트를 밀어준다 → 맵 위 캐릭터가 실시간으로 움직이고 알림 벨이 울린다.
    무슨 일을 하나: Redis의 project:{id} 채널을 구독해, 거기 올라오는 이벤트를 그대로 브라우저로 흘려보낸다.
        조용할 때도 15초마다 heartbeat(살아있다는 신호)를 보내 연결이 끊기지 않게 한다.
    누가 부르나: 프론트의 EventSource — frontend/lib/sse.ts의 connectSSE.
    처리 순서: 1) 소유권 확인 2) Redis 채널 구독 3) 메시지 오면 'data: ...'로 전송, 없으면 heartbeat.
    연결: 이 채널에 이벤트를 올리는 쪽(발행) → backend/app/services/events.py.
        받아서 화면에 반영하는 쪽 → frontend/lib/sse.ts + store.ts.
    """
    load_owned_project(db, scope, project_id)

    def gen():
        pubsub = redis_client.pubsub()
        pubsub.subscribe(f"project:{project_id}")
        try:
            yield ": connected\n\n"
            last = time.time()
            while True:
                msg = pubsub.get_message(timeout=1.0)
                if msg and msg["type"] == "message":
                    yield f"data: {msg['data']}\n\n"
                    last = time.time()
                elif time.time() - last > _HEARTBEAT_SEC:
                    yield ": heartbeat\n\n"
                    last = time.time()
        finally:
            pubsub.close()

    return StreamingResponse(gen(), media_type="text/event-stream")


# --- Notifications ---


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    user_id: str = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[NotificationOut]:
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.read, Notification.created_at.desc())
        .limit(100)
        .all()
    )
    return [NotificationOut.model_validate(r) for r in rows]


@router.post("/notifications/read-all", status_code=204)
def mark_all_read(
    user_id: str = Depends(require_user),
    db: Session = Depends(get_db),
) -> None:
    db.query(Notification).filter(
        Notification.user_id == user_id, Notification.read.is_(False)
    ).update({Notification.read: True})
    db.commit()


@router.post("/notifications/{notif_id}/read", status_code=204)
def mark_read(
    notif_id: uuid.UUID,
    user_id: str = Depends(require_user),
    db: Session = Depends(get_db),
) -> None:
    row = db.get(Notification, notif_id)
    if row is not None and row.user_id == user_id:
        row.read = True
        db.commit()


# --- Board ---


@router.get("/projects/{project_id}/board", response_model=BoardOut)
def board(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> BoardOut:
    """보드 데이터 — 칸반처럼 '목표별로 묶인 작업 목록'을 만들어 보드 화면에 보여준다.

    무슨 일을 하나: 프로젝트의 모든 작업을 목표(goal)별로 묶어서 돌려준다. 목표에 안 묶인 작업은
        'Unassigned'(미배정) 그룹으로 모은다. 각 작업엔 담당 에이전트 이름과 현재 상태가 붙는다.
    누가 부르나: 보드 오버레이 — frontend/components/overlays/Overlays.tsx의 BoardOverlay.
    """
    project = load_owned_project(db, scope, project_id)
    agent_names = {a.id: a.name for a in db.query(Agent).filter(Agent.project_id == project.id).all()}
    tasks = (
        db.query(Task)
        .filter(Task.project_id == project.id)
        .order_by(Task.created_at)
        .all()
    )
    goals = db.query(Goal).filter(Goal.project_id == project.id).order_by(Goal.created_at).all()

    def task_out(t: Task) -> BoardTaskOut:
        return BoardTaskOut(
            id=t.id, agent_id=t.agent_id,
            agent_name=agent_names.get(t.agent_id, "(removed)"),
            status=t.status, instructions=t.instructions,
        )

    by_goal: dict = {}
    for t in tasks:
        by_goal.setdefault(t.goal_id, []).append(t)

    out_goals: list[BoardGoalOut] = []
    for g in goals:
        out_goals.append(BoardGoalOut(id=g.id, title=g.title, tasks=[task_out(t) for t in by_goal.get(g.id, [])]))
    if None in by_goal:
        out_goals.append(BoardGoalOut(id=None, title="Unassigned", tasks=[task_out(t) for t in by_goal[None]]))
    return BoardOut(goals=out_goals)


# --- Usage ---


@router.get("/projects/{project_id}/usage", response_model=UsageOut)
def usage(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> UsageOut:
    """사용량/비용 집계 — 이 프로젝트가 LLM을 얼마나 썼는지(토큰·달러)를 합산해 보여준다.

    무슨 일을 하나: 모든 작업의 토큰 수와 추정 비용을 합쳐 전체 합계 + 에이전트별 + 팀별로 묶는다.
        비용은 작업이 끝날 때 이미 계산돼 저장돼 있어(model_used×단가) 여기선 그냥 더하기만 한다.
    누가 부르나: 설정/사용량 화면 — frontend/components/overlays/Overlays.tsx의 SettingsOverlay.
    """
    project = load_owned_project(db, scope, project_id)

    # 에이전트별 합.
    rows = (
        db.query(
            Task.agent_id,
            func.coalesce(func.sum(Task.tokens_in), 0),
            func.coalesce(func.sum(Task.tokens_out), 0),
            func.coalesce(func.sum(Task.est_cost_usd), 0),
        )
        .filter(Task.project_id == project.id)
        .group_by(Task.agent_id)
        .all()
    )
    agents = {a.id: a for a in db.query(Agent).filter(Agent.project_id == project.id).all()}
    teams = {t.id: t for t in db.query(Team).filter(Team.project_id == project.id).all()}

    by_agent: list[UsageBucketOut] = []
    team_acc: dict = {}
    tin = tout = 0
    cost = 0.0
    for agent_id, ti, to, c in rows:
        ti, to, c = int(ti), int(to), float(c)
        tin += ti; tout += to; cost += c
        agent = agents.get(agent_id)
        by_agent.append(UsageBucketOut(
            id=agent_id, name=agent.name if agent else "(removed)",
            tokens_in=ti, tokens_out=to, cost_usd=round(c, 6),
        ))
        if agent is not None:
            acc = team_acc.setdefault(agent.team_id, [0, 0, 0.0])
            acc[0] += ti; acc[1] += to; acc[2] += c

    by_team = [
        UsageBucketOut(
            id=team_id, name=teams[team_id].name if team_id in teams else "(removed)",
            tokens_in=v[0], tokens_out=v[1], cost_usd=round(v[2], 6),
        )
        for team_id, v in team_acc.items()
    ]

    # 오늘(UTC 자정 이후 생성) task만 별도 합 — 팝오버의 "Tokens today".
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_in, today_out = (
        db.query(
            func.coalesce(func.sum(Task.tokens_in), 0),
            func.coalesce(func.sum(Task.tokens_out), 0),
        )
        .filter(Task.project_id == project.id, Task.created_at >= today_start)
        .one()
    )

    return UsageOut(
        total_tokens_in=tin, total_tokens_out=tout, total_cost_usd=round(cost, 6),
        today_tokens_in=int(today_in), today_tokens_out=int(today_out),
        by_team=by_team, by_agent=by_agent,
    )
