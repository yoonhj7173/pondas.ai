"""크레딧 원장 서비스 (빌링 D46) — 잔액 차감/충전/환불을 모두 원장 엔트리로 기록.

이 모듈이 빌링의 심장이다. 모든 크레딧 변동은 반드시 `_post`를 거쳐 CreditLedger에 1줄 남기고
CreditAccount.balance 캐시를 갱신한다(원자적). 직접 balance를 만지는 코드는 없어야 한다.

핵심 개념:
  - balance = 원장 누적의 캐시(권위는 ledger). 모든 변동에 balance_after 스냅샷 저장(감사).
  - 등급 가중 차감(D46 B-1): senior(opus)는 junior(haiku)보다 훨씬 많은 크레딧을 태운다 —
    opus가 ~10-20배 원가라 가중이 마진 필수.
  - 스펜딩 캡(D46 B-6, 기본 ON): 잔액 부족 시 task 차단 → 요금 폭탄 방지. 캡 OFF면 오버리지 허용.

연결: task 실행 차감 → worker_core(다음 증분에서 charge_task 호출). 가입 무료크레딧 → 가입 훅.
      Stripe 구독/탑업 → 다음 증분(monthly_refill/topup).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import CreditAccount, CreditLedger

# 등급(model_tier) → task 1회 차감 크레딧 (D46 B-1, junior 1 : standard 3 : senior ~30).
# 토큰 COGS 비율(haiku $0.015 : sonnet $0.045 : opus 수십센트)을 반영한 가중.
TIER_CREDIT_COST = {"light": 1, "medium": 3, "strong": 30}
DEFAULT_TASK_COST = 3  # 등급 불명 시 standard 취급.


class InsufficientCreditsError(Exception):
    """스펜딩 캡 ON 상태에서 잔액이 모자라 task를 실행할 수 없음 — 페이월 트리거(D46)."""

    def __init__(self, needed: int, balance: int):
        self.needed = needed
        self.balance = balance
        super().__init__(f"insufficient credits: need {needed}, have {balance}")


def get_or_create_account(db: Session, user_id: str) -> CreditAccount:
    """유저의 크레딧 지갑을 가져오거나(없으면) 만든다. free 플랜 + 잔액 0으로 시작."""
    acct = db.get(CreditAccount, user_id)
    if acct is None:
        acct = CreditAccount(user_id=user_id)
        db.add(acct)
        db.flush()
    return acct


def balance(db: Session, user_id: str) -> int:
    """현재 잔액(없으면 0). 읽기 전용 — 계정 생성하지 않음."""
    acct = db.get(CreditAccount, user_id)
    return acct.balance if acct else 0


def credit_cost(model_tier: str | None) -> int:
    """등급 → task 1회 차감 크레딧."""
    return TIER_CREDIT_COST.get(model_tier or "", DEFAULT_TASK_COST)


def _post(
    db: Session,
    user_id: str,
    delta: int,
    reason: str,
    *,
    task_id=None,
    stripe_ref: str | None = None,
    note: str | None = None,
) -> int:
    """잔액 변동 1건 적용 — 원장 1줄 기록 + balance 캐시 갱신. 새 잔액 반환.

    모든 크레딧 변동의 단일 통로. balance_after를 원장에 박아 감사 가능하게 한다.
    """
    acct = get_or_create_account(db, user_id)
    acct.balance += delta
    db.add(
        CreditLedger(
            user_id=user_id,
            delta=delta,
            reason=reason,
            balance_after=acct.balance,
            task_id=task_id,
            stripe_ref=stripe_ref,
            note=note,
        )
    )
    db.flush()
    return acct.balance


def grant_signup(db: Session, user_id: str, credits: int) -> int:
    """가입 무료 크레딧 — 1계정 1회만(D46 B-5). 이미 받았으면 no-op, 현재 잔액 반환."""
    acct = get_or_create_account(db, user_id)
    if acct.signup_granted:
        return acct.balance
    acct.signup_granted = True
    return _post(db, user_id, credits, "signup_grant", note="welcome credits")


def charge_task(db: Session, user_id: str, task_id, model_tier: str | None) -> int:
    """task 1회 실행분 차감(등급 가중). 스펜딩 캡 ON + 잔액 부족이면 차단(예외).

    캡 OFF면 오버리지 허용(잔액 음수 가능 = 후불). 새 잔액 반환.
    """
    cost = credit_cost(model_tier)
    acct = get_or_create_account(db, user_id)
    if acct.spending_cap_enabled and acct.balance < cost:
        raise InsufficientCreditsError(cost, acct.balance)
    return _post(db, user_id, -cost, "task_charge", task_id=task_id)


def refund_task(db: Session, user_id: str, task_id, credits: int) -> int:
    """시스템 실패(우리 잘못) 환불 — 차감분을 크레딧으로 되돌림(D46 B-4). 현금 환불 아님."""
    return _post(db, user_id, credits, "refund_system_failure", task_id=task_id)
