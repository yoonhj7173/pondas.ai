"""복원력 하드닝 — 외부호출 타임아웃 + Celery 안전설정(prod 감사 P0/P1).

LLM completion이 timeout/num_retries를 넘기는지, Celery가 acks_late/time_limit를 갖는지 검증.
"""

from __future__ import annotations

import litellm

from app.config import settings
from app.db import SessionLocal
from app.services.orchestrator import LiteLLMClient


def _fake_resp():
    msg = type("M", (), {"content": "hi", "tool_calls": None})()
    choice = type("C", (), {"message": msg})()
    return type("R", (), {"choices": [choice]})()


def test_litellm_complete_passes_timeout(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _fake_resp()

    monkeypatch.setattr(litellm, "completion", fake_completion)
    db = SessionLocal()
    try:
        LiteLLMClient(db, model="claude-haiku-4-5-20251001").complete([{"role": "user", "content": "x"}], [])
    finally:
        db.close()
    assert captured["timeout"] == settings.llm_request_timeout_sec
    assert captured["num_retries"] == settings.llm_num_retries


def test_celery_has_acks_late_and_time_limits():
    from app.celery_app import celery_app

    conf = celery_app.conf
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.task_time_limit and conf.task_soft_time_limit
    assert conf.task_time_limit > conf.task_soft_time_limit
    # 가시성 타임아웃 > hard limit (장기 task 중복 재배달 방지).
    assert conf.broker_transport_options["visibility_timeout"] >= conf.task_time_limit
