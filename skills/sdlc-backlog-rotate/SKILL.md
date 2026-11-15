---
name: sdlc-backlog-rotate
description: Archive closed backlog tasks (done `- [x]` and canceled `- [c]`), leave open and deferred ones untouched, and refresh the id registry. Use when the generated `BACKLOG.md` index has grown past what a delivery reader should load, or the user says «разбить backlog», «архивировать закрытые», «backlog rotate», «backlog слишком большой». Slims an overgrown backlog WITHOUT re-decomposing a PRD.
---

# Backlog rotate (archive closed work)

The generated `BACKLOG.md` index grows one line per task for the life of the repo, and that file is what delivery skills and agents load. This skill is a **safe rotation**: it moves **only terminal** tasks (done `- [x]` and canceled `- [c]`) into the archive and leaves **open** (`- [ ]`) and **deferred** (`- [~]`) tasks in place **verbatim** — same ids, same blocks, same `Depends on:`. It is **hygiene**, not planning.

Contract: `.ai-task/docs/ai-task-backlog-contract.md` (profile: `docs/`) → § **Archive and active backlog**.

**Two layouts, two flows (check first).** In a repo with the file-per-task store (`backlog/tasks/*.md` populated, `backlog/index-skeleton.md` present), rotation is a **file move owned by the store tool**, not text surgery: follow «Workflow (file-per-task store)» below and skip the legacy steps 2–6. Only a non-migrated repo (inline `BACKLOG.md`) uses the legacy text-surgery workflow.

## Workflow (file-per-task store)

1. Preview: `python scripts/backlog-store.py rotate --dry-run` (consuming repo: the vendored `.ai-task/scripts/backlog-store.py`). It prints N done `[x]` and C canceled `[c]` → `backlog/archive/tasks/`, M open / K deferred staying, and the index volume before and after (see «The metric» below). Done and canceled are counted apart on purpose — a rotation report must never read a cancellation as a delivery.
2. Present the counts and **wait for explicit user confirmation** (never auto-rotate).
3. Run `python scripts/backlog-store.py rotate`. The tool moves every `- [x]` and `- [c]` task file to `backlog/archive/tasks/<ID>.md` verbatim, regenerates the `BACKLOG.md` index, and refreshes `backlog/id-registry.toml` (floors now also derive from task-file names in both dirs, so nothing is lost).
4. Optional cosmetics: prune now-empty phase headings/preambles from `backlog/index-skeleton.md` (never a heading that still owns an open/deferred task), then regenerate again.
5. Report: files moved, active counts after, **index volume before and after** (that is the number the rotation was for), registry floors (`next_free` per prefix). Legacy `BACKLOG-NNN.md` archives and `INDEX.md` are not touched and no new ones are written.

## Triggers

| User says | Intent |
|-----------|--------|
| «разбить backlog», «backlog слишком большой» | Archive terminal work — check the index volume first, it decides whether rotation is even the answer |
| «архивировать закрытые», «archive closed tasks» | Same |
| «backlog rotate», «rotate the backlog» | Same |

### The metric: the volume of the generated index

**Rotate on the total volume of `BACKLOG.md`, not on how many closed tasks have piled up.** Volume is what costs: the index is the file delivery skills and agents load, and it grows one line per task forever. The closed count is not the symptom, it is only the part rotation happens to be able to remove.

Measure it. `rotate --dry-run` prints the number with the counts (`index volume: BACKLOG.md N lines (B bytes), M lines after this rotation`), or read it directly:

```bash
wc -lc BACKLOG.md
```

**Tripwire: about 200 lines.** Over that, look at the index and decide; well under it, rotation is not what the repo needs however many closed tasks are sitting in `backlog/tasks/`. The number is a prompt to look, not a law - but it is a number, so the question has an answer rather than a feeling.

**When the index is over the line, find out which part of it is big.** Only one of the three answers is rotation:

| What is big | What to do |
|-------------|------------|
| Task lines, mostly terminal (`[x]` / `[c]`) | Rotate. This is the case this skill is for. |
| Task lines, mostly open or deferred | **Not rotation.** A large live backlog is a planning problem: hand it to **sdlc-backlog-decompose** or **ai-task-product**. Archiving whatever happens to be reachable would shave a few lines and leave the actual weight in place. |
| The skeleton preamble (`backlog/index-skeleton.md`: header, archive policy, phase preambles) | **Not rotation either.** That prose is regenerated into every copy of the index; trim it in the skeleton. Worth checking first: in some repos it is the bigger half of the file. |

### Why rotation still exists after the file-per-task migration

Worth stating plainly, because the file-per-task store took away most of the original reasons and the remaining one is easy to miss.

The migration removed four of them:

- **Index size.** The active file no longer holds task blocks, so closed work does not swell it the way it did inline.
- **Id safety.** `backlog/id-registry.toml` derives its per-prefix floors from filenames in **both** `backlog/tasks/` and `backlog/archive/tasks/`. Archiving is not what stops an id from being reused.
- **Validation and scheduling cost.** `check`, `dor` and every selection path filter on open, so closed files cost nothing in either. The proof: adding a fourth checkbox state needed no scheduler change at all.
- **Merge conflicts.** File-per-task removed those by construction, not rotation.

