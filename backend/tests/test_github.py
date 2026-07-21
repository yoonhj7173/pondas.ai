"""GitHub 소유권 테스트(item 36, D61) — FakeGitHubClient로 파이프 전체를 검증.

실 GitHub API는 어댑터(GitHubAppClient) 뒤에 격리 — 여기선 파이프 로직만:
push가 manifest의 실제 바이트를 커밋하는지, Restore가 새 버전을 컷하는지(히스토리 보존),
히스토리 API가 라벨/푸시 상태를 내는지, 멱등/스킵 경로가 안전한지.
"""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models import (
    Agent, GithubConnection, Output, Project, Team, Task, WorkspaceVersion,
)
from app.services import github_service as gh
from app.services import task_service as ts
from app.services.filestore import filestore


class FakeGitHubClient:
    """GitHubAppClient와 같은 시그니처 — 호출을 기록만 한다."""

    def __init__(self):
        self.repos: list[str] = []
        self.pushes: list[dict] = []

    def get_installation(self, installation_id: int) -> dict:
        if installation_id == 999_999:
            raise RuntimeError("not found")
        return {"account_login": "joshua"}

    def create_repo(self, user_token: str, name: str) -> str:
        full = f"joshua/{name}"
        self.repos.append(full)
        self.last_token = user_token
        return full

    def push_files(self, installation_id, repo_full_name, files, message) -> str:
        self.pushes.append({"repo": repo_full_name, "files": dict(files), "message": message})
        return "cafe" + uuid.uuid4().hex[:8]


@pytest.fixture
def env():
    db = SessionLocal()
    uid = f"gh_{uuid.uuid4().hex[:8]}"
    proj = Project(user_id=uid, name="Habit App")
    db.add(proj); db.flush()
    team = Team(project_id=proj.id, template_key="development", name="Dev")
    db.add(team); db.flush()
    agent = Agent(team_id=team.id, project_id=proj.id, name="SWE",
                  role_instructions="swe", model_tier="strong", slot=0)
    db.add(agent); db.commit()
    yield db, uid, proj, agent
    db.query(GithubConnection).filter_by(user_id=uid).delete()
    db.delete(db.get(Project, proj.id)); db.commit()
    db.close()


def _make_version(db, proj, agent, uid, *, paths: dict[str, bytes], label=None) -> WorkspaceVersion:
    task = ts.create_task(db, user_id=uid, project_id=proj.id, agent=agent,
                          instructions="build the app", origin="chat")
    db.flush()  # task.id 확보 — create_task는 flush하지 않는다.
    manifest = {}
    for path, data in paths.items():
        out = Output(task_id=task.id, project_id=proj.id, agent_id=agent.id, path=path,
                     mime="text/plain", size_bytes=len(data))
        filestore.put_bytes(out, data, mime="text/plain")  # content 채운 뒤 add/flush(체크 제약)
        db.add(out); db.flush()
        manifest[path] = str(out.id)
    no = (db.query(WorkspaceVersion).filter_by(project_id=proj.id).count()) + 1
    v = WorkspaceVersion(project_id=proj.id, version_no=no, task_id=task.id,
                         manifest=manifest, label=label)
    db.add(v); db.commit()
    return v


def test_push_version_commits_manifest_bytes(env):
    db, uid, proj, agent = env
    db.add(GithubConnection(user_id=uid, installation_id=42, account_login="joshua"))
    proj.repo_full_name = "joshua/habit-app"; db.commit()
    v = _make_version(db, proj, agent, uid,
                      paths={"index.html": b"<h1>hi</h1>", "app/page.tsx": b"export default 1"},
                      label="Added landing page")

    fake = FakeGitHubClient()
    assert gh.push_version_sync(db, v.id, client=fake) == "pushed"
    push = fake.pushes[0]
    assert push["repo"] == "joshua/habit-app"
    assert push["files"]["index.html"] == b"<h1>hi</h1>"          # 실제 바이트가 커밋된다
    assert "Added landing page" in push["message"] and "v1" in push["message"]
    db.refresh(v)
    assert v.pushed_at is not None and v.commit_sha
    # 멱등 — 두 번째 호출은 스킵.
    assert gh.push_version_sync(db, v.id, client=fake) == "skipped:already_pushed"
    assert len(fake.pushes) == 1


def test_push_skips_without_repo_or_connection(env):
    db, uid, proj, agent = env
    v = _make_version(db, proj, agent, uid, paths={"a.txt": b"x"})
    assert gh.push_version_sync(db, v.id, client=FakeGitHubClient()) == "skipped:no_repo"
    proj.repo_full_name = "joshua/habit-app"; db.commit()
    assert gh.push_version_sync(db, v.id, client=FakeGitHubClient()) == "skipped:no_connection"


