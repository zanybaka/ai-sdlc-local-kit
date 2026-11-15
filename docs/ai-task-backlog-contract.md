# Backlog task contract (ai-task)

Source of truth: the backlog store — `backlog/tasks/<TASK-ID>.md` in a migrated repo (one task block per file; root `BACKLOG.md` is then a generated read-only index), or inline `BACKLOG.md` in a repo that has not migrated. The orchestrator reads metadata inside each task block; it does not invent priorities or dependencies.

## Scheduling mode: explicit-deps

| Source | Role |
|--------|------|
| `Priority:` | P0–P3; lower index runs first among eligible tasks |
| `Depends on:` | Comma-separated task ids; all must be `- [x]` before this task is eligible |
| File order | Tie-break only when priority is equal |

Do not rely on «first `- [ ]` in the file» for scheduling. Use **`ai-task plan`** or **`ai-task dor`** when `.ai-task/` exists; use **`ai-task backlog-order`** when it does not (implement skills, no init required).

## Task id format (required)

The checkbox line must match the parser:

```text
- [ ] PREFIX-123 Short title
```

| Part | Rule | Valid | Invalid |
|------|------|-------|---------|
| `PREFIX` | Uppercase letters, digits, hyphens (`BUG`, `WEB`, `API-V2`) | `BUG-003` | `bug-003` |
| Numeric suffix | Digits only after the last hyphen | `BUG-003`, `WEB-010` | `BUG-B1`, `BUG-D1`, `BUG-01a` |
| Title | Non-empty text after the id (same line) | `BUG-003 Auto confirm-risk` | `- [ ] BUG-003` alone |

Batch or theme labels (for example «batch B») belong in the **title** or Task Context, not in the id token.

Lines that look like tasks but break this format are **ignored** by `plan`, `run`, and `backlog-order`. **`ai-task dor`** and **`plan --strict`** report them as DoR failures (`field: Task id`, `action: fix_task_id_format` in `--json`).

## Canonical task block

Every open task uses this shape (metadata after Task DOD):

```md
- [ ] AREA-001 Short title
Task Context
Implementation scope, files, constraints. For P0/P1 add: Risk: P1, approved YYYY-MM-DD (or PRD ref).
Task DOD
Testable completion criteria.
Priority: P2
Size: M
Depends on: AREA-000
Agent: auto
Docs: docs/techspec.md
Verify: python-quick
```

| Field | Required | Notes |
|-------|----------|-------|
| Checkbox | yes | `- [ ]` open, `- [x]` done, `- [~]` deferred, `- [c]` canceled |
| Task Context | yes | Scope and surfaces (web UI names for e2e) |
| Task DOD | yes | Commands, files, or behavior |
| `Priority:` | yes | P0–P3 |
| `Size:` | yes | S, M, L only; XL+ is a split signal, not a valid value |
| `Depends on:` | yes (line) | Empty value allowed (`Depends on:` or `none`) |
| `Agent:` | yes (line) | Default `auto`; `human` = no `ai-task run` |
| `Verify:` | recommended | Profile name from policy; omit → `default_profile` |
| `Source:` | optional | Provenance: `planned` (default) \| `incident` \| `monitoring` \| `owner` \| `retro`. Omit for normal delivery |
| `Canceled:` | required on `- [c]` | `<date> - <reason>`; rejected on any other checkbox |
| `Incident:` | required if `Source: incident` | `<ref> <sevN> (<signal + impact>)`; ties post-release work to the signal that raised it |
| `Docs:` | optional | The docs this task must update, or `none - <reason>`. `add` writes it on every open or deferred block, with a generic reminder when `--docs` is not given, so the shared rule "update dependent docs in the same task" is visible in the block. Never required by `check`: blocks without it stay valid. A repo that guards docs mechanically keeps its own refusal marker; this line does not replace it |

### Metadata ownership (delivery vs product)

These four lines are **backlog metadata**. **ai-task-product** owns them (discovery, post-decompose pipeline, DoR fixes, W6 handoffs). During delivery, **ai-task-teamlead** may apply **mechanical, validator-named fixes** inline — Size bucket normalization (`Size: XS` → `Size: S` when only S/M/L are allowed and scope is plainly small), task id format renames (`fix_task_id_format`), removal of dead `Depends on:` ids — with one **mandatory** journal row: `decision log --phase cross --choice mechanical_metadata_fix` naming task id + field + old→new. **Judgment calls** — scope mismatch, split/defer, priority changes, `Verify:` profile semantics, which S/M/L bucket actually fits the scope — stay with product: teamlead logs `delivery_feedback` and waits.

