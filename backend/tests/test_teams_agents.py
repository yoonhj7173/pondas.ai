"""Team + Agent management tests (item 7) — LIVE Postgres.

5캡 409, 슬롯 배정, 출력 엣지 동시 생성, working-게이트, 패널 페이로드, 외부 404를
실제 엔드포인트 + DB 조회로 검증한다.
"""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models import Agent, Project, Team
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


def _new_project(client, auth, sub, templates):
    r = client.post(
        "/api/projects",
        json={"name": "P", "template_keys": templates},
        headers=auth(sub),
    )
    return r.json()["id"]


def _team_id(client, auth, sub, pid, template_key):
    m = client.get(f"/api/projects/{pid}/map", headers=auth(sub)).json()
    return next(t["id"] for t in m["teams"] if t["template_key"] == template_key)


# --- Teams ---


def test_add_team_creates_room_and_starter(client, auth, made):
    sub = "t_add"
    pid = _new_project(client, auth, sub, ["planning"])
    made.append(uuid.UUID(pid))
    resp = client.post(f"/api/projects/{pid}/teams", json={"template_key": "design"}, headers=auth(sub))
    assert resp.status_code == 201, resp.text
    panel = resp.json()
    assert panel["template_key"] == "design"
    assert panel["engine"] == "agent_sdk"
    assert panel["agent_count"] == 1
    assert panel["agents"][0]["name"] == "Product Designer"


def test_team_rename_and_room_persist(client, auth, made):
    sub = "t_patch"
    pid = _new_project(client, auth, sub, ["planning"])
    made.append(uuid.UUID(pid))
    tid = _team_id(client, auth, sub, pid, "planning")
    resp = client.patch(f"/api/teams/{tid}", json={"name": "Renamed", "room_x": 123, "room_y": 456}, headers=auth(sub))
    assert resp.status_code == 200
    # 맵에서 좌표 영속 확인.
    m = client.get(f"/api/projects/{pid}/map", headers=auth(sub)).json()
    team = next(t for t in m["teams"] if t["id"] == tid)
    assert team["name"] == "Renamed"
    assert (team["room_x"], team["room_y"]) == (123, 456)


def test_delete_team_cascades(client, auth, made):
    sub = "t_del"
    pid = _new_project(client, auth, sub, ["planning", "development"])
    made.append(uuid.UUID(pid))
    tid = _team_id(client, auth, sub, pid, "development")
    assert client.delete(f"/api/teams/{tid}", headers=auth(sub)).status_code == 204
    db = SessionLocal()
    try:
        assert db.get(Team, uuid.UUID(tid)) is None
        assert db.query(Agent).filter_by(team_id=uuid.UUID(tid)).count() == 0
    finally:
        db.close()


def test_team_foreign_404(client, auth, made):
    pid = _new_project(client, auth, "t_owner", ["planning"])
    made.append(uuid.UUID(pid))
    tid = _team_id(client, auth, "t_owner", pid, "planning")
    assert client.get(f"/api/teams/{tid}", headers=auth("t_intruder")).status_code == 404


# --- Agents ---


def test_add_agent_assigns_next_slot(client, auth, made):
    sub = "a_slot"
    pid = _new_project(client, auth, sub, ["planning"])
    made.append(uuid.UUID(pid))
    tid = _team_id(client, auth, sub, pid, "planning")  # starter at slot 0
    resp = client.post(
        f"/api/teams/{tid}/agents",
        json={"name": "Spec Writer", "role_instructions": "write specs", "model_tier": "medium"},
        headers=auth(sub),
    )
    assert resp.status_code == 201, resp.text
    panel = client.get(f"/api/teams/{tid}", headers=auth(sub)).json()
    assert panel["agent_count"] == 2
    slots = sorted(a["slot"] for a in panel["agents"])
    assert slots == [0, 1]


