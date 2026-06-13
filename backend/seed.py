"""Idempotent seed — 4 clusters + 8 units + default config (tech-design §5, §4).

clusters/units는 전역 템플릿이며 `key`로 upsert한다(클러스터는 key, 유닛은
(cluster_id, key) 유니크 기준). 따라서 여러 번 실행해도 정확히 4 clusters / 8 units가
유지되고 중복 행이 생기지 않는다(deploy 시 매번 호출되어도 안전).

§4 매핑:
- PM: Product Manager, Business Analyst
- SWE: Senior Engineer, Technical Lead
- QA: QA Engineer, Test Planner
- DevOps: Deployment Engineer, Principal Engineer
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Cluster, Config, Unit

# (key, name, map_x, map_y, [units]) — 유닛은 (key, name, role, map_x, map_y).
# map 좌표는 클러스터를 4분면에 배치하고 유닛을 클러스터 주변에 좌/우로 둔 MVP 레이아웃.
CLUSTER_SEED: list[dict] = [
    {
        "key": "pm",
        "name": "Product Management",
        "map_x": -400,
        "map_y": -300,
        "units": [
            ("product_manager", "Product Manager", "Product Manager", -60, 0),
            ("business_analyst", "Business Analyst", "Business Analyst", 60, 0),
        ],
    },
    {
        "key": "swe",
        "name": "Software Engineering",
        "map_x": 400,
        "map_y": -300,
        "units": [
            ("senior_engineer", "Senior Engineer", "Senior Engineer", -60, 0),
            ("technical_lead", "Technical Lead", "Technical Lead", 60, 0),
        ],
    },
    {
        "key": "qa",
        "name": "Quality Assurance",
        "map_x": -400,
        "map_y": 300,
        "units": [
            ("qa_engineer", "QA Engineer", "QA Engineer", -60, 0),
            ("test_planner", "Test Planner", "Test Planner", 60, 0),
        ],
    },
    {
        "key": "devops",
        "name": "DevOps",
        "map_x": 400,
        "map_y": 300,
        "units": [
            ("deployment_engineer", "Deployment Engineer", "Deployment Engineer", -60, 0),
            ("principal_engineer", "Principal Engineer", "Principal Engineer", 60, 0),
        ],
    },
]

# 기본 config rows — concurrency cap과 가격 상수는 settings에서 끌어와 일관성 유지.
CONFIG_SEED: dict[str, str] = {
    "concurrency_cap": str(settings.concurrency_cap),
    "cost_per_1k_in": str(settings.cost_per_1k_in),
    "cost_per_1k_out": str(settings.cost_per_1k_out),
}


def _upsert_cluster(db: Session, spec: dict) -> Cluster:
    """key로 클러스터를 찾고 없으면 생성, 있으면 표시 속성 갱신."""
    cluster = db.query(Cluster).filter_by(key=spec["key"]).one_or_none()
    if cluster is None:
        cluster = Cluster(key=spec["key"])
        db.add(cluster)
    cluster.name = spec["name"]
    cluster.map_x = spec["map_x"]
    cluster.map_y = spec["map_y"]
    db.flush()  # cluster.id 확보(유닛 FK용)
    return cluster


def _upsert_unit(db: Session, cluster_id, key, name, role, map_x, map_y) -> None:
    """(cluster_id, key)로 유닛을 upsert."""
    unit = (
        db.query(Unit)
        .filter_by(cluster_id=cluster_id, key=key)
        .one_or_none()
    )
    if unit is None:
        unit = Unit(cluster_id=cluster_id, key=key)
        db.add(unit)
    unit.name = name
    unit.role = role
    unit.map_x = map_x
    unit.map_y = map_y


def _upsert_config(db: Session, key: str, value: str) -> None:
    row = db.query(Config).filter_by(key=key).one_or_none()
    if row is None:
        row = Config(key=key)
        db.add(row)
    row.value = value


def seed(db: Session) -> dict[str, int]:
    """시드를 멱등하게 적용하고 행 카운트를 반환한다."""
    for spec in CLUSTER_SEED:
        cluster = _upsert_cluster(db, spec)
        for key, name, role, mx, my in spec["units"]:
            _upsert_unit(db, cluster.id, key, name, role, mx, my)

    for key, value in CONFIG_SEED.items():
        _upsert_config(db, key, value)

    db.commit()

    return {
        "clusters": db.query(Cluster).count(),
        "units": db.query(Unit).count(),
        "config": db.query(Config).count(),
    }


def main() -> None:
    db = SessionLocal()
    try:
        counts = seed(db)
        print(
            f"Seed complete: {counts['clusters']} clusters, "
            f"{counts['units']} units, {counts['config']} config rows."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
