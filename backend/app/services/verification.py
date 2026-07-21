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

from sqlalchemy.orm import Session

from app.models import Output, Task
from app.services.sandbox import IGNORE_DIRS, SandboxProvider

log = logging.getLogger("app.verification")

# QA 역할 프롬프트 보강(D31): 빌드 성공이 아니라 실행해서 확인됐을 때만 APPROVED.
# NOTE: 아직 프롬프트 빌더에 배선 안 됨(미사용) — D31 QA 동작검증 배선 시 사용 예정.
QA_ADDENDUM = (
    "\n\n# Verification rule\n"
    "Start the app and exercise the real behavior before approving. A passing build is not "
    "enough. Emit APPROVED only when you have run it and confirmed it works as expected; "
    "otherwise return specific, reproducible feedback."
)


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


def _is_safe_path(path: str) -> bool:
    """zip-slip/경로탈출 방지 — 절대경로·'..'·백슬래시 금지."""
    if not path or path.startswith("/") or "\\" in path:
        return False
    return ".." not in path.split("/")


def collect_outputs(db: Session, task: Task, provider: SandboxProvider, sandbox_id: str,
                    *, since_mtime: float = 0.0) -> int:
    """결과 파일 거두기 — 개발/디자인 작업이 샌드박스에서 새로 만든·바꾼 파일만 골라 DB에 저장한다.

    무슨 일을 하나: 작업 시작 시각 이후에 바뀐 파일(mtime 비교)만 추려, node_modules 같은 잡파일은
        제외하고, outputs 테이블에 저장한다(코드·문서는 텍스트로, PNG 등은 바이너리로). 이게 결과물
        화면에 뜨고 zip 다운로드된다.
    누가 부르나: 개발/디자인 작업 완료 시 — _run_dev_task (backend/app/services/worker_core.py).
    보안 포인트: '../' 같은 경로 탈출(zip-slip — 압축 풀 때 엉뚱한 위치에 파일 쓰는 공격)은 걸러낸다.
    연결: 저장된 파일을 보여주는 곳 → outputs.py.
    """
    entries = provider.file_tree(sandbox_id, ".")
    n = 0
    for e in entries:
        if e.is_dir:
            continue
        if not _is_safe_path(e.path):  # 악성 에이전트가 쓴 '../' 등 거부(zip-slip 차단).
            log.warning("skipped unsafe output path", extra={"path": e.path})
            continue
        # 숨김 파일/디렉토리 제외(실사고 2026-07-21): baseline 0.0 첫 수집이 홈의 .bashrc류를
        # 쓸어와 유저 리포까지 오염시켰다. 에이전트 산출물은 dotfile일 이유가 없다.
        if any(part.startswith(".") for part in e.path.split("/") if part):
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
