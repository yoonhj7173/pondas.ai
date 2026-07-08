"""텍스트 에이전트 출력 헬퍼 — needs-input 센티넬 파싱 + 출력 정규화(엔진 무관).

에이전트 출력에 합의된 마커 `AWAITING_INPUT: <question>` 가 나타나면 needs-input으로 표면화한다
(CrewAI의 in-process HITL pause/resume에 의존하지 않는다 — 워커를 붙잡아 두면 재시작/배포에
취약하고 동시성 슬롯을 낭비하므로, 센티넬 + 재실행 기반 연속 방식을 쓴다 · tech-design §12).
"""

from __future__ import annotations

import re
from typing import Optional

# sentinel 컨벤션: Agent가 사용자 입력이 필요할 때 출력 어딘가에 이 마커를 포함한다.
# 예: "AWAITING_INPUT: 어떤 데이터베이스를 사용할까요? (Postgres/MySQL)"
AWAITING_INPUT_PATTERN = re.compile(
    r"AWAITING_INPUT:\s*(?P<question>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def detect_needs_input(output: str) -> Optional[str]:
    """Agent 출력에서 AWAITING_INPUT sentinel을 파싱한다.

    반환값이 None이면 입력 불필요(완료), 문자열이면 사용자에게 보여줄 질문이다.
    여러 개가 있으면 마지막(가장 최근) 질문을 사용한다.
    """
    matches = AWAITING_INPUT_PATTERN.findall(output or "")
    if not matches:
        return None
    return matches[-1].strip()


def _coerce_output(raw) -> str:
    """LLM 반환값을 문자열로 정규화한다(문자열이 아니어도 방어적으로 처리)."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    for attr in ("raw", "result", "content"):
        val = getattr(raw, attr, None)
        if isinstance(val, str):
            return val
    return str(raw)
