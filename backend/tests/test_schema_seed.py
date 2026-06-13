"""Schema + seed tests — run against LIVE Postgres (mock 아님).

migration이 적용되어 5개 테이블이 존재하는지, seed가 정확히 4 clusters / 8 units를
넣는지, 그리고 재실행 시 멱등한지(중복 없음)를 검증한다. tech-design §5 데이터 모델과
§4 클러스터/유닛 로스터에 대응.

전제: `alembic upgrade head`가 이미 적용된 라이브 DB(docker-compose).
"""

from __future__ import annotations

from sqlalchemy import inspect

from app.db import SessionLocal, engine
from app.models import Cluster, Config, Unit
from seed import seed

EXPECTED_ROSTER = {
    "pm": {"Product Manager", "Business Analyst"},
    "swe": {"Senior Engineer", "Technical Lead"},
    "qa": {"QA Engineer", "Test Planner"},
    "devops": {"Deployment Engineer", "Principal Engineer"},
}


def test_all_tables_exist():
    tables = set(inspect(engine).get_table_names())
    assert {"clusters", "units", "tasks", "notifications", "config"} <= tables


def test_task_indexes_present():
    names = {ix["name"] for ix in inspect(engine).get_indexes("tasks")}
    assert {"ix_tasks_user_status", "ix_tasks_unit_id", "ix_tasks_user_created"} <= names


def test_seed_inserts_exactly_4_clusters_8_units():
    db = SessionLocal()
    try:
        counts = seed(db)
        assert counts["clusters"] == 4
        assert counts["units"] == 8
        assert db.query(Cluster).count() == 4
        assert db.query(Unit).count() == 8
    finally:
        db.close()


def test_seed_is_idempotent():
    # 두 번 더 실행해도 카운트가 그대로여야 한다(중복 없음).
    db = SessionLocal()
    try:
        seed(db)
        seed(db)
        assert db.query(Cluster).count() == 4
        assert db.query(Unit).count() == 8
    finally:
        db.close()


def test_seed_roster_matches_tech_design():
    db = SessionLocal()
    try:
        seed(db)
        for cluster_key, expected_units in EXPECTED_ROSTER.items():
            cluster = db.query(Cluster).filter_by(key=cluster_key).one()
            unit_names = {u.name for u in cluster.units}
            assert unit_names == expected_units, cluster_key
    finally:
        db.close()


def test_config_rows_seeded():
    db = SessionLocal()
    try:
        seed(db)
        keys = {c.key for c in db.query(Config).all()}
        assert {"concurrency_cap", "cost_per_1k_in", "cost_per_1k_out"} <= keys
    finally:
        db.close()
