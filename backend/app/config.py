"""Application configuration — env-driven settings + Claude pricing constants.

backend/.env (gitignored, real secrets)에서 값을 읽는다. 모든 모듈은 이 모듈의
`settings` 싱글턴을 통해서만 설정에 접근한다 — 환경변수를 직접 os.getenv 하지 않는다.

DATABASE_URL은 .env에 `postgresql://...` 형식으로 저장되어 있는데, SQLAlchemy +
psycopg2 드라이버를 명시하려면 `postgresql+psycopg2://...` 가 필요하다.
`sqlalchemy_database_url` 프로퍼티가 이 정규화를 담당한다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # .env 파일에서 로드. 환경변수가 .env보다 우선한다(배포 환경에서 주입 가능).
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env에 app이 모르는 키(프론트엔드용 등)가 있어도 무시
        case_sensitive=False,
    )

    # --- Claude API ---
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-opus-4-8", alias="ANTHROPIC_MODEL")
    # LLM 호출 타임아웃/재시도 — 프로바이더 행이 워커를 영구 점유하지 않게(prod 감사 P0).
    llm_request_timeout_sec: float = Field(default=120.0, alias="LLM_REQUEST_TIMEOUT_SEC")
    llm_num_retries: int = Field(default=1, alias="LLM_NUM_RETRIES")
    # 텍스트 에이전트 출력 상한 — 비용 런어웨이 방지(문서류엔 충분). 필요 시 env로 조정.
    text_agent_max_tokens: int = Field(default=4096, alias="TEXT_AGENT_MAX_TOKENS")
    # dev/design 코딩루프 성능(프롬프트 캐싱 + 스트리밍). 로컬에서 실 Anthropic 경로 검증 불가라
    # kill switch로 둔다 — 문제 시 Railway에서 DEV_FAST_MODE=false로 재배포 없이 즉시 원복.
    dev_fast_mode: bool = Field(default=True, alias="DEV_FAST_MODE")

    # --- Auth ---
    clerk_secret_key: str = Field(default="", alias="CLERK_SECRET_KEY")
    # Slack 운영 알림 Incoming Webhook(opt-in). 미설정 시 알림 no-op. URL이 채널(#proj-pondas)에 묶임.
    slack_alert_webhook_url: str = Field(default="", alias="SLACK_ALERT_WEBHOOK_URL")

    # --- Billing: Stripe (D46, sandbox 먼저 → live 스왑) ---
    stripe_secret_key: str = Field(default="", alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = Field(default="", alias="STRIPE_WEBHOOK_SECRET")
    # publishable key는 frontend API 도메인을 base64로 인코딩하고 있어, 여기서
    # issuer/JWKS URL을 유도한다(app/auth.py). 시크릿이 아니다(클라이언트도 보유).
    clerk_publishable_key: str = Field(
        default="", alias="NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY"
    )

    # --- Environment ---
    # "production"이면 보안 가드가 엄격해진다(E2B 강제, auth 우회 금지). 기본 dev.
    app_env: str = Field(default="dev", alias="APP_ENV")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in ("production", "prod")

    @property
    def allow_e2e_bypass(self) -> bool:
        """E2E 인증 우회 최종 게이트 — 우회 플래그 + '알려진 개발 환경'일 때만 허용(fail-safe).

        APP_ENV가 미설정/오타/staging 등 dev 화이트리스트에 없으면 우회를 거부한다 → 프로덕션에
        E2E_AUTH_BYPASS가 새어들어가도(APP_ENV까지 정확히 dev로 안 맞춘 이상) 인증이 안 뚫린다.
        """
        return self.e2e_auth_bypass and self.app_env.lower() in ("dev", "development", "test", "e2e", "local")

    # --- Infra ---
    database_url: str = Field(
        default="postgresql://cursorpm:cursorpm@localhost:5432/cursorpm",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # --- Execution sandbox (E2B, D29) ---
    e2b_api_key: str = Field(default="", alias="E2B_API_KEY")
    # 샌드박스 인터넷 접근(D31). 프로덕션은 egress 제한 커스텀 템플릿을 써야 하며(레지스트리
    # 허용리스트), 그건 E2B 템플릿 빌드 단계에서 설정한다. 이 플래그는 SDK 레벨 토글.
    sandbox_allow_internet: bool = Field(default=True, alias="SANDBOX_ALLOW_INTERNET")

    # --- Concurrency / cost guardrails (tech-design §5 config, §12 concurrency) ---
    concurrency_cap: int = Field(default=3, alias="CONCURRENCY_CAP")
    daily_cost_cap_usd: float = Field(default=10.0, alias="DAILY_COST_CAP_USD")

    # --- Claude pricing constants (USD per 1K tokens) for cost estimation ---
    # tech-design §5 config: cost_per_1k_in / cost_per_1k_out. 토큰→비용 환산에 사용.
    # Claude Opus 가격 가정값. 환경변수로 오버라이드 가능(가격 변동 대응).
    cost_per_1k_in: float = Field(default=0.015, alias="COST_PER_1K_IN")
    cost_per_1k_out: float = Field(default=0.075, alias="COST_PER_1K_OUT")

    # --- E2E auth bypass (DEV/TEST ONLY — 기본 off, 프로덕션 금지) ---
    e2e_auth_bypass: bool = Field(default=False, alias="E2E_AUTH_BYPASS")
    e2e_user_id: str = Field(default="e2e_user", alias="E2E_USER_ID")

    # --- App ---
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    cors_origins: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")

    @property
    def sqlalchemy_database_url(self) -> str:
        """SQLAlchemy가 psycopg2 드라이버를 명시적으로 쓰도록 URL을 정규화한다."""
        url = self.database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def estimate_cost_usd(self, tokens_in: int, tokens_out: int) -> float:
        """입력/출력 토큰 수로부터 추정 비용(USD)을 계산한다. resource bar / 가드레일용."""
        return round(
            (tokens_in / 1000.0) * self.cost_per_1k_in
            + (tokens_out / 1000.0) * self.cost_per_1k_out,
            6,
        )


@lru_cache
def get_settings() -> Settings:
    """설정 싱글턴. lru_cache로 프로세스당 1회만 .env를 읽는다."""
    return Settings()


settings = get_settings()