def test_sixth_agent_rejected_409(client, auth, made):
    sub = "a_cap"
    pid = _new_project(client, auth, sub, ["development"])
    made.append(uuid.UUID(pid))
    tid = _team_id(client, auth, sub, pid, "development")  # 1 starter
    # 4명 더 추가 → 5명.
    for i in range(4):
        r = client.post(
            f"/api/teams/{tid}/agents",
            json={"name": f"Dev{i}", "role_instructions": "x", "model_tier": "medium"},
            headers=auth(sub),
        )
        assert r.status_code == 201, r.text
    # 6번째 → 409.
    r6 = client.post(
        f"/api/teams/{tid}/agents",
        json={"name": "Dev6", "role_instructions": "x", "model_tier": "medium"},
        headers=auth(sub),
    )
    assert r6.status_code == 409
    assert "full" in r6.json()["detail"].lower()


def test_add_agent_with_output_edge(client, auth, made):
    sub = "a_out"
    pid = _new_project(client, auth, sub, ["development"])
    made.append(uuid.UUID(pid))
    tid = _team_id(client, auth, sub, pid, "development")
    # starter SWE의 id.
    swe = client.get(f"/api/teams/{tid}", headers=auth(sub)).json()["agents"][0]
    # QA 추가하면서 SWE로 review_loop 출력.
    resp = client.post(
        f"/api/teams/{tid}/agents",
        json={
            "name": "QA", "role_instructions": "verify", "model_tier": "medium",
            "output": {"type": "review_loop", "to_agent_id": swe["id"], "max_iterations": 5},
        },
        headers=auth(sub),
    )
    assert resp.status_code == 201, resp.text
    panel = resp.json()
    assert panel["outgoing"]["type"] == "review_loop"
    assert panel["outgoing"]["to_agent_id"] == swe["id"]
    assert panel["outgoing"]["max_iterations"] == 5


def test_tier_edit_reflected_in_map(client, auth, made):
    sub = "a_tier"
    pid = _new_project(client, auth, sub, ["planning"])
    made.append(uuid.UUID(pid))
    tid = _team_id(client, auth, sub, pid, "planning")
    aid = client.get(f"/api/teams/{tid}", headers=auth(sub)).json()["agents"][0]["id"]
    assert client.patch(f"/api/agents/{aid}", json={"model_tier": "light"}, headers=auth(sub)).status_code == 200
    m = client.get(f"/api/projects/{pid}/map", headers=auth(sub)).json()
    agent = m["teams"][0]["agents"][0]
    assert agent["model_tier"] == "light"


def test_delete_agent_drops_edges(client, auth, made):
    sub = "a_deledge"
    pid = _new_project(client, auth, sub, ["development"])
    made.append(uuid.UUID(pid))
    tid = _team_id(client, auth, sub, pid, "development")
    swe = client.get(f"/api/teams/{tid}", headers=auth(sub)).json()["agents"][0]
    qa = client.post(
        f"/api/teams/{tid}/agents",
        json={"name": "QA", "role_instructions": "v", "model_tier": "medium",
              "output": {"type": "review_loop", "to_agent_id": swe["id"], "max_iterations": 3}},
        headers=auth(sub),
    ).json()
    # QA 삭제 → 엣지도 사라짐, map.edges 비어야.
    assert client.delete(f"/api/agents/{qa['id']}", headers=auth(sub)).status_code == 204
    m = client.get(f"/api/projects/{pid}/map", headers=auth(sub)).json()
    assert m["edges"] == []


def test_agent_panel_payload(client, auth, made):
    sub = "a_panel"
    pid = _new_project(client, auth, sub, ["planning"])
    made.append(uuid.UUID(pid))
    tid = _team_id(client, auth, sub, pid, "planning")
    aid = client.get(f"/api/teams/{tid}", headers=auth(sub)).json()["agents"][0]["id"]
    panel = client.get(f"/api/agents/{aid}", headers=auth(sub)).json()
    assert panel["name"] == "Product Manager"
    assert panel["model_tier"] == "strong"
    assert panel["status"] == "idle"
    assert panel["outgoing"] is None  # starter = Final
    assert panel["incoming"] == []
