"""Notes tests (issue 4) — LIVE Postgres. CRUD + tenant isolation."""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models import Project
from seed import seed


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


@pytest.fixture
def made():
    ids: list[uuid.UUID] = []
    yield ids
    db = SessionLocal()
    try:
        for pid in ids:
            obj = db.get(Project, pid)
            if obj is not None:
                db.delete(obj)
        db.commit()
    finally:
        db.close()


def _project(client, auth, sub):
    return client.post(
        "/api/projects", json={"name": "P", "template_keys": ["planning"]}, headers=auth(sub)
    ).json()["id"]


def test_notes_crud(client, auth, made):
    sub = "n_crud"
    pid = _project(client, auth, sub)
    made.append(uuid.UUID(pid))

    # 생성
    created = client.post(
        f"/api/projects/{pid}/notes",
        json={"title": "Ideas", "body": "- one\n- two\n1. first"},
        headers=auth(sub),
    )
    assert created.status_code == 201, created.text
    nid = created.json()["id"]

    # 목록
    listing = client.get(f"/api/projects/{pid}/notes", headers=auth(sub)).json()
    assert len(listing) == 1 and listing[0]["title"] == "Ideas"

    # 수정
    upd = client.patch(f"/api/notes/{nid}", json={"title": "Ideas v2", "body": "updated"}, headers=auth(sub))
    assert upd.status_code == 200 and upd.json()["title"] == "Ideas v2"

    # 삭제
    assert client.delete(f"/api/notes/{nid}", headers=auth(sub)).status_code == 204
    assert client.get(f"/api/projects/{pid}/notes", headers=auth(sub)).json() == []


def test_notes_empty_allowed(client, auth, made):
    # 빈 노트 생성 허용(제목/본문 없이).
    sub = "n_empty"
    pid = _project(client, auth, sub)
    made.append(uuid.UUID(pid))
    r = client.post(f"/api/projects/{pid}/notes", json={}, headers=auth(sub))
    assert r.status_code == 201 and r.json()["title"] == "" and r.json()["body"] == ""


def test_notes_tenant_isolation(client, auth, made):
    # 남의 프로젝트 노트는 보이지도/수정/삭제되지도 않음(404).
    owner = "n_owner"
    pid = _project(client, auth, owner)
    made.append(uuid.UUID(pid))
    nid = client.post(f"/api/projects/{pid}/notes", json={"title": "secret"}, headers=auth(owner)).json()["id"]

    intruder = "n_intruder"
    assert client.get(f"/api/projects/{pid}/notes", headers=auth(intruder)).status_code == 404
    assert client.patch(f"/api/notes/{nid}", json={"title": "hacked", "body": ""}, headers=auth(intruder)).status_code == 404
    assert client.delete(f"/api/notes/{nid}", headers=auth(intruder)).status_code == 404


def test_notes_bad_input_rejected(client, auth, made):
    # 널바이트 → 422(SafeStr).
    sub = "n_bad"
    pid = _project(client, auth, sub)
    made.append(uuid.UUID(pid))
    r = client.post(f"/api/projects/{pid}/notes", json={"title": "ok", "body": "bad\x00byte"}, headers=auth(sub))
    assert r.status_code == 422
