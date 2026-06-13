"""Verification toolchain + output collection (item 17, D31/D42).

- dev 서버 관리: 백그라운드 기동 + health 폴링 + 포트.
- 동작 검증: 실행 중인 앱에서 렌더 내용을 확인(headless Playwright는 E2B 런타임;
  내용 검증 자체는 fetch로). QA-role은 "실행해서 확인된 경우에만 APPROVED"(D31).
- 디자인 렌더: Playwright 스크린샷 → PNG 아웃풋(D42).
- 출력 수집: mtime-diff로 변경 파일만, ignore 규칙(node_modules/.next/venv) 적용 →
  outputs 행(텍스트/바이너리=PNG) + zip(item 9).

E2B 런타임(Node/Playwright)이 필요한 골든패스는 키 대기. 수집/서버/검증 메커니즘은
LocalSandboxProvider + python http.server로 라이브 검증된다.
"""

from __future__ import annotations

import logging
import mimetypes
import time

from sqlalchemy.orm import Session

from app.models import Output, Task
from app.services.sandbox import IGNORE_DIRS, SandboxProvider

log = logging.getLogger("app.verification")

# QA 역할 프롬프트 보강(D31): 빌드 성공이 아니라 실행해서 확인됐을 때만 APPROVED.
QA_ADDENDUM = (
    "\n\n# Verification rule\n"
    "Start the app and exercise the real behavior before approving. A passing build is not "
    "enough. Emit APPROVED only when you have run it and confirmed it works as expected; "
    "otherwise return specific, reproducible feedback."
)


def start_dev_server(provider: SandboxProvider, sandbox_id: str, cmd: str, port: int,
                     *, health_path: str = "/", timeout: int = 30) -> bool:
    """dev 서버를 백그라운드로 띄우고 포트가 응답할 때까지 폴링한다. 성공 True."""
    # 백그라운드 기동(셸이 즉시 반환). 로그는 파일로.
    provider.exec(sandbox_id, f"nohup {cmd} > .devserver.log 2>&1 &", timeout=10)
    deadline = time.time() + timeout
    probe = (
        "python3 -c \"import sys,urllib.request as u; "
        f"sys.exit(0 if u.urlopen('http://127.0.0.1:{port}{health_path}', timeout=2).status<500 else 1)\""
    )
    while time.time() < deadline:
        try:
            res = provider.exec(sandbox_id, probe, timeout=5)
            if res.exit_code == 0:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return False


def assert_rendered(provider: SandboxProvider, sandbox_id: str, url: str, expect: str,
                    verification: list | None = None) -> bool:
    """실행 중인 앱에서 URL을 가져와 expect가 렌더 내용에 있는지 확인(동작 검증)."""
    fetch = (
        "python3 -c \"import urllib.request as u; "
        f"print(u.urlopen('{url}', timeout=5).read().decode('utf-8','replace'))\""
    )
    res = provider.exec(sandbox_id, fetch, timeout=15)
    ok = expect in res.stdout
    if verification is not None:
        verification.append({"cmd": f"GET {url}", "exit_code": 0 if ok else 1,
                             "summary": f"expected '{expect}' {'found' if ok else 'NOT found'}"})
    return ok


def screenshot(provider: SandboxProvider, sandbox_id: str, url: str, out_path: str,
               *, timeout: int = 60) -> bool:
    """Playwright headless 스크린샷 → out_path(PNG). E2B 런타임(node+playwright) 필요(D42)."""
    cmd = f"npx --yes playwright screenshot --wait-for-timeout=1000 {url} {out_path}"
    try:
        res = provider.exec(sandbox_id, cmd, timeout=timeout)
        return res.exit_code == 0
    except Exception:  # noqa: BLE001
        return False


# --- 출력 수집 ---

# 텍스트로 취급할 확장자(나머지는 바이너리=content_bytes).
_TEXT_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".markdown", ".txt", ".html", ".css",
    ".json", ".yaml", ".yml", ".toml", ".sh", ".env", ".sql", ".xml", ".svg", ".cfg", ".ini",
}


def _is_text_path(path: str, data: bytes) -> bool:
    dot = path.rfind(".")
    ext = path[dot:].lower() if dot >= 0 else ""
    if ext in _TEXT_EXTS:
        return True
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".ico"}:
        return False
    # 휴리스틱: utf-8 디코드 가능하면 텍스트.
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def collect_outputs(db: Session, task: Task, provider: SandboxProvider, sandbox_id: str,
                    *, since_mtime: float = 0.0) -> int:
    """변경 파일(mtime >= since_mtime)을 ignore 규칙 적용해 outputs 행으로 수집. 행 수 반환."""
    entries = provider.file_tree(sandbox_id, ".")
    n = 0
    for e in entries:
        if e.is_dir:
            continue
        if any(part in IGNORE_DIRS for part in e.path.split("/")):
            continue
        if e.mtime and e.mtime < since_mtime:
            continue
        if e.path.startswith(".devserver"):  # 서버 로그 등 산출물 아님.
            continue
        data = provider.read_file(sandbox_id, e.path)
        mime = mimetypes.guess_type(e.path)[0] or "application/octet-stream"
        if _is_text_path(e.path, data):
            db.add(Output(
                project_id=task.project_id, agent_id=task.agent_id, task_id=task.id,
                path=e.path, mime=mime, size_bytes=len(data),
                content=data.decode("utf-8", errors="replace"), content_bytes=None,
            ))
        else:
            db.add(Output(
                project_id=task.project_id, agent_id=task.agent_id, task_id=task.id,
                path=e.path, mime=mime, size_bytes=len(data),
                content=None, content_bytes=data,
            ))
        n += 1
    db.commit()
    return n
