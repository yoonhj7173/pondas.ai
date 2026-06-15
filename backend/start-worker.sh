#!/usr/bin/env bash
# Celery 워커 진입 — 마이그레이션/시드는 web이 담당. 여기선 워커만.
set -e
echo "[deploy] celery worker"
exec celery -A app.celery_app worker --loglevel=info --concurrency=2
