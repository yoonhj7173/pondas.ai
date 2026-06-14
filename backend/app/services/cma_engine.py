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

from sqlalchemy.orm import Session

from app.crews.base import detect_needs_input
from app.models import Agent, Project, Task
from app.services import events
from app.services import task_service as ts
from app.services.cma import CMAClient, CMAError
from app.services.config_store import cost_usd, set_config

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
        "Use your shared project memory mount for cross-agent context, and record durable "
        "findings there as you go. If and only if you need information only the user can give, "
        "end your reply with exactly: AWAITING_INPUT: <your one question>.")
    return "\n\n".join(parts)


def run_dev_task_cma(db: Session, task: Task, agent: Agent, model: str, cfg, enqueue) -> str:
    """agent_sdk 경로의 CMA 구현. 반환: done | needs-input | failed."""
    from app.services.worker_core import _enqueue_children, _finalize_done  # 순환 회피(lazy).

    client = CMAClient()
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

        res = client.poll_until_idle(sid, timeout_sec=cfg.dev_task_timeout_min * 60)
    except CMAError as exc:
        log.warning("cma run failed", extra={"task_id": str(task.id)})
        ts.transition(db, task, "failed", error_summary=f"CMA: {exc}", model_used=model)
        events.emit_terminal_notification(db, task)
        db.commit(); events.emit_status(task)
        return "failed"
    finally:
        client.close()

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

    # done.
    ts.transition(db, task, "done", result_markdown=res.reply, model_used=model,
                  tokens_in=res.tokens_in, tokens_out=res.tokens_out, est_cost_usd=cost)
    new_ids = _finalize_done(db, task, res.tokens_in, res.tokens_out, cost)
    _enqueue_children(new_ids, enqueue)
    return "done"
