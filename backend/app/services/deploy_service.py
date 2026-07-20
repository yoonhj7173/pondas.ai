"""Deploy 서비스(item 37, D56②/D60) — Grand Opening: Vercel(호스팅/도메인) + Neon(DB) 오케스트레이션.

설계(tech-design §23.2):
- `DeployProvider` 프로토콜 뒤에 격리 — 플랫폼 리스크는 어댑터 교체로 흡수.
- 배포 = 현재 최신 버전의 canonical 파일을 파일 업로드로 배포(리포 비의존 — GitHub 미연결도 동작).
- 유저는 Vercel/Neon 계정·API키를 만나지 않는다(D54 접근성) — 플랫폼 토큰은 서버 env.
- 시크릿: Fernet 암호화 at rest, API는 값을 절대 반환하지 않음, 로그는 redact()로 마스킹.
- DEPLOY_ENABLED=false(기본)면 전 기능 503 — 실클라우드 검증 전 안전 가드.
"""

from __future__ import annotations

import logging
import uuid
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Output, Project, ProjectSecret, WorkspaceVersion
from app.services.filestore import filestore

log = logging.getLogger("app.deploy")


def enabled() -> bool:
    return settings.deploy_enabled and bool(settings.vercel_token)


# ── 시크릿(암호화 at rest + 로그 마스킹) ────────────────────────────────────


def _fernet():
    from cryptography.fernet import Fernet

    if not settings.secrets_key:
        raise RuntimeError("SECRETS_KEY not configured")
    return Fernet(settings.secrets_key.encode())


def set_secret(db: Session, project: Project, key: str, value: str) -> None:
    enc = _fernet().encrypt(value.encode())
    row = (
        db.query(ProjectSecret)
        .filter(ProjectSecret.project_id == project.id, ProjectSecret.key == key)
        .one_or_none()
    )
    if row is None:
        db.add(ProjectSecret(project_id=project.id, key=key, value_encrypted=enc))
    else:
        row.value_encrypted = enc


def get_secrets(db: Session, project: Project) -> dict[str, str]:
    """복호화된 시크릿 맵 — 배포 주입 전용. 라우터/로그로 절대 흘리지 않는다."""
    f = _fernet()
    return {
        row.key: f.decrypt(row.value_encrypted).decode()
        for row in db.query(ProjectSecret).filter(ProjectSecret.project_id == project.id)
    }


def redact(text: str, secrets: dict[str, str]) -> str:
    """로그 마스킹(D60) — 시크릿 값이 로그/에러 메시지에 평문으로 남지 않게."""
    for v in secrets.values():
        if v and len(v) >= 4:
            text = text.replace(v, "•••")
    return text


# ── 프로바이더 ──────────────────────────────────────────────────────────────


class DeployProvider(Protocol):
    def deploy(self, project_ref: str | None, name: str, files: dict[str, bytes],
               env: dict[str, str]) -> dict: ...
    def status(self, deployment_id: str) -> dict: ...
    def add_domain(self, project_ref: str, domain: str) -> dict: ...


class VercelProvider:
    """Vercel 어댑터 — 파일 인라인 배포(리포 비의존). 팀 계정 소유(유저는 Vercel을 모른다)."""

    _API = "https://api.vercel.com"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {settings.vercel_token}"}

    def _q(self) -> dict:
        return {"teamId": settings.vercel_team_id} if settings.vercel_team_id else {}

    def deploy(self, project_ref: str | None, name: str, files: dict[str, bytes],
               env: dict[str, str]) -> dict:
        import base64

        payload = {
            "name": name,
            "files": [
                {"file": path, "data": base64.b64encode(data).decode(), "encoding": "base64"}
                for path, data in files.items()
            ],
            "projectSettings": {"framework": "nextjs"},
        }
        if env:
            payload["env"] = env
        r = httpx.post(f"{self._API}/v13/deployments", headers=self._headers(),
                       params=self._q(), json=payload, timeout=120)
        r.raise_for_status()
        d = r.json()
        return {"deployment_id": d["id"], "url": f"https://{d['url']}",
                "project_ref": d.get("projectId") or name, "status": "building"}

    def status(self, deployment_id: str) -> dict:
        r = httpx.get(f"{self._API}/v13/deployments/{deployment_id}",
                      headers=self._headers(), params=self._q(), timeout=30)
        r.raise_for_status()
        state = r.json().get("readyState", "").lower()
        return {"status": {"ready": "ready", "error": "error", "canceled": "error"}.get(state, "building")}

    def add_domain(self, project_ref: str, domain: str) -> dict:
        r = httpx.post(f"{self._API}/v10/projects/{project_ref}/domains",
                       headers=self._headers(), params=self._q(),
                       json={"name": domain}, timeout=30)
        r.raise_for_status()
        return {"domain": domain, "verification": r.json().get("verification", [])}


class NeonProvider:
    """Neon 어댑터 — 프로젝트당 DB 1개 lazy 프로비저닝(scale-to-zero, D60)."""

    _API = "https://console.neon.tech/api/v2"

    def provision_db(self, name: str) -> dict:
        r = httpx.post(f"{self._API}/projects",
                       headers={"Authorization": f"Bearer {settings.neon_api_key}"},
                       json={"project": {"name": name}}, timeout=60)
        r.raise_for_status()
        d = r.json()
        return {"connection_uri": d["connection_uris"][0]["connection_uri"],
                "neon_project_id": d["project"]["id"]}


_provider: DeployProvider | None = None


def get_provider() -> DeployProvider:
    global _provider
    if _provider is None:
        _provider = VercelProvider()
    return _provider


# ── 배포 파이프 ─────────────────────────────────────────────────────────────


def latest_version_files(db: Session, project: Project) -> tuple[int | None, dict[str, bytes]]:
    v = (
        db.query(WorkspaceVersion)
        .filter(WorkspaceVersion.project_id == project.id)
        .order_by(WorkspaceVersion.version_no.desc())
        .first()
    )
    if v is None:
        return None, {}
    files: dict[str, bytes] = {}
    for path, output_id in (v.manifest or {}).items():
        out = db.get(Output, uuid.UUID(output_id))
        if out is not None:
            files[path] = filestore.get_bytes(out)
    return v.version_no, files


def deploy_project(db: Session, project: Project, provider: DeployProvider | None = None) -> dict:
    """Grand Opening — 최신 버전을 배포하고 프로젝트 상태를 갱신한다. 명시적 유저 액션 전용."""
    provider = provider or get_provider()
    version_no, files = latest_version_files(db, project)
    if not files:
        raise ValueError("nothing to deploy — the project has no files yet")
    try:
        secrets = get_secrets(db, project)
    except RuntimeError:
        secrets = {}  # SECRETS_KEY 미설정 — 시크릿 없이 배포는 가능.

    name = "pondas-" + str(project.id)[:8]
    try:
        result = provider.deploy(project.deploy_provider_id, name, files, secrets)
    except Exception as exc:  # noqa: BLE001 — 시크릿 마스킹 후 표면화
        project.deploy_status = "error"
        raise RuntimeError(redact(str(exc), secrets)) from None
    project.deploy_provider_id = result["project_ref"]
    project.deploy_url = result["url"]
    project.deploy_status = result["status"]
    project.deployed_version_no = version_no
    log.info("deployed project %s v%s → %s", project.id, version_no, result["url"])
    return {"url": result["url"], "status": result["status"], "version_no": version_no,
            "deployment_id": result["deployment_id"]}
