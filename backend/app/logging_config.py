"""Structured JSON logging.

tech-design §3 Observability: 모든 로그는 JSON으로 출력하고 task_id/user_id/attempt/crew
같은 컨텍스트 키를 함께 실을 수 있어야 한다. 표준 logging의 `extra=`로 넘긴 키를
JSON 필드로 직렬화한다.

외부 로깅 라이브러리(structlog 등)를 추가하지 않고 표준 logging.Formatter만으로 구현해
의존성을 최소화한다(tech-design §16 over-engineering 회피).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

# LogRecord의 기본 속성 집합 — 이 키들을 제외한 나머지가 사용자가 extra=로 넘긴 값이다.
_RESERVED = set(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """LogRecord를 단일 라인 JSON으로 직렬화한다."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        # extra=로 주입된 컨텍스트 키(task_id, user_id, attempt, crew 등)를 평면으로 합친다.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """루트 로거에 JSON 핸들러를 설정한다. 앱 부팅 시 1회 호출."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn 액세스 로그는 중복이 많아 노이즈를 줄인다.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
