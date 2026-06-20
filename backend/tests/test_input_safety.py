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
