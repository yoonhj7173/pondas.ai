Run a tight SE↔QA loop without the full pipeline. Good for focused implementation + immediate testing cycles.

Arguments: $ARGUMENTS
Format: `[task description]`
Example: `Implement and verify the payment flow`

---

## Instructions

1. If no task in $ARGUMENTS, ask the user: "What should SE implement?"

2. Generate a run_id: `run_YYYYMMDD_HHMMSS`

3. Create directory `runs/{run_id}/`

4. Set max_cycles = 5, current_cycle = 0

5. **Loop:**

   a. current_cycle += 1. If current_cycle > max_cycles, stop and report: "Max cycles reached. Remaining issues: {issues}"

   b. Invoke `software_engineer` with the task + any issues from the previous QA run
   
   c. If SE returns FAILED or BLOCKED → stop loop, report to user
   
   d. Invoke `qa_engineer` with: task + "Verify SE's implementation" + SE's handoff context
   
   e. Parse QA status block:
      - SUCCESS (PASS) → loop done, report success
      - FAILED (issues found) → extract issues_list, rebuild SE task with `## Issues Found\n{issues}`, continue loop
      - BLOCKED → stop loop, report blocker to user

6. On completion: summarise cycles run, final status, artifacts created.
