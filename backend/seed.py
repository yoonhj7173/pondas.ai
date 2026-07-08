"""Idempotent seed — 4 team templates + 11 role-catalog rows + config maps.

tech-design §5 / decision-log D40/D41/D43/D44. 템플릿은 전역 read-only 시드다:
- team_templates: key로 upsert (planning/research/design/development; Data는 P1).
- agent_templates: (template_key, role_key)로 upsert — 역할 카탈로그(role-catalog.md 전사).
- config: key로 upsert (티어맵/가격맵/캡/버짓/타임아웃).

여러 번 실행해도 정확히 4 templates / 11 roles / N config가 유지된다(중복 없음). 데이터는
app/catalog.py에 있고(= GET /templates도 같은 소스), 여기선 upsert 로직만 담는다.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.catalog import TEAM_TEMPLATES, config_seed
from app.config import settings
from app.db import SessionLocal
from app.models import AgentTemplate, Config, TeamTemplate


def _upsert_team_template(db: Session, spec: dict) -> None:
    """key로 팀 템플릿을 upsert하고, 그 역할 카탈로그를 (template_key, role_key)로 upsert."""
    tt = db.query(TeamTemplate).filter_by(key=spec["key"]).one_or_none()
    if tt is None:
        tt = TeamTemplate(key=spec["key"])
        db.add(tt)
    tt.name = spec["name"]
    tt.description = spec["description"]
    tt.engine = spec["engine"]
    db.flush()

    for (
        role_key,
        display_name,
        role_instructions,
        default_tier,
        is_starter,
        out_type,
        out_target,
        out_max_iter,
    ) in spec["roles"]:
        at = (
            db.query(AgentTemplate)
            .filter_by(template_key=spec["key"], role_key=role_key)
            .one_or_none()
        )
        if at is None:
            at = AgentTemplate(template_key=spec["key"], role_key=role_key)
            db.add(at)
        at.display_name = display_name
        at.role_instructions = role_instructions
        at.default_tier = default_tier
        at.is_starter = is_starter
        at.default_output_type = out_type
        at.default_output_target_role_key = out_target
        at.default_max_iterations = out_max_iter


# 유저가 설정 UI에서 튜닝하는 키(D32: config가 authoritative, 배포 없이 조정) — seed가 매 배포마다
# env 기본값으로 덮어쓰면 라이브 튜닝이 리셋된다. 이미 있으면 보존하고, 없을 때만 초기값을 심는다.
_PRESERVE_IF_SET = frozenset({"daily_cost_cap_usd", "concurrency_cap"})


def _upsert_config(db: Session, key: str, value: str) -> None:
    row = db.query(Config).filter_by(key=key).one_or_none()
    if row is None:
        db.add(Config(key=key, value=value))
        return
    if key in _PRESERVE_IF_SET:
        return  # 라이브 튜닝 값 보존.
    row.value = value


def seed(db: Session) -> dict[str, int]:
    """시드를 멱등하게 적용하고 행 카운트를 반환한다."""
    for spec in TEAM_TEMPLATES:
        _upsert_team_template(db, spec)

    for key, value in config_seed(
        settings.daily_cost_cap_usd, settings.concurrency_cap
    ).items():
        _upsert_config(db, key, value)

    db.commit()

    return {
        "team_templates": db.query(TeamTemplate).count(),
        "agent_templates": db.query(AgentTemplate).count(),
        "config": db.query(Config).count(),
    }


def main() -> None:
    db = SessionLocal()
    try:
        counts = seed(db)
        print(
            f"Seed complete: {counts['team_templates']} team templates, "
            f"{counts['agent_templates']} role-catalog rows, "
            f"{counts['config']} config rows."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
