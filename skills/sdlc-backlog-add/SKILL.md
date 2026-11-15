---
name: sdlc-backlog-add
description: Add one new task to BACKLOG.md in the project task format with stable ordering and implementation-ready context. Use when the user asks to add a backlog task, insert a todo into BACKLOG.md, or expand a phase without rebuilding the entire plan.
---

# Add backlog task

Add a single implementation-ready task to the backlog store. Contract: `.ai-task/docs/ai-task-backlog-contract.md` (profile: `docs/`) (**explicit-deps** scheduling).

**How the task gets written (file store).** If the repo has a file-per-task store (`backlog/tasks/*.md` populated, `backlog/index-skeleton.md` present), do not hand-author the file. Run `add`, which writes `backlog/tasks/<TASK-ID>.md`, refreshes the id registry and regenerates the index, in that order:

```bash
python scripts/backlog-store.py add WEB-152 --phase "Phase 3: Search" --title "…" --context "…" --dod "…" --priority P2 --size M --verify python-quick
```

In a consuming repo the tool is the vendored `.ai-task/scripts/backlog-store.py`. Add `--depends-on`, `--agent`, `--source`, `--incident`, `--docs`, `--risk` and `--status` as the task needs them; `--new-phase` opens a phase and writes its heading into `backlog/index-skeleton.md`, where you then add the preamble. The command refuses an id that already has a file, a phase heading the skeleton does not declare, and any metadata `check` would reject, so a rejected add leaves nothing behind. Never edit the generated `BACKLOG.md` by hand.

Only in a non-migrated repo (no task files) is the edit target the inline `BACKLOG.md`, hand-authored in the format below.

## Inputs to read first

1. **`BACKLOG.md`** and, when present, **`backlog/tasks/*.md`** — phases, ordering, numbering, style.
2. **`PRD.md`** and **`TECHSPEC.md`** (when present).
3. User constraints — phase, priority, dependencies, scope.

## Task format

On the file store the tool writes this shape; you choose the values. It is
reproduced here because a non-migrated repo still needs it hand-authored, and
because the values below are the ones you have to decide.

```md
- [ ] AREA-003 Task Title
Task Context
Task DOD
Priority: P2
Size: M
Depends on: AREA-001
Agent: auto
Docs: docs/techspec.md
Verify: python-quick
```

| Checkbox | Use |
|----------|-----|
| `- [ ]` | Open (default) |
| `- [~]` | Deferred — not picked by `sdlc-implement-task` or `plan` |
| `- [x]` | Done (unusual for new inserts) |
| `- [c]` | Canceled — dropped, not paused; needs a `Canceled:` line (see below) |

**Cancel, defer, or delete.** These three are easy to confuse, and picking the wrong one is how a decision gets lost.

- `- [~]` **deferred** — paused with intent, someone means to come back to it. Stays in the active backlog, on purpose: it is meant to keep being seen.
- `- [c]` **canceled** — decided against, superseded, duplicate, obsolete. Rotates to the archive like a done task, and requires `Canceled: <date> - <reason>`. `backlog-store.py check` exits 1 without that line, and `add --status c` refuses without `--canceled`.
- **delete the file** — only when the task never should have existed: a typo, a wrong id, a block created by mistake. There is no decision here worth preserving.

The test: if you cannot write the reason, it is deferred, not canceled. If the reason is worth nobody's time to read, it is a delete.

Duplicate and won't-fix do not get their own checkboxes — write them in the `Canceled:` reason (`Canceled: 2026-09-12 - duplicate of AREA-004`).

Rules:

