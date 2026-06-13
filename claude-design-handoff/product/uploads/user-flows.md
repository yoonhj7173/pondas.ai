# User Flows — Office-Sim Multi-Agent Orchestration Platform

> Companion to `specs/prd.md` (v2). Source decisions: `decision-log.md` D1–D33.
> Layout reference: §7 of the PRD. Look & feel: Two Point Hospital office sim (D13).

## Reference mockups (for Claude Design handoff)

Four rough founder-drawn wireframes accompany this document when handing off to Claude Design:

1. **Start screen** — game-style start screen with required inputs (sign-in, user name, project name, team selection, context upload). (file name: Desktop - 0.png)
2. **Main map** — team zones with agent units, real-time log panel (right), freeform chat input (bottom), token usage (bottom-right), settings/board/actions buttons (left edge). (file name: Desktop - 1.png)
3. **Inspector panel annotations** — what the team panel and agent panel show when a team/agent is clicked. (file name: Desktop - 2.png)
4. **Add-agent modal** — fields: name, role, which agents to connect (input/output interaction or loop). (file name: Desktop - 3.png)

These show **layout intent and information hierarchy only** — they are grey-box sketches, NOT the visual target. The visual target is Two Point Hospital (D13). Where the mockups conflict with this document, **this document + `decision-log.md` win** (the mockups predate decisions D16–D23: e.g., the "Add project" button in the actions popup moved to the top-left project switcher per D8, and the overhead "!" indicator of D23 is not drawn).

---

All screens must be in English.

## Flow −1 — Landing + Blog (public, D24/D33)

A simple product-intro page at `/`, entirely separate from the app. Statically generated (SEO/GEO); no auth, no Pixi.

1. Visitor lands on `/` — what it is, who it's for, screenshots/demo, CTA.
2. Clicks "Get started" → Clerk sign-in (Google OAuth) → Flow 0 (new user) or straight to their latest project's map (returning user).

**Blog (admin-only newsroom, D33):**
- `/blog` — list of posts (title, summary, date), newest first.
- `/blog/[slug]` — individual post, rendered from a markdown/MDX file. Per-post SEO/GEO (metadata, OG, Article JSON-LD).
- **Reader-facing only.** Visitors read; there is no commenting, login, or authoring in the UI. The founder publishes by committing an MDX file to the repo → site rebuilds → post is live. No admin screen exists to design.

## Flow 0 — First run / start screen

Game-style start screen (not a generic SaaS signup form).

1. **Sign in** — Clerk, Google OAuth (arrived from the landing CTA, Flow −1).
2. **User name** — display name for the workspace.
3. **Project name** — creates the first project (D2: project = one office map).
4. **Team selection** — pick from 5 templates: Product Planning, Research, Design, Development, Data (D1). Multi-select; at least one.
5. **Context upload (optional)** — drop files relevant to the project (D14). Skippable; can also be done later in Settings.
6. **Land on the map** — selected teams already exist as office zones with their template agents in place. Orchestrator chat greets the user at the bottom.

Returning users: sign in → land on their most recent project's map.

---

## Flow 1 — Orient (the main screen)

- **Map**: office floor rendered in **2.5D isometric** (fixed-angle camera, pan/zoom only — D34); each team = a zone (low partitions / floor color) with office signage for the team name. Agents are sprite characters inside their zone, animating by status (typing = working, hand raised = needs-input, idle = idle, etc.). Agents in `blocked`/`needs-input` show a persistent **"!" above their head** (red icon for `failed`), visible at any zoom, cleared only when resolved (D23).
- **Right**: event feed — `[team] agent: status` lines appended on every status change (D5).
- **Bottom**: persistent orchestrator chat input (D3).
- **Bottom-right**: real-time total token counter (D12).
- **Top-left**: project switcher dropdown (D8).
- **Left edge**: Settings / Board / Actions buttons.
- Clicking empty map space closes any open panel. No minimap (D11).

---## Flow 2 — Put agents to work (orchestrator)