def test_backfill_pushes_all_unpushed_in_order(env):
    db, uid, proj, agent = env
    db.add(GithubConnection(user_id=uid, installation_id=42, account_login="joshua"))
    proj.repo_full_name = "joshua/habit-app"; db.commit()
    _make_version(db, proj, agent, uid, paths={"a.txt": b"1"}, label="v1 work")
    _make_version(db, proj, agent, uid, paths={"b.txt": b"2"}, label="v2 work")

    fake = FakeGitHubClient()
    assert gh.backfill(db, proj, client=fake) == 2
    assert [p["message"] for p in fake.pushes] == ["v1 work (v1)", "v2 work (v2)"]


def test_restore_cuts_new_version_preserving_history(env):
    db, uid, proj, agent = env
    v1 = _make_version(db, proj, agent, uid, paths={"a.txt": b"old"}, label="First")
    _make_version(db, proj, agent, uid, paths={"a.txt": b"new", "b.txt": b"extra"}, label="Second")

    new_no = gh.restore_version(db, proj, 1)
    db.commit()
    assert new_no == 3  # 새 버전 컷 — 히스토리 보존(v1, v2 그대로)
    v3 = db.query(WorkspaceVersion).filter_by(project_id=proj.id, version_no=3).one()
    assert v3.label == "Restore to v1"
    assert v3.manifest == v1.manifest  # 내용은 v1 시점
    # ProjectFile 현재 상태도 v1으로 — b.txt는 사라진다.
    from app.models import ProjectFile
    paths = {pf.path for pf in db.query(ProjectFile).filter_by(project_id=proj.id)}
    assert paths == {"a.txt"}


def test_restore_unknown_version_raises(env):
    db, uid, proj, agent = env
    with pytest.raises(ValueError):
        gh.restore_version(db, proj, 99)


def test_fallback_label_derives_from_instructions(env):
    db, uid, proj, agent = env
    t = ts.create_task(db, user_id=uid, project_id=proj.id, agent=agent,
                       instructions="Build a very long landing page with hero and pricing " * 5,
                       origin="chat")
    label = gh.fallback_label(t)
    assert label.startswith("Build a very long landing page")
    assert len(label) <= 61
    assert gh.fallback_label(None) == "Workspace update"


# ── API 계층 ────────────────────────────────────────────────────────────────


def test_history_endpoint_shows_labels_and_push_state(client, auth, env):
    db, uid, proj, agent = env
    v = _make_version(db, proj, agent, uid, paths={"a.txt": b"x"}, label="Added checkout page")
    resp = client.get(f"/api/projects/{proj.id}/history", headers=auth(uid))
    assert resp.status_code == 200
    body = resp.json()
    assert body["versions"][0]["label"] == "Added checkout page"
    assert body["versions"][0]["pushed"] is False  # sync pending 표시용
    assert body["versions"][0]["files"] == 1


def test_history_cross_user_404(client, auth, env):
    db, uid, proj, agent = env
    resp = client.get(f"/api/projects/{proj.id}/history", headers=auth("someone_else"))
    assert resp.status_code == 404


def test_restore_endpoint_cuts_version(client, auth, env, monkeypatch):
    db, uid, proj, agent = env
    _make_version(db, proj, agent, uid, paths={"a.txt": b"old"})
    _make_version(db, proj, agent, uid, paths={"a.txt": b"new"})
    monkeypatch.setattr("app.services.preview.preview_service.refresh_if_active", lambda *a, **k: None)
    resp = client.post(f"/api/projects/{proj.id}/restore/1", headers=auth(uid))
    assert resp.status_code == 200
    assert resp.json()["version_no"] == 3


def test_status_endpoint_disabled_without_env(client, auth, env):
    db, uid, proj, agent = env
    resp = client.get("/api/github/status", headers=auth(uid))
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False and body["connected"] is False


def test_install_rejected_when_disabled(client, auth, env):
    db, uid, proj, agent = env
    resp = client.post("/api/github/install", json={"installation_id": 42}, headers=auth(uid))
    assert resp.status_code == 503


def test_install_validates_installation(client, auth, env, monkeypatch):
    db, uid, proj, agent = env
    monkeypatch.setattr(gh.settings, "github_app_id", "123")
    monkeypatch.setattr(gh.settings, "github_app_private_key", "key")
    monkeypatch.setattr(gh, "get_client", lambda: FakeGitHubClient())
    # 유효 설치 → 기록
    resp = client.post("/api/github/install", json={"installation_id": 42}, headers=auth(uid))
    assert resp.status_code == 204
    conn = db.query(GithubConnection).filter_by(user_id=uid).one()
    assert conn.account_login == "joshua" and conn.installation_id == 42
    # 위조 설치 → 400
    resp = client.post("/api/github/install", json={"installation_id": 999999}, headers=auth(uid))
    assert resp.status_code == 400


