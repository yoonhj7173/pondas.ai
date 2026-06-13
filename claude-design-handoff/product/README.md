# Handoff: Craft — the product (office-sim multi-agent app)

## Overview
Craft is a web app where a solo founder runs a virtual company of AI agents, visualized as a friendly office sim (Two Point Hospital-inspired, non-gamer friendly). Teams are rooms, agents are workers at desks, and the user steers everything from a persistent orchestrator chat. This folder covers the app surface only: onboarding wizard, the main office map with full HUD, and all panels/modals/overlays. (Marketing site is a sibling `marketing/` folder, built separately.)

Source product docs (bundled): `uploads/prd.md` (PRD v2), `uploads/user-flows.md`, `uploads/tech-design.md`. Where this README and the PRD disagree, the PRD wins for behavior; this README wins for visuals.

## About the Design Files
The files here are **design references created in HTML** — interactive prototypes showing intended look and behavior, NOT production code to copy directly. Your task is to **recreate these designs in the target codebase's environment** using its established patterns. Per `tech-design.md`, the intended stack renders the office world in **PixiJS (2.5D sprites, fixed camera)** with a React HUD on top; the DOM prototype approximates the world with absolutely-positioned divs.

The `.dc.html` files are self-running: serve the folder statically and open them in a browser (they load the bundled `support.js`). `Craft Prototype.dc.html` is the primary reference — fully interactive.

## Fidelity
**High-fidelity.** Colors, typography, spacing, copy, and interactions are final and should be recreated faithfully. The agent/room sprites are placeholder-quality geometry (final art will be richer sprite sheets in Pixi), but their proportions, colors, anchoring, and state signals (glow + badge) are the spec.

## Screenshots (`screenshots/`)
- `01-onboarding.png` — onboarding wizard (team-select step)
- `02-map.png` — main office map with full HUD (feed, chat, token counter, zoom control)
- `03-agent-panel.png` — glassy agent panel open over the map (initial avatar, role, connection, status; colored Activity feed)
- `04-design-system.png` — design system doc (live Workstation states, 5-slot diagram, palette, core UI)
- `05-onboarding-wizard.png` — onboarding standalone reference

## Files
| File | What it is |
|---|---|
| `Craft Prototype.dc.html` | **Primary reference.** Fully interactive: onboarding → map → all panels/modals/overlays |
| `Workstation.dc.html` | Agent workstation component — single source of truth for the agent sprite |
| `Design System.dc.html` | Design system doc: tokens, slot system, room anatomy, core UI (embeds the real Workstation) |
| `Onboarding.dc.html` | Standalone onboarding wizard reference |
| `support.js` | Prototype runtime — needed only to open the `.dc.html` files; not part of the product |
| `uploads/*.md` | PRD, user flows, tech design |

## Design Tokens

### Colors — the "two-layer" rule
**Rule: high-saturation color is reserved for things you can click or that need attention. The world stays calm.**

World (low saturation):
- Map ground: `#C6C9BC` + 42px grid lines `rgba(90,95,80,0.06)`
- Room floor: `#F2EFE3` with 32px checker `#E2E4D0` (two 45° linear-gradients, offset `16px 16px`)
- Wall band (top, 42px): molding `#8A7A5E` (top 10px) → face `#D9CCAB` → `#CEC09C`; side walls `#C9BC9A` (7px)
- Team carpets (identity): Research `#C2DAC6` · Development `#C8D6E4` · Planning `#DDD3E4` · Design `#EEE7D6` · Data `#E2EAD8`
- Carpet inset: equal visual margins inside the checker floor (prototype: left/right 16, top 16 below wall, bottom 26)

UI (candy):
- Primary blue: gradient `#67D2F2 → #3FB4DC`; Confirm green: `#74D982 → #4DBB5C`
- Status: working `#4FC3E8` · needs-input/queued `#F7B731` · done `#5FC96E` · failed `#E8503A` · idle `#A8A294`
- Status chip pairs (bg/fg): `#DCEEF8`/`#2C6FA0` · `#FBEFCB`/`#8A6200` · `#E0F2E5`/`#2C7A4A` · `#F8DAD3`/`#B23A26` · `#ECE8DD`/`#6A6258`
- Navy (signs, dark panels): `#2E3A52`; dark HUD panels: `rgba(36,46,66,0.92)`
- Text: ink `#2C2925`/`#3A3631`, secondary `#5C574F`, muted `#8A857C`/`#A8A294`
- Glass side panels: `rgba(253,253,251,0.26)` + `backdrop-filter: blur(10px) saturate(1.15)`
- Modal dim: `rgba(40,46,40,0.42)`

### Typography
- **Baloo 2** (700/800): headings, UI labels, buttons, signs
- **Nunito** (600–800): body, chips, feed lines
- **JetBrains Mono** (400/500): meta/eyebrow labels
- Buttons 14–17px · panel titles 20–21px · chips 11–12px · feed rows 11px

