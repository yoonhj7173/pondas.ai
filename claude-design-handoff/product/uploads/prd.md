# PRD v2 — Office-Sim Multi-Agent Orchestration Platform

> Status: APPROVED v2 (2026-06-11). Supersedes the v1 StarCraft-HUD PRD.
> Source of truth for every change: `decision-log.md` (D1–D33).
> Companion doc: `specs/user-flows.md` (detailed screen-by-screen flows + reference mockups note).

---

## 1. Product Summary

A web-based, canvas-driven platform that makes multi-agent orchestration intuitive and engaging by presenting AI agents as workers in a game-like office. The look & feel follows **Two Point Hospital** (D13): a project is an office map, teams are office rooms/zones, and agents are characters that animate while they work. Users watch the office at a glance, click teams/agents to inspect and manage them, talk to a per-project **orchestrator agent** through a persistent freeform chat, and get notified when an agent finishes, blocks, or needs input.

Two core bets:
1. **The UI/UX is the differentiator** — existing agent tools are config-heavy, CLI-bound, or chat-bound and illegible at a glance.
2. **The agent graph is the core mechanic** (D6) — users visually wire agents together (handoffs and review loops, including across teams) instead of writing orchestration config.

MVP ships **template-based teams that users customize** (D1): five pre-built team templates (Product Planning, Research, Design, Development, Data) that are cloned into each project, where the user can add/remove teams and agents, define each agent's role, and wire the graph.

Critically, the MVP **includes real execution** (D28–D31): the Development team doesn't draft code as text — it implements, runs, and tests it in a per-project sandbox (dev server + headless browser verification), iterating through the same implement→test→fix loops a real engineering team runs. Dev output is **working software**, with "working as expected" — not "build succeeded" — as the success criterion.

---

## 2. Target User

**Primary (MVP): solo founders** — building a product alone, needing a virtual company: planning, research, design, development, and data work delegated to AI agents they can see and steer.

**Post-MVP: individual employees at startups / small companies** — with team packs for email/Slack management, scheduling, to-do management, status reporting, etc. (roster TBD after further research).

User characteristics:
- Comfortable with modern web SaaS (Notion, Figma, Linear).
- Not necessarily technical; should never need to write orchestration config. Role definitions are written in natural language.
- Values legibility and control over raw flexibility.
- Game familiarity NOT assumed: the office metaphor is chosen precisely because it is intuitive to non-gamers (D13).

---

## 3. Problem

Multi-agent systems are powerful but illegible. Today's tools expose orchestration through configuration files, dashboards of text, or linear chat transcripts. When several agents run concurrently, the operator loses the thread:

- It is hard to tell **what each agent is doing** at a given moment.
- It is hard to spot **which agent is blocked or waiting on the user**.
- It is hard to know **what to do next** to keep work moving.
- Wiring agents together (who feeds whom, who reviews whom) requires code or YAML.

CLI-based multi-agent tools compound this: single-command and sequential by design, multiple terminal windows for concurrency, keyboard-shortcut memorization, no visual affordance. Managing a multi-agent operation at a glance is effectively impossible.

---

## 4. Goal

Make multi-agent orchestration **legible, operable, and engaging** through a spatial, game-like office interface where the agent graph is built visually.

MVP success means:
- A solo founder can set up a project with the teams they need, customize agents and their connections, and launch real work through the orchestrator — without reading docs.
- The user understands the state of every agent at a glance and is reliably notified when one finishes, blocks, or needs input — and can act in one or two clicks.
- Users describe the product as "fun" or "clear," validating UX as the differentiator.

---

## 5. Non-Goals (MVP)

- Not a from-scratch agent IDE: customization happens **on top of templates** (D1), not on a blank canvas.
- Not a real-time streaming console: status is event-feed + on-demand fetch (D5), no live token stream.
- Not a multi-harness abstraction layer — CrewAI is the single harness, used deeply.
- Not a team/collaboration product (single-user workspaces only).
- Not an in-product document editor: outputs are **files** the user downloads and manages themselves (D4; read-only inline preview is allowed, D18).
- Not an integrations platform in MVP — external tools / MCP are **P1**.
- Not a hosting platform: the product builds and tests the user's app in a sandbox but does **not deploy it** to the public internet — deploy config files + guide only; agent-driven deploy is P1 (D31).
- The blog is **admin-authored only** (founder writes MDX files in the repo), not a user-facing CMS or any kind of user-generated content (D33).
- Not a desktop application (web app only).

