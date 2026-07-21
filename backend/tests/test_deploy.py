"""Deploy 골격 테스트(item 37, D60) — FakeProvider + 시크릿 암호화/마스킹 + 플래그 가드."""

from __future__ import annotations

import uuid

import pytest
from cryptography.fernet import Fernet

from app.db import SessionLocal
from app.models import Agent, Output, Project, ProjectSecret, Team, WorkspaceVersion
from app.services import deploy_service as ds
from app.services import task_service as ts
from app.services.filestore import filestore


class FakeProvider:
    def __init__(self):
        self.deploys: list[dict] = []
        self.domains: list[tuple[str, str]] = []

    def deploy(self, project_ref, name, files, env):
        self.deploys.append({"ref": project_ref, "name": name, "files": dict(files), "env": dict(env)})
        return {"deployment_id": "dep_1", "url": f"https://{name}.vercel.app",
                "project_ref": "prj_1", "status": "building"}

    def status(self, deployment_id):
        return {"status": "ready"}

    def add_domain(self, project_ref, domain):
        self.domains.append((project_ref, domain))
        return {"domain": domain, "verification": [{"type": "CNAME", "value": "cname.vercel-dns.com"}]}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(ds.settings, "secrets_key", Fernet.generate_key().decode())
    db = SessionLocal()
    uid = f"dp_{uuid.uuid4().hex[:8]}"
    proj = Project(user_id=uid, name="Candle Store")
    db.add(proj); db.flush()
    team = Team(project_id=proj.id, template_key="development", name="Dev")
    db.add(team); db.flush()
    agent = Agent(team_id=team.id, project_id=proj.id, name="SWE",
                  role_instructions="swe", model_tier="strong", slot=0)
    db.add(agent); db.commit()
    yield db, uid, proj, agent
    db.delete(db.get(Project, proj.id)); db.commit(); db.close()


def _version(db, proj, agent, uid, files: dict[str, bytes]):
    task = ts.create_task(db, user_id=uid, project_id=proj.id, agent=agent,
                          instructions="build", origin="chat")
    db.flush()
    manifest = {}
    for path, data in files.items():
        out = Output(task_id=task.id, project_id=proj.id, agent_id=agent.id, path=path,
                     mime="text/plain", size_bytes=len(data))
        filestore.put_bytes(out, data, mime="text/plain")
        db.add(out); db.flush()
        manifest[path] = str(out.id)
    no = db.query(WorkspaceVersion).filter_by(project_id=proj.id).count() + 1
    db.add(WorkspaceVersion(project_id=proj.id, version_no=no, task_id=task.id, manifest=manifest))
    db.commit()


def test_secrets_encrypted_at_rest_and_roundtrip(env):
    db, uid, proj, agent = env
    ds.set_secret(db, proj, "STRIPE_KEY", "sk_live_supersecret")
    db.commit()
    row = db.query(ProjectSecret).filter_by(project_id=proj.id).one()
    assert b"sk_live_supersecret" not in row.value_encrypted  # 평문 저장 금지
    assert ds.get_secrets(db, proj) == {"STRIPE_KEY": "sk_live_supersecret"}


def test_redact_masks_secret_values():
    masked = ds.redact("error: auth failed with sk_live_supersecret token",
                       {"K": "sk_live_supersecret"})
    assert "sk_live_supersecret" not in masked and "•••" in masked


def test_deploy_pushes_latest_version_files_with_secrets(env):
    db, uid, proj, agent = env
    _version(db, proj, agent, uid, {"index.html": b"v1"})
    _version(db, proj, agent, uid, {"index.html": b"v2", "app.js": b"js"})
    ds.set_secret(db, proj, "DB_URL", "postgres://secret"); db.commit()

    fake = FakeProvider()
    result = ds.deploy_project(db, proj, provider=fake)
    db.commit()
    assert result["status"] == "building" and result["version_no"] == 2
    d = fake.deploys[0]
    assert d["files"]["index.html"] == b"v2"        # 최신 버전이 나간다
    assert d["env"] == {"DB_URL": "postgres://secret"}  # 시크릿 주입
    assert proj.deploy_url and proj.deployed_version_no == 2


def test_deploy_empty_project_raises(env):
    db, uid, proj, agent = env
    with pytest.raises(ValueError):
        ds.deploy_project(db, proj, provider=FakeProvider())


# ── API 계층(플래그/시크릿 노출) ────────────────────────────────────────────


def test_deploy_api_503_when_disabled(client, auth, env):
    db, uid, proj, agent = env
    resp = client.post(f"/api/projects/{proj.id}/deploy", headers=auth(uid))
    assert resp.status_code == 503  # DEPLOY_ENABLED=false 기본


def test_secrets_api_never_returns_values(client, auth, env):
    db, uid, proj, agent = env
    resp = client.put(f"/api/projects/{proj.id}/secrets", headers=auth(uid),
                      json={"key": "STRIPE_KEY", "value": "sk_live_supersecret"})
    assert resp.status_code == 204
    resp = client.get(f"/api/projects/{proj.id}/secrets", headers=auth(uid))
    assert resp.json() == {"keys": ["STRIPE_KEY"]}
    assert "sk_live_supersecret" not in resp.text  # 값은 어떤 응답에도 없다
    # 잘못된 키 형식
    resp = client.put(f"/api/projects/{proj.id}/secrets", headers=auth(uid),
                      json={"key": "bad key!", "value": "x"})
    assert resp.status_code == 422
    # 타 유저 접근 차단
    resp = client.get(f"/api/projects/{proj.id}/secrets", headers=auth("attacker"))
    assert resp.status_code == 404
    # 삭제
    resp = client.request("DELETE", f"/api/projects/{proj.id}/secrets/STRIPE_KEY", headers=auth(uid))
    assert resp.status_code == 204


def test_register_site_byo(client, auth, env):
    """BYO 배포(D63) — URL 등록/검증/해제 + 타 유저 차단."""
    db, uid, proj, agent = env
    resp = client.put(f"/api/projects/{proj.id}/site", headers=auth(uid),
                      json={"url": "https://candle-studio.netlify.app"})
    assert resp.status_code == 204
    db.refresh(proj)
    assert proj.deploy_url == "https://candle-studio.netlify.app" and proj.deploy_status == "live"
    # 스킴/형식 검증
    for bad in ("http://insecure.com", "javascript:alert(1)", "notaurl"):
        assert client.put(f"/api/projects/{proj.id}/site", headers=auth(uid),
                          json={"url": bad}).status_code == 422
    # 타 유저 404
    assert client.put(f"/api/projects/{proj.id}/site", headers=auth("attacker"),
                      json={"url": "https://evil.com"}).status_code == 404
    # 해제
    assert client.request("DELETE", f"/api/projects/{proj.id}/site", headers=auth(uid)).status_code == 204
    db.refresh(proj)
    assert proj.deploy_url is None
