"""샌드박스 수명 연장 + 커넥션 blip 재시도 테스트 (P0 — sandbox not found 크래시).

수명: E2B 샌드박스는 create 기본 10분 수명인데 dev/design 태스크 예산은 30분 —
extend_lifetime(set_timeout)으로 태스크 예산에 맞춰 늘린다. 실패는 best-effort로 삼킴.
재시도: 유휴 HTTP/2 커넥션이 끊기면(StreamReset/RemoteProtocolError) 핸들 폐기 후 1회 재접속.
"""

from __future__ import annotations

import pytest

from app.services.sandbox import E2BSandboxProvider, LocalSandboxProvider, SandboxTimeout
from app.services.workspace import WorkspaceService


# --- LocalSandboxProvider.set_timeout ---

def test_local_set_timeout_noop_and_validates():
    p = LocalSandboxProvider()
    sid = p.create("proj")
    p.set_timeout(sid, 2100)                       # no-op, 예외 없음
    with pytest.raises(KeyError):
        p.set_timeout("unknown_sbx", 2100)         # 존재 검증은 유지
    p.destroy(sid)


# --- WorkspaceService.extend_lifetime ---

class _RecordingProvider(LocalSandboxProvider):
    def __init__(self):
        super().__init__()
        self.calls: list[tuple[str, int]] = []

    def set_timeout(self, sandbox_id: str, seconds: int) -> None:
        self.calls.append((sandbox_id, seconds))


def test_extend_lifetime_calls_provider():
    p = _RecordingProvider()
    ws = WorkspaceService(p)
    ws.extend_lifetime("sbx1", 2100)
    assert p.calls == [("sbx1", 2100)]


def test_extend_lifetime_swallows_failure():
    class Boom(LocalSandboxProvider):
        def set_timeout(self, sandbox_id: str, seconds: int) -> None:
            raise RuntimeError("api down")

    ws = WorkspaceService(Boom())
    ws.extend_lifetime("sbx1", 2100)               # 예외 안 던짐(best-effort)


# --- E2B exec 커넥션 blip 재시도 ---

class _Run:
    def __init__(self, exit_code=0, stdout="ok", stderr=""):
        self.exit_code, self.stdout, self.stderr = exit_code, stdout, stderr


class _Cmds:
    def __init__(self, fail_with: Exception | None = None):
        self._fail = fail_with
        self.ran: list[str] = []

    def run(self, cmd, **kw):
        self.ran.append(cmd)
        if self._fail is not None:
            raise self._fail
        return _Run()


class _Handle:
    def __init__(self, fail_with: Exception | None = None):
        self.commands = _Cmds(fail_with)


class RemoteProtocolError(Exception):
    """httpx.RemoteProtocolError 모사 — 타입명으로 판별하므로 이름이 계약."""


def _provider_with_dead_then_good_handle():
    p = E2BSandboxProvider(api_key="test-key")
    dead = _Handle(fail_with=RemoteProtocolError("<StreamReset stream_id:77 ...>"))
    good = _Handle()
    p._handles["sbx"] = dead

    class _FakeSDK:
        @staticmethod
        def connect(sandbox_id, api_key=None):
            return good

    p._sdk = lambda: _FakeSDK  # 재접속이 good 핸들을 돌려주게.
    return p, dead, good


def test_e2b_exec_retries_transient_conn_error():
    p, dead, good = _provider_with_dead_then_good_handle()
    res = p.exec("sbx", "echo hi")
    assert res.exit_code == 0 and res.stdout == "ok"
    assert dead.commands.ran == ["echo hi"]        # 1차: 죽은 커넥션에서 실패
    assert good.commands.ran == ["echo hi"]        # 2차: 재접속 후 성공
    assert p._handles["sbx"] is good               # 핸들 교체됨


def test_e2b_exec_no_retry_on_non_transient():
    p = E2BSandboxProvider(api_key="test-key")
    h = _Handle(fail_with=ValueError("boom"))
    p._handles["sbx"] = h
    with pytest.raises(ValueError):
        p.exec("sbx", "echo hi")
    assert h.commands.ran == ["echo hi"]           # 재시도 없음(1회만)


def test_e2b_exec_timeout_not_retried():
    class TimeoutException(Exception):  # e2b TimeoutException 모사(타입명 판별)
        pass

    p = E2BSandboxProvider(api_key="test-key")
    h = _Handle(fail_with=TimeoutException("cmd too slow"))
    p._handles["sbx"] = h
    with pytest.raises(SandboxTimeout):
        p.exec("sbx", "sleep 999")
    assert h.commands.ran == ["sleep 999"]         # SandboxTimeout은 커넥션 문제 아님 → 재시도 없음
