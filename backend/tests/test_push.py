"""Web Push 테스트(item 39, D56⑤) — 구독 CRUD + 발송 파이프(가짜 webpush) + 알림 훅."""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models import PushSubscription
from app.services import push_service


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.query(PushSubscription).delete(); s.commit(); s.close()


def _sub(client, auth, uid, endpoint="https://push.example/ep-1"):
    return client.post("/api/push/subscribe", headers=auth(uid),
                       json={"endpoint": endpoint, "keys": {"p256dh": "pk", "auth": "ak"}})


def test_subscribe_upsert_and_unsubscribe(client, auth, db):
    uid = f"pu_{uuid.uuid4().hex[:8]}"
    assert _sub(client, auth, uid).status_code == 204
    assert db.query(PushSubscription).filter_by(user_id=uid).count() == 1
    # 같은 endpoint 재구독 = upsert(중복 없음, 키 갱신)
    assert _sub(client, auth, uid).status_code == 204
    db.expire_all()
    assert db.query(PushSubscription).filter_by(user_id=uid).count() == 1
    # 타 유저는 남의 구독을 못 지운다
    client.request("DELETE", "/api/push/subscribe", headers=auth("attacker"),
                   json={"endpoint": "https://push.example/ep-1"})
    db.expire_all()
    assert db.query(PushSubscription).filter_by(user_id=uid).count() == 1
    client.request("DELETE", "/api/push/subscribe", headers=auth(uid),
                   json={"endpoint": "https://push.example/ep-1"})
    db.expire_all()
    assert db.query(PushSubscription).filter_by(user_id=uid).count() == 0


def test_send_push_noop_without_vapid(db, monkeypatch):
    monkeypatch.setattr(push_service.settings, "vapid_public_key", "")
    assert push_service.send_push(db, "u1", title="t", body="b", url="/") == 0


def test_send_push_delivers_and_cleans_expired(db, monkeypatch):
    uid = f"pu_{uuid.uuid4().hex[:8]}"
    db.add(PushSubscription(user_id=uid, endpoint="https://push.example/ok", keys={"a": 1}))
    db.add(PushSubscription(user_id=uid, endpoint="https://push.example/gone", keys={"a": 1}))
    db.commit()
    monkeypatch.setattr(push_service.settings, "vapid_public_key", "pub")
    monkeypatch.setattr(push_service.settings, "vapid_private_key", "priv")

    sent_payloads = []

    class GoneResp:
        status_code = 410

    def fake_send(info, payload):
        if info["endpoint"].endswith("/gone"):
            exc = RuntimeError("gone")
            exc.response = GoneResp()
            raise exc
        sent_payloads.append((info["endpoint"], payload))

    monkeypatch.setattr(push_service, "_send", fake_send)
    n = push_service.send_push(db, uid, title="SWE needs your input", body="Which DB?", url="/app/p1")
    db.commit()
    assert n == 1
    assert "SWE needs your input" in sent_payloads[0][1]
    # 410 구독은 청소됐다
    eps = [s.endpoint for s in db.query(PushSubscription).filter_by(user_id=uid)]
    assert eps == ["https://push.example/ok"]


def test_config_endpoint(client, auth):
    resp = client.get("/api/push/config")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False  # 테스트 env엔 VAPID 없음
