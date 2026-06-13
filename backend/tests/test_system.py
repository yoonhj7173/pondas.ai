"""System endpoint tests — /health, /ready, config helpers.

/ready 테스트는 라이브 Postgres + Redis에 실제 연결한다(mock 아님). 인프라가 떠 있는
환경(docker-compose)에서 실행되는 것을 전제로 한다 — tech-design의 "실제로 동작" 검증.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_health_returns_200():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_connects_to_live_db_and_redis():
    # 라이브 Postgres + Redis에 실제 연결되어 ready여야 한다.
    resp = client.get("/ready")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"db": True, "redis": True}


def test_cost_estimation():
    # 1000 in + 1000 out = cost_per_1k_in + cost_per_1k_out
    expected = round(settings.cost_per_1k_in + settings.cost_per_1k_out, 6)
    assert settings.estimate_cost_usd(1000, 1000) == expected
    assert settings.estimate_cost_usd(0, 0) == 0.0


def test_sqlalchemy_url_uses_psycopg2_driver():
    assert settings.sqlalchemy_database_url.startswith("postgresql+psycopg2://")
