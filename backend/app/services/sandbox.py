"""SandboxProvider — 코드 실행 격리 추상화(item 14, D29/D31).

tech-design §10. 인터페이스 하나로 실행 환경을 추상화해 락인을 차단한다. 두 구현:

- **E2BSandboxProvider** (프로덕션): E2B Firecracker microVM. LLM이 짠 코드는 여기서만 실행되고
  제품 백엔드에서는 절대 직접 실행되지 않는다(D29). egress는 패키지 레지스트리 허용리스트만(D31).
  E2B_API_KEY가 필요하다. SDK는 지연 import(키 없는 환경에서도 모듈 로드 가능).

- **LocalSandboxProvider** (개발/테스트 전용 — 격리 없음, 프로덕션 금지): 샌드박스를 호스트의
  임시 디렉터리로 모사해 subprocess로 명령을 실행한다. 어댑터 계약을 키 없이 검증하고 상위
  레이어(WorkspaceService/dev-runner/verification, item 15-18)를 만들기 위한 것. 신뢰된 테스트
  코드만 돌린다. **신뢰할 수 없는 LLM 코드를 절대 이 프로바이더로 실행하지 말 것.**

런타임 이미지: node22-playwright / python312 (D31). Local은 호스트 런타임을 쓰므로 무시한다.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger("app.sandbox")


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str


@dataclass
class FileEntry:
    path: str       # 샌드박스 루트 기준 상대 경로
    is_dir: bool
    size: int
    mtime: float


class SandboxTimeout(Exception):
    """exec가 timeout으로 강제 종료됨."""


class SandboxProvider(Protocol):
    def create(self, project_id, runtime_image: str) -> str: ...
    def pause(self, sandbox_id: str) -> None: ...
    def resume(self, sandbox_id: str) -> None: ...
    def destroy(self, sandbox_id: str) -> None: ...
    def exec(self, sandbox_id: str, cmd: str, *, timeout: int = 120, env: dict | None = None) -> ExecResult: ...
    def read_file(self, sandbox_id: str, path: str) -> bytes: ...
    def write_file(self, sandbox_id: str, path: str, content: bytes) -> None: ...
    def file_tree(self, sandbox_id: str, path: str = ".") -> list[FileEntry]: ...


# 출력 수집 시 무시할 디렉터리(node_modules 등, D31/item 17).
IGNORE_DIRS = {"node_modules", ".next", ".git", "venv", ".venv", "__pycache__", "dist", "build", ".pytest_cache"}


class LocalSandboxProvider:
    """⚠️ 개발/테스트 전용 — 격리 없음. 임시 디렉터리 + subprocess. 프로덕션 금지."""

    def __init__(self):
        self._dirs: dict[str, Path] = {}

    def create(self, project_id, runtime_image: str = "local") -> str:
        sid = f"local_{uuid.uuid4().hex[:12]}"
        d = Path(tempfile.mkdtemp(prefix=f"sbx_{sid}_"))
        self._dirs[sid] = d
        log.info("local sandbox created", extra={"sandbox_id": sid})
        return sid

    def _dir(self, sandbox_id: str) -> Path:
        d = self._dirs.get(sandbox_id)
        if d is None or not d.exists():
            raise KeyError(f"unknown sandbox {sandbox_id}")
        return d

    def pause(self, sandbox_id: str) -> None:
        # 상태가 디스크에 있으므로 no-op(파일시스템이 보존됨).
        self._dir(sandbox_id)

    def resume(self, sandbox_id: str) -> None:
        self._dir(sandbox_id)

    def destroy(self, sandbox_id: str) -> None:
        d = self._dirs.pop(sandbox_id, None)
        if d and d.exists():
            shutil.rmtree(d, ignore_errors=True)

    def exec(self, sandbox_id: str, cmd: str, *, timeout: int = 120, env: dict | None = None) -> ExecResult:
        d = self._dir(sandbox_id)
        run_env = {**os.environ, **(env or {})}
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=str(d), env=run_env,
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxTimeout(f"command timed out after {timeout}s: {cmd}") from exc
        return ExecResult(exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)

    def read_file(self, sandbox_id: str, path: str) -> bytes:
        return (self._dir(sandbox_id) / path).read_bytes()

    def write_file(self, sandbox_id: str, path: str, content: bytes) -> None:
        target = self._dir(sandbox_id) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def file_tree(self, sandbox_id: str, path: str = ".") -> list[FileEntry]:
        root = self._dir(sandbox_id).resolve()  # macOS /var→/private/var 심링크 정합.
        base = (root / path).resolve()
        entries: list[FileEntry] = []
        for p in base.rglob("*"):
            if any(part in IGNORE_DIRS for part in p.relative_to(root).parts):
                continue
            st = p.stat()
            entries.append(FileEntry(
                path=str(p.relative_to(root)), is_dir=p.is_dir(),
                size=st.st_size, mtime=st.st_mtime,
            ))
        return entries


class E2BSandboxProvider:
    """프로덕션 — E2B Firecracker microVM(D29/SDK 2.28). E2B_API_KEY 필요. SDK 지연 import.

    워크스페이스 루트 = /home/user(E2B 기본 홈). 명령은 거기서 실행하고 상대경로 파일은 그
    아래로 매핑한다. file_tree는 find로 재귀 수집(출력 mtime-diff용). 커스텀 런타임 템플릿
    (node22-playwright)은 E2B CLI로 별도 빌드 — 미지정 시 기본 템플릿(Python/Node 포함).
    """

    WORKDIR = "/home/user"
    RUNTIME_TEMPLATES = {
        "node22-playwright": None,  # TODO: e2b template build 후 템플릿 id. 지금은 기본.
        "python312": None,
    }

    def __init__(self, api_key: str | None = None):
        from app.config import settings
        self._api_key = api_key or getattr(settings, "e2b_api_key", "") or os.environ.get("E2B_API_KEY")
        if not self._api_key:
            raise RuntimeError("E2B_API_KEY required for E2BSandboxProvider")
        self._handles: dict[str, object] = {}

    def _sdk(self):
        from e2b import Sandbox
        return Sandbox

    def _abs(self, path: str) -> str:
        return path if path.startswith("/") else f"{self.WORKDIR}/{path}"

    def create(self, project_id, runtime_image: str) -> str:
        from app.config import settings
        template = self.RUNTIME_TEMPLATES.get(runtime_image)
        # egress(D31): 프로덕션은 레지스트리 허용리스트 커스텀 템플릿 권장. SDK 레벨 토글로 제어.
        sbx = self._sdk().create(
            template=template, api_key=self._api_key, timeout=600,
            allow_internet_access=settings.sandbox_allow_internet,
        )
        self._handles[sbx.sandbox_id] = sbx
        return sbx.sandbox_id

    def _h(self, sandbox_id: str):
        h = self._handles.get(sandbox_id)
        if h is None:
            h = self._sdk().connect(sandbox_id, api_key=self._api_key)
            self._handles[sandbox_id] = h
        return h

    def pause(self, sandbox_id: str) -> None:
        self._h(sandbox_id).pause()
        self._handles.pop(sandbox_id, None)  # 재개는 connect로.

    def resume(self, sandbox_id: str) -> None:
        # E2B는 connect가 paused 샌드박스를 재개한다.
        self._handles[sandbox_id] = self._sdk().connect(sandbox_id, api_key=self._api_key)

    def destroy(self, sandbox_id: str) -> None:
        h = self._handles.pop(sandbox_id, None) or self._sdk().connect(sandbox_id, api_key=self._api_key)
        try:
            h.kill()
        except Exception:  # noqa: BLE001
            pass

    def exec(self, sandbox_id: str, cmd: str, *, timeout: int = 120, env: dict | None = None) -> ExecResult:
        h = self._h(sandbox_id)
        try:
            # request_timeout > command timeout: 정상적으로 긴 명령은 HTTP가 안 끊기게.
            r = h.commands.run(cmd, timeout=timeout, request_timeout=timeout + 60, envs=env or {}, cwd=self.WORKDIR)
            return ExecResult(exit_code=r.exit_code, stdout=r.stdout or "", stderr=r.stderr or "")
        except Exception as exc:  # noqa: BLE001
            # 타임아웃: e2b TimeoutException 또는 하위 httpcore ReadTimeout 등.
            if "Timeout" in type(exc).__name__:
                raise SandboxTimeout(f"command timed out after {timeout}s: {cmd}") from exc
            # 비-제로 exit는 CommandExitException(exit_code 보유) — 결과로 환원.
            if hasattr(exc, "exit_code"):
                return ExecResult(exit_code=getattr(exc, "exit_code"), stdout=getattr(exc, "stdout", "") or "", stderr=getattr(exc, "stderr", "") or "")
            raise

    def read_file(self, sandbox_id: str, path: str) -> bytes:
        data = self._h(sandbox_id).files.read(self._abs(path))
        return data.encode("utf-8") if isinstance(data, str) else data

    def write_file(self, sandbox_id: str, path: str, content: bytes) -> None:
        self._h(sandbox_id).files.write(self._abs(path), content)

    def file_tree(self, sandbox_id: str, path: str = ".") -> list[FileEntry]:
        # find로 재귀 수집 — %y(type) %s(size) %T@(mtime) %p(path). ignore 디렉터리는 prune.
        base = self._abs(path) if path != "." else self.WORKDIR
        prune = " ".join(f"-name {d} -prune -o" for d in sorted(IGNORE_DIRS))
        cmd = f"find {base} {prune} -printf '%y\\t%s\\t%T@\\t%p\\n'"
        res = self.exec(sandbox_id, cmd, timeout=30)
        out: list[FileEntry] = []
        for line in res.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 4:
                continue
            typ, size, mtime, p = parts
            rel = p[len(base):].lstrip("/")
            if not rel:
                continue
            out.append(FileEntry(path=rel, is_dir=(typ == "d"), size=int(size or 0), mtime=float(mtime or 0)))
        return out


def get_provider() -> SandboxProvider:
    """E2B(키 있으면). 키 없으면 dev는 Local 폴백, **프로덕션은 하드 실패**(D29).

    프로덕션에서 Local 폴백 = LLM 코드를 제품 호스트에서 직접 실행 = 보안 원칙 위반.
    따라서 프로덕션은 E2B 키가 없으면 시작을 거부한다.
    """
    from app.config import settings
    if getattr(settings, "e2b_api_key", "") or os.environ.get("E2B_API_KEY"):
        return E2BSandboxProvider()
    if settings.is_production:
        raise RuntimeError(
            "E2B_API_KEY required in production — refusing to run LLM-written code on the "
            "product host via LocalSandboxProvider (D29)."
        )
    log.warning("E2B_API_KEY not set — using LocalSandboxProvider (DEV/TEST ONLY, no isolation)")
    return LocalSandboxProvider()
