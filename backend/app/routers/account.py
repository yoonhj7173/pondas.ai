"""Account API — 계정 삭제(GDPR/데이터 삭제권).

DELETE /api/account: 로그인한 사용자의 모든 데이터(프로젝트+샌드박스, 크레딧 지갑/원장, 프로필,
알림)를 지우고, 활성 Stripe 구독이 있으면 해지하며, 마지막으로 Clerk 사용자 계정을 삭제한다.
되돌릴 수 없다 — 프론트에서 강한 확인(타이핑) 후 호출한다.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth import TenantScope, tenant_scope
from app.config import settings
from app.db import get_db
from app.models import CreditAccount, CreditLedger, Notification, Project, UserProfile
from app.ratelimit import rate_limit
from app.services.slack_alerts import send_slack_alert

router = APIRouter(prefix="/api", tags=["account"])


@router.delete(
    "/account",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("5/minute", "account_delete"))],  # 파괴적 — 폭주 방지.
)
def delete_account(
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    """계정 완전 삭제 — 데이터 → (Stripe 구독 해지) → Clerk 사용자 순. 되돌릴 수 없음.

    무슨 일을 하나: 이 사용자에게 속한 모든 것을 지운다. 순서는 FK 충돌을 피하도록: 사용자-스코프
        행(알림/원장) → 프로젝트(샌드박스 파기 + cascade로 팀·에이전트·task·output 등) → 지갑/프로필.
        DB 커밋이 끝난 뒤에야 Clerk 사용자를 지운다(데이터가 먼저 사라져야 GDPR 삭제권 충족).
    누가 부르나: 설정 위험구역의 'Delete account'(강한 확인 후) — frontend/components/overlays/Overlays.tsx.
    되돌릴 수 없음: 실 결제(Stripe)/인증(Clerk) 정리는 best-effort — 실패해도 데이터 삭제는 진행하고
        Slack으로 알린다(수동 정리용).
    """
    uid = scope.user_id

    # 1. Stripe 활성 구독 해지(best-effort) — 계정 삭제 전에 미리(지갑 삭제 후엔 참조 못 함).
    acct = db.get(CreditAccount, uid)
    if acct and acct.stripe_subscription_id:
        try:
            from app.services import stripe_service

            stripe_service._api().Subscription.cancel(acct.stripe_subscription_id)
        except Exception as exc:  # noqa: BLE001
            send_slack_alert("account delete: stripe sub cancel failed", f"{uid}: {exc}")

    # 2. 사용자-스코프 행 먼저(프로젝트 삭제 시 FK 순서 문제 회피).
    db.query(Notification).filter(Notification.user_id == uid).delete(synchronize_session=False)
    db.query(CreditLedger).filter(CreditLedger.user_id == uid).delete(synchronize_session=False)

    # 3. 프로젝트 — 샌드박스 파기 후 삭제(FK cascade가 팀/에이전트/task/output/버전 등 하위 정리).
    from app.services.preview import preview_service
    from app.services.workspace import workspace_service

    for project in db.query(Project).filter(Project.user_id == uid).all():
        try:
            workspace_service.destroy(db, project)
            preview_service.destroy(db, project)
        except Exception:  # noqa: BLE001 — 샌드박스 정리 실패가 계정삭제를 막지 않음
            pass
        db.delete(project)

    # 4. 지갑 + 프로필.
    if acct:
        db.delete(acct)
    profile = db.get(UserProfile, uid)
    if profile:
        db.delete(profile)
    db.commit()

    # 5. Clerk 사용자 삭제(best-effort) — 데이터는 이미 지워졌으므로 실패해도 GDPR 충족.
    _delete_clerk_user(uid)


def _delete_clerk_user(user_id: str) -> None:
    """Clerk 백엔드 API로 사용자를 삭제한다(로그인 자체를 제거). 키 없거나 E2E면 건너뜀."""
    if not settings.clerk_secret_key or user_id.startswith("e2e"):
        return
    try:
        resp = httpx.delete(
            f"https://api.clerk.com/v1/users/{user_id}",
            headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
            timeout=10,
        )
        if resp.status_code >= 400:
            send_slack_alert(
                "account delete: clerk user delete failed",
                f"{user_id}: {resp.status_code} {resp.text[:200]}",
            )
    except Exception as exc:  # noqa: BLE001
        send_slack_alert("account delete: clerk user delete error", f"{user_id}: {exc}")
