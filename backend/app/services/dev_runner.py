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

# D56③ 예산제 — 구 MAX_STEPS(40) 벽 폐기(Joshua 3연속 실패의 직접 원인). 실제 한도는
# 토큰 예산(settings.dev_token_budget)과 시간 예산이며, 아래는 폭주 방지용 하드 캡일 뿐.
HARD_STEP_CAP = 500
DEFAULT_TASK_TIMEOUT_SEC = 30 * 60
# 예산 소진 시 유저에게 보여줄 사람말 안내(D56③: 조용한 실패 금지 — 부분 결과 + 이어가기).
_BUDGET_PROMPT = (
    "I've used up this task's work budget before finishing. Everything I built so far is saved "
    "in the workspace — reply 'continue' and I'll pick up right where I left off."
)
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
    # 문자열 치환 편집(Claude Code의 Edit 계약) — 파일 전체 재작성(write_file)은 몇 줄 고치는 데도
    # 파일 전체를 출력 토큰(최고가)으로 다시 뱉는다: 느리고 비싸고 기존 코드 유실 위험.
    {"type": "function", "function": {
        "name": "edit_file",
        "description": (
            "Replace an exact text snippet in an existing file. old_string must match the file "
            "content EXACTLY (including whitespace) and appear exactly once — include a few "
            "surrounding lines to make it unique, or set replace_all to change every occurrence. "
            "ALWAYS prefer this over write_file when modifying an existing file."
        ),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean", "description": "replace every occurrence (default false)"},
        }, "required": ["path", "old_string", "new_string"]},
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
    "You are working inside a sandbox. Use the bash/write_file/edit_file/read_file tools to build "
    "and verify real software. Verify by RUNNING — a passing build is not success; the feature must "
    "work as expected. When you start a dev server, run it in the background "
    "(append ' > /tmp/dev.log 2>&1 &' so the command returns immediately). When you are done "
    "and everything works, give a short final summary. If you are a reviewer and the work meets "
    "the bar, include the word APPROVED. If you cannot proceed without information only the user "
    "can give, reply with a single line 'AWAITING_INPUT: <question>'.\n"
    "To MODIFY an existing file, use edit_file (exact-snippet replacement) — never rewrite a "
    "whole file with write_file to change a few lines. write_file is for NEW files.\n"
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


def _workspace_snapshot(provider: SandboxProvider, sandbox_id: str) -> str:
    """워크스페이스 파일 목록 스냅샷(최대 200개) — 시작 프롬프트에 깔아 첫 `ls` 스텝을 없앤다.

    Claude Code가 시스템 프롬프트에 환경 정보(cwd/파일)를 까는 것과 같은 계약. 베스트에포트 —
    실패해도 태스크는 정상 진행(에이전트가 직접 둘러보면 됨).
    """
    try:
        res = provider.exec(
            sandbox_id,
            "find . -type f -not -path './node_modules/*' -not -path './.git/*' "
            "-not -path './.next/*' -not -path './dist/*' | head -200",
            timeout=30,
        )
        listing = (res.stdout or "").strip()
    except Exception:  # noqa: BLE001 — 관측용, 본 루프를 못 깨뜨림
        return ""
    return listing or "(workspace is empty)"


def _step_label(call: ToolCall) -> str:
    """도구 호출 → 사람이 읽을 진행 한 줄(QA-01). 예: 'Writing src/App.tsx', 'Running: npm test'."""
    if call.name == "write_file":
        return f"Writing {call.args.get('path', '?')}"
    if call.name == "edit_file":
        return f"Editing {call.args.get('path', '?')}"
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
    if name == "edit_file":
        # 문자열 치환 편집 — old_string이 정확히 1회(또는 replace_all) 나타나야 안전하게 적용.
        try:
            text = provider.read_file(sandbox_id, args["path"]).decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return {"error": f"cannot read {args.get('path')}: {exc}"}
        old = args.get("old_string", "")
        new = args.get("new_string", "")
        if not old:
            return {"error": "old_string is required"}
        count = text.count(old)
        if count == 0:
            return {"error": "old_string not found — it must match the file content exactly "
                             "(read the file first and copy the exact text)"}
        if count > 1 and not args.get("replace_all"):
            return {"error": f"old_string appears {count} times — include more surrounding lines "
                             "to make it unique, or set replace_all:true"}
        updated = text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1)
        provider.write_file(sandbox_id, args["path"], updated.encode("utf-8"))
        return {"ok": True, "replacements": count if args.get("replace_all") else 1}
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


