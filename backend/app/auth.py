"""Clerk JWT verification dependency + tenancy scope helper.

tech-design §10 Security:
- AuthN: 모든 요청에서 Clerk가 발급한 JWT의 서명/issuer/만료를 검증한다.
- AuthZ/tenancy: 검증된 user_id(JWT `sub`)로만 동작한다. user_id는 절대 body에서
  받지 않는다 — 항상 토큰에서 추출한다.

검증 흐름:
1. `Authorization: Bearer <jwt>` 헤더(또는 SSE용 `?token=` 쿼리)에서 JWT를 꺼낸다.
2. Clerk의 JWKS 엔드포인트에서 공개키를 받아(캐시) RS256 서명을 검증한다.
3. issuer / 만료(exp) / not-before(nbf)를 검증한다.
4. `sub` 클레임을 user_id로 반환한다.

Clerk JWKS 통합(외부 API):
- publishable key(pk_test_<base64(domain$)>)를 디코드하면 frontend API 도메인이 나오고,
  issuer = https://<domain>, JWKS = https://<domain>/.well-known/jwks.json 이다.
- JWKS는 자주 안 바뀌므로 kid→공개키를 프로세스 메모리에 캐시한다. 모르는 kid가 오면
  (키 회전) 한 번 강제 리프레시한다.
"""

from __future__ import annotations

import base64
import threading
import time
from typing import Optional

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, Query, status
from jwt import PyJWKClient

from app.config import settings
from app.logging_config import get_logger

log = get_logger("app.auth")

# Clerk 토큰 서명 알고리즘. RS256만 허용한다(알고리즘 혼동 공격 방지 — none/HS 금지).
_ALLOWED_ALGORITHMS = ["RS256"]
# JWKS 캐시 수명(초). 키 회전 시에는 unknown-kid 경로에서 강제 리프레시도 한다.
_JWKS_CACHE_TTL = 600


def _decode_publishable_key(pk: str) -> Optional[str]:
    """Clerk publishable key에서 frontend API 도메인을 디코드한다.

    형식: `pk_(test|live)_<base64(domain + "$")>`. base64 payload를 디코드하면
    예: `true-kodiak-65.clerk.accounts.dev$` 가 나온다.
    """
    if not pk or "_" not in pk:
        return None
    parts = pk.split("_", 2)
    if len(parts) < 3:
        return None
    payload = parts[2]
    payload += "=" * (-len(payload) % 4)  # base64 패딩 보정
    try:
        decoded = base64.b64decode(payload).decode("utf-8")
    except Exception:  # noqa: BLE001
        return None
    return decoded.rstrip("$") or None


class ClerkAuthError(Exception):
    """검증 실패의 내부 표현. 라우트 의존성에서 401로 변환된다."""


class ClerkTokenVerifier:
    """Clerk JWT 검증기. issuer/JWKS를 한 번 해석하고 PyJWKClient로 키를 캐시한다.

    PyJWKClient는 kid로 서명 키를 조회하며 lifespan/lru 캐시를 자체 보유한다. 여기서는
    issuer 매칭과 알고리즘 화이트리스트, sub 존재를 추가로 강제한다.
    """

    def __init__(
        self,
        issuer: Optional[str] = None,
        jwks_url: Optional[str] = None,
    ) -> None:
        # 테스트에서 issuer/jwks_url을 직접 주입할 수 있게 인자로 받는다(stub JWKS 검증용).
        domain = _decode_publishable_key(
            getattr(settings, "clerk_publishable_key", "")
        )
        self.issuer = issuer or (f"https://{domain}" if domain else None)
        resolved_jwks = jwks_url or (
            f"https://{domain}/.well-known/jwks.json" if domain else None
        )
        self.jwks_url = resolved_jwks
        self._lock = threading.Lock()
        self._jwk_client: Optional[PyJWKClient] = None

    def _client(self) -> PyJWKClient:
        if self.jwks_url is None:
            raise ClerkAuthError("JWKS URL not configured")
        with self._lock:
            if self._jwk_client is None:
                # PyJWKClient: kid→키 캐시 + lifespan. 키 회전 시 자체적으로 재조회한다.
                self._jwk_client = PyJWKClient(
                    self.jwks_url,
                    cache_keys=True,
                    lifespan=_JWKS_CACHE_TTL,
                )
            return self._jwk_client

    def verify(self, token: str) -> str:
        """JWT를 검증하고 user_id(sub)를 반환한다. 실패 시 ClerkAuthError.

        서명(RS256, JWKS 공개키) + 만료(exp) + nbf + issuer를 검증한다. audience는
        Clerk 세션 토큰에서 선택적이므로 강제하지 않는다(issuer로 신뢰 경계를 잡는다).
        """
        try:
            signing_key = self._client().get_signing_key_from_jwt(token)
        except Exception as exc:  # noqa: BLE001  (PyJWK/네트워크 오류 포괄)
            raise ClerkAuthError(f"could not resolve signing key: {exc}") from exc

        options = {
            "require": ["exp", "sub"],  # 만료·주체가 없는 토큰은 거부
            "verify_signature": True,
            "verify_exp": True,
            "verify_nbf": True,
            "verify_iss": self.issuer is not None,
        }
        try:
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=_ALLOWED_ALGORITHMS,  # RS256만 — alg 혼동 공격 차단
                issuer=self.issuer,
                options=options,
            )
        except jwt.ExpiredSignatureError as exc:
            raise ClerkAuthError("token expired") from exc
        except jwt.InvalidIssuerError as exc:
            raise ClerkAuthError("invalid issuer") from exc
        except jwt.InvalidSignatureError as exc:
            raise ClerkAuthError("invalid signature") from exc
        except jwt.InvalidTokenError as exc:
            raise ClerkAuthError(f"invalid token: {exc}") from exc

        sub = claims.get("sub")
        if not sub or not isinstance(sub, str):
            raise ClerkAuthError("token missing sub claim")
        return sub


