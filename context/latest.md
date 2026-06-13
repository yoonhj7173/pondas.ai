# Latest Change

## Timestamp

2026-06-06

## Run ID

run_20260606_140258

## Agent

software_engineer

## Summary

Implemented and verified implementation-plan item 4 — Auth + tenancy middleware.

Created `app/auth.py`:
- `ClerkTokenVerifier`: derives the Clerk issuer and JWKS URL by base64-decoding
  `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` (→ `true-kodiak-65.clerk.accounts.dev`). Verifies
  RS256 signatures via `PyJWKClient` (JWKS cache, lifespan 600s), enforces
  issuer/`exp`/`nbf` and requires `sub`. Only RS256 allowed (blocks alg-confusion/`none`).
- `require_user` dependency: extracts the verified `user_id` from `Authorization: Bearer`
  or `?token=` (the query form is for SSE/EventSource which cannot set headers). Any
  failure → 401 with `WWW-Authenticate: Bearer`; the cause is logged server-side only.
- `TenantScope` + `tenant_scope` dependency: `scope.query(db, model)` filters every
  user-owned query by `user_id`; `owns(row)` for single-row ownership checks. This is the
  tenancy scope helper tech-design §10 calls for — cross-user access is structurally empty.

Added `app/routers/auth_demo.py` (`/api/me`, `/api/whoami`) as a curl-testable protected
route; the same `require_user`/`tenant_scope` dependencies are reused by item 5+ routers.
Added `clerk_publishable_key` to `config.py` and documented the dual-use in `.env.example`.

## Verification (real auth path exercised)

REAL Clerk JWKS, via booted uvicorn + curl:
- No token / malformed `Authorization` header / garbage token → 401.
- Forged token (locally minted, unknown `kid`) checked against the LIVE Clerk JWKS → 401;
  server log confirms `Unable to find a signing key that matches: "forged-kid"`, proving
  the verifier fetched the real Clerk keys.

Signature-crypto path, deterministic (local RSA keypair + stubbed JWKS — legitimate
verification of the crypto logic, not faked auth): valid token → `user_id` extracted;
expired / wrong issuer / bad signature / unknown kid / `alg=none` / missing `sub` all
rejected. Tenancy: against LIVE Postgres, two users' tasks inserted; one user's scope
returns only their rows (cross-user returns nothing).

34/34 pytest pass (19 prior + 15 new), no regressions.

## Why both real and stubbed JWKS

The real-Clerk curl proves the live integration (issuer/JWKS derivation + reachability +
rejection of forgeries). A real *valid* end-user session token requires a browser Clerk
sign-in (frontend, item 11), so the signature-acceptance path is proven deterministically
with a local keypair + stubbed JWKS — this exercises the exact same `jwt.decode` crypto
verification, just with a key we control.

## Files Changed

Created: backend/app/auth.py, backend/app/routers/auth_demo.py,
backend/tests/test_auth.py.
Modified: backend/app/config.py (clerk_publishable_key), backend/app/main.py (mount
auth_demo router), backend/.env.example (publishable-key dual-use note),
specs/implementation-plan.md (item 4 checked off), context/latest.md, context/progress.md.

## Result Status

FEATURE_COMPLETE (item 4 done; items 5–18 remain)

## Next Recommended Action

Run software_engineer again to implement item 5 (Map/topology read API: GET /map and
GET /units/{id}, scoped via tenant_scope).
