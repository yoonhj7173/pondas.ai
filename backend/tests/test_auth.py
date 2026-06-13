"""Auth + tenancy tests — Clerk JWT verification & scope helper.

서명 검증 로직을 결정적으로 검증하기 위해, 로컬 RSA 키페어로 테스트 JWT를 발급하고
PyJWKClient의 JWKS fetch를 그 공개키로 stub한다. 이렇게 하면 실제 Clerk 인스턴스에
의존하지 않고도 서명/issuer/만료 검증 경로(암호화 로직)를 그대로 통과시킨다.

실 Clerk JWKS 도달성은 별도로(run 리포트) 확인했고, 여기서는 검증 로직 자체를 본다.
"""

from __future__ import annotations

import datetime as dt
import json

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth import ClerkAuthError, ClerkTokenVerifier, TenantScope, get_verifier
from app.main import app

TEST_ISSUER = "https://test-instance.clerk.accounts.dev"
TEST_JWKS_URL = f"{TEST_ISSUER}/.well-known/jwks.json"
KID = "test-kid-1"


# --- 로컬 RSA 키페어: 테스트 JWT 서명용 + JWKS 공개키 ---
_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
# 두 번째 키페어: "서명은 유효하지만 JWKS에 없는/다른" 케이스(bad signature)용.
_priv_other = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks_json() -> str:
    """테스트 공개키를 RFC7517 JWKS 형태로 직렬화한다(PyJWKClient.fetch_data가 반환할 값)."""
    pub_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(_priv.public_key(), as_dict=True)
    pub_jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return json.dumps({"keys": [pub_jwk]})


@pytest.fixture
def stub_jwks(monkeypatch):
    """PyJWKClient의 네트워크 fetch를 로컬 JWKS로 대체한다(결정적 서명 검증)."""

    def fake_fetch_data(self):
        return json.loads(_jwks_json())

    monkeypatch.setattr("jwt.PyJWKClient.fetch_data", fake_fetch_data)


def _verifier() -> ClerkTokenVerifier:
    # 실 Clerk 대신 테스트 issuer/JWKS를 가리키는 검증기. 서명 로직은 동일하게 탄다.
    return ClerkTokenVerifier(issuer=TEST_ISSUER, jwks_url=TEST_JWKS_URL)


def _make_token(
    *,
    sub: str = "user_abc123",
    issuer: str = TEST_ISSUER,
    exp_delta: int = 3600,
    key=_priv,
    kid: str = KID,
) -> str:
    now = dt.datetime.now(tz=dt.timezone.utc)
    payload = {
        "sub": sub,
        "iss": issuer,
        "iat": now,
        "nbf": now,
        "exp": now + dt.timedelta(seconds=exp_delta),
    }
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": kid})


# ---------------------------------------------------------------------------
# 검증기 단위 테스트 (서명 / issuer / 만료)
# ---------------------------------------------------------------------------


def test_valid_token_extracts_user_id(stub_jwks):
    token = _make_token(sub="user_xyz")
    assert _verifier().verify(token) == "user_xyz"


def test_expired_token_rejected(stub_jwks):
    token = _make_token(exp_delta=-10)  # 이미 만료
    with pytest.raises(ClerkAuthError):
        _verifier().verify(token)


def test_wrong_issuer_rejected(stub_jwks):
    token = _make_token(issuer="https://evil.example.com")
    with pytest.raises(ClerkAuthError):
        _verifier().verify(token)


def test_bad_signature_rejected(stub_jwks):
    # JWKS에 등록된 키(_priv)가 아니라 다른 키로 서명 → kid는 같지만 서명 불일치.
    token = _make_token(key=_priv_other)
    with pytest.raises(ClerkAuthError):
        _verifier().verify(token)


def test_unknown_kid_rejected(stub_jwks):
    # JWKS에 없는 kid → signing key 조회 실패.
    token = _make_token(kid="nonexistent-kid")
    with pytest.raises(ClerkAuthError):
        _verifier().verify(token)