| Field | Who edits in delivery |
|-------|------------------------|
| `Priority:` | product (judgment) |
| `Size:` | teamlead for validator-named bucket normalization (journal row required); product for scope-based sizing and splits |
| `Depends on:` | teamlead for dead-id removal (journal row required); product for dependency design |
| `Verify:` | product (profile semantics) |

Task Context and Task DOD prose may be tightened by either role when scope is unclear. **Silently patching metadata to force delivery remains forbidden** — the `mechanical_metadata_fix` journal row is what makes an inline fix non-silent.

### Delivery record: Progress line and task report

A closed task carries a `Progress:` line right under its title: the date, DONE, and what was delivered and how it was verified. This line, the `CHANGELOG.md` entry and the commit are the required record. A report at `tasks/<TASK-ID>.md` (path configurable in policy `[handoff]`) is written on demand, only when there is something to keep beyond them: measurements, a live probe log, the reason for a decision. `ai-task status` does not count a missing report as a gap; `ai-task complete --require-report` fails closed for a task whose DoD asks for one. See `docs/ai-task.md` (task reports and release contract).

### Size playbook

`Size` is an estimate and routing hint, not the wave batch size. It never replaces `Priority` or `Depends on` for scheduling.

| Size | Use for | Delivery rule |
|------|---------|---------------|
| S | One surface, one verify profile, expected to finish well under the repo stall timeout | Runnable |
| M | Default implementation slice: a few files or one vertical feature slice | Runnable |
| L | Upper bound for one headless run | Runnable only when the task still has one verify profile and one coherent DoD |

Do **not** write `XL`, `XXL`, `Epic`, or similar values in `Size:`. XL+ means the unit is too large for one run and must be split by product before teamlead delivery. Prefer deferring the oversized parent (`- [~]`, reason: split from XL estimate) and adding S/M children with explicit `Depends on:` links.

`ai-task dor --json` reports invalid sizes with `action: "split_required"`. Do not normalize XL+ to `L`; that hides oversizing and can turn long healthy runs into `stalled` runs under `supervision.stall_timeout_seconds`.

### Priority playbook

| Level | Use for |
|-------|---------|
| P0 | Production outage, security, breaking contract |
| P1 | Blocks critical path for the feature |
| P2 | Normal implementation (default) |
| P3 | Polish, docs, optional cleanup |

P0/P1 need a **Risk:** line in Task Context (product records approval date or PRD reference). Headless `run` may still require `--confirm-risk` per policy.

### Agent routing

| `Agent:` | Meaning |
|----------|---------|
| `auto` | Project routing; host inference when enabled, then configured fallbacks |
| `claude` | Prefer Claude Code CLI |
| `cursor` | Prefer Cursor agent |
| `codex` | Prefer native Codex CLI in new policies; legacy policies preserve Codex-backed Cursor through agent_map |
| `devin` | Prefer Devin CLI (`devin` backend) |
| `human` | Coordination only; teamlead does not `run` |

Do not set `claude`/`cursor`/`codex`/`devin` in the backlog unless there is a strong reason. Product may set `human` for merge handoff or review-only tasks. `human` also covers post-hoc documentation blocks (retroactive `- [x]` entries) — there is no separate `manual` value.

Policy sync preserves existing Codex aliases. For adoption and rollback, follow the Upgrade an existing project section in docs/ai-task.md. The backlog format and Agent enum are unchanged.

A wave-level `ai-task pin <backend>` overrides every task's `Agent:` for the pinned wave; `Agent: human` still refuses to run.

### Provenance: `Source:` and `Incident:`

Provenance makes post-release/ops work **machine-distinguishable** from planned delivery, so a headless runner and analytics can tell reactive work from planned. Both lines are **optional** — a task with no `Source:` line is `planned`, so existing backlogs stay valid.