What it did **not** remove is the one reason left: the generated index carries one line per task for the life of the repo, and that file is read into a context window on every delivery run. Rotation stopped being hygiene of storage and became hygiene of **context**. That is why the metric above is the volume of the index and not the size of `backlog/tasks/`, which only a parser ever reads.

Do **not** use this skill for: PRD re-decompose (**sdlc-backlog-decompose**), adding a task (**sdlc-backlog-add**), splitting an XL task (**ai-task-product**), or documenting shipped work post-hoc (**sdlc-backlog-retroactive**).

## Invariants (never violate)

1. **Archive both terminals.** `- [x]` done and `- [c]` canceled move out. Dropped work is finished work: leaving it active recreates the eternal `- [~]` the canceled marker was added to replace.
2. **Deferred stays active.** `- [~]` is **not** archived — it is still schedulable history the team may revisit. Leave every `- [~]` block in `BACKLOG.md`.
   **This skill does not convert anything.** Rotation never flips a `- [~]` to `- [c]` to tidy the active file — deciding a task is dropped is the owner's call, made task by task with a reason, and it belongs to **sdlc-backlog-add**'s cancel-versus-defer rule. Rotation only moves what is already terminal. If deferred blocks are piling up, say so in the report and let the owner decide; do not decide for them.
3. **Open stays active.** Every `- [ ]` block stays in `BACKLOG.md`, byte-for-byte.
4. **No renumbering.** Do not change any existing task id (open, deferred, or archived). Ids are stable forever.
5. **User confirms before any write.** Show pre-flight counts and wait for a yes.
6. **Single scheduling source stays `BACKLOG.md`.** `ai-task plan` / `backlog-order` never read the archive.

## Archive layout (one documented rule)

File-per-task store: archived tasks live as **`backlog/archive/tasks/<TASK-ID>.md`**, one file each, moved verbatim by the store tool — the rest of this section describes the LEGACY inline layout only.

- Archive files: **`backlog/archive/BACKLOG-NNN.md`**, three-digit, zero-padded. First rotation is `001`.
- **Next number** = (max `NNN` found by scanning `backlog/archive/BACKLOG-*.md`) + 1; `001` when the directory is empty or missing.
- **Block placement rule (chosen, documented):** each rotation appends a **flat** section to the new archive file:

  ```md
  ## Archived from active YYYY-MM-DD (BACKLOG-NNN)

  <every `- [x]` block, in original file order, with all metadata lines>
  ```

  We do **not** reproduce the original phase headings inside the archive. The flat dated section keeps provenance (date + archive number) without trying to mirror the active file's evolving phase structure. (If you ever need the original phase for an audit, `git log -p backlog/archive/BACKLOG-NNN.md` and the source commit hold it.)

- **`backlog/archive/INDEX.md`** — one table row per archive file (newest last):

  ```md
  # Backlog archive index

  | Archive | Date | Commit | Moved [x] | Moved [c] | Active open | Active deferred | Reason |
  |---------|------|--------|-----------|-----------|-------------|-----------------|--------|
  | BACKLOG-001.md | 2026-06-07 | a1b2c3d | 42 | 0 | 6 | 3 | Phase 1–17 closed; slim active file |
  ```

  `Commit` is the short sha at rotation time (`git rev-parse --short HEAD`); optional, leave blank if not in git.

## Who reads the archive

Rotation must not blind history-facing tooling, and must not leak into scheduling:

| Reader | Sees archive? | Notes |
|--------|---------------|-------|
| `ai-task plan` / `backlog-order` / `dor` (delivery path) | **Never** | Schedule from active `BACKLOG.md` only (regression-tested) |
| Recurrence / sibling-rate (`decision analytics`, retro) | **Merged** | Active + `backlog/archive/BACKLOG-*.md`, de-dup by id, **active file wins**; unreadable archive ⇒ visible warning, degrade to readable files |
| `ai-task report` dashboard (`scripts/analytics.py`) | **Merged** | Archived tasks marked as history (milestone `ARCH`, phase `Archived`, Archived stat); warning banner on read failure |
| `scripts/check-delivery-artifacts.py` | **Merged** | Archived ids still resolve in artifact checks; also guards the generated index |
| sdlc-backlog-retroactive, sdlc-spec-sync | **On demand** | Read-only history when reconciling |
| sdlc-backlog-add / sdlc-backlog-decompose | **Via registry** | Never re-read archives for ids; `backlog/id-registry.toml` is the floor |

The audit-reader glob is overridable per repo via policy `[analytics] archive_glob` (default `backlog/archive/BACKLOG-*.md`).

## Workflow (legacy inline BACKLOG.md only)

### Step 0 — read state

Read `BACKLOG.md`. Scan `backlog/archive/` for existing `BACKLOG-*.md` (max `NNN`, existing `INDEX.md`). Read the active header so you can update it.

### Step 1 — pre-flight counts (blocking confirmation)

Count task **blocks** (a block = a checkbox line plus its following metadata lines up to the next checkbox or heading):

