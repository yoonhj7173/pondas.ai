"""Worker core — task 1건 처리 파이프라인(engine-agnostic, item 10).

process_task(db, task_id):
  1. queued 확인 → try_dispatch(5게이트) → 막히면 queued 유지(나중 재시도).
  2. engine 라우팅:
     - crew  : 프롬프트 조립 → CrewAI 1회 실행(주입/실 LLM) → 결과 분류
               DONE→done(+output file+tokens/cost+memory) / NEEDS_INPUT→needs-input / FAILED→failed
     - agent_sdk: 개발/디자인팀(코딩) 경로. 샌드박스에서 코드 실행 + 출력 수집.
               development+CMA 설정이면 run_dev_task_cma(cma_engine), 그 외(design 등)는 _run_dev_task(E2B).
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
from app.crews.factory import TextLLM
from app.models import Agent, AgentMemory, Output, Task
from app.services import events
from app.services import task_service as ts
from app.services.config_store import cost_usd, load_config, model_for_tier
from app.services.prompt import assemble_prompt
from app.services.slack_alerts import send_slack_alert

log = logging.getLogger("app.worker")


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
    """완료 마무리 공통부 — 작업이 끝났을 때 매번 똑같이 해야 하는 뒷정리를 한 곳에 모았다.

    무슨 일을 하나: 작업을 done으로 만든 뒤 공통으로 1) 에이전트 기억에 결과 요지 추가
        2) "완료됐어요" 알림 발행 3) 연결된 다음 에이전트로 일 전파 4) DB 커밋(확정)
        5) 화면 실시간 갱신용 이벤트(상태/사용량) 발행. 새로 생긴 자식 작업 id들을 돌려준다.
    누가 부르나: _finish_done(글쓰기팀), _run_dev_task / cma_engine(개발·디자인팀) — 엔진 무관 공통.
    연결: 전파 규칙 → propagate (backend/app/services/graph_engine.py). 실시간 이벤트 → events.py.
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


def _save_plan(db: Session, task: Task, steps: list) -> None:
    """update_plan 반영(QA-06) — tasks.plan 영속(+커밋) 후 SSE 브로드캐스트. 실패는 러너가 삼킴."""
    task.plan = steps
    db.commit()  # 러너 도중에도 패널 재오픈이 최신 plan을 보도록 즉시 커밋(스텝 경계라 안전).
    events.emit_plan(task.project_id, task.agent_id, task.id, steps)


def _task_stopped(db: Session, task_id) -> bool:
    """유저가 Stop을 눌렀는지 DB에서 확인(QA-05a) — 러너가 스텝 경계마다 부른다.

    컬럼 하나만 SELECT(식별맵 미사용) → 세션 캐시가 아니라 최신 커밋값을 본다(READ COMMITTED).
    Stop 라우트는 별도 세션에서 failed+stopped를 커밋하므로 이 조회가 그걸 즉시 감지한다.
    """
    return bool(db.query(Task.stopped).filter(Task.id == task_id).scalar())


def _refund_if_billing(db: Session, task: Task, agent: Agent, cfg) -> None:
    """시스템 실패(우리 잘못 — 크래시/샌드박스 기동 실패/타임아웃)일 때만 차감분 환불(D46 B-4).

    billing OFF면 no-op. 품질 실패(outcome=='failed')는 여기 안 옴 = 환불 X(어뷰징 방지).
    """
    if not cfg.billing_enabled:
        return
    from app.services import credit_service
    credit_service.refund_task(
        db, task.user_id, task.id, credit_service.credit_cost(agent.model_tier)
    )