| `Source:` | Meaning | Extra |
|-----------|---------|-------|
| `planned` | Normal decomposed delivery (default) | — |
| `incident` | Reactive post-release fix for a live breach | **requires** `Incident:` line |
| `monitoring` | Proactive from a signal/trend before an outage (capacity, cert/secret expiry) | — |
| `owner` | Owner-requested operational work | — |
| `retro` | Improvement raised by ai-task-retro | — |

`Incident:` carries `<ref> <sevN> (<one-line signal + impact>)`, e.g. `Incident: INC-YYYY-MM-DD-01 sev1 (heartbeat flatline, front down 12m)`. Severity maps to Priority by convention (`sev1→P0, sev2→P1, sev3→P2, sev4→P3`) — a **judgment**, not enforced by DoR; P0/P1 still need the standard `Risk:` line. **ai-task-ops** owns this stage (signal → triage → intake → post-mortem); see `skills/ai-task-ops/SKILL.md`.

### Depends on inference (product)

After TECHSPEC decomposition, **ai-task-product** infers technical dependencies (contract before impl, shared lib before consumer, predecessor in the same phase). File order alone is not enough for `plan` when tasks are reordered or parallel.

## Per-task files (`backlog/tasks/`) — the canonical store

File-per-task is the canonical store. When `backlog/tasks/*.md` is populated it is the ONLY source of task blocks; the old dual-read is retired. Parallel task creation and status flips touch distinct paths and merge without conflict by construction.

- One task file holds exactly one standard task block, in the same grammar as inline `BACKLOG.md` (checkbox line, Task Context / Task DOD prose, `Key: value` metadata lines). No frontmatter, no new record syntax.
- The filename equals the task id: `backlog/tasks/<TASK-ID>.md`.
- **Phase membership** is the file's optional first line: the `## <phase heading>` the task belongs to, followed by a blank line, then the block. The block parser reads it exactly as it read the heading in the old inline file, so `Task.phase` (packets, analytics, index grouping) survives migration with zero parser changes. A file without a heading parses fine; its task lands in a generated `## Unphased` index section.
- Ordering semantics: priority first, then file order — files are read sorted by filename, so the tie-break is deterministic.
- Duplicate ids abort loudly. A task file whose id already exists in another task file makes `plan`, `dor`, and `backlog-order` exit naming both files. An inline task block found in `BACKLOG.md` alongside a populated store also aborts loudly with the migration remedy — silent shadowing is exactly the merge hazard this store removes.
- A repo with no `backlog/tasks/` files keeps the original inline `BACKLOG.md` behavior unchanged (consuming repos migrate on their own schedule via `backlog-store split`).
- `backlog/archive/` stays invisible to delivery readers, including the archived task dir (`backlog/archive/tasks/`); audit readers (recurrence, dashboard, delivery-artifact check) merge it.

### Canceled (`- [c]`) — the negative terminal

The backlog knew open, deferred and done. Dropped work had no state: it was either a deleted line, which takes the reason with it, or an eternal `- [~]`, which is indistinguishable from paused-with-intent. `- [c]` is that missing terminal.

- **Never selected.** Like every non-open status, it is skipped by `plan`, `dor`, `backlog-order`, and the implement skills. Nothing has to be taught this: selection keys on open, not on a list of exclusions.
- **Rotated like done**, not kept like deferred. See "What rotation moves" below.
- **Counted as dropped, not delivered.** Analytics maps it to `canceled`, keeps it out of the burndown target, and shows it as its own tile. It never falls into the `open` bucket.
- **Owes a reason.** A `- [c]` block must carry `Canceled: <date> - <reason>`, and `check` exits 1 without it. This is the one state whose entire content is the explanation, so it is validated on the block itself rather than on open blocks the way the DoR keys are. Without the line, `[c]` is just a quieter delete.

**One marker, not one per reason.** Duplicate and won't-fix are written in the `Canceled:` reason, not given checkboxes of their own. Every extra done-like state has to be taught to selection, rotation, the index regex, the registry and analytics, and it buys information a reason string already carries. The market convention that motivates the terminal (Linear's Canceled/Duplicate categories, Azure DevOps Removed) is about reporting honesty, and one honest terminal delivers it.

**Cancel, defer, or delete.**

| Situation | State |
|-----------|-------|
| Paused with intent, will be revisited | `- [~]` deferred, stays in the active file |
| Decided against, superseded, duplicate, obsolete | `- [c]` canceled with the reason, rotates to archive |
| Never was a task — a typo, a wrong id, a block created by mistake | delete the file; there is no history worth keeping |