def _compact_messages(messages: list, client) -> tuple[int, int]:
    """컨텍스트 컴팩션(D56③) — 중간 히스토리를 한 개의 요약 메시지로 압축한다.

    구조: [system, user(과제)] + [중간 작업 로그...] + [최근 꼬리] 에서 중간만 요약으로 교체.
    tool 메시지는 자기 assistant(tool_calls)와 떨어지면 API가 거부하므로, 꼬리 시작점을
    tool이 아닌 메시지까지 앞으로 당겨 페어를 보존한다. 요약 실패 시 아무것도 안 바꾼다(안전).
    반환: 요약 호출에 쓴 (tokens_in, tokens_out) — 호출부가 태스크 사용량에 합산.
    """
    HEAD, TAIL = 2, 8
    if len(messages) <= HEAD + TAIL + 4:  # 압축할 중간이 충분히 없으면 스킵
        return (0, 0)
    tail_start = len(messages) - TAIL
    while tail_start > HEAD and messages[tail_start].get("role") == "tool":
        tail_start -= 1  # tool은 자기 assistant 뒤에 붙어야 함 — 페어 경계까지 당김
    middle = messages[HEAD:tail_start]
    if len(middle) < 4:
        return (0, 0)
    # 중간 로그를 텍스트로 직렬화(툴콜 이름/인자 요점 + 결과 앞부분만).
    lines: list[str] = []
    for m in middle:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            calls = ", ".join(c["function"]["name"] for c in m["tool_calls"])
            lines.append(f"assistant tools: {calls}")
            for c in m["tool_calls"]:
                lines.append(f"  args: {str(c['function'].get('arguments', ''))[:300]}")
        else:
            lines.append(f"{role}: {str(m.get('content') or '')[:500]}")
    log_text = "\n".join(lines)[:60_000]
    try:
        resp = client.complete([
            {"role": "system", "content": (
                "You compact a coding agent's work log. Summarize concisely: files created/modified "
                "(with paths), commands run and key results, decisions made, current state, and what "
                "remains. Preserve exact paths and error messages that may matter later."
            )},
            {"role": "user", "content": log_text},
        ], [])
    except Exception as exc:  # noqa: BLE001 — 컴팩션은 최적화일 뿐, 실패해도 본 루프는 계속.
        log.warning("compaction failed, keeping full history: %s", exc)
        return (0, 0)
    summary = resp.content or ""
    if not summary.strip():
        return (0, 0)
    messages[HEAD:tail_start] = [{
        "role": "user",
        "content": f"[Earlier work compacted — summary]\n{summary}",
    }]
    log.info("compacted %d messages into summary (%d chars)", len(middle), len(summary))
    return (resp.tokens_in, resp.tokens_out)


def run_dev_task(
    task_prompt: str,
    provider: SandboxProvider,
    sandbox_id: str,
    *,
    client,
    role_instructions: str = "",
    task_timeout_sec: int = DEFAULT_TASK_TIMEOUT_SEC,
    token_budget: int = 0,        # in+out 합산 토큰 예산(D56③). 0 = 무제한.
    compact_threshold: int = 0,   # 실효 프롬프트(tokens_in+cache_read) 컴팩션 임계. 0 = 끔.
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
    # 시작 시 파일 목록을 깔아준다(A5) — 없으면 에이전트가 첫 스텝을 `ls`에 낭비한다.
    snapshot = _workspace_snapshot(provider, sandbox_id)
    user_prompt = task_prompt
    if snapshot:
        user_prompt += f"\n\n# Workspace files (snapshot)\n{snapshot}"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]
    verification: list = []
    tokens_in = tokens_out = cache_read = cache_write = 0
    start = time.time()

    def _budget_outcome(reason: str) -> DevOutcome:
        # 예산 소진 = 실패가 아니라 needs-input(D56③) — 기존 continuation/재개 파이프를 그대로
        # 재사용한다: 워크스페이스는 영속이라 "continue" 재개 태스크가 파일 위에서 이어간다.
        log.info("dev task budget exhausted (%s): in=%d out=%d", reason, tokens_in, tokens_out)
        progress = f"[Budget reached — {reason}. Partial work is saved in the workspace; ready to continue.]"
        return DevOutcome(status="needs-input", output=progress, awaiting_prompt=_BUDGET_PROMPT,
                          verification=verification, tokens_in=tokens_in, tokens_out=tokens_out,
                          tokens_cache_read=cache_read, tokens_cache_write=cache_write)

    last_ctx = 0  # 직전 호출의 실효 프롬프트 크기(tokens_in + cache_read) — 컴팩션 트리거.
    step = 0
    while True:
        step += 1
        if step > HARD_STEP_CAP:
            return _budget_outcome("step safety cap")
        if token_budget and tokens_in + tokens_out >= token_budget:
            return _budget_outcome("token budget")
        # 컨텍스트 컴팩션(D56③) — 대화가 임계를 넘으면 중간 히스토리를 요약으로 압축.
        if compact_threshold and last_ctx > compact_threshold:
            ci, co = _compact_messages(messages, client)
            tokens_in += ci; tokens_out += co
            last_ctx = 0  # 압축 직후엔 재트리거하지 않는다(다음 호출이 실측 갱신).
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
            return _budget_outcome("time budget")
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
        # Anthropic은 prompt_tokens가 캐시 히트를 제외하므로(#91) 실효 컨텍스트 = in + cache_read.
        last_ctx = resp.tokens_in + resp.tokens_cache_read

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


