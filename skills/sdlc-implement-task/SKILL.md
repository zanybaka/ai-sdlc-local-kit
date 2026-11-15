---
name: sdlc-implement-task
description: Run the next open task from BACKLOG.md (`- [ ]` only; skip `- [~]` and `- [x]`) with minimal in-scope changes, verification, and doc updates. Use when the user wants one backlog task shipped, "next task", or same intent as the Cursor slash command /sdlc-implement-task.
---

# Implement a single task

Use this skill as the core single-task delivery flow. Additionally load when relevant:

1. **`sdlc-contract-guard`** — contracts, schemas, or public APIs change.
2. **`sdlc-verify-dod`** — checks and Definition of Done before handoff.
3. **`sdlc-docs-update`** — changelog, ADRs, task reports.

Scheduling: **`.ai-task/docs/ai-task-backlog-contract.md`** (**explicit-deps**: `Priority` + `Depends on`; file order is tie-break only).

## Step 0 — detect `.ai-task/`

Before any `ai-task plan`, `dor`, or `run`, check from repo root whether **`.ai-task/`** exists (for example `[ -d .ai-task ]`).

| Result | Action |
|--------|--------|
| **Absent** | **Backlog-only mode.** Run **`ai-task backlog-order`** (works without init) for scheduling. Do **not** call `plan`/`dor`/`run`. If you already ran `plan` and saw init error, ignore it and use `backlog-order`. |
| **Present** | Run **`ai-task plan`** (or `plan --strict` when DoR gates apply). |

## ADR decision gate (required)

Create or update an ADR when **any** condition below is true:

1. Materially different architectural approaches (WebView vs native, sync vs async, monolith vs split).
2. Long-lived platform/framework dependency that affects future choices.
3. Public contract change needing migration or coordinated consumers.
4. Deployment, trust boundary, data boundary, or security model change.
5. PRD/TECHSPEC **ADR-CANDIDATE** realized in this task.

Do **not** create an ADR for local, easily reversible details.

## BACKLOG.md task line status

| Checkbox | Meaning |
|----------|---------|
| `- [ ]` | Open |
| `- [x]` | Done — skip |
| `- [~]` | Deferred — skip |

## Pick the next task

### When `.ai-task/` exists (ai-task repo)

1. From repo root, run **`ai-task plan`** (use **`ai-task plan --strict`** if the project uses strict DoR).
2. Implement the **first task id** from the plan output (eligible under Priority + `Depends on`), not the first `- [ ]` in file order.
3. If plan prints no eligible tasks, read `Blocked by dependencies` / run **`ai-task dor`** and hand off to **ai-task-product** or **ai-task-teamlead** — do not pick another open line silently.

Wrapper example: `scripts/ai-task.sh --repo "$REPO_ROOT" plan`

### When `.ai-task/` is absent

1. Run **`ai-task backlog-order --json`** (or plain `backlog-order`) from repo root.
2. Implement the **first task id** in that output (same deps → priority → file tie-break as with `plan`).
3. If the list is empty, report no open tasks. If stderr warns about dependency cycles, hand off to **ai-task-product** to fix `Depends on`.

Wrapper example: `python3 scripts/ai-task.py backlog-order --json`

## Steps

1. Select the task (see above).
2. Re-check PRD/TECHSPEC and **ADR-CANDIDATE** notes.
3. Implement with the **smallest change** that satisfies the task.
4. Run verification per project and **`sdlc-verify-dod`**.
5. **ADR gate** — create/update ADR or state «ADR not required» with one-line reason.
6. Flip the checkbox to `- [x]` in the task's own store file **`backlog/tasks/[TASK-ID].md`** and regenerate the index (`python scripts/backlog-store.py regenerate`; vendored: `.ai-task/scripts/backlog-store.py`) — never edit the generated `BACKLOG.md` by hand. In a non-migrated repo (no `backlog/tasks/` files) flip it inline in `BACKLOG.md`. Right under the title add a **`Progress:`** line: the date, DONE, what was delivered and how it was verified. It is required. Write **`tasks/[TASK-ID].md`** only when there is something to keep beyond the Progress line, `CHANGELOG.md` and the commit: measurements, a live probe log, the reason for a decision.
7. Update **`CHANGELOG.md`** and related docs.
8. **Closing check**, before any report that the task is done or that nothing is needed from the owner. See the section below.

## Closing check

A task is not done while its tails are still in the session: a background command, an unpushed commit, a merged branch left in origin, a finding nobody filed. The owner should not have to call `/close-chat` to find them, so the agent runs the same checks itself as the last step of every delivered task.

1. **The close-chat points.** The agent works through points "1. Фон", "2. Git" and "5. Задачи и находки" of **`skills/close-chat/SKILL.md`** for this task, and through the matching points of the "Закрытие сессии" section in the repository's `AGENTS.override.md` when it has one. That file is the only copy of the list. Read it there and do not restate it here. What the agent can fix (commit, push, branch and worktree cleanup, a task for a finding) it fixes, as close-chat says.
2. **The run of the task.** The agent goes back over the commands of this task. Every unexpected exit code and every departure from the recipe it followed (a skipped step, a retried command, a workaround, a check that passed only on the second try) is either explained from the code or the data, with the file, line or output that shows it, or filed as a backlog task. A guess is not an explanation: "probably a flake" or "the network, most likely" without evidence means the case goes into a task.
3. **The report.** The done report names what this check found and fixed, and the tasks it filed. When it found nothing, one line says so.

## Output

- Code and tests for the task.
- Updated backlog with the Progress line, changelog, ADRs as required, and a task report only when there is something to keep.
