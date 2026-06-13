# Technical Design v3 — Office-Sim Multi-Agent Orchestration Platform

> Updated 2026-06-12 from `decision-log.md` D1–D32 and PRD v2 (user-authorized direct update; supersedes the v2 design of 2026-06-11).
> Source of truth: `specs/prd.md` + `decision-log.md`. Companion: `specs/user-flows.md`.
> v3 delta: execution-included MVP (D28–D31), dual engines (D30), E2B sandboxes (D29), Postgres FileStore (D27), per-agent model tiers (D32).

---

## 1. Summary

A web application that renders AI agent teams as office zones on a Two Point Hospital-style WebGL map. A single user owns isolated **projects**; each project contains team/agent **instances** cloned from system **templates**, a user-drawn **agent graph** (handoff + review-loop edges, cross-team), a per-project **orchestrator** chat, and — new in v3 — a per-project **execution workspace** where the Development team writes, runs, and tests real code.

**Build structure (D28): two tracks, joined at the end.**
- **Track 1 — the app:** schema/projects/graph/orchestrator/map/panels/board/landing. Knows nothing about execution beyond the `WorkspaceService` interface.
- **Track 2 — the execution engine:** `SandboxProvider` (E2B) + `WorkspaceService` + the Agent SDK dev-runner + the verification toolchain. Developed and tested headless (API-level), no UI required.

**Stack:** Next.js on Vercel (SSG landing + CSR app, Pixi.js). FastAPI + Celery on Railway. PostgreSQL = system of record (including files, via `FileStore` — D27). Redis = broker + pub/sub. **E2B** = per-project sandboxes (D29). Clerk auth. Claude only, via one provider-neutral LiteLLM layer with **per-agent model tiers** (D26, D32).

**Two execution engines (D30):**
- **Text teams** (Planning/Research/Design/Data) → CrewAI runs (the validated CrewRunner core).
- **Development team** → **Claude Agent SDK** sessions inside the project sandbox (bash/file tool loop, battle-tested, prompt caching built in). LLM-written code **never executes on the product backend**.

**Core invariants (unchanged):** `tasks.status` in Postgres is the single source of truth — every transition persists then publishes (Redis→SSE); animations/"!"/feed/board derive strictly from it. Edges always auto-fire (D21); review loops ride the re-enqueue continuation mechanism (no in-process pause/resume). Brakes are P0: Stop, project pause, chain budget, daily cost cap (D16).

---

## 2. Requirements Covered

| PRD v2 P0 | Section here |
|---|---|
| 1 Auth & start screen | §11, §6 |
| 2 Projects | §5, §6 |
| 3 Template→instance teams | §5, §7 |
| 4–5 Team/agent management (incl. tier) | §5, §6 |
| 6 Agent graph ⭐ | §8 |
| 7 Orchestrator | §9 |
| 8 Task status model | §13 |
| 9 Animation + "!" | §12, §13 |
| 10 Event feed | §6, §13 |
| 11 Notifications + continuation | §6, §14 |
| 12 Board | §5 (goals), §6 |
| 13 Token & cost tracking (per-model pricing) | §5, §6, §7 |
| 14 Outputs (file trees, zip, preview) | §5, §6 |
| 15 Context & memory | §5, §6, §7 |
| 16 Dual engines + LiteLLM | §7 |
| 17 Stop & pause | §8, §10, §13 |
| 18 Landing + SEO/GEO | §17 |
| 19 Execution workspace ⭐ | §10 |
| 20 Model tiers | §5, §7 |
| 21 Admin MDX blog | §17, §12 |

---

## 3. Non-Functional Requirements

**Performance** — Map ~60fps at MVP scale (≤8 zones, ≤~30 agents); API reads p95 < 300ms; SSE delivery < 1s; landing LCP < 2.5s, zero Pixi in landing bundle. Dev tasks are **minutes-long** (5–30 min normal): no HTTP request ever waits on one — all execution is Celery-async with status/SSE progress; per-task wall-clock timeout (config, default 30 min) enforced by the runner.

**Security** — §16. Headline: user+project ownership scoping on every query; LLM code only in E2B microVM isolation; no secrets inside sandboxes; registry-allowlist egress.

**Reliability** — Durable task state + reaper; idempotent jobs on `(task_id, attempt)`; transactional edge propagation with `(parent_task_id, edge_id)` dedup; SSE reconnect→reconcile; workspace state survives worker crashes (sandbox is independent of workers; reaper marks the task failed, workspace remains recoverable).

