"""Event publishing — project:{id} Redis 채널로 SSE 이벤트 + notification 행 생성(item 12).

세 종류 이벤트를 같은 채널로 publish하고, SSE 라우터(GET /sse)가 그대로 중계한다:
- task_status : task 상태 전이마다.
- notification: 종결/대기(done/blocked/needs-input/failed)에서 notification 행 + 이벤트.
- usage      : 토큰/비용 델타(카운터/팝오버).

publish 실패는 무시(관측 채널이지 권위 상태가 아니다 — 권위는 DB).
"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy.orm import Session

from app.db import redis_client
from app.models import Agent, Notification, OrchestratorMessage, Task

log = logging.getLogger("app.events")


def _channel(project_id) -> str:
    return f"project:{project_id}"


def _publish(project_id, payload: dict) -> None:
    """이벤트 발행(공통) — 한 프로젝트의 실시간 채널(Redis)로 메시지 한 건을 던진다.

    중요: 발행이 실패해도 무시한다. 이 채널은 '관측용'(화면을 예쁘게 갱신)일 뿐, 진짜 데이터(권위)는
        항상 DB다. 알림 하나 누락돼도 DB는 멀쩡하므로 작업을 깨뜨리지 않는다.
    누가 부르나: 아래 emit_status / emit_usage / emit_terminal_notification.
    연결: 이 채널을 구독해 브라우저로 중계하는 곳 → sse (backend/app/routers/realtime.py).
    """
    try:
        redis_client.publish(_channel(project_id), json.dumps(payload))
    except Exception:  # noqa: BLE001
        log.warning("event publish failed", extra={"project_id": str(project_id)})


def emit_status(task: Task) -> None:
    """상태 변경 알림 — 작업 상태가 바뀌었음을 실시간 채널로 쏴서 맵 캐릭터를 갱신시킨다."""
    _publish(task.project_id, {
        "type": "task_status",
        "task_id": str(task.id),
        "agent_id": str(task.agent_id),
        "status": task.status,
    })


def emit_progress(project_id, agent_id, task_id, label: str) -> None:
    """라이브 진행 한 줄(QA-01) — dev/design 러너가 지금 뭘 하는지 실시간으로 쏜다.

    "8분 침묵" 처방: 진행이 안 보이면 유저가 멀쩡한 태스크를 Stop해버린다(실사례 — 22파일 증발).
    DB에 안 쓰는 transient 이벤트 — 스텝마다 나가므로 가볍게, 발행 실패는 여느 이벤트처럼 무시.
    """
    _publish(project_id, {
        "type": "progress",
        "agent_id": str(agent_id),
        "task_id": str(task_id),
        "label": label[:160],
    })


def emit_plan(project_id, agent_id, task_id, steps: list) -> None:
    """서브태스크 plan 갱신(QA-06) — 에이전트가 update_plan을 부를 때 체크리스트를 브로드캐스트."""
    _publish(project_id, {
        "type": "plan",
        "agent_id": str(agent_id),
        "task_id": str(task_id),
        "steps": steps,
    })


def emit_usage(project_id, agent_id, tokens_in: int, tokens_out: int, cost: float) -> None:
    _publish(project_id, {
        "type": "usage",
        "agent_id": str(agent_id),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost,
    })


def emit_paywall(project_id, agent_id) -> None:
    """크레딧 부족으로 task가 막힘 — 프론트가 결제 모달을 자동으로 띄우게 하는 신호(D46 페이월).

    'blocked'는 다른 사유로도 생겨서 일반 알림으론 구분 불가 → 전용 paywall 이벤트를 따로 쏜다.
    """
    _publish(project_id, {"type": "paywall", "agent_id": str(agent_id)})


def emit_preview_status(project_id, status: str, *, url: str | None = None, version_no: int | None = None) -> None:
    """Live Preview 상태 변경(Phase 2, D49) — 시어터가 iframe/버전칩을 갱신하도록 쏘는 신호."""
    _publish(project_id, {
        "type": "preview_status",
        "status": status,
        "url": url,
        "version_no": version_no,
    })


# 종결/대기 상태 → 사용자에게 알릴 notification 매핑.
_NOTIFY_STATUSES = {"done", "blocked", "needs-input", "failed"}


def emit_terminal_notification(db: Session, task: Task) -> None:
    """완료/대기 알림 만들기 — 작업이 끝났거나 멈췄을 때 벨에 뜰 알림을 만들고 실시간으로 쏜다.

    무슨 일을 하나: 작업이 done/failed/needs-input/blocked가 되면, 사용자에게 보여줄 알림 한 줄
        ("OOO가 끝났어요" 등)을 notifications 테이블에 만들고 실시간 채널로도 발행한다(벨 뱃지 +1).
    누가 부르나: 작업 마무리 곳곳 — _finalize_done / 각 실패·대기 분기 (backend/app/services/worker_core.py).
    연결: 알림 목록 조회 → list_notifications (backend/app/routers/realtime.py).
    """
    if task.status not in _NOTIFY_STATUSES:
        return
    agent = db.get(Agent, task.agent_id)
    name = agent.name if agent else "Agent"
    msgs = {
        "done": f"{name} finished",
        "failed": f"{name} failed" + (" (stopped)" if task.stopped else ""),
        "needs-input": f"{name} needs your input",
        "blocked": f"{name} is blocked",
    }
    notif = Notification(
        user_id=task.user_id, project_id=task.project_id, agent_id=task.agent_id,
        task_id=task.id, type=task.status, message=msgs.get(task.status, name),
    )
    db.add(notif)
    # Web Push(D56⑤) — 유저가 자리에 없어도 모바일/데스크톱 알림. 베스트에포트(실패해도
    # 인앱 파이프 무영향). 딥링크 = 해당 프로젝트 오피스.
    try:
        from app.services.push_service import send_push
        send_push(db, task.user_id, title=notif.message,
                  body=(task.awaiting_prompt or task.result_markdown or task.error_summary or "")[:140],
                  url=f"/app/{task.project_id}")
    except Exception:  # noqa: BLE001
        pass
    # 오케스트레이터 컨텍스트 허브(B1) — 태스크 종결을 지휘자 대화 이력에도 이벤트로 남긴다.
    # 여태 완료가 벨(Activity)로만 가고 지휘자는 아무것도 몰라, "누가 뭘 끝냈어?"에 깜깜했고
    # 채팅창에도 흔적이 없었다. 이 행은 ① 다음 지휘자 턴의 히스토리로 주입되고(_load_history)
    # ② 채팅창에 회색 이벤트 라인으로 렌더된다(canned — LLM 호출 없음).
    snippet = " ".join(((task.result_markdown or task.error_summary or "")[:300]).split())
    db.add(OrchestratorMessage(
        project_id=task.project_id, role="event",
        content=f"[event] {notif.message}" + (f" — {snippet}" if snippet else ""),
    ))
    db.flush()
    _publish(task.project_id, {
        "type": "notification",
        "notification_id": str(notif.id),
        "agent_id": str(task.agent_id),
        "notif_type": task.status,
        "message": notif.message,
    })
