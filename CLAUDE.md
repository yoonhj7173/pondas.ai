# Harness cc-v1 — Claude Code Multi-Agent Workflow

Claude Code is the runtime. No external LLM provider, no Python package.

---

## Pipeline Flow

```
product_manager → system_architect → software_engineer → qa_engineer → code_reviewer → devops_engineer
```

Loops:
- `software_engineer` FEATURE_COMPLETE → `software_engineer` (one feature at a time)
- `qa_engineer` FAILED → `debugger_engineer` → `qa_engineer`
- `code_reviewer` FAILED → `debugger_engineer` → `code_reviewer`
- `code_reviewer` BLOCKED → `debugger_engineer` → `code_reviewer`

---

## How to Use

```
/pipeline pm [task]       full pipeline from product_manager
/pipeline swe [task]      pipeline from software_engineer (PRD + tech design already exist)
/pipeline qa [task]       pipeline from qa_engineer
/run-agent pm [task]      single agent run
/ralph [task]             SE↔QA tight loop
/status                   last run status
```

**Agent aliases:** `pm`, `arch`, `swe`, `qa`, `cr`, `devops`, `dbg`

---

## Agent Roster

| Agent | Alias | Model tier | Role |
|-------|-------|------------|------|
| `product_manager` | `pm` | strong | PRD draft, product definition |
| `system_architect` | `arch` | strong | Tech design + implementation plan |
| `software_engineer` | `swe` | medium | Feature implementation (one at a time) |
| `qa_engineer` | `qa` | medium | Runtime testing, bug finding |
| `code_reviewer` | `cr` | medium | Code quality, security, correctness |
| `devops_engineer` | `devops` | cheap | Deployment (requires explicit approval) |
| `debugger_engineer` | `dbg` | cheap | Deep bug fixing (auto-routed) |
| `advisor` | — | strong | Free-form conversation, pipeline entry |

See `config/models.yaml` for tier → model mapping.

---

## State Machine (authoritative — no agent can override this routing)

```
LINEAR_NEXT = {
  product_manager   → system_architect
  system_architect  → software_engineer
  software_engineer → qa_engineer
  qa_engineer       → code_reviewer
  code_reviewer     → devops_engineer
  devops_engineer   → (end)
}
```

Status routing rules:
- `SUCCESS` → LINEAR_NEXT[current_agent]
- `FEATURE_COMPLETE` (software_engineer only) → software_engineer again
- `FAILED` or `BLOCKED` from qa_engineer → debugger_engineer → qa_engineer
- `FAILED` or `BLOCKED` from code_reviewer → debugger_engineer → code_reviewer
- `FAILED` from any other agent → pipeline stops
- `NEEDS_USER_INPUT` → pause, wait for human, continue same agent with input

LLM's `next_agent` field in the status block is advisory only — the routing rules above are authoritative.

---

## Human Gates

Two mandatory pause points where you must stop and wait for the user:

1. **After product_manager** — PM prints PRD draft in response. User copies into `specs/prd.md` manually. Resume with `/pipeline arch`.
2. **After system_architect** — Arch prints both docs in response. User copies into `specs/tech-design.md` and `specs/implementation-plan.md`. Resume with `/pipeline swe`.

`devops_engineer` also requires explicit user approval before deploying — handled inside the agent via `NEEDS_USER_INPUT`.

---

## Status Codes

| Code | Meaning |
|------|---------|
| `SUCCESS` | Completed, route to next agent |
| `FEATURE_COMPLETE` | One feature done, more remain (swe only) |
| `FAILED` | Failed after max attempts |
| `BLOCKED` | Can't proceed — missing input, env issue, or needs debugger |
| `NEEDS_USER_INPUT` | Needs human decision before continuing |

---

## Protected Files

- `specs/prd.md` — **human-only**. No agent may create, modify, overwrite, append, or delete it. Ever.
- `specs/tech-design.md` — **system_architect creates it once**. No other agent may modify it.

---

## Status Block Convention

Every agent MUST end its response with a JSON status block inside a code fence:

```json
{
  "run_id": "<run_YYYYMMDD_HHMMSS>",
  "agent": "<agent_name>",
  "status": "SUCCESS",
  "summary": "<one sentence>",
  "files_created": [],
  "files_modified": [],
  "files_deleted": [],
  "commands_run": [],
  "issues_found": [],
  "human_input_required": false,
  "next_recommended_action": "",
  "next_agent": "<next_agent_name>",
  "handoff": {
    "from_agent": "<agent_name>",
    "to_agent": "<next_agent_name>",
    "decisions": [],
    "requirements": [],
    "artifacts": [],
    "blockers": [],
    "notes": ""
  }
}
```

---

## HandoffNote

Structured context passed between consecutive agents. Written by each agent to `runs/{run_id}/handoff.json`.

The orchestrator (pipeline command) reads this before invoking the next agent and injects it into the task prompt.

---

## Directory Structure

```
.claude/
  agents/               sub-agent system prompts
  commands/             slash commands (/pipeline, /run-agent, etc.)
  settings.json         tool permissions
config/
  models.yaml           tier → model mapping (edit here to change models)
CLAUDE.md               this file
context/
  project.md            project overview (persistent across runs)
  latest.md             most recent agent run summary
  progress.md           run history (newest first, keep 15)
specs/
  prd.md                PRD — HUMAN-ONLY, no agent may touch
  tech-design.md        tech design — system_architect creates, no one else modifies
  implementation-plan.md  feature checklist (created by arch, checked off by swe)
  qa-report.md          QA findings
  review-report.md      code review findings
  deploy-report.md      deploy report
runs/
  {run_id}/
    handoff.json        HandoffNote
    {agent}-report.md   agent output report
logs/
  pipeline.log          (optional)
```

---

## Korean Comments

Software engineer adds Korean comments for: complex logic, important data flow, architectural decisions, tricky edge cases, and external API integrations. Not for simple or obvious code.
