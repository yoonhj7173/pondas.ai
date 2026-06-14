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
DEV_TOOLSET = [{"type": "agent_toolset_20260401"}]  # bash/read/write/edit/glob/grep/web


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
    def create_environment(self, name: str, *, unrestricted: bool = True) -> str:
        net = {"type": "unrestricted"} if unrestricted else {"type": "limited"}
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
                or "Shared project memory. Check it before a task; write durable findings as you go.",
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

    # --- 폴링(이벤트 리스트 → 우리 상태 재료) ---
    def poll_until_idle(self, session_id: str, *, timeout_sec: float = 600.0,
                        interval: float = 3.0) -> SessionResult:
        """세션이 terminal(idle non-action / terminated)될 때까지 폴링하고 결과를 모은다.

        토큰은 span.model_request_end.model_usage 합산. 답변은 agent.message 텍스트.
        """
        deadline = time.time() + timeout_sec
        while True:
            evs = self._req("GET", f"/v1/sessions/{session_id}/events").get("data", [])
            reply = _collect_reply(evs)
            tin, tout = _collect_tokens(evs)
            term = _terminal(evs)
            if term is not None:
                status, stop_reason, await_ids = term
                return SessionResult(reply, tin, tout, status, stop_reason, await_ids)
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
