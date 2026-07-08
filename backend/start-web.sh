#!/usr/bin/env bash
# 웹 서비스 진입 — DB 마이그레이션 + 시드 후 API 서빙. (worker는 start-worker.sh)
# 마이그레이션 canary: railway.json의 deploy.preDeployCommand가 트래픽 라우팅 전에 alembic을 먼저
#   돌린다 → 마이그레이션이 실패하면 배포가 중단되고 직전 정상 버전이 계속 서빙된다(전면장애 방지).
#   여기의 alembic/seed는 idempotent 이중안전(preDeploy 미적용 환경 대비 fallback). preDeploy가 도는 걸
#   Railway 배포 로그에서 확인하면 아래 두 줄은 제거해도 된다.
set -e
echo "[deploy] alembic upgrade head (fallback; canary = railway.json preDeployCommand)"
alembic upgrade head
echo "[deploy] seed config + role catalog"
python seed.py
echo "[deploy] uvicorn on :${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 2
