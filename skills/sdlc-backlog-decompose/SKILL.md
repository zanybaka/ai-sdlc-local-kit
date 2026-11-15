---
name: sdlc-backlog-decompose
description: Decompose PRD and TECHSPEC into an ordered implementation backlog with phase-based tasks and task-level DoD. Use when creating or refreshing BACKLOG.md.
---

# Backlog decomposer

Create an implementation-ready backlog from PRD and TECHSPEC.

**Store layout (check first).** In a repo with the file-per-task store (`backlog/tasks/*.md` populated, `backlog/index-skeleton.md` present), each task is written to its own **`backlog/tasks/<TASK-ID>.md`** (first line the `## <phase heading>`, blank line, then the block); phase headings and preambles go into `backlog/index-skeleton.md`, and the run ends with `python scripts/backlog-store.py regenerate` (consuming repo: the vendored `.ai-task/scripts/backlog-store.py`). The generated `BACKLOG.md` index is never edited by hand. In a non-migrated repo, write the blocks inline into `BACKLOG.md` as before.

Scheduling for ai-task repos: **explicit-deps** (see `.ai-task/docs/ai-task-backlog-contract.md`; profile: `docs/`). After this skill finishes, **ai-task-product** runs the post-decompose pipeline (priority, verify, inferred `Depends on`) before delivery handoff.

## Inputs to read first

1. `docs/prd.md` (or `PRD.md`).
2. `docs/techspec.md` (or `TECHSPEC.md`).
3. Workspace-root **`AGENTS.md`**.

## Required output format

Each task block:

```md
- [ ] AREA-001 Task Title
Task Context
Task DOD
Priority: P2
Size: M
Depends on:
Agent: auto
Verify:
```

Task ids use an uppercase prefix and a **digit-only** suffix (`AREA-001`, `BUG-003`). Do not emit letter suffixes (`BUG-B1`). See `.ai-task/docs/ai-task-backlog-contract.md`.

When refreshing an existing backlog (not greenfield), do not restart a prefix's numbering from `001`. If `backlog/id-registry.toml` exists (repo uses **sdlc-backlog-rotate**), read its per-prefix `next_free` floor — or run the vendored helper `python .ai-task/scripts/backlog-id-registry.py scan --json` (in the ai-sdlc-local-kit profile itself the helper is at `python scripts/backlog-id-registry.py scan --json`) — and allocate new ids **above** `max_seen` so they never collide with archived (rotated-out) tasks.

Optional checkbox variants:

- `- [ ]` — open (default).
- `- [~]` — skipped or deferred.
- `- [x]` — done.

Use placeholder metadata on first write (`Priority: P2`, empty `Depends on:`) if product will run the metadata pass immediately. Otherwise set final values in the product pipeline.

Allowed sizes are only `S`, `M`, and `L`. Do **not** emit `XL`, `XXL`, `Epic`, or similar values. If a phase or requirement looks XL+, split it into S/M children before writing runnable tasks.

## Decomposition rules

1. Group work into major phases (initialization, data model, coding, testing, security).
2. Break each phase into implementation-ready tasks with enough context for a coding agent.
3. At the end of each phase, add cleanup, deduplication, security, and quality tasks.
4. Order tasks for a sensible build sequence; **product** will set explicit `Depends on` from TECHSPEC (file order is not enough for `ai-task plan`).
5. Never use one L task for a whole phase. Use `L` only for one coherent run with one primary verification profile; otherwise split into S/M child tasks and let product finalize dependencies.

## Output

- File store: one `backlog/tasks/<TASK-ID>.md` per task, skeleton updated with the phase headings, index regenerated. Non-migrated repo: all tasks written to `BACKLOG.md` in phase order.
- Hand off to **ai-task-product** for post-decompose metadata (do not skip before teamlead delivery).
