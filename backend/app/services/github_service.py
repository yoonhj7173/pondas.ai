"""GitHub 소유권 서비스(item 36, D56①/D61) — 프로젝트 = 유저 소유 리포.

핵심 설계(tech-design §23.1):
- GitHub App 설치(유저) → installation_id 저장. 토큰은 단명 installation token을 매 호출 발급
  (장기 토큰 저장 금지).
- 리포는 **유저 계정 소유**로 생성("코드를 안 읽어도 코드는 처음부터 네 것").
- 커밋은 버전 컷과 **비동기**(Celery) — 외부 API가 태스크 완료를 절대 블록하지 않는다.
  실패 시 pushed_at이 비어 있어 UI가 "sync pending"을 보여주고, 다음 push/백필이 따라잡는다.
- Restore = 과거 manifest를 현재 상태로 복사해 **새 버전 컷**(히스토리 보존, force-push 금지).

GITHUB_APP_* env 미설정 시 전 기능이 조용히 비활성(연결 UI가 "not configured"로 안내).
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import GithubConnection, Output, Project, ProjectFile, Task, WorkspaceVersion
from app.services.filestore import filestore

log = logging.getLogger("app.github")

_API = "https://api.github.com"
_UA = {"User-Agent": "pondas-app", "Accept": "application/vnd.github+json"}


def enabled() -> bool:
    return bool(settings.github_app_id and settings.github_app_private_key)


def install_url() -> str:
    return f"https://github.com/apps/{settings.github_app_slug}/installations/new"


def _normalize_pem(key: str) -> str:
    """env 붙여넣기 사고 흡수 — 리터럴 \\n 복원 + 헤더/푸터 없이 본문만 온 경우 래핑.

    실사고(2026-07-21): Railway에 PEM 본문만 붙여넣어져 JWT 서명 전체가 죽었다.
    """
    key = key.replace("\\n", "\n").strip()
    if key and not key.startswith("-----BEGIN"):
        key = f"-----BEGIN RSA PRIVATE KEY-----\n{key}\n-----END RSA PRIVATE KEY-----\n"
    return key


# ── user access token(OAuth during install) ────────────────────────────────
# 개인 계정 리포 생성(POST /user/repos)은 installation 토큰이 403(실측) —
# "Request user authorization during installation"으로 받은 user 토큰이 필요하다.


def _fernet():
    from cryptography.fernet import Fernet

    if not settings.secrets_key:
        raise RuntimeError("SECRETS_KEY not configured")
    return Fernet(settings.secrets_key.encode())


def exchange_oauth_code(code: str) -> dict:
    """설치 콜백의 ?code=를 user access token으로 교환. 반환: access/refresh/expires_in."""
    r = httpx.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json", **_UA},
        data={"client_id": settings.github_client_id,
              "client_secret": settings.github_client_secret, "code": code},
        timeout=20,
    )
    r.raise_for_status()
    d = r.json()
    if "access_token" not in d:
        raise RuntimeError(f"oauth exchange failed: {d.get('error', 'unknown')}")
    return d


def store_user_token(conn: GithubConnection, token_resp: dict) -> None:
    from datetime import timedelta

    f = _fernet()
    conn.user_token_encrypted = f.encrypt(token_resp["access_token"].encode())
    if token_resp.get("refresh_token"):
        conn.refresh_token_encrypted = f.encrypt(token_resp["refresh_token"].encode())
    expires = int(token_resp.get("expires_in") or 0)
    conn.token_expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=expires - 300) if expires else None
    )


def get_user_token(db, conn: GithubConnection) -> str:
    """복호화된 user 토큰 — 만료면 refresh로 갱신 후 저장. 없으면 RuntimeError(재연결 안내)."""
    if conn.user_token_encrypted is None:
        raise RuntimeError("no user token — reconnect GitHub")
    f = _fernet()
    if conn.token_expires_at is not None and conn.token_expires_at <= datetime.now(timezone.utc):
        if conn.refresh_token_encrypted is None:
            raise RuntimeError("token expired — reconnect GitHub")
        r = httpx.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json", **_UA},
            data={"client_id": settings.github_client_id,
                  "client_secret": settings.github_client_secret,
                  "grant_type": "refresh_token",
                  "refresh_token": f.decrypt(conn.refresh_token_encrypted).decode()},
            timeout=20,
        )
        r.raise_for_status()
        store_user_token(conn, r.json())
        db.commit()
    return f.decrypt(conn.user_token_encrypted).decode()


class GitHubAppClient:
    """실제 GitHub API 클라이언트 — App JWT → installation token → REST/Git Data API.

    테스트는 이 클래스 대신 FakeGitHubClient(tests)를 주입한다(같은 메서드 시그니처).
    """

    def _app_jwt(self) -> str:
        import jwt  # PyJWT — requirements 고정

        now = int(time.time())
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": settings.github_app_id},
            _normalize_pem(settings.github_app_private_key),
            algorithm="RS256",
        )

    def _inst_token(self, installation_id: int) -> str:
        r = httpx.post(
            f"{_API}/app/installations/{installation_id}/access_tokens",
            headers={**_UA, "Authorization": f"Bearer {self._app_jwt()}"},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()["token"]

    def get_installation(self, installation_id: int) -> dict:
        """설치 검증 — 우리 App의 설치가 맞는지 + 계정 로그인 확인(위조 installation_id 방어)."""
        r = httpx.get(
            f"{_API}/app/installations/{installation_id}",
            headers={**_UA, "Authorization": f"Bearer {self._app_jwt()}"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        return {"account_login": data["account"]["login"]}

    def create_repo(self, user_token: str, name: str) -> str:
        """유저 계정에 private 리포 생성(D61) — user access token 필수(installation 토큰은
        개인 계정에서 403 'Resource not accessible by integration', 실측 2026-07-21).
        이름 충돌 시 -2, -3… 반환값 = full_name."""
        headers = {**_UA, "Authorization": f"token {user_token}"}
        base = name
        for i in range(1, 6):
            r = httpx.post(
                f"{_API}/user/repos",
                headers=headers,
                json={"name": name, "private": True, "auto_init": True,
                      "description": "Built with pondas.ai"},
                timeout=30,
            )
            if r.status_code == 422 and "already exists" in r.text:
                name = f"{base}-{i + 1}"
                continue
            r.raise_for_status()
            return r.json()["full_name"]
        raise RuntimeError(f"repo name exhausted for {base}")

    def push_files(self, installation_id: int, repo_full_name: str,
                   files: dict[str, bytes], message: str) -> str:
        """Git Data API로 파일 세트를 1커밋으로 푸시(현 브랜치 위에). 반환 = commit sha."""
        import base64

        token = self._inst_token(installation_id)
        headers = {**_UA, "Authorization": f"token {token}"}

        def _get(url: str) -> dict:
            r = httpx.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            return r.json()

        def _post(url: str, payload: dict) -> dict:
            r = httpx.post(url, headers=headers, json=payload, timeout=60)
            r.raise_for_status()
            return r.json()

        repo = _get(f"{_API}/repos/{repo_full_name}")
        branch = repo.get("default_branch") or "main"
        ref = _get(f"{_API}/repos/{repo_full_name}/git/ref/heads/{branch}")
        parent_sha = ref["object"]["sha"]
        parent_commit = _get(f"{_API}/repos/{repo_full_name}/git/commits/{parent_sha}")

        tree_items = []
        for path, data in files.items():
            blob = _post(f"{_API}/repos/{repo_full_name}/git/blobs",
                         {"content": base64.b64encode(data).decode(), "encoding": "base64"})
            tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        tree = _post(f"{_API}/repos/{repo_full_name}/git/trees",
                     {"base_tree": parent_commit["tree"]["sha"], "tree": tree_items})
        commit = _post(f"{_API}/repos/{repo_full_name}/git/commits",
                       {"message": message, "tree": tree["sha"], "parents": [parent_sha]})
        httpx.patch(
            f"{_API}/repos/{repo_full_name}/git/refs/heads/{branch}",
            headers=headers, json={"sha": commit["sha"]}, timeout=30,
        ).raise_for_status()
        return commit["sha"]


_client: GitHubAppClient | None = None


def get_client() -> GitHubAppClient:
    global _client
    if _client is None:
        _client = GitHubAppClient()
    return _client


# ── 라벨(사람말 버전 히스토리) ──────────────────────────────────────────────


def fallback_label(task: Task | None) -> str:
    """LLM 없이 즉시 쓰는 폴백 라벨 — 지시문 첫 60자(개행 제거)."""
    if task is None or not task.instructions:
        return "Workspace update"
    text = " ".join(task.instructions.split())
    return text[:60] + ("…" if len(text) > 60 else "")


def humanize_label(db: Session, task: Task, changed_paths: list[str]) -> str:
    """사람말 버전 라벨(D61) — light-tier 한 콜, 실패 시 폴백. 절대 예외를 흘리지 않는다."""
    try:
        from app.services.config_store import guard_config
        from app.services.orchestrator import LiteLLMClient

        cfg = guard_config(db)
        model = cfg.tier_models.get("light") if cfg.tier_models else None
        if not model:
            return fallback_label(task)
        client = LiteLLMClient(db, model=model, max_tokens=60)
        resp = client.complete([
            {"role": "system", "content": (
                "Write a 3-8 word past-tense change summary for a version history, like "
                "'Added checkout page' or 'Fixed login redirect'. Reply with the label only."
            )},
            {"role": "user", "content": (
                f"Task: {task.instructions[:500]}\nChanged files: {', '.join(changed_paths[:20])}"
            )},
        ], [])
        label = (resp.content or "").strip().strip('"')
        return label[:80] if label else fallback_label(task)
    except Exception:  # noqa: BLE001 — 라벨은 장식, 본 파이프를 못 깨뜨림.
        return fallback_label(task)


# ── 푸시 파이프(비동기) ─────────────────────────────────────────────────────


def push_version_sync(db: Session, version_id: uuid.UUID, client=None) -> str:
    """버전 1개를 유저 리포에 커밋. 반환: pushed|skipped:<이유>. Celery 래퍼가 부른다.

    멱등: 이미 pushed_at이 있으면 스킵. 리포/연결이 없으면 스킵(연결 시점 백필이 처리).
    """
    v = db.get(WorkspaceVersion, version_id)
    if v is None:
        return "skipped:not_found"
    if v.pushed_at is not None:
        return "skipped:already_pushed"
    project = db.get(Project, v.project_id)
    if project is None or not project.repo_full_name:
        return "skipped:no_repo"
    conn = db.get(GithubConnection, project.user_id)
    if conn is None:
        return "skipped:no_connection"

    client = client or get_client()
    files: dict[str, bytes] = {}
    for path, output_id in (v.manifest or {}).items():
        out = db.get(Output, uuid.UUID(output_id))
        if out is not None:
            files[path] = filestore.get_bytes(out)
    if not files:
        return "skipped:empty"

    task = db.get(Task, v.task_id) if v.task_id else None
    message = v.label or fallback_label(task)
    sha = client.push_files(conn.installation_id, project.repo_full_name, files, f"{message} (v{v.version_no})")
    v.commit_sha = sha
    v.pushed_at = datetime.now(timezone.utc)
    db.commit()
    log.info("pushed v%d of project %s → %s", v.version_no, project.id, sha[:8])
    return "pushed"


def backfill(db: Session, project: Project, client=None) -> int:
    """리포 연결 시점 백필 — 미푸시 버전을 순서대로 전부 커밋. 반환: 푸시 건수."""
    versions = (
        db.query(WorkspaceVersion)
        .filter(WorkspaceVersion.project_id == project.id, WorkspaceVersion.pushed_at.is_(None))
        .order_by(WorkspaceVersion.version_no)
        .all()
    )
    n = 0
    for v in versions:
        if push_version_sync(db, v.id, client=client) == "pushed":
            n += 1
    return n


def enqueue_push(version_no: int | None, project_id: uuid.UUID, db: Session) -> None:
    """done 경로에서 부르는 파이어-앤-포겟 — 리포 연결 프로젝트만 Celery로 푸시를 건다."""
    if version_no is None or not enabled():
        return
    project = db.get(Project, project_id)
    if project is None or not project.repo_full_name:
        return
    v = (
        db.query(WorkspaceVersion)
        .filter(WorkspaceVersion.project_id == project_id,
                WorkspaceVersion.version_no == version_no)
        .one_or_none()
    )
    if v is None:
        return
    try:
        from app.celery_app import github_push
        # countdown: 호출부(worker)의 커밋이 끝난 뒤 실행되게 — 롤백 시 push가 not_found로 스킵.
        github_push.apply_async(args=[str(v.id)], countdown=5)
    except Exception:  # noqa: BLE001 — 큐 실패는 백필이 따라잡는다.
        log.warning("github push enqueue failed for v%d", version_no)


# ── Restore(D61: 새 버전 컷, 히스토리 보존) ─────────────────────────────────


def restore_version(db: Session, project: Project, version_no: int) -> int:
    """과거 버전의 manifest를 현재 파일 상태로 복사하고 새 버전을 컷한다. 반환 = 새 version_no."""
    from sqlalchemy import func

    target = (
        db.query(WorkspaceVersion)
        .filter(WorkspaceVersion.project_id == project.id,
                WorkspaceVersion.version_no == version_no)
        .one_or_none()
    )
    if target is None:
        raise ValueError("version not found")

    # 현재 파일 상태 = target manifest로 교체(없던 path는 삭제 — 진짜 그 시점으로 돌아간다).
    db.query(ProjectFile).filter(ProjectFile.project_id == project.id).delete()
    for path, output_id in (target.manifest or {}).items():
        db.add(ProjectFile(project_id=project.id, path=path, output_id=uuid.UUID(output_id)))
    db.flush()

    next_no = (
        db.query(func.max(WorkspaceVersion.version_no))
        .filter(WorkspaceVersion.project_id == project.id)
        .scalar() or 0
    ) + 1
    db.add(WorkspaceVersion(
        project_id=project.id, version_no=next_no, task_id=target.task_id,
        manifest=dict(target.manifest or {}), label=f"Restore to v{version_no}",
    ))
    db.flush()
    return next_no