- **N** = `- [x]` blocks → will move to archive.
- **M** = `- [ ]` blocks → stay in active.
- **K** = `- [~]` blocks → stay in active.

Present, then **wait** for explicit confirmation:

> Rotation preview → `backlog/archive/BACKLOG-NNN.md`:
> - **N** completed `[x]` to archive
> - **C** canceled `[c]` to archive
> - **M** open `[ ]` staying active
> - **K** deferred `[~]` staying active
> Proceed? (yes/no)

If the user says no, stop. Never auto-rotate.

### Step 2 — write the archive file

Create `backlog/archive/BACKLOG-NNN.md` with the flat `## Archived from active YYYY-MM-DD (BACKLOG-NNN)` section containing every `- [x]` and `- [c]` block (checkbox line **and** all its metadata lines: `Task Context`, `Task DOD`, `Canceled`, `Priority`, `Size`, `Depends on`, `Agent`, `Verify`) in original order. Copy verbatim — do not edit the blocks, and never rewrite a `[c]` checkbox to `[x]` on the way in.

### Step 3 — slim the active `BACKLOG.md`

Remove exactly the `- [x]` and `- [c]` blocks you copied. Leave every `- [ ]` and `- [~]` block untouched. If removing all tasks under a phase heading leaves it empty, you may drop the now-empty heading (optional, cosmetic) — but never drop a heading that still owns an open/deferred task.

### Step 4 — update the active header

The active `BACKLOG.md` header must document:

```md
# Backlog

Active since: YYYY-MM-DD
Supersedes: backlog/archive/BACKLOG-NNN.md
Id registry: backlog/id-registry.toml (next ids: WEB-029, API-062, …)

Archive policy: delivery skills read only this file. Consult `backlog/archive/*`
only on explicit user request, or from retro / audit / sync skills
(sdlc-backlog-retroactive, sdlc-spec-sync). `ai-task plan` / `backlog-order` never
read the archive.
```

`Active since` is today; `Supersedes` is the archive file you just wrote (latest rotation). Cite the registry path and the current per-prefix floors.

### Step 5 — refresh the id registry (mandatory)

Recompute per-prefix floors across active `BACKLOG.md` **and** every `backlog/archive/BACKLOG-*.md`, then write `backlog/id-registry.toml`:

The registry helper is vendored by `ai-task init` into the gitignored `.ai-task/scripts/`. Invoke the vendored copy; **when working in the ai-sdlc-local-kit profile itself** (which has no `.ai-task/`) run the tracked source at `scripts/backlog-id-registry.py` instead:

```bash
# target repo (vendored): use .ai-task/scripts/…
python .ai-task/scripts/backlog-id-registry.py update --reason "rotation BACKLOG-NNN"
# preview without writing:
python .ai-task/scripts/backlog-id-registry.py scan --json
# ai-sdlc-local-kit profile itself: the same commands run as
#   python scripts/backlog-id-registry.py update --reason "rotation BACKLOG-NNN"
#   python scripts/backlog-id-registry.py scan --json
```

The helper takes the **first** id token on each task checkbox line as authoritative (prose mentions are ignored), stores `max_seen` and `next_free` (= max + 1, zero-padded, min 3 digits), and records both `BACKLOG.md` and the archive files as `sources`. It also rewrites the `next ids:` line of the human-readable header itself, in the skeleton or in `BACKLOG.md` depending on the layout — do not edit that line by hand. When it reports that the skeleton changed, run `backlog-store.py regenerate` so the index picks the new numbers up.

### Step 6 — update the archive index

Append (or create) the `backlog/archive/INDEX.md` row for `BACKLOG-NNN.md` with date, short sha, the counts from Step 1, and a one-line reason.

### Step 7 — report

Tell the user: archive file written (path + N blocks), active counts after (M open, K deferred), registry floors (`next_free` per prefix), and INDEX row added. Remind that the commit is theirs to make (or follow the repo's commit flow if they ask).

## Id continuity (why the registry matters)

After rotation the slim active file no longer shows archived ids, so a naive "next free number = max in BACKLOG.md" would **reuse** an archived id. The registry is the floor: **never allocate a new task id with a suffix ≤ `max_seen` for that prefix.** `sdlc-backlog-add` and `sdlc-backlog-decompose` read it before picking an id.

## Out of scope

- Changing `ai-task plan` backlog path (stays `BACKLOG.md`).
- Moving `- [~]` blocks to archive.
- Renumbering open/deferred ids.
- Auto-rotating without the Step 1 confirmation.

## Related skills

- **sdlc-backlog-add** / **sdlc-backlog-decompose** — read `backlog/id-registry.toml` (or run the helper: `.ai-task/scripts/backlog-id-registry.py scan`; `scripts/backlog-id-registry.py scan` in the ai-sdlc-local-kit profile) before allocating an id.
- **sdlc-backlog-retroactive**, **sdlc-spec-sync** — may read `backlog/archive/*` when reconciling history.
- **ai-task-product** — XL split / decompose (not hygiene).
- **ai-task-teamlead** — schedules from active `BACKLOG.md` only; never plans from the archive.
