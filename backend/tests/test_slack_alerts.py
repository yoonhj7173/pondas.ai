"""Slack 운영 알림 테스트 — opt-in no-op, 페이로드, 실패 삼킴, 전역 500 핸들러 알림.

키 없으면 아무것도 안 하고(no-op), 있으면 #채널로 POST하며 알림 실패는 본 흐름을 안 깬다.
전역 예외핸들러는 처리 안 된 에러에 500 + 알림.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.main import _unhandled_exception_handler
from app.services import slack_alerts


def test_noop_when_url_unset(monkeypatch):
    monkeypatch.setattr(settings, "slack_alert_webhook_url", "")
    calls = []
    monkeypatch.setattr(slack_alerts.httpx, "post", lambda *a, **k: calls.append(1))
    slack_alerts.send_slack_alert("title", "detail")
    assert calls == []                                   # POST 안 함


def test_posts_when_url_set(monkeypatch):
    monkeypatch.setattr(settings, "slack_alert_webhook_url", "https://hooks.example/x")
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["text"] = json["text"]
        return type("R", (), {"status_code": 200})()

    monkeypatch.setattr(slack_alerts.httpx, "post", fake_post)
    slack_alerts.send_slack_alert("boom", "stack here")
    assert captured["url"] == "https://hooks.example/x"
    assert "boom" in captured["text"] and "pondas" in captured["text"]
    assert "stack here" in captured["text"]


def test_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(settings, "slack_alert_webhook_url", "https://hooks.example/x")

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(slack_alerts.httpx, "post", boom)
    slack_alerts.send_slack_alert("x")                   # 예외 안 던짐


def test_unhandled_handler_returns_500_and_alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(slack_alerts, "send_slack_alert", lambda *a, **k: sent.append(a))

    app = FastAPI()
    app.add_exception_handler(Exception, _unhandled_exception_handler)

    @app.get("/boom")
    def boom():
        raise ValueError("kaboom")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/boom")
    assert r.status_code == 500 and r.json()["detail"] == "Internal Server Error"
    assert sent and "prod error" in sent[0][0]           # 알림 발사됨
