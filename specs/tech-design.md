# Technical Design v3 — Office-Sim Multi-Agent Orchestration Platform

> Updated 2026-06-13 from `decision-log.md` D1–D44 and PRD v2 (user-authorized direct update; supersedes the v2 design of 2026-06-11). Visuals/interactions: `claude-design-handoff/product/README.md` is the single source of truth (D36).
> Source of truth: `specs/prd.md` + `decision-log.md`. Companion: `specs/user-flows.md`.
> v3 delta: execution-included MVP (D28–D31), engines per template (D30/D43: Dev+Design=agent_sdk), E2B sandboxes (D29), Postgres FileStore (D27), per-agent model tiers (D32), authored role catalogs + per-team starters (D40/D41), design output = render→screenshot (D42).
> **v3.1 delta (2026-07-07, PRD v2.1 Phase 2 / D47–D52): §22 — project file versioning, Preview Service (build-engine ↔ preview-runtime split), result-in-flow rendering, theater mode, signup credits.** Note: dev engine has since migrated to CMA with E2B fallback (D45) and billing is live (D46); §22 is written against that reality.

---

## 1. Summary

A web application that renders AI agent teams as office zones on a Two Point Hospital-style WebGL map. A single user owns isolated **projects**; each project contains team/agent **instances** cloned from system **templates** (agents picked from authored role catalogs, D41), a user-drawn **agent graph** (handoff + review-loop edges, cross-team), a per-project **orchestrator** chat, and — new in v3 — a per-project **execution workspace** where the Development & Design teams write, run, render, and test real code (D43).

**Build structure (D28): two tracks, joined at the end.**
- **Track 1 — the app:** schema/projects/graph/orchestrator/map/panels/board/landing. Knows nothing about execution beyond the `WorkspaceService` interface.
- **Track 2 — the execution engine:** `SandboxProvider` (E2B) + `WorkspaceService` + the Agent SDK dev-runner + the verification toolchain. Developed and tested headless (API-level), no UI required.

**Stack:** Next.js on Vercel (SSG landing + CSR app, Pixi.js). FastAPI + Celery on Railway. PostgreSQL = system of record (including files, via `FileStore` — D27). Redis = broker + pub/sub. **E2B** = per-project sandboxes (D29). Clerk auth. Claude only, via one provider-neutral LiteLLM layer with **per-agent model tiers** (D26, D32).

**Two execution engines — assigned per template (D30/D43):**
- **Text teams** (Planning/Research) → CrewAI runs (the validated CrewRunner core).
- **Development & Design teams** → **Claude Agent SDK** sessions inside the project sandbox (bash/file tool loop, battle-tested, prompt caching built in). Design writes frontend code and emits **rendered screenshots** as output — we are not a live-preview tool (D42). LLM-written code **never executes on the product backend**.

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

