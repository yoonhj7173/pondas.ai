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
    "dev_engine": "cma",          # development 팀 실행기: cma(D45, 기본) | e2b(폴백). design은 항상 e2b(게이트).
    "cma_environment_id": "",     # CMA 공유 cloud 환경 id(lazy 생성 후 여기 저장)
    "billing_enabled": "false",   # 크레딧 미터링(D46) 마스터 스위치. OFF=무과금(현행). Stripe+무료크레딧 준비 후 플립.
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
    billing_enabled: bool
    tier_models: dict[str, str]
    model_pricing: dict[str, dict[str, float]]


def load_config(db: Session) -> GuardConfig:
    """설정 읽기 — 비용 한도·동시실행 한도·모델 단가 같은 운영 값을 DB에서 한 묶음으로 읽는다.

    PM 한 줄: 이 값들이 config 테이블에 있어서, 코드 재배포 없이 DB만 고치면 한도/모델을 바꿀 수 있다.
        (예: 하루 비용 상한, 동시에 돌릴 작업 수, 등급별 어떤 모델 쓸지, 모델별 토큰 단가)
    무슨 일을 하나: config 테이블 전체를 읽어 타입이 정해진 GuardConfig 객체로 만든다. 빠진 값은 안전한 기본값.
    누가 부르나: 디스패치 게이트(task_service.py), 비용 계산, 워커 등 운영 한도가 필요한 거의 모든 곳.
    연결: 등급→모델 → 아래 model_for_tier. 비용 계산 → 아래 cost_usd. 기본 시드값 → catalog.py의 config_seed.
    """
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
        billing_enabled=g("billing_enabled").lower() == "true",
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
    """비용 계산 — 쓴 토큰 수와 모델 단가로 이 작업이 든 돈(달러)을 계산한다.

    무슨 일을 하나: 입력/출력 토큰 수 × 모델별 100만 토큰당 단가 = 추정 비용. 작업이 끝날 때
        호출해 task에 저장하고, 그 합이 하루 비용 한도(daily_cost_cap) 체크와 사용량 화면에 쓰인다.
    누가 부르나: 작업 마무리 — worker_core.py, cma_engine.py.
    """
    p = cfg.model_pricing.get(model)
    if not p:
        return 0.0
    return round(
        (tokens_in / 1_000_000.0) * p.get("in", 0.0)
        + (tokens_out / 1_000_000.0) * p.get("out", 0.0),
        6,
    )
