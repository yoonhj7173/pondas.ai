"""GET /map — 시드된 전역 토폴로지 read API (tech-design §6).

clusters + units(positions/roles 포함)를 반환한다. 이건 전역 템플릿이라 user 스코프가
없지만, 라우트 자체는 인증을 요구한다(§10: /health,/ready 외 모든 라우트는 Clerk JWT 필요).
require_user 의존성으로 인증을 강제하되 user_id는 쿼리에 쓰지 않는다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.models import Cluster, Unit
from app.schemas import ClusterOut, MapOut, UnitOut

router = APIRouter(prefix="/api", tags=["map"])


@router.get("/map", response_model=MapOut)
def get_map(
    _user_id: str = Depends(require_user),  # 인증 강제(전역 템플릿이라 스코프 필터는 없음)
    db: Session = Depends(get_db),
) -> MapOut:
    """전체 맵 토폴로지: 4 clusters / 8 units, 안정적 순서로 정렬.

    프론트 Pixi 씬 그래프가 결정적으로 빌드되도록 map_x로 정렬해 반환한다.
    """
    clusters = db.execute(select(Cluster).order_by(Cluster.map_x, Cluster.map_y)).scalars().all()
    units = db.execute(select(Unit).order_by(Unit.cluster_id, Unit.map_x)).scalars().all()
    return MapOut(
        clusters=[ClusterOut.model_validate(c) for c in clusters],
        units=[UnitOut.model_validate(u) for u in units],
    )
