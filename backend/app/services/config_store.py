"""Config 테이블 읽기 + 비용 계산 — 가드레일/가격은 DB config가 권위(D32, 배포없이 튜닝).

config 행은 key/value(text). 복합값(tier_models/model_pricing)은 JSON 문자열. 디스패치
게이트(TaskService)와 비용 집계가 이 모듈을 통해 값을 읽는다. 누락 키는 안전한 기본값으로.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Config

_DEFAULTS = {
    "concurrency_cap": "3",
    "daily_cost_cap_usd": "10",
    "goal_chain_budget": "25",
    "context_token_budget": "100000",
    "dev_task_timeout_min": "30",
    "sandbox_idle_pause_sec": "300",
    "dev_engine": "e2b",          # agent_sdk 경로 실행기: e2b(현행) | cma(D45 파일럿)
    "cma_environment_id": "",     # CMA 공유 cloud 환경 id(lazy 생성 후 여기 저장)
}


@dataclass(frozen=True)
class GuardConfig:
    concurrency_cap: int
    daily_cost_cap_usd: float
    goal_chain_budget: int
    context_token_budget: int
    dev_task_timeout_min: int
    sandbox_idle_pause_sec: int
    dev_engine: str
    cma_environment_id: str
    tier_models: dict[str, str]
    model_pricing: dict[str, dict[str, float]]


def load_config(db: Session) -> GuardConfig:
    """config 테이블을 typed GuardConfig로 읽는다(누락은 기본값)."""
    rows = {c.key: c.value for c in db.query(Config).all()}

    def g(key: str) -> str:
        return rows.get(key, _DEFAULTS.get(key, ""))

    return GuardConfig(
        concurrency_cap=int(g("concurrency_cap")),
        daily_cost_cap_usd=float(g("daily_cost_cap_usd")),
        goal_chain_budget=int(g("goal_chain_budget")),
        context_token_budget=int(g("context_token_budget")),
        dev_task_timeout_min=int(g("dev_task_timeout_min")),
        sandbox_idle_pause_sec=int(g("sandbox_idle_pause_sec")),
        dev_engine=g("dev_engine"),
        cma_environment_id=g("cma_environment_id"),
        tier_models=json.loads(rows.get("tier_models", "{}")),
        model_pricing=json.loads(rows.get("model_pricing", "{}")),
    )


def model_for_tier(cfg: GuardConfig, tier: str) -> str:
    """티어 → 실제 모델 id(D32). 미지정 티어는 medium으로 폴백."""
    return cfg.tier_models.get(tier) or cfg.tier_models.get("medium", "")


def set_config(db: Session, key: str, value: str) -> None:
    """config 키 upsert — lazy 생성한 리소스 id(예: cma_environment_id) 저장용."""
    row = db.get(Config, key)
    if row is None:
        db.add(Config(key=key, value=value))
    else:
        row.value = value
    db.flush()


def cost_usd(cfg: GuardConfig, model: str, tokens_in: int, tokens_out: int) -> float:
    """모델별 가격맵으로 USD 비용 계산(per MTok). 미지정 모델은 0."""
    p = cfg.model_pricing.get(model)
    if not p:
        return 0.0
    return round(
        (tokens_in / 1_000_000.0) * p.get("in", 0.0)
        + (tokens_out / 1_000_000.0) * p.get("out", 0.0),
        6,
    )
