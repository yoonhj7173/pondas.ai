# pondas — E2E / QA Test Runbook

**The single source of truth for testing pondas** (E2E + QA unified). Run this whole plan before a launch-grade deploy, and add a case here for **every** feature or bug fix so the process stays the same each time. Cover **happy + unhappy paths**. Tick `[x]` on pass; note failures inline.

**Last updated:** 2026-07-09 — (1) auth/routing/session (QA-ONB-02/05/06, QA-BILL-03). (2) agent validation + custom roles (QA-AGENT-02/11): 20-char name cap + control/angle-bracket rejection, real base-spec prefill, custom-role option, memory PUT hardening. (3) add-teams multi-select (QA-TEAM-02).

---

## How to run (the repeatable loop)

For each change (feature or fix):
1. **Backend unit/integration** — `cd backend && pytest -p no:warnings -q` (needs local Postgres + Redis; see Environment). Green is the gate.
2. **Frontend build** — `cd frontend && npm run build`; check the **exit code**. A failed Vercel build keeps prod on the last good deploy.
3. **Web E2E** — drive a **real browser** against **prod** (`https://pondas.ai`): walk the affected cases below, happy and unhappy. Don't stop at "build OK / API 200" — look at the rendered screen.
4. **Update this doc** — add/adjust the case(s) for what changed.
5. Merge via PR only (branch protection is strict). Deploy is automatic on merge to `main`; verify it's live on prod afterward.

## Pre-deploy gate (EVERY deploy)

Any failure blocks the merge:
1. `pytest` — full backend suite green (CI: `backend (pytest)`).
2. `npm run build` — exit 0 (CI: `frontend (build)`).
3. For a change to a flow below, walk its **affected** cases on prod post-deploy (happy + unhappy). Full sweep only for wide changes (billing / auth / engine / refactors).

## Gotchas (learned the hard way — read before testing)

