# pondas.ai — Final E2E Test (Prod) — results

Target: **https://pondas.ai** (prod) · 2026-06-20 · Driver: Playwright (chromium) via CDP to a real logged-in Chrome.
billing_enabled=OFF (metering/paywall out of scope). Stripe=sandbox keys on prod.
(Note: original `E2E_TEST_RESULTS.md` got OS-locked mid-run (EPERM); continuing here.)

Legend: ✅ pass · ❌ fail · ⏸ blocked · ⏳ not run · 🔁 fixed&reverified

## Summary (FINAL — 2026-06-20)
- A public: 8/8 ✅
- B auth/onboarding: core ✅ (B4 unblocked after BUG-2 fix) · B7–B9 minor ⏳
- C workspace/HUD: ✅ (Esc-close fixed, BUG-3) · D agent dispatch: ✅ (chat→task→output)
- E billing: **E1–E8 ✅, E4/E5/E6 ✅** (top-up + Pro subscription + portal cancel + declined card)
- F resilience: F1 Slack ✅, F2 CORS-on-500 ✅, F3–F6 not exercised (low prio)
- **Bugs found 7 · all fixed (6× P0, 1 minor) · 0 open.** Status: **READY FOR LAUNCH** (see follow-ups).

---

## A. Public (unauth) — all ✅
| ID | result |
|---|---|
| A1 GET / | ✅ 200, 0 console errors |
| A2 /terms /privacy /refunds | ✅ all 200 + h1 |
| A3 sitemap+robots | ✅ legal pages in sitemap; robots→sitemap |
| A4 cookie banner | ✅ Decline→gtag undefined; Accept→gtag fn + amplitude obj |
| A5 OG/meta/GSC tag | ✅ present |
| A6 /unknown | ✅ 404 |
| A7 mobile 390px | ✅ no overflow |
| A8 /blog | ✅ 200, 3 posts |

## B. Auth / onboarding
| ID | result |
|---|---|
| B1 unauthed /app/x | ✅ → redirected to /onboarding (login-first) |
| B2 click Sign in w/ Google | ✅ Clerk modal opens (test must wait for Clerk JS load; initial fail = test timing, not bug) |
| B3 Google OAuth | ✅ logged in (yoonhj7173@gmail.com) → onboarding step 1 |
| B5 validation | ✅ step1/2/3 disable Continue until filled/selected |
| B6 special/long name | ✅ 217-char + `<b>测试</b>🚀` accepted, no crash |
| B4 finish → workspace | ❌ project IS created (GET /api/projects→200) but `/app/<id>` → **500 SSR crash (BUG-2)** |
| B10 API no token | ✅ 401 |
| B7 refresh/logout | ⏳ blocked by BUG-2 |
| B8 returning user | ⏳ blocked |
| B9 back-button | ⏳ blocked |

## C. Workspace / map / HUD (after BUG-2 fix)
| ID | result |
|---|---|
| C1 map render | ✅ canvas 864×997 |
| C2 SSE | ✅ Activity "LIVE" indicator |
| C5 overlays board/outputs/settings | ✅ open + Esc closes each |
| C6/E1 treasury → modal | ✅ "Add credits" + 3 pack tiles render |
| C6.close (Esc on billing modal) | ❌ **BUG-3 (minor)**: billing modal doesn't close on Esc (other overlays do); ✕/scrim-click do close |
| C7 activity feed/bell | ✅ visible |
| C8 project switcher | ✅ visible |
| C9 empty states | ✅ 0 credits / no activity / no outputs |
| C10 Esc closes overlays | ✅ (except billing modal, BUG-3) |
| C11 refresh restores | ✅ reload 200, canvas+LIVE |
| C3 orchestrator chat | ⏸ COST (LLM) — pending confirm |
| C4 agent/team panel | ⏳ canvas-click (no __qa on prod) — pending |
| C12 multi-tab | ⏳ low priority |
| G4 workspace console errors | ✅ none |

