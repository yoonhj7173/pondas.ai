"""실행 가능한 스파이크 데모 — 사람이 직접 플로우를 눈으로 확인하기 위한 스크립트.

라이브 Claude API 키 없이 mocked Claude(ScriptedLLM)로 다음을 보여준다:
  assign -> run -> needs-input(질문 표면화) -> continue(사용자 답변) -> done

실행: backend/.venv/bin/python backend/scripts/continuation_spike_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# backend/ 를 import 경로에 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.crews.base import CrewContext, CrewRunner, RunOutcome  # noqa: E402
from app.crews.factory import ScriptedLLM, build_crew_factory  # noqa: E402


def main() -> int:
    scripted = ScriptedLLM(responses=[
        "I started outlining the deployment plan.\n"
        "AWAITING_INPUT: Which cloud provider should I target?",
        "Final deployment plan:\n"
        "1. Containerize the FastAPI backend\n"
        "2. Provision Postgres + Redis on Railway\n"
        "3. Deploy web + worker + beat services\n"
        "Done.",
    ])
    runner = CrewRunner(build_crew=build_crew_factory(llm=scripted))
    ctx = CrewContext(instructions="Write a deployment plan for our backend.")

    print("=== ASSIGN ===")
    print(f"instructions: {ctx.instructions}\n")

    print("=== RUN ===")
    first = runner.run(ctx)
    print(f"outcome: {first.outcome.value}")
    assert first.outcome is RunOutcome.NEEDS_INPUT, first.outcome
    print(f"needs-input question: {first.awaiting_prompt}\n")

    print("=== CONTINUE (user answers) ===")
    answer = "Target Railway."
    print(f"user reply: {answer}")
    second = runner.continue_run(ctx, new_instructions=answer)
    print(f"outcome: {second.outcome.value}")
    assert second.outcome is RunOutcome.DONE, second.outcome
    print("\n--- final result ---")
    print(second.output)

    print("\n=== SPIKE VALIDATED ===")
    print(f"mocked Claude calls (via CrewAI): {len(scripted.calls)}")
    print(f"accumulated continuations: {ctx.continuations}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
