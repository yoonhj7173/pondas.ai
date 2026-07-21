#!/usr/bin/env bash
# E2E 러너(test-plan §2) — 로컬 스택 기동 → 시드 → Playwright.
# 전제: docker(cpm-test-pg/redis) 가능, backend/.venv 존재, frontend deps 설치됨.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DATABASE_URL=${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/postgres}
export REDIS_URL=${REDIS_URL:-redis://localhost:6379/0}
export APP_ENV=test E2E_AUTH_BYPASS=1

docker start cpm-test-pg cpm-test-redis >/dev/null 2>&1 || true
until docker exec cpm-test-pg pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done

cd "$ROOT/backend"
.venv/bin/alembic upgrade head >/dev/null
.venv/bin/python seed.py >/dev/null
.venv/bin/python scripts/seed_e2e_fixture.py
.venv/bin/uvicorn app.main:app --port 8000 >/tmp/e2e-backend.log 2>&1 &
BACK=$!
FRONT=""
trap 'kill $BACK $FRONT 2>/dev/null || true' EXIT
until curl -sf http://localhost:8000/ready >/dev/null 2>&1; do sleep 1; done

cd "$ROOT/frontend"
NEXT_PUBLIC_E2E=1 NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev >/tmp/e2e-frontend.log 2>&1 &
FRONT=$!
until curl -sf http://localhost:3000/onboarding >/dev/null 2>&1; do sleep 2; done

npx playwright test "$@"
