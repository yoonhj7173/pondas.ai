"""Dev-runner tests (item 16) — LocalSandboxProvider + scripted agent.

'create a Python script that passes its own test'가 end-to-end로 돌고(verification에 pytest
exit 0 기록), needs-input 센티넬이 표면화되고, per-command 타임아웃이 깔끔히 종료되며, 토큰이
누적되는지 검증한다. (E2B + 실 Claude 라이브 검증은 동일 루프 + 키 필요.)
"""

from __future__ import annotations

import sys

import pytest

from app.services.dev_runner import DEFAULT_TASK_TIMEOUT_SEC, run_dev_task
from app.services.orchestrator import LLMResponse, ToolCall
from app.services.sandbox import LocalSandboxProvider


@pytest.fixture
def sandbox():
    p = LocalSandboxProvider()
    sid = p.create("proj", "python312")
    yield p, sid
    p.destroy(sid)


class ScriptedAgent:
    """미리 정해진 LLMResponse 시퀀스(도구 호출 → 최종 응답)."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.i = 0

    def complete(self, messages, tools):
        resp = self.steps[self.i]
        self.i = min(self.i + 1, len(self.steps) - 1)
        return resp


def _call(cid, name, args, tin=10, tout=5):
    return LLMResponse(tool_calls=[ToolCall(id=cid, name=name, args=args)], tokens_in=tin, tokens_out=tout)


def test_python_script_passes_its_own_test(sandbox):
    provider, sid = sandbox
    py = sys.executable  # 호스트 파이썬으로 실행(Local 프로바이더).
    agent = ScriptedAgent([
        _call("1", "write_file", {"path": "calc.py", "content": "def add(a, b):\n    return a + b\n"}),
        _call("2", "write_file", {"path": "test_calc.py", "content": "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"}),
        _call("3", "bash", {"cmd": f"{py} -m pytest -q test_calc.py"}),
        LLMResponse(content="Implemented add() and its test passes.", tokens_in=20, tokens_out=8),
    ])
    outcome = run_dev_task("Create a Python add() with a passing test.", provider, sid, client=agent)

    assert outcome.status == "done"
    # 파일이 실제로 샌드박스에 생성됨.
    assert provider.read_file(sid, "calc.py").startswith(b"def add")
    # verification에 pytest 명령 + exit 0 기록.
    pytest_cmd = next((v for v in outcome.verification if "pytest" in v["cmd"]), None)
    assert pytest_cmd is not None and pytest_cmd["exit_code"] == 0
    # 토큰 누적(3 도구스텝 ×(10,5) + 최종(20,8) = 50,23).
    assert outcome.tokens_in == 50 and outcome.tokens_out == 23


def test_failing_test_recorded(sandbox):
    provider, sid = sandbox
    py = sys.executable
    agent = ScriptedAgent([
        _call("1", "write_file", {"path": "bad.py", "content": "x = 1/0\n"}),
        _call("2", "bash", {"cmd": f"{py} bad.py"}),
        LLMResponse(content="It errors."),
    ])
    outcome = run_dev_task("run bad.py", provider, sid, client=agent)
    # 빌드/실행 실패가 verification에 non-zero로 남는다(working-as-expected 증적).
    run = next(v for v in outcome.verification if "bad.py" in v["cmd"])
    assert run["exit_code"] != 0


def test_needs_input_sentinel(sandbox):
    provider, sid = sandbox
    agent = ScriptedAgent([
        LLMResponse(content="AWAITING_INPUT: which web framework should I use?"),
    ])
    outcome = run_dev_task("build an app", provider, sid, client=agent)
    assert outcome.status == "needs-input"
    assert "framework" in outcome.awaiting_prompt


def test_per_command_timeout_killed_cleanly(sandbox):
    provider, sid = sandbox
    # 무한 sleep을 짧은 타임아웃으로 — per-command 타임아웃 경로(여기선 직접 도구 호출).
    from app.services.dev_runner import _exec_tool
    import app.services.dev_runner as dr
    dr.PER_COMMAND_TIMEOUT_SEC = 1  # 테스트용 단축
    try:
        v = []
        result = _exec_tool(provider, sid, ToolCall(id="x", name="bash", args={"cmd": "sleep 5"}), v)
        assert result["exit_code"] == -1 and "timed out" in result["error"]
        assert v[-1]["exit_code"] == -1
    finally:
        dr.PER_COMMAND_TIMEOUT_SEC = 300


def test_task_timeout_fails_cleanly(sandbox):
    provider, sid = sandbox
    # 항상 도구만 호출하는 에이전트 + task_timeout 0 → 즉시 시간초과 실패.
    agent = ScriptedAgent([_call("1", "bash", {"cmd": "echo loop"})])
    outcome = run_dev_task("loop forever", provider, sid, client=agent, task_timeout_sec=0)
    assert outcome.status == "failed" and "time budget" in outcome.error_summary


# --- 라이브 진행 콜백(QA-01) ---


def test_on_step_reports_progress_labels(sandbox):
    provider, sid = sandbox
    agent = ScriptedAgent([
        _call("1", "write_file", {"path": "app.py", "content": "print('hi')\n"}),
        _call("2", "bash", {"cmd": "python app.py"}),
        LLMResponse(content="Done."),
    ])
    labels = []
    outcome = run_dev_task("build it", provider, sid, client=agent, on_step=labels.append)
    assert outcome.status == "done"
    assert labels == ["Writing app.py", "Running: python app.py"]


def test_on_step_failure_does_not_break_loop(sandbox):
    provider, sid = sandbox
    agent = ScriptedAgent([
        _call("1", "write_file", {"path": "x.txt", "content": "x"}),
        LLMResponse(content="Done."),
    ])
    def boom(_label):
        raise RuntimeError("observer down")
    outcome = run_dev_task("go", provider, sid, client=agent, on_step=boom)
    assert outcome.status == "done"                     # 콜백 실패는 본 루프에 영향 없음
    assert provider.read_file(sid, "x.txt") == b"x"


# --- Stop 실효성(QA-05a): 스텝 경계에서 즉시 중단 + 부분 결과 보존 ---


def test_should_stop_aborts_between_steps(sandbox):
    provider, sid = sandbox
    agent = ScriptedAgent([
        _call("1", "bash", {"cmd": "echo step1"}),
        _call("2", "bash", {"cmd": "echo step2"}),   # 여기 도달하면 안 됨
        LLMResponse(content="Done."),
    ])
    answers = iter([False, True])                     # 1스텝 후 Stop 눌림
    outcome = run_dev_task("go", provider, sid, client=agent, should_stop=lambda: next(answers))
    assert outcome.status == "stopped"
    assert outcome.error_summary == "Stopped by user"
    assert [v["cmd"] for v in outcome.verification] == ["echo step1"]  # 2스텝은 실행 안 됨
    assert outcome.tokens_in == 10 and outcome.tokens_out == 5         # 부분 토큰 보존


def test_should_stop_error_ignored(sandbox):
    provider, sid = sandbox
    agent = ScriptedAgent([LLMResponse(content="Done.")])
    def boom():
        raise RuntimeError("db hiccup")
    outcome = run_dev_task("go", provider, sid, client=agent, should_stop=boom)
    assert outcome.status == "done"                   # 확인 실패는 루프를 못 깨뜨림


# --- 서브태스크 plan(QA-06): update_plan 도구 → 정제 + 콜백 ---


def test_update_plan_tool_calls_on_plan(sandbox):
    provider, sid = sandbox
    agent = ScriptedAgent([
        _call("1", "update_plan", {"steps": [
            {"title": "Set up project", "done": True},
            {"title": "Build home screen"},
        ]}),
        LLMResponse(content="Done."),
    ])
    plans = []
    outcome = run_dev_task("go", provider, sid, client=agent, on_plan=plans.append)
    assert outcome.status == "done"
    assert plans == [[
        {"title": "Set up project", "done": True},
        {"title": "Build home screen", "done": False},
    ]]


def test_update_plan_sanitizes_model_output(sandbox):
    from app.services.dev_runner import _sanitize_plan, PLAN_MAX_STEPS
    # 개수 캡 + 제목 길이 캡 + 쓰레기 항목 제거 + done 불리언 강제.
    steps = [{"title": "x" * 200, "done": "yes"}] + [{"title": f"s{i}"} for i in range(20)] + ["junk", {"done": True}]
    out = _sanitize_plan(steps)
    assert len(out) <= PLAN_MAX_STEPS
    assert len(out[0]["title"]) == 80 and out[0]["done"] is True
    assert all(isinstance(s["done"], bool) and s["title"] for s in out)
