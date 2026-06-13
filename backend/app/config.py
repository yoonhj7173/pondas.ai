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

    # --- Auth ---
    clerk_secret_key: str = Field(default="", alias="CLERK_SECRET_KEY")
    # publishable key는 frontend API 도메인을 base64로 인코딩하고 있어, 여기서
    # issuer/JWKS URL을 유도한다(app/auth.py). 시크릿이 아니다(클라이언트도 보유).
    clerk_publishable_key: str = Field(
        default="", alias="NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY"
    )

    # --- Infra ---
    database_url: str = Field(
        default="postgresql://cursorpm:cursorpm@localhost:5432/cursorpm",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # --- Concurrency / cost guardrails (tech-design §5 config, §12 concurrency) ---
    concurrency_cap: int = Field(default=3, alias="CONCURRENCY_CAP")
    daily_cost_cap_usd: float = Field(default=10.0, alias="DAILY_COST_CAP_USD")

    # --- Claude pricing constants (USD per 1K tokens) for cost estimation ---
    # tech-design §5 config: cost_per_1k_in / cost_per_1k_out. 토큰→비용 환산에 사용.
    # Claude Opus 가격 가정값. 환경변수로 오버라이드 가능(가격 변동 대응).
    cost_per_1k_in: float = Field(default=0.015, alias="COST_PER_1K_IN")
    cost_per_1k_out: float = Field(default=0.075, alias="COST_PER_1K_OUT")

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