### Shape & elevation
- Buttons: pill (radius 999) + white 2.5px border + text-shadow + colored drop shadow
- Cards/modals: radius 22–24, 3px white border, shadow `0 30px 70px rgba(30,35,25,0.4)`
- Panels (side): width 372px, glassy (see above), shadow `8px 0 32–36px rgba(50,55,45,~0.17)`
- Dark HUD tiles: radius 14–16
- Rooms cast `drop-shadow(0 14px 16px rgba(60,65,50,0.3))`

## The Workstation component (agent sprite)
Single source of truth: `Workstation.dc.html`. Slot footprint **106×82px**; internal sprite is a 150×116 drawing at `scale(0.7)`, **top-left anchored** (never bottom-anchor — a zero-height mount makes sprites jump up).

Parts (profile view): stool/chair `#8A8170`, tilted body (rotate 4°), round head with single eye dot `#4A443A`, forearm reaching to keyboard keys on desk `#FFFDF6` (shadow `0 3px 0 #C9BC9A`), monitor `#2E3A52` with **state glow** `box-shadow: -4px 0 16px 5px <state color>`, optional **badge** (28px circle, 3px white border, Baloo 800) above the head.

- `facing`: `right` (default) or `left` — pure mirror (`scaleX(-1)`), one asset
- Outfit pairs (body/arm): teal `#5FA89B`/`#4E8B80` · coral `#D98A70`/`#C2755C` · purple `#B58FBF`/`#9A75A3` · sage `#93A86E`/`#78905A` · mustard `#C9A24B`/`#AB8736`; heads `#EFC9A2` / `#E5B98F`
- State mapping (authoritative status → visuals):
  - idle: no glow, no badge
  - queued: faint amber glow `rgba(247,183,49,0.3)`
  - working: cyan glow `rgba(79,195,232,0.55)`
  - needs-input: amber glow + **"!" badge** `#F7B731` (persistent until resolved)
  - done: green glow + **"✓" badge** `#5FC96E` (brief, then idle)
  - failed: red glow `rgba(232,80,58,0.55)` + **"×" badge** `#E8503A` (persistent)
- Badges keep screen-space size at any zoom (legibility rule)

## Rooms & the 5-slot system
- Room sizes (gradual growth — room area tracks headcount): 5-seat `430×370` · 3-seat `410×280` · 2-seat `340×220`
- **Fixed 5 slots, filled in order** (430×370 room): 1 `(64,76)` facing left · 2 `(260,76)` facing right · 3 `(64,168)` facing left · 4 `(260,168)` facing right · 5 `(162,252)` centered solo. 2-seat rooms: `(40,88)`/`(194,88)`; 3-seat Research: `(30,119)`/`(274,119)` + center `(152,119)`
- **Centering rule:** the bounding box of occupied slots is centered on the carpet (5-seat: 48px left/right, 22px top/bottom margins)
- Never overlap slots, the wall, or the hanging sign; sign text never wraps
- **Hanging sign (S5):** navy plate (white 2px border, Baloo 13px, slight -1.2° rotate) suspended by two 2.5px cables from small mounts on the wall molding — cables never extend above the room
- Empty room shows a hint pill: "No agents yet — hire your first"

## Screens / Views

### 1. Onboarding (5-step wizard)
Calm gradient backdrop (`#DDE4D6 → #C6C9BC`) + grid, brand top-left, centered white card (680px, radius 24). Stepper: done = green check circles, active = larger blue circle, future = beige. Steps: ① Google sign-in ② display name ③ project name ④ team multi-select (5 template cards: Research[Analyst, Researcher], Product Planning[PM, Spec writer], Development[Architect, SWE, QA, Reviewer, DevOps], Design[UX, Visual], Data[Analyst, Engineer]; selected = tinted bg + accent border + check) ⑤ optional context-file dropzone. Final CTA: green "Enter the office →".

### 2. Main map (the app)
World layer (pans/zooms) + fixed HUD layer.
- **Camera:** drag empty floor to pan; wheel to zoom (clamp 0.55–1.4); zoom control (+ / fit / −) right-center in dark tile. Short-click on floor closes panels (only if not a drag).
- **Room drag:** dragging a room's top wall bar repositions the room; a short click on it opens the team panel.
- **HUD top-left:** project switcher pill (blue, project name + ▾) → dropdown with projects (click to switch offices) + "Add project".
- **HUD left-bottom:** stacked utility buttons: Settings, Board, Outputs (blue) and + Team (green), anchored to bottom-left.
- **HUD top-center:** toast stack — pill with status icon circle, message "Analyst (Research) needs your input", blue View button (focus+open agent), × dismiss.
- **HUD top-right:** bell (44px dark tile, red unread count) and the Activity feed panel (296px, dark): rows = status dot + `[Team]` + name + **colored status word**, 11px wrapping text, time right-aligned; failed/needs-input rows get tinted backgrounds. Rows click → **camera pans to the agent + opens its panel**.
- **HUD bottom-center:** orchestrator chat (640px). Bubbles render **only while the input is focused** (chat mode dims the world slightly); orchestrator = white bubble with "O" avatar, user = blue bubble right-aligned. Input pill + Send. Sending dispatches an idle agent: its monitor lights cyan, feed gains a line, reply names the agent.
- **HUD bottom-right:** token counter (dark tile, gold coin, count + "TOKENS TODAY"); click → popover breaking down tokens per team + total/today.