If you cannot write the `Canceled:` reason, the task is probably deferred, not canceled.

**Consuming repos** pick the marker up when the vendored store tool and the tracked guard are refreshed (`ai-task init`, or `backlog-store guard`). A guard generated before the `- [c]` marker existed does not know `- [c]` and will reject the checkbox — regenerate it before using the marker there.

### The generated index (root `BACKLOG.md`)

In a migrated repo, root `BACKLOG.md` is a **regenerated read-only index** owned by the store tool (`scripts/backlog-store.py` here; vendored as `.ai-task/scripts/backlog-store.py` in a consuming repo that migrates; the logic lives in `ai_task.backlog_store`):

- `add` — writes ONE new `backlog/tasks/<ID>.md` from arguments (`--phase`, `--title`, `--context`, `--dod`, `--priority`, `--size`, `--verify`, plus `--depends-on` / `--agent` / `--source` / `--incident` / `--docs` / `--risk` / `--status` / `--canceled` as needed; an open or deferred block always gets a `Docs:` line, the reminder when `--docs` is omitted; `--status c` and `--canceled` are required together and refused apart), then refreshes the id registry, then regenerates the index. That order is not advice: the registry helper rewrites the skeleton's `next ids:` line and the index is a projection of that skeleton, so regenerating first publishes an index advertising the id just taken. Refuses an id that already has a file, a phase heading the skeleton does not declare (`--new-phase` opens one and writes the heading into the skeleton), any metadata `check` would reject, and a tree where no registry helper is reachable — a refused add leaves no file, no moved floor and no regenerated index. The helper is looked up in the target repo, `scripts/` first and then `.ai-task/scripts/`, and then beside the running tool. The tracked `scripts/` copy goes first because in the ai-sdlc-local-kit profile a gitignored vendored copy may predate a fix; a consuming repo has no `scripts/` helper and uses its vendored copy. The lookup beside the tool means `add --repo .` from a git worktree without `.ai-task/` still moves that tree's floor. Allocate the id from the registry floor first.
- `split` — one-time migration: moves every inline block into `backlog/tasks/<ID>.md` byte-for-byte (with its `## <phase>` heading on top), extracts the non-task lines (header, phase headings, preambles) into **`backlog/index-skeleton.md`**, regenerates the index, refreshes the id registry.
- `regenerate` — rebuilds `BACKLOG.md` from skeleton + task files. Task entries are one-liners so humans keep the overview: `- [x] [WEB-012](<task file path>) Title`, grouped under the skeleton's phase headings (sorted by id within a phase; phases unknown to the skeleton are appended so nothing can vanish). The id sits inside a markdown link on purpose: the block parser cannot match an index entry as a task, so the index is structurally inert for every reader.
- `check` — the store gate, and it runs with or without `.ai-task/`. Exits 1 on four things: (1) `BACKLOG.md` differing from a fresh regeneration, the hand-edit guard; (2) a task filed under a phase heading `backlog/index-skeleton.md` never declared, which otherwise forks the phase in silence, since an unknown heading becomes a new phase by construction and a typo is indistinguishable from a real new phase to the generator; (3) an open block missing the metadata the scheduler acts on (`Priority`, `Size`, `Depends on`, `Agent`, plus `Verify` where no **tracked** policy `default_profile` can supply it: a gitignored `.ai-task/policies/` exists only in the operator's checkout, so it counts nowhere and the local verdict equals CI's), or carrying `Size: XL`; (4) a canceled (`- [c]`) block with no `Canceled:` reason. These are the checks that used to live only behind `ai-task dor`, which needs `.ai-task/` — in a repo without one they were not skipped but unreachable. `backlog-order` refuses the same blocks, so nothing is scheduled on a `Priority` nobody wrote. Enforced by the test suite (`tests/test_backlog_store.py`, `tests/test_backlog_store_add.py`) and by `scripts/check-delivery-artifacts.py`, so a hand edit — or task-file edits without a regeneration — fails CI. The index header carries a static generated-file marker naming the regenerate command; deliberately **no content hash in the marker** (a per-content hash line would make every pair of concurrent regenerations a guaranteed merge conflict — the exact failure this store removes).
- `guard` — writes the **tracked** CI guard `scripts/backlog-index-guard.py`: the same `check`, bundled into one stdlib-only tracked file so a consuming repo's CI — which never checks out gitignored `.ai-task/` — can run it as `python3 scripts/backlog-index-guard.py check`. `split` writes it during migration and `ai-task init` refreshes it; `guard --check` exits 1 when that copy is missing, stale, or hand-edited. Never re-implement this check in a consumer: the guard is the layout tool itself, a hand-written one is a second source of truth. See docs/ai-task.md, "The tracked index guard".
- `rotate` — see sdlc-backlog-rotate below.

