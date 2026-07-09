"""Notes API — Board 밑 Notes 메뉴(issue 4). 프로젝트별 자유 텍스트 노트(마크다운).

- POST   /api/projects/{id}/notes   생성
- GET    /api/projects/{id}/notes   목록(최근 수정순)
- PATCH  /api/notes/{id}            수정(title/body)
- DELETE /api/notes/{id}            삭제

모든 엔드포인트는 소유권 게이트(load_owned_project / scope.owns) — 남의 프로젝트 노트는 404.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import TenantScope, tenant_scope
from app.db import get_db
from app.models import Note, Project
from app.ownership import load_owned_project
from app.schemas import NoteCreate, NoteOut, NoteUpdate

router = APIRouter(prefix="/api", tags=["notes"])


@router.post(
    "/projects/{project_id}/notes",
    response_model=NoteOut,
    status_code=status.HTTP_201_CREATED,
)
def create_note(
    project_id: uuid.UUID,
    body: NoteCreate,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> NoteOut:
    project = load_owned_project(db, scope, project_id)
    note = Note(project_id=project.id, title=body.title, body=body.body)
    db.add(note)
    db.commit()
    db.refresh(note)
    return NoteOut.model_validate(note)


@router.get("/projects/{project_id}/notes", response_model=list[NoteOut])
def list_notes(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> list[NoteOut]:
    project = load_owned_project(db, scope, project_id)
    rows = (
        db.query(Note)
        .filter(Note.project_id == project.id)
        .order_by(Note.updated_at.desc())
        .all()
    )
    return [NoteOut.model_validate(r) for r in rows]


def _load_owned_note(db: Session, scope: TenantScope, note_id: uuid.UUID) -> Note:
    note = db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    project = db.get(Project, note.project_id)
    if project is None or not scope.owns(project):
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(
    note_id: uuid.UUID,
    body: NoteUpdate,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> NoteOut:
    note = _load_owned_note(db, scope, note_id)
    note.title = body.title
    note.body = body.body
    db.commit()
    db.refresh(note)
    return NoteOut.model_validate(note)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    note_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    note = _load_owned_note(db, scope, note_id)
    db.delete(note)
    db.commit()
