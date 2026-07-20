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
    # 항상 도구만 호출하는 에이전트 + task_timeout 0 → 즉시 시간 예산 소진.
    # D56③: 시간 초과는 이제 failed가 아니라 우아한 needs-input(부분 결과 + 이어가기).
    agent = ScriptedAgent([_call("1", "bash", {"cmd": "echo loop"})])
    outcome = run_dev_task("loop forever", provider, sid, client=agent, task_timeout_sec=0)
    assert outcome.status == "needs-input" and "continue" in (outcome.awaiting_prompt or "")


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


# --- PR harness-cost-stability: 툴결과 캡/tail 보존 + read_file range + LLM 재시도 ---

from app.services import dev_runner as dr  # noqa: E402


def test_clip_preserves_tail():
    # 빌드 에러의 실제 원인은 로그 끝에 있다 — head-only 절단 회귀 방지.
    s = "x" * 1000 + "ERROR: the real cause"
    out = dr._clip(s, 200)
    assert "ERROR: the real cause" in out
    assert "truncated" in out
    assert len(out) <= 200 + 60  # 마커 여유


def test_bash_long_output_tail_visible(sandbox):
    provider, sid = sandbox
    py = sys.executable
    verification = []
    call = ToolCall(id="1", name="bash",
                    args={"cmd": f'{py} -c "print(\'x\'*5000); print(\'THE_REAL_ERROR\')"'})
    res = dr._exec_tool(provider, sid, call, verification)
    assert "THE_REAL_ERROR" in res["stdout"]              # 모델에게 꼬리(진짜 에러)가 보인다
    assert "THE_REAL_ERROR" in verification[0]["summary"]  # UI 요약(2000캡)도 꼬리 보존


def test_read_file_offset_limit(sandbox):
    provider, sid = sandbox
    content = "\n".join(f"line{i}" for i in range(1, 101))
    provider.write_file(sid, "big.txt", content.encode())
    res = dr._exec_tool(provider, sid, ToolCall(id="1", name="read_file",
                        args={"path": "big.txt", "offset": 10, "limit": 5}), [])
    assert res["content"].splitlines() == [f"line{i}" for i in range(10, 15)]
    assert res["total_lines"] == 100
    assert "lines 10-14 of 100" in res["note"]


def test_read_file_large_clipped(sandbox):
    provider, sid = sandbox
    provider.write_file(sid, "huge.txt", ("A" * 100 + "\n").encode() * 500)  # ~50k chars
    res = dr._exec_tool(provider, sid, ToolCall(id="1", name="read_file", args={"path": "huge.txt"}), [])
    assert len(res["content"]) <= dr._READ_FILE_CAP + 60
    assert "clipped" in res["note"]


class FlakyAgent:
    """앞 n회는 예외, 이후엔 정상 응답 — 스텝 재시도 검증용."""

    def __init__(self, fails: int, then: LLMResponse):
        self.fails, self.then, self.calls = fails, then, 0

    def complete(self, messages, tools):
        self.calls += 1
        if self.calls <= self.fails:
            raise RuntimeError("transient provider error")
        return self.then


def test_llm_retry_recovers(sandbox, monkeypatch):
    # API가 2번 딸꾹질해도 태스크는 살아야 한다(총 3회 시도).
    monkeypatch.setattr(dr, "_retry_sleep", lambda s: None)
    provider, sid = sandbox
    agent = FlakyAgent(2, LLMResponse(content="Done."))
    outcome = run_dev_task("do it", provider, sid, client=agent)
    assert outcome.status == "done"
    assert agent.calls == 3


def test_llm_retry_exhausted_fails(sandbox, monkeypatch):
    monkeypatch.setattr(dr, "_retry_sleep", lambda s: None)
    provider, sid = sandbox
    agent = FlakyAgent(99, LLMResponse(content="never"))
    outcome = run_dev_task("do it", provider, sid, client=agent)
    assert outcome.status == "failed"
    assert "agent error" in outcome.error_summary
    assert agent.calls == 3  # _LLM_RETRIES+1