**Templates (seed, read-only):** `team_templates` (`key`: planning|research|design|development — **Data is P1, D44**; `name`, `description`, **`engine`** (`crew`|`agent_sdk`) — **development & design = agent_sdk, rest = crew**, D43); `agent_templates` = the **authored role catalog** per team (each: `role_key`, display name, **`role_instructions`** (our-authored, D41), **`default_tier`** (`strong|medium|light`, D32), **`is_starter` bool** — exactly one per team, D41; plus the role's suggested default output as columns: `default_output_type` (`handoff|review_loop|null`), `default_output_target_role_key`, `default_max_iterations` — used by the Add-agent modal prefill). `GET /templates` exposes the catalog. *(No separate `edge_templates` table — since each team starts with one agent there is no peer to wire at creation, D37; the default-output columns above carry the suggestion instead.)*

**`teams`** — `id`, `project_id` idx, `template_key`, `name`, `room_x`/`room_y` (draggable room position, D39), timestamps. Engine derives from template_key (custom teams added from a template inherit it). **Max 5 agents per team** — validated on agent insert (D37).

**`agents`** — `id`, `team_id`, `project_id` idx, `name`, `role_instructions` (user-editable), **`model_tier`** (`strong|medium|light`, default from template, user-editable — D32), pos, timestamps. Unique `(team_id, name)`.

**`edges`** (D6, D19, D25, D38) — `from_agent_id`, `to_agent_id`, `type` (`handoff|review_loop`), `max_iterations` (1–10, review_loop only). No self-edges; unique `(from,to,type)`; **at most ONE outgoing edge per agent** — unique index on `from_agent_id` (D38; "Final output" = no edge row). The graph is therefore chains + loops; the D25 DAG check reduces to rejecting a handoff that closes a cycle. Schema stays general for P1 multi-edge; the constraint is droppable.

**`goals`** (D20) — `id`, `project_id` idx, `title`, `created_at`. Board = goals × tasks.

**`tasks`** — v2 columns retained: scoping (`user_id/project_id/agent_id/goal_id`), `origin` (`chat|edge|panel`), provenance (`parent_task_id/edge_id`), `loop_state` jsonb, `override_route` jsonb (D21), `status` (7-state), `instructions`, `input_payload`, `continuations` jsonb (`via: panel|chat`), `result_markdown`, `awaiting_prompt`, `error_summary`, `attempt`, `tokens_in/out`, `est_cost_usd`, timestamps. **New:** `engine` (`crew|agent_sdk`, denormalized at creation), **`model_used`** text (actual model id for pricing, D32), **`verification` jsonb null** (dev tasks: `[{cmd, exit_code, summary}]` — the "working as expected" record, D31).
Indexes: `(project_id,status)`, `(agent_id,status)`, `(goal_id)`, `(user_id,created_at desc)`; unique partial `(parent_task_id,edge_id)`.

**`outputs`** (D4, D18, D27, D31) — `id`, `project_id` idx, `agent_id`, `task_id` idx, **`path`** text (relative path → one row per file; a dev task yields a tree of rows), `mime`, `size_bytes`, **`content`** text null (text/code) + **`content_bytes`** bytea null (binary — e.g. design PNG screenshots, D42; exactly one of the two is set), `created_at`. Per-task zip generated on demand from rows. Stored via the **`FileStore`** interface (`PostgresFileStore` now; `S3FileStore` P1 — D27).

**`context_files`** (D14) — `filename`, `content` (original, via FileStore), `extracted_text`, `size_bytes`. MVP extraction: txt/md as-is, PDF text-extracted; others rejected.

**`agent_memories`** (D14) — `agent_id` pk, `content_md`, `updated_at`.

**`orchestrator_messages`** — `project_id` idx, `role`, `content`, `created_at`.

**`notifications`** — + `project_id`, `agent_id`. Index `(user_id, read, created_at desc)`.

**`config`** — key/value, read at dispatch: `concurrency_cap=3`, `daily_cost_cap_usd`, `goal_chain_budget=25`, `context_token_budget`, **`tier_models`** (`{strong: claude-opus-4-8, medium: claude-sonnet-4-6, light: claude-haiku-4-5}`), **`model_pricing`** (per-model $/MTok in+out, incl. cache-read rate), **`dev_task_timeout_min=30`**, **`sandbox_idle_pause_sec`**.

**Token/cost aggregation (D12, D32):** SUM over `tasks` by project/team/agent; cost computed at write time from `model_used` × `model_pricing`. Live counter via SSE `usage` deltas.

**Migration from v1:** `clusters`/`units` dropped (dev-only seed, no prod data). `seed.py` v3 seeds **4 team templates** (Data is P1, D44) + their **authored role catalogs** + config maps. **Project creation instantiates one starter agent per selected team** (the `is_starter` catalog role, D37/D41) — proposed starters (adjustable): Planning→PM, Research→Researcher, Design→Product Designer, Development→Software Engineer. The design handoff's multi-agent rosters are placeholders → modeled as the rest of each team's catalog (added via Add-agent). Catalog role prompts are authored content (template quality = product quality); dev/design roles carry workspace conventions + the "working-as-expected" verification standard. **The authored prompts live in `specs/role-catalog.md`** (11 P0 roles across the 4 teams; the 2 Data roles are kept there marked P1) → transcribe into `agent_templates.role_instructions`.

---

## 6. API Contract

Base `/api`; Clerk JWT everywhere except `/health`,`/ready`; ownership-checked; cross-user → 404.

**Projects & templates** — `GET /templates`; `POST /projects` `{name, template_keys[], display_name?}` (transactional clone); `GET/PATCH/DELETE /projects/{id}`; `POST /projects/{id}/pause|resume` (D16; pause also blocks workspace dispatch).

**Map & inspection** — `GET /projects/{id}/map` → `{teams, agents(+status, +tier, +"!" flags), edges, paused}`; `GET /agents/{id}` (role, tier, edges, current task incl. `awaiting_prompt`/`error_summary`/`verification`, token totals); `GET /teams/{id}` (D15 payload).

**Management** — teams add/rename/remove, `PATCH /teams/{id}` `{room_x?, room_y?}` (drag persistence, D39); `POST /teams/{id}/agents` `{role_key?, name, role_instructions, model_tier, output?}` — `role_key` references the team's catalog (the modal prefills name/role/tier/output from it, all overridable, D41); `output` = `{type: handoff|review_loop, to_agent_id, max_iterations?}` or absent (= Final output) — **one output edge max** (D38), rejected if team already has 5 agents (D37, 409); `PATCH /agents/{id}` `{name?, role_instructions?, model_tier?}`; `DELETE /agents/{id}` (cancel tasks, drop edges; blocked while working/queued → 409); `POST /projects/{id}/edges` / `DELETE /edges/{id}` (one-outgoing + cycle validation, D25/D38).

**Orchestrator (D3/D21/D22)** — `POST /projects/{id}/chat` `{message}` → `{reply, actions[]}` (sync, <10s; dispatch async behind it); `GET /chat/history`.

**Tasks** — `GET /tasks/{id}` (full detail incl. continuations, provenance, verification); `POST /tasks/{id}/continue` (from blocked/needs-input; panel path); `POST /tasks/{id}/stop` (D16 — dequeues queued / revokes working **and kills the running sandbox command** for dev tasks; suppresses propagation).

**Board (D20)** — `GET /projects/{id}/board` → goals × items with statuses.

**Files (D27/D18/D31)** — `GET /projects/{id}/outputs` (grouped by task; file-tree entries); `GET /outputs/{id}/preview` (text/md/code); `GET /outputs/{id}/download`; **`GET /tasks/{id}/outputs.zip`** (tree as zip). Context upload/list/delete; memory GET/PUT/DELETE.

**Usage (D12/D32)** — `GET /projects/{id}/usage` → totals + by_team/by_agent + `active_tasks/cap/daily_cost_remaining` (cost from per-model pricing).

**Notifications & SSE** — list/read; `GET /projects/{id}/sse` (`task_status`, `notification`, `usage` events + heartbeats every ~20s). SSE chosen over WebSocket: traffic is one-directional server→client (commands go over REST), SSE is simpler, proxy-friendly, and auto-reconnects natively; the client treats events as lossy hints and reconciles against the DB on reconnect.

**System** — `/health`; `/ready` (DB + Redis + E2B API reachability).

---

## 7. Engines, Prompt Assembly & Model Tiers

**Engine routing (D30/D43):** `run_task` resolves `task.engine` from the agent's team template (`engine` is a per-template property — `development` & `design` = `agent_sdk`, `planning`/`research`/`data` = `crew`) — `crew` → CrewAI runner (validated CrewRunner core from the spike; dynamic Agent factory from DB rows), `agent_sdk` → dev-runner in the sandbox (§10). Design tasks run the same sandbox/render path as dev tasks; their deliverable is frontend code + **rendered screenshots** (§10), not a live preview (D42). Everything above (TaskService, GraphEngine, SSE, board) is engine-agnostic.

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

## 10. Execution Engine (Track 2 — D28–D31, D42/D43) ⭐

The self-contained module. Serves **both** agent_sdk teams — Development (code + tests) and Design (frontend code + rendered screenshots). Interface boundary:

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

**Design render path (D42):** Design tasks reuse the same Playwright instance to **screenshot rendered pages** (the dev server / built component) — the screenshots are saved as output files (PNG), the user's "see the design" deliverable alongside the frontend code. No live in-product preview (= deploy, P1).

**Output collection:** after a terminal state, `file_tree` mtime-diff (vs. task start) → changed files → `outputs` rows via FileStore (node_modules/, .next/, venv/ etc. excluded by ignore rules) → zip on demand. Design screenshots (PNG) are collected the same way (read-only image preview in Outputs).

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
  design/ tokens.ts (handoff README colors/type/shape) + primitives:
           PillButton, StatusChip, GlassPanel(372), DarkTile, Modal/Overlay, Stepper
    map/   MapCanvas, Room(wall band + checker floor + carpet + hanging sign, 3 sizes,
           5-slot placement + occupied-bbox centering), Workstation(106×82 sprite,
           top-left anchor, mirror facing, monitor glow + overhead badge), Camera(pan/zoom
           clamp 0.55–1.4 + fit, 4px drag threshold), RoomDrag(persist room_x/y)
    hud/   ProjectSwitcher, ActivityFeed(dark, row→focus), Bell+NotifDrawer, ToastStack,
           OrchestratorChat(focus-mode + world dim), TokenCounter(+per-team popover),
           ZoomControl, UtilityStack(Settings/Board/Outputs/+Team)
    panels/ TeamPanel(inline rename, stat tiles, full-team banner),
            AgentPanel(status-tinted header/role/tier/edges/status/usage/verification,
            ProvideInput-when-blocked, ErrorSummary-when-failed, Stop-when-running,
            Remove-gated)
    overlays/ BoardOverlay, SettingsOverlay(Context/Memory/Guardrails+Pause),
              OutputsList(task-grouped, FileTree expand, code/MarkdownPreview, ZipDownload)
    modals/ AddAgentModal(name/TierPicker/role/OUTPUT segment: Handoff|Loop|Final +target),
            AddTeamModal(dim in-office), Confirm
  lib/ api.ts, sse.ts(reconnect+reconcile), statusAnim.ts(sole status→visual map), store.ts
```
- **Rendering (D35, supersedes D34): flat front-view 2D in Pixi** — pan/zoom only (clamp 0.55–1.4 + fit; 4px drag threshold). Rooms = top-down rectangles + top wall band; characters = profile-view sprites, mirrored for facing (one asset). Status = **monitor glow + overhead badge** per the handoff Workstation spec; badges keep screen-space size at any zoom. No isometric, no 3D engine.
- `statusAnim.ts` remains the only status→visual mapping (glow + badge + animations); **`blocked` maps to the `needs-input` visual** (amber glow + "!"), backend keeps 7 states (D36).
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

---

## 22. Phase 2 — Closure (v3.1, D47–D52) ⭐

Design goal: close the receive-see-fix loop (PRD §16) **without touching** the task state machine, GraphEngine, engines, or the office canvas. Phase 2 is additive: one new service (Preview), one new projection (project files/versions), two frontend surfaces (result-in-flow, theater).

### 22.1 Project files & version snapshots (D50)

**Model.** Two additions, no change to `outputs`:

- **`project_files`** — the canonical current file state: `project_id`, `path` (unique per project), `output_id` fk (the Output row holding the content), `updated_at`, `updated_by_task_id`. A *manifest*, not a copy — content stays in FileStore rows.
- **`workspace_versions`** — one row per completed dev/design task that changed files: `id`, `project_id` idx, `version_no` (per-project sequence 1,2,…), `task_id`, `manifest` jsonb (`{path → output_id}` frozen at cut time), `created_at`.

**Write path.** In the worker, immediately after output collection (both engines — CMA `_collect_outputs` and E2B `collect_outputs`): upsert each collected file into `project_files` (same path → replace `output_id`), then cut a `workspace_versions` row with the full current manifest. Same transaction as the task's terminal transition — a version exists iff its task is `done`. Deletion semantics: MVP treats collection as upsert-only (agent file deletions are rare and recoverable via zip); explicit tombstones = P1 with rollback.

**Read path.** `GET /projects/{id}/versions` → `[{version_no, task_id, agent, created_at, file_count}]`; `GET /projects/{id}/files?version=` → manifest (defaults to latest). Existing per-task outputs endpoints unchanged (regression-free).

**Iteration continuity.** Dev dispatch already shares state via the CMA memory store / E2B workspace (D45/D29). `project_files` adds the *system-of-record* projection of that state — used by Preview materialization, the (P1) GitHub export, and as the recovery source if an engine store is lost. Iteration prompts reference the latest version implicitly (the engine's own store carries truth, per §10; no prompt change needed).

### 22.2 Preview Service (D49)

**The split.** Build engines produce files; the Preview Service runs them. Engines stay untouched (D45): preview always runs in **its own on-demand E2B sandbox**, regardless of `dev_engine`.

```
PreviewService
  start(project)  → status:starting → materialize latest version → npm install (lockfile-cached)
                    → npm run dev (port known) → health poll → url = sandbox.get_host(port)
                    → status:ready {url, version_no}
  status(project) → {status: none|starting|ready|error|paused, url?, version_no?}
  sync(project)   → write changed files of the new version into the running sandbox
                    (dev-server HMR picks them up; fallback: restart dev server)
  stop(project)   → pause sandbox
```

- **Columns:** on `projects`: `preview_sandbox_id`, `preview_status`, `preview_version_no`, `preview_last_active_at`. (Existing `sandbox_id` stays for the design/E2B build path — separate concerns.)
- **Lifecycle (D49, founder-set cost policy):** start on theater open or (if a preview was already active) on dev-task completion; **beat job pauses after 10 idle min** (`preview_last_active_at` refreshed by status polls/theater heartbeat); destroy after 24h paused; **max 1 per project**; sandbox-minutes logged per project.
- **Failure modes:** `npm install`/dev-server failure → `preview_status=error` + surfaced in the theater with the command tail ("the app didn't start — ask the dev team to fix it"), never a task failure; E2B outage → preview unavailable, builds unaffected.
- **API:** `POST /projects/{id}/preview/start|stop`, `GET /projects/{id}/preview` (poll), SSE event **`preview_status`** `{status, url?, version_no?}`.
- **Non-web projects** (pure docs/research, or Python-only): no runnable target detected (no `package.json` dev script) → preview card hidden; closure is fully served by result-in-flow (§22.3). Detection = manifest inspection, config-listed conventions.

**Security (D49):** preview URL = E2B host URL — unguessable, unauthenticated (unlisted-link bar; auth proxy P1). Never emitted to logs/sitemap/analytics. The iframe embeds a third-party origin — the app CSP must allow that frame; the preview app cannot script the parent (cross-origin). LLM code still never runs on our backend; the preview sandbox holds no secrets.

### 22.3 Result-in-flow (D51)

- **AgentPanel:** on `done`, render `result_markdown` in the panel (sanitized markdown — no raw HTML, schema-allowlisted; same renderer as the blog's `prose-craft` styling family), plus a files link into Outputs. This is the whole closure story for text-team tasks.
- **Outputs overlay:** replace the `<pre>` dump with rendered markdown for `.md`, syntax-highlighted code otherwise (client-side highlighter, lazy-loaded — keep the office bundle lean).
- **Sanitization is the regression gate:** stored-XSS via `result_markdown`/output content must stay neutralized (§16 invariant; adversarial suite re-run).

### 22.4 Theater mode & iteration loop (D51)

- **Preview card** (AgentPanel, dev projects with a runnable target): live thumbnail (static screenshot refresh or scaled iframe — implementation's choice on perf), LIVE dot bound to `preview_status`, URL row, open-in-new-tab, download-zip.
- **Theater** (overlay over the office, z-above panels): large iframe of the preview URL + browser-chrome header (URL, reload, new-tab, zip), version chips from `/versions`, **docked orchestrator chat** — same store/history/endpoint as the main chat (D3/D21/D22; one conversation, two mounts). Open → `preview/start` + heartbeat; close/ESC → office intact.
- **Iteration:** change requests go through the normal orchestrator dispatch (no new input surface). On the resulting task's `done`: version cut (§22.1) → SSE `preview_status`/`workspace_version` → chips advance + `PreviewService.sync` refreshes the app — no manual reload.
- Store additions: `preview` slice (status/url/version), `theaterOpen`; SSE handler maps the two new events.

### 22.5 Onboarding economics (D52)

`SIGNUP_CREDITS` 240 → **500** (`credit_service.py` constant; grant path/tests updated). No pricing/tier/margin changes. Existing accounts unaffected (grant is one-shot at first project).

### 22.6 Test strategy & rollout additions

- **Unit/integration:** version cut transactional with task completion (crash between = no orphan version); manifest correctness across 2+ sequential dev tasks incl. unchanged files; preview lifecycle (start/ready/idle-pause/resume/destroy) against real E2B; sanitized-markdown snapshot tests (XSS corpus from `ADVERSARIAL_TEST_RESULTS.md`).
- **E2E (Playwright, staging-safe):** signup → onboard → first dev task → panel result renders → theater opens → app serves → docked-chat iteration → chips advance + iframe updates → credits 500-depleted correctly → paywall.
- **Regression:** Phase 1 core flows (map/panels/board/outputs/continuation/stop/pause) + **billing untouched-paths check** (live money — checkout/webhook/topup suite green, no billing code in scope).
- **Rollout:** additive migrations (2 tables + 4 project columns + credits constant); `preview_enabled` config flag (default OFF in prod until E2E passes → flip ON via migration, same pattern as `billing_enabled`).
- **Cost watch:** preview sandbox-minutes per project in logs + weekly eyeball; idle-pause verified in prod within the first week.

---

## 23. Phase 3 — MLP (v3.2, D54–D62) ⭐

> PRD §17 / `specs/mlp-spec.md`의 기술 설계. 원칙: 기존 아키텍처에 얹는다(리라이트 기각, D57) — 신규는 어댑터/서비스로 격리하고, 가장 비싼 기존 자산(빌링·하네스·프로드 운영)은 건드리지 않는다.

### 23.1 GitHub Ownership Service (D56①, D61)

- **GitHub App** (not OAuth App): fine-grained 권한 `contents:write`, `administration:write`(리포 생성), user-install. 유저가 앱 설치 → installation_id를 `user_profiles`(or 별도 `github_connections`)에 저장. 토큰은 단명 installation token을 매 호출 발급(장기 토큰 저장 금지).
- **리포 생성:** 프로젝트당 1리포, **유저 계정 소유**로 생성(`POST /user/repos` via installation). 이름 = 프로젝트 슬러그(충돌 시 `-2`). private 기본.
- **커밋 파이프:** `workspace_versions`(D50) 컷과 **비동기**로 — 버전 컷 트랜잭션에 GitHub 호출을 넣지 않는다(외부 API가 태스크 완료를 블록하면 안 됨). Celery task `push_version(version_id)`: manifest의 파일들을 Git Data API(blob/tree/commit)로 커밋, 메시지 = 사람말 버전 라벨. 실패 시 재시도 + `versions.pushed_at` null 유지(UI에 "sync pending" 표시). 미연결 프로젝트는 스킵; 연결 시점에 전체 히스토리 백필(버전 순서대로 커밋).
- **사람말 버전 라벨:** 버전 컷 시 light-tier LLM 한 콜로 changed-file 요약 → `workspace_versions.label` ("Added checkout page"). 실패 시 폴백 = task instructions 앞 60자.
- **Restore:** 과거 버전 manifest를 현재 상태로 복사 → **새 버전 컷**(+커밋 "Restore to v3"). force-push/히스토리 리라이트 금지. 프리뷰 sync 트리거.
- **API:** `POST /github/connect`(install URL) · `GET /github/status` · `POST /projects/{id}/repo`(생성/연결) · `GET /projects/{id}/history`(버전+라벨+push 상태) · `POST /projects/{id}/restore/{version_no}`.

### 23.2 Deploy Service (D56②, D60)

- **`DeployProvider` 인터페이스** (Vercel/Neon 어댑터, 교체 가능): `provision(project)`, `deploy(version)`, `status()`, `set_env(k,v)`, `add_domain(domain)`, `provision_db()`.
- **Vercel:** 플랫폼 API(팀 계정 소유 — 유저는 Vercel 계정 불필요). 배포 = 현재 버전 파일을 Vercel deployment API로 업로드(리포 연동 아님 — GitHub 미연결 프로젝트도 배포 가능해야 함). `projects.deploy_*` 컬럼(provider_project_id, url, domain, status, last_deployed_version).
- **Neon:** 프로젝트당 DB 1개 lazy 프로비저닝(앱이 DB를 쓸 때만) — dev task가 `DATABASE_URL` 요구를 감지하면 생성 후 env로 주입. scale-to-zero로 유휴 원가 ~0.
- **커스텀 도메인:** Vercel domains API + 유저에게 DNS 레코드 안내(사람말 스텝) → 검증 폴링 → HTTPS 자동.
- **시크릿:** `project_secrets` 테이블(암호화 at rest, Fernet + 서버 키) → 배포 시 Vercel env로 주입. **로그/SSE/LLM 프롬프트에 값 노출 금지** (마스킹 유틸 필수).
- **Grand Opening UX:** `POST /projects/{id}/deploy` → SSE `deploy_status`(building/ready/error + URL). 배포는 명시적 유저 액션만(자동 배포 없음 — 프리뷰가 자동, 배포는 의식).
- **원가:** 배포/도메인/DB는 크레딧 차감 항목으로 계상(요율은 구현 시 D-결정).

### 23.3 반복 신뢰성 (D56③)

- **예산제:** `MAX_STEPS=40` 폐기 → per-task **토큰 예산**(기본 dev 500k in+out) + **시간 예산**(30분, 기존 유지). 초과 시: 진행분 수집(부분 결과) + 사람말 사유 + `continuations`에 "이어서 진행" 컨텍스트 저장 → 유저 액션으로 새 태스크가 이어받음. 조용한 실패 금지.
- **샌드박스 env 하드닝:** E2B 템플릿에 dev-runner 의존성 프리인스톨(tenacity류 재발 방지), 기동 헬스체크(임포트 스모크) 실패 시 재생성 후 1회 재시도.
- **"고쳐줘" 루프:** failed task의 error_summary를 light-tier로 사람말 번역 + AgentPanel/채팅에 **Fix it** 액션 → debugger 롤 프롬프트로 새 태스크(원 태스크 컨텍스트 + 로그 tail 주입). 기존 continuation 메커니즘 재사용.
- **E2B 컨텍스트 컴팩션:** dev_runner 대화가 토큰 예산 70% 도달 시 중간 요약으로 히스토리 압축(CMA의 자동 컴팩션과 등가 기능을 E2B 경로에). 백로그에서 P0로 승격.

### 23.4 감독 표면 (D56④)

- **디자인 코멘트 모드:** Theater iframe에 코멘트 토글 → 프리뷰 샌드박스에 주입되는 경량 스크립트(클릭 → element selector + boundingRect + 스크린샷 crop 캡처, postMessage로 부모에)가 요소 선택 → 코멘트 입력 → orchestrator dispatch에 `{selector, screenshot, comment}` 구조로 주입. 크로스오리진 경계 유지(스크립트는 프리뷰 번들에만, 부모 DOM 접근 불가).
- **코드뷰:** 기존 `GET /projects/{id}/files` 재사용 — 읽기 전용 파일 트리 + 하이라이트 뷰어(기존 outputs 렌더러 재사용, lazy chunk). "숨기되 잠그지 않기": 프로젝트 뷰 구석의 "View code" 진입점.

### 23.5 비동기 (D56⑤)

- **PWA:** manifest(이미 존재) + service worker(오프라인 셸 불필요 — 푸시 수신이 목적) + **Web Push**(VAPID): `push_subscriptions` 테이블, 구독 UI(온보딩 후 프롬프트). 발송 = 기존 `emit_terminal_notification`에 push 채널 추가(needs-input/failed/done). 클릭 → 해당 프로젝트 딥링크(모바일 웹에서 needs-input 응답 가능해야 함 — AgentPanel 모바일 레이아웃).
- iOS Safari 웹푸시 = 홈스크린 설치 필요 → 온보딩 카피에 반영(이메일 폴백은 P1 유지).

### 23.6 활성화 + 애널리틱스 (D58, D62)

- **온보딩 v2:** 사장님 프레이밍 카피(영어), 팀 선택 후 **예시 목표 카드 3개**(카탈로그에 저작) → 클릭 = 첫 오케 메시지 프리필. 목표: 가입→첫 태스크 디스패치 무중단.
- **PostHog:** frontend snippet + backend capture(서버 이벤트: task_dispatched/completed, deploy, purchase). 핵심 퍼널: visit→signup→project→**first_task**→result_viewed→return(D+1/D+7)→deploy→purchase. 세션 리플레이는 온보딩 라우트만. 개인정보 고지 추가.

### 23.7 디자인 시스템 v2 (D59)

- 토큰 전면 교체: G-Clay 팔레트(CSS vars, 라이트/다크 2세트 — 다크는 변수만 예약, Night Shift는 백로그), Inter/JetBrains Mono, 카드/섀도/radius 스케일. `/design` 레퍼런스 라우트 갱신.
- 월드: 현 React 카드 오피스를 **SVG 디오라마 컴포넌트**(Room/Desk/AgentSprite/StatusGlow)로 교체 — 정적 SVG + DOM 오버레이(네임 필/뱃지/글로우), 상태 파이프라인(QA-01/06, store 구독)은 그대로 재사용. 런타임 엔진 도입 금지.
- 신뢰 표면(billing/deploy/secrets)은 크롬 컴포넌트만 사용 — 월드 요소 금지(D59) — 를 컴포넌트 레벨로 강제(lint 룰까지는 불요, 리뷰 체크리스트 항목).

### 23.8 Test strategy 추가분

`specs/test-plan.md`(신설)가 전체 테스트 전략의 source of truth — 본 절 생략. 회귀 필수: Joshua 실패 모드 3종(스텝 벽/env 버그/지킬 수 없는 알림 약속) + QA-01~06 + 빌링 무접촉 검증.