- Keep **`AREA`** (prefix) consistent with nearby tasks.
- **Numeric suffix only** after the last hyphen: `BUG-003`, `WEB-010`. Do not use letter suffixes (`BUG-B1`, `BUG-D1`); put batch labels in the title (for example `BUG-003 [batch-B] …`).
- Pick the **next free number** in that prefix. If `backlog/id-registry.toml` exists (repo uses **sdlc-backlog-rotate**), read its `next_free` for the prefix (or run the vendored helper `python .ai-task/scripts/backlog-id-registry.py scan --json`; in the ai-sdlc-local-kit profile itself the helper is at `python scripts/backlog-id-registry.py scan --json`) — closed tasks may have been archived, so the active `BACKLOG.md` alone undercounts. **Never** pick a suffix ≤ `max_seen` for that prefix. With no registry, scan existing ids in `BACKLOG.md`.
- On the file store, `add` runs the registry update and the regeneration for you, in that order. Only in a non-migrated repo do you run the helper's `update` yourself (`python .ai-task/scripts/backlog-id-registry.py update --reason "<id> allocated"`; in the ai-sdlc-local-kit profile `python scripts/backlog-id-registry.py update ...`). It moves the floor AND rewrites the `next ids:` line of the backlog header, which nobody maintains by hand.
- **`Depends on`** — technical predecessors (comma-separated ids), or empty only when truly independent.
- **`Size:`** — use only `S`, `M`, or `L`. Never write `XL`, `XXL`, `Epic`, or similar values.
- **`Agent:`** — `auto` by default; `human` only for coordination-only work (no `ai-task run`).
- Do not set `claude`/`cursor`/`codex`/`devin` without a documented reason.
- P0/P1: add `Risk: Pn, approved YYYY-MM-DD` (or PRD ref) in Task Context.
- **`Docs:`** — the documents this task must update in the same change, or `none - <reason>`. It is how the shared rule "update dependent docs in the same task" reaches the executor, who reads the block and not the rules. Pass `--docs` when you know which documents; without it `add` writes a generic reminder on an open or deferred block, so the line is never absent, but a named document is the useful form. `check` does not require the line. If the repo guards docs mechanically, its refusal marker is what the guard reads; `Docs: none` does not replace it.

## Testable DoD when the outcome is visual

A rendered outcome - a page, a layout, a theme, a chart, an exported document - invites
an acceptance line written as a quality adjective: readable, clean, consistent, looks
right. Such a line cannot fail. Whatever ships satisfies it, so it reads as coverage
while gating nothing, which is worse than leaving it out: verify checks the diff against
the DoD, and the DoD said readable.

Write every acceptance line for a visual task as something checkable - a comparison
between two values, a presence or absence, or a number. A rendered result is checkable
headlessly far more often than it looks, because the decisive evidence is usually a
computed value or a comparison of two of them, not a screenshot.

| Instead of | Write |
|------------|-------|
| Light and dark theme are both readable | The code block background comes from the same variables as the page background, in both themes |
| The layout does not break on mobile | At 375px width the document body does not scroll horizontally: only the code block and the table scroll inside themselves |

Both lines are from one real DoD, and only the second did any work: measurement
afterwards showed the document at 375 with `pre` at 343 against a 1293 scroll width. The
first line shipped a black `github-dark` code block into the middle of a light minimal
page - the text in that block IS readable, in both themes, so the run passed the line
honestly and shipped the defect.