def test_cache_tokens_accumulate(sandbox):
    provider, sid = sandbox
    agent = ScriptedAgent([
        LLMResponse(tool_calls=[ToolCall(id="1", name="update_plan", args={"steps": [{"title": "t"}]})],
                    tokens_in=10, tokens_out=5, tokens_cache_read=100, tokens_cache_write=7),
        LLMResponse(content="Done.", tokens_in=3, tokens_out=2, tokens_cache_read=50),
    ])
    outcome = run_dev_task("do it", provider, sid, client=agent)
    assert outcome.status == "done"
    assert (outcome.tokens_in, outcome.tokens_out) == (13, 7)
    assert (outcome.tokens_cache_read, outcome.tokens_cache_write) == (150, 7)


# --- PR harness-tools: edit_file(문자열 치환) + 워크스페이스 스냅샷 ---


def test_edit_file_replaces_snippet(sandbox):
    provider, sid = sandbox
    provider.write_file(sid, "app.py", b"def greet():\n    return 'hello'\n\nprint(greet())\n")
    res = dr._exec_tool(provider, sid, ToolCall(id="1", name="edit_file", args={
        "path": "app.py", "old_string": "return 'hello'", "new_string": "return 'world'"}), [])
    assert res == {"ok": True, "replacements": 1}
    content = provider.read_file(sid, "app.py").decode()
    assert "return 'world'" in content
    assert "print(greet())" in content  # 나머지 내용 보존 — whole-file rewrite가 아님


def test_edit_file_not_found_error(sandbox):
    provider, sid = sandbox
    provider.write_file(sid, "a.txt", b"actual content")
    res = dr._exec_tool(provider, sid, ToolCall(id="1", name="edit_file", args={
        "path": "a.txt", "old_string": "no such text", "new_string": "x"}), [])
    assert "not found" in res["error"]


def test_edit_file_ambiguous_requires_replace_all(sandbox):
    provider, sid = sandbox
    provider.write_file(sid, "b.txt", b"dup\ndup\n")
    res = dr._exec_tool(provider, sid, ToolCall(id="1", name="edit_file", args={
        "path": "b.txt", "old_string": "dup", "new_string": "x"}), [])
    assert "2 times" in res["error"]
    res2 = dr._exec_tool(provider, sid, ToolCall(id="1", name="edit_file", args={
        "path": "b.txt", "old_string": "dup", "new_string": "x", "replace_all": True}), [])
    assert res2 == {"ok": True, "replacements": 2}
    assert provider.read_file(sid, "b.txt") == b"x\nx\n"


class CapturingAgent:
    """messages를 캡처하고 즉시 종료 — 프롬프트 조립 검증용."""

    def __init__(self):
        self.seen = None

    def complete(self, messages, tools):
        self.seen = [dict(m) for m in messages]
        return LLMResponse(content="Done.")


def test_workspace_snapshot_in_first_prompt(sandbox):
    # A5: 기존 파일 목록이 첫 user 메시지에 깔린다 — 첫 스텝 `ls` 낭비 제거.
    provider, sid = sandbox
    provider.write_file(sid, "src/main.py", b"print('x')\n")
    agent = CapturingAgent()
    run_dev_task("continue the work", provider, sid, client=agent)
    user_msg = agent.seen[1]["content"]
    assert "# Workspace files (snapshot)" in user_msg
    assert "src/main.py" in user_msg


# ── D56③ 예산제 + 컴팩션 (item 38) ─────────────────────────────────────────────


class LoopingAgent:
    """항상 도구를 호출하는 에이전트 — 예산 없이는 영원히 도는 시나리오."""

    def __init__(self, tin=10, tout=5):
        self.tin, self.tout = tin, tout
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        return LLMResponse(
            tool_calls=[ToolCall(id=str(self.calls), name="bash", args={"cmd": "true"})],
            tokens_in=self.tin, tokens_out=self.tout,
        )


def test_token_budget_exhaustion_is_graceful_needs_input(sandbox):
    """토큰 예산 소진 = failed가 아니라 needs-input(부분 결과 + 이어가기) — 조용한 실패 금지."""
    provider, sid = sandbox
    agent = LoopingAgent(tin=100, tout=50)
    outcome = run_dev_task("Endless task.", provider, sid, client=agent, token_budget=500)

    assert outcome.status == "needs-input"
    assert "continue" in (outcome.awaiting_prompt or "")
    # 예산(500)에 도달할 만큼만 돌았다: 150/스텝 → 4스텝째 진입 전 중단(600 >= 500).
    assert 3 <= agent.calls <= 5
    # 지금까지의 사용량은 보존된다(회계).
    assert outcome.tokens_in + outcome.tokens_out >= 500


