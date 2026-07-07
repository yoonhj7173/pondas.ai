"""Project files + version snapshots (item 28, D50) — LIVE Postgres.

- snapshot_version: outputs → project_files upsert + v1 cut
- two sequential tasks → v1/v2, unchanged file carried into v2 manifest, changed file repointed
- no outputs → no version (text-only summary)
- resilience: a broken snapshot never raises (isolated like memory-append)
- API: GET /versions (newest-first, file_count), GET /files (current + ?version=frozen), cross-user 404
"""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models import (
    Agent,
    Output,
    Project,
    ProjectFile,
    Task,
    Team,
    WorkspaceVersion,
)
from app.services import task_service as ts
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
def env():
    """dev(agent_sdk) 프로젝트 1개 + 에이전트 1명. 정리는 프로젝트 삭제 cascade."""
    db = SessionLocal()
    uid = f"v_{uuid.uuid4().hex[:8]}"
    proj = Project(user_id=uid, name="ver")
    db.add(proj); db.flush()
    team = Team(project_id=proj.id, template_key="development", name="Development")
    db.add(team); db.flush()
    agent = Agent(team_id=team.id, project_id=proj.id, name="SWE",
                  role_instructions="build", model_tier="strong", slot=0)
    db.add(agent); db.commit()
    yield db, uid, proj.id, agent.id
    db.delete(db.get(Project, proj.id)); db.commit()
    db.close()


def _done_task_with_files(db, uid, pid, agent_id, files: dict[str, str]) -> Task:
    """files: {path: content}. done task + Output 행들을 만들고 task를 돌려준다."""
    agent = db.get(Agent, agent_id)
    task = ts.create_task(db, user_id=uid, project_id=pid, agent=agent,
                          instructions="build", origin="chat")
    db.flush()
    for path, content in files.items():
        db.add(Output(project_id=pid, agent_id=agent_id, task_id=task.id,
                      path=path, mime="text/plain", size_bytes=len(content),
                      content=content, content_bytes=None))
    db.commit()
    return task


def test_snapshot_cuts_v1_and_upserts_files(env):
    db, uid, pid, aid = env
    task = _done_task_with_files(db, uid, pid, aid, {"app/page.tsx": "v1", "data.json": "{}"})

    no = snapshot_version(db, task)
    db.commit()
    assert no == 1

    ver = db.query(WorkspaceVersion).filter_by(project_id=pid, version_no=1).one()
    assert set(ver.manifest.keys()) == {"app/page.tsx", "data.json"}

    pfs = {pf.path: pf.output_id for pf in db.query(ProjectFile).filter_by(project_id=pid)}
    assert set(pfs) == {"app/page.tsx", "data.json"}
    # 매니페스트의 output_id가 실제 project_files 포인터와 일치.
    assert ver.manifest["app/page.tsx"] == str(pfs["app/page.tsx"])


def test_two_tasks_carry_unchanged_and_repoint_changed(env):
    db, uid, pid, aid = env
    t1 = _done_task_with_files(db, uid, pid, aid, {"a.py": "a1", "b.py": "b1"})
    assert snapshot_version(db, t1) == 1
    db.commit()
    o1_a = db.query(ProjectFile).filter_by(project_id=pid, path="a.py").one().output_id

    t2 = _done_task_with_files(db, uid, pid, aid, {"b.py": "b2", "c.py": "c2"})
    assert snapshot_version(db, t2) == 2
    db.commit()

    v2 = db.query(WorkspaceVersion).filter_by(project_id=pid, version_no=2).one()
    assert set(v2.manifest.keys()) == {"a.py", "b.py", "c.py"}  # a.py 미변경이지만 매니페스트에 포함
    assert v2.manifest["a.py"] == str(o1_a)                     # a.py는 v1 output을 그대로 가리킴

    pfs = {pf.path: pf.output_id for pf in db.query(ProjectFile).filter_by(project_id=pid)}
    assert pfs["a.py"] == o1_a                                  # 미변경 파일 포인터 유지
    b_output = db.query(Output).filter_by(task_id=t2.id, path="b.py").one()
    assert pfs["b.py"] == b_output.id                           # b.py는 최신 output으로 재지정


def test_no_outputs_no_version(env):
    db, uid, pid, aid = env
    agent = db.get(Agent, aid)
    task = ts.create_task(db, user_id=uid, project_id=pid, agent=agent,
                          instructions="just talk", origin="chat")
    db.commit()
    assert snapshot_version(db, task) is None
    assert db.query(WorkspaceVersion).filter_by(project_id=pid).count() == 0


def test_snapshot_isolated_on_error(env, monkeypatch):
    """스냅샷 내부 오류는 삼켜지고 None 반환 — task 완료를 깨지 않는다(격리)."""
    db, uid, pid, aid = env
    task = _done_task_with_files(db, uid, pid, aid, {"x.py": "x"})

    def _boom(**kwargs):
        raise RuntimeError("boom")

    # WorkspaceVersion 생성 시 터지도록 — snapshot_version은 예외를 삼키고 None + rollback.
    monkeypatch.setattr("app.services.versioning.WorkspaceVersion", _boom)
    assert snapshot_version(db, task) is None
    # task/outputs는 이미 커밋돼 있으니 살아있고, 버전만 안 생김.
    assert db.query(WorkspaceVersion).filter_by(project_id=pid).count() == 0


# --- API ---


def _seed_versions(db, uid, pid, aid):
    t1 = _done_task_with_files(db, uid, pid, aid, {"a.py": "a1", "b.py": "b1"})
    snapshot_version(db, t1); db.commit()
    t2 = _done_task_with_files(db, uid, pid, aid, {"b.py": "b2", "c.py": "c2"})
    snapshot_version(db, t2); db.commit()


def test_api_list_versions_newest_first(env, client, auth):
    db, uid, pid, aid = env
    _seed_versions(db, uid, pid, aid)
    resp = client.get(f"/api/projects/{pid}/versions", headers=auth(uid))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert [r["version_no"] for r in rows] == [2, 1]
    assert rows[0]["file_count"] == 3 and rows[1]["file_count"] == 2
    assert rows[0]["agent_id"] == str(aid)


def test_api_files_current_and_frozen(env, client, auth):
    db, uid, pid, aid = env
    _seed_versions(db, uid, pid, aid)

    cur = client.get(f"/api/projects/{pid}/files", headers=auth(uid)).json()
    assert cur["version_no"] == 2
    assert sorted(f["path"] for f in cur["files"]) == ["a.py", "b.py", "c.py"]

    v1 = client.get(f"/api/projects/{pid}/files?version=1", headers=auth(uid)).json()
    assert v1["version_no"] == 1
    assert sorted(f["path"] for f in v1["files"]) == ["a.py", "b.py"]

    missing = client.get(f"/api/projects/{pid}/files?version=99", headers=auth(uid))
    assert missing.status_code == 404


def test_api_cross_user_404(env, client, auth):
    db, uid, pid, aid = env
    _seed_versions(db, uid, pid, aid)
    assert client.get(f"/api/projects/{pid}/versions", headers=auth("intruder")).status_code == 404
    assert client.get(f"/api/projects/{pid}/files", headers=auth("intruder")).status_code == 404