---

## 6. Domain Model (user-facing concepts)

| Concept | Meaning | Key decisions |
|---|---|---|
| **Project** | Top-level workspace = one office map. Teams, agents, tasks, context, memory, token usage, logs are all project-scoped. | D2 |
| **Team template** | Read-only system blueprint (Product Planning, Research, Design, Development, Data). | D1, D2 |
| **Team (instance)** | Cloned from a template into a project; user-editable; lives as a room/zone on the map. | D2 |
| **Agent** | A worker character in a team. Has name, role (natural-language instructions), **model tier (strong/medium/light)**, connections, status, memory, token usage. Runs **one task at a time** — parallelism = add more agents. Text-team agents execute on CrewAI; Development-team agents execute on the Claude Agent SDK inside the project workspace. | D1, D6, D17, D30, D32 |
| **Workspace (sandbox)** | One isolated E2B sandbox per project — a persistent filesystem where Development-team agents write, run, and test real code (Node/Next.js + Python). Paused between tasks (billing stops, state preserved). | D28–D31 |
| **Connection (edge)** | Directed link between two agents. Exactly **two kinds** in MVP: **handoff** (A's output → B's input, one-way) and **review loop** (A ↔ B, user-set max N iterations + early exit on reviewer approval signal). Cross-team allowed. **Edges always auto-fire**: the graph the user draws is the graph that executes. | D6, D19, D21 ⭐ |
| **Orchestrator** | One per project. Not on the map — lives in the persistent bottom chat. Entry point for all work; chat routing instructions act as **one-off overrides** that never mutate edges; can relay input to blocked agents; reports status on demand. Cross-crew = P0. | D3, D21, D22 |
| **Board** | Work-plan checklist (like an implementation plan): instructions are broken into work items, grouped by instruction/goal, showing done / in-progress / pending. **Derived directly from tasks** — no separate action-item protocol. | D20 |
| **Context** | User-uploaded files, project-scoped, injected into agent prompts (full-text, no RAG in MVP). | D14 |
| **Agent memory** | Per-agent markdown scratchpad, auto-appended after each task, user-manageable in settings. | D14 |
| **Output** | Files written by agents — documents from text teams, **file trees of working code** from the Development team. User sees a list, previews text/markdown/code read-only, downloads individual files or a **per-task zip**. No in-product output management. | D4, D18, D27, D31 |

Default Development team roster (template): Architect, Software Engineer, QA Engineer, Code Reviewer, DevOps — pre-wired with sensible default connections (e.g., SWE ↔ QA review loop, SWE → Code Reviewer handoff). Other templates' rosters defined by the architect, 2–5 agents each.

---

## 7. UI Layout (persistent HUD)

Look & feel: **Two Point Hospital** — bright, friendly office sim. Teams are office zones separated by low partitions / floor color; team names rendered as office signage (standing sign or floor decal — pick during visual design). No military/RTS styling (D13). No minimap (D11).

Rendering: **2.5D isometric 2D** (D34) — Two Point Hospital's warmth via Theme Hospital's technique (isometric sprites). Fixed-angle camera with pan/zoom only (no rotation); characters are sprite sheets (6 status looks + overhead badge overlays); rendered in Pixi.js. Not real 3D.

| Zone | Location | Purpose |
|---|---|---|
| **Map canvas** | Centre / full screen | The office. Team zones with agent characters; animations keyed to authoritative status. Persistent **"!" overlay** above agents in `blocked`/`needs-input` (red icon for `failed`), visible even zoomed out (D23). |
| **Project switcher** | Top-left | "Project name ▾" dropdown: switch project, add project (D8). |
| **Inspector sidebar** | Left (opens on click) | Team panel or agent panel, depending on what was clicked (contents: §8.5, §8.6 / D15). |
| **Event feed** | Right panel | Real-time log of status-change events: `[team] agent_name: status` lines (D5). Not token streaming. |
| **Orchestrator chat** | Bottom, persistent | Freeform input field — always available conversation with the project orchestrator (D3, D10). |
| **Token counter** | Bottom-right | Real-time **total** token usage, StarCraft-mineral style. Per-team/per-agent breakdowns live in the inspector panels (D12). |
| **Utility buttons** | Left edge | Settings (project settings + context/memory management, D9), Board (D20), Actions (Add team). |