1. User types into the bottom chat, freeform: e.g. "리서치팀이 경쟁사 조사하고, 끝나면 기획팀이 PRD 초안 잡아줘."
2. Orchestrator interprets, creates task(s), dispatches to the right team(s)/agent(s) — cross-team chains included (D3, cross-crew = P0).
3. Orchestrator replies in chat with what it dispatched ("Research team is on competitor analysis; Planning will pick up the output").
4. Dispatched agents' statuses change → animations + event feed lines update.
5. User can ask the orchestrator anything at any time: "status?", "what's blocked?", "주제 바꿔서 다시" — it answers from authoritative task state and can re-dispatch.
6. The user can also answer a `blocked`/`needs-input` agent's question right in the chat ("그 QA가 물어본 거 B안으로 해") — the orchestrator relays the input and the task resumes, same as the agent-panel path (D22).

**Routing rules (D21):** user-drawn edges **always auto-fire** — when an agent completes a task, its output flows along its edges with no orchestrator involvement. The chat is the **entry point + one-off override**: a chat instruction that routes differently wins for that task only and never mutates edges. (Repeated overrides → "make this an edge?" suggestion is P1.)

---

## Flow 3 — Inspect & manage a team

1. Click a team zone (its signage or floor area) → **team panel** opens in the left sidebar (D15):
   - Current agent count
   - Team token usage (D12)
   - Agent list — click an agent row to jump to that agent's panel
   - **Add agent** CTA
   - Rename team / **Remove team** CTA
2. **Add agent** → modal (D1, D6, D19):
   - Name
   - Role — natural-language instructions (what this agent does, how it behaves)
   - Connections — per connected agent, one of two types: **handoff** (whose output feeds whom) or
     **review loop** (with a max-iteration count N); cross-team allowed
   - Model tier — **strong / medium / light** 3-choice (defaults from template; maps to Opus/Sonnet/Haiku
     in config — raw model names never shown) (D32)
   - Confirm → new character walks into the zone. (SCV-simple: one modal, no config files.)
3. **Remove team** → confirm dialog (warns about its agents/edges/running tasks) → zone disappears.

**Add team**: left-edge Actions button → "Add team" → pick a template → new zone appears on the map.

---

## Flow 4 — Inspect & manage an agent

1. Click an agent character → **agent panel** opens in the left sidebar:
   - Name, role
   - Connected agents (handoff / review-loop edges) with direction
   - Current status (running / waiting for human input / idle / failed …)
   - Agent token usage (D12)
   - **Provide human input** — shown **only** when status is `blocked`/`needs-input` (D10; ad-hoc input to running agents is P2). Same input can alternatively go through the orchestrator chat (D22)
   - **Stop** — shown while a task is running: cancels the task; downstream edges do not fire from it (D16)
   - Edit role / **Remove agent** CTA
2. Graph semantics (D6, D19, D21):
   - **Handoff edge A → B**: A's completed output is delivered to B as input and B starts (subject to concurrency cap) — always automatic, no orchestrator involvement.
   - **Review loop A ↔ B (max N)**: output → review → feedback → revise, iterating via the re-enqueue continuation mechanism. Ends early on the reviewer's approval signal; otherwise stops at N with a "not approved within N rounds" report for the user.
   - One agent runs **one task at a time**; tasks targeting a busy agent queue up. Parallelism = add more agents (D17).
   - All hops are visible as status changes + event feed lines.

---

## Flow 4½ — Development team executes (D28–D31)

What makes dev-team tasks different from text-team tasks — invisible plumbing, same UI:

1. The project's **workspace** (one persistent E2B sandbox; created on the first dev task, paused between tasks) holds the evolving codebase.
2. A dev agent picks up a task → Claude Agent SDK session runs in the workspace: writes code, installs deps (registry allowlist), runs builds/tests, starts the dev server. The character just animates "working" — no streaming.
3. SWE ↔ QA review loops (D19) verify **real behavior**: QA runs the app and checks it with headless Playwright. "Build passed" never closes a loop; "works as expected" does. Failures route back as revision rounds.
4. On completion, the task's file tree is collected into outputs (Flow 6) — per-file download + zip. The verification record (commands run + results) is attached to the task.
5. Stop (Flow 4) kills the running sandbox command; project pause also pauses dispatching to the workspace. Deploy is NOT performed — the DevOps agent writes deploy configs + a guide; the user downloads the zip, runs locally, and deploys themselves (agent-driven deploy = P1).

