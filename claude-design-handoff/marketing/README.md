# Handoff: Craft — marketing site (landing + blog)

## Overview
The public marketing surface for Craft, an office-sim multi-agent orchestration app for solo founders. Two pages: a landing page and a blog. This builds **separately** from the app (sibling `product/` folder) — it's a static/marketing site, not part of the app shell. It shares Craft's visual language but needs none of the app logic.

## About the Design Files
The `.dc.html` files are **design references** (interactive HTML prototypes), not production code. Serve this folder statically and open them in a browser (they load the bundled `support.js`) to see intended look + behavior. Recreate them in your chosen web framework (Next.js, Astro, plain static — your call). Blog posts are meant to be MDX authored by the founder (no comments, no auth, no CMS).

## Fidelity
**High-fidelity.** Colors, type, spacing, and copy are final. Tone: casual, founder-to-founder (think a friendly indie SaaS, not enterprise).

## Screenshots (`screenshots/`)
- `01-landing.png` — landing page
- `02-blog.png` — blog index

## Files
| File | What it is |
|---|---|
| `Landing.dc.html` | Landing page (one scroll) |
| `Blog.dc.html` | Blog — index + post views (interactive: click a post to open it) |
| `support.js` | Prototype runtime — needed only to open the `.dc.html` files; not part of the product |

## Shared design tokens (subset used here)
- **Type:** Baloo 2 (700/800 — headings, buttons), Nunito (600–800 — body), Bricolage Grotesque (700 — big editorial titles / blog), Mulish (500 — blog body), JetBrains Mono (meta/dates). Google Fonts.
- **Primary blue button:** gradient `#67D2F2 → #3FB4DC`, pill (radius 999), white 2.5px border, text-shadow, colored drop shadow. **Confirm green:** `#74D982 → #4DBB5C`.
- **Surfaces:** page `#FBFAF6`; hero gradient `#DDE4D6 → #C6C9BC` + faint grid; ink `#2C2925`, secondary `#5C574F`, muted `#8A857C`; navy band `#2E3A52`.
- **Category chips (blog):** Engineering `#DCEEF8`/`#2C6FA0` · Product `#ECE4F6`/`#6B4FA0` · Design `#E0F2E5`/`#2C7A4A`.
- **Logo:** rounded-square "C" in the primary-blue gradient with white border + "Craft" wordmark (Baloo 2 800, navy).

## Screens

### Landing page (`Landing.dc.html`) — single scroll
1. **Nav:** logo · links: *How it works*, *Blog* (→ blog), *Get started* (→ app onboarding). No "Teams" item.
2. **Hero (2-col):** left — eyebrow pill "A whole team. None of the hiring.", H1 "Run your AI company like a tiny office sim." (Baloo 2 ~56px), casual subhead, green "Start building →" CTA + "Free to try · sign in with Google"; right — a mini office-vignette art card (rooms + sign + desks) on `#C6C9BC`.
3. **Three answer cards:** "What is Craft?" / "Who is it for?" / "Why is it different?" — icon tile + heading + 2–3 sentence answer (SEO/GEO-friendly Q&A phrasing).
4. **How it works:** 4 numbered cards — Pick your teams → Wire the graph → Talk to dispatch → Watch & steer.
5. **Demo band:** large rounded screenshot-style panel of the office map.
6. **CTA band (navy `#2E3A52`):** "Got a to-do list? Hand it to the office." + green CTA.
7. **Footer:** logo, Blog / Privacy / Terms / © links.

Links: Get started / Start building → `../product` onboarding; Blog → `Blog.dc.html`.

### Blog (`Blog.dc.html`) — index + post (one file, view-switching)
- **Index:** nav (logo "/ Blog", Get started) · "The Craft newsroom" + tagline · **featured post** (image card + category chip + title + excerpt + author·date·read-time, click → post) · **list rows** (category chip, Baloo title, summary, mono date; click → post). Three sample posts: Engineering / Product / Design.
- **Post:** "← All posts" (→ index) · category chip · Bricolage Grotesque title (~38px) · author row (avatar + name + date·read-time) · body (Mulish 17px, line-height 1.75) with: H2 subheads (Baloo), a dark code block (`#1F2430` with colored syntax), a blue-left-border blockquote (Bricolage). · footer logo + ©.
- Behavior: clicking any post (featured or list) opens that post; "← All posts" returns. State: `view` (index|post) + `post` id.

## Assets
No external images — all visuals CSS-drawn; replace with real product screenshots/illustration as desired. Fonts via Google Fonts (listed above).
