"""Projects API + template cloning tests (item 6) — LIVE Postgres.

실제 엔드포인트를 TestClient로 호출해 라이브 DB에 행이 만들어지고 맵에 반영되는지,
교차 사용자 404, 삭제 cascade가 실제로 동작하는지 검증한다(목 아님).
"""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models import Agent, Edge, Project, Team
from seed import seed


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    """템플릿 시드가 존재함을 보장(GET /templates / 클론 전제)."""
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


@pytest.fixture
def made():
    """생성한 project id를 모아 테스트 종료 시 정리(cascade)."""
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


def _create(client, auth, sub, **body):
    body.setdefault("name", "Test Project")
    body.setdefault("template_keys", ["planning", "development"])
    return client.post("/api/projects", json=body, headers=auth(sub))


# --- Templates ---


def test_templates_returns_4_teams_11_roles(client, auth):
    resp = client.get("/api/templates", headers=auth("user_tpl"))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert {t["key"] for t in data} == {"planning", "research", "design", "development"}
    roles_total = sum(len(t["roles"]) for t in data)
    assert roles_total == 11
    dev = next(t for t in data if t["key"] == "development")
    assert dev["engine"] == "agent_sdk"
    assert len(dev["roles"]) == 5
    assert sum(1 for r in dev["roles"] if r["is_starter"]) == 1


def test_templates_requires_auth(client):
    assert client.get("/api/templates").status_code == 401


# --- Create / clone ---


def test_create_clones_one_starter_per_team_no_edges(client, auth, made):
    resp = _create(client, auth, "user_clone", template_keys=["planning", "development"])
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    made.append(uuid.UUID(pid))

    m = client.get(f"/api/projects/{pid}/map", headers=auth("user_clone")).json()
    assert {t["template_key"] for t in m["teams"]} == {"planning", "development"}
    # 팀당 starter 1명, 엣지 0개(D37/D38).
    for team in m["teams"]:
        assert len(team["agents"]) == 1
        assert team["agents"][0]["status"] == "idle"
    assert m["edges"] == []
    planning = next(t for t in m["teams"] if t["template_key"] == "planning")
    assert planning["engine"] == "crew"
    assert planning["agents"][0]["name"] == "Product Manager"
    assert planning["agents"][0]["model_tier"] == "medium"  # opus=premium upsell; defaults dropped to sonnet
    dev = next(t for t in m["teams"] if t["template_key"] == "development")
    assert dev["engine"] == "agent_sdk"
    assert dev["agents"][0]["name"] == "Software Engineer"
    # 방 좌표는 서로 다름(겹침 방지).
    assert (planning["room_x"], planning["room_y"]) != (dev["room_x"], dev["room_y"])


def test_team_card_status_and_summary(client, auth, made):
    """팀 카드 pill + 1줄 요약(영어) — needs-input(질문) / done(goal 제목) / idle(task 없음)."""
    from app.models import Agent, Goal
    from app.services import task_service as ts

    resp = _create(client, auth, "user_card", template_keys=["research", "development", "design"])
    pid = uuid.UUID(resp.json()["id"]); made.append(pid)
    m = client.get(f"/api/projects/{pid}/map", headers=auth("user_card")).json()
    res = next(t for t in m["teams"] if t["template_key"] == "research")
    dev = next(t for t in m["teams"] if t["template_key"] == "development")
    des = next(t for t in m["teams"] if t["template_key"] == "design")

    db = SessionLocal()
    try:
        # Research → needs-input(질문)
        res_agent = db.get(Agent, uuid.UUID(res["agents"][0]["id"]))
        t1 = ts.create_task(db, user_id="user_card", project_id=pid, agent=res_agent,
                            instructions="research", origin="chat")
        t1.status = "needs-input"; t1.awaiting_prompt = "Which region should I focus on first?"
        # Development → done(goal 제목)
        g = Goal(project_id=pid, title="Bean There landing page"); db.add(g); db.flush()
        dev_agent = db.get(Agent, uuid.UUID(dev["agents"][0]["id"]))
        t2 = ts.create_task(db, user_id="user_card", project_id=pid, agent=dev_agent,
                            instructions="build", origin="chat")
        t2.status = "done"; t2.goal_id = g.id
        db.commit()
    finally:
        db.close()

    m2 = client.get(f"/api/projects/{pid}/map", headers=auth("user_card")).json()
    res2 = next(t for t in m2["teams"] if t["template_key"] == "research")
    dev2 = next(t for t in m2["teams"] if t["template_key"] == "development")
    des2 = next(t for t in m2["teams"] if t["template_key"] == "design")
    assert res2["status"] == "needs-input" and res2["summary"] == "Which region should I focus on first?"
    assert dev2["status"] == "done" and dev2["summary"] == "Bean There landing page"
    assert des2["status"] == "idle" and des2["summary"] is None  # task 없음


