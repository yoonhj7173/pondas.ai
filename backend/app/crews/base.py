"""CrewAI continuation spike — minimal Crew runner.

이 모듈은 구현계획 item 1(가장 위험한 가정)을 검증한다:

  1. CrewAI Agent를 실행하고
  2. 구조화된 "사용자 입력 필요" 신호를 감지/표면화하며
  3. 재구성된 컨텍스트(이전 지시 + 새 지시)로 재실행하여
     blocked/needs-input → working 연속성을 in-process pause/resume 없이 구현한다.

핵심 설계 결정 (tech-design §12):
- CrewAI의 in-process Human-in-the-Loop(human_input=True) pause/resume에 의존하지 않는다.
  사람의 think-time 동안 워커/프로세스를 붙잡아 두는 것은 워커 재시작/배포/메모리 압박에
  취약하고 동시성 슬롯을 낭비한다.
- 대신, Agent 출력에 합의된 sentinel 컨벤션 `AWAITING_INPUT: <question>` 이 나타나면
  runner가 이를 파싱하여 needs-input 상태로 표면화하고, 부분 컨텍스트를 영속화한 뒤 종료한다.
- 연속(continue) 시에는 누적 컨텍스트(원 지시 + continuations[] + 직전 부분 출력)를 재조립한
  프롬프트로 *새* Crew를 실행한다. 이것이 "재실행 기반 연속" 방식이며 crash-safe하다.

LLM은 CrewAI `LLM` 추상화를 통해 주입되므로, 테스트에서는 라이브 Claude API 키 없이
mocked LLM으로 전체 플로우를 검증할 수 있다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol

# sentinel 컨벤션: Agent가 사용자 입력이 필요할 때 출력 어딘가에 이 마커를 포함한다.
# 예: "AWAITING_INPUT: 어떤 데이터베이스를 사용할까요? (Postgres/MySQL)"
AWAITING_INPUT_PATTERN = re.compile(
    r"AWAITING_INPUT:\s*(?P<question>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


class RunOutcome(str, Enum):
    """Crew 1회 실행의 결과 분류. tech-design §8 상태 머신의 일부에 매핑된다."""

    DONE = "done"
    NEEDS_INPUT = "needs-input"
    FAILED = "failed"


@dataclass
class RunResult:
    """Crew 실행 한 번의 결과.

    상위 계층(TaskService/worker)이 이 결과를 task row 상태 전이에 매핑한다.
    - outcome=NEEDS_INPUT  -> status `needs-input`, awaiting_prompt=question
    - outcome=DONE         -> status `done`, result_markdown=output
    - outcome=FAILED       -> status `failed`, error_summary
    """

    outcome: RunOutcome
    output: str
    awaiting_prompt: Optional[str] = None
    error_summary: Optional[str] = None


@dataclass
class CrewContext:
    """연속(continuation) 컨텍스트 누적기.

    하나의 task에 대한 누적 상태를 담는다. 재실행마다 새 Crew가 이 컨텍스트로부터
    프롬프트를 재조립하므로, 워커가 중간에 죽어도 DB에서 이 값들을 복원해 이어갈 수 있다.
    (MVP DB 매핑: instructions=str, continuations=jsonb, result_markdown=partial output)
    """

    instructions: str
    continuations: list[str] = field(default_factory=list)
    last_partial_output: Optional[str] = None

    def add_continuation(self, text: str) -> None:
        self.continuations.append(text)

    def build_prompt(self) -> str:
        """누적 컨텍스트를 단일 Agent 프롬프트 문자열로 재조립한다.

        이것이 "재실행 기반 연속"의 핵심이다: in-process 상태가 아니라
        프롬프트에 이전 턴을 모두 포함시켜 Agent가 사실상 이어서 작업하게 만든다.
        """
        parts: list[str] = []
        parts.append("# Original instructions\n" + self.instructions.strip())

        if self.last_partial_output:
            parts.append(
                "# Work produced so far (your previous partial output)\n"
                + self.last_partial_output.strip()
            )

        for i, cont in enumerate(self.continuations, start=1):
            parts.append(f"# User follow-up #{i}\n" + cont.strip())

        # sentinel 컨벤션을 Agent에게 명시적으로 지시한다.
        parts.append(
            "# Protocol\n"
            "If you have everything you need, produce the final answer.\n"
            "If and only if you cannot proceed without additional information from the "
            "user, respond with a single line exactly in the form:\n"
            "AWAITING_INPUT: <your one specific question>\n"
            "Do not guess or hallucinate missing facts."
        )
        return "\n\n".join(parts)


class CrewLike(Protocol):
    """테스트 가능한 Crew 추상화.

    실제로는 CrewAI `Crew` 인스턴스가 들어오지만, 단위 테스트는 mocked LLM을 주입한
    실 CrewAI Crew를 사용하므로 별도 가짜 구현이 필요 없다. 이 Protocol은 runner가
    `kickoff(inputs=...)`만 의존한다는 계약을 문서화한다.
    """

    def kickoff(self, inputs: Optional[dict] = None): ...  # noqa: E704


def detect_needs_input(output: str) -> Optional[str]:
    """Agent 출력에서 AWAITING_INPUT sentinel을 파싱한다.

    반환값이 None이면 입력 불필요(완료), 문자열이면 사용자에게 보여줄 질문이다.
    여러 개가 있으면 마지막(가장 최근) 질문을 사용한다.
    """
    matches = AWAITING_INPUT_PATTERN.findall(output or "")
    if not matches:
        return None
    return matches[-1].strip()


class CrewRunner:
    """CrewAI Crew를 1회 실행하고 결과를 분류하는 최소 runner.

    build_crew: CrewContext의 재조립된 프롬프트를 받아 실행 가능한 Crew를 만드는 팩토리.
                (실 구현은 cluster별 Agent/LLM을 주입한 CrewAI Crew를 반환)
    """

    def __init__(self, build_crew):
        self._build_crew = build_crew

    def run(self, ctx: CrewContext) -> RunResult:
        prompt = ctx.build_prompt()
        try:
            crew = self._build_crew(prompt)
            raw = crew.kickoff(inputs={"prompt": prompt})
            output = _coerce_output(raw)
        except Exception as exc:  # noqa: BLE001 - 워커 경계에서 모든 예외를 failed로 흡수
            return RunResult(
                outcome=RunOutcome.FAILED,
                output="",
                error_summary=f"{type(exc).__name__}: {exc}",
            )

        question = detect_needs_input(output)
        if question is not None:
            # 부분 출력을 컨텍스트에 영속화하여 다음 재실행이 이어받게 한다.
            ctx.last_partial_output = output
            return RunResult(
                outcome=RunOutcome.NEEDS_INPUT,
                output=output,
                awaiting_prompt=question,
            )

        return RunResult(outcome=RunOutcome.DONE, output=output)

    def continue_run(self, ctx: CrewContext, new_instructions: str) -> RunResult:
        """needs-input 상태에서 사용자 추가 지시를 받아 *새* 실행을 수행한다.

        이것이 연속 플로우의 진입점이다. in-process resume이 아니라,
        누적 컨텍스트에 새 지시를 더해 build_prompt()로 프롬프트를 재조립하고
        run()을 다시 호출한다 — 즉 매 연속은 새 Crew 실행(new attempt)이다.
        """
        ctx.add_continuation(new_instructions)
        return self.run(ctx)


def _coerce_output(raw) -> str:
    """CrewAI kickoff 반환값(CrewOutput 등)을 문자열로 정규화한다.

    CrewAI 버전에 따라 CrewOutput 객체 또는 문자열이 반환될 수 있어 방어적으로 처리한다.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    # CrewOutput은 .raw 속성에 최종 텍스트를 담는다.
    for attr in ("raw", "result"):
        val = getattr(raw, attr, None)
        if isinstance(val, str):
            return val
    return str(raw)
