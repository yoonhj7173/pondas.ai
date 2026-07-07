#!/usr/bin/env bash
# 웹 서비스 진입 — DB 마이그레이션 + 시드 후 API 서빙. (worker는 start-worker.sh)
# redeploy trigger 2026-07-07: Railway 플랜 복구 후 main HEAD(Phase 2 item 28/30/33) 배포 재트리거.
set -e
echo "[deploy] alembic upgrade head"
alembic upgrade head
echo "[deploy] seed config + role catalog"
python seed.py
echo "[deploy] uvicorn on :${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 2
