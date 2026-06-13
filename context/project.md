# Project Context

## Project Name

cursor-pm (StarCraft-style multi-agent orchestration platform)

## Project Summary

A web-based, canvas-driven platform that makes multi-agent orchestration intuitive and
engaging by presenting AI agents as units on a StarCraft-style map. Agent teams are
positioned as clusters around a navigable map; units animate while working. Users navigate
the map, click units to view status and give instructions, and receive notifications when
agents finish, get blocked, or need input. The UI/UX is the core differentiator, not the
underlying agent tech.

## Target Users

Individual professionals and small teams (marketers, researchers, operators, founders) who
want to delegate recurring knowledge work to AI agents. Companies with cross-team automation
needs are a later-phase audience.

## Product Purpose

Make multi-agent orchestration legible and operable through a spatial, game-like interface —
solving the "what are my agents doing / which is stuck / what next" problem that abstract,
config- or chat-based agent tools fail to address.

## Core Features

- Pixi.js/WebGL map canvas with pan/zoom and clickable team clusters + agent units
- Pre-built teams (MVP): 4 clusters — PM (Product Manager + Business Analyst), SWE (Senior
  Engineer + Technical Lead), QA (QA Engineer + Test Planner), DevOps (Deployment Engineer +
  Principal Engineer). No custom agent creation in MVP.
- Click unit -> on-demand status panel + actions (no real-time streaming)
- Instruction-based task assignment and continuation (respond to blocked / needs-input)
- State-keyed unit animation (idle/queued/working/blocked/needs-input/done/failed)
- In-app notification system via SSE push (done / blocked / needs-input / failed)
- Inline result/artifact panel (text/markdown, non-versioned)
- Per-user concurrency cap of 3 (config-driven) with queued overflow

## Current Tech Stack Summary

- Frontend: Next.js + Pixi.js (WebGL canvas)
- Backend: FastAPI (Python)
- Agent harness: CrewAI (Crew=cluster, Agent=unit, Task=task)
- LLM: Claude API
- Job queue: Celery; Pub/sub + cache: Redis; DB: PostgreSQL
- Auth: Clerk
- Deploy: Vercel (frontend) + Railway (backend)

## Current Architecture Summary

Two-tier: Next.js frontend (Pixi.js canvas + HUD) on Vercel; FastAPI backend + Celery workers
on Railway, with PostgreSQL and Redis. Backend exposes a REST API for CRUD/commands and one SSE
endpoint for notification push. Task lifecycle: FastAPI writes the authoritative task row,
enqueues a Celery job (gated by a per-user concurrency cap of 3), and the Celery worker runs a
CrewAI Crew against the Claude API. The task DB row (status: idle | queued | working | blocked |
needs-input | done | failed) is the single source of truth; every transition publishes a
Redis pub/sub event that fans out to the user's SSE stream. Blocked/needs-input continuation is
handled by persisting task state and re-enqueuing a fresh Celery job with appended user
instructions (no in-process pause — validated as a deliberate design choice over CrewAI's
HITL pause/resume). Pure-LLM/text outputs only; single-user workspaces; no streaming.

## Important Project-Level Principles

- UX is the differentiator; agent tech is commoditized — invest in the map experience.
- Notification-based status, not real-time streaming (simplifies architecture).
- One harness, deep (CrewAI) — no multi-harness abstraction in MVP.
- Go deep on a few teams rather than wide and shallow.
- Web app, not desktop (lower friction, Figma precedent).

## Major Decisions

- MVP ships pre-built teams only; custom agents are Phase 2/3.
- Roadmap: Phase 1 MVP (pre-built teams, UX validation) -> Phase 2 (configurable agents,
  prompt/tool editing, team workspaces) -> Phase 3 (full custom creation, marketplace).
- MVP recommendations pending user confirmation: 2 deep teams, in-app-only notifications,
  single-user workspaces, inline (non-versioned) results, state-keyed animation,
  pure-LLM/text outputs (no external tools), per-user concurrency cap (~3-5).

## Architecture Decisions (system_architect, run_20260606_134542)

- Transport: SSE (not WebSocket) for one-directional notification push; commands over plain REST.
- Source of truth: PostgreSQL `tasks.status` row; Redis events are derived/lossy hints; client
  always reconciles against the DB on SSE reconnect (no animation state without a backing status).
- Continuation (blocked/needs-input): re-enqueue a fresh Celery job with reconstructed context
  (prior instructions + continuations[] + partial output), NOT CrewAI in-process pause/resume —
  crash-safe and frees the concurrency slot during human think-time.
- Concurrency cap (3, config-driven) enforced atomically at dispatch time inside the worker,
  not only at creation; terminal/awaiting transitions trigger dispatch of the next queued task.
- Idempotency keyed on (task_id, attempt); reaper beat job fails stuck `working` tasks.
- CRITICAL SPIKE (implementation-plan item 1): validate CrewAI needs-input signaling +
  context-reconstruction continuation BEFORE building the broader flow; sentinel-marker
  (AWAITING_INPUT: <q>) fallback if native HITL is unreliable.
- No microservices/extra caches: one FastAPI app + one Celery worker type; Redis is broker +
  pub/sub only; single-row Postgres reads are fast enough.
