"""PreviewService — Live Preview 런타임(Phase 2, item 29, D49).

빌드 엔진(CMA/E2B)이 '코드를 짓는' 것과 별개로, 유저에게 '돌아가는 앱'을 보여주는 계층.
프로젝트의 canonical 파일 상태(project_files, D50)를 **독립된 on-demand E2B 샌드박스**에
머티리얼라이즈 → `npm install` → `npm run dev` → public host URL 노출한다. 빌드 워크스페이스
(project.sandbox_id)와 분리(D49) — 엔진이 뭐든 프리뷰 동작 동일.

수명(D49, 파운더 정책): 시어터 열 때/커밋 완료 시 기동 → idle 10분 pause(과금 정지) →
장기 미사용 destroy. 프로젝트당 1개. preview_enabled 플래그(기본 OFF)로 게이트.

보안: 프리뷰 URL = E2B host(추측 불가) + 미인증(unlisted 링크 수준, D49). 로그/사이트맵에 안 남긴다.
       인증 프록시는 P1. LLM 코드는 여전히 제품 백엔드가 아니라 샌드박스에서만 실행.

핵심 상태(projects): preview_status(none|starting|ready|error|paused) / preview_sandbox_id /
       preview_version_no / preview_last_active_at.

테스트 이음새: E2B 런타임에 의존하는 `_serve`(install+dev server+host)만 라이브 검증 대상이라
       단위 테스트에서 monkeypatch한다. 게이트·머티리얼라이즈·상태전이·runnable 판정·idle 선택은
       LocalSandbox/실 DB로 검증한다. 풀 라이브 검증은 item 34 QA(라이브 E2B).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Output, Project, ProjectFile, WorkspaceVersion
from app.services import events
from app.services.config_store import load_config
from app.services.workspace import WORKSPACE_RUNTIME, workspace_service

log = logging.getLogger("app.preview")

PREVIEW_PORT = 3000
_INSTALL_TIMEOUT = 420    # npm install 상한(초)
_HEALTH_TIMEOUT = 90      # dev server 헬스 폴링 상한(초)
_HEALTH_INTERVAL = 3


class PreviewError(Exception):
    """프리뷰 기동 실패(설치/서버/호스트) — task를 깨지 않고 시어터에 표면화."""


class PreviewService:
    """프리뷰 샌드박스 수명주기. 빌드 워크스페이스와 동일한 provider 싱글턴을 쓰되 별도 sandbox id."""

    @property
    def provider(self):
        # workspace_service.provider를 공유 — 테스트 conftest가 이걸 Local로 스왑하면 프리뷰도 따라감.
        return workspace_service.provider

    # --- 파일 상태 ---

    def _current_files(self, db: Session, project: Project) -> list[tuple[str, bytes]]:
        """프로젝트 현재 canonical 파일(path, bytes) 목록 — Output content를 실제 바이트로."""
        rows = (
            db.query(ProjectFile, Output)
            .join(Output, ProjectFile.output_id == Output.id)
            .filter(ProjectFile.project_id == project.id)
            .all()
        )
        files: list[tuple[str, bytes]] = []
        for pf, out in rows:
            if out.content_bytes is not None:
                data = out.content_bytes
            else:
                data = (out.content or "").encode("utf-8")
            files.append((pf.path, data))
        return files

    def _latest_version(self, db: Session, project: Project) -> int | None:
        from sqlalchemy import func
        return (
            db.query(func.max(WorkspaceVersion.version_no))
            .filter(WorkspaceVersion.project_id == project.id)
            .scalar()
        )

    def runnable_target(self, files: list[tuple[str, bytes]]) -> str | None:
        """실행 가능한 웹 앱인지 판정 — 루트 package.json에 dev 스크립트가 있으면 그 명령을 반환.

        없으면 None(순수 문서/리서치 프로젝트 → 프리뷰 카드 숨김, closure는 result-in-flow가 담당).
        """
        pkg = next((data for path, data in files if path == "package.json"), None)
        if pkg is None:
            return None
        try:
            scripts = json.loads(pkg.decode("utf-8")).get("scripts", {})
        except (ValueError, UnicodeDecodeError):
            return None
        return "npm run dev" if "dev" in scripts else None

    # --- 샌드박스 수명 ---

    def _ensure_sandbox(self, db: Session, project: Project) -> str:
        """프리뷰 샌드박스를 running으로 보장(lazy 생성/resume/재생성). 빌드 샌드박스와 독립."""
        sid = project.preview_sandbox_id
        if sid and project.preview_status in ("ready", "starting") and self._alive(sid):
            return sid
        if sid and project.preview_status == "paused":
            try:
                self.provider.resume(sid)
                if self._alive(sid):
                    return sid
            except Exception:  # noqa: BLE001 — resume 실패 → 재생성.
                log.warning("preview resume failed, recreating", extra={"project_id": str(project.id)})
        # 새로 생성(또는 죽은 것 재생성).
        new_sid = self.provider.create(project.id, WORKSPACE_RUNTIME)
        project.preview_sandbox_id = new_sid
        return new_sid

    def _alive(self, sandbox_id: str) -> bool:
        try:
            self.provider.exec(sandbox_id, "true", timeout=10)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _materialize(self, sandbox_id: str, files: list[tuple[str, bytes]]) -> None:
        """현재 파일을 샌드박스에 기록. 이후 install/dev server가 이 위에서 돈다."""
        for path, data in files:
            self.provider.write_file(sandbox_id, path, data)

    def _serve(self, sandbox_id: str, dev_cmd: str) -> str:
        """install + dev server 기동 + 헬스 폴링 → public host 반환. (라이브 E2B 의존 — item 34 검증.)"""
        inst = self.provider.exec(sandbox_id, "npm install", timeout=_INSTALL_TIMEOUT)
        if inst.exit_code != 0:
            raise PreviewError(f"npm install failed: {inst.stderr[-500:]}")
        # dev server를 백그라운드로 기동(0.0.0.0 바인딩 — E2B host 노출). 로그는 파일로.
        self.provider.exec(
            sandbox_id,
            f"sh -c 'nohup {dev_cmd} -- -H 0.0.0.0 -p {PREVIEW_PORT} "
            f"> /tmp/preview.log 2>&1 & echo started'",
            timeout=30,
        )
        # 헬스 폴링 — dev server가 뜰 때까지.
        deadline = time.time() + _HEALTH_TIMEOUT
        while time.time() < deadline:
            r = self.provider.exec(
                sandbox_id, f"curl -sf -o /dev/null localhost:{PREVIEW_PORT} && echo up || true",
                timeout=15,
            )
            if "up" in r.stdout:
                return self.provider.get_host(sandbox_id, PREVIEW_PORT)
            time.sleep(_HEALTH_INTERVAL)
        tail = self.provider.exec(sandbox_id, "tail -c 500 /tmp/preview.log || true", timeout=10)
        raise PreviewError(f"dev server did not become ready: {tail.stdout[-500:]}")

    # --- 공개 API ---

    def start(self, db: Session, project: Project) -> dict:
        """프리뷰 기동 — 현재 버전을 샌드박스에 올려 dev server로 서빙하고 URL을 돌려준다.

        게이트: preview_enabled OFF면 disabled. runnable 타겟 없으면 none(문서형 프로젝트).
        실패는 preview_status='error'로 표면화(시어터에서 안내) — task/서비스를 깨지 않는다.
        """
        cfg = load_config(db)
        if not cfg.preview_enabled:
            return {"status": "disabled"}

        files = self._current_files(db, project)
        dev_cmd = self.runnable_target(files)
        if dev_cmd is None:
            self._set_status(db, project, "none")
            return {"status": "none"}

        version = self._latest_version(db, project)
        self._set_status(db, project, "starting", version_no=version)
        try:
            sid = self._ensure_sandbox(db, project)
            self._materialize(sid, files)
            host = self._serve(sid, dev_cmd)
        except Exception as exc:  # noqa: BLE001 — 기동 실패는 error 상태로.
            log.warning("preview start failed", extra={"project_id": str(project.id), "err": str(exc)})
            self._set_status(db, project, "error", version_no=version)
            return {"status": "error", "detail": str(exc)[:300]}

        url = f"https://{host}"
        self._set_status(db, project, "ready", version_no=version, touch=True)
        events.emit_preview_status(project.id, "ready", url=url, version_no=version)
        return {"status": "ready", "url": url, "version_no": version}

    def status(self, db: Session, project: Project) -> dict:
        """현재 프리뷰 상태 조회 + ready면 last_active 갱신(idle-pause 카운터 리셋)."""
        if project.preview_status == "ready":
            project.preview_last_active_at = _now()
            db.commit()
        url = self._url(project) if project.preview_status == "ready" else None
        return {
            "status": project.preview_status,
            "url": url,
            "version_no": project.preview_version_no,
        }

    def sync(self, db: Session, project: Project) -> dict:
        """새 버전 반영 — 변경 파일을 running 샌드박스에 다시 써 HMR 갱신(iteration, item 32에서 사용)."""
        if project.preview_status != "ready" or not project.preview_sandbox_id:
            return self.start(db, project)  # 안 떠 있으면 새로 기동.
        files = self._current_files(db, project)
        try:
            self._materialize(project.preview_sandbox_id, files)
        except Exception as exc:  # noqa: BLE001
            log.warning("preview sync failed", extra={"project_id": str(project.id), "err": str(exc)})
            return {"status": "error", "detail": str(exc)[:300]}
        version = self._latest_version(db, project)
        self._set_status(db, project, "ready", version_no=version, touch=True)
        url = self._url(project)
        events.emit_preview_status(project.id, "ready", url=url, version_no=version)
        return {"status": "ready", "url": url, "version_no": version}

    def stop(self, db: Session, project: Project) -> dict:
        """프리뷰 pause(과금 정지). 파일시스템 보존 — 다음 start가 수초 내 resume."""
        if project.preview_sandbox_id and project.preview_status in ("ready", "starting"):
            try:
                self.provider.pause(project.preview_sandbox_id)
            except Exception:  # noqa: BLE001
                log.warning("preview pause failed", extra={"project_id": str(project.id)})
        self._set_status(db, project, "paused")
        events.emit_preview_status(project.id, "paused")
        return {"status": "paused"}

    def destroy(self, db: Session, project: Project) -> None:
        """프리뷰 샌드박스 완전 파기 — 프로젝트 삭제 시(빌드 샌드박스 destroy와 나란히)."""
        if project.preview_sandbox_id:
            try:
                self.provider.destroy(project.preview_sandbox_id)
            except Exception:  # noqa: BLE001
                log.warning("preview destroy failed", extra={"project_id": str(project.id)})
        project.preview_sandbox_id = None
        project.preview_status = "none"

    def pause_idle_previews(self, db: Session) -> int:
        """beat — idle 임계(기본 10분)를 넘긴 ready 프리뷰를 pause해 과금을 멈춘다(D49)."""
        cfg = load_config(db)
        cutoff = _now().timestamp() - cfg.preview_idle_pause_sec
        stale = (
            db.query(Project)
            .filter(
                Project.preview_status == "ready",
                Project.preview_last_active_at.isnot(None),
            )
            .all()
        )
        n = 0
        for project in stale:
            la = project.preview_last_active_at
            if la is not None and la.replace(tzinfo=la.tzinfo or timezone.utc).timestamp() < cutoff:
                self.stop(db, project)
                n += 1
        if n:
            log.info("paused %d idle previews", n)
        return n

    # --- 내부 ---

    def _url(self, project: Project) -> str | None:
        if not project.preview_sandbox_id:
            return None
        try:
            return f"https://{self.provider.get_host(project.preview_sandbox_id, PREVIEW_PORT)}"
        except Exception:  # noqa: BLE001
            return None

    def _set_status(self, db: Session, project: Project, status: str, *,
                    version_no: int | None = None, touch: bool = False) -> None:
        project.preview_status = status
        if version_no is not None:
            project.preview_version_no = version_no
        if touch:
            project.preview_last_active_at = _now()
        db.commit()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# 프로세스 공유 싱글턴(provider의 sandbox 매핑 공유).
preview_service = PreviewService()