def test_time_budget_exhaustion_is_graceful_needs_input(sandbox, monkeypatch):
    """시간 예산 초과도 동일하게 우아한 needs-input — 구 'failed: exceeded time budget' 대체."""
    provider, sid = sandbox
    agent = LoopingAgent()
    outcome = run_dev_task("Slow task.", provider, sid, client=agent, task_timeout_sec=0)
    assert outcome.status == "needs-input"
    assert "continue" in (outcome.awaiting_prompt or "")


def test_hard_step_cap_backstop(sandbox, monkeypatch):
    """토큰 예산이 무제한(0)이어도 하드 스텝 캡이 폭주를 막는다."""
    import app.services.dev_runner as dr
    monkeypatch.setattr(dr, "HARD_STEP_CAP", 6)
    provider, sid = sandbox
    agent = LoopingAgent()
    outcome = run_dev_task("Endless task.", provider, sid, client=agent, token_budget=0)
    assert outcome.status == "needs-input"
    assert agent.calls == 6


class CompactionAgent:
    """도구 호출을 반복하다 컴팩션 요약 요청(tools=[])에는 요약 텍스트로 답하는 에이전트."""

    def __init__(self, big_ctx_after=3):
        self.calls = 0
        self.summaries = 0
        self.big_ctx_after = big_ctx_after
        self.seen_compacted = False

    def complete(self, messages, tools):
        if tools == []:  # 컴팩션 요약 호출
            self.summaries += 1
            return LLMResponse(content="Summary: wrote a.py and b.py; tests pass; next step c.py.",
                               tokens_in=50, tokens_out=20)
        self.calls += 1
        # 컴팩션이 실제로 히스토리를 바꿨는지 관찰.
        if any(isinstance(m.get("content"), str) and "Earlier work compacted" in m["content"] for m in messages):
            self.seen_compacted = True
            return LLMResponse(content="Done after compaction.", tokens_in=10, tokens_out=5)
        # big_ctx_after 스텝부터 실효 프롬프트가 임계를 넘는 것으로 보고.
        big = self.calls >= self.big_ctx_after
        return LLMResponse(
            tool_calls=[ToolCall(id=str(self.calls), name="bash", args={"cmd": "true"})],
            tokens_in=200_000 if big else 100, tokens_out=10,
        )


def test_compaction_replaces_middle_history(sandbox):
    """실효 프롬프트가 임계를 넘으면 중간 히스토리가 요약 한 개로 교체되고 작업은 계속된다."""
    provider, sid = sandbox
    agent = CompactionAgent(big_ctx_after=3)
    # 컴팩션 조건(len > HEAD+TAIL+4 = 14 메시지)을 만들려면 도구 스텝이 충분히 쌓여야 한다.
    outcome = run_dev_task("Long task.", provider, sid, client=agent,
                           token_budget=10_000_000, compact_threshold=150_000)
    assert outcome.status == "done"
    assert agent.summaries >= 1          # 요약 호출이 실제로 나갔고
    assert agent.seen_compacted          # 이후 호출의 히스토리에 요약 마커가 들어있다


def test_compaction_failure_is_safe(sandbox):
    """요약 호출이 죽어도 본 루프는 계속된다(컴팩션은 최적화일 뿐)."""
    provider, sid = sandbox

    class FailingSummaryAgent(CompactionAgent):
        def complete(self, messages, tools):
            if tools == []:
                raise RuntimeError("summary call failed")
            return super().complete(messages, tools)

    agent = FailingSummaryAgent(big_ctx_after=3)
    outcome = run_dev_task("Long task.", provider, sid, client=agent,
                           token_budget=10_000_000, compact_threshold=150_000)
    # 컴팩션 실패 → 히스토리 유지 → seen_compacted 경로가 없으니 예산/캡 전에 done은 못 만든다.
    # 대신 하드 캡/토큰 예산 내에서 needs-input 또는 done 어느 쪽이든 '조용한 크래시'만 아니면 된다.
    assert outcome.status in ("done", "needs-input")
