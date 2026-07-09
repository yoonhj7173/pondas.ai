"""Context 파일 텍스트 추출 + 타입 허용리스트(D14).

MVP 허용: txt/md(그대로 디코드), pdf(pdfminer 텍스트 추출). 그 외는 거부.
추출 텍스트는 프롬프트에 풀텍스트로 주입되므로(no RAG) 여기서 한 번만 뽑아 저장한다.

보안(업로드 경로는 온보딩·Settings 공용):
- 확장자 허용리스트 + **매직바이트 검증** — .pdf인데 %PDF 헤더가 없거나, 텍스트인데 널바이트가
  섞인(위장 바이너리) 파일을 거부(확장자만 믿지 않음).
- 파일명 정리 — 디렉터리 성분/제어문자 제거, 길이 제한(경로 탐색·깨진 이름 방지).
- PDF 파싱 페이지 상한 — 조작된 PDF의 파싱 DoS 방지.
"""

from __future__ import annotations

import io

from fastapi import HTTPException

# 확장자/mime 허용리스트.
TEXT_EXTS = {".txt", ".md", ".markdown"}
PDF_EXTS = {".pdf"}

PDF_MAGIC = b"%PDF-"
PDF_MAX_PAGES = 100  # 조작된 PDF의 파싱 폭탄 방지(10MB 상한과 별개로 페이지 수도 제한).


def _ext(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot >= 0 else ""


def is_allowed(filename: str) -> bool:
    ext = _ext(filename)
    return ext in TEXT_EXTS or ext in PDF_EXTS


def safe_filename(filename: str | None) -> str:
    """저장용 파일명 정리 — basename만 남기고 제어문자 제거, 길이 제한.

    "../../etc/passwd" 같은 경로 탐색, 개행/널이 섞인 깨진 이름을 무해화한다. 빈 이름은 'upload'.
    """
    name = (filename or "").replace("\\", "/").split("/")[-1]  # 디렉터리 성분 제거(basename).
    name = "".join(c for c in name if ord(c) >= 0x20 and ord(c) != 0x7F)  # 제어문자 제거.
    name = name.strip() or "upload"
    return name[:255]


def extract(filename: str, data: bytes) -> tuple[str, str]:
    """텍스트 뽑기 — 업로드된 파일에서 글자만 추출한다(에이전트가 읽을 수 있게).

    무슨 일을 하나: 허용된 파일 종류(txt/md는 그대로 디코드, pdf는 글자 추출)에서 텍스트를 뽑아
        (추출텍스트, 파일종류)를 돌려준다. 확장자 허용 + 매직바이트 검증을 통과 못하면 400.
        이 텍스트가 나중에 에이전트 프롬프트에 통째로 들어간다.
    누가 부르나: 자료 업로드 — upload_context (backend/app/routers/context.py).
    """
    ext = _ext(filename)
    if ext in TEXT_EXTS:
        # 텍스트로 위장한 바이너리(예: 이름만 .txt인 실행파일) 거부 — 널바이트 = 비텍스트 신호.
        if b"\x00" in data:
            raise HTTPException(status_code=400, detail="File looks binary, not text (contains null bytes).")
        return data.decode("utf-8", errors="replace"), ("text/plain" if ext == ".txt" else "text/markdown")
    if ext in PDF_EXTS:
        # .pdf 확장자인데 실제 PDF가 아니면 거부(매직바이트).
        if not data[:8].startswith(PDF_MAGIC):
            raise HTTPException(status_code=400, detail="Not a valid PDF (missing %PDF header).")
        from pdfminer.high_level import extract_text

        text = extract_text(io.BytesIO(data), maxpages=PDF_MAX_PAGES) or ""
        return text, "application/pdf"
    raise HTTPException(
        status_code=400,
        detail=f"Unsupported file type '{ext or filename}'. Allowed: txt, md, pdf.",
    )
