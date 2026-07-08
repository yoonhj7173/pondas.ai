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

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import CreditAccount, CreditLedger

# 등급(model_tier) → task 1회 차감 크레딧 (D46 B-1). 비율 junior 1 : standard 3 : senior 30 유지,
# 단위 스케일은 목업(월≈2,000 = standard ~60개, 팩 +500~5,000)에 맞춰 ×10.
# 토큰 COGS 비율(haiku $0.015 : sonnet $0.045 : opus 수십센트)을 반영한 가중.
TIER_CREDIT_COST = {"light": 10, "medium": 30, "strong": 300}
DEFAULT_TASK_COST = 30  # 등급 불명 시 standard 취급.
# 가입 무료 크레딧(D46 B-5 → D52 갱신) — north-star 루프(D48)를 정확히 1회 무료 완주:
# strong dev task 1회(300) + light/medium 수정 지시 1~2회 커버. ~$1 COGS. 1계정 1회.
SIGNUP_CREDITS = 500


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


def _already_posted(db: Session, stripe_ref: str) -> bool:
    """이 stripe_ref로 적립(delta>0)한 원장 줄이 이미 있나 — 웹훅 중복 전송 멱등 가드(BUG-7).

    Stripe는 동일 이벤트를 재시도/중복 전송하며(at-least-once) 멱등 처리를 요구한다.
    가드 없으면 재전송마다 크레딧이 중복 적립된다.
    """
    return (
        db.query(CreditLedger.id)
        .filter(CreditLedger.stripe_ref == stripe_ref, CreditLedger.delta > 0)
        .first()
        is not None
    )


def _post(
    db: Session,
    user_id: str,
    delta: int,
    reason: str,
    *,
    task_id=None,
    stripe_ref: str | None = None,
    note: str | None = None,
    guard_min: int | None = None,
) -> int:
    """잔액 변동 1건 적용 — 원장 1줄 기록 + balance 캐시 갱신. 새 잔액 반환.

    모든 크레딧 변동의 단일 통로. balance_after를 원장에 박아 감사 가능하게 한다.
    stripe_ref가 이미 적립됐으면(웹훅 중복) 스킵하고 현재 잔액 반환(멱등).
    guard_min이 주어지면(차감 시 캡 ON) balance>=guard_min일 때만 원자적으로 차감하고, 조건
        미달(0행)이면 InsufficientCreditsError — 캡 체크와 차감이 한 문장이라 TOCTOU가 없다(감사 P0).
    """
    if delta > 0 and stripe_ref and _already_posted(db, stripe_ref):
        return get_or_create_account(db, user_id).balance
    acct = get_or_create_account(db, user_id)
    # 호출자가 미리 바꾼 속성(plan/signup_granted 등)을 먼저 영속화하고 행이 DB에 있게 한다.
    db.flush()
    # 잔액은 read-modify-write 대신 원자적 UPDATE로 더한다 — 동시 변동(워커 차감 + 웹훅 충전 등)에서
    # lost-update/캡 우회를 막는다(감사 P0). DB가 행 단위로 직렬화한다.
    stmt = update(CreditAccount).where(CreditAccount.user_id == user_id)
    if guard_min is not None:
        stmt = stmt.where(CreditAccount.balance >= guard_min)  # 캡 가드: 부족하면 0행 → 미차감.
    res = db.execute(stmt.values(balance=CreditAccount.balance + delta))
    if guard_min is not None and res.rowcount == 0:
        db.refresh(acct, attribute_names=["balance"])
        raise InsufficientCreditsError(-delta, acct.balance)
    db.refresh(acct, attribute_names=["balance"])  # 갱신된 잔액을 ORM 객체에 반영.
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
    # 캡 ON이면 원자적 조건부 차감(balance>=cost일 때만) — 캡 체크와 차감을 한 문장으로 묶어
    # 동시 디스패치 TOCTOU(캡 우회/음수 잔액)를 막는다(감사 P0). 락 없이 DB가 행 단위 직렬화.
    guard = cost if acct.spending_cap_enabled else None
    return _post(db, user_id, -cost, "task_charge", task_id=task_id, guard_min=guard)


def refund_task(db: Session, user_id: str, task_id, credits: int) -> int:
    """시스템 실패(우리 잘못) 환불 — 차감분을 크레딧으로 되돌림(D46 B-4). 현금 환불 아님."""
    return _post(db, user_id, credits, "refund_system_failure", task_id=task_id)


def topup(db: Session, user_id: str, credits: int, stripe_ref: str | None = None) -> int:
    """크레딧 팩 구매 적립(D46) — Stripe 결제 성공 웹훅이 호출. 탑업 크레딧은 소멸 없음(B-3)."""
    return _post(db, user_id, credits, "topup", stripe_ref=stripe_ref)


def apply_subscription_refill(
    db: Session, user_id: str, plan: str, allowance: int, stripe_ref: str | None = None
) -> int:
    """구독 결제 성공 시 — 플랜 설정 + 월 allowance 적립(D46).

    invoice.paid 웹훅이 매 청구주기 호출. MVP는 가산식(미사용분 전액 이월). D46 B-3의 1개월 캡
    이월/탑업-월분 버킷 분리는 추후 정교화 지점. 새 잔액 반환.
    """
    acct = get_or_create_account(db, user_id)
    acct.plan = plan
    acct.monthly_allowance = allowance
    return _post(db, user_id, allowance, "monthly_refill", stripe_ref=stripe_ref)
