"""Auth demo route — exercises the Clerk JWT dependency end-to-end.

item 4 검증용 보호 라우트. 실제 비즈니스 라우터(map/units/tasks 등)는 이후 item에서
이 동일한 `require_user`/`tenant_scope` 의존성을 재사용한다. 여기서는 인증 경로가
실제로 401/통과하는지 curl로 증명할 수 있게 최소 엔드포인트만 둔다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import TenantScope, require_user, tenant_scope

router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/me")
def me(user_id: str = Depends(require_user)) -> dict:
    """검증된 Clerk user_id를 그대로 돌려준다. 무인증/잘못된 토큰이면 의존성이 401."""
    return {"user_id": user_id}


@router.get("/whoami")
def whoami(scope: TenantScope = Depends(tenant_scope)) -> dict:
    """TenantScope 주입 경로 검증 — scope에 바인딩된 user_id가 보이는지 확인."""
    return {"tenant": scope.user_id}
