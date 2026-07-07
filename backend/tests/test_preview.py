"""Live Preview service + API (item 29, D49) — LIVE Postgres, LocalSandbox, mocked _serve.

라이브 E2B 의존부(_serve: npm install + dev server + host)는 monkeypatch로 대체하고, 그 외
전부(게이트·runnable 판정·머티리얼라이즈·상태전이·idle-pause·API 소유권)를 실제로 검증한다.
풀 라이브 검증(앱이 실제 URL로 뜸)은 item 34 QA(라이브 E2B).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db import SessionLocal
from app.models import Agent, Output, Project, ProjectFile, Team, WorkspaceVersion
from app.services import task_service as ts
from app.services.config_store import set_config
from app.services.preview import preview_service
from app.services.versioning import snapshot_version
from seed import seed


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


@pytest.fixture
def preview_on():
    """preview_enabled=true로 켰다가 테스트 후 false로 되돌린다(config는 공유 테이블)."""
    db = SessionLocal()
    try:
        set_config(db, "preview_enabled", "true"); db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        set_config(db, "preview_enabled", "false"); db.commit()
    finally:
        db.close()


@pytest.fixture
def env():
    db = SessionLocal()
    uid = f"pv_{uuid.uuid4().hex[:8]}"
    proj = Project(user_id=uid, name="preview")
    db.add(proj); db.flush()
    team = Team(project_id=proj.id, template_key="development", name="Development")
    db.add(team); db.flush()
    agent = Agent(team_id=team.id, project_id=proj.id, name="SWE",
                  role_instructions="build", model_tier="strong", slot=0)
    db.add(agent); db.commit()
    yield db, uid, proj.id, agent.id
    db.delete(db.get(Project, proj.id)); db.commit()
    db.close()


def _seed_files(db, uid, pid, aid, files: dict[str, str]) -> None:
    """files를 done task의 Output으로 만들고 버전 스냅샷까지 커팅 → project_files 채움."""
    agent = db.get(Agent, aid)
    task = ts.create_task(db, user_id=uid, project_id=pid, agent=agent,
                          instructions="build", origin="chat")
    db.flush()
    for path, content in files.items():
        db.add(Output(project_id=pid, agent_id=aid, task_id=task.id,
                      path=path, mime="text/plain", size_bytes=len(content),
                      content=content, content_bytes=None))
    db.commit()
    snapshot_version(db, task); db.commit()


_PKG_RUNNABLE = '{"name":"app","scripts":{"dev":"next dev","build":"next build"}}'
_PKG_NO_DEV = '{"name":"app","scripts":{"build":"next build"}}'


# --- runnable 판정 ---

def test_runnable_target_detection():
    svc = preview_service
    assert svc.runnable_target([("package.json", _PKG_RUNNABLE.encode())]) == "npm run dev"
    assert svc.runnable_target([("package.json", _PKG_NO_DEV.encode())]) is None
    assert svc.runnable_target([("index.md", b"# doc")]) is None            # package.json 없음
    assert svc.runnable_target([("package.json", b"not json{")]) is None    # 파싱 실패


# --- start 게이트 ---

def test_start_disabled_when_flag_off(env):
    db, uid, pid, aid = env
    _seed_files(db, uid, pid, aid, {"package.json": _PKG_RUNNABLE, "app/page.tsx": "x"})
    # preview_on 픽스처 없음 = 플래그 OFF(기본).
    assert preview_service.start(db, db.get(Project, pid))["status"] == "disabled"


def test_start_none_when_no_runnable(env, preview_on):
    db, uid, pid, aid = env
    _seed_files(db, uid, pid, aid, {"report.md": "# research"})  # 문서형 → runnable 없음
    out = preview_service.start(db, db.get(Project, pid))
    assert out["status"] == "none"
    assert db.get(Project, pid).preview_status == "none"


# --- start happy path (serve mock) ---

def test_start_ready_materializes_and_sets_url(env, preview_on, monkeypatch):
    db, uid, pid, aid = env
    _seed_files(db, uid, pid, aid, {"package.json": _PKG_RUNNABLE, "app/page.tsx": "export default 1"})
    monkeypatch.setattr(preview_service, "_serve", lambda sid, cmd: "3000-fake.e2b.app")

    out = preview_service.start(db, db.get(Project, pid))
    assert out["status"] == "ready"
    assert out["url"] == "https://3000-fake.e2b.app"
    assert out["version_no"] == 1

    project = db.get(Project, pid)
    assert project.preview_status == "ready"
    assert project.preview_sandbox_id is not None
    assert project.preview_last_active_at is not None
    # 파일이 실제 샌드박스에 머티리얼라이즈됐는지(LocalSandbox 디렉터리에서 확인).
    data = preview_service.provider.read_file(project.preview_sandbox_id, "package.json")
    assert b'"dev"' in data


def test_start_error_when_serve_fails(env, preview_on, monkeypatch):
    db, uid, pid, aid = env
    _seed_files(db, uid, pid, aid, {"package.json": _PKG_RUNNABLE})

    def _boom(sid, cmd):
        from app.services.preview import PreviewError
        raise PreviewError("dev server did not become ready")

    monkeypatch.setattr(preview_service, "_serve", _boom)
    out = preview_service.start(db, db.get(Project, pid))
    assert out["status"] == "error"
    assert db.get(Project, pid).preview_status == "error"


# --- stop / status / idle ---

def test_stop_pauses(env, preview_on, monkeypatch):
    db, uid, pid, aid = env
    _seed_files(db, uid, pid, aid, {"package.json": _PKG_RUNNABLE})
    monkeypatch.setattr(preview_service, "_serve", lambda sid, cmd: "3000-fake.e2b.app")
    preview_service.start(db, db.get(Project, pid))
    out = preview_service.stop(db, db.get(Project, pid))
    assert out["status"] == "paused"
    assert db.get(Project, pid).preview_status == "paused"


def test_refresh_if_active_syncs_only_when_ready(env, preview_on, monkeypatch):
    """iteration 훅(item 32) — 프리뷰 ready일 때만 sync 호출, 아니면 no-op."""
    db, uid, pid, aid = env
    _seed_files(db, uid, pid, aid, {"package.json": _PKG_RUNNABLE})
    calls: list[str] = []
    monkeypatch.setattr(preview_service, "sync", lambda db, p: calls.append(str(p.id)) or {"status": "ready"})

    # 안 켜진 상태(none) → no-op.
    preview_service.refresh_if_active(db, db.get(Project, pid))
    assert calls == []

    # ready로 만든 뒤 → sync 호출.
    project = db.get(Project, pid)
    project.preview_status = "ready"; db.commit()
    preview_service.refresh_if_active(db, db.get(Project, pid))
    assert calls == [str(pid)]


def test_pause_idle_previews(env, preview_on, monkeypatch):
    db, uid, pid, aid = env
    _seed_files(db, uid, pid, aid, {"package.json": _PKG_RUNNABLE})
    monkeypatch.setattr(preview_service, "_serve", lambda sid, cmd: "3000-fake.e2b.app")
    preview_service.start(db, db.get(Project, pid))

    project = db.get(Project, pid)
    # 방금 켠 프리뷰는 idle 아님 → pause 안 됨.
    assert preview_service.pause_idle_previews(db) == 0
    assert db.get(Project, pid).preview_status == "ready"

    # last_active를 11분 전으로 → idle 초과 → pause.
    project.preview_last_active_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    db.commit()
    assert preview_service.pause_idle_previews(db) >= 1
    assert db.get(Project, pid).preview_status == "paused"


# --- adversarial (item 34 신규 표면) ---

def test_materialize_skips_unsafe_paths(env):
    """경로 탈출('../', 절대경로)은 프리뷰 샌드박스 밖으로 못 쓴다(방어적 심층)."""
    db, uid, pid, aid = env
    provider = preview_service.provider
    sid = provider.create(pid, "local")
    try:
        preview_service._materialize(sid, [
            ("../evil.txt", b"escape"),
            ("/etc/passwd", b"absolute"),
            ("app/page.tsx", b"ok"),
        ])
        tree = {e.path for e in provider.file_tree(sid, ".")}
        assert "app/page.tsx" in tree
        assert not any(".." in p or p.startswith("/") for p in tree)
    finally:
        provider.destroy(sid)


def test_malicious_package_json_only_detected_not_executed_on_backend():
    """악성 dev 스크립트여도 runnable_target은 'npm run dev'만 반환(감지) — 실제 실행은 샌드박스 안에서만.

    runnable_target은 스크립트 '값'을 절대 백엔드에서 실행하지 않는다(D29 격리). 여기선 판정만.
    """
    evil = '{"name":"x","scripts":{"dev":"rm -rf /tmp/pwn && next dev"}}'
    assert preview_service.runnable_target([("package.json", evil.encode())]) == "npm run dev"


# --- API ---

def test_api_start_stop_get_and_ownership(env, preview_on, client, auth, monkeypatch):
    db, uid, pid, aid = env
    _seed_files(db, uid, pid, aid, {"package.json": _PKG_RUNNABLE, "app/page.tsx": "x"})
    monkeypatch.setattr(preview_service, "_serve", lambda sid, cmd: "3000-fake.e2b.app")

    start = client.post(f"/api/projects/{pid}/preview/start", headers=auth(uid))
    assert start.status_code == 200 and start.json()["status"] == "ready"
    assert start.json()["url"] == "https://3000-fake.e2b.app"

    got = client.get(f"/api/projects/{pid}/preview", headers=auth(uid)).json()
    assert got["status"] == "ready"

    stop = client.post(f"/api/projects/{pid}/preview/stop", headers=auth(uid)).json()
    assert stop["status"] == "paused"

    # cross-user 404.
    assert client.get(f"/api/projects/{pid}/preview", headers=auth("intruder")).status_code == 404
    assert client.post(f"/api/projects/{pid}/preview/start", headers=auth("intruder")).status_code == 404
