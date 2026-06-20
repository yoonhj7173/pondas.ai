# pondas.ai — Production Readiness Audit (Prod)

Target: `https://pondas.ai` (Vercel) + `https://api.pondas.ai` (Railway web+worker), Postgres+Redis (Railway). No separate staging. billing_enabled=OFF, Stripe sandbox.
Date: 2026-06-20 · Method: code/architecture review + empirical measurement where possible. Findings logged as-you-go.

Severity: **P0** blocker · **P1** should-fix · **P2** nice-to-have. Status: ⏳ auditing · 🔴 open · 🔁 fixed&reverified · ✅ clean.

> Load/concurrency/stress against prod gated on user confirmation + volume cap (no staging).

---

## Findings by area

### 1. Concurrency & data integrity
- 🔴 **P0 — no DB uniqueness on `credit_ledger.stripe_ref` → concurrent webhook double-credit.** App-level `_already_posted` (credit_service.py:61-72) is a check-then-insert at READ COMMITTED; two concurrent deliveries of the same Stripe event both see 0 rows → both insert → double credit. (This is the exact follow-up flagged after BUG-7.) Fix: partial unique index `UNIQUE(stripe_ref) WHERE delta>0`, treat IntegrityError as already-processed.
- 🔴 **P0 — credit balance is read-modify-write with no row lock → lost updates + spending-cap bypass.** `_post` (credit_service.py:92-93) reads `acct.balance` into Python, `+= delta`, writes back; concurrent charge+topup (or two workers) lose one update. `charge_task` cap check (124-127) reads balance unlocked → cap bypassable. Fix: `SELECT … FOR UPDATE` on CreditAccount or atomic `UPDATE … SET balance = balance + :delta`.
- 🟠 **P1 — `get_or_create_account` insert race** (42-47): concurrent first-touch → duplicate PK insert aborts txn. Fix: INSERT … ON CONFLICT DO NOTHING / catch IntegrityError + refetch.
- 🟠 **P1 — `apply_subscription_refill` writes plan/allowance before idempotency check** (148-151) → duplicate webhook still does a (harmless, same-value) write. Fix: check `_already_posted` first.
- ✅ Clean: project-creation atomicity (single commit + rollback), orchestrator enqueue-AFTER-commit (BUG-5 fix holds), `try_dispatch` uses `with_for_update()` + status recheck (no two-worker grab), task-status transition table.
- 🟡 P2: API stop/continue don't lock the task row (worst case redundant terminal write / caught IllegalTransition).

### 2. Performance & algorithmic efficiency
- ✅ Backend `/health` latency (15 samples): p50 **243ms**, p95 445ms — mostly client→Railway network RTT (min 232ms); endpoint itself is fast.
- 🟡 P2 — authed DB-query endpoints (map/board) latency + N+1 review not deep-measured this pass; ORM relationships look eager-loaded but worth a slow-query/EXPLAIN pass under load. No obvious O(n²) in hot paths from the agent review.

### 3. Web performance (frontend) — ✅ essentially clean
- **Core Web Vitals (warm, real Chrome):** TTFB **47ms**, FCP **772ms**, LCP **772ms** (good <2.5s), **CLS 0** (perfect), DOMContentLoaded 712ms, load 2.39s, 32 resources. All CWV in "good" range.
- 🟡 P2 — **cold-start TTFB ~1.75s** (first hit after idle = Vercel serverless cold start; warm hits 137-356ms). Mitigate with more SSG/ISR or keep-warm if it matters for first-visit SEO.

### 4. Scalability & load
_(rate-limit fixed earlier; load test gated on confirmation)_