Editing rule for every writer (skills, run packets, humans): **a NEW task comes from `add`; an EXISTING task is edited in `backlog/tasks/<ID>.md`, followed by `regenerate`. Never edit `BACKLOG.md` directly.** New phases: `add --new-phase` writes the heading into `backlog/index-skeleton.md`, and you write its preamble there.

### Merge behavior (the reason this store exists)

Replayed conflict shapes (pinned in `tests/test_backlog_store.py`), replacing hand-resolved BACKLOG.md merges:

- Parallel task add + status flip in different phases: merges clean, and the merged index already equals a fresh regeneration — no post-merge step.
- Add + flip in the SAME phase can still put two index one-liners on adjoining lines and textually conflict — but only in the generated index, never in a task file. Resolution is mechanical, not judgment: take either side of `BACKLOG.md` (`git checkout --ours BACKLOG.md`), run `regenerate`, commit. No task block can be lost this way.
- Two edits to the same task file conflict loudly, as they must.

## Definition of Ready (DoR)

Checked by **ai-task-product** before handoff and by CLI:

```bash
ai-task dor
ai-task plan --strict
```

`run` refuses tasks that fail DoR. See `docs/ai-task.md`. DoR also validates provenance: an unknown `Source:` value fails, and a `Source: incident` task with no `Incident:` line fails (`action: add_incident_ref`).

### Shared-contract rebuild invariants

Some invariants needed to rebuild a system from scratch live OUTSIDE the DoD of the task that changes the contract: a shared onboarding label set, a rebuild runbook, an operator checklist. Verify checks only that task's own DoD, so a cross-cutting rebuild invariant is silently dropped. Seen in practice: a new `bug` label was never added to the repo's onboarding label set, and the operator-checklist owner-steps snapshot went stale. Neither was in any task's DoD, both were found only by a from-scratch rebuild audit.

When a task changes a SHARED CONTRACT, the DoR step imprints the matching rebuild invariant into the task's DoD. The contract classes and their rebuild docs are named here so the check is not guesswork. This is the single source of truth; the mechanical detector lives in `scripts/ai_task/backlog.py` (`SHARED_CONTRACT_CLASSES`), and the verify skill points back here.

| Contract class | Signal in the task | Rebuild doc | DoD invariant to imprint |
|----------------|--------------------|-------------|--------------------------|
| Label | new/added/defined label, new метка (добавить метку) | the onboarding label set (canonical label-bootstrap list) | add the new label to the onboarding label set |
| n8n node | a node added to an n8n workflow (needs an `n8n` mention) | the n8n workflow rebuild runbook | add the node to the rebuild runbook |
| Endpoint | new/exposed endpoint or API/HTTP route (not a frontend router route) | the API-surface list or operator rebuild checklist | add the endpoint to the API-surface list / operator checklist |
| Env var | new env var, environment variable, or a named deploy variable (e.g. `DATABASE_URL` near an env/deploy/secret context) | the env template (`.env.example`) or deploy env doc | add the variable to the env template / deploy env doc |
| Wire format | new/changed wire format, protocol version, or message/payload schema | the protocol/schema rebuild doc | update the protocol/schema rebuild doc |

Two levers use this table:

- **DoR (advisory).** `ai-task dor` emits a soft note (not a blocking gap) for each open task whose text signals a shared-contract change but whose block never names the matching rebuild doc. `dor --json` carries the same list under `rebuild_invariant_reminders`. It is keyword-driven, so it WARNs rather than blocks, following the same lesson as the risk-keyword scan: a keyword false positive must not gate delivery. **ai-task-product** authors the invariant into the DoD before handoff (see `reference-pipeline.md`). To silence a genuine non-match, name any rebuild doc in the block or mark the invariant not-applicable (`n/a`).
- **Verify (completeness).** When a diff touches a shared contract, verify requires the matching rebuild doc to be updated in the same PR or explicitly marked not-applicable. This widens the doc policy from "docs" to "rebuild docs". See `skills/sdlc-verify-dod/SKILL.md`.

