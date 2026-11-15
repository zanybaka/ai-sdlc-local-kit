---
name: sdlc-backlog-retroactive
description: Create [x] backlog tasks for uncommitted or recently committed changes that were done without prior planning. Use when the user says "добавь постфактум задачи", "задокументируй что сделано", "retroactive tasks", or asks to add backlog entries for uncommitted/untracked work.
---

# Retroactive backlog

Universal skill for repos on the shared stack (`AGENTS.md`, `BACKLOG.md`, `CHANGELOG.md`). Document work that shipped without a backlog task, backfill changelog, commit docs, then optionally commit code.

## Reuse sdlc-backlog-add (required)

**Read and follow `skills/sdlc-backlog-add/SKILL.md`** (or the synced copy under `~/.cursor/skills/sdlc-backlog-add/`) for every task block:

- Task format template, checkbox/id rules, metadata lines (`Priority`, `Size`, `Depends on`, `Agent`, `Verify`)
- Oversized / XL+ split policy
- Quality gates (`backlog-store.py check`, which runs with or without `.ai-task/`)

**Do not re-derive format from memory.** Section **Called from sdlc-backlog-retroactive** in that skill lists only the retroactive overrides:

| Override | Value |
|----------|--------|
| Checkbox | `- [x]` |
| `Agent:` | `human` |
| Context / DOD | From diff (delivered behaviour), not a forward plan |
| Placement | Before first open `- [ ]`, in the best phase section |

Contract file: `.ai-task/docs/ai-task-backlog-contract.md` (referenced by sdlc-backlog-add).

Also follow workspace **`AGENTS.md`** (dependent docs in the same pass) and **sdlc-docs-update** for CHANGELOG / ADR / `tasks/[TASK-ID].md` when the repo uses them.

## When to use

- Uncommitted working-tree changes to document before committing.
- Recent commits (since a sha or date) with no matching backlog task.
- After an exploratory session with ad-hoc fixes or features.

## Step 1 — gather the diff surface

Run in parallel:

```bash
git status --short
git diff --stat           # unstaged
git diff --staged --stat  # staged
git log --oneline -20     # recent commits for context
git log --oneline <base-sha>..HEAD  # if user named a sha
```

Read **`AGENTS.md`**, **`BACKLOG.md`**, **`CHANGELOG.md`**, and (per sdlc-backlog-add) **`PRD.md` / `TECHSPEC.md`** when they inform scope.

From BACKLOG/CHANGELOG learn: max id per prefix, style, existing ids in commit subjects, Unreleased changelog bullets to avoid duplicating.

If the repo has been rotated (**sdlc-backlog-rotate**), the active `BACKLOG.md` no longer shows closed work. To pick a correct next id and to avoid documenting an already-archived task twice, consult `backlog/id-registry.toml` (per-prefix `next_free` floors) and, when reconciling history, `backlog/archive/BACKLOG-*.md` + `backlog/archive/INDEX.md`. Retro is one of the few skills allowed to read the archive — use the registry floor, never "max id in active BACKLOG.md", when allocating ids.

## Step 2 — group changes into logical tasks

Group by **intent**, not by file or commit:

| Group type | Examples |
|------------|----------|
| New feature | popup on click, search cycling, new mode |
| UX polish | chevron badge, cursor change, transition timing |
| Persistence | persist window size, persist sort order |
| Bug fix | centering on first open, scroll jump on collapse |
| Config / data | new config entry, status mapping, sort order |
| Minor multi-fix | several tiny UI fixes in one `BUG-*` ticket |

Rules:

- One group = one backlog task. Two distinct surfaces at L size → two M tasks with `Depends on` (sdlc-backlog-add split policy).
- Skip: pure refactors with no user-visible change, reverts, merges, chore-only with no backlog story.
- If a group would be XL+ per sdlc-backlog-add, split before writing blocks ( **ai-task-product** if unclear).

## Step 3 — write Task Context and DOD from the diff

Per group, read the actual diff (`git diff <sha>^..<sha> -- <files>` or `git diff -- <files>`), then write Context and DOD that satisfy sdlc-backlog-add (testable, specific paths/functions).

Retroactive DOD must also include:

1. Visible behaviour that changed.
2. A verify command that exits 0 (reuse `Verify:` profile from peer tasks when unsure).
3. `CHANGELOG.md` Unreleased bullet for this task id.

Do not copy commit messages verbatim — synthesize from the diff.

## Step 4 — insert tasks into the backlog store

For **each** group:

1. Apply **sdlc-backlog-add** (id, metadata, quality gates, store layout) with retroactive overrides from its **Called from sdlc-backlog-retroactive** section.
2. File-per-task store (`backlog/tasks/*.md` populated): write each retro block with `python scripts/backlog-store.py add <ID> --status x --agent human …`, which writes the file, refreshes the registry and regenerates the index; never edit the generated `BACKLOG.md`. Non-migrated repo: insert inline **before the first open `- [ ]`**; preserve headings; do not reorder unrelated tasks.

Run **`python scripts/backlog-store.py check`** after the batch and fix what it names. It is the gate, and it does not depend on `.ai-task/` existing. Where `.ai-task/` is present, `ai-task dor` adds the richer report on top.

## Step 5 — update CHANGELOG.md

For each new task id, add under **`## Unreleased`**:

```md
- PREFIX-123: Short user-visible summary (not a file list).
```

Follow existing changelog order. One bullet per id. Mandatory for retroactive work even when `tasks/[TASK-ID].md` is optional.

Any task id used later in a **code** commit subject must already exist in both BACKLOG and CHANGELOG.

## Step 6 — commit backlog and CHANGELOG.md

One commit, all backlog-store files touched (task files, regenerated index) plus the changelog:

```
chore(docs): add retroactive tasks <id-range>
```

(or the repo's doc-commit style from `git log`). Do not bundle with code commits.

## Step 7 — commit the code (required; do not skip)

After the docs commit, if `git status` still shows code changes beyond BACKLOG/CHANGELOG, ask:

> "Код ещё не закоммичен. Закоммитить сейчас по одному коммиту на задачу? (да/нет)"

Do not finish without committing code or an explicit **no** (then warn what remains).

**If yes:**

- Dependency order when `Depends on` applies.
- One commit per task id; shared files go in the earliest task's commit.
- Subject: **`PREFIX-123: short summary`** (same id as BACKLOG/CHANGELOG). Read `git log` (**commit-current-changes**); use `feat()`/`fix()` only if the repo already does.
- `git add` untracked files explicitly.

## Quality checklist

From **sdlc-backlog-add** (ids, metadata, Size S/M/L, dor when applicable), plus:

- [ ] Every changed file covered by at least one task.
- [ ] Context/DOD grounded in the actual diff.
- [ ] Every new id has a CHANGELOG Unreleased bullet.
- [ ] Code commits use `PREFIX-123: …` when step 7 runs.
- [ ] BACKLOG + CHANGELOG committed together, separate from code.
