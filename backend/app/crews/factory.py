"""실 CrewAI Crew 빌더 + 테스트용 mock LLM.

스파이크의 목적은 *실제 CrewAI 하네스 모양* 그대로 연속 플로우를 검증하는 것이다.
따라서 가짜 Crew를 만들지 않고, CrewAI의 `Agent`/`Task`/`Crew`를 그대로 쓰되
LLM만 주입 가능하게 한다. 라이브 Claude API 키 없이 테스트하기 위해 `ScriptedLLM`이
CrewAI `LLM`의 `.call()`을 오버라이드하여 미리 정해진 응답을 반환한다.

프로덕션에서는 동일한 build_crew 시그니처에 `crewai.LLM(model="claude-opus-4-8", ...)`를
주입하면 된다 (tech-design: agents use claude-opus-4-8).
"""

from __future__ import annotations

from typing import Callable

from crewai import Agent, Crew, Task
from crewai.llm import LLM


class ScriptedLLM(LLM):
    """미리 정해진 응답을 순서대로 반환하는 테스트용 LLM.

    CrewAI 내부는 LLM.call(messages, ...) -> str 계약에만 의존하므로, 이 메서드만
    오버라이드하면 Agent/Task/Crew의 실제 실행 경로를 그대로 타면서 Claude 호출만
    스크립트로 대체할 수 있다. (mocked Claude response)
    """

    def __new__(cls, responses: list[str] | None = None, model: str = "claude-opus-4-8"):
        # CrewAI LLM.__new__ 은 provider별 서브클래스로 라우팅하는 팩토리라서 그대로 쓰면
        # ScriptedLLM 인스턴스가 안 나온다. 라우팅을 우회해 LLM 타입의 빈 인스턴스를 만든다.
        return object.__new__(cls)

    def __init__(self, responses: list[str], model: str = "claude-opus-4-8"):
        # 부모 LLM 초기화 — model 문자열만 있으면 되고 실제 네트워크 호출은 하지 않는다.
        LLM.__init__(self, model=model)
        self._responses = list(responses)
        self._idx = 0
        self.calls: list = []  # 디버깅/검증용 호출 기록

    def call(self, messages, *args, **kwargs) -> str:  # type: ignore[override]
        self.calls.append(messages)
        if self._idx >= len(self._responses):
            # 스크립트 소진 시 마지막 응답을 반복 (방어적)
            return self._responses[-1] if self._responses else ""
        resp = self._responses[self._idx]
        self._idx += 1
        return resp


# cluster_key -> (role, goal, backstory). tech-design §4의 4개 클러스터 / 8개 유닛.
UNIT_DEFS: dict[str, tuple[str, str, str]] = {
    "product_manager": (
        "Product Manager",
        "Define clear, prioritized product requirements.",
        "A seasoned PM who turns vague asks into crisp specs.",
    ),
    "senior_engineer": (
        "Senior Engineer",
        "Implement robust, well-structured software.",
        "A pragmatic engineer who ships maintainable code.",
    ),
}


def build_crew_factory(
    llm: LLM,
    unit_key: str = "senior_engineer",
) -> Callable[[str], Crew]:
    """build_crew(prompt) -> Crew 팩토리를 만든다.

    CrewRunner가 재조립된 프롬프트를 Task description으로 주입하여 매 실행마다
    동일 Agent에 대해 새 Crew를 구성한다. human_input=False 임에 주의:
    우리는 CrewAI의 in-process HITL을 쓰지 않고 sentinel 컨벤션으로 needs-input을
    표면화한다 (tech-design §12).
    """
    role, goal, backstory = UNIT_DEFS.get(unit_key, UNIT_DEFS["senior_engineer"])

    def _build(prompt: str) -> Crew:
        agent = Agent(
            role=role,
            goal=goal,
            backstory=backstory,
            llm=llm,
            allow_delegation=False,
            verbose=False,
        )
        task = Task(
            description=prompt,
            expected_output=(
                "Either the final answer, or a single line "
                "'AWAITING_INPUT: <question>' if user input is required."
            ),
            agent=agent,
            human_input=False,
        )
        return Crew(agents=[agent], tasks=[task], verbose=False)

    return _build
