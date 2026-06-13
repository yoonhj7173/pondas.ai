Show the current project status.

Arguments: $ARGUMENTS (optional run_id)

---

## Instructions

1. Read `context/latest.md` and display its contents.

2. Read `context/progress.md` and display the last 5 entries.

3. If $ARGUMENTS contains a run_id:
   - Read `runs/{run_id}/handoff.json` if it exists
   - Show the last agent, status, summary, and next recommended action

4. If `specs/prd.md` exists and is not all TBD, show: "PRD: present"
   Otherwise: "PRD: empty (run /pipeline pm to create)"

5. If `specs/tech-design.md` exists and is not all TBD, show: "Tech design: present"
   Otherwise: "Tech design: empty (run /pipeline arch after PRD is done)"

6. If `specs/implementation-plan.md` exists, count checked vs unchecked items and show progress:
   "Implementation: 3/8 features complete"

Format the output cleanly. One section per item.
