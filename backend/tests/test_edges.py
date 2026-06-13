"""Edge management tests (item 7) — LIVE Postgres.

출력 1개(D38), 사이클 거부(D25), loop N(D19), self-edge, 삭제를 실제 엔드포인트로 검증.
"""

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


def _setup_three_agents(client, auth, sub, made):
    """development 팀에 SWE(starter) + A + B 3명을 만들고 id를 돌려준다."""
    pid = client.post(
        "/api/projects", json={"name": "P", "template_keys": ["development"]}, headers=auth(sub)
    ).json()["id"]
    made.append(uuid.UUID(pid))
    m = client.get(f"/api/projects/{pid}/map", headers=auth(sub)).json()
    tid = m["teams"][0]["id"]
    swe = m["teams"][0]["agents"][0]["id"]
    a = client.post(f"/api/teams/{tid}/agents", json={"name": "A", "role_instructions": "x", "model_tier": "medium"}, headers=auth(sub)).json()["id"]
    b = client.post(f"/api/teams/{tid}/agents", json={"name": "B", "role_instructions": "x", "model_tier": "medium"}, headers=auth(sub)).json()["id"]
    return pid, swe, a, b


def _mk_edge(client, auth, sub, pid, frm, to, type_="handoff", n=None):
    body = {"from_agent_id": frm, "to_agent_id": to, "type": type_}
    if n is not None:
        body["max_iterations"] = n
    return client.post(f"/api/projects/{pid}/edges", json=body, headers=auth(sub))


def test_create_handoff_edge(client, auth, made):
    sub = "e_ok"
    pid, swe, a, b = _setup_three_agents(client, auth, sub, made)
    r = _mk_edge(client, auth, sub, pid, swe, a)
    assert r.status_code == 201, r.text
    assert r.json()["type"] == "handoff"


def test_second_outgoing_edge_rejected_409(client, auth, made):
    sub = "e_one"
    pid, swe, a, b = _setup_three_agents(client, auth, sub, made)
    assert _mk_edge(client, auth, sub, pid, swe, a).status_code == 201
    # SWE는 이미 출력 있음 → 두 번째는 409(D38).
    r = _mk_edge(client, auth, sub, pid, swe, b)
    assert r.status_code == 409, r.text


def test_cycle_rejected_400(client, auth, made):
    sub = "e_cycle"
    pid, swe, a, b = _setup_three_agents(client, auth, sub, made)
    # SWE→A, A→B 체인.
    assert _mk_edge(client, auth, sub, pid, swe, a).status_code == 201
    assert _mk_edge(client, auth, sub, pid, a, b).status_code == 201
    # B→SWE 는 사이클을 닫음 → 400(D25).
    r = _mk_edge(client, auth, sub, pid, b, swe)
    assert r.status_code == 400, r.text
    assert "cycle" in r.json()["detail"].lower()


def test_review_loop_back_edge_allowed(client, auth, made):
    """review_loop는 양방향이라 cycle 검사 대상 아님 — SWE→A handoff 후 A→SWE review_loop 허용."""
    sub = "e_loop"
    pid, swe, a, b = _setup_three_agents(client, auth, sub, made)
    assert _mk_edge(client, auth, sub, pid, swe, a).status_code == 201
    r = _mk_edge(client, auth, sub, pid, a, swe, type_="review_loop", n=5)
    assert r.status_code == 201, r.text


def test_review_loop_requires_n_range(client, auth, made):
    sub = "e_n"
    pid, swe, a, b = _setup_three_agents(client, auth, sub, made)
    assert _mk_edge(client, auth, sub, pid, swe, a, type_="review_loop").status_code == 422  # N 없음
    assert _mk_edge(client, auth, sub, pid, swe, a, type_="review_loop", n=0).status_code == 422
    assert _mk_edge(client, auth, sub, pid, swe, a, type_="review_loop", n=11).status_code == 422


def test_self_edge_rejected(client, auth, made):
    sub = "e_self"
    pid, swe, a, b = _setup_three_agents(client, auth, sub, made)
    assert _mk_edge(client, auth, sub, pid, swe, swe).status_code == 422


def test_delete_edge(client, auth, made):
    sub = "e_del"
    pid, swe, a, b = _setup_three_agents(client, auth, sub, made)
    eid = _mk_edge(client, auth, sub, pid, swe, a).json()["id"]
    assert client.delete(f"/api/edges/{eid}", headers=auth(sub)).status_code == 204
    m = client.get(f"/api/projects/{pid}/map", headers=auth(sub)).json()
    assert m["edges"] == []
    # 삭제 후 다시 출력 추가 가능(one-outgoing 해제 확인).
    assert _mk_edge(client, auth, sub, pid, swe, b).status_code == 201


def test_edge_foreign_404(client, auth, made):
    sub = "e_owner"
    pid, swe, a, b = _setup_three_agents(client, auth, sub, made)
    eid = _mk_edge(client, auth, sub, pid, swe, a).json()["id"]
    assert client.delete(f"/api/edges/{eid}", headers=auth("e_intruder")).status_code == 404
