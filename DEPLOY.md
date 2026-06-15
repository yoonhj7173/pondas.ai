# pondas.ai — Production Deploy

Architecture: **Frontend → Vercel · Backend(API)+Worker → Railway · Postgres+Redis → Railway · domain → pondas.ai**

```
pondas.ai        → Vercel (Next.js)
api.pondas.ai    → Railway web  (FastAPI, ./start-web.sh = migrate+seed+uvicorn)
(internal)       → Railway worker (Celery, ./start-worker.sh)
                   Railway Postgres + Redis
```

---

## Order of operations

1. **Railway** — project → deploy backend → add Postgres + Redis → 2 services (web, worker)
2. **Vercel** — deploy frontend → add domain pondas.ai
3. **Clerk** — production instance + domain → get pk_live/sk_live → re-enable Google
4. **Rotate keys** — Anthropic + E2B (the exposed ones)
5. **DNS** — add Vercel + Railway + Clerk records at the registrar
6. **Set env vars** (tables below) → redeploy → verify

---

## 1. Railway

- New Project → **Deploy from GitHub repo** `yoonhj7173/pondas.ai`
- **web service:** Settings → **Root Directory = `backend`** (Dockerfile auto-detected). Start command = default (`./start-web.sh`). Networking → **Custom domain `api.pondas.ai`**.
- **worker service:** New service from the **same repo**, Root Directory = `backend`, **Start command override = `./start-worker.sh`**, no public domain.
- **+ New → Database → Postgres** and **+ New → Database → Redis**.

### Railway env vars — **set on BOTH web and worker**
| Var | Value |
|---|---|
| `DATABASE_URL` | reference: `${{Postgres.DATABASE_URL}}` |
| `REDIS_URL` | reference: `${{Redis.REDIS_URL}}` |
| `ANTHROPIC_API_KEY` | new rotated key |
| `E2B_API_KEY` | new rotated key |
| `CLERK_SECRET_KEY` | `sk_live...` (from Clerk prod) |
| `APP_ENV` | `production` |
| `CORS_ORIGINS` | `https://pondas.ai` |

Optional hardening: `SANDBOX_ALLOW_INTERNET=false` (D31 — locks E2B/design sandbox egress; verify the Design team still installs what it needs, else keep default or use a custom E2B template).
Do **not** set `E2E_AUTH_BYPASS` (must stay off in prod — the app refuses to start otherwise).

---

## 2. Vercel (frontend)

- Add New → Project → same repo → **Root Directory = `frontend`** (Next.js auto-detected).
- Settings → Domains → add **`pondas.ai`** (and `www.pondas.ai`).

### Vercel env vars
| Var | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://api.pondas.ai` |
| `NEXT_PUBLIC_SITE_URL` | `https://pondas.ai` |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `pk_live...` |
| `CLERK_SECRET_KEY` | `sk_live...` |

---

## 3. Clerk (production instance)

- dashboard.clerk.com → app → **Create production instance** → domain `pondas.ai`.
- Clerk shows **CNAME records** → add them at the registrar (DNS below).
- **SSO Connections → enable Google** (production is separate from dev).
- Copy **`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` (pk_live)** + **`CLERK_SECRET_KEY` (sk_live)**.

---

## 4. Rotate keys

- **Anthropic** — console.anthropic.com → API Keys → revoke old, create new → `ANTHROPIC_API_KEY`.
- **E2B** — e2b.dev/dashboard → API Keys → new → `E2B_API_KEY`.

---

## 5. DNS (at the pondas.ai registrar)

| Host | Type | Points to | From |
|---|---|---|---|
| `pondas.ai` (apex) | A / ALIAS | Vercel (`76.76.21.21` or as Vercel shows) | Vercel |
| `www` | CNAME | `cname.vercel-dns.com` | Vercel |
| `api` | CNAME | (Railway-provided target) | Railway |
| (clerk/accounts…) | CNAME | (Clerk-provided targets) | Clerk |

Use the exact targets each dashboard shows.

---

## 6. Verify

- `https://api.pondas.ai/health` → 200 ok
- `https://pondas.ai` → landing
- "Get started" → Google sign-in → onboarding → office map
- Dispatch a Dev task → runs on CMA (Managed Agents); other teams on crew.

---

## Notes
- Backend image: `backend/Dockerfile` (Python 3.11). `start-web.sh` runs `alembic upgrade head` + `python seed.py` then uvicorn; `start-worker.sh` runs Celery. Migrations/seed run only on web.
- Dev team runs on **Claude Managed Agents (CMA)** by default (D45); design on E2B; text teams on CrewAI. Rollback: set config `dev_engine=e2b`.
