"""Celery app — 비동기 task 실행 + reaper beat (item 10).

broker/backend = Redis(settings.redis_url). 실행 자체는 worker_core.process_task가 하고
여기선 Celery 태스크로 감싸 세션 수명/재시도 경계를 둔다. 디스패치는 enqueue_task로.

run: celery -A app.celery_app worker --beat (개발). 테스트는 process_task를 직접 호출하거나
task_always_eager로 동기 실행한다.
"""

from __future__ import annotations

import uuid

from celery import Celery

from app.config import settings
from app.db import SessionLocal
from app.services.worker_core import process_task, reap_stale_tasks

celery_app = Celery(
    "cursorpm",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    # 재배포/워커 사망 시 in-flight task 유실 방지(감사 P1): 메시지를 실행 성공 후에 ack,
    # 워커가 죽으면 메시지를 브로커로 되돌려 다른 워커가 재실행(process_task는 status 가드로 멱등).
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # acks_late와 궁합 — 워커당 1개씩만 선점.
    # 하드/소프트 시간 제한(감사 P1) — agent 루프 밖에서 행 걸린 task를 강제 종료.
    # dev task는 최대 30분이라 그 위로 잡는다(soft가 먼저 SoftTimeLimitExceeded를 던져 정리 기회).
    task_soft_time_limit=2100,  # 35분
    task_time_limit=2400,       # 40분(hard kill)
    # Redis 브로커 가시성 타임아웃은 hard limit보다 커야 장기 task가 중복 재배달되지 않음.
    broker_transport_options={"visibility_timeout": 3600},
    beat_schedule={
        "reap-stale-tasks": {
            "task": "app.celery_app.reap_stale",
            "schedule": 60.0,  # 매 60초 stale working task 회수.
        },
        "pause-idle-previews": {
            "task": "app.celery_app.pause_idle_previews",
            "schedule": 120.0,  # 매 120초 idle 프리뷰 pause(과금 정지, D49).
        },
    },
)


@celery_app.task(name="app.celery_app.run_task")
def run_task(task_id: str) -> str:
    """워커가 집어 실행하는 작업 1건 — 큐에서 꺼낸 작업을 실제 처리 함수로 넘긴다.

    PM 한 줄: API는 작업을 '큐에 던지기만' 하고 즉시 응답한다(사용자를 안 기다리게). 그러면 별도
        백그라운드 프로세스(Celery 워커)가 이 함수를 실행해 진짜 일을 한다. = 비동기 처리(@Async 비슷).
    무슨 일을 하나: DB 세션을 열고 process_task로 작업을 처리한 뒤 닫는다.
    연결: 실제 처리 로직 → process_task (backend/app/services/worker_core.py). 큐에 넣기 → 아래 enqueue_task.
    """
    db = SessionLocal()
    try:
        return process_task(db, uuid.UUID(task_id))
    except Exception as exc:  # process_task를 빠져나온 예외 = 워커 자체 크래시 → 알림 후 재던짐.
        from app.services.slack_alerts import send_slack_alert
        send_slack_alert(f"worker crash · task {task_id}", f"{type(exc).__name__}: {exc}")
        raise
    finally:
        db.close()


@celery_app.task(name="app.celery_app.reap_stale")
def reap_stale() -> int:
    db = SessionLocal()
    try:
        return reap_stale_tasks(db)
    finally:
        db.close()


@celery_app.task(name="app.celery_app.pause_idle_previews")
def pause_idle_previews() -> int:
    """idle 프리뷰 pause(과금 정지, D49) — 매 120초 beat."""
    from app.services.preview import preview_service
    db = SessionLocal()
    try:
        return preview_service.pause_idle_previews(db)
    finally:
        db.close()


def enqueue_task(task_id: uuid.UUID) -> None:
    """작업 큐에 넣기 — "이 작업 처리해줘"라고 백그라운드 워커 큐에 작업 번호를 올린다.

    무슨 일을 하나: 작업을 즉시 실행하지 않고 Redis 큐에 등록만 한다. 워커가 알아서 꺼내 run_task로 처리한다.
    누가 부르나: 작업이 만들어지는 모든 곳 — 지휘자 dispatch_task(orchestrator.py), 자동 전파(graph_engine.py),
        입력 재개(tasks.py). 연결: 큐에서 꺼내 실행 → 위 run_task.
    """
    run_task.delay(str(task_id))


@celery_app.task(name="app.celery_app.github_push", bind=True, max_retries=5,
                 retry_backoff=30, retry_backoff_max=600)
def github_push(self, version_id: str) -> str:
    """버전 1개를 유저 GitHub 리포에 비동기 커밋(item 36, D61) — 태스크 완료를 절대 블록하지 않는다.

    재시도: 지수 백오프(30s→최대 10분) 5회 — GitHub 일시 장애/rate limit 흡수. 최종 실패해도
    pushed_at이 비어 있어 다음 연결/백필이 따라잡는다(멱등).
    """
    from app.services.github_service import push_version_sync

    db = SessionLocal()
    try:
        return push_version_sync(db, uuid.UUID(version_id))
    except Exception as exc:  # noqa: BLE001 — 재시도 대상(일시 장애 가정)
        raise self.retry(exc=exc)
    finally:
        db.close()