An adjective is not banned. It may ride along as a gloss on a checkable clause ("the code
block background comes from the same variables as the page background, so the page reads
as one surface"). The rule is that no acceptance line consists of the adjective alone.
Do not manufacture pseudo-precise numbers where a plain comparison is the honest
statement: a contrast ratio of at least 4.5:1 is a real threshold, "no more than 3
paddings" is noise.

### Checkable is not enough when the executor cannot run the check

The rule above pushes an adjective towards something checkable. It does not say WHO
checks. A line can be a sharp yes or no and still be impossible for the runner that will
be asked to prove it: a headless worker has no browser, no GUI and no renderer, so a
defect that only a real render shows is not evidence it can produce. That is found at the
gate, and it costs a verify attempt, so the corrected line may arrive when the retries
are gone.

Ask the second question right after the first: is the line checkable, and can THIS
executor run the check? Where it cannot, either restate it as a proxy the executor
computes, or move it out of the worker's DoD into your own manual acceptance. Both are
fine; leaving it in silently is not. What the executor can and cannot do is a stated list
rather than a guess, kept where the executor's own rules live. When the list does not
settle the question, ask instead of assuming.

One pair from a real request for a custom font (PT Serif instead of system-ui):

| The line as written | What a headless runner can do with it |
|---------------------|---------------------------------------|
| Contrast of at least 4.5:1 in both themes | Computable from the token values, so it stays in the worker DoD |
| No clipped glyphs, no overlapping lines, no column overflow and no substituted font on the named layout elements | Only the substituted font has a proxy the worker can compute (the built CSS names the family, the font file is served). The other three need a real render - restate them or move them to manual acceptance |

Both lines are checkable, because the author had already replaced an adjective with them.
The run still ended with its only PR closed on verify-fail, because the second line asked
for evidence the worker could not produce.

## Oversized requests

If the requested task would be XL+ ("whole phase", multi-day, several independent surfaces, or several verify profiles), do not add it as one backlog item. Split it first:

- Defer or omit the oversized parent; if it stays, use `- [~]` with a reason such as "split from XL estimate".
- Add S/M child tasks with explicit `Depends on:` links.
- Use `Size: L` only when the task has one coherent DoD, one primary `Verify:` profile, and should make visible progress within the repo stall timeout.
- Hand broad or ambiguous splits to **ai-task-product** instead of guessing.

## Placement rules

1. Insert into the most relevant phase.
2. Preserve **dependency correctness** under explicit-deps (not just visual order).
3. Create a phase heading if none fits.
4. Reorder only when required for dependency clarity.

## Selection with ai-task

When `.ai-task/` exists, the next task for delivery comes from **`ai-task plan`** or the first id in **`ai-task backlog-order`**, not the first `- [ ]` in the file. Without `.ai-task`, implement skills use **`backlog-order`** only. Place new tasks so `Depends on` and `Priority` match the intended schedule.

## Quality gates before finalizing

- **`python scripts/backlog-store.py check` exits 0** (consuming repo: the vendored `.ai-task/scripts/backlog-store.py`). This is the gate, and it runs whether or not `.ai-task/` exists. It covers what used to be listed here as prose: id shape, unique id, the metadata lines the scheduler acts on, no XL size, and a phase heading the skeleton actually declares. A mistyped heading fails here rather than forking the phase in silence.
- Context and DoD testable. For a rendered or visual outcome, every acceptance line is
  checkable rather than a quality adjective on its own, AND the executor that will be
  asked to prove it can run the check - see "Testable DoD when the outcome is visual" and
  the subsection after it. **No tool can check this line; it is the one that needs you.**
- Priority, dependencies and the phase are judgment calls the tool takes on trust. Re-read them once against the rest of the backlog before finishing.
- Where `.ai-task/` exists, `ai-task dor` remains the richer report (review registry, rebuild-invariant reminders). It is a supplement, not the gate.

## Called from sdlc-backlog-retroactive

**sdlc-backlog-retroactive** reuses this skill for task **format, id rules, metadata lines, oversized split policy, and quality gates**. It does not duplicate that content. Read this file when inserting retroactive blocks.

| Topic | sdlc-backlog-retroactive override |
|-------|------------------------------|
| Checkbox | `- [x]` (work already landed) |
| `Agent:` | `human` (post-hoc documentation, not `ai-task run`) |
| Task Context / Task DOD | From `git diff` / recent commits (what changed), not forward plan |
| Placement | Insert **before the first open `- [ ]`** (completed section); still pick the right phase heading |
| PRD / TECHSPEC | Optional; diff is the primary source |

Everything else in this skill still applies: contract id shape, `Size` S/M/L only, `Depends on`, `Verify` from peer tasks, XL+ → split via **ai-task-product**, and `backlog-store.py check` as the gate. A retroactive block is written with the same `add`, passing `--status x --agent human`.

## Output expectations

- File store: new **`backlog/tasks/<TASK-ID>.md`** plus the regenerated **`BACKLOG.md`** index (and a skeleton heading when the phase is new, whose preamble you then write). All three come from one `add`. Non-migrated repo: updated inline **`BACKLOG.md`**.
- Brief note: insertion point and dependency rationale.
