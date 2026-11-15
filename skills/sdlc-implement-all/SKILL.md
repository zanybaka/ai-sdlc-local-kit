---
name: sdlc-implement-all
description: Implements ALL open tasks from BACKLOG.md sequentially, each in a fresh agent context in the main working tree. Use when the user says "run all tasks", "ship everything", "implement all backlog items", "запусти все задачи", or wants hands-free sequential delivery of every open item. Always invoke this skill instead of running sdlc-implement-task in a loop.
---

# Implement All Tasks

Deliver every open backlog task sequentially, one agent per task, directly in the main working tree.

Scheduling: **explicit-deps** when the backlog uses metadata (`Depends on`, `Priority`). See `.ai-task/docs/ai-task-backlog-contract.md`.

## Step 0 — detect `.ai-task/`

Before `ai-task plan`, `dor`, `run`, or `backlog-order --strict`, check whether **`.ai-task/`** exists.

| Result | Action |
|--------|--------|
| **Absent** | **Backlog-only mode.** Run **`ai-task backlog-order`** for execution order (no init required). Do **not** call `plan`/`dor`/`run`. Init errors from `plan --strict` are expected, not batch failures. |
| **Present** | Use `backlog-order` / `dor` / `plan --strict` as in Step 1. |

## Steps

### 1. Build execution order (not raw file order)

Do **not** use «every `- [ ]` top to bottom» when tasks have `Depends on` or different priorities.

**When `.ai-task/` exists** (recommended for this repo profile):

```bash
ai-task dor                    # or: ai-task backlog-order --strict
ai-task backlog-order          # ordered open task ids
ai-task backlog-order --json   # machine-readable
```

Use that order for the batch. Run `plan --strict` first if DoR was never checked.

**When `.ai-task/` is absent:**

```bash
ai-task backlog-order          # ordered open task ids
ai-task backlog-order --json   # machine-readable
```

Use the full ordered list (same explicit-deps rules as above). Do **not** sort by raw file order.

For each id, extract **task body** (title line through the block until the next list item).

If no open tasks, tell the user and stop.

### 2. Confirm with the user

Show ordered task IDs and ask: «Implement all N tasks in this order: [list]?» Wait for confirmation unless the user already said run all / ship everything / прогони всё.

### 3. Implement each task — sequentially

For each task id **in execution order**:

1. Tell the user: «Starting task **{task_id}**…»

2. Spawn an `Agent` (no isolation) with this prompt:

---
```
You are implementing a single backlog task in the main working tree.

## Task to implement
ID: {task_id}

{task_body}

## Instructions
Follow the sdlc-implement-task workflow for THIS task only:

1. Read AGENTS.md, PRD.md, TECHSPEC.md as needed.
2. Implement the smallest in-scope change.
3. Run sdlc-verify-dod.
4. ADR gate per sdlc-implement-task (or one-line «ADR not required»).
5. Mark `- [ ] {task_id}` → `- [x]` in `backlog/tasks/{task_id}.md` and regenerate the index (`python scripts/backlog-store.py regenerate`); in a non-migrated repo (no backlog/tasks/ files), flip it inline in BACKLOG.md.
6. Update CHANGELOG.md.
7. Commit with the task id in the message.
8. Run the closing check of sdlc-implement-task (its section "Closing check") before you report the task done, and put what it found, fixed and filed into your report.

Implement only {task_id}. Do not pick another open task.
```
---

3. **Wait** for the agent to finish before the next task.

4. Report ✓/✗ and a one-line summary per task.

### 4. Final summary

| Task | Result | Summary |
|------|--------|---------|
| … | ✓/✗ | … |

Note failed tasks.

Before this summary the lead runs the closing check of sdlc-implement-task once more for the whole batch: the task agents are its own background work, and a tail one agent left (a finding in its report that has no task yet, an unpushed commit) is the lead's to fix.

## Important notes

- **Sequential only** — later tasks may depend on earlier ones (respect `backlog-order`).
- Each agent runs in a fresh context but in the same working tree — it sees all commits from previous tasks.
- On failure, **continue** the batch unless the user asked to stop.
- **Git isolation:** this skill does not use git worktrees. For batch delivery with per-run isolation (`.ai-task/worktrees/`, parallel headless runs), use **ai-task-teamlead** and scenario **`isolated_worktree_batch`** with `worktrees_enabled` in `.ai-task/config.toml`.
- For headless Claude/Cursor CLI batches in the same repo, prefer **ai-task-teamlead** (`ai-task run --wait` or waves) instead of this IDE skill.
- For subagent delivery that keeps leases, worktrees, verify, review and verdict, use **ai-task-teamlead** with the in-session executor (`claude_subagent` or `codex_subagent`). It needs no headless CLI token.

## vs ai-task-teamlead «run all»

| | sdlc-implement-all | ai-task-teamlead |
|--|---------------------|------------------|
| Runtime | Cursor subagent, main working tree | `ai-task run` + optional ai-task git worktrees |
| Order | `backlog-order` / explicit-deps | **Iterative waves**: `plan --auto-batch` by default (or `--batch N` when user fixed N), not full `backlog-order` every wave |
