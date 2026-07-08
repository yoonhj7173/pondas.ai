"""Schema + seed tests (v3) — run against LIVE Postgres (mock 아님).

migration이 적용되어 v3 테이블이 존재하는지, seed가 정확히 4 team templates / 11 role
catalog rows를 넣는지, 재실행 시 멱등한지, starter/엔진/티어/config 맵이 스펙대로인지
검증한다. tech-design §5 + decision-log D40/D41/D43/D44 / specs/role-catalog.md 대응.

전제: `alembic upgrade head`가 이미 적용된 라이브 DB(docker-compose).
"""

from __future__ import annotations

import json

from sqlalchemy import inspect

from app.catalog import MODEL_PRICING, TIER_MODELS
from app.db import SessionLocal, engine
from app.models import AgentTemplate, Config, TeamTemplate
from seed import seed

V3_TABLES = {
    "user_profiles", "projects", "team_templates", "agent_templates",
    "teams", "agents", "edges", "goals", "tasks", "outputs",
    "context_files", "agent_memories", "orchestrator_messages",
    "notifications", "config",
}

# (template_key, engine, {role_key: is_starter})
EXPECTED_TEMPLATES = {
    "planning": ("crew", {"pm": True, "spec_writer": False}),
    "research": ("crew", {"researcher": True, "analyst": False}),
    "design": ("agent_sdk", {"product_designer": True, "visual_designer": False}),
    "development": ("agent_sdk", {
        "swe": True, "architect": False, "qa": False,
        "code_reviewer": False, "devops": False,
    }),
}


def test_all_v3_tables_exist():
    tables = set(inspect(engine).get_table_names())
    assert V3_TABLES <= tables
    # v1 잔재가 없어야 한다.
    assert "clusters" not in tables
    assert "units" not in tables


def test_no_data_team_in_p0():
    """Data 팀은 P0에서 제외(D44)."""
    db = SessionLocal()
    try:
        seed(db)
        assert db.query(TeamTemplate).filter_by(key="data").one_or_none() is None
    finally:
        db.close()


def test_seed_inserts_4_templates_11_roles():
    db = SessionLocal()
    try:
        counts = seed(db)
        assert counts["team_templates"] == 4
        assert counts["agent_templates"] == 11
        assert db.query(TeamTemplate).count() == 4
        assert db.query(AgentTemplate).count() == 11
    finally:
        db.close()


def test_seed_is_idempotent():
    db = SessionLocal()
    try:
        seed(db)
        seed(db)
        assert db.query(TeamTemplate).count() == 4
        assert db.query(AgentTemplate).count() == 11
    finally:
        db.close()


def test_seed_preserves_live_tuned_caps(db=None):
    """유저가 UI에서 튜닝한 cost/concurrency cap을 재-seed(배포)가 덮어쓰지 않는다(D32, 감사 P2)."""
    db = SessionLocal()
    try:
        seed(db)
        # 유저가 라이브로 캡을 바꿈.
        row = db.query(Config).filter_by(key="daily_cost_cap_usd").one()
        row.value = "77"
        conc = db.query(Config).filter_by(key="concurrency_cap").one()
        conc.value = "5"
        db.commit()
        # 배포 = 재-seed.
        seed(db)
        assert db.query(Config).filter_by(key="daily_cost_cap_usd").one().value == "77"  # 보존
        assert db.query(Config).filter_by(key="concurrency_cap").one().value == "5"       # 보존
        # 비-튜닝 키(가격맵)는 여전히 갱신됨.
        assert db.query(Config).filter_by(key="model_pricing").one().value == json.dumps(MODEL_PRICING)
    finally:
        db.close()


def test_templates_engine_and_starters():
    db = SessionLocal()
    try:
        seed(db)
        for key, (engine_val, roles) in EXPECTED_TEMPLATES.items():
            tt = db.query(TeamTemplate).filter_by(key=key).one()
            assert tt.engine == engine_val, key
            cat = {a.role_key: a.is_starter for a in tt.agent_templates}
            assert cat == roles, key
            # 팀당 정확히 1개의 starter.
            assert sum(1 for v in cat.values() if v) == 1, key
    finally:
        db.close()


def test_default_output_wiring():
    """Architect→handoff→swe, QA/Reviewer→review_loop→swe (max 5) (D38)."""
    db = SessionLocal()
    try:
        seed(db)
        arch = db.query(AgentTemplate).filter_by(template_key="development", role_key="architect").one()
        assert arch.default_output_type == "handoff"
        assert arch.default_output_target_role_key == "swe"
        qa = db.query(AgentTemplate).filter_by(template_key="development", role_key="qa").one()
        assert qa.default_output_type == "review_loop"
        assert qa.default_output_target_role_key == "swe"
        assert qa.default_max_iterations == 5
        # starter(pm)는 출력 없음(Final).
        pm = db.query(AgentTemplate).filter_by(template_key="planning", role_key="pm").one()
        assert pm.default_output_type is None
    finally:
        db.close()


def test_config_maps_seeded():
    db = SessionLocal()
    try:
        seed(db)
        cfg = {c.key: c.value for c in db.query(Config).all()}
        for k in ("concurrency_cap", "daily_cost_cap_usd", "goal_chain_budget",
                  "context_token_budget", "dev_task_timeout_min",
                  "sandbox_idle_pause_sec", "tier_models", "model_pricing"):
            assert k in cfg, k
        assert json.loads(cfg["tier_models"]) == TIER_MODELS
        assert json.loads(cfg["model_pricing"]) == MODEL_PRICING
    finally:
        db.close()
