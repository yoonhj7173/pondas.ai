"""E2E 인증 우회 fail-safe — 알려진 개발 환경에서만 allow_e2e_bypass가 True."""

from __future__ import annotations

import pytest

from app.config import Settings


@pytest.mark.parametrize(
    "app_env,bypass,expected",
    [
        ("dev", "1", True),
        ("test", "1", True),
        ("production", "1", False),   # prod → 우회 거부
        ("prod", "1", False),
        ("staging", "1", False),      # 미인식 env → 거부
        ("Produciton", "1", False),   # 오타 → 거부(fail-safe)
        ("dev", "0", False),          # 플래그 off → 당연히 거부
    ],
)
def test_allow_e2e_bypass_only_in_dev_envs(monkeypatch, app_env, bypass, expected):
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("E2E_AUTH_BYPASS", bypass)
    assert Settings().allow_e2e_bypass is expected
