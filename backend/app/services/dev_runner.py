"""Dev-runner — 샌드박스 안에서 도는 코딩 에이전트 루프(item 16, D30/D31).

dev/design task 1건마다 새 에이전트 세션을 워크스페이스(SandboxProvider) 안에서 돌린다:
bash/file 도구로 코드를 쓰고 명령을 실행하며, 모든 명령+exit code를 tasks.verification으로
기록한다("working as expected" 증적, D31). 센티넬: AWAITING_INPUT → needs-input,
APPROVED(리뷰어) → GraphEngine이 루프 종료(D19). per-command + per-task(기본 30분) 타임아웃.

LLM "brain"은 주입 가능(테스트=스크립트). 프로덕션은 Claude Agent SDK / LiteLLM 툴루프를
이 인터페이스 뒤에 꽂는다(루프/도구/검증은 동일). re-enqueue 철학 유지 — 세션은 매번 새로
시작하고 워크스페이스가 구체 상태를 들고 있다(§14).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from app.crews.base import detect_needs_input
from app.services.orchestrator import LLMResponse, ToolCall  # 정규화된 응답 재사용
from app.services.sandbox import SandboxProvider, SandboxTimeout

log = logging.getLogger("app.dev_runner")

MAX_STEPS = 40
DEFAULT_TASK_TIMEOUT_SEC = 30 * 60
PER_COMMAND_TIMEOUT_SEC = 300
_SUMMARY_CAP = 2000        # verification DB행 요약(UI 표시용) — 모델에게 주는 캡과 별개.
# 모델에게 보여주는 툴 결과 캡. 기존엔 전 필드 2,000자 head-절단이라 긴 빌드 에러의
# 실제 원인(대개 로그 끝)이 잘려 에이전트가 못 고쳤다. 캐싱이 켜져 있어(이전 스텝 결과는
# cache_read 0.1×) 넉넉히 줘도 반복 비용은 낮다.
_TOOL_RESULT_CAP = 30_000   # bash stdout/stderr 합산 기준(필드당 절반씩)
_READ_FILE_CAP = 16_000     # read_file 1회 내용 캡 — 초과분은 offset/limit으로 이어 읽기
# LLM 호출 재시도 — API 일시 장애(429/529/타임아웃) 1번에 30분 태스크가 통째로 죽지 않게.
_LLM_RETRIES = 2            # 총 3회 시도
_retry_sleep = time.sleep   # 테스트에서 대기 없이 패치하기 위한 이음새.

# dev 에이전트 도구(샌드박스에서 실행).
DEV_TOOLS = [
    {"type": "function", "function": {
        "name": "bash",
        "description": "Run a shell command in the workspace and get exit code + output.",
        "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write a file in the workspace (creates parent dirs).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"},
        }, "required": ["path", "content"]},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": (
            "Read a file from the workspace. Large files are clipped — use offset/limit "
            "(1-based line number / line count) to read a specific range."
        ),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "description": "1-based first line to read"},
            "limit": {"type": "integer", "description": "max lines to return"},
        }, "required": ["path"]},
    }},
    # 서브태스크 plan(QA-06 2단계) — 유저에게 진행률 체크리스트로 보인다. 전체 교체 방식(멱등).
    {"type": "function", "function": {
        "name": "update_plan",
        "description": (
            "Share/update your work plan with the user as a short checklist (3-6 steps). "
            "Call this FIRST with your plan, then again whenever you complete a step "
            "(send the full list each time, marking finished steps done:true)."
        ),
        "parameters": {"type": "object", "properties": {
            "steps": {"type": "array", "items": {"type": "object", "properties": {
                "title": {"type": "string"}, "done": {"type": "boolean"},
            }, "required": ["title"]}},
        }, "required": ["steps"]},
    }},
]

PLAN_MAX_STEPS = 8
PLAN_TITLE_CAP = 80


def _clip(s: str, cap: int) -> str:
    """긴 텍스트를 cap 이내로 — 머리 1/4 + 꼬리 3/4 보존(빌드 에러는 대개 끝에 있다).

    기존 head-only 절단([:cap])은 에러 로그의 실제 원인을 잘라 에이전트가 헛돌게 했다.
    잘린 사실과 분량을 마커로 남겨 모델이 '전부 봤다'고 착각하지 않게 한다.
    """
    if len(s) <= cap:
        return s
    head = cap // 4
    tail = cap - head
    return s[:head] + f"\n…[{len(s) - cap} chars truncated]…\n" + s[-tail:]


def _sanitize_plan(steps) -> list[dict]:
    """update_plan 인자 정제 — 모델 출력이므로 개수/길이/타입을 강제한다."""
    out: list[dict] = []
    for s in (steps or [])[:PLAN_MAX_STEPS]:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title", "")).strip()[:PLAN_TITLE_CAP]
        if title:
            out.append({"title": title, "done": bool(s.get("done", False))})
    return out

_WORKSPACE_CONVENTIONS = (
    "# Workspace conventions\n"
    "You are working inside a sandbox. Use the bash/write_file/read_file tools to build and "
    "verify real software. Verify by RUNNING — a passing build is not success; the feature must "
    "work as expected. When you start a dev server, run it in the background. When you are done "
    "and everything works, give a short final summary. If you are a reviewer and the work meets "
    "the bar, include the word APPROVED. If you cannot proceed without information only the user "
    "can give, reply with a single line 'AWAITING_INPUT: <question>'.\n"
    "Start by calling update_plan with a short checklist (3-6 steps) of how you'll approach the "
    "task, and call it again (full list) each time you finish a step — the user watches this "
    "checklist to follow your progress.\n"
    "Build INCREMENTALLY in small files: split UI into per-screen/per-component files "
    "(e.g. src/screens/Home.tsx, src/components/Card.tsx) rather than dumping one giant file. "
    "A single monolithic file makes one huge, slow write and hides progress — many small "
    "write_file calls are faster and let the user watch each piece land."
)


@dataclass
class DevOutcome:
    status: str                 # done | needs-input | failed | stopped
    output: str = ""
    awaiting_prompt: str | None = None
    error_summary: str | None = None
    verification: list = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cache_read: int = 0   # 캐시 히트 관측(비용) — 로그/추후 대시보드용.
    tokens_cache_write: int = 0


def _step_label(call: ToolCall) -> str:
    """도구 호출 → 사람이 읽을 진행 한 줄(QA-01). 예: 'Writing src/App.tsx', 'Running: npm test'."""
    if call.name == "write_file":
        return f"Writing {call.args.get('path', '?')}"
    if call.name == "read_file":
        return f"Reading {call.args.get('path', '?')}"
    if call.name == "bash":
        return f"Running: {call.args.get('cmd', '')[:80]}"
    if call.name == "update_plan":
        return "Updating plan"
    return call.name


def _exec_tool(provider: SandboxProvider, sandbox_id: str, call: ToolCall, verification: list) -> dict:
    """도구 1개를 샌드박스에서 실행. bash는 verification에 명령 로그를 남긴다."""
    name, args = call.name, call.args
    if name == "bash":
        cmd = args.get("cmd", "")
        try:
            res = provider.exec(sandbox_id, cmd, timeout=PER_COMMAND_TIMEOUT_SEC)
            # UI용 요약(짧게, 꼬리 위주)과 모델용 결과(넉넉히)를 분리 — 모델은 에러 전문을 봐야 고친다.
            summary = _clip(res.stdout + res.stderr, _SUMMARY_CAP)
            verification.append({"cmd": cmd, "exit_code": res.exit_code, "summary": summary})
            half = _TOOL_RESULT_CAP // 2
            return {"exit_code": res.exit_code, "stdout": _clip(res.stdout, half), "stderr": _clip(res.stderr, half)}
        except SandboxTimeout:
            # per-command 타임아웃 → 깔끔히 종료된 것으로 기록하고 에이전트에 알린다.
            verification.append({"cmd": cmd, "exit_code": -1, "summary": "command timed out (killed)"})
            return {"exit_code": -1, "error": "command timed out and was killed"}
    if name == "write_file":
        provider.write_file(sandbox_id, args["path"], args.get("content", "").encode("utf-8"))
        return {"ok": True}
    if name == "read_file":
        try:
            text = provider.read_file(sandbox_id, args["path"]).decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        lines = text.splitlines()
        total = len(lines)
        # offset/limit(1-based 줄) — 큰 파일을 조각으로 읽는다(입력 토큰 폭발 방지).
        offset = max(int(args.get("offset") or 1), 1)
        limit = args.get("limit")
        end = min(offset - 1 + int(limit), total) if limit else total
        chunk = "\n".join(lines[offset - 1:end])
        clipped = _clip(chunk, _READ_FILE_CAP)
        result = {"content": clipped, "total_lines": total}
        if offset > 1 or end < total or clipped is not chunk:
            result["note"] = (
                f"showing lines {offset}-{end} of {total}"
                + ("; content clipped — use offset/limit to read the rest" if clipped is not chunk else "")
            )
        return result
    return {"error": f"unknown tool {name}"}


def run_dev_task(
    task_prompt: str,
    provider: SandboxProvider,
    sandbox_id: str,
    *,
    client,
    role_instructions: str = "",
    task_timeout_sec: int = DEFAULT_TASK_TIMEOUT_SEC,
    on_step=None,  # (label: str) -> None — 스텝별 라이브 진행 콜백(QA-01). 실패해도 루프 안 깨짐.
    should_stop=None,  # () -> bool — 스텝 경계마다 확인(QA-05a). True면 즉시 status="stopped" 반환.
    on_plan=None,  # (steps: list[dict]) -> None — update_plan 도구 호출 시 정제된 plan 전달(QA-06).
) -> DevOutcome:
    """코딩 에이전트 루프 — 샌드박스 안에서 AI가 직접 코드를 쓰고·돌려보고·고치길 반복한다.

    개발·디자인 작업의 심장. 글쓰기팀(orchestrator의 툴루프와 비슷)과 달리, 여기 도구는 실제
    컴퓨터를 만진다: bash(명령 실행)·write_file(파일 쓰기)·read_file(파일 읽기).

    무슨 일을 하나: AI에게 도구를 주고 "직접 만들고, 빌드 통과가 아니라 '실제로 동작'할 때까지 확인하라"고
        시킨다. AI가 도구를 부르면 샌드박스에서 실행해 결과를 돌려주고, AI는 그걸 보고 다음 행동을 정한다.
    누가 부르나: _run_dev_task (backend/app/services/worker_core.py).
    처리 순서(최대 40스텝, 기본 30분 제한):
        1. 역할 + 워크스페이스 규약을 시스템 지시로 깐다.
        2. 반복: client.complete(LLM 호출) → 도구를 부르면 _exec_tool로 실행해 결과 회신 → 다시 LLM.
        3. 도구 없이 답만 내놓으면 종료. 'AWAITING_INPUT:'이면 needs-input, 아니면 done.
        4. 돌린 모든 명령+종료코드를 verification에 기록(= "정말 동작함" 증적).
    연결: 명령 실행 → 이 파일 _exec_tool → sandbox.py. 결과를 받아 처리 → worker_core.py의 _run_dev_task.
        (client=LLM 두뇌는 주입형 — 테스트는 스크립트, 프로덕션은 LiteLLM)
    """
    system = (role_instructions.strip() + "\n\n" + _WORKSPACE_CONVENTIONS).strip()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": task_prompt},
    ]
    verification: list = []
    tokens_in = tokens_out = cache_read = cache_write = 0
    start = time.time()

    for _ in range(MAX_STEPS):
        # Stop 확인(QA-05a) — 유저가 Stop을 눌렀으면 다음 스텝을 시작하지 않고 즉시 접는다.
        # 기존엔 kill_current(베스트에포트)뿐이라 Stop 후에도 루프가 몇 분씩 더 돌았다(실사례 6분).
        # 지금까지의 토큰/verification은 들고 나가서 호출부가 부분 작업물을 보존한다(QA-05b).
        if should_stop is not None:
            try:
                stop = bool(should_stop())
            except Exception:  # noqa: BLE001 — 확인 실패는 계속 진행(관측이 본 루프를 못 깨뜨림)
                stop = False
            if stop:
                return DevOutcome(status="stopped", error_summary="Stopped by user",
                                  verification=verification, tokens_in=tokens_in, tokens_out=tokens_out,
                              tokens_cache_read=cache_read, tokens_cache_write=cache_write)
        if time.time() - start > task_timeout_sec:
            return DevOutcome(status="failed", error_summary="dev task exceeded time budget",
                              verification=verification, tokens_in=tokens_in, tokens_out=tokens_out,
                              tokens_cache_read=cache_read, tokens_cache_write=cache_write)
        # LLM 호출 + 스텝 재시도 — 일시 장애(429/529/타임아웃) 1번에 30분 작업이 통째로
        # 죽지 않게 한다. 재시도 간 백오프(2s→8s). 전부 실패하면 그때 failed.
        resp = None
        last_exc: Exception | None = None
        for attempt in range(_LLM_RETRIES + 1):
            try:
                resp = client.complete(messages, DEV_TOOLS)
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < _LLM_RETRIES:
                    log.warning("llm call failed (attempt %d/%d): %s", attempt + 1, _LLM_RETRIES + 1, exc)
                    _retry_sleep(2 * (4 ** attempt))
        if resp is None:
            return DevOutcome(status="failed", error_summary=f"agent error: {last_exc}",
                              verification=verification, tokens_in=tokens_in, tokens_out=tokens_out,
                              tokens_cache_read=cache_read, tokens_cache_write=cache_write)
        tokens_in += resp.tokens_in
        tokens_out += resp.tokens_out
        cache_read += resp.tokens_cache_read
        cache_write += resp.tokens_cache_write

        if resp.tool_calls:
            messages.append({
                "role": "assistant", "content": None,
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.args)}}
                    for c in resp.tool_calls
                ],
            })
            for c in resp.tool_calls:
                if on_step is not None:
                    try:
                        on_step(_step_label(c))
                    except Exception:  # noqa: BLE001 — 진행 표시는 관측용, 본 루프를 못 깨뜨림
                        pass
                if c.name == "update_plan":
                    # 샌드박스를 안 만지는 메타 도구(QA-06) — 정제 후 콜백으로 영속/브로드캐스트 위임.
                    plan = _sanitize_plan(c.args.get("steps"))
                    if on_plan is not None and plan:
                        try:
                            on_plan(plan)
                        except Exception:  # noqa: BLE001 — 관측용
                            pass
                    result: dict = {"ok": True, "steps": len(plan)}
                else:
                    result = _exec_tool(provider, sandbox_id, c, verification)
                # 필드별로 이미 캡됨 — JSON 중간을 자르는 블라인드 슬라이스는 모델에게 깨진 구조를 보여줬다.
                messages.append({"role": "tool", "tool_call_id": c.id, "content": _clip(json.dumps(result), _TOOL_RESULT_CAP * 4)})
            continue

        output = resp.content or ""
        question = detect_needs_input(output)
        if question is not None:
            return DevOutcome(status="needs-input", output=output, awaiting_prompt=question,
                              verification=verification, tokens_in=tokens_in, tokens_out=tokens_out,
                              tokens_cache_read=cache_read, tokens_cache_write=cache_write)
        return DevOutcome(status="done", output=output, verification=verification,
                          tokens_in=tokens_in, tokens_out=tokens_out,
                          tokens_cache_read=cache_read, tokens_cache_write=cache_write)

    return DevOutcome(status="failed", error_summary=f"dev task exceeded {MAX_STEPS} steps",
                      verification=verification, tokens_in=tokens_in, tokens_out=tokens_out,
                              tokens_cache_read=cache_read, tokens_cache_write=cache_write)
