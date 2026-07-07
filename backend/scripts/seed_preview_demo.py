"""로컬 프리뷰 테스트용 데모 앱 시드 (Phase 2, item 34 QA 보조).

실제 dev task를 돌리지 않고도 프리뷰가 띄울 대상(최소 Next.js 앱)을 프로젝트에 심는다.
project_files + workspace_version(v1)까지 만들어 preview_service.start가 바로 서빙할 수 있게 한다.

사용:
  export DATABASE_URL=...        # 로컬/스테이징 DB
  python scripts/seed_preview_demo.py <project_id>

주의: 프로덕션 DB에는 쓰지 말 것(테스트 데이터). preview_enabled 플래그는 별도로 켜야 한다.
"""

from __future__ import annotations

import os
import sys
import uuid

# standalone 실행 시에도 `app` 패키지를 찾도록 backend/ 를 path에 추가.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal
from app.models import Agent, Output, Task
from app.services import task_service as ts
from app.services.versioning import snapshot_version

# 최소 실행 가능한 Next.js 14 앱 — npm install + next dev로 바로 뜬다.
FILES: dict[str, str] = {
    "package.json": """{
  "name": "pondas-preview-demo",
  "version": "0.1.0",
  "private": true,
  "scripts": { "dev": "next dev", "build": "next build", "start": "next start" },
  "dependencies": { "next": "14.2.5", "react": "18.3.1", "react-dom": "18.3.1" }
}
""",
    "next.config.js": "module.exports = {};\n",
    "app/layout.tsx": """export const metadata = { title: "pondas preview demo" };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (<html lang="en"><body style={{ margin: 0, fontFamily: "system-ui, sans-serif" }}>{children}</body></html>);
}
""",
    "app/page.tsx": """export default function Page() {
  return (
    <main style={{ minHeight: "100vh", display: "grid", placeItems: "center",
      background: "linear-gradient(160deg,#fffdf9,#eef1ea)" }}>
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 48 }}>☕</div>
        <h1 style={{ fontSize: 28, color: "#2c2925" }}>Hello from your pondas preview</h1>
        <p style={{ color: "#6d6a60" }}>This app is running live in a sandbox. Ask the team to change it.</p>
      </div>
    </main>
  );
}
""",
}


def main(project_id: str) -> None:
    db = SessionLocal()
    try:
        pid = uuid.UUID(project_id)
        from app.models import Project
        project = db.get(Project, pid)
        if project is None:
            raise SystemExit(f"no project {project_id}")
        agent = db.query(Agent).filter(Agent.project_id == pid).first()
        if agent is None:
            raise SystemExit(f"no agent found in project {project_id} — create a team first")

        task = ts.create_task(db, user_id=project.user_id, project_id=pid, agent=agent,
                              instructions="[demo] scaffold preview app", origin="chat")
        task.status = "done"
        task.result_markdown = "Scaffolded a minimal Next.js app for preview testing."
        db.flush()
        for path, content in FILES.items():
            db.add(Output(project_id=pid, agent_id=agent.id, task_id=task.id,
                          path=path, mime="text/plain", size_bytes=len(content.encode()),
                          content=content, content_bytes=None))
        db.commit()
        ver = snapshot_version(db, task)
        db.commit()
        print(f"✓ seeded demo app into project {project_id} as version v{ver} "
              f"({len(FILES)} files). Now flip preview_enabled ON and open the theater.")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/seed_preview_demo.py <project_id>")
    main(sys.argv[1])
