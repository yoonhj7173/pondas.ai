Initialise a new project with the harness directory structure and template files.

Arguments: $ARGUMENTS (optional — project name or description)

---

## Instructions

1. Ask the user for the project name if not provided in $ARGUMENTS. Keep it short (e.g. "x-bot", "task-manager").

2. Create the following directories if they don't exist:
   - `specs/`
   - `context/`
   - `runs/`
   - `logs/`

3. Create each template file below **only if it does not already exist** (never overwrite):

---

### `specs/prd.md`
```
# PRD

Only the human user may manually edit this file.

Agents may read this file but must not create, modify, overwrite, append, or delete it.

## Product Summary

TBD

## Target User

TBD

## Problem

TBD

## Goal

TBD

## Non-Goals

TBD

## User Stories

TBD

## Core User Flows

TBD

## P0 Scope

TBD

## P1 Scope

TBD

## P2 Scope

TBD

## Acceptance Criteria

TBD

## Open Questions

TBD

## Assumptions

TBD

## Risks

TBD

## Out of Scope

TBD
```

---

### `specs/tech-design.md`
```
# Technical Design

Drafted by system_architect, manually updated by the user before the pipeline continues.

Other agents may read this file but must not modify it.

## Overview

TBD

## Architecture

TBD

## Key Components

TBD

## Data Models

TBD

## API Contracts

TBD

## Technology Decisions

TBD

## Non-Functional Requirements

TBD

## Open Questions

TBD
```

---

### `specs/implementation-plan.md`
```
# Implementation Plan

Drafted by system_architect, manually updated by the user before the pipeline continues.
software_engineer checks off items as features are completed.

<!-- system_architect이 파이프라인 실행 시 초안을 출력합니다. 복붙 후 직접 수정하세요. -->
```

---

### `context/project.md`
```
# Project Context

## Project Name

{project_name}

## Project Summary

TBD

## Target Users

TBD

## Product Purpose

TBD

## Core Features

TBD

## Current Tech Stack Summary

TBD

## Current Architecture Summary

TBD

## Important Project-Level Principles

TBD

## Major Decisions

TBD
```
(replace `{project_name}` with the actual project name)

---

### `context/latest.md`
```
# Latest Change

## Timestamp

TBD

## Run ID

TBD

## Agent

TBD

## Summary

TBD

## Files Changed

TBD

## Result Status

TBD

## Next Recommended Action

TBD
```

---

### `context/progress.md`
```
# Progress

Newest entry first. Keep latest 15 entries only.
```

---

4. After creating all files, print a summary:

```
Project initialised: {project_name}

Created:
  specs/prd.md
  specs/tech-design.md
  specs/implementation-plan.md
  context/project.md
  context/latest.md
  context/progress.md
  runs/
  logs/

Next steps:
  1. Fill in specs/prd.md with your product requirements
     (or run /pipeline pm to have the PM agent draft it)
  2. Run /pipeline arch once specs/prd.md is ready
  3. Run /pipeline swe once specs/tech-design.md and specs/implementation-plan.md are ready
  4. Run /status at any time to check progress
```
