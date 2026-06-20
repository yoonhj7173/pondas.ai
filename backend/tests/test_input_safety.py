"""입력 안전 — null byte / 짝없는 surrogate가 422로 거부되는지(악용 테스트 ABUSE-BUG-1/2).

이 바이트들은 Postgres text/UTF-8을 깨 그대로 두면 커밋 시점 500. 입력 경계(Pydantic)에서 막아야 함.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.routers.chat import ChatIn
from app.schemas import AgentCreate, ProjectCreate


def test_null_byte_rejected_project_name():
    with pytest.raises(ValidationError, match="null bytes"):
        ProjectCreate(name="e2e-abuse-\x00x", template_keys=["development"])


def test_lone_surrogate_rejected_project_name():
    with pytest.raises(ValidationError, match="surrogate"):
        ProjectCreate(name="e2e-abuse-\ud800", template_keys=["development"])


def test_null_byte_rejected_chat_message():
    with pytest.raises(ValidationError, match="null bytes"):
        ChatIn(message="hello\x00world")


def test_null_byte_rejected_agent_fields():
    with pytest.raises(ValidationError, match="null bytes"):
        AgentCreate(name="ok", role_instructions="do \x00 stuff", model_tier="medium")


def test_clean_unicode_still_allowed():
    # 정상 유니코드(이모지/CJK/RTL/zero-width)는 통과 — 거부는 깨진 바이트에 한함.
    p = ProjectCreate(name="proj 🔥 測試 ‮rtl ​zwsp", template_keys=["development"])
    assert "🔥" in p.name
    assert ChatIn(message="안녕 🚀").message == "안녕 🚀"


# --- HTTP 레벨: lone surrogate가 응답 직렬화를 깨 500 나지 않는지(ABUSE-BUG-2) ---


def test_lone_surrogate_http_returns_422_not_500(client, auth):
    # 와이어에 JSON 이스케이프 \ud800 → 서버 json.loads가 lone surrogate로 복원 →
    # 검증 422. 그 422 본문이 입력값을 echo해도 SafeJSONResponse가 안 깨져야 함.
    r = client.post(
        "/api/projects",
        headers={**auth(), "Content-Type": "application/json"},
        content=b'{"name":"e2e-abuse-\\ud800","template_keys":["development"]}',
    )
    assert r.status_code == 422            # 500 아님
    assert r.json()["detail"]              # 본문 파싱 가능


def test_blank_name_rejected():
    # 공백/탭/개행만인 이름 거부(P2) — min_length=1은 통과시켜 빈 이름이 저장됐었다.
    for blank in ("   ", "\t\n ", " "):
        with pytest.raises(ValidationError, match="blank"):
            ProjectCreate(name=blank, template_keys=["development"])


def test_blank_chat_message_rejected():
    with pytest.raises(ValidationError, match="blank"):
        ChatIn(message="   ")


def test_project_cap_returns_409(client, auth, monkeypatch):
    # 계정당 프로젝트 총량 캡 — 초과 시 409(스팸 방어). cap=0으로 첫 생성부터 막힘.
    monkeypatch.setattr("app.routers.projects.MAX_PROJECTS_PER_USER", 0)
    r = client.post(
        "/api/projects",
        json={"name": "e2e-cap", "template_keys": ["development"]},
        headers=auth("cap_user"),
    )
    assert r.status_code == 409
    assert "limit" in r.json()["detail"].lower()


def test_route_rate_limit_dependency(monkeypatch):
    # per-route dependency: 저장소가 '초과'라 하면 429 + Retry-After, '허용'이면 통과.
    import time

    from fastapi import HTTPException

    from app import ratelimit

    class _Req:
        headers = {"x-forwarded-for": "9.9.9.9"}
        client = type("C", (), {"host": "9.9.9.9"})()

    ratelimit.limiter.enabled = True
    dep = ratelimit.rate_limit("20/minute", "unit_test_scope")
    monkeypatch.setattr(ratelimit._route_limiter, "hit", lambda *a, **k: True)
    assert dep(_Req()) is None                              # 허용
    monkeypatch.setattr(ratelimit._route_limiter, "hit", lambda *a, **k: False)
    monkeypatch.setattr(
        ratelimit._route_limiter, "get_window_stats",
        lambda *a, **k: type("S", (), {"reset_time": time.time() + 30})(),
    )
    with pytest.raises(HTTPException) as ei:
        dep(_Req())
    assert ei.value.status_code == 429 and "Retry-After" in ei.value.headers
    ratelimit.limiter.enabled = False                      # 복원(autouse가 또 끄지만 명시)


def test_ratelimit_key_uses_forwarded_for():
    # 프록시 뒤 실 IP는 X-Forwarded-For 첫 항목 — 안 그러면 모두 같은 키로 묶여 리밋 무력화(ABUSE-BUG-3).
    from app.ratelimit import client_ip

    class _Req:
        def __init__(self, headers, client_host="10.0.0.1"):
            self.headers = headers
            self.client = type("C", (), {"host": client_host})()

    assert client_ip(_Req({"x-forwarded-for": "1.2.3.4, 10.0.0.1"})) == "1.2.3.4"
    assert client_ip(_Req({})) == "10.0.0.1"  # XFF 없으면 직접 피어


def test_surrogate_in_400_detail_does_not_crash(client, auth):
    # 알 수 없는 template_key에 surrogate → 400 detail이 그 값을 echo → 렌더 크래시 안 나야.
    r = client.post(
        "/api/projects",
        headers={**auth(), "Content-Type": "application/json"},
        content=b'{"name":"ok","template_keys":["\\ud800"]}',
    )
    assert r.status_code in (400, 422)     # 500 아님
    assert r.content                       # 응답 바디 정상 인코딩
