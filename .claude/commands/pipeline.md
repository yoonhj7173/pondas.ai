Run the multi-agent pipeline as described in CLAUDE.md.

Arguments: $ARGUMENTS
Format: `<agent_alias_or_name> [task description]`
Examples:
- `pm Build a task management app for remote teams`
- `swe Implement per specs/prd.md and specs/tech-design.md`
- `qa Run QA on the current implementation`
- `resume <run_id>` — resume a paused pipeline

Agent aliases: pm, arch, swe, qa, cr, devops, dbg

---

## Instructions

Parse $ARGUMENTS to get the starting agent and task.

If $ARGUMENTS starts with `resume`:
- Extract the run_id
- Read `runs/{run_id}/handoff.json` to understand the last state
- Continue the pipeline from where it left off

Otherwise:

1. Resolve agent alias to full name (pm→product_manager, arch→system_architect, swe→software_engineer, qa→qa_engineer, cr→code_reviewer, devops→devops_engineer, dbg→debugger_engineer)

2. Generate a run_id: `run_YYYYMMDD_HHMMSS` (use current date/time)

3. Create directory `runs/{run_id}/`

4. If no task was provided in $ARGUMENTS, ask the user: "What's the task for {agent_name}?"

5. Build the task prompt:
   - Include the user's task description
   - Read `runs/{run_id}/handoff.json` if it exists and append as `## Handoff Context`
   - Include: `Run ID: {run_id}`

6. Invoke the starting agent using the Task tool with the built prompt

7. After the agent completes, parse its status block (the JSON block at the end of the response)

8. Save the handoff to `runs/{run_id}/handoff.json`

9. Route to next agent based on CLAUDE.md state machine rules:
   - SUCCESS → LINEAR_NEXT[current_agent]
   - FEATURE_COMPLETE (swe only) → software_engineer again
   - FAILED or BLOCKED from qa/cr → debugger_engineer → back to qa/cr
   - FAILED from others → stop, report to user
   - NEEDS_USER_INPUT → pause, show agent's question to user, wait for input, continue

10. Human gates — STOP and notify the user:
    - After product_manager SUCCESS: "PM done. Review the PRD draft above and copy it into specs/prd.md. Then run /pipeline arch to continue."
    - After system_architect SUCCESS: "Arch done. Copy the tech design into specs/tech-design.md and the implementation plan into specs/implementation-plan.md. Then run /pipeline swe [task] to continue."

11. Repeat from step 5 for each subsequent agent until the pipeline ends or a human gate is hit.

12. On pipeline complete: summarise what was done, list all artifacts created.