## Batch delivery (waves vs full-queue preview)

**Default (ai-task-teamlead):** iterative **waves** — each wave uses `plan --auto-batch` (and `parallel-plan --auto-batch` when N>=2), then verify → review → verdict, then re-plan from live `BACKLOG.md`. Product may change tasks between waves.

Operator summary for wave execution: `docs/ai-task-delivery-waves.md`.

Remember:

- Wave batch size (`plan` result) is not the same as parallel runtime cap (`parallel.max_concurrent`).
- Teamlead dispatches runs manually per sub-wave; there is no `run-wave` command.

```bash
ai-task plan --auto-batch
ai-task parallel-plan --auto-batch --json   # when N>=2
```

Wave sizing policy (`[batch]`) is shared by both commands:

- `--batch N`: `min(N, max_size, eligible_count)`
- `--auto-batch`: `min(auto_target, max_size, eligible_count)`
- No batch flag: `min(default_size, max_size, eligible_count)`

Bundled defaults: `default_size = 1`, `auto_target = 5`, `max_size = 5`.
Use no batch flags only for single-task debug paths. Bulk delivery waves should use `--auto-batch`.
`plan` picks the wave slice size; `parallel-plan` then decides sequential vs `parallel_waves` and groups sub-waves with `[parallel].max_concurrent`.

**Full-queue preview** (optional, not every wave):

```bash
ai-task backlog-order [--strict] [--json]
```

Use `backlog-order` for «покажи всю очередь», **sdlc-implement-all** (IDE), or explicit **monolithic** ship. Not file order.

## Archive and active backlog

The store under `backlog/tasks/` (or inline `BACKLOG.md` where not migrated) is the primary scheduling source. When closed work piles up, the **sdlc-backlog-rotate** skill performs a *hygiene rotation* that moves history out without changing what is schedulable.

### Single source, read-only history

| File | Role | Who reads it |
|------|------|--------------|
| `backlog/tasks/<TASK-ID>.md` | Canonical store: one task block per file (see above) | `plan`, `run`, `backlog-order`, all delivery skills |
| `BACKLOG.md` | Generated read-only index (migrated repo) / inline store (non-migrated) | Humans for overview; never parsed for tasks when the store is populated |
| `backlog/index-skeleton.md` | Index header, phase headings, preambles | The index regenerator only |
| `backlog/archive/tasks/<TASK-ID>.md` | Read-only history: rotated-out closed task files, verbatim | Retro / audit / sync skills, recurrence, dashboard, artifact check |
| `backlog/archive/BACKLOG-NNN.md` | Legacy read-only history from pre-file-per-task rotations | Same audit readers; kept as-is, never rewritten |
| `backlog/archive/INDEX.md` | Table of legacy archive files (date, sha, counts, reason) | Humans, audits |
| `backlog/id-registry.toml` | Per-prefix id floors (active + archive, text ids + task filenames) | `sdlc-backlog-add`, `sdlc-backlog-decompose`, `sdlc-backlog-rotate` |

`ai-task plan` / `dor` / `backlog-order` **never** read `backlog/archive/*`.

### What rotation moves (and what it must not)

- **Rotation is a file move** in a migrated repo: `python scripts/backlog-store.py rotate` moves every closed (`- [x]`) task file to `backlog/archive/tasks/<ID>.md` verbatim (phase heading and all), regenerates the index, and refreshes the id registry. No text surgery. Legacy `BACKLOG-NNN.md` archives are not touched and no new ones are written.
- **Canceled (`- [c]`) rotates with done.** Dropped work is finished work: leaving it in the active file recreates the eternal `- [~]` the marker replaces. The preview counts the two apart (`N done [x] and M canceled [c] -> archive`) so a cancellation is never reported as a delivery.
- **Deferred (`- [~]`) stays active.** It is revisitable history, not closed work — never archived.
- **Open (`- [ ]`) stays active**, verbatim.
- **No renumbering.** Existing ids (open, deferred, archived) are stable forever.
- **User confirms** the pre-flight counts (`rotate --dry-run`: N done `[x]` and C canceled `[c]` → archive, M open / K deferred staying, plus the index volume before and after) before the real run; no auto-rotation.

