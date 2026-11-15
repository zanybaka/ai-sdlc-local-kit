# Single Task Command Router

Use skill: "sdlc-implement-task".

Additional skills loaded by that workflow when relevant:
- "sdlc-contract-guard" (if contracts/schemas/APIs change)
- "sdlc-verify-dod"
- "sdlc-docs-update"

## Step 0 — detect `.ai-task/`

From repo root, check whether `.ai-task/` exists (for example `[ -d .ai-task ]`).

- **Absent:** do **not** run `ai-task plan`, `dor`, or `run`. Run **`ai-task backlog-order`** for the next task (Priority + `Depends on`). A `plan --strict` init error is expected and is **not** a workflow failure.
- **Present:** use `ai-task plan` for scheduling (see **When `.ai-task/` exists**).

## Task selection

**When `.ai-task/` exists** in the repo:

1. Run `ai-task plan` (use `ai-task plan --strict` when delivery gates apply).
2. Implement the **first task id from plan output** (Priority + `Depends on`), not the first `- [ ]` in file order.
3. If plan is empty, run `ai-task dor` and hand off to product/teamlead — do not pick another open line.

**When `.ai-task/` is absent:**

1. Run `ai-task backlog-order --json` (ordering works without init).
2. Implement the **first task id** in the output (honors `Depends on` and `Priority`, not raw file order).
3. If empty, stop; if dependency warnings on stderr, hand off to product to fix backlog metadata.

## Execution

- Execute the listed skills in order, minimal in-scope implementation.
- Re-check PRD/TECHSPEC before coding.
- Apply contract/verification/documentation gates per `AGENTS.md` and skill rules.

## Output

- Updated code and tests.
- Status flip in `backlog/tasks/[TASK-ID].md` plus the regenerated `BACKLOG.md` index (`python scripts/backlog-store.py regenerate`); in a non-migrated repo, `BACKLOG.md` inline. A `Progress:` line under the task title (required), updated `CHANGELOG.md`, ADRs when required, and `tasks/[TASK-ID].md` only when there is something to keep beyond them.
