# User Flows — Office-Sim Multi-Agent Orchestration Platform

> Companion to `specs/prd.md` (v2). Source decisions: `decision-log.md` D1–D44.
> Layout reference: §7 of the PRD. Look & feel: Two Point Hospital office sim (D13).
> **Visual source of truth: `claude-design-handoff/product/README.md` (D36)** — the design is final at pixel level. This doc owns behavior; the handoff owns visuals. The founder wireframes below are historical (they fed the design phase, now complete).

## Reference mockups (historical — design phase complete)

Four rough founder-drawn wireframes seeded the Claude Design handoff (`Desktop - 0..3.png`): start screen, main map, inspector annotations, add-agent modal. They showed **layout intent only**; the realized design now lives in `claude-design-handoff/product/` and supersedes them. Kept here for provenance.

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
4. **Team selection** — pick from 4 templates: Product Planning, Research, Design, Development (D1; Data team is P1, D44). Multi-select; at least one.
5. **Context upload (optional)** — drop files relevant to the project (D14). Skippable; can also be done later in Settings.
6. **Land on the map** — selected teams already exist as office rooms, each with its **one starting agent** (the team's designated catalog starter — Planning→PM, Research→Researcher, Design→Product Designer, Development→SWE; D41). Rosters grow via Add agent from the team's role catalog, up to 5. Orchestrator chat greets the user at the bottom.

Returning users: sign in → land on their most recent project's map.

---

## Flow 1 — Orient (the main screen)

- **Map**: office floor rendered in **flat front-view 2D** (Pixi, pan/zoom only — D35); each team = a room (top-down rectangle + top wall band) with a hanging navy sign for the team name. Rooms are **draggable by their wall bar** (positions persist — D39); a short click on the bar opens the team panel. Agents are profile-view sprite characters at desks (5-slot layout), showing status via **monitor glow + overhead badge**: cyan glow = working, amber glow + **"!"** = needs-input/`blocked`, green glow + "✓" = done, red glow + "×" = failed; badges stay screen-size at any zoom, cleared only when resolved (D23, D36).
- **Top-right**: "Activity" event feed (dark panel) — `[team] agent: status` lines, status word colored, rows click → focus the agent (D5). A **bell** beside it opens the notifications drawer (D36).
- **Bottom-center**: persistent orchestrator chat — bubbles show only while the input is focused, dimming the world (D3, D36).
- **Bottom-right**: real-time total token counter; click → per-team breakdown popover (D12).
- **Top-left**: project switcher dropdown (D8).
- **Bottom-left stack**: Settings / Board / Outputs / + Team buttons. Zoom control (+ / fit / −) right-center.
- Clicking empty map space closes any open panel (only if not a drag — 4px threshold). No minimap (D11).

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
2. **Add agent** → modal (D1, D6, D19, D38, D41). Blocked with a "desks are full" banner if the team already has 5 agents (D37):
   - **Pick a role from the team's catalog** — our-authored roles (e.g. Development: Architect / QA / Code Reviewer / DevOps; Design: Visual). Selecting **prefills name / role / tier / output**, all editable. Not a blank box; fully custom from-scratch roles are P1 (D40).
   - Name
   - Model tier — **Strong / Medium / Light** segmented (defaults from the picked role; maps to Opus/Sonnet/Haiku
     in config — raw model names never shown) (D32)
   - Role — natural-language instructions, prefilled from the catalog, editable (what this agent does, how it behaves)
   - Output — **one** choice (D38): **→ Hand off** (to one target agent) / **⇄ Review loop** (one target +
     max N) / **✓ Final output** (no downstream — result goes straight to Outputs). Hand off & Loop show a
     target row ("TO: SWE (Development)" + change); cross-team allowed.
   - Confirm → new character takes the next free desk; existing agents re-center. (SCV-simple: one modal, no config files.)
3. **Remove team** → confirm dialog (warns about its agents/edges/running tasks) → zone disappears.

**Add team**: left-edge Actions button → "Add team" → pick a template → new zone appears on the map.

---

## Flow 4 — Inspect & manage an agent

1. Click an agent character → **agent panel** opens in the left sidebar (header tinted by status — amber needs-input / red failed / blue default):
   - Name, role (✎ edit inline)
   - Model tier chip
   - Connected agent — the single outgoing edge if any: `→ handoff` (blue) or `⇄ review loop · max N` (purple). Changing it = remove & re-hire (edit UI is P1, D38).
   - Current status (running / waiting for human input / idle / failed …)
   - Agent token usage (D12)
   - **Provide human input** — shown **only** when status is `blocked`/`needs-input` (D10; ad-hoc input to running agents is P2). Same input can alternatively go through the orchestrator chat (D22)
   - **Stop** — shown while a task is running: cancels the task; downstream edges do not fire from it (D16)
   - Edit role / **Remove agent** CTA — Remove is **disabled while working/queued** (tooltip "Stop the task before removing")
2. Graph semantics (D6, D19, D21, D38):
   - Each agent has **at most one outgoing edge** — the graph is chains + loops, no fan-out/fan-in (D38).
   - **Handoff edge A → B**: A's completed output is delivered to B as input and B starts (subject to concurrency cap) — always automatic, no orchestrator involvement.
   - **Review loop A ↔ B (max N)**: output → review → feedback → revise, iterating via the re-enqueue continuation mechanism. Ends early on the reviewer's approval signal; otherwise stops at N with a "not approved within N rounds" report for the user.
   - **Final output (no edge)**: the agent's result goes straight to Outputs (Flow 6), nothing downstream.
   - One agent runs **one task at a time**; tasks targeting a busy agent queue up. Parallelism = add more agents (D17).
   - All hops are visible as status changes + event feed lines.

---

## Flow 4½ — Execution teams: Development & Design (D28–D31, D42/D43)

What makes **agent_sdk** teams (Development & Design, D43) different from text teams — invisible plumbing, same UI:

1. The project's **workspace** (one persistent E2B sandbox; created on the first execution task, paused between tasks) holds the evolving codebase.
2. A dev/design agent picks up a task → Claude Agent SDK session runs in the workspace: writes code, installs deps (registry allowlist), runs builds/tests, starts the dev server. The character just animates "working" — no streaming.
3. SWE ↔ QA review loops (D19) verify **real behavior**: QA runs the app and checks it with headless Playwright. "Build passed" never closes a loop; "works as expected" does. Failures route back as revision rounds.
4. On completion, the task's file tree is collected into outputs (Flow 6) — per-file download + zip. The verification record (commands run + results) is attached to the task.
5. **Design tasks** ride the same path but their deliverable is **frontend code + rendered screenshots** (Playwright screenshots the rendered page → PNG outputs). This is our "see the design" — a static screenshot + runnable code, **not a live in-product preview** (that's deploy-shaped, P1; we are not Lovable — D42).
6. Stop (Flow 4) kills the running sandbox command; project pause also pauses dispatching to the workspace. Deploy is NOT performed — the DevOps agent writes deploy configs + a guide; the user downloads the zip, runs locally, and deploys themselves (agent-driven deploy = P1).

## Flow 5 — Notification → respond

1. An agent hits `done` / `blocked` / `needs-input` / `failed` → toast fires (top-center, with View) + Activity feed line + bell unread count (D5, D36) + overhead badge on the map: **"!"** for blocked/needs-input, **"×"** for failed (D23). Persistent badges survive toast dismissal and clear only on resolution — missing the toast costs nothing.
2. Click the toast (or feed line, or the "!" agent itself) → camera focuses the agent, highlight, agent panel opens.
3. `needs-input`/`blocked`: panel shows the agent's question/blocker → user types into **Provide human input** → task resumes to `working`, "!" clears. (Or answer via the orchestrator chat — D22, Flow 2.)
4. `done`: panel links to the output (Flow 6). `failed`: panel shows a short error summary.

---

## Flow 6 — Outputs (files)

1. Agents write results as **files** to project storage (D4, D27): documents from text teams, **multi-file code trees** from Development, **code + rendered screenshots (PNG)** from Design (collected from the workspace per task, D42). No in-product document management.
2. User opens the output list (from the agent panel's "outputs", the Outputs button, or Settings) → entries grouped per task: single files or expandable file trees, with name/agent/date.
3. Click a text/markdown/code file → **read-only inline preview** renders in place; **image files (design screenshots) preview as images** (D18). No editing, versioning, foldering, or search — reading only.
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

## Status → visual key (reference — Workstation spec, D36)

Status drives **monitor glow + overhead badge** (the authoritative visual). The backend keeps 7 states; the UI shows 6 — `blocked` reuses the `needs-input` look.

| Status | Monitor glow | Overhead badge | Notes |
|---|---|---|---|
| `idle` | none | none | |
| `queued` | faint amber | none | |
| `working` | cyan | none | |
| `needs-input` / `blocked` | amber | **"!"** (persistent until resolved) | D23 |
| `done` | green | "✓" (brief, then idle) | |
| `failed` | red | "×" (persistent) | D23 |

Glow and badge are driven only by the authoritative task status (no desync by construction); badges keep **screen-space size at any zoom** (legibility). Per-state desk animations (typing, etc.) are decorative within a state.

Asset format (D35): all map elements are **flat front-view 2D sprites** — characters as profile-view sprite sheets (one look per state above) mirrored for facing (one asset), rooms as top-down rectangles + wall band, signage as single sprites. See the handoff Workstation spec for footprint (106×82), anchoring (top-left), and exact glow/badge colors.
