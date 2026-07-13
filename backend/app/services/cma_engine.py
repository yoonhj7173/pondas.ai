"""CMA Dev-engine — agent_sdk 경로의 cma 구현(D45 파일럿).

worker_core가 cfg.dev_engine == "cma"일 때 여기로 라우팅(아니면 기존 E2B 경로). 우리 그래프
오케스트레이션은 그대로; 이 모듈은 "에이전트 1명이 task 1건 실행 + 기억"만 CMA에 위임한다.

리소스 lazy 생성:
- 공유 cloud environment(조직 1개, config.cma_environment_id).
- 프로젝트 공유 memory store(project.cma_memory_store_id) = 회사 기억(cross-agent).
- 에이전트당 CMA agent(agent.cma_agent_id) + 영속 session(agent.cma_session_id) = 개인 기억.

상태 매핑: idle+end_turn→done / 답변에 AWAITING_INPUT(또는 requires_action)→needs-input /
terminated·timeout→failed. 토큰/비용은 세션 이벤트 usage 합산.
"""

from __future__ import annotations

import logging
import mimetypes
import time

from sqlalchemy.orm import Session

from app.crews.base import detect_needs_input
from app.models import Agent, Output, Project, Task
from app.services import events
from app.services import task_service as ts
from app.services.cma import SESSION_OUTPUT_DIR, CMAClient, CMAError
from app.services.config_store import cost_usd, set_config
from app.services.verification import _is_safe_path, _is_text_path

log = logging.getLogger("app.cma_engine")


# --- 리소스 ensure(lazy) ---

def _ensure_environment(db: Session, cfg, client: CMAClient) -> str:
    if cfg.cma_environment_id:
        return cfg.cma_environment_id
    env_id = client.create_environment("craft-shared")
    set_config(db, "cma_environment_id", env_id)
    db.commit()
    return env_id


def _ensure_memory_store(db: Session, project: Project, client: CMAClient) -> str:
    if project.cma_memory_store_id:
        return project.cma_memory_store_id
    store = client.create_memory_store(
        f"craft-proj-{project.id}", "Shared project memory — the company brain.")
    project.cma_memory_store_id = store
    db.commit()
    return store


def _ensure_agent(db: Session, agent: Agent, model: str, client: CMAClient) -> str:
    # NOTE: 모델은 CMA agent 생성시 고정. tier 변경 시 재생성은 추후 정교화(파일럿은 고정).
    if agent.cma_agent_id:
        return agent.cma_agent_id
    aid = client.create_agent(f"craft-{agent.name}-{agent.id}"[:250], model, agent.role_instructions)
    agent.cma_agent_id = aid
    db.commit()
    return aid


def _ensure_session(db: Session, agent: Agent, env_id: str, store_id: str, client: CMAClient) -> str:
    if agent.cma_session_id:
        return agent.cma_session_id
    sid, _ = client.create_session(
        agent.cma_agent_id, env_id, memory_store_id=store_id, title=agent.name)
    agent.cma_session_id = sid
    db.commit()
    return sid


def _build_message(task: Task) -> str:
    """이 task의 턴 메시지. 역할은 CMA agent system, 기억은 store/session이 담당 →
    여기엔 입력(핸드오프)+지시+연속분만."""
    parts: list[str] = []
    if task.input_payload:
        prov = " (delivered from an upstream agent)" if task.edge_id else ""
        parts.append(f"# Input{prov}\n{task.input_payload.strip()}")
    if task.result_markdown:
        parts.append(f"# Your previous partial output\n{task.result_markdown.strip()}")
    for i, c in enumerate(task.continuations or [], start=1):
        text = c.get("text", "") if isinstance(c, dict) else str(c)
        parts.append(f"# User follow-up #{i}\n{text.strip()}")
    parts.append(f"# Task\n{task.instructions.strip()}")
    parts.append(
        "# Workspace\n"
        "Your shared project memory mount is the team's shared codebase/workspace — other "
        "agents read and write the same files there. Read the existing work in it first, then "
        "make your changes there so the rest of the team (e.g. reviewers, downstream agents) "
        "sees them. When you finish, also copy the concrete deliverables you produced into "
        f"{SESSION_OUTPUT_DIR}/ so they are captured as this task's output.\n"
        "If and only if you need information only the user can give, end your reply with "
        "exactly: AWAITING_INPUT: <your one question>.")
    return "\n\n".join(parts)


def _collect_outputs(db: Session, task: Task, client: CMAClient, session_id: str) -> int:
    """세션이 /mnt/session/outputs에 쓴 파일을 Output 행으로 수집(E2B collect_outputs 미러).

    idle 직후 인덱싱 ~1–3s 지연 가능 → 비면 한 번 재시도.
    """
    files: list = []
    for _ in range(3):
        try:
            files = client.list_session_outputs(session_id)
        except CMAError:
            return 0
        if files:
            break
        time.sleep(2)
    n = 0
    for f in files:
        path = (f.get("filename") or "").lstrip("/")
        if not path or not _is_safe_path(path):  # zip-slip 등 거부.
            continue
        try:
            data = client.download_file(f["id"])
        except CMAError:
            continue
        mime = f.get("mime_type") or mimetypes.guess_type(path)[0] or "application/octet-stream"
        if _is_text_path(path, data):
            db.add(Output(project_id=task.project_id, agent_id=task.agent_id, task_id=task.id,
                          path=path, mime=mime, size_bytes=len(data),
                          content=data.decode("utf-8", errors="replace"), content_bytes=None))
        else:
            db.add(Output(project_id=task.project_id, agent_id=task.agent_id, task_id=task.id,
                          path=path, mime=mime, size_bytes=len(data),
                          content=None, content_bytes=data))
        n += 1
    if n:
        db.commit()
    return n