**Maintainability** — transitions centralized in `TaskService`; propagation centralized in `GraphEngine`; execution behind `WorkspaceService`/`SandboxProvider` interfaces (Track-2 isolation, provider swap, S3 FileStore swap at P1); templates and tier/pricing maps are data, not code.

**Observability** — structured JSON logs keyed by `task_id`/`project_id`/`goal_id`/`agent_id`/`attempt`/`engine`; every transition logs old→new; every edge fire logs `(parent, edge, child)`; dev tasks log every executed command + exit code (the verification record); tokens/cost per attempt with per-model pricing (D32); `/health`, `/ready`.

---

## 4. Architecture Overview

```
                ┌─────────────────────────── Vercel ───────────────────────────┐
   Crawlers ───▶│  /            landing (SSG: meta/OG/JSON-LD/sitemap/llms.txt) │
   Browser  ◀──▶│  /app/**      auth-gated app (CSR): Pixi map + HUD            │
                └────────────────────────────────────────────────────────────────┘
                       │ REST (Clerk JWT)                ▲ SSE (events)
                       ▼                                 │
   ┌──────────────────────────────────── Railway ─────────────────────────────────────┐
   │  FastAPI (stateless)                                                               │
   │   - REST: projects/templates/teams/agents/edges/tasks/chat/board/files/context/    │
   │           memory/usage/notifications      - SSE per-project channel                │
   │   - OrchestratorService (LiteLLM tool-loop)                                        │
   │   - TaskService (transitions+gates)  - GraphEngine (propagation)                   │
   │        │                          │ enqueue                ▲ pub/sub               │
   │        ▼                          ▼                        │                       │
   │   ┌─────────────┐         ┌──────────────────────┐   ┌─────────────┐               │
   │   │ PostgreSQL  │◀──r/w──│ Celery worker          │──▶│    Redis    │               │
   │   │ truth + ────│         │  text task → CrewAI    │   │ broker+pub  │               │
   │   │ FileStore   │         │  dev task  → AgentSDK ─┼─┐ └─────────────┘               │
   │   │ (D27)       │         │  (engine router)       │ │                               │
   │   └─────────────┘         └──────────┬─────────────┘ │ WorkspaceService              │
   │                                      │ LiteLLM       ▼ (exec/file/tree)              │
   │                                      ▼          ┌──────────────────────┐             │
   │                               Claude API        │  E2B sandbox (per    │             │
   │                          (tiered: opus/sonnet/  │  project, paused     │             │
   │                           haiku via config)     │  between tasks) D29  │             │
   │                                                 │  - workspace files   │             │
   │                                                 │  - npm/pip allowlist │             │
   │                                                 │  - dev server +      │             │
   │                                                 │    headless Playwright│            │
   │                                                 └──────────────────────┘             │
   └────────────────────────────────────────────────────────────────────────────────────┘
```

**Lifecycle — text task:** chat → orchestrator creates goal+tasks → gates → worker runs CrewAI → result_markdown + output file (FileStore) → tokens/cost → GraphEngine propagates → SSE.

**Lifecycle — dev task (new):** dispatch → worker resolves engine by team type → `WorkspaceService.ensure_running(project)` (create-or-resume sandbox) → **Agent SDK session in the sandbox** (write/exec/test loop; per-command logs collected) → on terminal: collect changed file tree → outputs rows (FileStore) + verification record on the task → tokens/cost → pause sandbox if no queued dev task → GraphEngine propagates → SSE. Same status machine, same events, same map UX — the engine difference is invisible above `run_task`.

---

## 5. Data Model

PostgreSQL. Every user-owned row carries `user_id`; everything below `projects` carries `project_id`; all queries scoped to both.

**`user_profiles`** — `user_id` pk, `display_name`, timestamps.

**`projects`** — `id`, `user_id` idx, `name`, `paused` bool (D16), **`sandbox_id` text null, `sandbox_status` (`none|running|paused|error`)** (D29), timestamps. Delete cascades subtree + destroys sandbox.

**Templates (seed, read-only):** `team_templates` (`key`: planning|research|design|development|data, `name`, `description`, **`engine`** (`crew`|`agent_sdk`) — development=agent_sdk, rest=crew); `agent_templates` (+ `role_instructions`, **`default_tier`** (`strong|medium|light`, D32), pos); `edge_templates` (default wiring, e.g. SWE↔QA review loop, SWE→Code Reviewer handoff).

