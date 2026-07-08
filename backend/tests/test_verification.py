"""Verification toolchain + output collection tests (item 17) — LIVE Postgres + Local sandbox.

골든패스(호스트 http.server 버전): index.html 작성 → dev 서버 기동 → health → 렌더 내용
검증 → 출력 수집 + zip. 디자인 PNG 수집, ignore 규칙도 검증한다.
(Next.js+Playwright 골든패스는 동일 메커니즘 + E2B 런타임/키 필요.)
"""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest

from app.db import SessionLocal
from app.models import Agent, Output, Project, Task, Team
from app.services import task_service as ts
from app.services.sandbox import LocalSandboxProvider
from app.services.verification import collect_outputs


@pytest.fixture
def env():
    db = SessionLocal()
    uid = f"v_{uuid.uuid4().hex[:8]}"
    proj = Project(user_id=uid, name="v")
    db.add(proj); db.flush()
    team = Team(project_id=proj.id, template_key="development", name="Dev")
    db.add(team); db.flush()
    agent = Agent(team_id=team.id, project_id=proj.id, name="SWE", role_instructions="swe", model_tier="strong", slot=0)
    db.add(agent); db.commit()
    provider = LocalSandboxProvider()
    sid = provider.create(proj.id, "node22-playwright")
    yield db, uid, proj, agent, provider, sid
    provider.destroy(sid)
    db.delete(db.get(Project, proj.id)); db.commit()
    db.close()


def _task(db, uid, proj, agent):
    t = ts.create_task(db, user_id=uid, project_id=proj.id, agent=agent, instructions="build", origin="chat")
    t.engine = "agent_sdk"; t.status = "working"; db.commit()
    return t


# --- output collection ---


def test_collect_outputs_with_ignore_rules(env):
    db, uid, proj, agent, provider, sid = env
    t = _task(db, uid, proj, agent)
    provider.write_file(sid, "src/app.py", b"print('hi')\n")
    provider.write_file(sid, "README.md", b"# readme\n")
    provider.write_file(sid, "node_modules/lib/x.js", b"junk")  # ignore
    provider.write_file(sid, ".next/cache/y", b"junk")          # ignore
    n = collect_outputs(db, t, provider, sid)
    rows = db.query(Output).filter_by(task_id=t.id).all()
    paths = {r.path for r in rows}
    assert paths == {"src/app.py", "README.md"}
    assert n == 2
    # 텍스트로 저장.
    app_row = next(r for r in rows if r.path == "src/app.py")
    assert app_row.content == "print('hi')\n" and app_row.content_bytes is None


def test_design_png_collected_as_binary(env):
    db, uid, proj, agent, provider, sid = env
    t = _task(db, uid, proj, agent)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32  # PNG 매직 + 바이너리
    provider.write_file(sid, "screenshots/home.png", png)
    collect_outputs(db, t, provider, sid)
    row = db.query(Output).filter_by(task_id=t.id, path="screenshots/home.png").one()
    assert row.content is None and row.content_bytes == png
    assert row.mime == "image/png"


def test_collected_tree_zips(client, auth, env):
    db, uid, proj, agent, provider, sid = env
    t = _task(db, uid, proj, agent)
    provider.write_file(sid, "main.py", b"x = 1\n")
    provider.write_file(sid, "assets/logo.png", b"\x89PNG\r\n\x1a\nbinary")
    collect_outputs(db, t, provider, sid)
    z = client.get(f"/api/tasks/{t.id}/outputs.zip", headers=auth(uid))
    assert z.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    assert set(zf.namelist()) == {"main.py", "assets/logo.png"}
    assert zf.read("main.py") == b"x = 1\n"


def test_mtime_diff_only_changed(env):
    db, uid, proj, agent, provider, sid = env
    t = _task(db, uid, proj, agent)
    provider.write_file(sid, "old.txt", b"old")
    import time as _t
    cutoff = _t.time()
    _t.sleep(0.05)
    provider.write_file(sid, "new.txt", b"new")
    n = collect_outputs(db, t, provider, sid, since_mtime=cutoff)
    paths = {r.path for r in db.query(Output).filter_by(task_id=t.id).all()}
    assert paths == {"new.txt"}  # old.txt는 cutoff 이전이라 제외