def test_create_persists_real_rows(client, auth, made):
    resp = _create(client, auth, "user_rows", template_keys=["research"])
    pid = uuid.UUID(resp.json()["id"])
    made.append(pid)
    db = SessionLocal()
    try:
        assert db.query(Team).filter_by(project_id=pid).count() == 1
        assert db.query(Agent).filter_by(project_id=pid).count() == 1
        agent = db.query(Agent).filter_by(project_id=pid).one()
        assert agent.name == "Researcher"  # research starter
        assert agent.slot == 0
    finally:
        db.close()


def test_create_unknown_template_400_and_rollback(client, auth, made):
    resp = _create(client, auth, "user_bad", template_keys=["planning", "nope"])
    assert resp.status_code == 400
    db = SessionLocal()
    try:
        # 롤백되어 user의 프로젝트가 0이어야 한다.
        assert db.query(Project).filter_by(user_id="user_bad").count() == 0
    finally:
        db.close()


def test_create_requires_at_least_one_template(client, auth):
    resp = client.post(
        "/api/projects", json={"name": "x", "template_keys": []}, headers=auth("user_empty")
    )
    assert resp.status_code == 422  # pydantic min_length


def test_display_name_upserts_profile(client, auth, made):
    resp = _create(client, auth, "user_dn", display_name="Jane", template_keys=["design"])
    made.append(uuid.UUID(resp.json()["id"]))
    from app.models import UserProfile

    db = SessionLocal()
    try:
        prof = db.get(UserProfile, "user_dn")
        assert prof is not None and prof.display_name == "Jane"
    finally:
        db.close()


# --- Ownership / isolation ---


def test_foreign_project_404(client, auth, made):
    pid = _create(client, auth, "owner_a").json()["id"]
    made.append(uuid.UUID(pid))
    # 다른 사용자는 존재를 못 본다(404).
    assert client.get(f"/api/projects/{pid}", headers=auth("intruder_b")).status_code == 404
    assert client.get(f"/api/projects/{pid}/map", headers=auth("intruder_b")).status_code == 404


def test_list_scoped_to_user(client, auth, made):
    p1 = _create(client, auth, "lister", template_keys=["planning"]).json()["id"]
    made.append(uuid.UUID(p1))
    rows = client.get("/api/projects", headers=auth("lister")).json()
    assert {r["id"] for r in rows} == {p1}
    # 다른 유저는 빈 목록.
    assert client.get("/api/projects", headers=auth("other_lister")).json() == []


def test_projects_require_auth(client):
    assert client.get("/api/projects").status_code == 401


# --- Mutations ---


def test_rename(client, auth, made):
    pid = _create(client, auth, "renamer").json()["id"]
    made.append(uuid.UUID(pid))
    resp = client.patch(f"/api/projects/{pid}", json={"name": "Renamed"}, headers=auth("renamer"))
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"


def test_pause_resume_toggles(client, auth, made):
    pid = _create(client, auth, "pauser").json()["id"]
    made.append(uuid.UUID(pid))
    assert client.post(f"/api/projects/{pid}/pause", headers=auth("pauser")).json()["paused"] is True
    assert client.post(f"/api/projects/{pid}/resume", headers=auth("pauser")).json()["paused"] is False


def test_delete_cascades(client, auth):
    pid = _create(client, auth, "deleter", template_keys=["planning", "development"]).json()["id"]
    puid = uuid.UUID(pid)
    resp = client.delete(f"/api/projects/{pid}", headers=auth("deleter"))
    assert resp.status_code == 204
    assert client.get(f"/api/projects/{pid}", headers=auth("deleter")).status_code == 404
    db = SessionLocal()
    try:
        # cascade로 teams/agents/edges 실제 삭제 확인.
        assert db.query(Team).filter_by(project_id=puid).count() == 0
        assert db.query(Agent).filter_by(project_id=puid).count() == 0
        assert db.query(Edge).filter_by(project_id=puid).count() == 0
    finally:
        db.close()