**`teams`** — `id`, `project_id` idx, `template_key`, `name`, pos, timestamps. Engine derives from template_key (custom teams added from a template inherit it).

**`agents`** — `id`, `team_id`, `project_id` idx, `name`, `role_instructions` (user-editable), **`model_tier`** (`strong|medium|light`, default from template, user-editable — D32), pos, timestamps. Unique `(team_id, name)`.

**`edges`** (D6, D19, D25) — `from_agent_id`, `to_agent_id`, `type` (`handoff|review_loop`), `max_iterations` (1–10, review_loop only). No self-edges; unique `(from,to,type)`; **handoff subgraph must stay a DAG** — DFS check on insert; loops only as review_loop.

**`goals`** (D20) — `id`, `project_id` idx, `title`, `created_at`. Board = goals × tasks.

**`tasks`** — v2 columns retained: scoping (`user_id/project_id/agent_id/goal_id`), `origin` (`chat|edge|panel`), provenance (`parent_task_id/edge_id`), `loop_state` jsonb, `override_route` jsonb (D21), `status` (7-state), `instructions`, `input_payload`, `continuations` jsonb (`via: panel|chat`), `result_markdown`, `awaiting_prompt`, `error_summary`, `attempt`, `tokens_in/out`, `est_cost_usd`, timestamps. **New:** `engine` (`crew|agent_sdk`, denormalized at creation), **`model_used`** text (actual model id for pricing, D32), **`verification` jsonb null** (dev tasks: `[{cmd, exit_code, summary}]` — the "working as expected" record, D31).
Indexes: `(project_id,status)`, `(agent_id,status)`, `(goal_id)`, `(user_id,created_at desc)`; unique partial `(parent_task_id,edge_id)`.

**`outputs`** (D4, D18, D27, D31) — `id`, `project_id` idx, `agent_id`, `task_id` idx, **`path`** text (relative path → one row per file; a dev task yields a tree of rows), `mime`, `size_bytes`, **`content`** (text for text/code; bytea for the rare binary), `created_at`. Per-task zip generated on demand from rows. Stored via the **`FileStore`** interface (`PostgresFileStore` now; `S3FileStore` P1 — D27).

**`context_files`** (D14) — `filename`, `content` (original, via FileStore), `extracted_text`, `size_bytes`. MVP extraction: txt/md as-is, PDF text-extracted; others rejected.

**`agent_memories`** (D14) — `agent_id` pk, `content_md`, `updated_at`.

**`orchestrator_messages`** — `project_id` idx, `role`, `content`, `created_at`.

**`notifications`** — + `project_id`, `agent_id`. Index `(user_id, read, created_at desc)`.

**`config`** — key/value, read at dispatch: `concurrency_cap=3`, `daily_cost_cap_usd`, `goal_chain_budget=25`, `context_token_budget`, **`tier_models`** (`{strong: claude-opus-4-8, medium: claude-sonnet-4-6, light: claude-haiku-4-5}`), **`model_pricing`** (per-model $/MTok in+out, incl. cache-read rate), **`dev_task_timeout_min=30`**, **`sandbox_idle_pause_sec`**.

**Token/cost aggregation (D12, D32):** SUM over `tasks` by project/team/agent; cost computed at write time from `model_used` × `model_pricing`. Live counter via SSE `usage` deltas.

**Migration from v1:** `clusters`/`units` dropped (dev-only seed, no prod data). `seed.py` v3 seeds 5 team templates + rosters (Development: Architect/SWE/QA/Code Reviewer/DevOps with default tiers per D32) + default edges + config maps.

---

## 6. API Contract

Base `/api`; Clerk JWT everywhere except `/health`,`/ready`; ownership-checked; cross-user → 404.

**Projects & templates** — `GET /templates`; `POST /projects` `{name, template_keys[], display_name?}` (transactional clone); `GET/PATCH/DELETE /projects/{id}`; `POST /projects/{id}/pause|resume` (D16; pause also blocks workspace dispatch).

**Map & inspection** — `GET /projects/{id}/map` → `{teams, agents(+status, +tier, +"!" flags), edges, paused}`; `GET /agents/{id}` (role, tier, edges, current task incl. `awaiting_prompt`/`error_summary`/`verification`, token totals); `GET /teams/{id}` (D15 payload).

**Management** — teams add/rename/remove; `POST /teams/{id}/agents` `{name, role_instructions, model_tier, edges[]}` (one-modal, D1/D32); `PATCH /agents/{id}` `{name?, role_instructions?, model_tier?}`; `DELETE /agents/{id}` (cancel tasks, drop edges); `POST /projects/{id}/edges` / `DELETE /edges/{id}` (DAG validation, D25).

