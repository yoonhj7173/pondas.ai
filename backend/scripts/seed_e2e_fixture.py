"""E2E 픽스처 시드(test-plan §2) — Playwright 스위트가 기대하는 결정적 데이터.

e2e_user 소유의 "E2E Candle" 프로젝트: Design 팀+에이전트, done 태스크(결과+파일 2개),
workspace_version v1(사람말 라벨), failed 태스크(Fix it 버튼 검증용). 멱등(있으면 재생성).

usage: APP_ENV=test E2E_AUTH_BYPASS=1 DATABASE_URL=... python scripts/seed_e2e_fixture.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/를 import 루트로

from app.db import SessionLocal
from app.models import Agent, Output, Project, ProjectFile, Task, Team, WorkspaceVersion
from app.services.filestore import filestore

USER = "e2e_user"
NAME = "E2E Candle"


def main() -> None:
    db = SessionLocal()
    old = db.query(Project).filter_by(user_id=USER, name=NAME).one_or_none()
    if old is not None:
        db.delete(old)
        db.commit()

    proj = Project(user_id=USER, name=NAME)
    db.add(proj); db.flush()
    team = Team(project_id=proj.id, template_key="design", name="Design")
    db.add(team); db.flush()
    agent = Agent(team_id=team.id, project_id=proj.id, name="Product Designer",
                  role_instructions="design things", model_tier="medium", slot=0)
    db.add(agent); db.flush()

    done = Task(user_id=USER, project_id=proj.id, agent_id=agent.id, origin="chat",
                engine="agent_sdk", status="done", instructions="Build the candle mockup",
                result_markdown="## Mockup shipped\nAll pages render.")
    db.add(done); db.flush()
    manifest = {}
    for path, data in {"index.html": b"<h1>candles</h1>", "design-system.css": b":root{}"}.items():
        out = Output(task_id=done.id, project_id=proj.id, agent_id=agent.id, path=path,
                     mime="text/plain", size_bytes=len(data))
        filestore.put_text(out, data.decode(), mime="text/html" if path.endswith(".html") else "text/css")
        db.add(out); db.flush()
        manifest[path] = str(out.id)
        # 코드뷰(/files)는 project_files를 읽는다 — canonical 상태도 시드.
        db.add(ProjectFile(project_id=proj.id, path=path, output_id=out.id, updated_by_task_id=done.id))
    db.add(WorkspaceVersion(project_id=proj.id, version_no=1, task_id=done.id,
                            manifest=manifest, label="Added candle mockup pages"))

    failed = Task(user_id=USER, project_id=proj.id, agent_id=agent.id, origin="chat",
                  engine="agent_sdk", status="failed", instructions="Broken run",
                  error_summary="Simulated failure for E2E",
                  verification=[{"cmd": "npm run build", "exit_code": 1}])
    db.add(failed)
    db.flush()
    # created_at이 server_default(now())라 같은 트랜잭션 내 done과 동률 — 패널의 latest 선택이
    # 결정적이도록 failed를 명시적으로 더 뒤 시각으로.
    from datetime import datetime, timedelta, timezone
    failed.created_at = datetime.now(timezone.utc) + timedelta(seconds=2)
    db.commit()
    print(f"seeded {proj.id}")
    db.close()


if __name__ == "__main__":
    main()