**What rotation is for, after the file-per-task migration.** The migration removed most of the original reasons: the active file no longer holds task blocks, the id registry derives its floors from filenames in both task dirs so archiving is not what protects an id, `check` / `dor` / selection all filter on open so closed files cost nothing, and file-per-task removed the merge conflicts by construction. What is left is that the generated index carries one line per task for the life of the repo, and that file is read into a context window on every delivery run. So the trigger metric is the **total volume of `BACKLOG.md`** — reported by `rotate --dry-run`, tripwire about 200 lines — and not the count of closed task files, which only a parser ever reads. When the volume is in open task lines rather than terminal ones the answer is decomposition (`sdlc-backlog-decompose`, `ai-task-product`), and when it is in the skeleton preamble the answer is trimming that prose; neither is a rotation. See the **sdlc-backlog-rotate** skill for the full rule.

The skeleton header documents `Active since:`, `Supersedes:`, the registry path with current floors, and the archive-read policy above.

### Id continuity (id registry)

After rotation the slim active file no longer lists archived ids, so picking "max id in `BACKLOG.md` + 1" would **reuse** an archived id. The registry prevents that:

- The helper - `.ai-task/scripts/backlog-id-registry.py` in a consuming repo, `scripts/backlog-id-registry.py` in the ai-sdlc-local-kit profile - scans active `BACKLOG.md`, every `backlog/archive/BACKLOG-*.md`, **and** the task-file names in `backlog/tasks/` and `backlog/archive/tasks/` (the filename IS the id, so even an emptied rotated file still floors its id). In text scans the **first** `PREFIX-NNN` token on each task checkbox line is authoritative (prose-only mentions are ignored).
- It stores per-prefix `max_seen` and `next_free` (= max + 1, zero-padded to repo convention, min 3 digits) in `backlog/id-registry.toml`.
- **The registry is tracked, the helper is not**. `.ai-task/` is gitignored, so a fresh clone has the floors and no generator. The generated header names whichever helper path exists in that repo, falling back to the vendored one, and says to run `ai-task init` when the file is missing - so a stale registry has a documented recovery instead of a guess.
- **Never allocate a new task id with a suffix ≤ `max_seen` for its prefix.** `sdlc-backlog-add` and `sdlc-backlog-decompose` read the registry (or run `backlog-id-registry.py scan`) before choosing an id.
- **Regeneration is event-driven, not per-delivery:** the registry refreshes on id allocation (`sdlc-backlog-add` / `sdlc-backlog-decompose` scan-on-allocate) and on rotation (`sdlc-backlog-rotate`) — its only consumers. Delivering a task never allocates an id, so task DODs must not require an "id registry regenerated" step.

When `backlog/archive/` does not exist, everything behaves as before: the registry (if present) reflects only `BACKLOG.md`, and `scripts/check-delivery-artifacts.py` resolves ids against `BACKLOG.md` alone. After rotation, that checker also scans `backlog/archive/*.md` so a delivered id present only in the archive does not false-fail.

### When agents may read the archive

- **sdlc-backlog-retroactive**, **sdlc-spec-sync** — may consult `backlog/archive/*` and `INDEX.md` when reconciling specs/changelog with history.
- **ai-task-product**, **ai-task-teamlead** — plan only from active `BACKLOG.md`; do not pull tasks from the archive.

## Related skills

- **sdlc-backlog-decompose** — phases and Task Context/DOD; product runs metadata passes after.
- **sdlc-backlog-add** — full block for every new task.
- **ai-task-product** — post-decompose pipeline (priority, verify, inferred deps).
- **ai-task-teamlead** — iterative waves; `dor` / `plan --strict` at start and after backlog edits.
- **sdlc-implement-task** — Step 0: if `.ai-task/` exists use `plan`; else **`backlog-order`** (first id), not file order.
- **sdlc-implement-all** — full **`backlog-order`** list (with or without `.ai-task`; `--strict` only when init exists).

Contract choices: explicit deps, the full block always, strict CLI DoR, product-inferred deps.
