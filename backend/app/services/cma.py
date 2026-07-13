"""CMA(Claude Managed Agents) 클라이언트 — Dev팀 실행 엔진 파일럿(D45).

CrewAI/E2B dev 경로를 대체하는 매니지드 실행기. Anthropic이 에이전트 루프 + 컨테이너 +
컨텍스트 자동압축 + 프롬프트 캐싱 + memory store를 관리한다. 우리 오케스트레이션 하네스는 유지.

설계(business-model-decisions #3):
- 에이전트당 영속 session(개인 기억=세션 히스토리, 자동압축).
- 프로젝트당 공유 memory store(회사 기억, 모든 Dev 에이전트가 read/write).
- cloud 컨테이너(E2B 대체). 툴(bash/코드/파일)은 agent_toolset로 컨테이너에서 실행.

SDK 미설치(crewai가 anthropic 핀) → httpx 직통. beta 헤더 자동.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from app.config import settings

BASE = "https://api.anthropic.com"
BETA = "managed-agents-2026-04-01"
FILES_BETA = "managed-agents-2026-04-01,files-api-2025-04-14"  # session-output 조회는 헤더 2개.
DEV_TOOLSET = [{"type": "agent_toolset_20260401"}]  # bash/read/write/edit/glob/grep/web
SESSION_OUTPUT_DIR = "/mnt/session/outputs"  # 여기 쓴 파일이 files.list(scope_id)로 캡처됨.
# CMA 루프 턴 상한(감사 P0) — CMA는 에이전트 루프를 Anthropic에 위임해 폴 타임아웃(30분)만 있고
# 턴 캡이 없어, 모델이 도구호출을 무한 반복하면 30분치 비용을 다 태운다. 모델요청 수로 상한을 건다.
MAX_MODEL_REQUESTS = 60


class CMAError(RuntimeError):
    pass


@dataclass
class SessionResult:
    """poll_until_idle 결과 — 우리 7-state task로 매핑할 재료."""

    reply: str
    tokens_in: int
    tokens_out: int
    status: str                  # idle | terminated | timeout
    stop_reason: str | None      # end_turn | requires_action | retries_exhausted | ...
    awaiting_event_ids: list = field(default_factory=list)


class CMAClient:
    """CMA 서버 통신기 — Anthropic의 'Claude 관리형 에이전트' API와 HTTP로 대화하는 창구.

    PM 한 줄: 이 클래스가 외부 API(api.anthropic.com)를 직접 호출한다(외부 연동 지점). 에이전트·실행환경·
        세션·기억저장소를 거기서 만들고, 작업 메시지를 보내고, 결과 파일을 받아온다. 우리 코드가 직접
        에이전트 루프를 돌리는 대신 Anthropic이 그 루프·컨테이너·기억을 관리해준다.
    누가 쓰나: run_dev_task_cma (backend/app/services/cma_engine.py).
    주요 메서드: create_environment/create_agent/create_memory_store(초기 1회 셋업),
        create_session·send_user_message(매 작업), poll_until_idle(끝날 때까지 대기), list_session_outputs/download_file(결과 수거).
    """

    def __init__(self, api_key: str | None = None, timeout: float = 60.0):
        key = api_key or settings.anthropic_api_key
        if not key:
            raise CMAError("ANTHROPIC_API_KEY missing — CMA needs it")
        self._http = httpx.Client(
            base_url=BASE,
            timeout=timeout,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": BETA,
                "content-type": "application/json",
            },
        )

    # --- 내부 ---
    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        r = self._http.request(method, path, json=body)
        if r.status_code >= 300:
            raise CMAError(f"CMA {method} {path} -> {r.status_code}: {r.text[:400]}")
        return r.json() if r.content else {}

    def close(self) -> None:
        self._http.close()

    # --- 리소스 라이프사이클(setup, 한 번씩) ---
    def create_environment(self, name: str, *, allow_package_managers: bool = True,
                           allowed_hosts: list | None = None) -> str:
        """D31③: limited 네트워크 — npm/pypi 등 패키지 레지스트리만 허용, 임의 인터넷 차단(보안).
        untrusted LLM 코드가 도는 컨테이너라 egress를 허용리스트로 제한한다."""
        net: dict = {"type": "limited", "allow_package_managers": allow_package_managers,
                     "allow_mcp_servers": False}
        if allowed_hosts:
            net["allowed_hosts"] = allowed_hosts
        return self._req("POST", "/v1/environments", {
            "name": name, "config": {"type": "cloud", "networking": net},
        })["id"]

    def create_agent(self, name: str, model: str, system: str, tools: list | None = None) -> str:
        return self._req("POST", "/v1/agents", {
            "name": name, "model": model, "system": system,
            "tools": tools if tools is not None else DEV_TOOLSET,
        })["id"]

    def archive_agent(self, agent_id: str) -> None:
        self._req("POST", f"/v1/agents/{agent_id}/archive")

    def create_memory_store(self, name: str, description: str = "") -> str:
        return self._req("POST", "/v1/memory_stores", {
            "name": name, "description": description,
        })["id"]

    # --- 세션(매 실행) ---
    def create_session(
        self, agent_id: str, environment_id: str,
        *, memory_store_id: str | None = None, memory_instructions: str = "",
        title: str | None = None,
    ) -> tuple[str, str]:
        body: dict = {"agent": agent_id, "environment_id": environment_id}
        if title:
            body["title"] = title
        if memory_store_id:
            body["resources"] = [{
                "type": "memory_store", "memory_store_id": memory_store_id,
                "access": "read_write", "instructions": memory_instructions
                or "This is the team's SHARED project workspace and codebase — every agent "
                "reads and writes the same files here. Read existing work before starting; "
                "write your code and changes here so other agents see them.",
            }]
        s = self._req("POST", "/v1/sessions", body)
        return s["id"], s.get("status", "")

    def send_user_message(self, session_id: str, text: str) -> None:
        self._req("POST", f"/v1/sessions/{session_id}/events", {
            "events": [{"type": "user.message", "content": [{"type": "text", "text": text}]}],
        })

    def delete_session(self, session_id: str) -> None:
        try:
            self._req("DELETE", f"/v1/sessions/{session_id}")
        except CMAError:
            pass  # 정리 실패는 무시.

    # --- 세션 출력 파일(컨테이너 /mnt/session/outputs → files.list) ---
    def list_session_outputs(self, session_id: str) -> list[dict]:
        r = self._http.get("/v1/files", params={"scope_id": session_id},
                           headers={"anthropic-beta": FILES_BETA})
        if r.status_code >= 300:
            raise CMAError(f"CMA list files -> {r.status_code}: {r.text[:300]}")
        return r.json().get("data", [])

    def download_file(self, file_id: str) -> bytes:
        r = self._http.get(f"/v1/files/{file_id}/content",
                           headers={"anthropic-beta": FILES_BETA})
        if r.status_code >= 300:
            raise CMAError(f"CMA download -> {r.status_code}: {r.text[:200]}")
        return r.content

    # --- 폴링(이벤트 리스트 → 우리 상태 재료) ---
    def poll_until_idle(self, session_id: str, *, timeout_sec: float = 600.0,
                        interval: float = 3.0, on_progress=None, should_stop=None) -> SessionResult:
        """끝날 때까지 기다리기(폴링) — 에이전트가 일을 마칠 때까지 주기적으로 상태를 물어본다.

        PM 한 줄: 폴링(polling — 결과가 나왔는지 일정 간격으로 계속 되묻는 방식). CMA는 작업이
            오래 걸리므로, 3초마다 "끝났어?"를 물어 끝나면(idle/terminated) 결과를 모아 돌려준다.
        무슨 일을 하나: 세션 이벤트들을 읽어 답변 텍스트·토큰 수·종료 상태를 모은다. 제한 시간을
            넘기면 timeout으로 반환. 결과(SessionResult)는 호출부가 done/needs-input/failed로 매핑한다.
        누가 부르나: run_dev_task_cma (backend/app/services/cma_engine.py).
        on_progress: (label: str) -> None — 모델 턴이 늘 때마다 라이브 진행 한 줄(QA-01). 실패 무시.
        should_stop: () -> bool — 폴마다 확인(QA-05a). True면 status="stopped"로 즉시 반환
            (호출부가 부분 산출물 수집 + 세션 종료 처리).
        """
        deadline = time.time() + timeout_sec
        seen_turns = 0
        while True:
            evs = self._req("GET", f"/v1/sessions/{session_id}/events").get("data", [])
            reply = _collect_reply(evs)
            tin, tout = _collect_tokens(evs)
            # Stop 확인(QA-05a) — 유저가 Stop을 눌렀으면 지금까지의 부분 결과를 들고 즉시 나간다.
            if should_stop is not None:
                try:
                    if should_stop():
                        return SessionResult(reply, tin, tout, "stopped", None, [])
                except Exception:  # noqa: BLE001 — 확인 실패는 계속 폴링
                    pass
            term = _terminal(evs)
            if term is not None:
                status, stop_reason, await_ids = term
                return SessionResult(reply, tin, tout, status, stop_reason, await_ids)
            turns = sum(1 for e in evs if e.get("type") == "span.model_request_end")
            if on_progress is not None and turns > seen_turns:
                seen_turns = turns
                try:
                    on_progress(f"Working — model turn {turns}")
                except Exception:  # noqa: BLE001 — 진행 표시는 관측용
                    pass
            # 턴 상한 초과 → 폭주로 간주해 종료(호출부가 terminated/timeout처럼 failed 처리, 감사 P0).
            if turns >= MAX_MODEL_REQUESTS:
                return SessionResult(reply, tin, tout, "timeout", "turn_cap", [])
            if time.time() > deadline:
                return SessionResult(reply, tin, tout, "timeout", None, [])
            time.sleep(interval)


# --- 이벤트 파서(엔드포인트 응답 → 재료) ---

def _collect_reply(events: list) -> str:
    parts: list[str] = []
    for e in events:
        if e.get("type") == "agent.message":
            for b in e.get("content", []):
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
    return "\n".join(p for p in parts if p).strip()


def _collect_tokens(events: list) -> tuple[int, int]:
    tin = tout = 0
    for e in events:
        if e.get("type") == "span.model_request_end":
            u = e.get("model_usage") or {}
            tin += int(u.get("input_tokens", 0) or 0) + int(u.get("cache_read_input_tokens", 0) or 0) \
                + int(u.get("cache_creation_input_tokens", 0) or 0)
            tout += int(u.get("output_tokens", 0) or 0)
    return tin, tout


def _terminal(events: list) -> tuple[str, str | None, list] | None:
    """마지막 상태 이벤트가 terminal이면 (status, stop_reason, awaiting_event_ids) 반환, 아니면 None.

    idle + requires_action = 유저 입력 대기(needs-input). idle + 그외 = 완료. terminated = 종료.
    """
    last = None
    for e in events:
        t = e.get("type")
        if t in ("session.status_idle", "session.status_terminated", "session.status_running"):
            last = e
    if last is None:
        return None
    t = last.get("type")
    if t == "session.status_terminated":
        return ("terminated", None, [])
    if t == "session.status_idle":
        sr = last.get("stop_reason") or {}
        kind = sr.get("type")
        if kind == "requires_action":
            return ("idle", "requires_action", sr.get("event_ids", []))
        return ("idle", kind, [])
    return None  # running.
