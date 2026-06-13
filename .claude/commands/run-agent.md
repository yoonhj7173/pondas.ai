Run a single agent and return its output. Does not continue the pipeline.

Arguments: $ARGUMENTS
Format: `<agent_alias_or_name> [task description]`
Examples:
- `pm Write a PRD for an auth module`
- `arch Design the API layer`
- `swe Implement the login feature`
- `qa Test the current implementation`

Agent aliases: pm, arch, swe, qa, cr, devops, dbg

---

## Instructions

Parse $ARGUMENTS to get the agent and task.

1. Resolve agent alias to full name

2. Generate a run_id: `run_YYYYMMDD_HHMMSS`

3. Create directory `runs/{run_id}/`

4. If no task was provided, ask the user: "What's the task for {agent_name}?"

5. Build task prompt:
   - User's task description
   - Read `context/project.md` and append if it exists
   - Include: `Run ID: {run_id}`

6. Invoke the agent using the Task tool

7. Report the agent's output to the user. No automatic routing to the next agent.