def test_create_repo_and_backfill_endpoint(client, auth, env, monkeypatch):
    db, uid, proj, agent = env
    monkeypatch.setattr(gh.settings, "github_app_id", "123")
    monkeypatch.setattr(gh.settings, "github_app_private_key", "key")
    fake = FakeGitHubClient()
    monkeypatch.setattr(gh, "get_client", lambda: fake)
    # user access token 경로(403 quirk) — 저장된 user 토큰이 있어야 리포 생성 가능.
    from cryptography.fernet import Fernet
    monkeypatch.setattr(gh.settings, "secrets_key", Fernet.generate_key().decode())
    conn = GithubConnection(user_id=uid, installation_id=42, account_login="joshua")
    gh.store_user_token(conn, {"access_token": "ghu_usertoken", "expires_in": 3600})
    db.add(conn); db.commit()
    _make_version(db, proj, agent, uid, paths={"a.txt": b"x"}, label="First")

    resp = client.post(f"/api/projects/{proj.id}/repo", headers=auth(uid))
    assert resp.status_code == 200
    body = resp.json()
    assert body["repo_full_name"] == "joshua/habit-app"  # 슬러그화(공백→하이픈, 소문자)
    assert body["backfilled"] == 1
    assert fake.pushes[0]["repo"] == "joshua/habit-app"



def test_create_repo_without_user_token_asks_reconnect(client, auth, env, monkeypatch):
    """구버전 연결(user 토큰 없음) → 409 reconnect 안내 — installation 토큰 403 quirk 가드."""
    db, uid, proj, agent = env
    monkeypatch.setattr(gh.settings, "github_app_id", "123")
    monkeypatch.setattr(gh.settings, "github_app_private_key", "key")
    from cryptography.fernet import Fernet
    monkeypatch.setattr(gh.settings, "secrets_key", Fernet.generate_key().decode())
    db.add(GithubConnection(user_id=uid, installation_id=42, account_login="joshua")); db.commit()
    resp = client.post(f"/api/projects/{proj.id}/repo", headers=auth(uid))
    assert resp.status_code == 409
    assert "reconnect" in resp.json()["detail"]


def test_normalize_pem_wraps_bare_body():
    """실사고(2026-07-21): 헤더 없이 본문만 붙여넣은 PEM 자동 래핑."""
    from app.services.github_service import _normalize_pem
    assert _normalize_pem("MIIEogIBAAKCAQEA").startswith("-----BEGIN RSA PRIVATE KEY-----")
    full = "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"
    assert _normalize_pem(full) == full


def test_user_token_roundtrip_and_expiry(env, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from cryptography.fernet import Fernet
    db, uid, proj, agent = env
    monkeypatch.setattr(gh.settings, "secrets_key", Fernet.generate_key().decode())
    conn = GithubConnection(user_id=uid, installation_id=42, account_login="joshua")
    gh.store_user_token(conn, {"access_token": "ghu_abc", "refresh_token": "ghr_x", "expires_in": 3600})
    db.add(conn); db.commit()
    assert conn.user_token_encrypted is not None and b"ghu_abc" not in conn.user_token_encrypted
    assert gh.get_user_token(db, conn) == "ghu_abc"
    # 만료 + refresh 성공 경로
    conn.token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    monkeypatch.setattr(gh.httpx, "post", lambda *a, **k: type("R", (), {
        "raise_for_status": lambda self: None,
        "json": lambda self: {"access_token": "ghu_new", "refresh_token": "ghr_y", "expires_in": 3600},
    })())
    assert gh.get_user_token(db, conn) == "ghu_new"


def test_code_only_reauthorize_updates_token(client, auth, env, monkeypatch):
    """기존 연결의 user 토큰 재발급(code-only) — 설치 URL이 code를 다시 안 주는 갭의 해법."""
    from cryptography.fernet import Fernet
    db, uid, proj, agent = env
    monkeypatch.setattr(gh.settings, "github_app_id", "123")
    monkeypatch.setattr(gh.settings, "github_app_private_key", "key")
    monkeypatch.setattr(gh.settings, "secrets_key", Fernet.generate_key().decode())
    db.add(GithubConnection(user_id=uid, installation_id=42, account_login="joshua")); db.commit()
    monkeypatch.setattr(gh, "exchange_oauth_code",
                        lambda code: {"access_token": "ghu_re", "expires_in": 3600})
    resp = client.post("/api/github/install", json={"code": "abc123"}, headers=auth(uid))
    assert resp.status_code == 204
    conn = db.query(GithubConnection).filter_by(user_id=uid).one()
    db.refresh(conn)
    assert conn.user_token_encrypted is not None
    # 연결 자체가 없으면 400
    resp = client.post("/api/github/install", json={"code": "abc123"}, headers=auth("stranger"))
    assert resp.status_code == 400