**Input channels (D10, D22):** (a) orchestrator chat = always-on, project-wide — can also relay input to `blocked`/`needs-input` agents; (b) "Provide human input" in the agent panel = only when that agent is `blocked`/`needs-input`. Both paths resume the same task. Ad-hoc instructions to a *running* agent are **P2**.

**Public landing page (D24):** entirely separate from the app — a simple product-intro page at `/` (what it is, who it's for, screenshots/demo, CTA → sign-in). Statically generated for SEO/GEO; the app itself is client-rendered behind auth. Flow: landing → Clerk sign-in → start screen (Flow 0) → map.

Detailed flows: see `specs/user-flows.md`.

---

## 8. P0 Scope (MVP — must ship)

1. **Auth & start screen** — Game-style start screen: Clerk sign-in (Google OAuth), user name, project name, team selection (from the 5 templates), context file upload. Selected teams are pre-built on the map when the user lands.
2. **Projects** — Create/delete/switch projects (top-left dropdown). Full project isolation: teams, agents, context, memory, tokens, logs are per-project (D2).
3. **Template → instance teams** — Five templates (Product Planning, Research, Design, Development, Data) cloned into project instances at creation; instances are user-editable (D1, D2).
4. **Team management** — Add team (from template), rename team, remove team. Via Actions button + team panel.
5. **Agent management** — Add agent (SCV-simple: from team panel), defining name, role (natural-language instructions), and connections in one modal. Remove agent. Edit role.
6. **Agent graph** ⭐ — Two edge types only: **handoff** (one-way output→input) and **review loop** (user-set max N iterations + reviewer-approval early exit), cross-team allowed (D6, D19). **Edges always auto-fire** on task completion (D21). Compiled to CrewAI crews/tasks at dispatch; review loops run on the re-enqueue continuation mechanism. One agent runs **one task at a time** — parallelism = add more agents; tasks targeting a busy agent queue up (D17).
7. **Orchestrator** — One per project; persistent bottom freeform chat; understands the project, dispatches tasks to any team/agent (cross-crew routing = P0), reports status on demand (D3). Chat routing instructions are **one-off overrides** — they win for that task only and never mutate edges (D21). Chat can also relay input to blocked/needs-input agents (D22).
8. **Task status model** — Authoritative: `idle | queued | working | blocked | needs-input | done | failed`. Single source of truth for UI and animation (unchanged from v1).
9. **State-keyed animation + overhead indicators** — Office-worker animations keyed to status (typing = working, hand raised / speech bubble = needs-input, etc.). Persistent overhead **"!"** while `blocked`/`needs-input` and a red icon for `failed`, visible zoomed out, cleared only when resolved (D23). Decorative within a state; transitions driven only by authoritative status.
10. **Event feed** — Right panel; one line per status-change event, pushed via SSE (D5).
11. **Notifications + continuation** — Toast + feed entry on `done/blocked/needs-input/failed`; clicking focuses the agent; user resumes blocked agents via "Provide human input" (D10).
12. **Board** — Work-plan checklist for the active project: instructions broken into work items (like an implementation plan), grouped by instruction/goal, showing done / in-progress / pending. Derived directly from tasks — no separate action-item protocol (D20).
13. **Token & cost tracking** — Real-time total counter (bottom-right); per-team and per-agent usage in inspector panels; per-agent usage aggregation in backend; daily cost cap + concurrency cap (config-driven) (D12).
14. **Outputs as files & file trees** — Text agents produce documents; the Development team produces multi-file code trees collected from the workspace. Output list + per-file download + **per-task zip** + read-only inline preview for text/markdown/code (no editing, versioning, foldering, or search — reading ≠ managing); stored behind a `FileStore` interface (Postgres-backed in MVP, S3-swappable at P1) (D4, D18, D27, D31).
15. **Context & memory** — Project context: upload at start screen + settings, full-text injection within token budget (no RAG). Agent memory: per-agent markdown scratchpad auto-appended after tasks, injected into subsequent tasks, viewable/editable/deletable in settings (D14, D9).
16. **Claude as sole LLM; two execution engines** — Text teams run on CrewAI; the Development team runs on the **Claude Agent SDK** inside the sandbox (D30). Every LLM call goes through one provider-neutral layer (LiteLLM, D26). No external tools / MCP in MVP (P1).
17. **Stop & pause (emergency brakes)** — Per-agent **Stop** (cancel running task, from the agent panel; terminates running sandbox commands) and **project-wide pause** (panic button: halts all dispatching, including edge auto-fires). Mandatory counterweight to auto-firing edges and loops (D16).
18. **Public landing page + SEO/GEO** (D24) — Statically generated product-intro page at `/`, separate from the auth-gated app. SEO package: meta/OG tags + OG image, canonical, `sitemap.xml`, `robots.txt`, semantic HTML, JSON-LD (SoftwareApplication). GEO package: `llms.txt`, AI crawlers (GPTBot/ClaudeBot/PerplexityBot) allowed in robots, citation-friendly plain-language content. Landing bundle excludes Pixi (code-splitting; Core Web Vitals).
21. **Admin-only blog (newsroom)** (D33) — `/blog` index + `/blog/[slug]` posts, all **statically generated from MDX/markdown files committed to the repo** (author = the founder; no user authoring, no login, no DB, no admin auth). Per-post title/description/canonical/OG + **Article JSON-LD** (strong GEO signal); posts auto-included in `sitemap.xml` and linked from `llms.txt`. Tags/RSS/search are P1; writing content is ongoing.
19. **Execution workspace** ⭐ (D28–D31) — One persistent E2B sandbox per project, paused between tasks. Development-team agents implement features, install dependencies, run builds/tests, start dev servers, and verify real behavior with **headless Playwright** — the implement→test→fix loop (SE↔QA↔debug) runs inside the product on the existing review-loop/handoff mechanics (D19/D21). Runtimes: Node/Next.js + Python. Network: package-registry allowlist only. Success criterion: working-as-expected in the sandbox, never build-success alone. LLM-written code never executes on the product backend.
20. **Per-agent model tiers** (D32) — strong/medium/light per agent, mapped in config to Opus/Sonnet/Haiku with a per-model pricing map. Template defaults: orchestrator + core dev agents = strong; QA/reviewers/text teams = medium; memory append = light. User-editable in the agent modal.

---

## 9. P1 Scope (fast-follow)

1. **External tools / MCP integrations** (General control 2 — promoted from v1's P2).
2. Per-agent task history / activity log.
3. Retry for failed tasks (Stop/Cancel is **P0** per D16).
4. **Conditional loops** — LLM-judged exit conditions ("repeat until X"), excluded from MVP by D19.
5. **Queue priority management** — reorder tasks waiting on the concurrency cap (resolves User role 7).
6. **Context summary injection** — one-time summary on upload; inject summary by default, full text on demand (cost control for D14).
7. **Edge suggestion** — orchestrator detects repeated chat overrides and offers "make this an edge?" (D21).
8. Queue visibility (what's waiting due to the concurrency cap).
9. Email notifications.
10. RAG / embedding search over project context (when uploads outgrow full-text injection).
11. Onboarding/empty-state polish, sample projects.
12. Prompt-injection hardening for uploaded context (blast radius grows when MCP lands).
13. **Blog advanced features** — tags/categories, RSS feed, blog search (the blog **infrastructure** itself is P0 per D33; only these extras are deferred).
14. **Agent-driven deploy** of the generated product (user cloud credentials; MVP ships deploy configs + guide only) (D31).
15. Additional sandbox runtimes beyond Node/Python; S3-backed FileStore swap (D27, D31).

---

## 10. P2 Scope (later)

1. **Ad-hoc instructions to running agents** (D10).
2. Multi-user / shared workspaces, roles & permissions.
3. Real-time token streaming view.
4. Marketplace / template sharing; from-scratch team creation.
5. Post-MVP team packs: email/Slack management, scheduling, to-do, status reporting (targeting employees at startups/small companies).
6. Artifact versioning / in-product output management.

---

## 11. Acceptance Criteria (per P0 item; representative)

**Start screen & projects**
- Given a new user, when they complete the start screen (sign-in, name, project name, team selection, optional context upload), then they land on a map where exactly the selected teams exist as zones with their template agents.
- Given two projects, when the user switches via the top-left dropdown, then teams/agents/context/tokens/logs shown are only those of the active project.

**Team & agent management**
- Given a team panel, when the user clicks Add agent and submits name/role/connections, then the new agent appears in the team zone and its connections are persisted.
- Given an agent, when the user removes it, then its pending tasks are cancelled and edges referencing it are removed.

**Agent graph**
- Given a handoff edge A → B (any team), when A completes a task, then B receives A's output as input and starts (subject to concurrency cap) — always, with no orchestrator involvement.
- Given a review-loop edge A ↔ B with max N, when the loop runs, then each iteration is visible as status changes, the loop ends early on the reviewer's approval signal, and otherwise stops at N with a "not approved within N rounds" report.
- Given a busy agent (one task running), when another task targets it, then the new task queues (one task per agent at a time, D17).

**Orchestrator**
- Given the bottom chat, when the user asks for work in freeform language, then the orchestrator creates and dispatches task(s) to the appropriate team(s) and replies with what it did.
- Given a running project, when the user asks "status?", then the orchestrator summarizes per-team/per-agent status accurately (matching authoritative task statuses).
- Given an edge A → B and a chat instruction routing A's result elsewhere, then the chat instruction wins **for that task only** and the edge fires normally on A's next completion (D21).
- Given a `blocked`/`needs-input` agent, when the user answers via the orchestrator chat, then the input is relayed and the task resumes — equivalent to the agent-panel path (D22).

**Status, events, notifications**
- Given any status transition, then the agent's animation changes to match, an event line appears in the feed, and (for done/blocked/needs-input/failed) a toast fires; clicking it focuses the agent and opens its panel.
- Given an agent entering `blocked`/`needs-input`, then a "!" appears above it (red icon for `failed`), stays until resolved, and is noticeable at any zoom level (D23).
- Given a `blocked`/`needs-input` agent, when the user submits input via the agent panel, then the task resumes to `working` and eventually reaches `done`/`failed`.

**Board, tokens, outputs**
- Given dispatched instructions, when the user opens the board, then work items appear grouped by instruction/goal with done / in-progress / pending states that match authoritative task statuses (D20).
- Given completed work, then the total token counter reflects usage in near-real-time, and team/agent panels show their own usage.
- Given an agent that produced files, when the user opens the output list, then files are listed, downloadable, and text/markdown files render read-only inline on click (D18).

**Guardrails & brakes**
- Given the concurrency cap is reached, new tasks queue and auto-start in order as slots free.
- Given the daily cost cap is hit, new dispatches are refused with a clear in-app explanation.
- Given a running agent, when the user clicks Stop, then its task is cancelled and downstream edges do not fire from it (D16).
- Given project pause is engaged, then no new tasks dispatch (including edge auto-fires) until resumed; running tasks finish or are stopped individually (D16).

**Execution workspace (D28–D31)**
- Given a dev-team feature task, when the agent completes it, then the code exists in the project workspace, the build/tests it ran passed, and a verification record (commands + results) is attached to the task.
- Given a QA review-loop round, when QA verifies, then it exercises the **running app** (dev server + headless Playwright) — never a build result alone.
- Given a completed dev task, then the resulting file tree is collected as outputs and downloadable per-file and as a zip.
- Given Stop on a running dev task (D16), then the executing sandbox command is terminated and the workspace remains in a recoverable state.
- Given a project idle between tasks, then its sandbox is paused (no compute billing) and resumes with state intact on the next dev task.

**Model tiers (D32)**
- Given a new agent from a template, then it carries the template's default tier; given a tier change in the agent modal, then subsequent tasks run on the mapped model and cost tracking uses that model's pricing.

**Landing & SEO/GEO (D24)**
- Given the landing page, when fetched without JavaScript, then the full product-intro content is present in the HTML (static generation).
- Given the landing page, then meta/OG tags, canonical, JSON-LD, `sitemap.xml`, `robots.txt`, and `llms.txt` are served, and AI crawlers are allowed.
- Given the landing bundle, then it contains no Pixi.js code (verified via bundle analysis).
- Given a markdown post committed to the repo, when the site builds, then `/blog/[slug]` renders it as static HTML with per-post metadata, OG tags, and Article JSON-LD, and the post appears in `/blog` and `sitemap.xml` — with no DB, admin route, or login involved (D33).

---

## 12. Decisions (Resolved)

Authoritative record: **`decision-log.md` D1–D33** — template+customize MVP (D1), project isolation + template/instance split (D2), per-project orchestrator chat with cross-crew P0 (D3), file outputs + list/download (D4), event feed not streaming (D5), agent graph P0 cross-team (D6), board (D7→D20), top-left project switcher (D8), settings incl. context/memory management (D9), two input channels (D10→D22), no minimap (D11), total token counter + per-panel breakdown (D12), Two Point Hospital look & feel (D13), 2-layer context/memory without RAG (D14), team panel contents (D15), Stop/pause as P0 (D16), one task per agent (D17), inline output preview (D18), edges limited to handoff + bounded review loop (D19), board = task-derived work-plan checklist (D20), edges auto-fire / chat = one-off override (D21), chat can resume blocked agents (D22), overhead "!" indicators (D23), public landing page + SEO/GEO as P0 (D24), handoff DAG enforcement (D25), LiteLLM-based orchestrator tool-loop (D26), Postgres-backed FileStore (D27), execution-included MVP + two-track build (D28), E2B sandbox per project (D29), dual engines — Claude Agent SDK for dev / CrewAI for text (D30), execution scope cuts incl. no-deploy (D31), per-agent model tiers (D32), admin-only MDX blog as P0 (D33).

Carried over from v1: concurrency cap 3 (config-driven); SSE push for events, detail fetched on demand; in-app notifications only (email P1); status model and continuation semantics.

---

## 13. Assumptions

- Two engines map to the domain: a text-team task = a CrewAI Crew run; a dev-team task = a Claude Agent SDK session in the project sandbox. The user-drawn graph drives both identically (handoff/loop on the validated re-enqueue continuation mechanism — no in-process pause/resume).
- Claude is the sole LLM provider; per-agent model tiers (Opus/Sonnet/Haiku) resolve through one provider-neutral LiteLLM layer (D26, D32).
- Full-text context injection is sufficient for solo-founder-scale uploads (1M-context model); RAG deferred to P1.
- Single-user, project-isolated workspaces are sufficient to validate the core UX.
- Pixi.js/WebGL handles the MVP map (a handful of teams, tens of agents) at ~60fps on modern laptops.
- Deploy targets: Vercel (frontend incl. static landing) + Railway (backend) + E2B (per-project sandboxes). Files live in Postgres behind a FileStore interface — no object storage in MVP (D27).
- The office metaphor is learnable without onboarding for non-gamers.

---

## 14. Risks

- **UX is the bet, and it's hard.** If the office doesn't feel clear/fun, the differentiator fails. Mitigation: invest disproportionately in map feel, animation legibility, and the event→focus loop.
- **Agent graph complexity** ⭐ co-top technical risk: user-drawn graphs must compile to valid executions. Mitigated by design: edge semantics constrained to handoff + bounded review loop (D19), edges deterministic / chat one-off (D21), graphs validated at save time; architect to spike graph→CrewAI compilation early.
- **Execution engine quality** ⭐ co-top technical risk: LLM-written code running in sandboxes brings hangs, timeouts, flaky verification, and minutes-long tasks. Mitigation: battle-tested Agent SDK loop instead of a homegrown one (D30), strict isolation — LLM code never on the product backend (D29), per-task timeouts + resource caps, pause between tasks, and Track-2 isolation so the engine is built and tested headless before UI integration (D28).
- **Orchestrator quality.** Freeform dispatch that misroutes work erodes trust. Mitigation: orchestrator always states what it dispatched; user can correct via chat (one-off override, D21).
- **Animation/status desync.** Mitigation unchanged: no animation state without backing status; "!" indicators driven by the same authoritative status (D23).
- **Cost.** Graphs, loops, and dev sessions multiply LLM calls (full product build ≈ $50–150 in tokens; sandbox compute is negligible at ~$0.10/hr). Mitigation: concurrency cap, daily cost cap (raise to $50–100 on dev days), loop iteration bounds (D19), per-agent Stop + project pause (D16), model tiers cutting an estimated 25–40% (D32), token counter always visible.
- **Latency vs. expectations.** No streaming → uncertainty during long tasks. Mitigation: clear working/queued states, event feed, reliable notifications.
- **Template content quality.** 5 templates × 2–5 role prompts each — template quality IS product quality (first-run experience runs on defaults). Budget real iteration time.
- **Scope creep** into from-scratch agent building / marketplace. Mitigation: hold the template+customize line (D1).

---

## 15. Out of Scope (MVP)

- From-scratch (non-template) team creation; marketplace/template sharing (P2+).
- Multi-user / shared workspaces and collaboration (P2+).
- External tool integrations / MCP (P1).
- Deploying the user's generated product (P1 — MVP ships deploy configs + guide, D31).
- Sandbox runtimes beyond Node/Next.js + Python (P1).
- Real-time token streaming (P2).
- Ad-hoc instructions to running agents (P2).
- In-product output/document management, artifact versioning (P2+).
- Blog/content marketing (P1, on the landing domain).
- Desktop/native apps; multi-LLM / multi-harness abstraction.
- Billing/monetization specifics.
