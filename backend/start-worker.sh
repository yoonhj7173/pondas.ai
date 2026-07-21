#!/usr/bin/env bash
# Celery 워커 진입 — 마이그레이션/시드는 web이 담당. 여기선 워커만.
set -e
echo "[deploy] celery worker"
# --beat 필수(실사고 2026-07-21): 이게 없으면 리퍼(좀비 task 청소·환불)와 프리뷰 idle-pause
# (비용 정지)가 프로드에서 전혀 안 돈다 — 46분 좀비 + 샌드박스 과금 누수로 실측 발견.
# 단일 워커 replica 전제의 embedded beat(복제 늘리면 beat 분리 필요).
exec celery -A app.celery_app worker --beat --loglevel=info --concurrency=2
