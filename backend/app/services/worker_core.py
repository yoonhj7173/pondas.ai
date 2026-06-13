"""Worker core — task 1건 처리 파이프라인(engine-agnostic, item 10).

process_task(db, task_id):
  1. queued 확인 → try_dispatch(5게이트) → 막히면 queued 유지(나중 재시도).
  2. engine 라우팅:
     - crew  : 프롬프트 조립 → CrewAI 1회 실행(주입/실 LLM) → 결과 분류
               DONE→done(+output file+tokens/cost+memory) / NEEDS_INPUT→needs-input / FAILED→failed
     - agent_sdk: 아직 미구현(item 18) → failed로 스텁(BLOCKED until item 18)
  3. 토큰/비용: model_used × pricing(usage 없으면 길이 휴리스틱 폴백).
  4. usage 이벤트: Redis project:{id} 채널로 publish(SSE는 item 12에서 소비).

mocked Claude: llm 인자로 ScriptedLLM을 주입하면 라이브 키 없이 전체 경로를 검증한다.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.crews.base import _coerce_output, detect_needs_input
from app.crews.factory import build_agent_crew
from app.models import Agent, AgentMemory, Output, Task
from app.services import events
from app.services import task_service as ts
from app.services.config_store import cost_usd, load_config, model_for_tier
from app.services.prompt import assemble_prompt

log = logging.getLogger("app.worker")


def _tokens(crew, prompt: str, output: str) -> tuple[int, int]:
    """crew.usage_metrics에서 토큰을, 없으면 길이 휴리스틱(≈4 chars/token)으로."""
    um = getattr(crew, "usage_metrics", None)
    pin = int(getattr(um, "prompt_tokens", 0) or 0)
    pout = int(getattr(um, "completion_tokens", 0) or 0)
    if pin == 0:
        pin = max(1, len(prompt) // 4)
    if pout == 0:
        pout = max(1, len(output) // 4)
    return pin, pout


def _append_memory(db: Session, agent_id, output: str) -> None:
    """light-tier 메모리 append(D14) — 격리 실패(메모리 오류가 task를 깨지 않음).

    MVP는 결과 요지를 템플릿으로 append(light-model 요약은 추후 정교화 지점).
    """
    try:
        first = (output.strip().splitlines() or [""])[0][:200]
        mem = db.get(AgentMemory, agent_id)
        line = f"- {datetime.now(timezone.utc).date()}: {first}"
        if mem is None:
            db.add(AgentMemory(agent_id=agent_id, content_md=line))
        else:
            mem.content_md = (mem.content_md + "\n" + line).strip()
        db.flush()
    except Exception:  # noqa: BLE001 — 격리.
        log.warning("memory append failed", extra={"agent_id": str(agent_id)})
        db.rollback()


def _finalize_done(db: Session, task: Task, tokens_in: int, tokens_out: int, cost: float) -> list:
    """done 공통 마무리(엔진 무관): 메모리 + 알림 + 전파 + 커밋 + 이벤트. 새 child id 반환.

    호출부가 이미 status=done 전이 + 아웃풋 행 추가를 마친 상태로 호출한다.
    """
    from app.services import graph_engine

    _append_memory(db, task.agent_id, task.result_markdown or "")
    events.emit_terminal_notification(db, task)
    new_ids = [n for n in graph_engine.propagate(db, task) if n is not None]
    db.commit()
    events.emit_status(task)
    events.emit_usage(task.project_id, task.agent_id, tokens_in, tokens_out, cost)
    return new_ids


def _finish_done(db: Session, task: Task, output: str, model: str, tokens_in: int, tokens_out: int, cfg) -> list:
    """텍스트팀 done — 결과를 단일 마크다운 아웃풋으로 저장 후 공통 마무리."""
    cost = cost_usd(cfg, model, tokens_in, tokens_out)
    ts.transition(
        db, task, "done",
        result_markdown=output, model_used=model,
        tokens_in=tokens_in, tokens_out=tokens_out, est_cost_usd=cost,
    )
    db.add(Output(
        project_id=task.project_id, agent_id=task.agent_id, task_id=task.id,
        path="output.md", mime="text/markdown", size_bytes=len(output.encode("utf-8")),
        content=output, content_bytes=None,
    ))
    return _finalize_done(db, task, tokens_in, tokens_out, cost)


def _enqueue_children(new_ids: list, enqueue) -> None:
    if not new_ids:
        return
    if enqueue is None:
        from app.celery_app import enqueue_task as enqueue
    for nid in new_ids:
        enqueue(nid)


def process_task(db: Session, task_id: uuid.UUID, *, llm=None, dev_client=None, enqueue=None) -> str:
    """task 1건을 처리하고 최종 상태 문자열을 반환한다(테스트/관측용).

    반환: "not_found" | "skipped:<status>" | "not_dispatched" | "done" | "needs-input" | "failed".
    llm: crew 경로 주입 LLM(테스트 ScriptedLLM). dev_client: agent_sdk 경로 주입 에이전트.
    """
    task = db.get(Task, task_id)
    if task is None:
        return "not_found"
    if task.status != "queued":
        return f"skipped:{task.status}"

    # 게이트 통과 + queued→working(원자적). paused면 dev/text 모두 디스패치 차단(D16).
    if not ts.try_dispatch(db, task):
        db.rollback()
        return "not_dispatched"
    db.commit()
    events.emit_status(task)  # working

    cfg = load_config(db)
    agent = db.get(Agent, task.agent_id)
    model = model_for_tier(cfg, agent.model_tier)

    # 엔진 라우팅.
    if task.engine == "agent_sdk":
        return _run_dev_task(db, task, agent, model, cfg, dev_client, enqueue)

    # crew 경로.
    prompt = assemble_prompt(db, task, context_token_budget=cfg.context_token_budget)
    if llm is None:
        from crewai.llm import LLM
        llm = LLM(model=model)

    try:
        crew = build_agent_crew(llm, agent.role_instructions, prompt)
        raw = crew.kickoff(inputs={"prompt": prompt})
        output = _coerce_output(raw)
    except Exception as exc:  # noqa: BLE001 — 워커 경계.
        ts.transition(db, task, "failed", error_summary=f"{type(exc).__name__}: {exc}")
        events.emit_terminal_notification(db, task)
        db.commit()
        events.emit_status(task)
        return "failed"

    tokens_in, tokens_out = _tokens(crew, prompt, output)
    question = detect_needs_input(output)
    if question is not None:
        cost = cost_usd(cfg, model, tokens_in, tokens_out)
        ts.transition(
            db, task, "needs-input",
            awaiting_prompt=question, result_markdown=output, model_used=model,
            tokens_in=tokens_in, tokens_out=tokens_out, est_cost_usd=cost,
        )
        events.emit_terminal_notification(db, task)
        db.commit()
        events.emit_status(task)
        events.emit_usage(task.project_id, task.agent_id, tokens_in, tokens_out, cost)
        return "needs-input"

    new_ids = _finish_done(db, task, output, model, tokens_in, tokens_out, cfg)
    _enqueue_children(new_ids, enqueue)
    return "done"


def _run_dev_task(db: Session, task: Task, agent: Agent, model: str, cfg, dev_client, enqueue) -> str:
    """agent_sdk 경로(Dev/Design) — 워크스페이스에서 dev-runner 실행 + 출력 수집(item 18)."""
    import time

    from app.models import Project
    from app.services import dev_runner
    from app.services.verification import collect_outputs
    from app.services.workspace import WorkspaceError, workspace_service

    project = db.get(Project, task.project_id)
    try:
        sandbox_id = workspace_service.ensure_running(db, project)
    except WorkspaceError as exc:
        ts.transition(db, task, "failed", error_summary=str(exc))
        events.emit_terminal_notification(db, task)
        db.commit(); events.emit_status(task)
        return "failed"

    prompt = assemble_prompt(db, task, context_token_budget=cfg.context_token_budget)
    if dev_client is None:
        from app.services.orchestrator import LiteLLMClient
        dev_client = LiteLLMClient(db, model=model)

    start_mtime = time.time()
    outcome = dev_runner.run_dev_task(
        prompt, workspace_service.provider, sandbox_id,
        client=dev_client, role_instructions=agent.role_instructions,
        task_timeout_sec=cfg.dev_task_timeout_min * 60,
    )
    cost = cost_usd(cfg, model, outcome.tokens_in, outcome.tokens_out)

    if outcome.status == "needs-input":
        ts.transition(db, task, "needs-input", awaiting_prompt=outcome.awaiting_prompt,
                      result_markdown=outcome.output, model_used=model, verification=outcome.verification,
                      tokens_in=outcome.tokens_in, tokens_out=outcome.tokens_out, est_cost_usd=cost)
        events.emit_terminal_notification(db, task)
        db.commit(); events.emit_status(task)
        events.emit_usage(task.project_id, task.agent_id, outcome.tokens_in, outcome.tokens_out, cost)
        workspace_service.pause_if_idle(db, project)
        return "needs-input"

    if outcome.status == "failed":
        ts.transition(db, task, "failed", error_summary=outcome.error_summary or "dev task failed",
                      verification=outcome.verification, model_used=model,
                      tokens_in=outcome.tokens_in, tokens_out=outcome.tokens_out, est_cost_usd=cost)
        events.emit_terminal_notification(db, task)
        db.commit(); events.emit_status(task)
        workspace_service.pause_if_idle(db, project)
        return "failed"

    # done — 변경 파일을 아웃풋으로 수집(코드 트리 + 디자인 PNG).
    ts.transition(db, task, "done", result_markdown=outcome.output, model_used=model,
                  verification=outcome.verification, tokens_in=outcome.tokens_in,
                  tokens_out=outcome.tokens_out, est_cost_usd=cost)
    collect_outputs(db, task, workspace_service.provider, sandbox_id, since_mtime=start_mtime)
    new_ids = _finalize_done(db, task, outcome.tokens_in, outcome.tokens_out, cost)
    workspace_service.pause_if_idle(db, project)
    _enqueue_children(new_ids, enqueue)
    return "done"


def reap_stale_tasks(db: Session, older_than_sec: int = 600) -> int:
    """heartbeat(updated_at)이 오래된 working task를 failed로(워커 크래시 복구, §15).

    반환: reap된 task 수. 전파는 절반만 발화되지 않음(failed는 핸드오프 안 함).
    """
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_sec)
    stale = (
        db.query(Task)
        .filter(Task.status == "working", Task.updated_at < cutoff)
        .all()
    )
    n = 0
    for task in stale:
        task.status = "failed"
        task.error_summary = "Worker timed out (reaped)"
        n += 1
    if n:
        db.commit()
    return n
