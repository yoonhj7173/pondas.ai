"""Context / Outputs / Memory tests (item 9) — LIVE Postgres.

- context: txt/md 업로드+추출, 실제 PDF 추출, 허용 외 타입 거부, 목록/삭제
- outputs: 멀티파일 트리 라운드트립, 미리보기, 다운로드, zip 언팩 검증
- memory: GET(빈)/PUT/GET/DELETE
"""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest

from app.db import SessionLocal
from app.models import Agent, Output, Project, Task, Team
from seed import seed


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


@pytest.fixture
def made():
    ids: list[uuid.UUID] = []
    yield ids
    db = SessionLocal()
    try:
        for pid in ids:
            obj = db.get(Project, pid)
            if obj is not None:
                db.delete(obj)
        db.commit()
    finally:
        db.close()


def _project(client, auth, sub):
    return client.post(
        "/api/projects", json={"name": "P", "template_keys": ["planning"]}, headers=auth(sub)
    ).json()["id"]


def _make_pdf(text: str) -> bytes:
    """xref 오프셋을 정확히 계산한 최소 유효 PDF(추출 가능 텍스트 1줄)."""
    stream = b"BT /F1 24 Tf 72 720 Td (" + text.encode() + b") Tj ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(pdf))
        pdf += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref_off = len(pdf)
    pdf += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        pdf += ("%010d 00000 n \n" % off).encode()
    pdf += (
        b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_off).encode() + b"\n%%EOF"
    )
    return pdf


# --- Context ---


def test_upload_txt_extracts(client, auth, made):
    sub = "f_txt"
    pid = _project(client, auth, sub)
    made.append(uuid.UUID(pid))
    resp = client.post(
        f"/api/projects/{pid}/context",
        files={"file": ("notes.md", b"# Title\nhello context", "text/markdown")},
        headers=auth(sub),
    )
    assert resp.status_code == 201, resp.text
    listing = client.get(f"/api/projects/{pid}/context", headers=auth(sub)).json()
    assert len(listing) == 1 and listing[0]["filename"] == "notes.md"
    # extracted_text를 DB로 확인.
    db = SessionLocal()
    try:
        from app.models import ContextFile
        row = db.query(ContextFile).filter_by(project_id=uuid.UUID(pid)).one()
        assert "hello context" in row.extracted_text
    finally:
        db.close()


def test_upload_real_pdf_extracts(client, auth, made):
    sub = "f_pdf"
    pid = _project(client, auth, sub)
    made.append(uuid.UUID(pid))
    pdf = _make_pdf("Competitor pricing summary")
    resp = client.post(
        f"/api/projects/{pid}/context",
        files={"file": ("report.pdf", pdf, "application/pdf")},
        headers=auth(sub),
    )
    assert resp.status_code == 201, resp.text
    db = SessionLocal()
    try:
        from app.models import ContextFile
        row = db.query(ContextFile).filter_by(project_id=uuid.UUID(pid)).one()
        assert "Competitor pricing summary" in (row.extracted_text or "")
        assert row.mime == "application/pdf"
        assert row.content_bytes is not None  # 원본 보관
    finally:
        db.close()


def test_upload_bad_type_rejected(client, auth, made):
    sub = "f_bad"
    pid = _project(client, auth, sub)
    made.append(uuid.UUID(pid))
    resp = client.post(
        f"/api/projects/{pid}/context",
        files={"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")},
        headers=auth(sub),
    )
    assert resp.status_code == 400


def test_upload_fake_pdf_rejected(client, auth, made):
    # .pdf 확장자지만 %PDF 헤더 없는 위장 바이너리 → 매직바이트 검증으로 400.
    sub = "f_fakepdf"
    pid = _project(client, auth, sub)
    made.append(uuid.UUID(pid))
    resp = client.post(
        f"/api/projects/{pid}/context",
        files={"file": ("report.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")},
        headers=auth(sub),
    )
    assert resp.status_code == 400


def test_upload_binary_as_txt_rejected(client, auth, made):
    # .txt로 위장한 바이너리(널바이트 포함) → 400.
    sub = "f_bintxt"
    pid = _project(client, auth, sub)
    made.append(uuid.UUID(pid))
    resp = client.post(
        f"/api/projects/{pid}/context",
        files={"file": ("notes.txt", b"hello\x00\x01binary", "text/plain")},
        headers=auth(sub),
    )
    assert resp.status_code == 400


