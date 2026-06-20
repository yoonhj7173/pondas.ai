"""Orchestrator chat API (item 13, D3).

- POST /api/projects/{id}/chat          freeform 메시지 → 오케스트레이터 1턴 → {reply, actions}
- GET  /api/projects/{id}/chat/history  대화 히스토리(시간순)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import TenantScope, require_user, tenant_scope
from app.db import get_db
from app.models import OrchestratorMessage
from app.ownership import load_owned_project
from app.ratelimit import rate_limit
from app.schemas import NonBlankStr
from app.services.orchestrator import run_chat

router = APIRouter(prefix="/api", tags=["chat"])


class ChatIn(BaseModel):
    message: NonBlankStr = Field(min_length=1, max_length=8000)


class ChatOut(BaseModel):
    reply: str
    actions: list


class ChatMessageOut(BaseModel):
    role: str
    content: str


# LLM을 돌려 비용이 큰 입구 → 전역 120/min보다 빡세게 분당 20(비용 폭발 방어, ABUSE-BUG-3 follow-up).
@router.post(
    "/projects/{project_id}/chat",
    response_model=ChatOut,
    dependencies=[Depends(rate_limit("20/minute", "chat"))],
)
def chat(
    project_id: uuid.UUID,
    body: ChatIn,
    user_id: str = Depends(require_user),
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> ChatOut:
    """채팅 보내기 입구 — 사용자의 한 마디를 받아 오케스트레이터(작업 지휘자)를 1턴 돌린다.

    무슨 일을 하나: 화면 하단 채팅창에 사용자가 "리서치팀에 경쟁사 조사 시켜줘" 같은
        자유 문장을 쓰면 여기로 들어온다. 그 문장을 작업 지휘자(orchestrator)에게 넘겨
        실제로 goal/task를 만들고 에이전트에게 일을 던지게 한 뒤, 지휘자의 답변을 돌려준다.
    누가 부르나: 프론트엔드 sendChat() — frontend/app/app/[projectId]/page.tsx.
    처리 순서:
        1. require_user / tenant_scope: Clerk 로그인 토큰을 까서 "누구인지" 확인(= Spring Security).
        2. load_owned_project: 이 프로젝트가 정말 이 사용자 것인지 검사(소유권 격리).
           남의 프로젝트 id를 넣으면 여기서 404로 막힌다.
        3. run_chat: 핵심 두뇌 호출. {reply(지휘자 답변), actions(이번에 한 일 목록)} 반환.
    연결: 이 함수가 부르는 run_chat이 실질적 두뇌 → backend/app/services/orchestrator.py.
        (= Spring으로 치면 이 함수는 @RestController, run_chat은 @Service)
    """
    load_owned_project(db, scope, project_id)
    result = run_chat(db, project_id, user_id, body.message)
    return ChatOut(reply=result["reply"], actions=result["actions"])


@router.get("/projects/{project_id}/chat/history", response_model=list[ChatMessageOut])
def history(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> list[ChatMessageOut]:
    """채팅 기록 불러오기 — 그동안 사용자와 지휘자가 주고받은 대화를 시간순으로 돌려준다.

    무슨 일을 하나: 프로젝트를 다시 열었을 때 이전 대화가 채팅창에 다시 보이도록,
        orchestrator_messages 테이블에 쌓인 메시지(role=user/orchestrator)를 오래된 순으로 읽어온다.
    누가 부르나: 프론트엔드가 채팅창을 처음 띄울 때.
    연결: 메시지가 저장되는 곳은 run_chat 끝부분 → backend/app/services/orchestrator.py.
    """
    project = load_owned_project(db, scope, project_id)
    rows = (
        db.query(OrchestratorMessage)
        .filter(OrchestratorMessage.project_id == project.id)
        .order_by(OrchestratorMessage.created_at)
        .all()
    )
    return [ChatMessageOut(role=r.role, content=r.content) for r in rows]