def process_task(db: Session, task_id: uuid.UUID, *, llm=None, dev_client=None, enqueue=None) -> str:
    """작업 처리 엔진 — 작업 1건을 실제로 실행하는 일꾼. 에이전트가 '일하는' 바로 그 함수.

    이것이 백그라운드 일꾼(워커)의 심장이다. 채팅으로 만들어진 작업이든 자동 전파된 작업이든,
    결국 전부 여기로 들어와 LLM을 돌리고 결과를 저장하고 다음 단계로 넘긴다.

    무슨 일을 하나: 대기 작업 하나를 받아 → 게이트 통과 확인 → 알맞은 엔진으로 실행 →
        결과(완료/입력대기/실패)를 분류해 저장 → 완료면 다음 에이전트로 일을 전파한다.
    누가 부르나: 백그라운드 큐(Celery)가 작업을 꺼낼 때 — backend/app/celery_app.py.
        (dispatch_task/_spawn이 enqueue로 큐에 올린 것을 워커가 집어 이 함수를 부른다)
    처리 순서:
        1. 작업이 아직 queued인지 확인(아니면 건너뜀).
        2. try_dispatch: 5게이트 통과 + queued→working 전이(원자적). 막히면 그대로 둠.
        3. 엔진 분기:
           - agent_sdk(개발/디자인팀): 샌드박스(격리된 가상 컴퓨터)에서 코드를 짜고 검증 → _run_dev_task
             (개발팀 + CMA 설정이면 Claude 관리형 에이전트 경로 run_dev_task_cma로).
           - crew(기획/리서치 등 글쓰기팀): 프롬프트 조립 → CrewAI로 LLM 1회 실행 → 결과 분류.
        4. 결과 분류: done(완료) / needs-input(질문하며 멈춤) / failed(실패).
        5. 완료면 _finish_done → 결과 저장 + 다음 에이전트로 전파(propagate) + 자식 작업 큐잉.
    연결: 게이트/전이 → task_service.py. 프롬프트 조립 → prompt.py. 다음 전파 → graph_engine.py.
        반환값(테스트/관측용): not_found | skipped:<상태> | not_dispatched | done | needs-input | failed.
        (llm/dev_client 인자를 주입하면 라이브 키 없이 가짜 LLM으로 전체 경로 테스트 가능)
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

    # 미터링(D46) — billing_enabled일 때만. working 진입 후 등급가중 1회 차감.
    # 잔액 부족 + 스펜딩 캡 ON이면 실행하지 않고 blocked로 멈춤 → 페이월 트리거(컴퓨트 안 태움).
    if cfg.billing_enabled:
        from app.services import credit_service
        try:
            credit_service.charge_task(db, task.user_id, task.id, agent.model_tier)
            db.commit()
        except credit_service.InsufficientCreditsError:
            ts.transition(db, task, "blocked", error_summary="Insufficient credits — top up to continue")
            events.emit_terminal_notification(db, task)
            db.commit()
            events.emit_status(task)
            events.emit_paywall(task.project_id, task.agent_id)  # 결제 모달 자동 노출(D46).
            return "insufficient_credits"

    # 엔진 라우팅.
    if task.engine == "agent_sdk":
        # CMA 파일럿(D45): development 팀만 cma. design은 playwright 스크린샷(D42) 필요 → E2B 유지.
        from app.models import Team
        team = db.get(Team, agent.team_id)
        is_dev = bool(team and team.template_key == "development")
        if cfg.dev_engine == "cma" and is_dev:
            from app.services.cma_engine import run_dev_task_cma
            return run_dev_task_cma(db, task, agent, model, cfg, enqueue)
        return _run_dev_task(db, task, agent, model, cfg, dev_client, enqueue)

    # 텍스트 경로(기획/리서치 등 글쓰기팀) — litellm 1회 호출(과거 CrewAI).
    prompt = assemble_prompt(db, task, context_token_budget=cfg.context_token_budget)
    client = llm or TextLLM(model)

    try:
        raw, tokens_in, tokens_out = client.complete(agent.role_instructions, prompt)
        output = _coerce_output(raw)
    except Exception as exc:  # noqa: BLE001 — 워커 경계.
        _refund_if_billing(db, task, agent, cfg)  # 시스템 실패(크래시) → 환불
        send_slack_alert(f"agent run crashed · {agent.name}", f"{type(exc).__name__}: {exc}")
        ts.transition(db, task, "failed", error_summary=f"{type(exc).__name__}: {exc}")
        events.emit_terminal_notification(db, task)
        db.commit()
        events.emit_status(task)
        return "failed"

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
    """개발/디자인 작업 실행 — 격리된 가상 컴퓨터(샌드박스)에서 실제로 코드를 짜고 결과를 거둔다.

    무슨 일을 하나: 글쓰기팀과 달리 개발·디자인팀은 진짜 파일을 만들어야 한다. 그래서 프로젝트별
        샌드박스(E2B — 안전하게 명령을 돌릴 수 있는 일회용 리눅스 컴퓨터)를 띄우고, 그 안에서
        dev-runner(AI가 명령을 내려 코드를 작성·실행·검증하는 루프)를 돌린 뒤 바뀐 파일을 수집한다.
    누가 부르나: process_task의 engine=="agent_sdk" 분기.
    처리 순서:
        1. ensure_running: 프로젝트 샌드박스를 켠다(없으면 그때 생성 = lazy).
        2. assemble_prompt + dev_runner.run_dev_task: 샌드박스 안에서 작업 수행.
        3. 결과에 따라 needs-input / failed / done 전이.
        4. done이면 collect_outputs로 바뀐 파일(코드 트리·디자인 PNG)을 아웃풋으로 저장 + _finalize_done.
        5. pause_if_idle: 더 돌릴 작업이 없으면 샌드박스를 잠재워 비용 절약.
    연결: 샌드박스 관리 → workspace.py. 실제 실행 루프 → dev_runner.py. 파일 수집 → verification.py.
    """
    import time

    from app.models import Project
    from app.services import dev_runner
    from app.services.verification import collect_outputs
    from app.services.workspace import WorkspaceError, workspace_service

    project = db.get(Project, task.project_id)
    try:
        sandbox_id = workspace_service.ensure_running(db, project)
    except WorkspaceError as exc:
        _refund_if_billing(db, task, agent, cfg)  # 샌드박스 기동 실패 = 시스템 실패 → 환불
        send_slack_alert(f"sandbox start failed · {agent.name}", str(exc))
        ts.transition(db, task, "failed", error_summary=str(exc))
        events.emit_terminal_notification(db, task)
        db.commit(); events.emit_status(task)
        return "failed"

    # 샌드박스 수명을 태스크 예산에 맞춤(P0) — create 기본 10분 vs 태스크 예산 30분 불일치로
    # 장시간 태스크 도중 E2B가 샌드박스를 GC("sandbox not found" 크래시)하던 것 방지.
    # +300s 여유: 출력 수집(collect_outputs)·버전 스냅샷까지 샌드박스가 살아있어야 한다.
    workspace_service.extend_lifetime(sandbox_id, cfg.dev_task_timeout_min * 60 + 300)

    prompt = assemble_prompt(db, task, context_token_budget=cfg.context_token_budget)
    if dev_client is None:
        from app.services.orchestrator import LiteLLMClient
        dev_client = LiteLLMClient(db, model=model)

    # mtime 여유 2초 — 파일시스템 mtime이 초 단위로 truncate되면(일부 FS/타이밍) task 시작과
    # 같은 초에 쓰인 파일이 since_mtime보다 작아져 수집에서 누락될 수 있다(간헐 flake). 살짝 과수집이
    # 나더라도(직전 2초 내 파일) 영속 워크스페이스에선 무해하고, 누락보다 안전하다.
    start_mtime = time.time() - 2.0
    outcome = dev_runner.run_dev_task(
        prompt, workspace_service.provider, sandbox_id,
        client=dev_client, role_instructions=agent.role_instructions,
        task_timeout_sec=cfg.dev_task_timeout_min * 60,
        # 라이브 진행(QA-01): 스텝마다 "Writing src/App.tsx" 같은 한 줄을 SSE로 흘린다.
        on_step=lambda label: events.emit_progress(task.project_id, task.agent_id, task.id, label),
        # Stop 실효(QA-05a): 스텝 경계마다 DB의 stopped 플래그 확인 → 유저 Stop이 즉시 먹힌다.
        should_stop=lambda: _task_stopped(db, task.id),
        # 서브태스크 plan(QA-06): 영속(패널 재오픈용) + SSE(라이브 체크리스트).
        on_plan=lambda steps: _save_plan(db, task, steps),
    )
    cost = cost_usd(cfg, model, outcome.tokens_in, outcome.tokens_out)

    if outcome.status == "stopped":
        # Stop 라우트가 이미 failed+stopped로 전이·커밋했다 — 여기서 전이하면 IllegalTransition.
        # 대신 부분 작업물을 보존한다(QA-05b): 지금까지 만든 파일을 수집·버전 커팅하고, 중단
        # 시점까지의 토큰을 회계에 남긴다(기존엔 22개 파일과 토큰 기록이 통째로 증발했다).
        # 워크스페이스는 프로젝트별 영속이라 재시도 태스크가 이 파일들 위에서 자연스럽게 이어간다.
        collect_outputs(db, task, workspace_service.provider, sandbox_id, since_mtime=start_mtime)
        from app.services.versioning import snapshot_version
        snapshot_version(db, task)
        task.verification = outcome.verification
        task.model_used = model
        task.tokens_in, task.tokens_out, task.est_cost_usd = outcome.tokens_in, outcome.tokens_out, cost
        db.commit()
        events.emit_usage(task.project_id, task.agent_id, outcome.tokens_in, outcome.tokens_out, cost)
        workspace_service.pause_if_idle(db, project)
        return "stopped"

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
    from app.services.versioning import snapshot_version
    snapshot_version(db, task)  # 프로젝트 파일 상태 갱신 + 버전 커팅(D50, 격리).
    new_ids = _finalize_done(db, task, outcome.tokens_in, outcome.tokens_out, cost)
    from app.services.preview import preview_service
    preview_service.refresh_if_active(db, project)  # 프리뷰 켜져 있으면 새 버전 반영(iteration, D51).
    workspace_service.pause_if_idle(db, project)
    _enqueue_children(new_ids, enqueue)
    return "done"


def reap_stale_tasks(db: Session, older_than_sec: int = 600) -> int:
    """좀비 작업 청소 — 워커가 죽어서 영영 안 끝날 'working' 작업을 찾아 failed 처리한다.

    무슨 일을 하나: 워커 프로세스가 도중에 죽으면 작업이 'working'에 영원히 멈춰 화면에 계속
        "일하는 중"으로 남는다. 일정 시간(기본 10분) 넘게 갱신 안 된 working 작업을 failed로 정리한다.
    누가 부르나: 주기적 청소 작업(Celery beat 등). 반환: 정리한 작업 수.
    """
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_sec)
    stale = (
        db.query(Task)
        .filter(Task.status == "working", Task.updated_at < cutoff)
        .all()
    )
    cfg = load_config(db)
    n = 0
    for task in stale:
        ag = db.get(Agent, task.agent_id)  # 좀비 = 시스템 실패 → 차감분 환불(billing ON일 때).
        if ag is not None:
            _refund_if_billing(db, task, ag, cfg)
        task.status = "failed"
        task.error_summary = "Worker timed out (reaped)"
        n += 1
    if n:
        db.commit()

    # queued 유실/데드락 복구 — 브로커 재시작(비영속 Redis)/게이트 데드락으로 멈춘 대기 task 재큐잉.
    _recover_stuck_queued(db)
    return n


def _recover_stuck_queued(db: Session, stuck_sec: int = 180) -> int:
    """queued에 갇힌 task 복구 — 유실/데드락된 대기 task를 다시 큐에 올린다(감사 P1).

    무슨 일을 하나: status=queued인데 stuck_sec(기본 3분) 넘게 디스패치 안 된 task를 재큐잉한다.
        비영속 Redis가 재시작하면 브로커의 대기 메시지가 증발 → task는 DB엔 queued인데 아무도 안
        집는다(유실 벡터). 동시성 게이트로 대기하던 형제 task도 마찬가지로 멈출 수 있다. process_task는
        status 가드로 멱등이라, 혹시 브로커에 아직 남아있어도 중복 큐잉은 무해하다.
    누가 부르나: reap_stale(주기 beat, 60초). 반환: 재큐잉한 개수.
    한계: 정당하게 게이트된(일시정지 등) task도 매 주기 재큐잉→게이트 재확인(저비용). 30분 넘게도 안
        풀리면 진짜 데드락 신호 → 임계 크로싱 시 1회 Slack 알림.
    """
    from datetime import timedelta

    from app.celery_app import enqueue_task

    now = datetime.now(timezone.utc)
    stuck = (
        db.query(Task)
        .filter(Task.status == "queued", Task.updated_at < now - timedelta(seconds=stuck_sec))
        .limit(200)
        .all()
    )
    for t in stuck:
        enqueue_task(t.id)  # 멱등 재큐잉(유실/데드락 복구).

    # 30분 넘게도 안 풀린 것 = 진짜 데드락 → 임계 크로싱 시 1회 알림(스팸 방지). 비교는 SQL에서
    # (updated_at은 tz-naive 컬럼이라 파이썬에서 aware now와 직접 비교하면 TypeError).
    hard = (
        db.query(Task)
        .filter(
            Task.status == "queued",
            Task.updated_at < now - timedelta(seconds=1800),
            Task.updated_at >= now - timedelta(seconds=1890),
        )
        .all()
    )
    if hard:
        ids = ", ".join(str(t.id) for t in hard[:10])
        log.warning("stuck queued tasks (>1800s, re-enqueued): %s", ids)
        send_slack_alert(
            f"stuck tasks · {len(hard)} queued >30m (re-enqueued, still stuck)",
            f"task ids: {ids}",
        )
    return len(stuck)