### 3. Team panel (left glass panel, 372px)
Header: team-initial avatar (46px, carpet color), name (pencil → inline rename input + Save), "N agents · M need attention". Stat tiles: AGENTS / TOKENS. Agent list rows: initial avatar, name, tier, status chip → click opens agent panel. Footer: green "+ Add agent" (opens modal; if team is full → amber "desks are full" banner in modal), Rename, red Remove team.

### 4. Agent panel (left glass panel)
Header tinted by status (amber needs-input / red failed / blue default), agent-initial avatar (50px), name + status chip. Body: ROLE (✎ Edit → inline input + Save role), MODEL tier chip, CONNECTED AGENTS (chips: `→ handoff` blue, `⇄ review loop · max N` purple), TOKENS/STATUS tiles. Conditional: needs-input → amber "Provide human input" box (question, answer input, "Send & resume" → resolves: badge clears, toast clears, status → working); failed → red "Error summary" box. Footer: "■ Stop task" (only while working; sets idle + feed line) and Remove (**disabled while working/queued**, tooltip "Stop the task before removing").

### 5. Add Agent modal (660px)
NAME input · MODEL TIER segmented (Strong/Medium/Light) · ROLE textarea (plain language) · OUTPUT segmented: **→ Hand off / ⇄ Review loop / ✓ Final output** — first two show a target row ("TO: SWE (Development)" + change), Final output shows green "Standalone — delivers straight to Outputs, no downstream agent." Footer: Cancel / green "Hire agent" → adds the agent to the next free slot on the map (existing agents re-center), feed line, panel count updates.

### 6. Add Team modal (780px)
5 template cards; teams already in the office are dimmed with "In office" tag (clicking warns "X is already in your office"); selecting highlights; "Build room" → new room appears on the map with its agents, feed line.

### 7. Board overlay ("Work plan")
Centered card (840px). Goals with colored bullet + title + status chip; checklist rows: green ✓ done / blue outline in-progress / beige pending / red × failed, each with team·agent·status caption; in-progress and failed rows click → focus that agent.

### 8. Settings overlay (860×600)
Left tab rail (Context files / Agent memory / Guardrails / Project) + footer with Log out, Terms of Use, Privacy Policy. Guardrails: Daily cost cap (progress bar + −/+ steppers, $10–100), Concurrency cap (−/+ 1–5), red "Pause project" toggle row. Context files: upload dropzone + file list. Agent memory: per-agent memory cards + clear. Project: name, danger zone (delete).

### 9. Outputs overlay (960×600)
Left: per-task cards (icon, name, type chip code/doc, "team · agent · N files · date"). Right: file tree (per-file download ⇩ on rows) + read-only code preview (dark `#1F2430`), header "build & tests passed" + blue "⇩ Download zip".

### 10. Notifications
Bell toggles a white drawer (344px): rows = status circle + title + caption + time, unread tinted bg + dot, "Mark all read". Row click → camera focus + agent panel.

## Interactions & Behavior (summary)
- All status visuals derive from one authoritative agent status (6 values); badge/glow/chips/feed must never disagree
- Persistent badges (! and ×) survive toast dismissal; resolving (human input / retry) clears them
- Focus action = pan camera so agent is ~screen center + open its panel (used by feed, notifications, toast View, board rows)
- Panels close on empty-map click; drag is distinguished from click by a 4px movement threshold
- Toast: slide-in 0.3s ease; only on the project that owns the event
- Chat dispatch targets idle agents only; stopping a working agent frees it
- Remove gating: only when not working/queued; teams at capacity can't hire (5-slot max)

## State Management (prototype's model — mirror it)
- `screen` (onboarding|map), wizard step, name/project/teams selections
- `roomPos{}` per-room x/y (drag), `panX/panY/zoom` camera
- `panel` (team|agent + id), `modal` (addAgent|addTeam), `overlay` (board|settings|outputs), `notifOpen`, `menuOpen`, `tokenOpen`, `chatFocused`
- Agent runtime: `overrides{}` (status changes), `removed{}`, `roleOverrides{}`, `teamNames{}`, `hired`, `newRoom`, `feed[]` (prepend, cap 8), `chat[]`
- Settings: `concurrency` (1–5), `costCap` ($10–100), `paused`
- Real app: statuses arrive via WebSocket/SSE from the orchestrator (see `uploads/tech-design.md`); the feed and map are projections of the same event stream

## Assets
No external images. All visuals are CSS-drawn (prototype) → to be replaced by Pixi sprite sheets matching the Workstation spec. Fonts via Google Fonts: Baloo 2, Nunito, Mulish, Bricolage Grotesque, JetBrains Mono.
