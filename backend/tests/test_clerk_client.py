"""Clerk 이메일 조회 테스트 — opt-in no-op, primary 선택, 실패 삼킴.

키 없으면 네트워크 안 타고 None. 있으면 primary 이메일을 고르고, 조회 실패는 본
흐름(온보딩)을 안 깨고 None으로 삼킨다.
"""

from __future__ import annotations

from app.config import settings
from app.services import clerk_client


def _resp(payload):
    return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: payload})()


def test_noop_when_key_unset(monkeypatch):
    monkeypatch.setattr(settings, "clerk_secret_key", "")
    calls = []
    monkeypatch.setattr(clerk_client.httpx, "get", lambda *a, **k: calls.append(1))
    assert clerk_client.get_user_email("user_x") is None  # 네트워크 안 탐
    assert calls == []


def test_picks_primary_email(monkeypatch):
    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_x")
    payload = {
        "primary_email_address_id": "id:2",
        "email_addresses": [
            {"id": "id:1", "email_address": "alt@example.com"},
            {"id": "id:2", "email_address": "primary@example.com"},
        ],
    }
    monkeypatch.setattr(clerk_client.httpx, "get", lambda *a, **k: _resp(payload))
    assert clerk_client.get_user_email("user_x") == "primary@example.com"


def test_falls_back_to_first_email(monkeypatch):
    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_x")
    payload = {  # primary id가 매칭 안 될 때 첫 이메일
        "primary_email_address_id": "missing",
        "email_addresses": [{"id": "id:1", "email_address": "first@example.com"}],
    }
    monkeypatch.setattr(clerk_client.httpx, "get", lambda *a, **k: _resp(payload))
    assert clerk_client.get_user_email("user_x") == "first@example.com"


def test_no_emails_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_x")
    monkeypatch.setattr(clerk_client.httpx, "get", lambda *a, **k: _resp({"email_addresses": []}))
    assert clerk_client.get_user_email("user_x") is None


def test_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_x")

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(clerk_client.httpx, "get", boom)
    assert clerk_client.get_user_email("user_x") is None  # 예외 안 던짐
