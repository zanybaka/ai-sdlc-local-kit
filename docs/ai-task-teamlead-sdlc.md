# AI Task SDLC: roles, delivery contours and the operator flow

This guide is for the operator who runs delivery with the `ai-task-*` skills. Skills carry the SDLC judgment and one lean CLI (`ai-task`) stays the runtime. The discipline is the same in every contour: Definition of Ready, plan, implementation, review, verify, verdict, release. What changes is who writes the code and where the gates keep their state.

## Three delivery contours

| Contour | Who implements a task | Where gates and state live |
|---------|-----------------------|----------------------------|
| **Local `ai-task`, headless** | the CLI starts a worker process in a worktree: `claude -p`, `codex exec`, Cursor or Devin | the CLI (`dor`, `verify`, `review`, `verdict`), run records and quota in gitignored `.ai-task/` |
| **Local `ai-task`, in the teamlead session** | a fresh subagent of the teamlead session. The CLI takes the lease, creates the worktree and reserves quota, but starts no process; `ai-task worker-done` records the subagent's answer | the same CLI gates, on a run without a pid |
| **GitHub wave pipeline** | a worker on a separate, semi-trusted host picks up a labelled issue and opens a PR | labels and verdict comments in GitHub, automerge on green CI; the only human gate is the approval of a production rollout |

This kit covers the first two contours. The third needs a build host of its own and is not part of this kit; its gates reuse the same review and verification skills.

## Roles

| Skill | SDLC scope | User when |
|-------|------------|-----------|
| [ai-task-product](../skills/ai-task-product/SKILL.md) | PRD, TECHSPEC, backlog, priorities, DoR | Business tie-break, product and teamlead deadlock |
| [ai-task-teamlead](../skills/ai-task-teamlead/SKILL.md) | Waves: pin, plan, run, verify, review, verdict, release | Policy risk, `ask_user`, executor mode for a large batch, deadlock, blocked CLI |
| [ai-task-reviewer](../skills/ai-task-reviewer/SKILL.md) | Three-pass review in a fresh context, `review-findings.md`, verdict input for the teamlead | Never directly; the teamlead owns the verdict |
| [ai-task-retro](../skills/ai-task-retro/SKILL.md) | Decision retrospective after a large batch, improvement tasks | The owner starts it and answers its questions |
| [ai-task-ops](../skills/ai-task-ops/SKILL.md) | A live service after release: signals, incidents, incident tasks with provenance | An incident needs an owner decision |
| [ai-task-maintainer](../skills/ai-task-maintainer/SKILL.md) | The CLI code and the default policy | A change to the tool itself |

**Default:** agents decide inside their domain. **Product fixes DoR** before the user sees delivery blockers. **The user** steps in only when one role cannot convince the other or policy requires human approval.

## Choosing the executor of a wave

Claude Code and Codex are equal. Either one can lead a wave and either one can be its worker. When neither the owner nor the project names an executor, a new policy picks the worker of the teamlead's own vendor (`routing.default_source = "host"`). A project can set `default_source = "policy"` to use its routing order instead.

The teamlead fixes the executor for the whole wave with `ai-task pin <backend>` or `ai-task pin auto`. While the pin holds, neither a rate limit nor a quota block moves a task to another vendor: the run waits or fails with a clear reason. The default policy ships an empty `limit_fallback_order`, so a fallback vendor exists only when the project sets one. The teamlead clears the pin after the wave.

The in-session executor is always an explicit choice: `--backend claude_subagent` or `codex_subagent`, a pin, or the policy's `[executor] default`. Before a batch of more than one wave or more than `[executor] ask_above_tasks` tasks, the teamlead runs `ai-task executor --tasks N --waves M` and asks the owner which mode to use when it answers `ask: yes`.

## Typical flow

```text
User idea
  → ai-task-product (sdlc-prd-interview → sdlc-techspec-interview → sdlc-backlog-decompose)
  → post-decompose pipeline (priority, verify, inferred Depends on)
  → task files backlog/tasks/<ID>.md; the BACKLOG.md index is regenerated, never edited by hand
  → ai-task dor / plan --strict
  → ai-task-teamlead (**iterative waves**: pin → plan --batch N → parallel-plan → run → verify → review → verdict → release → wave gate → repeat)
  → implement run: code, `- [x]` with a Progress line in the task file, changelog (often uncommitted); `tasks/<ID>.md` only when there is something to keep
  → teamlead W4: regenerate the index, git commit, then `ai-task complete`
```

**Default delivery** does not run the entire backlog in one pass. The teamlead finishes each wave (review and verdict per run), re-plans from the current backlog, and involves **product** when tasks are added, deferred or reprioritized between waves. A monolithic run happens only when the user asks for it.

**The backlog store.** In a migrated repository each task lives in its own file `backlog/tasks/<ID>.md`. The root `BACKLOG.md` is an index that `scripts/backlog-store.py regenerate` builds (`.ai-task/scripts/backlog-store.py` in a consuming repository), and `backlog-store.py check` fails when someone edits it by hand. A repository without task files keeps one inline `BACKLOG.md`. Contract (explicit dependencies, full metadata, index format): [ai-task-backlog-contract.md](ai-task-backlog-contract.md).

## Parallelism

| Layer | Behavior |
|-------|----------|
| **Inside one task** | Packet asks for **Claude/Cursor subagents**; ai-task does not spawn its own. |
| **Across tasks (planning)** | Build one wave batch (`plan --auto-batch` or `plan --batch N`), then run `parallel-plan --json` on that same batch. |
| **Across tasks (execution)** | Execute returned sub-waves in order; inside each sub-wave, start up to `parallel.max_concurrent` detached `ai-task run TASK-ID` in worktrees. |
| **State metadata safety** | `.ai-task/state.json` writes use file lock + leases. This serializes metadata writes, not code execution. |

Do not launch all ids from all sub-waves at once, and do not treat three `run --wait` calls in one shell as parallel.

Terminology:

- **Wave batch size** (`batch_size`, `auto_target`, up to `max_size`) controls planning input.
- **`parallel.max_concurrent`** controls concurrent runs inside one sub-wave.

See [ai-task.md](ai-task.md) and [ai-task-decisions.md](ai-task-decisions.md).

## Decision journal and maintainer loop

Teamlead records choices in `.ai-task/decisions.jsonl` (`decision log`, `result`, `reflect`, `analytics`). See [ai-task-decisions.md](ai-task-decisions.md). **ai-task-maintainer** uses aggregates to improve `parallel-plan`, policy, and verify profiles.