**Orchestrator (D3/D21/D22)** — `POST /projects/{id}/chat` `{message}` → `{reply, actions[]}` (sync, <10s; dispatch async behind it); `GET /chat/history`.

**Tasks** — `GET /tasks/{id}` (full detail incl. continuations, provenance, verification); `POST /tasks/{id}/continue` (from blocked/needs-input; panel path); `POST /tasks/{id}/stop` (D16 — dequeues queued / revokes working **and kills the running sandbox command** for dev tasks; suppresses propagation).

**Board (D20)** — `GET /projects/{id}/board` → goals × items with statuses.

**Files (D27/D18/D31)** — `GET /projects/{id}/outputs` (grouped by task; file-tree entries); `GET /outputs/{id}/preview` (text/md/code); `GET /outputs/{id}/download`; **`GET /tasks/{id}/outputs.zip`** (tree as zip). Context upload/list/delete; memory GET/PUT/DELETE.

**Usage (D12/D32)** — `GET /projects/{id}/usage` → totals + by_team/by_agent + `active_tasks/cap/daily_cost_remaining` (cost from per-model pricing).

**Notifications & SSE** — list/read; `GET /projects/{id}/sse` (`task_status`, `notification`, `usage` events + heartbeats every ~20s). SSE chosen over WebSocket: traffic is one-directional server→client (commands go over REST), SSE is simpler, proxy-friendly, and auto-reconnects natively; the client treats events as lossy hints and reconciles against the DB on reconnect.

**System** — `/health`; `/ready` (DB + Redis + E2B API reachability).

---

## 7. Engines, Prompt Assembly & Model Tiers

**Engine routing (D30):** `run_task` resolves `task.engine` from the agent's team template — `crew` → CrewAI runner (validated CrewRunner core from the spike; dynamic Agent factory from DB rows), `agent_sdk` → dev-runner in the sandbox (§10). Everything above (TaskService, GraphEngine, SSE, board) is engine-agnostic.

**Model tier resolution (D32):** `agents.model_tier` → `config.tier_models` → model id, passed to CrewAI (per-agent model string), to the Agent SDK session (model param), and recorded on `tasks.model_used`. Orchestrator = strong; memory append = light (D14). All calls route through LiteLLM (CrewAI internally; orchestrator + memory directly — D26), so future provider/model changes are config.

**Prompt assembly (shared by both engines):**
1. `role_instructions` → 2. project context (extracted text within `context_token_budget`, oldest-first truncation, logged) → 3. agent memory → 4. `input_payload` + provenance line (edge-fired) → 5. prior output + reviewer feedback (loop revision rounds) → 6. `instructions`. Dev-runner additionally injects workspace conventions (§10).

**Sentinels (spike-validated, engine-agnostic):** `AWAITING_INPUT: <question>` → `needs-input` + `awaiting_prompt`; `APPROVED` (reviewers) → loop early-exit (D19). The dev-runner enforces the same contract via its system prompt.

**Outputs:** text tasks → `result_markdown` + one FileStore file. Dev tasks → `result_markdown` (summary) + changed-file tree collected from the workspace (§10) + `verification` record.

**Memory append:** post-`done`, bounded light-tier LLM call (~200 tok out) appends 3–5 bullets to `agent_memories`; failure never fails the task.

---

## 8. Graph Engine (D6, D19, D21, D16, D17, D25)

Single propagation path, transactional with the parent's terminal transition, **engine-agnostic** (a dev task's handoff can feed a text task and vice versa — input_payload carries `result_markdown`; downstream dev tasks also see the shared workspace).

```
on task T (agent A) → done:
  if project.paused: skip
  if T.loop_state: → review-loop protocol
  if T.override_route: dispatch to override target; skip A's edges (consumed)   # D21
  else for each edge from A:
     handoff: child task (origin=edge, input=T.result, goal inherited)
     review_loop: reviewer task, loop_state{edge, iter:1}
  guard: goal task count > chain budget → halt + notify
```
- Dedup: unique `(parent_task_id, edge_id)`; failed/stopped tasks never propagate.
- **Review loop:** producer→reviewer; `APPROVED` → loop closed, producer's handoffs fire; else revision round until max N; N exhausted → "not approved within N rounds" notification + board flag, downstream does NOT auto-fire (user decides via chat). For dev loops, "reviewer" = QA actually running the app (§10) — `APPROVED` means verified behavior, per D31's success criterion.
- **Busy agents (D17):** one running task per agent; per-agent FIFO; global cap on top.
- **Stop (D16):** terminal `failed(stopped)` + propagation suppressed + sandbox command killed (dev).