# 프로세스 전역 검증기 — JWKS 캐시를 공유한다. 테스트는 override_verifier로 교체한다.
_verifier: Optional[ClerkTokenVerifier] = None
_verifier_lock = threading.Lock()


def get_verifier() -> ClerkTokenVerifier:
    """전역 검증기 싱글턴. FastAPI 의존성이 주입받아 토큰을 검증한다.

    이 의존성을 오버라이드하면(app.dependency_overrides) 테스트에서 stub JWKS를 가리키는
    검증기로 교체할 수 있다 — 서명 검증 로직 자체는 그대로 타게 된다.
    """
    global _verifier
    if _verifier is None:
        with _verifier_lock:
            if _verifier is None:
                _verifier = ClerkTokenVerifier()
    return _verifier


def _extract_bearer(authorization: Optional[str], token_q: Optional[str]) -> str:
    """Authorization 헤더 또는 ?token= 쿼리에서 raw JWT를 추출한다.

    SSE는 EventSource가 커스텀 헤더를 못 붙이므로 쿼리 파라미터 토큰도 허용한다(§10).
    헤더가 우선한다.
    """
    if authorization:
        scheme, _, credential = authorization.partition(" ")
        if scheme.lower() != "bearer" or not credential:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return credential.strip()
    if token_q:
        return token_q.strip()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_user(
    authorization: Optional[str] = Header(default=None),
    token: Optional[str] = Query(default=None),
    verifier: ClerkTokenVerifier = Depends(get_verifier),
) -> str:
    """FastAPI 의존성: 검증된 Clerk user_id를 반환한다. 실패 시 401.

    라우트에서 `user_id: str = Depends(require_user)` 로 주입받으면, 그 핸들러는
    인증된 사용자에 한해서만 실행되고 user_id를 신뢰할 수 있다.
    """
    # E2E 우회(개발/테스트 전용, 기본 off) — 풀스택 브라우저 E2E에서 실 Clerk 세션 없이
    # 앱 와이어링을 검증하기 위함. settings.e2e_auth_bypass가 켜질 때만 활성(프로덕션 금지).
    # 인증 로직 자체는 test_auth.py(실 JWT 검증)로 별도 검증됨.
    if settings.e2e_auth_bypass:
        return settings.e2e_user_id

    raw = _extract_bearer(authorization, token)
    try:
        return verifier.verify(raw)
    except ClerkAuthError as exc:
        # 어떤 실패든 클라이언트엔 401로만 노출(원인 상세는 서버 로그에만).
        log.info("auth rejected", extra={"reason": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


class TenantScope:
    """테넌시 스코프 헬퍼 — 검증된 user_id로 쿼리를 강제로 좁힌다.

    tech-design §10 AuthZ: 모든 사용자 소유 쿼리는 user_id로 필터되어야 한다. 라우트가
    직접 .filter(Task.user_id == ...)를 잊지 않도록, 이 헬퍼를 통해서만 사용자 데이터를
    조회하는 규약을 둔다. 교차 사용자 접근은 구조적으로 빈 결과가 된다.
    """

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

    def query(self, db, model):
        """주어진 모델을 user_id로 스코프한 SQLAlchemy 쿼리를 반환한다.

        model은 user_id 컬럼을 가진 사용자 소유 테이블(Task, Notification)이어야 한다.
        """
        return db.query(model).filter(model.user_id == self.user_id)

    def owns(self, row) -> bool:
        """주어진 row가 이 테넌트 소유인지 확인한다. 단건 조회 후 소유권 확인용."""
        return getattr(row, "user_id", None) == self.user_id


def tenant_scope(user_id: str = Depends(require_user)) -> TenantScope:
    """FastAPI 의존성: 인증된 사용자에 바인딩된 TenantScope를 반환한다.

    `scope: TenantScope = Depends(tenant_scope)` 로 주입받아 scope.query(db, Task)로
    조회하면 항상 user_id로 좁혀진다.
    """
    return TenantScope(user_id)