## Flow 5 — Notification → respond

1. An agent hits `done` / `blocked` / `needs-input` / `failed` → toast fires + event feed line (D5) + overhead indicator appears on the map: "!" for blocked/needs-input, red icon for failed (D23). The indicator persists until resolved — missing the toast costs nothing.
2. Click the toast (or feed line, or the "!" agent itself) → camera focuses the agent, highlight, agent panel opens.
3. `needs-input`/`blocked`: panel shows the agent's question/blocker → user types into **Provide human input** → task resumes to `working`, "!" clears. (Or answer via the orchestrator chat — D22, Flow 2.)
4. `done`: panel links to the output (Flow 6). `failed`: panel shows a short error summary.

---

## Flow 6 — Outputs (files)

1. Agents write results as **files** to project storage (D4, D27): documents from text teams, **multi-file code trees** from the Development team (collected from the workspace per task). No in-product document management.
2. User opens the output list (from the agent panel's "outputs" or Settings) → entries grouped per task: single files or expandable file trees, with name/agent/date.
3. Click a text/markdown/code file → **read-only inline preview** renders in place (D18). No editing, versioning, foldering, or search — reading only.
4. Download per file, or **download the whole task as a zip** (code trees). The user manages files themselves from there — running locally and deploying is their move (Flow 4½ step 5).

---

## Flow 7 — Board

1. Click the **Board** button (left edge) → centred overlay over the map (D20).
2. **Work-plan checklist** — like an implementation plan: when an instruction is dispatched, its work items appear here, grouped by instruction/goal, each showing done / in-progress / pending. The "what exists, what's finished, what's being worked on" big picture — nothing more, nothing less.
3. Derived directly from tasks (no separate action-item protocol). Items deep-link: clicking one focuses the relevant agent on the map.

---

## Flow 8 — Settings

Click the **Settings** button (left edge) → settings overlay (D9):
- **Context** — upload/delete project context files (same store as start-screen step 5; full-text injected into agent prompts, D14).
- **Agent memory** — per-agent scratchpads: view / edit / delete (D14; User role 6 "memory management").
- **Guardrails** — daily cost cap, concurrency cap (read/adjust), **project pause/resume** (D16).
- Project settings — rename, **delete project** (confirm dialog).

**Project pause (D16):** panic button — halts all new dispatching including edge auto-fires; running tasks finish or are stopped individually (Flow 4). Lives in Settings guardrails; a quick-access placement near the token counter is a visual-design option.

---

## Flow 9 — Projects

1. **Switch**: top-left "Project name ▾" → dropdown lists projects → select → map swaps to that project's office (full isolation: teams, agents, context, tokens, logs — D2).
2. **Add project**: same dropdown → "Add project" → mini start-screen (project name, team selection, optional context upload) → lands on the new map.
3. **Delete project**: in Settings (Flow 8), with confirm.

---

## Status → animation key (reference)

| Status | Character animation (TPH-style) |
|---|---|
| `idle` | Standing/stretching at desk |
| `queued` | Waiting pose (looking at watch) |
| `working` | Typing at desk |
| `blocked` / `needs-input` | Hand raised / speech-bubble "?" + persistent overhead **"!"** (D23) |
| `done` | Brief celebration, then idle |
| `failed` | Slumped at desk + persistent overhead red icon (D23) |

Animations are decorative within a state; transitions are driven only by the authoritative task status (no desync by construction). Overhead indicators ("!"/red) are driven by the same authoritative status, persist until resolved, and must be noticeable at any zoom level.

Asset format (D34): all map elements are **2.5D isometric sprites** — characters as sprite sheets (one look per state above), zones as iso tiles/partitions, signage as single sprites. Fixed camera angle means 1–2 character facings suffice.