---

## 9. Orchestrator Service (D3, D21, D22, D26)

LiteLLM-based tool-loop (provider-neutral; Claude strong-tier via config; Anthropic prompt caching through passthrough — project snapshot + history ride every message). Tools: `create_goal`, `dispatch_task(agent_id, instructions, goal_id, override_route?)`, `get_project_status` (DB-read, never from memory), `resume_task(task_id, input)` (chat relay, D22 — recorded `via: chat`), `list_outputs`. Behavior contract: always state what was dispatched; decompose multi-part instructions into one goal + tasks; route by reading `role_instructions`; if no suitable agent, say so and suggest adding one. Orchestrator usage billed into project totals.

---

## 10. Execution Engine (Track 2 — D28–D31) ⭐

The self-contained module. Interface boundary:

```
SandboxProvider (E2B impl; adapter-swappable)
  create(project_id, runtime_image) → sandbox_id     pause(id) / resume(id) / destroy(id)
  exec(id, cmd, timeout, env) → {exit_code, stdout, stderr}
  read_file/write_file(id, path)                      file_tree(id, path) → entries(+mtime)

WorkspaceService (the only thing Track 1 sees)
  ensure_running(project) → workspace handle          pause_if_idle(project)
  run_dev_task(task) → RunOutcome                     collect_outputs(task) → file rows
  kill_current(task)                                  destroy(project)
```

**Lifecycle (D29):** sandbox created lazily on the project's first dev task (image: Node 22 + Python 3.12 + Playwright preinstalled); **paused** when no dev task is queued (billing stops, filesystem preserved); resumed in seconds on the next task; destroyed with the project. One sandbox per project = the workspace IS the repo state shared across SWE/QA/debug tasks — no context reconstruction needed for code (the handoff payload carries intent; the workspace carries truth).

**Dev-runner (Agent SDK, D30):** each dev task = a **fresh Claude Agent SDK session** executing inside the sandbox against the persistent workspace (re-enqueue philosophy preserved — crash-safe, no held processes). Session config: model from tier (D32), bash/file tools scoped to the workspace, per-command and per-task timeouts, system prompt = shared assembly (§7) + workspace conventions (project layout, "verify by running — build success is not success", sentinel contract, output discipline). Token usage captured per session onto the task.

**Verification toolchain (D31):** dev server started inside the sandbox (`npm run dev` etc., port known); **headless Playwright** in the same sandbox exercises real flows; QA-role sessions are instructed to verify behavior and emit `APPROVED` only on working-as-expected. Every executed command + exit code is appended to `tasks.verification` — the user-visible proof trail.

**Output collection:** after a terminal state, `file_tree` mtime-diff (vs. task start) → changed files → `outputs` rows via FileStore (node_modules/, .next/, venv/ etc. excluded by ignore rules) → zip on demand.

**Constraints (D31):** runtimes Node/Next.js + Python only; egress = package-registry allowlist (npm/pypi + lockfile hosts); no deploy — DevOps agent writes configs (vercel.json/Dockerfile/README-deploy) as ordinary outputs.

**Failure modes:** command hang → exec timeout → runner retries-or-fails per attempt policy; task wall-clock timeout (default 30 min) → `failed` + verification record so far; sandbox boot/resume failure → task `failed` with clear `error_summary`, sandbox_status=`error`, retry path recreates; E2B outage → dev dispatch refused with in-app explanation (text teams unaffected). Worker crash mid-dev-task → reaper fails the task; workspace untouched (next task continues from real state).

**Cost (D29):** tokens dominate (~95%+); sandbox ≈ $0.10/hr (2 vCPU), pause between tasks ⇒ negligible. Sandbox runtime minutes logged per task for visibility.

---

## 11. Auth, Tenancy & Onboarding

Clerk JWT verification (existing `app/auth.py` — JWKS from publishable key, RS256, `?token=` for SSE) kept as-is. `TenantScope` v3: user → owned projects; every repository call requires explicit project scope; cross-tenant → 404. Onboarding (Flow 0): display name / project name / template keys / context files → `POST /projects`; returning users → latest project.

---

## 12. Frontend Plan