### 5. Resilience & fault tolerance
- 🔴 **P0 — LiteLLM `completion()` has NO timeout/retries** (orchestrator.py:399). Used by sync chat endpoint + dev_runner per-step. A hung provider pins a FastAPI thread / Celery worker indefinitely (the per-task timeout is only checked *between* steps, can't interrupt an in-flight call). Fix: `timeout=` + `num_retries=`.
- 🟠 **P1 — Clerk JWKS fetch no timeout** (auth.py:98-112) → on key rotation/cache-miss every authed request can block site-wide. Fix: `PyJWKClient(..., timeout=…)`.
- 🟠 **P1 — Stripe SDK no timeout/retries** (stripe_service.py:41-43) → checkout/portal/webhook threads can stall. Fix: `stripe.max_network_retries=2` + client timeout.
- 🟠 **P1 — Redis client no socket timeout** (db.py:32) → `/ready` + enqueue can hang if Redis unreachable. Fix: `socket_timeout`/`socket_connect_timeout`.
- ✅ Clean: E2B/CMA/dev-runner all have timeouts + budgets; Redis pub/sub degrades gracefully (DB is authority); Slack alerts best-effort w/ 3s timeout; `reap_stale_tasks` reaps stuck `working` tasks (60s beat) as a backstop.

### 6. Security — ✅ CLEAN (no P0/P1)
- **AuthZ on all 47 routes** ✅ — every business route requires `require_user`/`tenant_scope`; every id lookup goes through ownership loaders (ownership.py) returning **404 (existence-hiding)** for non-owned → IDOR-safe. Webhook/`/health`/`/ready` intentionally unauth (Stripe signature-verified / infra probes).
- **Secrets** ✅ — no hardcoded keys (only `.env.example` placeholders, no `.env` tracked); all `NEXT_PUBLIC_*` are publishable/public-safe (Stripe pk, Clerk pk, GA id, Amplitude ingest key); no server secret in client bundle. **Empirically verified: scanned 11 prod JS chunks → 0 secret leaks.**
- **CORS** ✅ strict allowlist (not wildcard), credentials paired with explicit origins.
- **Input** ✅ — ORM parameterized (no string SQL); `subprocess shell=True` gated to E2B microVM in prod (refuses to boot without E2B_API_KEY); `dangerouslySetInnerHTML` only static JSON-LD; SafeStr/NonBlankStr on user text.
- 🟡 Operational (verify in prod env, not code): `APP_ENV=production`, `E2B_API_KEY` set, `E2E_AUTH_BYPASS=false` (boot-guard exists), `CORS_ORIGINS`=real domain.
- 🟠 **P1 — dependency vulns:** `npm audit` → 4 (1 **high**, 3 moderate). `next@14.2.35` has many HIGH CVEs (DoS via image optimizer, HTTP request smuggling in rewrites, RSC cache-poisoning, SSRF via WS upgrade, CSP-nonce XSS…). Fix requires Next 15/16 (breaking). Many are Vercel-edge-mitigated but should bump. **Flag: major upgrade → confirm before doing.**

### 7. Observability
- ✅ Structured JSON logging (logging_config.py); Slack alerts for 500s, agent crash, sandbox-start fail, worker crash, **Stripe webhook fail**; `reap_stale_tasks` backstop.
- 🟠 **P1 — no error tracking (Sentry/equiv)** → no grouping/stack search/release tracking; debugging = grep Railway logs. Fix: add Sentry (FastAPI + Celery). **Needs your Sentry account/DSN.**
- 🟠 **P1 — no metrics** (throughput, queue depth, dispatch-reject rate, spend trend). Fix: Prometheus/StatsD basics.
- 🟠 **P1 — silent blind spots:** stuck `queued`/`needs-input` tasks never surfaced or reaped (reaper only targets `working`); `not_dispatched`/`not_found` returns not logged/alerted → an enqueued-but-never-dispatched task is invisible. Fix: extend reaper to alert (not auto-fail) on long-stuck queued/needs-input + log dispatch-skip returns.

### 8. Cost controls (LLM/agent)
- ✅ Bounded: dev_runner E2B loop `MAX_STEPS=40` + 30min + 300s/cmd; orchestrator tool-loop `max_iters=8`; dispatch gates (concurrency 3, daily $10/user, goal-chain 25) enforced atomically under `with_for_update()`.
- 🔴 **P0 — CMA dev loop has NO turn cap** (cma_engine.py:172 / cma.py:156). CMA is the **default** engine; only bound is `poll_until_idle(30min)`. A thrashing model bills 30 min of Opus tool-calling with no turn ceiling; with billing OFF, no credit backstop. Fix: count model-request events in poll loop, abort past N (or per-session token budget).
- 🔴 **P0 — `daily_cost_cap` silently no-ops if `model_pricing` misses the live model** (config_store.py:106 → `cost_usd()` returns 0.0). Every task records `est_cost_usd=0` → "$10/day hard stop" never trips → unlimited spend. Fix: on pricing-miss, log WARN + fall back to non-zero estimate so cap still bites.
- 🟠 **P1 — caps are post-hoc, not pre-flight:** a single in-flight task has no budget kill; first run of the day is unbounded. Goal-less chat-dispatched tasks (goal_id=None) **bypass the goal-chain budget** (task_service.py:140); no per-user total/daily task-count quota — only concurrency=3 throttles. Fix: per-task token ceiling in both engine loops + per-user daily task quota.

### 9. State & caching
- ⏳ light review pending (config_store cached config invalidation, SSE/optimistic-UI). No obvious P0 from agent passes.

### 10. SEO/GEO & accessibility
- ✅ `robots.txt` correct: `Allow /`, `Disallow /app/ /onboarding` (don't index authed app), **explicitly allows GPTBot/ClaudeBot/PerplexityBot/Google-Extended** (GEO). `sitemap.xml` renders (home + blog + posts w/ lastmod/priority). GSC verification tag present (from E2E).
- ⏳ a11y (keyboard/focus/ARIA/contrast via axe) — pending.

### 11. Deploy / infra robustness
- ✅ env separation (`is_production` gate, refuses boot if `e2e_auth_bypass` in prod); `/health` dep-free + `/ready` checks DB+Redis (503 if down); start scripts use `exec` (uvicorn/celery get SIGTERM as PID 1); migrations run before serve; `pool_pre_ping=True`.
- 🟠 **P1 — worker no `acks_late`/graceful shutdown → dropped tasks on redeploy.** Default `acks_late=False` acks before exec; Railway SIGTERM→SIGKILL loses in-flight task (reaper marks zombie failed after 10min but task is dropped, not resumed). Fix: `task_acks_late=True` + `task_reject_on_worker_lost=True` + shutdown grace.
- 🟠 **P1 — no Celery `time_limit`/`soft_time_limit`/retries** (celery_app.py) → a task hung outside the agent loop has no hard kill; transient failures not retried (and lost since acks_late off). Fix: `task_time_limit`/`soft_time_limit` above 30min + bounded retries.
- 🟡 P2 — DB pool unsized (defaults 15/proc × 4 procs = up to 60 conns — verify < Railway max); `sandbox_allow_internet` defaults True (CMA uses limited; verify E2B egress in prod); `/ready` → confirm Railway healthcheck points at it (infra).

### 12. Backup / DR
- ✅ Alembic downgrades present + real on all 5 migrations (rollback path exists).
- 🟡 P2 — downgrades are destructive (drop), no data-preserving story; `alembic upgrade head` runs on every web boot (a bad migration blocks all web start — no canary).
- 🟠 **Infra-level (verify in Railway, not code):** Postgres backup/PITR retention; Redis persistence (AOF/RDB) — Redis is broker+pubsub; non-persistent Redis + acks_late gap = queued-task-loss vector on restart.

---

## Summary (audit complete — Phase 1/2)

| Area | Findings | Verdict |
|---|---|---|
| 1 Concurrency/integrity | 2× P0, 2× P1 | needs fix (locking + stripe_ref uniqueness) |
| 2 Performance | clean + P2 | ✅ acceptable |
| 3 Web perf (CWV) | clean + P2 | ✅ good |
| 4 Scalability/rate-limit | fixed earlier | ✅ (load test gated) |
| 5 Resilience | 1× P0, 3× P1 | needs fix (external-call timeouts) |
| 6 Security | clean + 1× P1 (deps) | ✅ strong (Next CVE bump) |
| 7 Observability | 3× P1 | gaps (Sentry/metrics/stuck-task alerts) |
| 8 Cost controls | 2× P0, 1× P1 | needs fix (CMA cap, cost-cap no-op) |
| 9 State/caching | light | ✅ no P0 seen |
| 10 SEO/a11y | SEO ✅ | a11y pending |
| 11 Deploy/infra | 2× P1, P2 | needs fix (acks_late, time_limit) |
| 12 Backup/DR | infra-level | verify in Railway |

**P0 (5):** ① stripe_ref no unique index (concurrent double-credit) ② credit balance read-modify-write no lock ③ LiteLLM no timeout (worker hang) ④ CMA loop no turn cap (unbounded cost) ⑤ daily_cost_cap no-ops on pricing miss (unbounded cost).
**P1 (≈10):** Clerk/Stripe/Redis timeouts · get_or_create race · Next CVE upgrade · Sentry · metrics · stuck-task alerts · Celery acks_late/graceful-shutdown · Celery time_limit/retries.
**Security = clean. CWV = good. Cost & resilience = the real risk surface.**

### Fix plan (recommended split)
**Fix now (low-risk, high-value, additive):** external-call timeouts (LiteLLM/Clerk/Stripe/Redis + DB statement_timeout) · Celery `acks_late`+`reject_on_worker_lost`+`time_limit`/`soft_time_limit` · daily_cost_cap pricing-miss fallback · CMA loop turn cap · credit-balance atomic update · reaper alert on stuck queued/needs-input.
**Flag / needs your input:** stripe_ref unique index (needs prod dedup of existing duplicate rows first — prod data) · Sentry (needs your account/DSN) · metrics stack · per-user task quota (product decision) · Next 15/16 upgrade (breaking) · infra-level (Railway Postgres backup/PITR, Redis persistence, healthcheck path).

---

## Phase 3 — Fixes applied (safe batch)

### ✅ PR #29 — resilience timeouts + Celery hardening (merged + deployed)
- LiteLLM `completion()`: `timeout` (120s) + `num_retries` — no more worker-pinning provider hangs. **P0 ✅**
- Clerk JWKS `timeout=10`; Stripe `max_network_retries=2`; Redis `socket_timeout=5`; DB `statement_timeout=30s` + `connect_timeout` + explicit pool. **P1/P2 ✅**
- Celery `task_acks_late` + `task_reject_on_worker_lost` + `prefetch=1` + `task_time_limit`/`soft_time_limit` (40/35m) + broker `visibility_timeout`. No dropped task on redeploy; hung tasks hard-killed. **P1 ✅**

### ✅ PR #30 — cost caps + integrity (merged + deployed)
- **CMA loop turn cap** `MAX_MODEL_REQUESTS=60` (default engine; was 30-min-only). **P0 cost ✅**
- **daily_cost_cap pricing-miss fallback** → non-zero estimate so the cap always bites. **P0 cost ✅**
- **Atomic credit balance** `UPDATE … SET balance = balance + :delta` (was read-modify-write → lost-update/cap-bypass race). **P0 integrity ✅**
- **Stuck-queued Slack alert** at 30-min threshold (was a silent blind spot). **P1 obs ✅**

Both verified: full test suite green; **post-deploy prod smoke ✅** — `/health` 200, `/ready` 200 (`db:true, redis:true` — new Redis socket-timeout + DB pool didn't break readiness), project create 201, map 200, billing summary reads fine. No functional regression from the timeout/pool/Celery/atomic-balance changes.

---

## Phase 4 — Handoff

### What was fixed & re-verified (this pass)
| # | Item | Sev | PR | Re-verified |
|---|---|---|---|---|
| 5 | LiteLLM timeout (worker-hang) | P0 | #29 | suite + smoke |
| 5 | Clerk/Stripe/Redis/DB timeouts | P1/P2 | #29 | smoke (/ready ok) |
| 11 | Celery acks_late + time_limit | P1 | #29 | suite |
| 8 | CMA loop turn cap | P0 | #30 | unit test |
| 8 | cost-cap pricing-miss fallback | P0 | #30 | unit test |
| 1 | atomic credit balance | P0 | #30 | unit + smoke |
| 7 | stuck-queued alert | P1 | #30 | unit |

### Prioritized backlog (not done — your call)
**P0 (do before real scale / billing-on):**
1. `credit_ledger.stripe_ref` partial unique index + dedup existing prod dup rows (concurrent webhook double-credit). Separate PR — touches prod data (your sandbox account's BUG-7 dup rows + balance correction).

**P1:**
2. Sentry (web + worker) — needs your DSN.
3. Metrics (task throughput, queue depth, spend trend) — Prometheus/StatsD.
4. `get_or_create_account` ON CONFLICT (insert race).
5. Per-user daily task-count quota + force goal_id on chat dispatches (goal-less tasks bypass chain budget).
6. Next.js 15/16 upgrade (HIGH CVEs; breaking — dedicated regression task).

**P2:** DB pool tuned to Railway plan; `SANDBOX_ALLOW_INTERNET=false` default in prod; cold-start (more SSG/ISR); a11y axe pass; migrate-on-boot canary.

### You should verify / do (infra-level, not in code)
- Railway: **Postgres backup/PITR** retention enabled; **Redis persistence** (AOF/RDB) on (broker durability — else queued tasks lost on Redis restart); healthcheck path = `/ready`.
- Prod env vars: `APP_ENV=production`, `E2B_API_KEY` set, `E2E_AUTH_BYPASS=false`, `CORS_ORIGINS`=real domains, `SANDBOX_ALLOW_INTERNET=false`.
- Sentry account/DSN if you want #2.

### Cleanup / reset needed first
- None outstanding from this audit (smoke test project auto-deleted). The `stripe_ref` dedup (backlog #1) will need a one-time prod data migration — I'll show the exact dedup before running.

### Remaining (your-input / flagged — see handoff)
- 🔴→📋 **stripe_ref unique index + prod dedup** (P0 concurrency, app-level guard covers sequential retries today; concurrent double-delivery still possible). Separate PR — needs prod dedup of sandbox dup rows + balance correction.
- 📋 Sentry (P1, needs DSN), metrics (P1), per-user task quota / goal-less budget (P1, product), `get_or_create_account` ON CONFLICT (P1), Next 15/16 upgrade (P1 deps, breaking), DB pool tuning to plan limits (P2), cold-start (P2).
- 📋 **Infra-level (verify in Railway dashboard, not code):** Postgres backup/PITR retention; Redis persistence (AOF/RDB) — broker durability; `/ready` wired as the healthcheck path; confirm `APP_ENV=production`, `E2B_API_KEY`, `E2E_AUTH_BYPASS=false`, `CORS_ORIGINS`, `SANDBOX_ALLOW_INTERNET=false`.