- **Prod E2E costs real money.** Signup grants **500 credits**; task dispatch charges by tier (light 10 / medium 30 / strong 300). A full signup→dev-task→iteration→paywall walk burns real credits on the founder's live Stripe. Use text/light tasks for smoke; do NOT loop dev tasks to force the paywall unless you mean to spend. Billing regression → **staging keys**, not prod.
- **Login is Clerk (Google).** The automated tester can't enter credentials — have the human log in when prompted; the session persists in the same browser profile.
- **Browser-automation viewport coordinates shift with window size.** The chat bar / buttons move when the window resizes (e.g. 1512px vs 1568px). Re-screenshot and re-locate before clicking; a "sent" message that didn't dispatch usually means the Send click missed (no world-dim / no orchestrator reply bubble = it didn't send).
- **Two engines, different failure modes.** Text teams (Planning/Research) run via **litellm** (`crews/factory.TextLLM`, since #61 — CrewAI removed). Dev/Design run in an **E2B sandbox**; Development defaults to **CMA** (Claude Managed Agents). A text task failing with `OPENAI_API_KEY` = a regression of #61.
- **Deploy timing.** Vercel (frontend) ~60–90s after merge; Railway (backend) ~2–3min (Docker build + `alembic upgrade head` on boot). Poll before verifying backend changes.
- **Team-card summary is a map snapshot, refreshed live.** Pills/avatars update instantly from the store; the one-line summary is debounce-refetched on any status change (#62). If it looks stale, that's the ~900ms debounce, not a bug — but a summary that never updates IS.
- **Never commit to `main`; never `git add -A`.** Branch per change, stage only files you touched, `git branch --show-current` before commit/push. PRs squash-merge.

## Environment / preconditions

- **Prod**: frontend `https://pondas.ai`, API `https://api.pondas.ai`. Real Clerk auth + live Stripe.
- **Local test stack**: Postgres + Redis containers; `DATABASE_URL` / `REDIS_URL` env; `alembic upgrade head`. E2E-bypass: backend `E2E_AUTH_BYPASS=1` (user `e2e_user`) + frontend `NEXT_PUBLIC_E2E=1` (token `"e2e"`); `window.__qa.selectAgent(id)` hook opens panels without canvas clicks.
- **Dev preview routes** (not user-facing, robots-disallowed): `/map-preview`, `/overlays-preview`, `/panels-preview` render live components with mock data — fast UI checks without a backend.
- Slack alerts need `SLACK_ALERT_WEBHOOK_URL`. Stripe live keys live in Railway/Vercel dashboards (never in chat).

---

## 1. Onboarding (Flow 0)

- [ ] **QA-ONB-01 — New user → office** — logged-out `/onboarding` (or landing "Start building"): Google sign-in → display name → project name → **team multi-select** (4 cards: Planning / Research / Design / Development, rosters shown) → optional context dropzone → "Enter the office →". Lands on `/app/{id}` with **exactly the selected teams**, one starter agent each.
- [ ] **QA-ONB-02 — Returning user skips + last-project restore** — an onboarded user hitting bare `/app` **or** `/onboarding` (without `?new=1`) is routed to the **last project they had open** (localStorage `pondas:last_project`, validated against the live list; falls back to newest if stale/deleted), not re-onboarded and **not** a duplicate new project. Reopening the browser and revisiting returns to the same workspace.
- [ ] **QA-ONB-03 — Signup grants 500 credits** — a fresh account's Treasury shows **500** (D52). (Was 240 pre-#33.)
- [ ] **QA-ONB-04 — Bad input rejected** — blank/whitespace project name → 422 (not a blank project). Null byte / lone surrogate in name → 422, not 500 (input-sanitization guard).
- [ ] **QA-ONB-05 — Signed-in root → workspace** — an authenticated user visiting `/` is redirected by middleware to `/app` (→ last project). Logged-out visitors and crawlers still get the marketing landing (SEO preserved). The switcher's "＋ New project" goes to `/onboarding?new=1`, which **always** shows the wizard (creating an additional project is intentional there).
- [ ] **QA-ONB-06 — Tab titles** — product surfaces set a real `document.title` (client pages can't export metadata): workspace = `{project name} · pondas.ai`, `/onboarding` = `Get started · pondas.ai`, `/billing/return` = `Payment complete · pondas.ai`. Marketing/legal pages keep their existing SSG titles.

## 2. Office / orient (Flow 1) + status pipeline

- [ ] **QA-OFFICE-01 — Card office renders** — `/app/{id}` shows white **team cards**: team emoji + name + status pill + one-line summary + emoji-avatar crew (role→emoji, model tier under each). Scrollable; 5-agent teams wrap to rows. (React cards, not Pixi — #55.)
- [ ] **QA-OFFICE-02 — Workspace vertically centered** — with few cards the grid is **centered** in the viewport (not pinned to the top); with many it scrolls. No card underlaps the top-right Activity panel or top-left switcher at ≥1280px.
- [ ] **QA-OFFICE-03 — Live status pipeline** — one dispatched task updates the avatar ring/dot + team pill + Activity feed **identically and live** (SSE → store). `blocked` renders as `needs-input`. Reconnect re-fetches `/map` + `/usage`.
- [ ] **QA-OFFICE-04 — Team pill = current state** — pill reflects each agent's **latest** task (needs-input > failed > working > done > idle); an old resolved failure does NOT keep the card red (#64). Pill and summary agree.
- [ ] **QA-OFFICE-05 — Summary live-refresh** — after a task goes done, the card summary updates (to the goal title / "Task complete") **without a page reload** (#62, ~900ms debounce).
- [ ] **QA-OFFICE-06 — Click → panel** — clicking a team opens the TeamPanel; clicking an agent opens the AgentPanel; both without a full reload.
- [ ] **QA-OFFICE-07 — Empty team** — a team with 0 agents shows "No agents yet — hire your first"; a project with no tasks shows "No tasks yet — give the team something to do".

## 3. Project switcher (Flow 9)  _(#57)_

- [ ] **QA-PROJ-01 — List + current** — top-left project button (▾) → dropdown lists all your projects (newest first), current marked **✓**.
- [ ] **QA-PROJ-02 — Switch** — click another project → navigates to `/app/{id}`, office re-mounts with that project's teams.
- [ ] **QA-PROJ-03 — New project** — "＋ New project" → `/onboarding` (name + team wizard).
- [ ] **QA-PROJ-04 — Delete** — hover a row → 🗑 → inline "Delete X?" → Delete → `DELETE /projects/{id}` (sandboxes destroyed + cascade). Deleting the **current** project routes to another project, or `/onboarding` if none left.
- [ ] **QA-PROJ-05 — Outside-click / ESC** — closes the dropdown; list-fetch failure degrades to an empty menu (dev preview pages don't break).

## 4. Orchestrator chat (dispatch / goals / resume)

- [ ] **QA-CHAT-01 — Freeform dispatch** — type a request → orchestrator creates a goal + task(s), replies conversationally ("Dispatched … I'll share it once ready"), and the target agent goes working. Focus-mode dims the world; user bubble + reply bubble show.
- [ ] **QA-CHAT-02 — Status query** — "what's the status?" → reply matches the board/DB (no hallucinated agents).
- [ ] **QA-CHAT-03 — Resume needs-input via chat** — a needs-input task continues when you answer in chat (same conversation, one history).
- [ ] **QA-CHAT-04 — Send failure preserves bubble** — if the POST fails, the HUD keeps your user bubble (no lost message); no crash.

## 5. Teams (Flow 3)

- [ ] **QA-TEAM-01 — Team panel** — initial avatar, inline rename, AGENTS/TOKENS tiles, agent rows → agent panel, +Add agent / Rename / Remove.
- [ ] **QA-TEAM-02 — Add teams (multi-select)** — +Team → "Add teams" modal → template cards (in-office ones dimmed/disabled). **Toggle multiple** — selected cards show ✓; CTA reflects the count ("Build 1 room" / "Build 3 rooms", disabled at 0). Confirm creates **each** selected team (sequential `POST /teams`, one per card) with its starter agent; office shows all new rooms. If one create fails mid-batch, the banner shows and already-created rooms persist (no rollback).

## 6. Agents (Flow 4)

- [ ] **QA-AGENT-01 — Agent panel** — status-tinted header, role inline-edit, tier chip, single connection chip, TOKENS/STATUS tiles.
- [ ] **QA-AGENT-02 — Add agent (role catalog + custom)** — AddAgentModal: picking a pre-defined role prefills name/tier and the **real authored base spec** into the Role-instructions box (not a placeholder) with a notice "Prefilled with the {role} base spec — edit or add your own"; a **"+ Custom role"** pill clears to a blank slate (define name + instructions yourself). TierPicker (Strong·Medium·Light); OUTPUT segment (Handoff·Loop·Final + target). Hire persists with tier + single output (agent uses exactly what's in the instructions box).
- [ ] **QA-AGENT-11 — Agent name validation** — name input is capped at **20 chars** (visible `n/20` counter, `maxLength` enforced). Server rejects (422, not 500) names that are >20 chars, blank/whitespace-only, contain control chars (newline/tab), or contain `<`/`>` (stored-XSS vector killed at the source). Same rules on rename (`AgentPatch`). Agent memory PUT (`content_md`) is byte-safe (null/surrogate → 422) and capped at 20 000 chars; empty is allowed (clear).
- [ ] **QA-AGENT-03 — Desks full at 5** — 6th hire blocked ("desks are full" banner).
- [ ] **QA-AGENT-04 — Elapsed timer** — a working/queued task shows a live "**Working · 2m 14s**" that ticks each second (#60).
- [ ] **QA-AGENT-05 — Result in-flow** — on done, the panel renders the result **markdown inline** (no extra click) + a files link. Raw HTML is neutralized (XSS-safe renderer, no `rehype-raw`).
- [ ] **QA-AGENT-06 — Stop** — a working task's "■ Stop task" terminates it (dev: kills the sandbox command) → failed+stopped.
- [ ] **QA-AGENT-07 — Provide input** — needs-input panel shows the question + a textarea → "Send & resume" continues the task (badge/toast clear).
- [ ] **QA-AGENT-08 — Retry (unhappy→recover)** — a **failed** task shows "↻ Retry task" → spawns a fresh queued task (same agent/instructions/goal); the failed one is preserved as history (#59). Non-failed → no retry button.
- [ ] **QA-AGENT-09 — Remove gated** — Remove is blocked while working/queued ("Stop the task before removing").
- [ ] **QA-AGENT-10 — Error summary** — a failed task shows its `error_summary` in the panel.

## 7. Text engine — Planning / Research  _(litellm, #61)_

- [ ] **QA-TEXT-01 — Text task completes** — dispatch a writing task to a Planning/Research agent → runs via litellm→Claude → **done** with a real markdown result + tokens recorded. **Must NOT fail with `OPENAI_API_KEY is required`** (that was the CrewAI bug, fixed in #61).
- [ ] **QA-TEXT-02 — needs-input sentinel** — a task that needs a decision surfaces `AWAITING_INPUT: <question>` → needs-input (not a hallucinated answer).
- [ ] **QA-TEXT-03 — Handoff fires** — a done text task with an outgoing edge auto-dispatches the target agent (cross-engine dev↔text works).

## 8. Dev / Design engine — E2B sandbox (Flow 4½)

- [ ] **QA-DEV-01 — Dev task builds** — dispatch a build task to a Development agent → CMA (default) runs in the E2B sandbox → implements → QA-verifies (APPROVED) → done → outputs (code tree) collected + a version cut. First task creates the sandbox; second reuses it; idle → paused (billing stops).
- [ ] **QA-DEV-02 — Design produces a screenshot** — a Design task renders the page and collects a PNG output.
- [ ] **QA-DEV-03 — Sandbox boot failure** — a sandbox that can't start → clean task failure + `error` status + refund (billing), Slack-alerted; no stuck "working".
- [ ] **QA-DEV-04 — Version snapshots** — two sequential dev tasks → v1/v2 exist; v2 manifest = v1's unchanged files + v2's changes (D50).

## 9. Live Preview & Theater (Flow 6½ — D49/D51)

- [ ] **QA-PREV-01 — Preview card** — for a runnable dev project the AgentPanel shows a Live-Preview card (LIVE dot from `preview_status`, URL row, new-tab, zip); hidden when there's no runnable target.
- [ ] **QA-PREV-02 — Theater opens the app** — Theater overlay: large iframe (cross-origin-isolated), browser-chrome bar, version chips from `/versions`, docked orchestrator chat (same store/history as main chat). Cold-open shows "starting…" then the real app (~30s on E2B). ESC restores the office exactly.
- [ ] **QA-PREV-03 — Iteration (the north-star)** — a docked-chat request ("make the button blue") dispatches a dev task against current state → on done, a new version is cut → chips advance + the **iframe refreshes without a manual reload** → chat confirms "applied — preview updated ✓ vN".
- [ ] **QA-PREV-04 — Idle pause / resume** — preview idle 10min → paused; revisiting resumes. Install failure → `error` + command tail, no task impact. URL never appears in logs.

## 10. Outputs (Flow 6)

- [ ] **QA-OUT-01 — File tree + preview** — Outputs overlay: per-task cards + file tree; per-file code/markdown **rendered** preview + image preview for design PNGs.
- [ ] **QA-OUT-02 — Download** — per-file download + **Download zip** of the tree (valid zip).

## 11. Board (Flow 7)

- [ ] **QA-BOARD-01 — Goals mirror dispatch** — a dispatched goal appears as a checklist with status icons; in-progress/failed rows deep-link (focus the agent).

## 12. Settings (Flow 8)

- [ ] **QA-SET-01 — Guardrails persist** — daily cost cap ($10–100) + concurrency (1–5) steppers + **Pause project** toggle persist and take effect (pause blocks dispatch from UI + chat).
- [ ] **QA-SET-02 — Context / memory** — context dropzone + list; per-agent memory cards view/edit/clear (persist).
- [ ] **QA-SET-03 — Delete project (danger zone)** — Settings → Project → "Delete project" → inline confirm → deletes + routes to `/app` (redirects onward). _(Was a dead button before #63.)_
- [ ] **QA-SET-04 — Delete account (GDPR, #63)** — "Delete account" → **type `DELETE` to confirm** (button disabled until exactly "DELETE") → `DELETE /api/account` wipes projects (+sandboxes)/wallet/ledger/profile/notifications, cancels any Stripe sub, deletes the Clerk user → signOut → home. **DESTRUCTIVE — only on a throwaway account.** Own-data scoped (can't touch another user).

## 13. Billing / credits (D46)

- [ ] **QA-BILL-01 — Treasury tile** — bottom-right shows the credit balance + tokens-today; "+" opens the top-up modal.
- [ ] **QA-BILL-02 — Charge on dispatch** — a dispatched task deducts its tier cost (light 10 / medium 30 / strong 300); a system failure (crash/sandbox) **refunds** (net zero).
- [ ] **QA-BILL-03 — Top-up (embedded checkout)** — top-up modal → Stripe **embedded** checkout (no redirect to checkout.stripe.com) → pay (staging card on a test deployment) → balance updates via webhook. After payment, `/billing/return` shows the confirmation then **auto-returns to `/app`** (last project) within ~2.5s; the "워크스페이스로" button also points to `/app` (never the marketing landing `/`).
- [ ] **QA-BILL-04 — Paywall** — insufficient credits → task blocked (`insufficient_credits`) + SSE `paywall` auto-opens the billing modal (D46).
- [ ] **QA-BILL-05 — Customer portal (cancel)** — a "Manage billing / cancel" path opens the Stripe Customer Portal (CA ARL — click-to-cancel).
- [ ] **QA-BILL-06 — Webhook idempotency** — a duplicated Stripe event does not double-credit (`credit_ledger.stripe_ref` unique index; IntegrityError treated as already-processed).

## 14. Notifications

- [ ] **QA-NOTIF-01 — Bell + feed + toast** — done/blocked/needs-input/failed each push a notification (bell unread count, Activity feed row, top-center toast). Clicking any **focuses** the right agent (opens its panel). Mark-all-read works.

## 15. Landing + blog (marketing / SEO)

- [ ] **QA-SEO-01 — SSG landing** — `curl https://pondas.ai/` returns full HTML sans JS; metadata/OG/canonical present. `robots.txt` disallows `/app`,`/onboarding`,`/billing`,`/api`,`/*-preview`; AI crawlers allowed. `sitemap.xml` valid.
- [ ] **QA-SEO-02 — Blog** — `curl /blog/<slug>` returns full HTML; Article JSON-LD validates; post in sitemap. No Pixi in marketing chunks.

## 16. Security / unhappy / edge

- [ ] **QA-SEC-01 — Tenant isolation** — every read is user-scoped: another user's project/map/task/account op → **404**, never data leak. `DELETE /api/account` only touches your own rows.
- [ ] **QA-SEC-02 — Input sanitization** — null byte / lone surrogate in any user string → 422, not 500 (ABUSE-BUG-1/2).
- [ ] **QA-SEC-03 — Rate limiting** — abusive request rate is throttled (slowapi; keyed by real client IP via XFF, Redis-backed).
- [ ] **QA-SEC-04 — Stored-XSS dead** — a task result / agent field containing `<script>` renders inert (react-markdown without `rehype-raw`); the ADVERSARIAL_TEST_RESULTS.md corpus stays dead.
- [ ] **QA-SEC-05 — LLM request timeout** — a hung provider call is killed by `llm_request_timeout` + `num_retries` (doesn't pin a Celery worker forever).
- [ ] **QA-EDGE-01 — Insufficient credits mid-flow** — see QA-BILL-04.
- [ ] **QA-EDGE-02 — Stop mid-execution** — see QA-AGENT-06; suppresses propagation, no orphan.
- [ ] **QA-EDGE-03 — Task loss on Redis restart** — a queued (not yet picked) task survives a broker restart (Redis AOF on — infra; plus the queued-task reaper re-enqueues stragglers). _(See Known issues if AOF not yet on.)_

---

## Known issues / backlog (track, don't fail E2E on these)

- **Prod hardening (mostly P2):** Redis AOF persistence (queued-task-loss vector on restart — **Railway dashboard toggle**); DB pool sizing vs Railway max (verify); `alembic upgrade head` runs on every web boot (no migration canary — a bad migration blocks all web start); map/board N+1 not deep-measured under load; Vercel cold-start TTFB ~1.75s (mitigate with SSG/ISR).
- **Legal:** ToS/Privacy/Refund are drafts (attorney review pending); click-to-cancel is via the Stripe portal (verify it's prominent).
- **Growth:** SEO tech foundations done (robots/sitemap/OG/JSON-LD); remaining is content + GEO. Blog automation scope TBD.
- **Phase 2 item 34:** full Playwright signup→onboarding→dev-task→theater→iteration→credits→paywall automation not yet scripted (this runbook is the manual source of truth for it).
- **Founder's prod account** carries a test project **"Bean There Café"** (created during verification) — delete via the switcher if unwanted.