```
frontend/
  app/(marketing)/page.tsx + llms.txt/robots/sitemap/og   # SSG, zero Pixi (D24)
  app/(marketing)/blog/page.tsx + blog/[slug]/page.tsx     # admin MDX blog, SSG (D33)
  content/blog/*.mdx                                       # founder-authored posts (frontmatter + body)
  app/app/start/page.tsx                                  # Flow 0 wizard
  app/app/[projectId]/page.tsx                            # the office (CSR)
  components/
    map/   MapCanvas, TeamZone(signage), AgentSprite(7-state anims),
           IndicatorOverlay("!"/failed — same statusAnim source)
    hud/   ProjectSwitcher, EventFeed, OrchestratorChat, TokenCounter,
           UtilityButtons(Settings/Board/Actions), Toast
    panels/ TeamPanel, AgentPanel(role/tier/edges/status/usage/verification,
            ProvideInput-when-blocked, Stop-when-running)
    overlays/ BoardOverlay, SettingsOverlay(Context/Memory/Guardrails+Pause),
              OutputsList(task-grouped, FileTree expand, MarkdownPreview, ZipDownload)
    modals/ AddAgentModal(name/role/TierPicker/edge picker w/ type+N), AddTeamModal, Confirm
  lib/ api.ts, sse.ts(reconnect+reconcile), statusAnim.ts(sole status→visual map), store.ts
```
- **Rendering (D34): 2.5D isometric 2D in Pixi** — fixed-angle camera, pan/zoom only (no rotation). Zones = iso floor tiles + low partitions; characters = sprite sheets (6 status looks + badge overlays), 1–2 facings (mirrorable) since the camera never rotates. No 3D engine.
- `statusAnim.ts` remains the only status→visual mapping (animations + overhead indicators).
- Event feed = client ring buffer (~200 lines) of `task_status` events.
- Reconnect → re-fetch `/map` + `/usage`.
- Pixi dynamically imported only in `[projectId]`; CI bundle check (D24).
- Dev tasks look identical on the map — only the agent panel shows extra detail (verification record link).

---

## 13. State Management

**Task machine (unchanged):** `queued→working→{done|failed|blocked|needs-input}`; `{blocked|needs-input}→queued` (continue); `{queued|working}→failed` (stop); done/failed terminal (retry P1). `idle` = API-derived. Illegal writes rejected+logged.

**Dispatch gates (atomic, in order):** ① project not paused ② agent not busy (D17) ③ user concurrency < cap ④ daily cost cap ⑤ goal chain budget. Dev tasks additionally require workspace ensure_running success (failure → task `failed`, not stuck).

**Client:** `Map<agentId,status>` from `/map` + SSE; board/feed/usage from same events; UI state never touches task state.

---

## 14. Continuation & Loops

No in-process pause/resume anywhere. Text tasks: re-enqueue with reconstructed context (instructions + continuations + partial output) — spike-validated. Dev tasks: re-enqueue starts a fresh Agent SDK session; **the workspace carries the concrete state**, the prompt carries the question/answer + accumulated continuations — strictly easier than the text case. Review-loop rounds are fresh tasks in both engines.

---

## 15. Error Handling & Recovery

Claude failure/timeout → bounded in-attempt retries → `failed` + summary + partial tokens + notification. Worker crash → reaper (stale `updated_at` heartbeat) → `failed`, never silently stuck; propagation never half-fired (transactional). Idempotency `(task_id, attempt)` + pre-state check. Gate races under one `SELECT...FOR UPDATE`. SSE drop → reconcile. Stale commands → 409. Context extraction failure → reject upload with reason. FileStore write failure on outputs → task still completes (`result_markdown` safe), rows deferred-retried. Orchestrator tool-loop failure → error reply, no partial dispatch without a goal. Sandbox failure modes → §10.

---

## 16. Security

- **Code isolation (the big one, D29/D30):** LLM-written code executes only inside E2B Firecracker microVMs — never on the product backend. Sandboxes hold **no secrets** (no Claude key, no DB URL — the Agent SDK loop runs API calls from our worker side, only tool execution happens in the sandbox); egress limited to package registries (D31).
- **AuthN/Z:** Clerk JWT; strict user+project scoping; 404 on miss.
- **Untrusted data:** user instructions, uploaded context, agent outputs crossing edges, and **code/file contents returning from sandboxes** are data, never directives; markdown/code rendered sanitized (no raw HTML) — blocks stored-XSS. Prompt-injection via context: residual, bounded by no-MCP; hardening P1.
- **Uploads:** type allowlist (txt/md/pdf), size caps, served from FileStore with auth (no public URLs needed in MVP).
- **Cost defense in depth:** concurrency cap, daily cap, chain budget, loop max-N, per-task timeouts, Stop/pause, tier defaults (D32).
- **CORS:** Vercel origins only.