def test_alg_none_rejected(stub_jwks):
    # alg=none 토큰(서명 없음)은 거부되어야 한다(alg 혼동 공격 방지).
    payload = {"sub": "user_x", "iss": TEST_ISSUER, "exp": 9999999999}
    unsigned = jwt.encode(payload, key=None, algorithm="none")
    with pytest.raises(ClerkAuthError):
        _verifier().verify(unsigned)


def test_missing_sub_rejected(stub_jwks):
    now = dt.datetime.now(tz=dt.timezone.utc)
    payload = {"iss": TEST_ISSUER, "exp": now + dt.timedelta(hours=1)}
    token = jwt.encode(payload, _priv, algorithm="RS256", headers={"kid": KID})
    with pytest.raises(ClerkAuthError):
        _verifier().verify(token)


# ---------------------------------------------------------------------------
# 라우트 통합 테스트 (의존성 → 401 / 통과)
# ---------------------------------------------------------------------------


@pytest.fixture
def client(stub_jwks):
    # 전역 검증기를 테스트 issuer/JWKS 검증기로 오버라이드.
    app.dependency_overrides[get_verifier] = _verifier
    c = TestClient(app)
    yield c
    app.dependency_overrides.pop(get_verifier, None)


def test_protected_route_no_token_401(client):
    resp = client.get("/api/me")
    assert resp.status_code == 401, resp.text


def test_protected_route_malformed_header_401(client):
    resp = client.get("/api/me", headers={"Authorization": "Token abc"})
    assert resp.status_code == 401


def test_protected_route_garbage_token_401(client):
    resp = client.get("/api/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401


def test_protected_route_expired_token_401(client):
    token = _make_token(exp_delta=-10)
    resp = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_protected_route_valid_token_200(client):
    token = _make_token(sub="user_route_ok")
    resp = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"user_id": "user_route_ok"}


def test_query_param_token_accepted_for_sse(client):
    # SSE용 ?token= 경로도 동작해야 한다(EventSource 헤더 제약 대응).
    token = _make_token(sub="user_q")
    resp = client.get(f"/api/me?token={token}")
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "user_q"}


def test_whoami_tenant_scope_binding(client):
    token = _make_token(sub="user_tenant")
    resp = client.get("/api/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"tenant": "user_tenant"}


# ---------------------------------------------------------------------------
# 테넌시 스코프: 교차 사용자 쿼리는 빈 결과
# ---------------------------------------------------------------------------


def test_tenant_scope_isolates_users():
    """TenantScope.query가 user_id로 필터하여 교차 사용자 데이터를 빈 결과로 만든다.

    라이브 Postgres에 서로 다른 두 사용자의 task를 넣고, 한 사용자 스코프로 조회하면
    상대 사용자의 row가 안 보이는지 확인한다.
    """
    import uuid

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Task, Unit

    db = SessionLocal()
    user_a = f"user_a_{uuid.uuid4().hex[:8]}"
    user_b = f"user_b_{uuid.uuid4().hex[:8]}"
    created_ids = []
    try:
        # 시드된 unit 하나를 빌려 task를 만든다.
        unit = db.execute(select(Unit).limit(1)).scalar_one()
        for uid in (user_a, user_b):
            t = Task(
                user_id=uid,
                unit_id=unit.id,
                cluster_key="pm",
                status="queued",
                instructions="test",
            )
            db.add(t)
            db.flush()
            created_ids.append(t.id)
        db.commit()

        scope_a = TenantScope(user_a)
        rows_a = scope_a.query(db, Task).all()
        assert all(r.user_id == user_a for r in rows_a)
        assert any(r.user_id == user_a for r in rows_a)
        # user_b의 row는 user_a 스코프에서 안 보여야 한다(교차 사용자 격리).
        assert all(r.user_id != user_b for r in rows_a)

        scope_b = TenantScope(user_b)
        rows_b = scope_b.query(db, Task).all()
        assert all(r.user_id == user_b for r in rows_b)
    finally:
        # 테스트 데이터 정리.
        for tid in created_ids:
            obj = db.get(Task, tid)
            if obj is not None:
                db.delete(obj)
        db.commit()
        db.close()