def test_upload_filename_sanitized(client, auth, made):
    # 경로 탐색 시도 → basename만 저장.
    sub = "f_fname"
    pid = _project(client, auth, sub)
    made.append(uuid.UUID(pid))
    resp = client.post(
        f"/api/projects/{pid}/context",
        files={"file": ("../../../etc/passwd.txt", b"safe text", "text/plain")},
        headers=auth(sub),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["filename"] == "passwd.txt"


def test_context_delete(client, auth, made):
    sub = "f_del"
    pid = _project(client, auth, sub)
    made.append(uuid.UUID(pid))
    cid = client.post(
        f"/api/projects/{pid}/context",
        files={"file": ("a.txt", b"x", "text/plain")},
        headers=auth(sub),
    ).json()["id"]
    assert client.delete(f"/api/context/{cid}", headers=auth(sub)).status_code == 204
    assert client.get(f"/api/projects/{pid}/context", headers=auth(sub)).json() == []


# --- Outputs ---


def _task_with_outputs(pid_uuid):
    """프로젝트에 task + 멀티파일 아웃풋(텍스트 2개 + 바이너리 1개)을 심는다."""
    db = SessionLocal()
    try:
        team = db.query(Team).filter_by(project_id=pid_uuid).first()
        agent = db.query(Agent).filter_by(project_id=pid_uuid).first()
        task = Task(
            user_id=db.get(Project, pid_uuid).user_id, project_id=pid_uuid, agent_id=agent.id,
            origin="chat", engine="agent_sdk", status="done", instructions="build",
        )
        db.add(task)
        db.flush()
        files = [
            ("src/app.py", "text/x-python", b"print('hi')", None),
            ("README.md", "text/markdown", b"# readme", None),
            ("shot.png", "image/png", None, b"\x89PNG\r\n\x1a\n\x00binary"),
        ]
        for path, mime, text, binary in files:
            o = Output(
                project_id=pid_uuid, agent_id=agent.id, task_id=task.id, path=path, mime=mime,
                size_bytes=len(text or binary), content=(text.decode() if text else None),
                content_bytes=binary,
            )
            db.add(o)
        db.commit()
        return task.id
    finally:
        db.close()


def test_outputs_tree_roundtrip_and_zip(client, auth, made):
    sub = "o_tree"
    pid = _project(client, auth, sub)
    made.append(uuid.UUID(pid))
    task_id = _task_with_outputs(uuid.UUID(pid))

    groups = client.get(f"/api/projects/{pid}/outputs", headers=auth(sub)).json()
    assert len(groups) == 1
    g = groups[0]
    assert g["file_count"] == 3
    paths = {f["path"] for f in g["files"]}
    assert paths == {"src/app.py", "README.md", "shot.png"}

    # 텍스트 미리보기 → 내용, 바이너리 → null.
    py = next(f for f in g["files"] if f["path"] == "src/app.py")
    prev = client.get(f"/api/outputs/{py['id']}", headers=auth(sub)).json()
    assert prev["is_binary"] is False and "print('hi')" in prev["content"]
    png = next(f for f in g["files"] if f["path"] == "shot.png")
    prev_png = client.get(f"/api/outputs/{png['id']}", headers=auth(sub)).json()
    assert prev_png["is_binary"] is True and prev_png["content"] is None

    # 단일 다운로드.
    dl = client.get(f"/api/outputs/{py['id']}/download", headers=auth(sub))
    assert dl.status_code == 200 and dl.content == b"print('hi')"

    # zip 언팩 검증.
    z = client.get(f"/api/tasks/{task_id}/outputs.zip", headers=auth(sub))
    assert z.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    assert set(zf.namelist()) == {"src/app.py", "README.md", "shot.png"}
    assert zf.read("src/app.py") == b"print('hi')"
    assert zf.read("shot.png") == b"\x89PNG\r\n\x1a\n\x00binary"


def test_outputs_foreign_404(client, auth, made):
    sub = "o_own"
    pid = _project(client, auth, sub)
    made.append(uuid.UUID(pid))
    task_id = _task_with_outputs(uuid.UUID(pid))
    assert client.get(f"/api/tasks/{task_id}/outputs.zip", headers=auth("o_intruder")).status_code == 404


# --- Memory ---


def test_memory_crud(client, auth, made):
    sub = "m_crud"
    pid = _project(client, auth, sub)
    made.append(uuid.UUID(pid))
    tid = client.get(f"/api/projects/{pid}/map", headers=auth(sub)).json()["teams"][0]["id"]
    aid = client.get(f"/api/teams/{tid}", headers=auth(sub)).json()["agents"][0]["id"]

    # 초기 빈.
    assert client.get(f"/api/agents/{aid}/memory", headers=auth(sub)).json()["content_md"] == ""
    # PUT.
    assert client.put(f"/api/agents/{aid}/memory", json={"content_md": "remember X"}, headers=auth(sub)).status_code == 200
    assert client.get(f"/api/agents/{aid}/memory", headers=auth(sub)).json()["content_md"] == "remember X"
    # DELETE → 다시 빈.
    assert client.delete(f"/api/agents/{aid}/memory", headers=auth(sub)).status_code == 204
    assert client.get(f"/api/agents/{aid}/memory", headers=auth(sub)).json()["content_md"] == ""
