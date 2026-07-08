"""계정 삭제(GDPR) — DELETE /api/account 이 사용자 데이터를 모두 지우고 남의 것은 건드리지 않는다."""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models import CreditAccount, CreditLedger, Notification, Project, UserProfile
from app.services import credit_service as cs
from seed import seed


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _no_clerk(monkeypatch):
    # 실제 Clerk 백엔드 API를 때리지 않도록 사용자 삭제 훅을 no-op로.
    monkeypatch.setattr("app.routers.account._delete_clerk_user", lambda uid: None)


def _create_project(client, auth, uid: str) -> uuid.UUID:
    resp = client.post(
        "/api/projects",
        json={"name": "Doomed", "template_keys": ["planning"]},
        headers=auth(uid),
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


def test_delete_account_wipes_everything(client, auth):
    uid = "acct_del_user_1"
    pid = _create_project(client, auth, uid)
    db = SessionLocal()
    try:
        cs.grant_signup(db, uid, 500)  # 지갑 + 원장 1행 생성
        db.add(UserProfile(user_id=uid, display_name="Doomed User"))
        db.add(Notification(user_id=uid, project_id=pid, type="done", message="x", read=False))
        db.commit()
    finally:
        db.close()

    assert client.delete("/api/account", headers=auth(uid)).status_code == 204

    db = SessionLocal()
    try:
        assert db.query(Project).filter_by(user_id=uid).count() == 0
        assert db.get(CreditAccount, uid) is None
        assert db.get(UserProfile, uid) is None
        assert db.query(Notification).filter_by(user_id=uid).count() == 0
        assert db.query(CreditLedger).filter_by(user_id=uid).count() == 0
    finally:
        db.close()


def test_delete_account_only_touches_own_data(client, auth):
    me, other = "acct_del_me", "acct_del_other"
    other_pid = _create_project(client, auth, other)
    my_pid = _create_project(client, auth, me)
    db = SessionLocal()
    try:
        cs.grant_signup(db, other, 500)
        db.commit()
    finally:
        db.close()

    assert client.delete("/api/account", headers=auth(me)).status_code == 204

    db = SessionLocal()
    try:
        assert db.get(Project, my_pid) is None          # 내 것은 사라짐
        assert db.get(Project, other_pid) is not None    # 남의 것은 그대로
        assert db.get(CreditAccount, other) is not None
        # 정리
        db.delete(db.get(Project, other_pid))
        db.delete(db.get(CreditAccount, other))
        db.commit()
    finally:
        db.close()