def run_dev_task_cma(db: Session, task: Task, agent: Agent, model: str, cfg, enqueue) -> str:
    """CMA 방식 개발 실행 — 코딩 작업을 우리가 직접 안 돌리고 'Claude 관리형 에이전트'에 맡긴다.

    PM 한 줄: 같은 개발 작업을 두 가지 방식으로 돌릴 수 있다 — 우리가 샌드박스를 직접 모는 E2B 방식
        (dev_runner.py)과, Anthropic의 CMA(Claude Managed Agents — 에이전트·실행환경·'기억'을 클라우드가
        통째로 관리)에 위임하는 이 방식. 설정 dev_engine=="cma"이고 개발팀이면 이쪽으로 온다(D45 파일럿).
        장점: 에이전트별 개인 기억 + 프로젝트 공유 기억('회사 두뇌')을 클라우드가 관리해준다.
    무슨 일을 하나: 필요한 CMA 리소스(공유 환경·프로젝트 기억저장소·에이전트·세션)를 그때그때 만들고,
        작업 메시지를 보내 끝날 때까지 기다린 뒤, 결과를 done/needs-input/failed로 분류하고 출력 파일을 수집한다.
    누가 부르나: process_task의 agent_sdk 분기 — backend/app/services/worker_core.py.
    연결: CMA 서버와 실제 통신 → CMAClient (backend/app/services/cma.py).
        완료 후 공통 마무리·전파 → _finalize_done (worker_core.py). (E2B 대응판 → _run_dev_task)
    """
    from app.services.worker_core import _enqueue_children, _finalize_done  # 순환 회피(lazy).

    client = CMAClient()
    try:  # outer: client는 출력수집까지 열려있어야 함 → 맨 끝 finally에서 close.
        try:
            project = db.get(Project, task.project_id)
            env_id = _ensure_environment(db, cfg, client)
            store_id = _ensure_memory_store(db, project, client)
            _ensure_agent(db, agent, model, client)
            sid = _ensure_session(db, agent, env_id, store_id, client)

            msg = _build_message(task)
            try:
                client.send_user_message(sid, msg)
            except CMAError:
                # 세션이 terminated 등으로 죽었으면 1회 재생성 후 재시도.
                agent.cma_session_id = None
                db.commit()
                sid = _ensure_session(db, agent, env_id, store_id, client)
                client.send_user_message(sid, msg)

            res = client.poll_until_idle(
                sid, timeout_sec=cfg.dev_task_timeout_min * 60,
                # 라이브 진행(QA-01): CMA는 스텝 상세가 없어 모델 턴 수로 "일하고 있음"을 알린다.
                on_progress=lambda label: events.emit_progress(task.project_id, task.agent_id, task.id, label),
            )
        except CMAError as exc:
            log.warning("cma run failed", extra={"task_id": str(task.id)})
            ts.transition(db, task, "failed", error_summary=f"CMA: {exc}", model_used=model)
            events.emit_terminal_notification(db, task)
            db.commit(); events.emit_status(task)
            return "failed"

        cost = cost_usd(cfg, model, res.tokens_in, res.tokens_out)

        # terminated / timeout → failed.
        if res.status in ("terminated", "timeout"):
            ts.transition(db, task, "failed", error_summary=f"CMA session {res.status}",
                          result_markdown=res.reply, model_used=model,
                          tokens_in=res.tokens_in, tokens_out=res.tokens_out, est_cost_usd=cost)
            events.emit_terminal_notification(db, task)
            db.commit(); events.emit_status(task)
            return "failed"

        # idle: AWAITING_INPUT 센티넬 또는 requires_action → needs-input.
        question = detect_needs_input(res.reply)
        if question is not None or res.stop_reason == "requires_action":
            ts.transition(db, task, "needs-input", awaiting_prompt=question or "Awaiting your input",
                          result_markdown=res.reply, model_used=model,
                          tokens_in=res.tokens_in, tokens_out=res.tokens_out, est_cost_usd=cost)
            events.emit_terminal_notification(db, task)
            db.commit(); events.emit_status(task)
            events.emit_usage(task.project_id, task.agent_id, res.tokens_in, res.tokens_out, cost)
            return "needs-input"

        # done — 컨테이너 출력 파일 수집(client 아직 열림) 후 공통 마무리.
        ts.transition(db, task, "done", result_markdown=res.reply, model_used=model,
                      tokens_in=res.tokens_in, tokens_out=res.tokens_out, est_cost_usd=cost)
        _collect_outputs(db, task, client, sid)
        from app.services.versioning import snapshot_version
        snapshot_version(db, task)  # 프로젝트 파일 상태 갱신 + 버전 커팅(D50, 격리).
        new_ids = _finalize_done(db, task, res.tokens_in, res.tokens_out, cost)
        # 프리뷰 켜져 있으면 새 버전 반영(iteration, D51). project는 위(초반)에서 이미 로드됨 —
        # 여기서 `from app.models import Project`를 다시 하면 Project가 함수-로컬이 되어 초반 156줄
        # 참조가 UnboundLocalError로 터진다(전체 CMA dev task 크래시 버그였음). 로컬 import 금지.
        from app.services.preview import preview_service
        preview_service.refresh_if_active(db, project)
        _enqueue_children(new_ids, enqueue)
        return "done"
    finally:
        client.close()
