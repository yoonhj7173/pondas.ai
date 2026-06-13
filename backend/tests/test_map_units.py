"""Map/topology read API tests (item 5) — GET /map, GET /units/{id}.

인증은 test_auth.py가 확립한 로컬 RSA 키페어 + stub JWKS 패턴을 재사용한다(실 Clerk
인스턴스 의존 없이 서명 검증 경로를 그대로 통과). DB는 라이브 Postgres(시드된 4/8).

검증 포인트:
- GET /map → 시드된 4 clusters / 8 units, positions/roles 포함.
- 인증 없음 → 401.
- GET /units/{id} task 없음 → status 'idle', task=None.
- task row를 직접 넣으면 그 권위 status가 반영된다.
- 교차 사용자 task는 안 보인다(tenant scope).
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import ClerkTokenVerifier, get_verifier
from app.db import SessionLocal
from app.main import app
from app.models import Task, Unit

TEST_ISSUER = "https://test-instance.clerk.accounts.dev"
TEST_JWKS_URL = f"{TEST_ISSUER}/.well-known/jwks.json"
KID = "test-kid-1"

_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks_json() -> str:
    pub_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(_priv.public_key(), as_dict=True)
    pub_jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return json.dumps({"keys": [pub_jwk]})


@pytest.fixture
def stub_jwks(monkeypatch):
    def fake_fetch_data(self):
        return json.loads(_jwks_json())

    monkeypatch.setattr("jwt.PyJWKClient.fetch_data", fake_fetch_data)


def _verifier() -> ClerkTokenVerifier:
    return ClerkTokenVerifier(issuer=TEST_ISSUER, jwks_url=TEST_JWKS_URL)


def _make_token(*, sub: str) -> str:
    now = dt.datetime.now(tz=dt.timezone.utc)
    payload = {
        "sub": sub,
        "iss": TEST_ISSUER,
        "iat": now,
        "nbf": now,
        "exp": now + dt.timedelta(hours=1),
    }
    return jwt.encode(payload, _priv, algorithm="RS256", headers={"kid": KID})


@pytest.fixture
def client(stub_jwks):
    app.dependency_overrides[get_verifier] = _verifier
    c = TestClient(app)
    yield c
    app.dependency_overrides.pop(get_verifier, None)


def _auth(sub: str) -> dict:
    return {"Authorization": f"Bearer {_make_token(sub=sub)}"}


# ---------------------------------------------------------------------------
# GET /map
# ---------------------------------------------------------------------------


def test_map_unauthenticated_401(client):
    resp = client.get("/api/map")
    assert resp.status_code == 401, resp.text


def test_map_returns_seeded_topology(client):
    resp = client.get("/api/map", headers=_auth("user_map_1"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["clusters"]) == 4
    assert len(body["units"]) == 8

    cluster_keys = {c["key"] for c in body["clusters"]}
    assert cluster_keys == {"pm", "swe", "qa", "devops"}

    # 위치/role이 실려 있는지 확인.
    for c in body["clusters"]:
        assert isinstance(c["map_x"], int) and isinstance(c["map_y"], int)
    for u in body["units"]:
        assert u["role"]  # role 문자열 존재
        assert isinstance(u["map_x"], int) and isinstance(u["map_y"], int)
        assert u["cluster_id"]


# ---------------------------------------------------------------------------
# GET /units/{id}
# ---------------------------------------------------------------------------


def _some_unit_id() -> uuid.UUID:
    db = SessionLocal()
    try:
        return db.execute(select(Unit).limit(1)).scalar_one().id
    finally:
        db.close()


def test_unit_detail_unauthenticated_401(client):
    resp = client.get(f"/api/units/{_some_unit_id()}")
    assert resp.status_code == 401


def test_unit_detail_not_found_404(client):
    resp = client.get(f"/api/units/{uuid.uuid4()}", headers=_auth("user_u_404"))
    assert resp.status_code == 404


def test_unit_with_no_task_is_idle(client):
    unit_id = _some_unit_id()
    # 이 사용자에겐 이 unit에 task가 없는 상태.
    resp = client.get(f"/api/units/{unit_id}", headers=_auth("user_idle_only"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "idle"
    assert body["task"] is None
    assert body["unit"]["id"] == str(unit_id)
    assert body["unit"]["role"]


def test_unit_reflects_authoritative_task_status(client):
    """task row를 직접 넣으면 detail이 그 권위 status를 반영한다."""
    db = SessionLocal()
    user_id = f"user_task_{uuid.uuid4().hex[:8]}"
    unit = db.execute(select(Unit).limit(1)).scalar_one()
    task = Task(
        user_id=user_id,
        unit_id=unit.id,
        cluster_key="pm",
        status="working",
        instructions="do the thing",
        result_markdown="partial result body",
        awaiting_prompt=None,
    )
    db.add(task)
    db.commit()
    task_id = task.id
    try:
        resp = client.get(f"/api/units/{unit.id}", headers=_auth(user_id))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "working"
        assert body["task"] is not None
        assert body["task"]["status"] == "working"
        assert body["task"]["id"] == str(task_id)
        assert body["task"]["result_snippet"] == "partial result body"
    finally:
        obj = db.get(Task, task_id)
        if obj is not None:
            db.delete(obj)
            db.commit()
        db.close()


def test_unit_task_scoped_to_user(client):
    """다른 사용자의 task는 보이지 않는다 — 그 사용자에겐 여전히 idle."""
    db = SessionLocal()
    owner = f"user_owner_{uuid.uuid4().hex[:8]}"
    other = f"user_other_{uuid.uuid4().hex[:8]}"
    unit = db.execute(select(Unit).limit(1)).scalar_one()
    task = Task(
        user_id=owner,
        unit_id=unit.id,
        cluster_key="pm",
        status="done",
        instructions="x",
    )
    db.add(task)
    db.commit()
    task_id = task.id
    try:
        # owner는 done을 본다.
        r_owner = client.get(f"/api/units/{unit.id}", headers=_auth(owner))
        assert r_owner.json()["status"] == "done"
        # other 사용자는 같은 unit에서 idle(교차 사용자 격리).
        r_other = client.get(f"/api/units/{unit.id}", headers=_auth(other))
        assert r_other.json()["status"] == "idle"
        assert r_other.json()["task"] is None
    finally:
        obj = db.get(Task, task_id)
        if obj is not None:
            db.delete(obj)
            db.commit()
        db.close()


def test_unit_latest_task_wins(client):
    """같은 unit에 여러 task가 있으면 가장 최근 것이 권위 상태다."""
    db = SessionLocal()
    user_id = f"user_multi_{uuid.uuid4().hex[:8]}"
    unit = db.execute(select(Unit).limit(1)).scalar_one()
    older = Task(
        user_id=user_id, unit_id=unit.id, cluster_key="pm",
        status="failed", instructions="old",
        created_at=dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc),
    )
    newer = Task(
        user_id=user_id, unit_id=unit.id, cluster_key="pm",
        status="needs-input", instructions="new",
        awaiting_prompt="which option?",
        created_at=dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc),
    )
    db.add_all([older, newer])
    db.commit()
    ids = [older.id, newer.id]
    try:
        resp = client.get(f"/api/units/{unit.id}", headers=_auth(user_id))
        body = resp.json()
        assert body["status"] == "needs-input"
        assert body["task"]["awaiting_prompt"] == "which option?"
    finally:
        for tid in ids:
            obj = db.get(Task, tid)
            if obj is not None:
                db.delete(obj)
        db.commit()
        db.close()
