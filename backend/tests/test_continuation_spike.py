"""구현계획 item 1 검증 테스트 — CrewAI 연속 스파이크.

핵심 시나리오(가장 위험한 가정):
  run -> needs-input 캡처 -> continue -> 완료까지 재개
모두 mocked Claude(ScriptedLLM)로 라이브 API 키 없이 검증한다.

이 테스트들은 두 레벨을 커버한다:
  1) 순수 로직 (sentinel 파싱, 컨텍스트 재조립) — CrewAI 독립
  2) 실 CrewAI 하네스를 통한 end-to-end 연속 (ScriptedLLM 주입)
"""

from __future__ import annotations

import pytest

from app.crews.base import (
    CrewContext,
    CrewRunner,
    RunOutcome,
    detect_needs_input,
)


# ---------------------------------------------------------------------------
# 1) 순수 로직: sentinel 감지
# ---------------------------------------------------------------------------

def test_detect_needs_input_returns_none_on_plain_output():
    assert detect_needs_input("Here is the final answer. All done.") is None


def test_detect_needs_input_parses_question():
    out = "I started the spec.\nAWAITING_INPUT: Which database — Postgres or MySQL?"
    assert detect_needs_input(out) == "Which database — Postgres or MySQL?"


def test_detect_needs_input_uses_last_marker_when_multiple():
    out = "AWAITING_INPUT: first?\nsome work\nAWAITING_INPUT: second?"
    assert detect_needs_input(out) == "second?"


# ---------------------------------------------------------------------------
# 2) 컨텍스트 재조립: 연속 시 이전 턴이 프롬프트에 포함되는가
# ---------------------------------------------------------------------------

def test_build_prompt_accumulates_context():
    ctx = CrewContext(instructions="Write a deploy plan.")
    ctx.last_partial_output = "Drafted step 1."
    ctx.add_continuation("Use Railway, not AWS.")

    prompt = ctx.build_prompt()

    assert "Write a deploy plan." in prompt
    assert "Drafted step 1." in prompt
    assert "Use Railway, not AWS." in prompt
    assert "AWAITING_INPUT:" in prompt  # 프로토콜 지시가 항상 포함됨


# ---------------------------------------------------------------------------
# 3) Runner 단위: 가짜 build_crew로 분기 검증 (CrewAI 미의존)
# ---------------------------------------------------------------------------

class _FakeCrew:
    def __init__(self, output: str):
        self._output = output

    def kickoff(self, inputs=None):
        return self._output


def test_runner_marks_needs_input():
    runner = CrewRunner(build_crew=lambda prompt: _FakeCrew(
        "Partial work.\nAWAITING_INPUT: What region?"
    ))
    ctx = CrewContext(instructions="Provision infra.")
    res = runner.run(ctx)

    assert res.outcome is RunOutcome.NEEDS_INPUT
    assert res.awaiting_prompt == "What region?"
    # 부분 출력이 컨텍스트에 영속화되어 다음 재실행이 이어받음
    assert ctx.last_partial_output is not None


def test_runner_marks_done():
    runner = CrewRunner(build_crew=lambda prompt: _FakeCrew("Final answer."))
    res = runner.run(CrewContext(instructions="Say hi."))
    assert res.outcome is RunOutcome.DONE
    assert res.output == "Final answer."


def test_runner_absorbs_exception_as_failed():
    def boom(prompt):
        raise RuntimeError("claude down")

    res = CrewRunner(build_crew=boom).run(CrewContext(instructions="x"))
    assert res.outcome is RunOutcome.FAILED
    assert "claude down" in res.error_summary


def test_continue_run_reaches_done_pure():
    """needs-input -> continue -> done 전체 라운드트립 (순수 로직)."""
    outputs = iter([
        "Started.\nAWAITING_INPUT: Which framework?",
        "Done: built it with FastAPI.",
    ])
    runner = CrewRunner(build_crew=lambda prompt: _FakeCrew(next(outputs)))
    ctx = CrewContext(instructions="Build a web API.")

    first = runner.run(ctx)
    assert first.outcome is RunOutcome.NEEDS_INPUT

    second = runner.continue_run(ctx, new_instructions="Use FastAPI.")
    assert second.outcome is RunOutcome.DONE
    assert "FastAPI" in second.output
    # 연속 지시가 누적되었는지 확인
    assert ctx.continuations == ["Use FastAPI."]


# ---------------------------------------------------------------------------
# 4) END-TO-END: 실 CrewAI 하네스 + mocked Claude (ScriptedLLM)
#    이것이 스파이크의 핵심 — 라이브 API 키 없이 실제 Agent/Task/Crew 경로를 탄다.
# ---------------------------------------------------------------------------

crewai = pytest.importorskip("crewai")


def test_crewai_end_to_end_continuation_with_mocked_claude():
    from app.crews.factory import ScriptedLLM, build_crew_factory

    # 첫 실행은 needs-input sentinel, 연속 실행은 완료를 반환하도록 스크립트.
    scripted = ScriptedLLM(responses=[
        "I began the deployment plan.\n"
        "AWAITING_INPUT: Which cloud provider should I target?",
        "Final deployment plan:\n1. Build image\n2. Deploy to Railway\nComplete.",
    ])
    build_crew = build_crew_factory(llm=scripted, unit_key="senior_engineer")
    runner = CrewRunner(build_crew=build_crew)

    ctx = CrewContext(instructions="Write a deployment plan for our backend.")

    # --- run: needs-input 캡처 ---
    first = runner.run(ctx)
    assert first.outcome is RunOutcome.NEEDS_INPUT
    assert "cloud provider" in first.awaiting_prompt.lower()

    # --- continue: 완료까지 재개 ---
    second = runner.continue_run(ctx, new_instructions="Target Railway.")
    assert second.outcome is RunOutcome.DONE
    assert "Railway" in second.output

    # mocked Claude가 실제로 (CrewAI 경유) 두 번 호출되었는지 검증.
    assert len(scripted.calls) >= 2