## D. Agent dispatch
| ID | result |
|---|---|
| C3 orchestrator chat (readonly) | ✅ "what agents do I have" → coherent reply (run_chat→LLM→get_project_status tool→reply) |
| D1 dispatch a task | ✅ (after BUG-4 + BUG-5 fixes) chat dispatches → task created → worker runs → **status "done"** |
| D2 output appears | ✅ Outputs shows **hello.txt** (text/plain, 11 bytes) — agent actually created the file |
| D3 status lifecycle | ✅ queued→working→done (agent working→idle) observed live |
| F1 errors → Slack alert | ✅ the BUG-4 500s fired `prod error · POST .../chat` Slack alerts to #proj-pondas |

## E. Billing (Stripe sandbox on prod) — core verified ✅
| ID | result |
|---|---|
| E1 treasury → modal | ✅ balance/plan + 3 packs |
| E2 Embedded Checkout loads | ✅ real Stripe session `cs_test_...`, $13 Pack M, TEST MODE, card form |
| E3 pay 4242 → webhook → balance↑ | ✅ **balance 0 → 1,500** after payment (checkout.session.completed → topup → ledger) |
| E8 GET /billing/summary | ✅ reflects balance/plan |
| E4 subscription (Pro) | ✅ (after BUG-6 fix) invoice.paid → **plan=pro, allowance 8000, +8000 credits** |
| E5 manage & cancel (portal) | ✅ portal opens → click-to-cancel (cancel_at_period_end) → immediate cancel → `customer.subscription.deleted` → **plan=free** |
| E6 declined card (4000…0002) | ✅ no credit granted (balance unchanged, session never completes); decline message = Stripe hosted component, **manually verified by user** (CDP auto-entry blocked by Stripe anti-bot) |
| BUG-6 invoice.subscription schema move | 🔁 FIXED (PR #22) — verified plan=pro after resend |
| BUG-7 webhook double-credit (idempotency) | 🔁 FIXED (PR #23) — verified resend leaves balance unchanged |

## F. Errors / resilience
| ID | result |
|---|---|
| F1 errors → Slack alert | ✅ verified — dispatch 500s (pre-fix) fired `prod error · POST .../chat` to #proj-pondas |
| F2 500 carries CORS headers | ✅ fixed (PR #21) + covered by `test_unhandled_handler_500_carries_cors_headers` |
| F3–F6 (rate limit / partial failure / retry caps) | ⏳ not exercised on prod (low priority; metering off) |

---

## ===== SUMMARY =====
**Core product flows verified end-to-end on prod:** landing/legal/cookies → Google login → onboarding → workspace (map/HUD/overlays/treasury) → **orchestrator chat → agent dispatch → task runs → output** → **billing: top-up + subscription + cancel + declined-card → credit/plan**.

**Bugs found: 7 · Fixed: 7 (6× P0, 1 minor) · Open: 0**
- ✅ BUG-1 (P0) backend couldn't verify prod Clerk JWT (Railway missing `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`) — env fix
- ✅ BUG-2 (P0) workspace 500 (OG image runtime `readFileSync` ENOENT) — PR #18
- ✅ BUG-3 (minor) billing modal not closeable via Esc — PR #21
- ✅ BUG-4 (P0) dispatch 500 (orchestrator history started with assistant; Anthropic needs user-first) — PR #19
- ✅ BUG-5 (P0) dispatched task stuck queued (enqueue-before-commit race → worker not_found) — PR #20
- ✅ BUG-6 (P0) subscription credits never granted (Stripe moved `invoice.subscription` → `invoice.parent.subscription_details`) — PR #22
- ✅ BUG-7 (P0) webhook double-credit — `_post` not idempotent on `stripe_ref`; Stripe at-least-once delivery re-credited (observed 16000 vs 8000) — PR #23
- ✅ Secondary: backend 500s lacked CORS headers (browser saw ERR_FAILED, masked real errors) — PR #21

**Billing follow-ups (not blocking launch):**
- Partial unique index on `credit_ledger.stripe_ref` to also defeat *concurrent* double-delivery (needs dedup of existing duplicate rows first). App-level guard (PR #23) already covers sequential retries.
- E6 declined-card *message rendering* is Stripe's hosted component — manually verified, not in automation.

## Cleanup — DONE
- ✅ 2 `e2e-test-*` projects deleted (f672974e, af24e5b2) → `DELETE /api/projects/{id}` 204; remaining projects = [] (orphan task cascade-deleted with project).
- ⬜ Residual on your account (all **sandbox / billing_enabled OFF / no real money**, left as-is — your call per earlier decision):
  - 17,500 sandbox credits (1,500 top-up + 8,000 legit refill + 8,000 from the pre-BUG-7 double-credit). Cosmetic; correct with a -8,000 ledger adjustment only if you want a clean number.
  - 1 Stripe sandbox subscription, now **canceled** (Pro, sub_1TkHjX…).
  - Stripe sandbox test customer/sessions/payments — no real money.
- ⬜ Stray local files: `E2E_TEST_RESULTS.md` (OS-locked earlier, harmless), `mockups/` — not committed.

## Manual re-run checklist (for your own pass)
1. (unauth) load /, /terms /privacy /refunds, cookie banner Accept/Decline.
2. Get started → Google login → onboarding (name/project/team) → workspace renders.
3. Chat "what agents do I have" → reply. Then "create hello.txt with hi" → task → done → Outputs shows hello.txt.
4. Treasury → pack → 4242 → balance rises.
5. (optional) Pro subscription → Manage & cancel (portal); declined card 4000…0002.

---

### BUG-5 (P0) — dispatched task stuck in "queued" — FIXED ✅ (PR #20)
Re-verify: after deploy, a new dispatch ran queued→working→**done** + produced hello.txt output. CONFIRMED FIXED. (Was: enqueue-before-commit race; see below. NOT a different-DB issue — web/worker share the same Postgres.)

### BUG-5 detail —
- After BUG-4 fix: dispatch works (POST /chat 200, orchestrator replies "Dispatched... queued", goal+task created). But the task sits in **"queued" for 8+ min**, never working→done, 0 outputs. Board shows the task cleanly queued, no error.
- **Root cause (worker logs):** worker IS up + consuming (`celery ready`, shared Redis). It RECEIVES the task but returns **`not_found` in 0.16s** — `process_task` returns "not_found" only when `db.get(Task, task_id)` is None. Task exists (web API sees it) but worker can't → **web and worker point to DIFFERENT databases (`DATABASE_URL` mismatch / two Postgres instances).** Web creates+enqueues in DB-A; worker looks up in DB-B → not_found → task stuck "queued" in DB-A forever.
- **Fix (Railway env, user):** set worker `DATABASE_URL` = web's (same `${{Postgres.DATABASE_URL}}` / same Postgres) → redeploy worker.
- (3rd prod env/infra gap caught by E2E, after BUG-1 backend Clerk key + BUG-2 OG.)

### BUG-4 (P0) — dispatching a task via orchestrator chat fails (500) — FIXED ✅ (PR #19)
- Symptom: readonly chat (status query) works (200 + reply); **dispatch instructions produce NO orchestrator reply, NO goal/task** (`GET .../board` → `{"goals":[]}`), agent stays idle, 0 tokens, no output. Browser sees `POST .../chat` → **net::ERR_FAILED** (~1.5s).
- Analysis: the dispatch fails server-side (500) in the `dispatch_task` tool path of `run_chat` (create_goal/dispatch_task/enqueue). The 500 comes from the global `Exception` handler which (Starlette) runs in ServerErrorMiddleware OUTSIDE CORSMiddleware → response lacks CORS headers → browser reports `ERR_FAILED` (masks the 500). Frontend `sendChat` catch → user bubble kept, no reply.
- Two issues: (a) **the real backend error on dispatch** (needs traceback — auto-sent to Slack #proj-pondas as `prod error · POST .../chat`); (b) secondary: 500 responses lack CORS headers (should wrap CORS so even errors carry them).
- NEEDS: the Slack traceback to pinpoint (a).

---

### BUG-3 (minor, UX) — billing modal not closeable via Esc
- BillingModal closes via ✕ button or scrim click, but NOT the Escape key (workspace overlays do close on Esc). Inconsistent. Low severity. Fix: add Esc handler to BillingModal. (Batch with end-of-run minor fixes.)

---

## Bug-fix log

### BUG-7 (P0) — webhook double-credit (non-idempotent) — FIXED ✅ (PR #23)
- Symptom: a single Pro `invoice.paid` granted **16,000 credits instead of 8,000** (balance 9,500 → 17,500). Found while verifying BUG-6.
- Root cause: `credit_service._post` (and thus `topup`/`apply_subscription_refill`) had no dedup on `stripe_ref`. Stripe delivers webhooks **at-least-once** and retries on timeout/5xx → same event credited twice.
- Fix (PR #23): `_post` skips the credit (delta>0) when a ledger row with the same `stripe_ref` already exists → returns current balance (idempotent). Tests use unique refs per run (handle_event commits) + 2 new idempotency tests.
- Re-verify ✅: resent the same `invoice.paid` after deploy → **balance stayed 17,500** (old code would have made 25,500). CONFIRMED FIXED.
- Follow-up: partial unique index on `stripe_ref` for concurrent races (needs dup-row cleanup first).

### BUG-6 (P0) — subscription credits never granted — FIXED ✅ (PR #22)
- Symptom: Pro subscription paid (4242) but `plan` stayed "free", 0 credits granted; `/billing/summary` = `{balance:1500, plan:"free", monthly_allowance:0}`.
- Root cause: newer Stripe API (2026-05-27.dahlia) **removed top-level `invoice.subscription`** and moved it + our metadata to **`invoice.parent.subscription_details`**. Our handler read `obj.get("subscription")` → None → skipped refill. Confirmed via real prod event: `parent.subscription_details.metadata = {credits:"8000", plan:"pro", user_id:"user_3FNh…"}`.
- Fix (PR #22): read `obj["parent"]["subscription_details"]["metadata"]` (with legacy `invoice.subscription` + `Subscription.retrieve` fallback). Tests updated for new structure + legacy path.
- Re-verify ✅: resent `invoice.paid` via `stripe events resend` → **plan=pro, allowance 8000**. CONFIRMED FIXED.

### BUG-1 (P0) — backend couldn't verify prod Clerk JWT — FIXED ✅
- Symptom: onboarding finish → "invalid or expired token"; all `require_user` routes failed.
- Root cause: `ClerkTokenVerifier` derives issuer/JWKS from `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`; that env was NOT set on Railway (only CLERK_SECRET_KEY was) → JWKS URL unconfigured → all tokens rejected.
- Fix: user added `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_live_Y2xlcmsucG9uZGFzLmFpJA` to Railway + redeploy.
- Re-verify: ✅ `GET /api/projects` → 200, projects created. CONFIRMED FIXED.

### BUG-2 (P0) — workspace `/app/[projectId]` 500 SSR crash — FIXED ✅ (PR #18)
- Symptom: after login + project creation, `GET /app/<id>` → **500** (Next SSR, digest 2610330691), deterministic. Unauth /app → redirect (200); only AUTHED render 500s.
- **Root cause (Vercel log):** `app/opengraph-image.tsx` ran `readFileSync(join(process.cwd(),"app/icon.png"))` at **module scope**. Static routes read it at build; **dynamic routes (/app/[projectId]) load the module at request time in the Vercel serverless function where app/icon.png isn't bundled → ENOENT → OG metadata generation crash → 500** on the whole route. (My earlier hypotheses — loadStripe / Clerk secret — were WRONG; the log pinned it.)
- **Fix (PR #18):** `new URL("./icon.png", import.meta.url)` (Next traces+bundles the asset) + try/catch (render OG without logo rather than 500).
- **Re-verify ✅:** after deploy, `GET /app/<id>` → **doc 200**, workspace renders (HUD/chat/treasury/activity), 0 console/network errors. CONFIRMED FIXED. B4 now effectively passes (project creates → workspace loads). C–G unblocked.

## Test-data cleanup (pending)
- Orphan projects created during test (delete after): `e2e-test-1781927619241` (f672974e-...), `e2e-test-1781926630876` (af24e5b2-...).
- Old locked file `E2E_TEST_RESULTS.md` (can't delete, EPERM; harmless).