---

## 17. Landing, SEO & GEO (D24)

**Architecture split.** The public marketing surface and the app are one Next.js codebase with two route groups that render differently:
- `(marketing)` — `/` and future public routes. **Static generation at build time (SSG)**: the full product-intro content exists in the HTML with zero JavaScript required — crawler-complete by construction. No Clerk, no Pixi, no API calls.
- `app/**` — the auth-gated office (CSR behind Clerk). Deliberately **not indexed**: `noindex` meta on all app routes + disallowed in robots. There is nothing for a crawler behind auth, and indexing app shells produces junk results.

**SEO package (MVP):**
- **Metadata** per route via the Next.js Metadata API: unique `title`/`description`, `canonical` URL, Open Graph + Twitter Card tags with a generated OG image (the share-card is many users' first impression).
- **`sitemap.xml` + `robots.txt`** generated via Next.js file conventions (`sitemap.ts` / `robots.ts`) — marketing routes listed, app routes disallowed.
- **Structured data:** JSON-LD `SoftwareApplication` (name, description, applicationCategory, offers) inlined in the landing HTML so rich results are possible.
- **Semantic HTML:** proper landmark structure (`header/main/section/footer`), one `h1`, descriptive heading hierarchy — this doubles as GEO substrate (see below).
- **Core Web Vitals:** LCP < 2.5s on the landing. Enforced by design: zero Pixi/canvas chunks in marketing routes (dynamic import boundary + **CI bundle-analysis assertion**), `next/image` for all landing imagery, fonts self-hosted/preloaded.
- **Post-launch ops:** submit sitemap to Google Search Console; monitor indexing + CWV there (ops task, not code).

**GEO package (MVP)** — being findable and citable by AI search (ChatGPT/Perplexity/Google AI Overviews):
- **`llms.txt`** at the domain root: a concise, plain-language description of what the product is, who it's for, what's different, and links to key pages — written for machine consumption.
- **AI crawler access:** `robots.txt` explicitly allows `GPTBot`, `ClaudeBot`, `PerplexityBot`, `Google-Extended` on marketing routes (same disallow for app routes).
- **Citation-friendly copy structure:** landing copy written as direct, self-contained answer sentences under stable headings ("What is X", "Who is it for", "How is it different") — generative engines lift and cite clear declarative claims, not marketing fluff. This is a copywriting constraint, enforced at content-review time.

**Admin-only blog / newsroom (D33) — P0, MDX-in-repo:**
- **Authoring model:** the founder writes posts as **MDX/markdown files committed to the repo** (e.g. `content/blog/*.mdx` with frontmatter: `title`, `description`, `date`, `slug`, optional `ogImage`). A git commit triggers a Vercel rebuild and the post goes live. **No admin UI, no admin auth, no database, no CMS** — this is the deliberate simplification (the author is technical; static files maximize SEO and eliminate a whole auth/DB surface).
- **Routes (both SSG/SSG-with-generateStaticParams, in the `(marketing)` group):**
  - `/blog` — index: list of posts (title, summary, date), newest first, built from the MDX file set at build time.
  - `/blog/[slug]` — one static page per MDX file; markdown rendered to HTML (code blocks, images via `next/image`).
- **Per-post SEO/GEO:** each post page emits its own `title`/`description`/`canonical` + Open Graph/Twitter tags from frontmatter, and **`Article` JSON-LD** (`headline`, `datePublished`, `author`, `description`) — a strong citation signal for generative engines. Posts are auto-added to `sitemap.xml` (the `sitemap.ts` enumerates the MDX file set) and the blog index is linked from `llms.txt`.
- **No Pixi, no app coupling** — same static, crawler-complete profile as the landing; same CWV budget.
- **P1 (deferred):** tags/categories, RSS feed, blog search, FAQ/HowTo structured data. Writing posts is ongoing content work, not a build dependency.

**Verification gates (CI / item 19):** `curl /` and `curl /blog/<slug>` return full content without JS; `sitemap.xml` (incl. blog posts) / `robots.txt` / `llms.txt` served; SoftwareApplication + per-post Article JSON-LD validate; Lighthouse ≥ 90 on both Performance and SEO; bundle assertion proves no Pixi in marketing chunks.

---

## 18. Test Strategy

**Track 1 backend:** TaskService transition table + 5 gates (incl. pause/busy/budget) under parallel dispatch; idempotency; GraphEngine full matrix (handoff fire, override consumption, loop approve/exhaust/blocked, dedup, DAG rejection); ownership scoping 404s; template cloning atomicity; board/usage projections; SSE emission; tier resolution + pricing math.
**Track 2 (headless, no UI):** SandboxProvider contract tests (create/exec/pause/resume/tree) against real E2B; WorkspaceService lifecycle (lazy create, pause-if-idle, crash recovery); dev-runner with scripted SDK responses (sentinel compliance, timeout kill, token capture); output collection ignore-rules; **golden-path live test: "build a 1-page Next.js app + verify with Playwright" runs end-to-end in a real sandbox**.
**Cross-engine integration:** dev→text and text→dev handoffs; SWE↔QA loop with real execution + APPROVED; stop kills sandbox cmd; pause blocks dev dispatch.
**Frontend:** statusAnim totality; reconnect reconcile; panel action visibility; tier picker persistence; outputs tree/zip; landing bundle/SEO assertions.
**E2E (Playwright):** landing → sign-in → onboarding → chat dispatch → text teams produce docs → dev team builds + QA-verifies a mini-app in the sandbox → handoff auto-fires → board/outputs(zip)/usage correct → continuation both paths → stop + pause.

---

## 19. Deployment

- **Vercel:** landing SSG + app. Env: Clerk publishable key, API base.
- **Railway:** FastAPI web, Celery worker, Celery beat (reaper). Managed Postgres + Redis. Env adds `E2B_API_KEY`, tier/pricing config. No object storage, no MinIO (D27).
- **E2B:** account + API key; two runtime templates (node, python) defined as E2B custom images; sandbox lifecycle fully API-driven.
- Migrations on deploy; `seed.py` v3 idempotent. Config (caps/budgets/tiers/pricing/timeouts) changeable without redeploy. devops_engineer deploys only with explicit user approval (harness rule).

---

## 20. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Graph→execution bugs (core mechanic) | 2 edge types (D19), handoff DAG (D25), single GraphEngine path + heavy tests, chain budget + dedup backstops. |
| **Dev-loop quality/flakiness** (co-top) | Battle-tested Agent SDK loop (D30); verification record makes failures inspectable; per-command/task timeouts; reaper; workspace survives crashes; Track-2 golden-path test in CI. |
| Sandbox security | E2B microVM isolation; no secrets in sandbox; registry-only egress; LLM code never on backend. |
| Reviewer rubber-stamps / never approves | Bounded N + unapproved report → human; QA prompt defines APPROVED = verified-by-running (D31); template tuning. |
| Runaway cost | 5-gate dispatch, daily cap (raise to $50–100 on dev days), chain budget, loop bounds, timeouts, Stop/pause, tiers (−25~40%), live counter. |
| Orchestrator misroutes | Tool-based auditable actions; states what it did; DB-read status; chat override. |
| Animation/indicator desync | Single statusAnim source; DB-status-only; reconcile on reconnect. |
| Long dev tasks vs. UX expectations | Notification-based by design; event feed + working animation + board progress; verification record on completion. |
| E2B dependency/outage | SandboxProvider adapter (swap path); text teams unaffected; clear refusal messaging. |
| Template content quality | Templates are data → hot-fixable; dedicated tuning time (PRD risk); dev-team prompts iterate against the golden-path test. |

---

## 21. Explicit Non-Goals / Avoid Over-Engineering

- No WebSockets; no token streaming; no microservices; no read-cache layer (unchanged).
- **No object storage in MVP** — Postgres FileStore behind an interface; S3 swap is a P1 task, not a maybe (D27).
- **No third engine** — CrewAI for text, Agent SDK for dev, LiteLLM tool-loop for orchestrator. Nothing else (D30/D26).
- **No arbitrary runtimes/deploy/MCP in the sandbox** — Node+Python, registry allowlist, configs-only deploy (D31).
- **No raw model selection UI** — tiers only; tier→model and pricing are config (D32).
- **No arbitrary graph semantics** — handoff (DAG) + bounded review loop, nothing else (D19/D25).
- No separate board entity (projection of goals+tasks, D20); no in-product file management (list/preview/zip only, D4/D18); no RAG (D14); no in-process pause/resume anywhere (§14).
- Keep the 7-state machine exactly; engine/loop bookkeeping in columns, not new statuses.
