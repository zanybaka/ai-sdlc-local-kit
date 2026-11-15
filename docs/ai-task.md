# ai-task

`ai-task` is an opt-in local orchestrator for repositories that want managed multi-agent backlog execution. It does not replace `BACKLOG.md`, `AGENTS.md`, Cursor commands, or Claude Code skills.

Use it when a repo needs more control than `/sdlc-implement-task`: prioritized batches, task packets, run state, backend fallback, review queues, cleanup records, and user notes during active work.

Do not use it when IDE chat or `/sdlc-implement-task` in one tool is enough. `ai-task` does not replace agent intelligence; it routes backlog work to vendor CLIs.

## SDLC skills (recommended UX)

You do not need to learn CLI flags. Use two skills:

| Skill | When |
|-------|------|
| **`ai-task-product`** | PRD, TECHSPEC, backlog tasks, priorities, Definition of Ready |
| **`ai-task-teamlead`** | Plan, run, verify, review, verdict, merge, cleanup |

Full flow: [ai-task-teamlead-sdlc.md](ai-task-teamlead-sdlc.md).

Operator quick guide for wave delivery: [ai-task-delivery-waves.md](ai-task-delivery-waves.md).

Teamlead examples:

- «Тимлид, статус backlog и агентов»
- «Прогони все открытые задачи через ai-task»
- «Запусти следующую задачу и дождись»

The teamlead runs `ai-task` internally in **iterative waves** (default): `plan --auto-batch` (or `plan --batch N`) → `parallel-plan --json` for that same batch → execute sub-waves in order → per-run verify/review/verdict → re-plan after backlog changes. Not a single `backlog-order` + run-all unless the selected delivery scenario says so. For Cursor-native sequential batches in the **main working tree** (chat subagents, no git worktree per task), use **sdlc-implement-all**. For batch **git isolation**, use teamlead scenario **`isolated_worktree_batch`** with `worktrees_enabled`.

### Delivery scenarios (shore interview or policy default)

For bulk intents (`ship backlog`, `run all`, `continue` with many tasks left, monolithic phrases, isolated batch), teamlead must confirm a scenario before W0:

- **Policy default fast path:** when the active policy sets `[scenario] default` to a valid scenario id, skip the interview — announce one line (`running <id> (policy [scenario] default); say «настрой сценарий» to change`) and proceed. The full picker still runs on the first-ever bulk run in a repo, on explicit user request, or when the user's wording conflicts with the stored default.
- Otherwise ask the picker questions one per message with numbered options (full Q1-Q7 only when wording is genuinely ambiguous; normally Q2 cadence + Q7 failure policy suffice — Q3/Q4 are skill-mandated constants).
- Confirm a named scenario (`wave_full`, `wave_monolithic`, `wave_monolithic_sequential`, `single_next`, `isolated_worktree_batch`) in one summary line/table.
- Wait for `yes` before starting W0/plan/run.
- Persist choice as `decision log --phase plan --choice delivery_scenario:<id>`.

If a user says `continue`, reuse the last scenario only when it is fresh and still matches intent; otherwise run a mini-interview (minimum Q2 cadence + Q7 failure policy).

### CLI scenario handshake guard

`plan --bulk` and `run --bulk` (without a specific task) enforce that a fresh `delivery_scenario:*` decision exists before proceeding:

```bash
# Check scenario freshness directly
ai-task scenario check              # exits 1 if missing or stale (>[scenario] stale_days, default 7d)
ai-task scenario check --json       # machine-readable {ok, reason, choice, at}

# Plan with handshake enforced
ai-task plan --auto-batch --bulk    # fails unless scenario confirmed

# Run with handshake enforced (bulk mode, no specific task id)
ai-task run --bulk                  # fails unless scenario confirmed

# Skip the guard (manual override, testing)
ai-task plan --bulk --no-bulk-check
```

The guard reads `decisions.jsonl` for the most recent `delivery_scenario:*` entry (choice starting with `delivery_scenario:`). If missing or older than the staleness window, the command exits non-zero with a human-readable message pointing to the teamlead picker.

Policy section `[scenario]` (added by `policy sync` to older policies):

- `default = ""` — when set to a valid scenario id (`wave_full`, `wave_monolithic`, `wave_monolithic_sequential`, `single_next`, `isolated_worktree_batch`), `scenario check` (and the `plan --bulk` / `run --bulk` guard) passes without a fresh decision and prints the one-line announcement `running <id> (policy [scenario] default); say «настрой сценарий» to change`. A fresh explicit `delivery_scenario:*` decision always wins over the default. An invalid value warns and behaves as unset.
- `stale_days = 7` — staleness window in days for `delivery_scenario:*` decisions; `scenario check --max-stale-days N` overrides per call.

Teamlead runs `plan --auto-batch --bulk` (not bare `plan --auto-batch`) for bulk delivery waves to ensure the handshake is enforced at the CLI level. The flag is optional for single-task runs (`run TASK-ID --bulk` is a no-op handshake — use bare `run TASK-ID` instead).

To change `scripts/ai-task.py`, default policy, or supervision behavior, use the **`ai-task-maintainer`** skill.

### Delivery artifact consistency guard

`scripts/check-delivery-artifacts.py` validates that recent delivery commits whose subject carries a task id have matching entries in both `BACKLOG.md` and `CHANGELOG.md`. The id prefixes it recognises are set in `TASK_ID_RE` at the top of the script; set them to the prefixes of your own backlog.

```bash
# Check last 20 commits (default)
python scripts/check-delivery-artifacts.py --repo /path/to/repo

# Check last N commits
python scripts/check-delivery-artifacts.py --since 50

# Check specific commits
python scripts/check-delivery-artifacts.py --commits abc1234,def5678

# Machine-readable output
python scripts/check-delivery-artifacts.py --json
```

Failure output names the missing task ids and target files. Exit code 1 when any mapping is missing. Wire into verify profile or CI by adding this command to the verify command list in `.ai-task/policies/default.toml`.

## Doc ownership — where rules live

**One normative home per SDLC topic; every other file points to it instead of restating.** When changing a rule, edit the owning file and keep the pointers as one-line pointers («Normative: `<file>` → `<section>`»).

| Topic | Normative home |
|-------|----------------|
| Wave lifecycle (W0–W7 loop), who decides what, scenario picker, escalation | `skills/ai-task-teamlead/SKILL.md` |
| Per-run stage gates, verdict checklist, parallelism + overlap gate, persist/resume | `skills/ai-task-teamlead/reference.md` |
| W4 review gates (UI-interaction template, real-browser evidence), run release contract, DoD evidence rules, W6 product handoff | `skills/ai-task-teamlead/reference-review-gates.md` |
| W3 operator rules: quota-aware dispatch, detached run monitoring, auto-confirm-risk, run health / status template | `skills/ai-task-teamlead/reference-operations.md` |
| Journal discipline (judgment template, when the full template is required, grading, retro cadence), `report` handoff | `skills/ai-task-teamlead/reference-journal.md` |
| CLI mechanism semantics: commands, statuses, policy keys, quota admission control / auto-resume machinery, worktree apply cadence | `docs/ai-task.md` (this file); code lives in the `scripts/ai_task/` package (domain modules: `backlog`, `backlog_store`, `index_guard`, `scheduling`, `runs`, `quota`, `decisions`, `analytics`, `policy`, `policy_edit`, `state`, `init`, `verify`, `review`, `codex_review`, `claude_settings`, `packets`, `notify`, `lifecycle`, `cli`, plus the shared helpers in `_shared`) behind a 27-line `scripts/ai-task.py` shim |
| Decision journal CLI semantics: `decision log/result/reflect/analytics` flags, auto-stub triggers, SLO machinery | `docs/ai-task-decisions.md` |
| Review procedure: fresh-context bug-finding passes, three-pass structure, `review-findings.md` contract, verdict handoff | `skills/ai-task-reviewer/SKILL.md` |
| Post-release operations: signal watch (heartbeat/capacity/expiry/error-budget), incident triage, incident→backlog intake, post-mortem handoff, ops-feedback loop | `skills/ai-task-ops/SKILL.md` |
| Backlog format, metadata ownership (incl. `Source:`/`Incident:` provenance) | `docs/ai-task-backlog-contract.md` |
| Shared-contract rebuild invariants (label/n8n/endpoint/env/wire -> rebuild doc): the contract-class table, DoR imprint heuristic, verify completeness check | `docs/ai-task-backlog-contract.md` (Shared-contract rebuild invariants); levers in `scripts/ai_task/backlog.py` `SHARED_CONTRACT_CLASSES`, `skills/sdlc-verify-dod` |
| Verify profiles and gates | `docs/ai-task-verify.md` |
| Operator command cheat-sheet for waves (commands + pointers, no normative prose) | `docs/ai-task-delivery-waves.md` |
| Skill-authoring conventions: what does not go into a skill (values of a foreign layer, case paragraphs) | `docs/skill-authoring.md` |

## Lean scope

`ai-task` is intentionally a **lean orchestrator**: backlog router, CLI launcher, run journal, and backend policy.

| You need | Use |
|----------|-----|
| Fast answer in chat, one task, one IDE | Cursor or Claude Code directly |
| Shared `BACKLOG.md`, same workflow in Cursor and Claude | `ai-task backlog-order` without init; `plan` / `run` after `init` |
| Rate-limit fallback across CLIs | Opt-in via `routing.limit_fallback_order` in `.ai-task/policies/default.toml` (off by default) and `run --wait` |
| Rich streaming UI and tool approval in the loop | IDE (not `ai-task`) |

**Non-goals:** second agent brain, autonomous daemon, semantic progress tracking, replacing background agents, auto-editing backlog without agent output.

## Install

Run profile setup once from `ai-sdlc-local-kit` ([SETUP.md](../SETUP.md)): `link-symbolic-folders` installs `ai-task` into `~/.local/bin`. Then:

```bash
ai-task --help
```

If `command not found`, add `export PATH="$HOME/.local/bin:$PATH"` to your shell profile, or call `scripts/ai-task.sh` by full path.

On Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ai-task.ps1 --help
```

## Initialize a Repo

Run this inside the target repository:

```bash
ai-task init
```

This creates `.ai-task/`:

```text
.ai-task/
  config.toml
  state.json
  inbox.jsonl
  policies/default.toml
  runs/
  packets/
  cleanup/
```

Repositories that do not run `ai-task init` are unaffected.

### Own and foreign repositories

ai-task is the operator's personal tooling, and not every repository it runs in is the operator's. Before writing anything, `ai-task init` decides ownership from the `origin` remote and prints it as `Repository ownership: own` or `foreign`, with the reason.

The remote is reduced to `host/owner/repo` (https, ssh and the `user@host:owner/repo` form all work, a trailing `.git` is dropped) and matched against the glob patterns in `own_remotes`. A pattern without a wildcard covers everything below it: `github.com/your-name` means every repository of that owner. The list is operator data, so it lives in the profile checkout and not in any target repository: `ai-task-profile.local.toml` in the profile root (gitignored), with the tracked template `ai-task-profile.example.toml` beside it. `AI_TASK_PROFILE_CONFIG` points init at a file elsewhere.

| Case | Mode | What init does |
|------|------|----------------|
| origin matches `own_remotes` | own | As before. Tracking `config.toml` and `policies/` is the operator's choice. |
| origin does not match | foreign | Writes `/.ai-task/` into `.git/info/exclude` (local, never committed, shared by all worktrees of the checkout). Touches no `.gitignore` and leaves no `.ai-task` file for git to offer. |
| no origin, a local-path origin, or no `own_remotes` | foreign | Same as above. An unknown owner gets the mode that cannot publish anything. Without `own_remotes` init also says how to configure it. |

`--ownership own` or `--ownership foreign` overrides the decision, for example when the operator confirms that a repository without a remote is theirs. An explicit `own` is remembered as `ownership = "own"` in that repository's `.ai-task/config.toml`, so the operator answers once and later runs without the flag stay own, `--force` included. `--ownership foreign` removes the recorded answer.

A foreign repository may already carry ai-task files from an earlier init. Init then prints the commands that take them out: `git rm -r --cached -- .ai-task`, the files it would untrack, and the `.gitignore` lines that name `.ai-task`. It runs none of them, since they are commits in someone else's repository. Earlier commits keep their copies; rewriting that history is out of scope. Making every repository use `info/exclude` was rejected: in the operator's own repositories a tracked policy is useful across machines.

### Bootstrap delivery docs

`ai-task init` also copies a **minimal bootstrap doc bundle** from the ai-sdlc-local-kit profile checkout (the directory holding `scripts/ai-task.py`) into the target repo's gitignored **`.ai-task/docs/`**, so that the local references skills and `dor` hints rely on resolve instead of 404ing. The manifest is `BOOTSTRAP_DOCS` in `scripts/ai_task/init.py`; the entries are the **source** paths in the profile, and each lands at the same relative path under `.ai-task/`:

- source `docs/ai-task-backlog-contract.md` → dest `.ai-task/docs/ai-task-backlog-contract.md` — backlog task format / DoR contract.
- source `docs/ai-task-verify.md` → dest `.ai-task/docs/ai-task-verify.md` — verify stack profiles reference.

Each file is copied **only when the destination is missing**; existing files (including operator edits) are never overwritten, and init lists every path it copies. Re-running `init` on a repo that already has them is a no-op for those files. `ai-task self-test` warns when an initialized repo is missing any bootstrap doc.

An earlier version moved the destination from the tracked `docs/` tree into gitignored `.ai-task/docs/` — see "Bootstrap files live under `.ai-task/`" below for the rationale and the migration note for older repos.

### Bootstrap helper scripts

`ai-task init` also **vendors profile-owned helper scripts** into the target repo's gitignored **`.ai-task/scripts/`**. The manifest is `BOOTSTRAP_SCRIPTS` in `scripts/ai_task/init.py` (source path in the profile → same relative path under `.ai-task/`); today it is:

- source `scripts/backlog-id-registry.py` → dest `.ai-task/scripts/backlog-id-registry.py` — per-prefix id floors for **sdlc-backlog-rotate** / **sdlc-backlog-add** / **sdlc-backlog-decompose**.
- source `scripts/ai-task-quota-statusline.py` → dest `.ai-task/scripts/ai-task-quota-statusline.py` — Claude Code `statusLine` helper that writes `.ai-task/quota-snapshot.json` for quota supervision.
- source `scripts/backlog-store.py` → dest `.ai-task/scripts/backlog-store.py` — the file-per-task backlog store CLI (`split` / `regenerate` / `check` / `rotate` / `guard`). Unlike the two helpers above it is not self-contained: it is a thin shim over the `ai_task` store modules, so init vendors the module subset with it — `scripts/ai_task/_shared.py`, `scripts/ai_task/backlog.py`, `scripts/ai_task/backlog_store.py`, `scripts/ai_task/index_guard.py` land under `.ai-task/scripts/ai_task/`, deliberately without the facade `__init__.py`. The shim detects the missing `__init__.py` and registers a synthetic parent package anchored on the vendored directory, so `ai_task.*` imports resolve against the vendored copies from the consuming repo's own tree, with no ai-sdlc-local-kit path anywhere.

**One exception to "vendored means gitignored": the index guard.** `ai-task init` also writes `scripts/backlog-index-guard.py` into a **migrated** consumer's tracked tree — see "The tracked index guard" below. Everything else on this manifest is operator tooling that only the delivery skills run; the guard exists for the repo's **CI**, which checks out tracked files only.

These differ from docs in two ways. (1) **Why they must be local:** the delivery skills invoke the registry helper from the *target repo's own vendored copy* (`python .ai-task/scripts/backlog-id-registry.py …`, no `--repo` escape hatch), so the file has to be present there; the quota helper also writes the repo-local `.ai-task/quota-snapshot.json` used by admission control. (The ai-sdlc-local-kit profile tracks the source of these scripts at `scripts/`, and the skills run that copy there. A profile checkout where the operator ran `ai-task init` also has a gitignored `.ai-task/` with vendored copies, which may lag behind; `backlog-store.py add` takes the tracked `scripts/` registry helper first for that reason, see `docs/ai-task-backlog-contract.md`.) (2) **Refresh, not copy-once:** a script is profile-owned tooling, not operator-editable content, so init **creates it when missing and refreshes it to the profile version when the bytes differ**. That is exactly what makes a re-run useful — an old repo initialized long ago picks up new or updated tools by simply running `ai-task init` again. Init reports each as `(created)` or `(updated)`, and `ai-task self-test` warns when a bootstrap script is missing.

For global statusLine wiring, the profile also ships `scripts/ai-task-quota-statusline-dispatch.py`. It is intentionally **not vendored** into target repos. Install that dispatcher on PATH (for example `~/.local/bin`) and use `ai-task quota setup-statusline --global` to print a repo-agnostic snippet for global Cursor/Claude settings.

### Consumer adoption runbook: file-per-task backlog

How a consuming repo migrates its inline `BACKLOG.md` to the file-per-task store (see `docs/ai-task-backlog-contract.md` for the layout contract):

1. **Re-run `ai-task init`** in the consuming repo. It vendors (or refreshes) `.ai-task/scripts/backlog-store.py` with its module subset, and refreshes `.ai-task/scripts/backlog-id-registry.py` to the current version — the registry refresh matters, because older copies do not derive id floors from task-file names and would go stale after migration.
2. **Migrate once:** `python3 .ai-task/scripts/backlog-store.py split`. This moves every inline task block into `backlog/tasks/<TASK-ID>.md` byte-for-byte, extracts `backlog/index-skeleton.md`, regenerates the `BACKLOG.md` index, refreshes `backlog/id-registry.toml`, and writes the tracked CI guard `scripts/backlog-index-guard.py` (step 5).
3. **Commit the result together:** `BACKLOG.md`, `backlog/tasks/`, `backlog/index-skeleton.md`, `backlog/id-registry.toml`, `scripts/backlog-index-guard.py`. The store data is tracked; the writer tool stays gitignored under `.ai-task/`; the guard is tracked because CI needs it.
4. **From then on everything runs locally** from the vendored copy: edit `backlog/tasks/<ID>.md`, then `python3 .ai-task/scripts/backlog-store.py regenerate`; guard with `... check`; archive closed tasks with `... rotate`. Never call ai-sdlc-local-kit's `scripts/backlog-store.py` by absolute path from another repo, and never hand-edit the generated index.
5. **Wire the guard into your CI** — one line, no dependencies beyond python3:

   ```bash
   python3 scripts/backlog-index-guard.py check
   ```

   Nothing else is needed. If the repo lints Python, the guard is already exempt by construction — do not add an `extend-exclude` for it.

Repos that skip this stay on inline `BACKLOG.md` behavior unchanged — an absent or empty `backlog/tasks/` keeps the original parser path, so each consumer migrates on its own schedule.

### The tracked index guard

The store promises that hand edits to the generated `BACKLOG.md` fail CI. The profile repository keeps that promise with its own checks. A consuming repo has none of them, and the store tool it vendors lives in gitignored `.ai-task/` — so **its CI has no copy of the checker at all**. Without a fix, every migrating consumer is pushed into hand-writing a repo-local structural checker: a second source of truth for the layout, living outside the repo that owns it. That is exactly what the store exists to remove.

So the store generates the guard instead of asking anyone to write one:

- **What it is.** `scripts/backlog-index-guard.py` is the store's own code (`_shared` + `backlog` + `backlog_store`) bundled into one stdlib-only script with a small `check` / `regenerate` / `source-hash` CLI. It is generated, never authored — the header says so, and the bundler (`scripts/ai_task/index_guard.py`) refuses to build if the store modules ever grow an import it cannot bundle, so a breakage surfaces when the guard is built rather than in someone's CI.
- **Why it is tracked.** The single deliberate exception to "tools are gitignored, data is tracked" (below): CI cannot run a tool it never checks out. The **writer** stays vendored and gitignored; only the read-only guard travels with the data it guards.
- **Where it comes from.** `split` writes it during migration; `ai-task init` writes or refreshes it in any repo that is already migrated (that is the upgrade path for a consumer that migrated before the guard existed). `python3 .ai-task/scripts/backlog-store.py guard` does it on demand. Init deliberately skips repos that have not migrated — no generated index means nothing to guard, and `check` there exits 0 with "nothing to guard" rather than false-failing.
- **Lint-exempt by construction — do not add an `extend-exclude` for it.** The bundle repeats each module's stdlib imports mid-file and keeps the profile's line width: correct for a generated file, and a wall of findings in a repo whose own code is clean. The generator emits the exemptions into the header itself — `# ruff: noqa`, `# flake8: noqa`, `# pylint: skip-file`, `# fmt: off` — so `ruff check`, `ruff format --check` and `flake8` all pass over the file with **no configuration in the consuming repo**. If a repo already carries a per-repo exclude for the guard from before this landed, remove it: it is a workaround pointing at a solved problem. The generator suppresses rather than rewriting, deliberately — the guard's value is being the store's code byte-for-byte, and a bundler that also reformatted would be a second thing to trust.
- **How staleness is caught, and by what.** Two hops, two detectors — do not expect either to cover the other. `ai-task init` refreshes the vendored modules from the profile and rewrites the guard from them, so **init is the only thing that can see that the profile moved**; because the guard is tracked, that refresh lands in `git status` instead of ageing invisibly. `python3 .ai-task/scripts/backlog-store.py guard --check` compares the tracked guard against the modules **in this repo** — it catches a hand-edited guard, or a guard left behind after an init, and it reports `fresh` on a repo that simply has not re-initialized in months. Refresh path is therefore always: re-run `ai-task init`, then `... backlog-store.py guard --check` to confirm, and commit the diff.
- **What a consumer removes after adopting it.** Any repo-local re-implementation of the index contract written while this gap was open. Delete such a checker and its test harness, and call `python3 scripts/backlog-index-guard.py check` from your CI workflow instead. That stopgap was temporary by construction; the guard is the replacement, and it cannot drift from the layout because it *is* the layout tool.

The script's **location** is operator tooling, but the **data** it manages is tracked: `backlog-id-registry.py` only ever reads/writes `BACKLOG.md`, `backlog/archive/`, and `backlog/id-registry.toml` (all tracked), so moving the tool under `.ai-task/` has no effect on what it produces — see the data-vs-tool split below.

Re-running `init` is **data-safe**: everything under `.ai-task/` (`state.json`, `decisions.jsonl`, `inbox.jsonl`, `config.toml`, `policies/`) is left untouched unless you pass `--force`; only bootstrap docs (when missing) and bootstrap scripts (when missing or stale) are topped up.

**Bootstrap files live under `.ai-task/` (gitignored) — reproduced by `ai-task init`, not committed.** The vendored docs and scripts land under the target repo's `.ai-task/` directory, which is gitignored like the rest of that operator-local tree. They are **operator tooling**, not part of the repo's tracked toolchain: only the Claude Code delivery skills use them (teammates and CI don't), and they are fully reproducible by re-running `ai-task init`, so there is nothing to commit and a fresh clone or CI runner doesn't need them. A profile refresh just re-vendors on the next init.

**Data vs. tool — what stays tracked.** The bootstrap files are *tools* and live under gitignored `.ai-task/`. The **data those tools produce stays in tracked locations**: `BACKLOG.md`, `backlog/archive/`, and `backlog/id-registry.toml`. `backlog-id-registry.py` reads and writes only those tracked paths, so moving the script itself under `.ai-task/` changes nothing about the data it manages — the registry `.toml`, the active backlog, and the archive are versioned and shared as before. Keep the split crisp: **tools are reproducible and gitignored; the backlog data they manage is tracked.** The one exception, and the reason it is an exception, is `scripts/backlog-index-guard.py`: it is read-only, generated, and exists for the repo's CI — which never checks out `.ai-task/`. Tracking it is what makes the hand-edit guard real outside ai-sdlc-local-kit; it changes nothing about the rule for the writer tools. The wider `.ai-task/` runtime tree (`state.json`, `runs/`, `packets/`, `cleanup/`, `worktrees/`, `inbox.jsonl`, plus the vendored `docs/`+`scripts/`) is machine-local — `config.toml` / `policies/` (and `decisions.jsonl`, if you want delivery analytics) are tracked at the operator's discretion in an own repository, and never in a foreign one (see "Own and foreign repositories" above).

**Migration for repos initialized before this change.** Older repos may still have tracked copies at `scripts/backlog-id-registry.py` and `docs/ai-task-*.md` (the previous destination). `ai-task init` now vendors to `.ai-task/` and prints a note listing any leftover old copies; you may **delete those old tracked files** — init does not remove them for you, and nothing executable references them anymore. The delivery skills use the `.ai-task/` paths going forward.

**Profile-only (not bootstrapped):** the full `docs/ai-task.md`, teamlead/SDLC playbooks under `docs/`, and the skills under `~/.claude/skills`. These stay on the ai-sdlc-local-kit profile and are not vendored into target repos. Profile-only helper scripts such as `check-delivery-artifacts.py` and `worktree-preflight.py` run from the profile against any repo and are likewise **not** vendored. The review registry (`skills/ai-task-reviewer/registry.json`) is not copied either — `load_review_registry` falls back to the profile copy when the repo has none.

## Core Commands

```bash
ai-task plan --auto-batch
ai-task plan --batch 3
ai-task parallel-plan --auto-batch --json
ai-task run WEB-001 --dry-run
ai-task run WEB-001
ai-task run WEB-001 --wait
ai-task status
ai-task status --json
ai-task quota status
ai-task quota status --json
ai-task quota doctor
ai-task quota doctor --json
ai-task quota refresh
ai-task quota refresh --json
ai-task wait-runs <run-id>...
ai-task wait-runs <run-id>... --resume-on-quota
ai-task watch <run-id>
ai-task watch <run-id> --follow
ai-task pause <run-id>
ai-task resume <run-id>
ai-task stop <run-id>
ai-task supersede <run-id> --by <later-run-id> --reason "delivered by the later run"
ai-task note "new user input" --run-id <run-id>
ai-task note "scope hint" --task-id TASK-001
ai-task review <run-id>
ai-task cleanup --dry-run
ai-task policy backends
ai-task run TASK-001 --confirm-risk
ai-task packet refresh TASK-001
```

## Risk gates

Headless `run` blocks tasks with review gates (P0/P1 priority or risk keywords in the backlog block) unless you pass `--confirm-risk`. Teamlead should ask before using that flag.

When policy sets `ask_before_weaker_fallback_for_risky_tasks`, `cursor_auto` is not added to the backend order for risky tasks unless `--confirm-risk` is set.

## Status summary

`ai-task status` prints a one-line summary (running, failed, needs_review, leased tasks; `needs_recovery` appears when any orphaned run is awaiting recovery) and dependency blocks. `ai-task status --json` adds `summary` (including `needs_recovery_count`) and `leases`.

`status` does not check task reports, because a report is written on demand. The JSON key `missing_task_reports` is gone, and `status --require-report` is accepted as a no-op with a note on stderr, so old scripts keep running. **`complete --require-report`** still fails closed when the run's task has no report: pass it for a task whose DoD asks for one.

### Agent View vs ai-task state

Claude Code's native **Agent View** (`claude agents`, v2.1.139+) is one dashboard for sessions you dispatch through Claude Code itself: what's running, what needs input, what's done. Use it for **ad-hoc parallel sessions** — a bug fix, a review, and an investigation as three rows — with no backlog ceremony. It knows nothing about `BACKLOG.md` metadata, leases, verify profiles, review verdicts, or quota reservations.

**ai-task state** (`.ai-task/state.json` + `ai-task status`) is for **gated delivery waves**: task selection by Priority/`Depends on`, run records and leases, verify → review → verdict gates, quota admission. ai-task launches its own headless CLI processes journaled under `.ai-task/runs/` — check those with `ai-task status`, not Agent View. Rule of thumb: parallel work without verdicts → `claude agents`; backlog delivery with gates → ai-task. The two compose; neither replaces the other.

## Task leases

A started run leases its task id so a second `ai-task run` for the same id fails. Use `--take-lease` to override. Leases are local best-effort locks (IDE agents are not blocked). Each lease carries an `operator` field (from `operator_identity`; legacy rows read as `unknown`) so the refusal message names the holder («leased by run Y, operator Z»). They remain per-clone and machine-local — see «Two operators» below for the multi-machine posture (cross-machine locking is out of scope; the git conflict at push is the guard).

## State file concurrency

`state.json` writes are guarded by a local file lock at `.ai-task/state.lock`. Mutating commands wait for the lock, then save with an atomic temp-file replace so a crash does not leave partial JSON.

Lock wait timeout is configurable via `AI_TASK_STATE_LOCK_TIMEOUT_SECONDS` (default: `10`). If timeout is reached, the command exits with a clear message that another `ai-task` process is holding the state lock.

The `run --wait` supervision loop polls the child process and log mtimes every `AI_TASK_POLL_INTERVAL_SECONDS` (default: `2`). This is a test/tuning knob — the CLI test suite sets it small so `--wait` tests do not pay the 2s-per-poll floor; production behavior is unchanged at the default. A missing/blank/invalid value falls back to `2`; negative values clamp to `0`. The stall-timeout threshold is in wall-clock seconds and is independent of this interval.

What is protected: atomic state writes and merge-safe updates for unrelated run records by `run_id`. What is not protected: distributed multi-host locking and cross-machine coordination.

Platforms: POSIX uses `fcntl.flock`; Windows uses `msvcrt.locking` (same timeout/poll contract). If neither module is available, a one-time warning is printed — "state locking unavailable on this platform — do not run parallel ai-task processes" — and the command proceeds without locking.

## Data durability

Everything under `.ai-task/` is **gitignored by design** — a lost disk loses all of it, and with several repos the loss surface multiplies. Per-file inventory:

| File | What is lost | Cost | Reconstructible? | In backup set |
|------|--------------|------|------------------|---------------|
| `decisions.jsonl` | months of judgment history (overrides, escalations, retro grades, anomaly stubs) | highest — feeds retro, analytics, SLO gates | no — anomaly ingest stubs can be partially rebuilt from `state.json` run records; judgment entries cannot | yes |
| `quota-telemetry.jsonl` | calibration samples (`quota calibrate` needs ~`calibration_min_samples` of them) | high — re-accumulates only over weeks of runs | no | yes |
| `state.json` | run records, verdicts, leases, quota snapshot | medium — delivered work stays visible in git history and BACKLOG checkboxes | partially — completed-task facts recoverable from git; useful source for rebuilding decision ingest stubs | yes (leases/locks inside are **machine-local** — stale data after a restore on another machine) |
| `policies/` | tuned verify profiles, thresholds, `[scenario]` default | medium — local tuning is accumulated judgment | partially — the template regenerates via `ai-task init`/`policy sync`, local tuning is lost | yes |
| `config.toml` | project id, backend, worktree flag | low | mostly — `ai-task init` regenerates, manual edits lost | yes (cheap) |
| `reports/` | decision/retro/analytics MD+HTML reports | low–medium | mostly — regenerable from the journal and state while those survive | yes (cheap) |
| `inbox.jsonl` | pending operator notes | low — transient, consumed into the next packet | no, but short-lived | no |
| `runs/<id>/` | per-run packets/logs (forensics) | low — rarely consulted after the verdict | no | no |
| `packets/` | generated task packets | none | yes — regenerated from `BACKLOG.md` | no |
| `quota-refresh.json`, `state.lock` | machine-local quota cache / lock file | none | n/a | no |
| `scripts/` (vendored helpers) | bootstrap script copies | none | yes — `ai-task init` re-vendors | no |

### Backup helper (`scripts/ai-task-backup.sh`)

```bash
# archive one or many repos into a timestamped tar (default target ~/Backups/ai-task)
scripts/ai-task-backup.sh ~/Src/repo-a ~/Src/repo-b
scripts/ai-task-backup.sh --target /mnt/usb/ai-task ~/Src/repo-a

# restore (refuses a non-empty .ai-task without --force)
scripts/ai-task-backup.sh --restore ~/Backups/ai-task/ai-task-backup-20260613-101500.tar.gz --repo ~/Src/repo-a
# multi-repo archive: name the subdir
scripts/ai-task-backup.sh --restore <archive> --repo ~/Src/repo-a --from repo-a__proj-a --force
```

- Read-only on sources; bash 3.2-compatible. Target dir is `--target`, the `AI_TASK_BACKUP_DIR` env var, or `~/Backups/ai-task`.
- Per-repo subdir inside the tar: `<basename>` or `<basename>__<project_id>` when `config.toml` has a readable `project_id`. Repos without `.ai-task` are skipped with a notice.
- A pooled telemetry file configured via an **absolute** `[quota] telemetry_path` lives outside `.ai-task/` and is not picked up — back that file up separately.

## Two operators (multi-user readiness)

The system was built for one operator. With a second person (own machine, own clone, shared git remote) every coordination surface was audited against the actual code. Verdicts: **works** (safe today), **degrades** (functions, but loses information or relies on manual discipline), **breaks** (silent collision possible).

| Surface | Behavior with two operators today | Verdict |
|---------|-----------------------------------|---------|
| Task leases | `acquire_task_lease` stores `{run_id, backend, operator, created_at}` in the per-clone `state.json` (`scripts/ai_task/lifecycle.py`) — the `operator` field (from `operator_identity`; legacy rows read as `unknown`) is stamped at acquire and the refusal message now names the holder («leased by run Y, operator Z»; `status --json` leases include it). The lease is still machine-local by design: the per-clone `state.json` is the documented isolation boundary («`state.json` locality» row, «State file concurrency»). Within one clone a second `run` for the same task is refused (override: `--take-lease`); operator B on another machine never sees A's lease, so both can start the same task and the **git conflict at push is the final guard**. | **same-machine** collision now legible (operator named); cross-machine locking **accepted out of scope** (no distributed lock by design — git conflict is the guard) |
| `state.json` locality | Per-clone and gitignored; the state lock (`.ai-task/state.lock`) is machine-local by contract (see «State file concurrency»). Two machines accumulate two disjoint run histories; neither `status` view shows the other's runs. Restoring one operator's backup on the other machine carries stale machine-local leases/pids (see «Data durability»). | works as isolation by design; **degrades** for shared visibility — no cross-machine merge tool |
| `decisions.jsonl` journal | Per-clone; every writer funnels through `new_decision_entry` (`scripts/ai_task/decisions.py`) — manual `decision log`, auto anomaly rows, and ingest stubs alike. Rows stamp an `operator` field; legacy rows aggregate as `unknown`; `decision analytics` prints an operators breakdown. Merging two journals is a manual line-union (append-only JSONL, unique ids — safe), but nothing automates it. | **degrades** — attribution fixed, sync/merge stays manual; analytics on one machine see only that machine's rows |
| `BACKLOG.md` concurrent edits | Tracked file; git is the coordination layer. Checkbox flips on distinct lines merge cleanly; same-block edits conflict loudly at pull/merge. Safe but late: nothing prevents both operators *starting* the same open task (see leases row). | **works** at the git level; duplicate-work prevention missing |
| Profile divergence | Two clones of the profile repository diverge silently in their machine-local gitignored artifacts: root `AGENTS.md` symlink, `skills/` symlinks into `~/.agents`, `.venv`, `.ai-task`. The link scripts detect a detached root-`AGENTS.md` hardlink and auto-repair the provable cases — but only when a link script runs; pulling a `context/AGENTS.md` change does not trigger it, so the second machine runs stale shared policy until its next link run. SETUP.md «Keeping a second machine in sync» documents a two-machine sync checklist — pull → `link-symbolic-folders` → `sync-third-party-skills`, with the why per step. Skills that another installer puts into `~/.agents` can also differ per machine, invisible to git. | **degrades** — divergence is pull-driven; the checklist documents the relink; no session-start auto-check |
| Shared telemetry pooling | An absolute `[quota] telemetry_path` pools samples across repos; each sample carries `repo_id` but no operator or account identity. `append_quota_telemetry_sample` (`scripts/ai_task/quota.py`) is a plain single-line append — atomic on local POSIX filesystems, not guaranteed on network mounts. Quota windows are per-Anthropic-account, so pooling samples from two operators' accounts feeds `quota calibrate` mixed-account deltas. | **works** for one operator across repos (the designed case); **breaks** if two operators share one telemetry file — keep telemetry per-operator until samples carry account identity |

The multi-operator change ships an optional `operator` field (git `user.name` → `$USER` → `"operator"`; `operator_identity` in `scripts/ai_task/decisions.py` — cached, never raises, never required) stamped on every new decision row and run record, plus an operators breakdown in `decision analytics` (text line, report header, `by_operator` in `--json`). Rows and records written before this field aggregate as `unknown`; `schema_version` is unchanged. **Lease ownership shipped** (operator stamped on each lease, named in the refusal message and `status --json`). **Profile-sync checklist shipped** (two-machine sync checklist in SETUP.md — see the profile-divergence row).

**Cross-machine duplicate-start posture (accepted residual).** Cross-machine task locking stays **out of scope by design**, not by omission. The per-clone `state.json` is the documented isolation boundary (it is gitignored and machine-local by contract — see «`state.json` locality» and «State file concurrency»), so a lease cannot and should not be made visible to another machine without a distributed lock the project deliberately does not introduce («What is not protected: distributed multi-host locking», State file concurrency section). The accepted guard remains the **git conflict at push** when two operators flip the same `BACKLOG.md` block or commit overlapping work; the new operator-named lease message plus the `operator` field make the *same-machine* collision case fully legible. No pre-run upstream-diff warn was added: it would only narrow, not close, the race (the window between fetch and start), and a partial mitigation does not justify the extra fetch plumbing when the push-time guard already exists.

With a second operator, backlog blocks are no longer self-authored: treat them as untrusted input — follow the «Untrusted backlog input» checklist (in the scope-guard section) and set `[scope_guard] mode = "require_ack"`. The shipped default stays `warn` because the solo flow gains nothing from gating self-reviewed edits.

## User notes

`note` still does not inject into a live CLI process. Pending inbox notes for a task are appended to the next generated packet automatically. Rebuild without running: `ai-task packet refresh <task-id>`.

## Worktrees

Opt-in per-run git isolation:

```bash
ai-task init --worktrees
# or set worktrees_enabled = true in .ai-task/config.toml
```

Each `run` creates `.ai-task/worktrees/<run-id>` on branch `ai-task/<task-id>-<suffix>`. Requires a git repo. After review, merge the branch, then:

```bash
ai-task complete <run-id> --remove-worktree
ai-task complete <run-id> --require-report
ai-task status --require-report
# or: ai-task cleanup --remove-worktrees
```

**`complete` prunes its own worktree.** A completed run's work is merged, so its worktree is disposable, and this is the one moment the tool knows that without asking the operator to judge anything. `complete` therefore removes the worktree by default, under exactly the guards `cleanup --remove-worktrees` uses: a dirty working tree or a branch with commits ahead is kept and printed as `worktree kept: <reason>`, never force-removed, and `complete` still succeeds. Set `[cleanup] remove_worktree_on_complete = false` in policy to keep every worktree for post-hoc inspection; `policy sync` preserves that local `false`. `--remove-worktree` remains the explicit request and overrides the opt-out, and `--force` overrides the guards on both.

Removing a worktree also deletes the run branch when it holds no commits the base lacks; an unmerged branch is kept and reported (see "Review, cleanup, and prune" for the guards).

**Run release contract:** normative: `skills/ai-task-teamlead/reference-review-gates.md` → Run release contract (implement run vs teamlead W4 — who commits, who marks `[x]` and writes the Progress line).

**Task reports (on demand):** the required record of a closed task is its `Progress:` line under the title, the `CHANGELOG.md` entry and the commit. A report at `tasks/<TASK-ID>.md` is written only when there is something to keep beyond them: measurements, a live probe log, the reason for a decision. The run packet asks for the Progress line and names the report path as optional. `complete` prints the path and whether the file is there, and reminds about a missing `[x]` or Progress line; `complete --require-report` exits non-zero when the report is missing.

Policy (`.ai-task/policies/default.toml`):

```toml
[handoff]
task_report_dir = "tasks"
task_report_pattern = "{task_id}.md"
```

A policy that still holds the old bundled default `{task_id}-report.md` gets the new one on `ai-task policy sync`. Any other pattern is the project's choice and stays. Until the sync runs, the old value only changes the path the packet names.

On **`ai-task init`**, `worktrees_enabled = true` when the repo is a git checkout (use `--no-worktrees` to disable). 

### Worktree overlap and apply cadence (ai-task runs)

**sdlc-implement-all** runs in the **main working tree** (one commit per task, sequential). It does not create per-task git worktrees and does not need merge/apply cadence between IDE subagents.

For **ai-task** batches with `worktrees_enabled` (especially parallel sub-waves or scenario **`isolated_worktree_batch`**), use a decision rule when merging finished runs into `main`:

- **Immediate merge (default):** merge each finished run before starting the next when tasks touch shared control files (`BACKLOG.md`, `CHANGELOG.md`, `docs/ai-task*.md`, `skills/ai-task-*`, `scripts/ai-task.py`, core tests) or when dependencies are tight.
- **Deferred merge (optional):** keep worktrees separate until the end only for clearly disjoint file sets or when the user explicitly asks to review branches first.
- **Switch rule:** if overlap appears during the batch, switch to immediate merge for remaining runs.
- **Always merge in dependency order** from the primary checkout branch (`main` unless repo policy says otherwise).

**Preflight overlap analyzer:** before merging multiple ai-task worktrees, run:

```bash
python scripts/worktree-preflight.py --repo /path/to/repo
# Machine-readable output:
python scripts/worktree-preflight.py --json
```

The script reports overlap between worktrees, flags high-risk shared control files, and recommends `immediate` or `deferred` apply mode with a dependency-safe apply order. Exit code 0 = deferred safe; exit code 1 = immediate required.

## Parallel safety layers

Do not conflate git merge safety with runtime state safety. They are separate layers:

| Layer | Protects | Mechanism | Notes |
|-------|----------|-----------|-------|
| **Git content isolation** | Concurrent file edits and merge safety | Per-run git worktrees (`worktrees_enabled`) | Lets multiple runs edit code concurrently without sharing one dirty tree. |
| **Runtime state metadata** | `.ai-task/state.json` consistency (`runs`, `last_batch`, cooldowns, leases) | State file lock helper + task leases | Lock serializes metadata writes; leases prevent duplicate `task_id` runs. This does not force code execution to be sequential. |

The state lock helper is owned by **ai-task-maintainer** scope.

## Backlog Selection

Scheduling mode: **explicit-deps** (see `docs/ai-task-backlog-contract.md`). `ai-task plan` reads `BACKLOG.md`, skips `- [x]` and `- [~]`, honors `Depends on`, and sorts eligible tasks by **priority first**, then file order as tie-break.

### Wave sizing (plan + parallel-plan)

`plan` and `parallel-plan` use the same batch-size resolver:

- `--batch N` → `min(N, max_size, eligible_count)`.
- `--auto-batch` → `min(auto_target, max_size, eligible_count)`.
- No batch flag → `min(default_size, max_size, eligible_count)`.

Bundled policy defaults in `[batch]` are `default_size = 1`, `auto_target = 5`, `max_size = 5`.

- `default_size = 1` is a deliberate single-task default for debug or focused runs.
- For normal bulk delivery waves, use `--auto-batch`.
- `plan` chooses wave size first; `parallel-plan` then subdivides the selected wave into sub-waves using `[parallel].max_concurrent`.
- `plan --json` and `parallel-plan --json` include `batch_size`, `eligible_count`, and `batch_reasoning`.
- Only `plan` updates `state.last_batch`.

**Repos without `.ai-task`:** `/sdlc-implement-task` and **sdlc-implement-all** use **`ai-task backlog-order`** (deps → priority → file tie-break; no init). Do not call `plan`, `dor`, or `run` until `ai-task init`. `plan --strict` without init exits with an expected error (not an IDE workflow failure). `backlog-order --strict` still requires init (DoR checks).

### Definition of Ready (CLI)

```bash
ai-task dor              # all open tasks
ai-task dor --task-id TASK-001
ai-task dor --json
ai-task plan --strict    # exit 1 if any open task fails DoR
```

Checks: task id format on every task-shaped checkbox line (`PREFIX-123` with a digit-only suffix and title; see `docs/ai-task-backlog-contract.md`), required metadata lines (`Priority`, `Size`, `Depends on`, `Agent`), valid values, dependency ids exist, P0/P1 blocks include a `Risk:` acknowledgment in Task Context.

Invalid ids such as `BUG-B1` are not parsed into the backlog model; `dor` reports `field: Task id` with `action: fix_task_id_format` in `--json`.

`Size:` accepts only `S`, `M`, or `L`. XL+ is not normalized to `L`: `dor --json` reports invalid sizes with `action: "split_required"` so product can split the parent into S/M children before teamlead delivery.

`ai-task run` applies the same checks for the selected task and refuses `Agent: human` (coordination only; do not `run`).

#### Detected stacks and risk class at DoR

`dor --json` stamps every open task with what review will key on later, so risky and stack-specific work is visible at plan time instead of after implementation. Nothing new is authored in `BACKLOG.md` - the stamp is derived from heuristics that already exist:

| Field | Meaning | Derived from |
|-------|---------|--------------|
| `detected_stacks` | registry stack ids predicted from repo markers and Task Context keywords (`review_stack` keeps its old name as an alias) | `detect_stacks_predictive` in `scripts/ai_task/review.py` |
| `risk_class` | one coarse label: `high-priority`, `shared-contract`, `risk-keyword`, or `plain` | `risk_gates` plus the contract-class detector |
| `risk_gates` | the raw gate strings the run path enforces (`high-priority:P0`, `risk-keyword:schema`, …) | `risk_gates` |
| `contract_classes` | shared-contract classes the task text signals | `rebuild_invariant_reminders_for_task` |

Precedence for the coarse label: a priority gate wins (it needs an explicit `--confirm-risk` approval), then a shared-contract class, then a bare risk keyword, then `plain`. Plain `dor` prints it inline on the `Review plan …` line as `risk=<class>`.

The same two lines land in the generated packet header, so the backend sees at dispatch what the reviewer will check afterwards:

```
Detected stacks: python
Risk class: high-priority (high-priority:P1, risk-keyword:contract)
```

Best-effort and additive: with no review registry reachable the stamp is empty and the packet is unchanged.

#### Autonomous / headless selection skips `Agent: human`

`Agent: human` marks owner-only, coordination work that an agent cannot deliver. **Autonomous/headless selection therefore never picks it**, so an unattended runner drains `Agent: auto` work instead of spending a run on a task that by definition needs the owner. This is a single lever (`autonomous_skip_reason`), so the same rule can later also defer review-gated tasks — one chokepoint, not per-command special cases.

Where the gate applies and how to trigger it:

| Command | Autonomous when | Effect on `Agent: human` |
|---------|-----------------|--------------------------|
| `backlog-order` | `--autonomous` | Dropped from the ordered queue; listed separately as an `owner-only remaining: …` note on **stderr** (JSON/stdout stays a clean dispatch list). |
| `plan` | always (a plan batch is dispatch prep) | Excluded from **every** batch — a plan batch feeds packet generation and backend selection, which cannot run an owner-only task, so a pinned/top-priority human task is skipped past instead of hard-failing; `owner-only remaining` note on stderr. |
| `parallel-plan` | always (wave dispatch) | Excluded from waves; `owner-only remaining` note on stderr. |
| `run` (no task id) | always (default = headless dispatch) or `--autonomous` | Never selected; if nothing else is eligible, the error names the owner-only ids. |
| `run <id>` (explicit) | never | Addressable by the operator; an owner-only id still hits the coordination-only refusal above. |

`dor` prints a soft `owner-only remaining: …` note (stderr, not a DoR gap) so the operator sees which tasks a headless wave will skip. A headless runner should call `backlog-order --autonomous` (or `run` with no id) so `Agent: human` tasks never enter its queue.

**Read/monitoring paths never hard-fail on a pinned owner-only `last_batch`.** The run-only refusal (`… has Agent: human — complete work manually; do not use ai-task run`) lives in `choose_backend_order`, which read paths also called through the status routing preview. So when a task reclassified to `Agent: human` was pinned in `state.json.last_batch` (or was simply the top open task), bare `ai-task status`, `ai-task wait-runs <id>`, and plain `ai-task plan` errored — the runner's monitoring and detached-run waiting became unusable until `last_batch` was cleared by hand. Now the status routing preview resolves the next *dispatchable* task (skips owner-only), `plan` excludes owner-only from every batch, and `choose_backend_order` returns an empty backend order (rather than refusing) when a read/planning caller passes it an owner-only task. Only the actual run path (`run`, packet dispatch) still refuses.

### Execution order (all open tasks)

```bash
ai-task backlog-order              # deps → priority → file tie-break (all open tasks)
ai-task backlog-order --json
ai-task backlog-order --strict     # with DoR check when .ai-task exists
ai-task backlog-order --autonomous # headless: exclude Agent: human; note owner-only on stderr
```

Use for **sdlc-implement-all** preview and optional full-queue display. **Teamlead default** uses `plan --auto-batch` each wave, not full `backlog-order` every time. Works without `.ai-task` for ordering only; `--strict` requires init. Add `--autonomous` for headless dispatch queues (see the autonomous-selection note above).

Task metadata inside each backlog block:

```md
- [ ] TASK-123 Example task
Priority: P1
Size: M
Depends on: TASK-100
Agent: auto
Task Context
...
Task DOD
...
```

Parser defaults when lines are missing: `Priority: P2`, `Size: M`, `Agent: auto`. **`plan --strict` and `run` require explicit lines** (DoR).

Product fills metadata after decomposition; see `skills/ai-task-product/SKILL.md` post-decompose pipeline.

### `Agent:` routing

| `Agent:` | Backend order (when `--backend auto`) |
|----------|--------------------------------------|
| `auto` | Explicit project order, otherwise host inference when enabled; no fallback unless configured |
| `claude` | `claude` first |
| `cursor` | `cursor_codex`, then `cursor_auto` on limits (opt-in per task) |
| `codex` | Native `codex` CLI in new policies; legacy policies preserve the Cursor alias |
| `devin` | `devin` (opt-in) |
| `human` | No `run` — manual/owner-only work; excluded from autonomous selection, refused by explicit `run` |

Override per run: `ai-task run TASK-001 --backend claude`. Override for a whole wave: `ai-task pin <backend>` (see Wave-level backend pin). Custom map: `[routing] agent_map` in policy TOML.

### `Source:` / `Incident:` provenance

Optional lines that mark where a task came from, so post-release/ops work is machine-distinguishable from planned delivery. Owned by the **ai-task-ops** post-release stage; full contract in `docs/ai-task-backlog-contract.md`.

| Field | Values / format | Notes |
|-------|-----------------|-------|
| `Source:` | `planned` (default) \| `incident` \| `monitoring` \| `owner` \| `retro` | Missing line ⇒ `planned`, so existing backlogs stay valid |
| `Incident:` | `<ref> <sevN> (<signal + impact>)` | Required when `Source: incident`; severity→Priority by convention (`sev1→P0 … sev4→P3`, `INCIDENT_SEVERITY_PRIORITY`) |

DoR (`dor` / `plan --strict` / `run`) fails an unknown `Source:` value and a `Source: incident` task with no `Incident:` line (`action: add_incident_ref`). The run packet surfaces a `Source: … · Incident: …` line so the agent sees the provenance. Parser defaults: `Source: planned`, `Incident:` empty.

## Runtime Router

The default policy:

| Role | Backend | CLI command (summary) |
|------|---------|------------------------|
| Claude worker | `claude` | `sonnet`, `--effort high`, `--print`, auto mode with no prompts (see Headless Claude permissions), `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` |
| Codex worker | `codex` | `codex exec --model gpt-6.1-sol --json --sandbox workspace-write`, high effort, approvals disabled |
| Limit fallback (opt-in) | `cursor_auto` | `cursor-agent --model auto --print --trust --yolo` — **off by default**; set `limit_fallback_order = ["cursor_auto"]` to enable |
| Opt-in Codex | `cursor_codex` | `gpt-5.3-codex-high` — **not** in default auto routing; use `Agent: cursor` or `run --backend cursor_codex` |
| Opt-in Devin | `devin` | `devin --model swe --permission-mode bypass --respect-workspace-trust false -p <prompt>` — **not** in default auto routing; use `Agent: devin` or `run --backend devin` |
| In-session Claude | `claude_subagent` | no process: a fresh Claude Code subagent of the teamlead session; `run --backend claude_subagent` or `pin claude_subagent` |
| In-session Codex | `codex_subagent` | no process: a fresh Codex subagent of the teamlead session; `run --backend codex_subagent` or `pin codex_subagent` |

**Routing order:** new projects use `routing.default_source = "host"`. After a wave pin, explicit `--backend`, task `Agent:` and custom project orders, the runner infers Codex from `CODEX_THREAD_ID` or Claude Code from `CLAUDECODE` / `CLAUDE_CODE_ENTRYPOINT`. Conflicting or missing markers use the project order. `status --json.routing.selection_reason` and run records explain the choice. Set `default_source = "policy"` to always use the configured orders. The bundled `limit_fallback_order = []` prevents automatic vendor switching. Opt-in fallback remains available; a pin suppresses it.

**Opt-in Codex:** backlog `Agent: cursor` or operator `run --backend cursor_codex` after explicit approval. Codex draws from Cursor **API pool** (monthly billing cycle), not short session resets.

**Recovery:** Claude — probe after cooldown expires. **Cursor backends** (`cursor_codex`, `cursor_auto`) — cooldown stays until `ai-task cooldown clear <backend> --force` (no timer auto-clear; `status --json` shows `sticky: true`).

### Headless Claude permissions

The bundled `[backends.claude] extra_args` launch the worker with `--permission-mode auto --permission-prompts none --settings <json>`. Auto mode decides each tool call. Whatever would wait on a permission prompt is denied, in subagents too, and the turn goes on. The settings JSON (`CLAUDE_HEADLESS_SETTINGS` in `scripts/ai_task/policy.py`) carries two groups of keys.

- `permissions.denyInsteadOfPrompting` and `permissions.blockWritesOutsideWorkingDirectories`: the Write, Edit and NotebookEdit tools refuse paths outside the worktree.
- The Bash sandbox: `sandbox.enabled`, `failIfUnavailable`, `allowUnsandboxedCommands = false` and `network` with `strictAllowlist`, `allowedDomains` and `allowMachLookup`. A shell command writes only inside the worktree and the temp folder. It reaches only `github.com`, `*.github.com`, `*.githubusercontent.com`, `pypi.org` and `files.pythonhosted.org`. Any other host is denied without a prompt, so a task that needs another domain fails and the teamlead reports it. A command cannot ask to run outside the sandbox. When the sandbox cannot start, claude exits with an error instead of running without it.
- `env`: the sandbox refuses the package caches in the home folder, so `UV_CACHE_DIR`, `UV_TOOL_DIR`, `UV_PYTHON_INSTALL_DIR`, `PIP_CACHE_DIR` and `npm_config_cache` point to `.ai-task/cache/` of the worktree (`CLAUDE_SANDBOX_CACHE_ENV`). The paths are relative, so a command run from a subfolder still writes inside the worktree, and git ignores `.ai-task/` at any depth. Each run starts with a cold cache and downloads its packages again.

Claude Code 2.1.319 or newer is required: `--permission-prompts` arrived in 2.1.259, `blockWritesOutsideWorkingDirectories` in 2.1.314, `denyInsteadOfPrompting` in 2.1.319; the sandbox keys are older. On macOS the sandbox blocks the trust service that pip and `gh` use to verify TLS certificates, and they fail with OSStatus -26276; `allowMachLookup = ["com.apple.trustd.agent"]` opens that one service. On Linux the sandbox needs `bwrap` (bubblewrap) and `socat` on PATH, and Ubuntu's AppArmor restriction on user namespaces can still keep bubblewrap from starting; then every run fails at start, and the run log names the cause.

The settings travel in argv. A project `.claude/settings.json` would not do: since 2.1.257 Claude Code ignores `defaultMode` auto or bypassPermissions there, and the worker can edit that file inside its worktree.

`quota doctor` has a `permissions` check, and `--json` carries it under `permissions` (`mode`, `ok`, `cli_version`, `min_version`, `sandbox`, `why`). It reuses the version the `login` check read. The check fails in two cases: the policy asks for this mode and the local Claude Code is older than 2.1.319, because every run would stop on an unknown option; or the sandbox is on, the host is Linux, and `bwrap` or `socat` is missing. A policy that still carries `--dangerously-skip-permissions`, or argv of its own, is reported with mode `bypass` or `custom` and passes.

In print mode Claude Code silently ignores a settings file that fails validation, so a key that a later Claude Code retypes or renames would drop the whole JSON: auto mode and the no-prompt flag would stay, the write block, the sandbox and the cache env would go, and runs would keep passing. A settings canary (`claude_settings_canary` in `scripts/ai_task/claude_settings.py`) checks this without a model call. It runs `claude --settings <file> doctor` with the inline JSON of `[backends.claude]` written to a file of its own, so an invalid user or project settings file is not blamed on the worker, and looks for every key name of the JSON outside `env` in the Claude Code binary (or `cli.js` of an npm install), because the validator lets an unknown key through. A control file with `sandbox.enabled = "yes"` must be flagged by the same doctor run; when it is not, the canary reports that it cannot tell. The check takes about two seconds.

- `quota doctor` has a `settings` check, and `--json` carries the report under `settings_canary` (`checked`, `ok`, `undetermined`, `cli_version`, `invalid`, `unknown_keys`, `last_passed_version`, `last_passed_at`, `why`). It fails on an invalid or unknown key, and when the canary cannot tell. The line names the Claude Code version the canary last passed on.
- `ai-task run`, and the auto-resume of a `waiting_quota` run, refuse to launch a claude worker on an invalid or unknown key. When the canary cannot tell, they print a warning and launch, so a changed doctor output does not stop every wave. A pass is remembered per Claude Code version and settings hash in `.ai-task/claude-settings-canary.json`, so the check runs once per new CLI version.
- `AI_TASK_CLAUDE_SETTINGS_CANARY=0` skips the canary wherever it is set; the test suite sets it so tests never run the developer's real CLI.

A key that keeps its name and type but loses its effect passes the canary. Only a live run with one model call catches that (see docs/vendor-contract.md).

On `policy sync` a local `extra_args` equal to an old bundled value is replaced with the current list: `["--dangerously-skip-permissions"]`, the first no-prompt list without the sandbox, and the sandbox list before the cache env. Any other local `extra_args` is the project's choice and stays whole (see Policy sync).

The bundled list fits Python projects. For other stacks `read_policy` adds entries to the run argv by the markers of the repository (`detect_sandbox_stacks`, `CLAUDE_SANDBOX_STACK_EXTRAS` in `scripts/ai_task/policy.py`); the policy file keeps the bundled list, so `policy sync` is unaffected.

| Stack | Marker | Added to the sandbox |
|---|---|---|
| node | `package.json` at the root or one level below, outside `node_modules` and dot folders | `registry.npmjs.org` in `network.allowedDomains` |
| xcode | `*.xcodeproj` or `*.xcworkspace` at the root, `*.xcodeproj` one level below, or `Package.swift` | `filesystem.allowWrite`: `~/Library/Developer/Xcode/DerivedData`, `~/Library/Caches/org.swift.swiftpm`, `~/Library/org.swift.swiftpm`, and the per-user temp and cache folders of macOS, which xcrun writes and which differ per user, so ai-task reads them with `getconf DARWIN_USER_TEMP_DIR` and `DARWIN_USER_CACHE_DIR` at launch |

`[backends.claude] sandbox_stacks = ["node"]` in the policy replaces detection, and an empty list turns the additions off. `quota doctor` names the stacks it added (`stack additions: node`), and `--json` carries them under `permissions.sandbox_stacks`. A stack with no row here runs with the bundled list only; a worker that needs another host or folder fails, and the teamlead reports it.

What the boundary does not stop: reads. A worker can still read any file the OS user can, credentials included, and send it to an allowed domain, for example in a GitHub gist or issue. `git push` to GitHub works if the host has credentials. Behind an LLM gateway or with telemetry off, auto mode denies the calls its server-side check cannot reach, and `claude -p` exits 1.

### Native Codex CLI

Requires `codex` on PATH, codex-cli 0.131.0 or later, and an existing `codex login`; check with `codex --version` and `codex login status`. 0.131.0 is the first release that has every flag of the policy, read in the Codex release tags on 2026-11-14; the launch contract was confirmed live with codex-cli 0.167.1. New policies enable the backend and map `Agent: codex` to it. An explicit `run --backend codex` works from either teamlead application.

The runner passes the assigned packet on stdin to `codex exec`. The policy pins `gpt-6.1-sol` and `model_reasoning_effort="high"`; operators can change the backend args. `--json` preserves events in the run's stdout log, `--output-last-message` writes `final.md` in the run directory, and the run's `final_message` field links it. Model and effort are recorded from the launch arguments. `--ephemeral` avoids an extra persistent CLI session.

Codex uses the workspace-write sandbox with `approval_policy="never"`. Operations outside its permissions fail without asking for interactive approval. If a task needs broader access, the teamlead reports the denied operation and applies the project's existing approval rules before changing permissions. Claude's permission flags remain separate. Workers have inherited parent session markers removed and receive `AI_TASK_WORKER_BACKEND` identifying the selected executor.

The plain workspace-write sandbox refuses the package caches and DerivedData in the home folder and has no network, so a Codex worker could not run `scripts/lint.sh` of a uv project or build an Xcode project. With `worker_sandbox = true` in `[backends.codex]` ai-task adds the settings of the Claude worker as `-c` arguments at launch (`codex_sandbox_args` in `scripts/ai_task/runs.py`). `shell_environment_policy.set` points `UV_CACHE_DIR`, `UV_TOOL_DIR`, `UV_PYTHON_INSTALL_DIR`, `PIP_CACHE_DIR` and `npm_config_cache` to `.ai-task/cache/` of the run directory, as absolute paths. `sandbox_workspace_write.network_access=true` with `features.network_proxy={enabled=true, mode="full", domains={...}}` starts the managed proxy of Codex, which lets through only the GitHub and PyPI domains of `CLAUDE_SANDBOX_ALLOWED_DOMAINS`; a direct connection that skips the proxy is refused by the sandbox. The stacks found by `detect_sandbox_stacks` add their `CLAUDE_SANDBOX_STACK_EXTRAS` entries: node adds `registry.npmjs.org` to the domains, and Xcode adds DerivedData, the two SwiftPM caches and the two per-user folders of `getconf DARWIN_USER_TEMP_DIR` and `DARWIN_USER_CACHE_DIR` as `sandbox_workspace_write.writable_roots`. `sandbox_stacks = [...]` in `[backends.codex]` replaces detection, and an empty list turns the stack additions off. The caches moved into the worktree, and the home caches stay closed, because a worker that can write the shared uv or pip cache could plant a package that later runs in the owner's own tools; the price is a cold cache and a download on each new worktree. The `[review.codex]` pass keeps its read-only sandbox and gets none of this. The settings come from the Codex sources (`network_config.rs` applies the domain list in workspace-write mode since 0.131.0) and were confirmed live on codex-cli 0.167.1. `network_proxy` is an experimental Codex feature: on a new CLI version, repeat the negative probe (a host off the list must be refused), because a proxy that silently stops filtering would leave the worker with open network.

The worker reads its rules from the worktree, and Codex loads them differently from Claude. In each directory Codex takes the first existing file of `AGENTS.override.md` and `AGENTS.md`, so in a repository with an override it loads the override and not the canon. Every override therefore opens with the fixed line from the canon (Project-specific overrides) that sends the agent to `AGENTS.md`, and `scripts/propagate-agents.sh` reports an override without it. All instruction files share `project_doc_max_bytes`, 32768 bytes by default. A large override with the canon on top can exceed it, and then Codex cuts the override. The policy passes `-c project_doc_max_bytes=262144`, so a large override fits in full and the canon still fits when the agent opens it. `policy sync` replaces a local `args` list that still equals an earlier template (the empty placeholder and the two earlier argv lists) with the current one; a policy that chose its own `args` keeps them whole (see Policy sync), and the operator adds the new items there by hand. Interactive Codex on the same machine needs the same value as a top-level `project_doc_max_bytes` in `~/.codex/config.toml`.

A personal Codex config does not change a worker run. The policy passes `--ignore-user-config`, so Codex does not load `$CODEX_HOME/config.toml`: its model and effort, MCP servers, plugins, `notify` command and project trust table stay out of the run, and login still comes from `CODEX_HOME`. `--strict-config` stops the run at start when a `-c` value or a project's own `.codex/config.toml` carries a key this Codex version does not know. Everything the worker needs arrives in argv. The model, effort, sandbox, approval policy and instruction budget are flags of `args`. The hooks of `$CODEX_HOME/hooks.json` still load, but their saved trust sits in the ignored config, and Codex skips untrusted hooks. With `hook_trust_from_home = true` ai-task reads the `hooks.state` entries of that one file from `$CODEX_HOME/config.toml` at launch and passes them as one `-c hooks.state={...}` argument; hooks a project carries in its own `.codex` folder get no trust. Without a readable config the argument is left out and the hooks do not run. Execpolicy `.rules` files under `CODEX_HOME` still load. A worker in workspace-write that finds no trust entry for its directory writes `[projects."<repository root>"] trust_level = "trusted"` into the personal config, the ignored one included, as a live run showed. With `trust_run_directory = true` ai-task passes `-c projects={"<run directory>"={trust_level="trusted"}}`, the same trust Codex would grant itself, and the run leaves the personal config alone.

The worker returns its final report by the worker-done contract, the same three fields that `ai-task worker-done` takes from an in-session worker: `outcome` (`success`, `failure` or `limited`), `final_answer` (the Markdown report for review) and `note` (the cause of a failure). ai-task writes the schema to `worker-done.schema.json` in the run directory and passes it with `--output-schema`, so Codex holds the final message to it. After a clean exit ai-task checks the message again: a valid report leaves its JSON in `final.json` and its `final_answer` in `final.md`, and the run records `worker_report` with the outcome and note. A reported `failure` makes the run `failed` with the worker's note. A reported `limited` puts the backend in cooldown only when the log carries a limit text; otherwise the run is `failed`, because a real Codex usage limit ends the process with an error. An invalid report is recorded as `worker_report.valid = false` with a warning in `status_note`, and the run stays `needs_review`, since the work in the worktree may still be good.

Codex loads no instructions at all in a project marked untrusted: a `[projects."<path>"]` table with `trust_level = "untrusted"` in `~/.codex/config.toml`, looked up by the working directory first and then by the repository root. A worktree under `.ai-task/worktrees/` with no entry of its own and no untrusted entry for the repository loads them, as a live probe confirmed. The worker now ignores that file and gets its trust from ai-task, so an untrusted entry in the personal config no longer stops a worker; a policy that must keep Codex off a repository disables the backend instead. An interactive Codex session still reads the entry.

Codex has no configured quota telemetry; routing reports it as unavailable. It never reserves Claude quota or uses Claude reset times. Usage limits trigger Codex cooldown and `quota_blocked`, including when a detached process exits before the monitor sees it. This does not consume a task failure; the teamlead waits or makes an explicitly authorized vendor choice. No automatic resume time is invented. Command availability is checked before launch, and failed authentication reports `codex login` through the existing credential-dead path. Account access restrictions also produce `backend_unusable` rather than failed work.

### Upgrade an existing project

`policy sync` preserves routing orders, disabled backends and `default_source`, including with `--force`. A policy without `default_source` gains `"policy"` so updating does not change its worker. It also gains a legacy `agent_map.codex = ["cursor_codex"]` unless a mapping already exists. Unupgraded policies retain that alias when read.

To adopt native Codex, sync the runtime and policy first. If the project still has the old disabled Codex placeholder (`args = []`, `workload = "future"`), remove that backend table and sync again to install the current definition; preserve any deliberate custom backend instead. Remove `codex` from `routing.disabled_backends` and ensure the backend is enabled. Set `default_source = "host"` to enable inference, and remove the legacy `agent_map.codex` entry when task metadata should select native Codex. Review `policy sync --dry-run` before applying. To roll back routing, select `default_source = "policy"` and pin the desired backend.

**Opt-in Devin:** backlog `Agent: devin` or operator `run --backend devin`. Requires the `devin` CLI on PATH and `devin auth login`. Headless dispatch uses `-p` (print) mode with `bypass` permissions and `--respect-workspace-trust false` (a non-interactive run cannot show the workspace-trust prompt). Devin bills per ACU and is **not** quota-gated — no quota source exists, so admission control does not apply. Cooldown clears on the timer (`cooldown.default_seconds`), not the sticky Cursor rule. When `ai-task run` itself is launched from inside a Devin/Windsurf agent session, the runner strips the inherited `ACP_BACKEND` variable for the spawned devin — otherwise the nested CLI authenticates against the session's ACP backend and dies "Not logged in" despite valid credentials.

### In-session executor

A teamlead can deliver tasks without headless workers, so delivery keeps working when the headless CLI token is stale or missing. On 2026-10-31 a stale local Claude login made every `claude -p` worker fail while the interactive session worked; this mode covers that case.

The backends `claude_subagent` and `codex_subagent` have `in_session = true` and no command. `ai-task run <ID> --backend claude_subagent` does everything a detached run does before launch: DoR, lease, worktree, run record, scope snapshot and quota reservation. Then it launches nothing. The run stays `running` with `in_session: true`, no pid and the note "awaiting in-session worker". The teamlead gives the run's `packet.md` and worktree to one fresh subagent of its own session; `run` prints absolute paths for the packet and for `final.md`, both in the run directory of the main checkout, so the subagent can write its answer there from the worktree. A relative `--final-file` resolves against the current directory first and then the repository root. When the subagent answers, the teamlead records the outcome:

```bash
ai-task worker-done <run-id> --outcome success --agent-id <agentId> --final-file <path>
ai-task worker-done <run-id> --outcome failure --note "<cause>"
ai-task worker-done <run-id> --outcome limited
```

`worker-done` finalizes through the same path as a detached run, so verify, review, verdict, `complete` and cleanup see an ordinary record. Success becomes `needs_review` with exit code 0 and needs a final answer, which is stored as `final.md` in the run directory. Failure becomes `failed` with the note. A limit becomes `quota_blocked`, puts the backend in cooldown and consumes no task failure.

**Model and effort.** `run` records `requested_model` and `requested_effort` from the headless backend of the same vendor (`[backends.claude]` for `claude_subagent`, `[backends.codex]` for `codex_subagent`, after `model_override`) and prints them on a `subagent:` line. The teamlead passes them as the Agent tool's `model` and `effort` parameters (Claude Code 2.1.292 and later); without them the subagent inherits the teamlead session's model and effort, or `CLAUDE_CODE_SUBAGENT_MODEL` and `CLAUDE_CODE_SUBAGENT_EFFORT`. `worker-done --agent-id <agentId>` then reads the subagent's Claude Code transcript, `projects/*/*/subagents/agent-<agentId>.jsonl` under `CLAUDE_CONFIG_DIR` or `~/.claude`, and records the model that answered and the effort of its last turn with `model_source: transcript`. A gap to the request lands in `model_mismatch`, and `worker-done` prints it as a warning. Without a readable transcript the run records `--model` and `--effort` as `reported`, and with neither the requested values as `requested`. `status --json` carries `model_source`, `requested_model`, `requested_effort` and `model_mismatch` per run. The transcript layout is not a published Claude Code contract, so a miss degrades to the fallback with a warning and never blocks the outcome.

`run --wait` is refused for these backends, and they never appear in auto routing or fallback orders: the teamlead selects them with `--backend` or `pin`. `claude_subagent` draws on the Claude subscription pool (`quota_pool = "claude"`), so it takes and releases a reservation like `claude`. `codex_subagent` bills the Codex pool and never touches Claude quota. A quota block or a cooldown never moves the task to another vendor, and an in-session run never enters `waiting_quota`, because auto-resume would launch a headless worker; it ends as `quota_blocked` and the teamlead starts it again after the reset. Supervision skips these runs, so they never get the `stalled` signal. `stop <run-id>` closes an in-session run and frees its task; `pause` and `resume` are refused because there is no process. A run nobody reports is reaped to `needs_recovery` after `[executor] in_session_timeout_seconds` (default 7200, 0 disables). A late `worker-done` on such a run still lands its outcome. `status --json.summary.awaiting_in_session_count` counts runs waiting for a worker.

The `[executor]` policy section holds the teamlead's mode choice. `default` is `headless` or `in_session`. `ai-task executor --tasks N --waves M` applies the ask rule: a batch of more than one wave or more than `ask_above_tasks` tasks (default 3) asks the owner, with `default` as the recommended answer, unless `--named` passes the mode from the request or `--no-questions` marks an intent that forbids questions. A smaller batch takes `default` without asking. The JSON result also names `in_session_backend` for the detected teamlead host. `policy sync` keeps local `[executor]` values even with `--force`.

### Wave-level backend pin

`ai-task pin <backend>` pins one backend for the whole wave. The pin lives in `state.json` and applies to every `run`/`plan` until `ai-task pin --clear`. The teamlead uses it to turn a chat-level "use Devin for this wave" into runner state instead of editing `Agent:` on every task.

Precedence while pinned:

1. The pin wins over per-task `Agent:` metadata and over `default_order`/`simple_order` — every task routes to the pinned backend.
2. An explicit `run --backend X` that disagrees with the pin is a hard error, not a silent override. `--backend <pinned>` is a no-op.
3. `Agent: human` still refuses to run — the pin overrides backend selection, not the owner-only gate.
4. **No substitution:** limit fallback (`limit_fallback_order`) and quota fallback are both suppressed. If the pinned backend is cooled down, credential-dead, or missing from PATH, the run refuses (`backend_unusable` / "no available backend") — it never moves work to another vendor. Wait for it or `pin --clear`.

`pin` takes a backend name (`claude`, `codex`, `cursor_codex`, `cursor_auto`, `devin`, `claude_subagent`, `codex_subagent`); "use Cursor" means `pin cursor_codex`. `pin auto` resolves the next eligible task's worker once and keeps an existing pin. Before using it, the teamlead groups planned tasks with different explicit Agent choices into separate waves. At the end of a wave it clears the pin, then resolves the next wave. `pin` with no argument shows the current pin; `status --json` exposes `pinned_backend` at top level and in `routing`.

### Credential-dead backends

"Binary on PATH" is not "backend can work". A fallback that is installed but never authenticated used to be advertised as `available`, get dispatched on the first limit, die in about a second, and finalize the run as `status: failed` with zero work done — an operator-configuration fault reported as a task failure.

| Concept | Meaning |
|---------|---------|
| `available` | The backend's command exists on PATH (unchanged) |
| `usable` | Enabled **and** available **and** not known credential-dead |
| `auth_patterns` | Per-backend substrings that mean "not authenticated"; policy default covers `Authentication required`, `agent login`, `CURSOR_API_KEY`, `invalid api key`, … (append-only on `policy sync`) |
| `auth_fix` | Per-backend operator instruction, e.g. `run `cursor-agent login` … or set CURSOR_API_KEY` |
| `backend_unusable` | Terminal run status: **not** a task failure, no attempt consumed |

**What happens on an auth failure.** Detection is lazy — no probe on the dispatch hot path — and gated on a **nonzero-exit** attempt, so a run that merely mentions authentication while succeeding is never reclassified. A limited attempt is still a limit (it authenticated fine); the auth branch is evaluated only after the limit branch.

1. The backend is remembered as **credential-dead** in `state.json` → `backend_credentials` (sticky until fixed, unlike the timer-based `backend_cooldowns`).
2. `run --wait` **falls through** to the next backend in the chain — a credential-dead primary opens the limit-fallback chain exactly as a cooldown does (with the bundled `limit_fallback_order = []` the chain is just the primary, so a dead primary means `backend_unusable` right away).
3. Chain exhausted (every attempt unauthenticated or limited) → the run refuses with status **`backend_unusable`** and names the fix. Not `failed`, so a headless wave does not burn attempts against a backend that can never succeed.
4. A **detached** run cannot fall through in-process; it finalizes as `backend_unusable` and the credential-dead memory routes the *next* auto dispatch past that backend.
5. Auto routing skips credential-dead backends; an explicit `--backend NAME` still dispatches to it (that is how an operator who just authenticated proves it works — a clean attempt clears the mark).

**Where you see it.** `status` **Operator alerts** name the backend, reason, and fix; `status --json` carries `backend_credentials` plus `usable` / `unusable_reason` / `fix` per backend in `backends`; `policy backends` prints `available=yes usable=no … [fix: …]`; `self-test` warns for every enabled-but-unusable backend (missing binary or credential-dead) without probing. Clear it with `ai-task cooldown clear <backend> --force` after authenticating, or just let a successful run on that backend clear it.

### Model and context notes

- **Claude:** alias `sonnet` with `--effort high`: coding runs on Sonnet, review and verdict stay with the teamlead session (2026-10-09; before that `opus` with `--effort max`, which is Opus-only in Claude Code). Extended 1M is `opus[1m]` or env overrides; ai-task keeps `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` for the standard window.
- **Which model ran:** every run record, and every entry of its `attempts`, carries `model` and `effort` read from the backend's own `--model` / `--effort` args (`null` when the args leave it to the CLI default). After a fall-through the record names the backend and model that finished the run. `run`, `run --dry-run` and the finish output print `model: <model>, effort <effort>` under `backend:`, `status` adds it to the run line and `status --json` to each run, and the review packet names it. The teamlead reports them per stage in chat, two lines per wave (skill `ai-task-teamlead`, Models in chat).
- **Cursor Codex:** pinned to `gpt-5.3-codex-high` so Cursor does not pick a newer non-Codex model via `auto`. Check `cursor-agent --list-models` and edit policy if your account differs.

Edit `.ai-task/policies/default.toml` in each target repo to match the actual CLI flags and model ids on that machine. Tune `[cooldown] default_seconds` and `gpt-5.3-codex-high` if your Cursor account exposes different model names (`cursor-agent --list-models`).

Detached runs fall back only on backend availability before launch. Waited runs (`ai-task run --wait`) also inspect output for configured limit patterns — and for credential failures (see "Credential-dead backends" above) — and try the next backend in policy order.

`ai-task status` reports process state (pid alive, exit code) and coarse log signals: `limit`, `blocked_on_user`, `stalled`. Plain `status` prints an **Operator alerts** section when backends are in cooldown or a running run hit a limit. `status --json` adds **`idle_seconds`** per active run (seconds since the last growth of any run log) and a **`routing`** object for the next eligible task (or `--task <id>`): `available_backends`, `primary_cooled_down`, `fallback_candidates`, `fallback_blocked_reason` (`none`, `confirm_risk_required`, `cooldown`, `disabled`), `earliest_ready_at`. These are not fine-grained agent progress. For interactive work, prefer IDE chat.

**Backend pid (liveness).** Every run — detached *and* `--wait` — records the backend child **`pid`** into `.ai-task/state.json` at launch, so `status --json` `pid_alive` reflects reality (a `--wait` run no longer persists `pid: null`). Liveness, not log growth, is the primary health signal: backends launch with `--print` and emit **no incremental output** (the log file stays 0 bytes until a clean exit), so a long, healthy run looks "silent" the entire time. `idle_seconds` still measures log silence, but the `stalled` *verdict* is gated on liveness (see below).

## Supervision (lean)

Configure in `.ai-task/policies/default.toml` under `[supervision]`:

- `stall_timeout_seconds` — log-silence threshold; `stalled` fires only when the run has had no log growth for this long **and** its backend pid is not alive (or was never recorded). A silent-but-alive run (the normal `--print` case) is never `stalled`. Set on `init` from the policy template; `0` disables.
- `auto_stop_on_stall` — terminate **waited** runs after `stall_timeout_seconds` of no log growth (use with care). This in-loop timer keys on log growth, not pid, so enabling it with a silent `--print` backend can kill a healthy long run — leave it `false` unless your backend streams output.
- `blocked_patterns` — substrings that imply the CLI is waiting on a human.

### Idle vs stalled vs dead/orphaned vs blocked

Three independent dimensions: **`idle_seconds`** = how long the log has been silent; **`pid_alive`** = is the backend process running; **`status`** = the run's lifecycle state. Because `--print` keeps the log silent for the whole run, judge health by `pid_alive` first.

| Signal / field | Meaning | What to do |
|----------------|---------|------------|
| `idle_seconds` low | Log grew recently | Usually healthy; task may still be long-running |
| `idle_seconds` high, `pid_alive: true`, no `stalled` | Quiet but the backend is alive (normal for `--print`) | Wait; this is **not** a stall. `idle_seconds` is silence, not hang |
| `stalled` | No log growth for `stall_timeout_seconds` **and** pid not alive / absent | Genuinely stuck or already gone; `watch` tail, check `blocked_on_user`, consider `stop` |
| `status: needs_recovery` | Orphaned run: was `running` but the backend pid is dead, or a `--wait` run left no live pid (supervisor killed). Surfaced with `uncommitted_changes`; lease released | Recover or re-run deterministically. The task is eligible again; `cleanup --remove-worktrees` can prune its worktree (kept if the tree is dirty or commits are ahead) |
| `blocked_on_user` | Trust or approval text in logs | Fix headless flags or continue in IDE |
| `limit` | Rate limit in logs | Wait for cooldown or next backend on `--wait` |
| `status: backend_unusable` | The backend is not authenticated on this host. **Not** a task failure and no attempt consumed; `backend_unusable_reason` names the fix | Authenticate (`agent login` / `claude login` / API key), then re-run. Auto routing skips the dead backend meanwhile |

When a later run has already delivered the task, the operator closes the stale `needs_recovery` or `failed` record with `ai-task supersede <run-id> [--by <run-id>] [--reason <text>]`. The record gets the terminal status `superseded` with `superseded_at`, `--by` is stored as `superseded_by` and `--reason` as `status_note`, and the task lease and quota reservation of that run are released, so the record stops counting in `needs_recovery_count`. The command refuses a `running` or `paused` run: stop it first.

A run is **never silently left `running`** when its supervisor/backend dies: `status` reaps it to `needs_recovery` (pid-less runs are reaped only after a short grace so an in-flight launch is not falsely killed). The plain `status` listing prints a `recover:` / `uncommitted:` line for each `needs_recovery` run; `status --json` adds a `needs_recovery_count` summary field and an `uncommitted_changes` per-run field.

### Rate limits and cooldowns (troubleshooting)

- **Cooldown duration:** `[cooldown] default_seconds` in policy (default 1800). `cooldown_until` is stored in `.ai-task/state.json`.
- **Do not edit `backend_cooldowns` by hand** to bypass limits. Finished runs no longer re-arm cooldown on `status`. A running limit or `run --wait` attempt still sets cooldown; vendor APIs may still rate-limit after a manual clear.
- **Probe:** when Claude cooldown expires, `plan` / `run` / `status` may run a short probe. If the API is still limited, cooldown is re-armed.
- **Fallback:** off by default (`limit_fallback_order = []`). When configured — e.g. `["cursor_auto"]` — a cooled Claude gets `cursor_auto` appended for that run (not `cursor_codex`). Risky tasks (P0/P1 or risk keywords) need `run --confirm-risk` when `ask_before_weaker_fallback_for_risky_tasks` is true.
- **Codex opt-in:** `cursor_codex` is never default for `Agent: auto`. Use `Agent: cursor` or `--backend cursor_codex`. Cursor API pool resets monthly; sticky cooldown until `cooldown clear --force`.
- **Wait vs switch:** use `routing.earliest_ready_at` to wait, or `run --backend cursor_auto` / `--confirm-risk` when `routing` shows fallback available.
- **Pinned wave:** while `ai-task pin` is active, cooldown on the pinned backend means the run refuses — fallback is suppressed by design. `pin --clear` releases the wave.
- **Optional:** `ai-task cooldown clear <backend> --force` removes the state entry only (stderr warning); does not remove vendor limits. It also clears a **credential-dead** mark, and is accepted when only that mark exists.
- **Credential failure ≠ rate limit:** a backend that dies on `Authentication required` / `agent login` / `CURSOR_API_KEY` is *unusable*, not limited — the run ends `backend_unusable` (no task failure, no attempt consumed), routing falls through, and `status` / `policy backends` / `self-test` name the fix. See "Credential-dead backends" above.
- **Quota reserve:** separate from reactive cooldowns, `ai-task quota status` reports Claude subscription quota windows and a reserve stop line *before* you hit a hard limit (see "Claude quota reserve" below). Best-effort: no quota source means limit/cooldown behavior is unchanged; run `ai-task quota setup-statusline --global` to print the recommended Claude Code statusLine wiring. When a wave hits limits anyway, run `ai-task quota doctor` first — it explains, check by check, why admission control did or did not gate.
- **Policy sync:** run `ai-task policy sync` (or `--dry-run`) to merge bundled defaults into `.ai-task/policies/default.toml`. The template wins for `supervision.stall_timeout_seconds`, `cooldown.default_seconds`, and Claude backend `args` and `reasoning`. A project keeps its Claude model through `model_override`. Pattern lists append missing entries. Recipe lists keep local sequences whole, including with `--force`: verify commands, backend args except Claude args, and routing orders and disabled backends. `routing.default_source` also stays local in both modes. Other scalars stay local unless forced. Missing keys are added, with compatibility defaults for older routing. Sync writes `default.toml.bak` before applying.

### Policy sync

```bash
ai-task policy sync --dry-run           # side-by-side local vs bundled (green = will apply, yellow = kept as-is)
ai-task policy sync --dry-run --force   # preview full overwrite from bundled template
ai-task policy sync --force             # apply; backup at default.toml.bak
```

Sync edits the policy file in place. A key it adds goes into its table after the nearest bundled neighbour, with the template's comment block above it. A changed value is replaced on its own lines, and the indent, list layout and a trailing comment stay. A missing table is appended at the end of the file, copied from the template with its comments. Every other line of the file stays byte for byte, so the diff after sync shows only what sync changed. When a change has no safe place in the text, for example a value written as an inline table, a dotted key or an array of tables, sync rewrites the file from the merged data as before: the report says so, and the previous file is in `default.toml.bak`.

Default sync is additive: the template wins for the listed supervision, cooldown and Claude model fields; other scalars stay local. `--force` overwrites bundled fields except recipe lists and `routing.default_source`. Keys and backends that exist only locally are kept.

Recipe lists are the exception to both modes. Verify profile `commands` and backend `args` / `extra_args` are a sequence of steps, so merging them item by item breaks them. Local recipes stay whole and appear as "recipe list: local override kept whole". The same rule applies to routing orders and disabled-backend lists. `backends.claude.args` keeps template-wins. To take a bundled recipe, delete the key or table and sync again.

A repository that runs Claude on another model by owner decision keeps it with `model_override`, not by editing `backends.claude.args`, which sync would put back:

```toml
[backends.claude]
model_override = "opus"
model_override_reason = "owner moved coding runs to Opus"
model_override_since = 2026-10-22
```

The run argv is then the bundled `args` with only the `--model` value replaced, so effort, `--print` and any flag the template adds later still come from the template. If the bundled args name no model, `--model <override>` goes first. The run record and `ai-task status` name the model that actually ran, the override included. A key without `model_override_reason` or `model_override_since` is refused when the policy is loaded and by sync, and the message names the missing field.

Sync keeps these keys in both modes, `--force` included, and lists the override on every run among the kept fields: "local model opus since 2026-10-22 (owner moved coding runs to Opus), bundled sonnet". Sync also writes `model_override_bundled`, the bundled model it last checked the override against. When a later template ships a different model, sync prints a separate warning that the template changed its model while the repository keeps its own, and records the new bundled model when it applies. To go back to the bundled model, delete `model_override`. The next run uses the template model, and the other `model_override_*` keys are ignored.

**Policy-hash baseline.** Policy and config files are config-as-code: verify profile commands, backend argv (permission flags such as `--permission-mode` and `--settings`), and quota refresh sources are all executed from them. The in-run sensitive watch (below) only sees edits made during a tracked run — a policy edited *between* runs (merged PR, manual agent session) would otherwise load silently. So `ai-task init` and every non-dry-run `ai-task policy sync` (the operator's review point) record SHA-256 hashes of `.ai-task/config.toml` and `.ai-task/policies/*.toml` into **`.ai-task/policy-hashes.json`**, and `run`, `verify`, and `plan --bulk` check the current hashes against that baseline at entry. On mismatch they print a loud stderr warning naming the drifted file(s) — *"policy changed since last sync — review …, then run `ai-task policy sync` to re-baseline"* — and auto-log a `policy_baseline_drift` decision row (deduped while the drift fingerprint is unchanged; the warning itself repeats every time). The check **never blocks** and the verify/refresh execution mechanism is unchanged. A repo initialized before the baseline existed gets a one-time "policy baseline recorded" notice and an auto-baseline instead of a warning storm. After reviewing an intentional edit, run `ai-task policy sync` to re-baseline (it re-baselines even when it reports "Policy already in sync."). Residual: the baseline catches agent/PR drift, not a malicious operator — whoever can edit the policy can also rewrite `policy-hashes.json`.

Use after upgrading the `ai-task` script or when run logs show a limit but the attempt record has `limited: false` (stale `limit_patterns` in local policy).

`ai-task watch <run-id>` tails run logs and prints an **activity** line (`silent Nm`, stall threshold). Use `--follow` to stream until Ctrl+C.

`ai-task note` stores messages in `inbox.jsonl` but does **not** inject them into a running process.

Verify supervision helpers: `ai-task self-test`.

## Claude quota reserve

`ai-task` can read Claude Code subscription quota snapshots so a headless wave keeps a small budget for teamlead/control turns and warns before it runs the window dry. This is **best-effort**: with no fresh quota source, limit-pattern detection and `[cooldown]` keep working and status reports quota as `unavailable`. For headless dispatch, `plan --bulk` and `run` first try `quota refresh` when the snapshot is missing or stale. Quota supervision is **runtime routing only**; it never plans or reasons about the work itself.

Two rolling windows are tracked: **`five_hour`** (rolling 5-hour) and **`seven_day`** (rolling weekly). For each window the **reserve stop line** is `used == 100 - reserve_percentage` (default reserve 5 → stop at 95% used).

```bash
ai-task quota status          # human summary: windows, used %, reset, stop line, freshness
ai-task quota status --json   # machine-readable; reports unavailable without contacting any service
ai-task quota doctor          # FIRST STEP when waves hit limits: explain why admission control did or did not gate
ai-task quota refresh         # actively refresh snapshot from configured headless live sources
ai-task quota probe           # live global read; works without .ai-task/ — pre-fan-out check anywhere
```

### `quota doctor`: first step when waves hit limits

Quota supervision can be **silently inert**: a policy created before quota supervision existed has no `[quota]` section (so `enabled` defaults to false), or the snapshot is missing/stale while headless refresh keeps failing — in both cases dispatch is documented fail-open and a wave runs to 100% of the window with no pause. When that happens (or before a long unattended batch), run `ai-task quota doctor` **first** — it is the one-command diagnosis, no code archaeology needed:

```bash
ai-task quota doctor          # pass/fail per check, each with a one-line why
ai-task quota doctor --json   # machine-readable report (checks[], gating[], blind)
```

It reports, with pass/fail and a one-line why per item: the `[quota]` section present and enabled (when the section is absent it tells you to run `ai-task policy sync`, which adds the missing keys); statusLine wiring (repo helper vendored at `.ai-task/scripts/ai-task-quota-statusline.py` plus a dispatcher reachable on PATH or via an existing settings `statusLine` command); snapshot path, freshness, and age vs `max_snapshot_age_seconds`; the last headless refresh attempt result and source; active reservations vs current window headroom; and the effective stop line with a **dry reservation view** showing what would gate right now for Size S/M/L/unknown (`reservation_decision` without reserving anything). Doctor is read-only — it never shells out to refresh sources and never mutates state.

**Exit code:** non-zero only when supervision is **enabled but blind** — enabled in policy, no fresh source, and headless refresh unavailable (disabled, unconfigured, or its last attempt failed). A policy with quota intentionally disabled exits 0 with the failing `policy` check explaining why nothing gates.

`quota status --json` always returns a payload. Key fields: `enabled`, `available`, `source`, `source_fresh`, `age_seconds`, `reserve_percentage`, `stop_line_percentage`, `near_limit`, `at_or_over_stop`, and a `windows[]` list (`window`, `used_percentage`, `remaining_before_stop`, `stop_line_percentage`, `near_limit`, `at_or_over_stop`, `resets_at`, `captured_at`). When unavailable it sets `available: false` and a `reason`.

`status --json` always includes a **compact `quota` object**. When the source is missing, stale, disabled, or unreadable it sets `available: false` and `reason` so teamlead can see that Claude quota admission control is blind before dispatch. It also always includes a **`quota_telemetry`** object (recent sample count + last sample time; see «Quota telemetry» below). `quota status --json` exposes the same telemetry under a `telemetry` key. Plain `status` prints a **`Quota alerts`** block warning when the quota source is unavailable, per window at/above `near_limit_start_threshold_percentage` (default 85), or at/over the reserve stop line.

### `quota probe`: global pre-fan-out check

`ai-task quota probe` answers "how much window is left" **anywhere** — it needs no `.ai-task/`, no policy file, and no initialized repo, so any orchestrator (a teamlead in a fresh repo, an IDE agent about to fan out subagents, the ai-sdlc-local-kit profile itself) can run it before spending the window. It resolves the Claude Code OAuth token via the existing env → credentials file → macOS Keychain chain, queries the OAuth usage endpoint live, and prints each window with used %, `resets_at`, headroom before the stop line, and a plain assessment against built-in defaults (reserve 5% → stop line 95%, near-limit 85%).

```bash
ai-task quota probe           # human summary + assessment: safe to fan out / near limit / do not fan out
ai-task quota probe --json    # machine dict: windows[], near_limit, at_or_over_stop, captured_at, reason
```

Probe is strictly **read-only**: it never writes the snapshot or any other state, inside or outside an initialized repo (inside one, `quota refresh` remains the snapshot writer). It exits non-zero with a clear reason when no token source exists, the endpoint is unreachable or returns an HTTP error, or the response has no known windows. Use it as the standard pre-fan-out check in any agent workflow.

### Login expiry of the headless Claude

A headless worker whose claude.ai sign-in has lapsed fails with "Not logged in" or "account on hold", while the interactive app on the same machine keeps working. Since Claude Code 2.1.318 the CLI reports when the stored sign-in ends: `loginExpiresAt` in `claude auth status --json` and `credential_expires_at` in the result of `claude -p --output-format json`. Claude Code itself warns on stderr only 10 days ahead and only in text output, which nobody reads on a worker host.

`quota doctor` and `quota probe` ask the local CLI for that date and print it. Doctor adds a `login` check, and probe prints a `Login:` line, also when the quota read itself fails. Both run `claude --version`, then `claude auth status --json`, with the command and env of `[backends.claude]`, so a worker's `CLAUDE_CONFIG_DIR` set there is the one asked. The `login` check fails, and probe prefixes the line with `WARNING:`, in three cases: the CLI on this host is not logged in, the sign-in has already ended, or fewer than `[quota] login_expiry_warn_days` days are left (default 14). The fix is `claude auth login` as the user the workers run as.

The interactive CLI in a terminal and the headless workers can be logged in separately. Doctor reports the login of whichever CLI and config directory it runs with, so run it as the worker user, or set the worker's `CLAUDE_CONFIG_DIR` in `[backends.claude.env]`.

On Claude Code older than 2.1.318 the field does not exist. The check then passes with `expiry unknown, Claude Code < 2.1.318 (found <version>)` and never calls `claude auth status`. A missing `claude` binary or an API key login also pass with an "expiry unknown" reason. `--json` carries the same report under `login` (`known`, `ok`, `warn`, `logged_in`, `expires_at`, `days_left`, `threshold_days`, `cli_version`, `reason`). The test suite sets `AI_TASK_CLAUDE_LOGIN_CHECK=0` so tests never run the developer's real CLI; that variable skips the check anywhere it is set.

### Official source: the statusLine snapshot

The preferred (and only auto-read) source is a JSON **snapshot file written by a Claude Code `statusLine` helper**. `ai-task` reads it from `[quota] snapshot_path` (default `.ai-task/quota-snapshot.json`, relative to the repo root; absolute paths are honored). Each window needs `used_percentage`, and should carry `resets_at` and `captured_at`. Both shapes are accepted:

```json
{
  "captured_at": "2026-06-08T18:30:00Z",
  "five_hour": { "used_percentage": 92, "resets_at": "2026-06-08T21:00:00Z" },
  "seven_day": { "used_percentage": 50, "resets_at": "2026-06-13T00:00:00Z" }
}
```

…or wrapped under a `windows` key (`{"captured_at": "...", "windows": {"five_hour": {...}, "seven_day": {...}}}`). A top-level `captured_at` is inherited by windows that omit their own. Friendly window aliases are normalized (`5h`/`hourly` → `five_hour`, `7d`/`weekly`/`week` → `seven_day`).

**Set up statusLine wiring.** Claude Code `statusLine` is a standard Claude Code setting. The `.ai-task/quota-snapshot.json` file is the ai-sdlc-local-kit contract. `ai-task init` vendors the repo-local helper to `.ai-task/scripts/ai-task-quota-statusline.py`, but it does not edit external settings.

Start with mode selection (default command explains both options):

```bash
ai-task quota setup-statusline
```

Recommended path for global settings (`~/.claude/settings.json` or `~/.cursor/cli-config.json`):

```bash
ai-task quota setup-statusline --global
```

`--global` prints a repo-agnostic snippet that calls `ai-task-quota-statusline-dispatch.py` (no repo path, no `.ai-task/...`, no `--repo`). Install the dispatcher on PATH first, for example:

```bash
mkdir -p "$HOME/.local/bin"
ln -sf "/path/to/ai-sdlc-local-kit/scripts/ai-task-quota-statusline-dispatch.py" "$HOME/.local/bin/ai-task-quota-statusline-dispatch.py"
chmod +x "$HOME/.local/bin/ai-task-quota-statusline-dispatch.py"
```

Project-local override for one repo only:

```bash
ai-task quota setup-statusline --project
```

`--project` prints the repo-specific helper command (`.ai-task/scripts/ai-task-quota-statusline.py --repo <repo>`). Use it only in project-local settings, never in global settings.

After installing either snippet, let Claude Code render the status line once in the target repo, then validate from that repo:

```bash
ai-task quota setup-statusline --check
```

Expected success is `Quota statusLine helper: ok` plus `Quota snapshot: fresh`. If the helper is missing, re-run `ai-task init` first. If the snapshot is missing or stale, Claude Code has not rendered the configured status line recently enough. The snapshot file lives under gitignored `.ai-task/`, so it is operator runtime state, never committed.

**Verify without a delivery run.** After installing the helper (and triggering Claude Code at least once so the file exists), run `ai-task quota status` — it should print `available` with both windows. `ai-task quota status --json` confirms `source_fresh: true` and a small `age_seconds`. No run, plan, or backend launch is needed to verify the source.

### Headless refresh

Interactive statusLine rendering is not enough for long detached waves: while `run` and `wait-runs` are working headlessly, the statusLine may not re-render and the snapshot can age past `[quota] max_snapshot_age_seconds`. `ai-task quota refresh` is the headless complement. It tries configured live-source commands, normalizes their JSON into the same `.ai-task/quota-snapshot.json` contract, and writes the file atomically.

```bash
ai-task quota refresh
ai-task quota refresh --json
ai-task quota refresh --force
```

`quota status` stays read-only and never shells out. `quota refresh` may use configured live sources. By default it first uses the built-in `claude_oauth` source: it reads the existing Claude Code OAuth credential from a logged-in Claude Code CLI/Desktop setup (environment, Claude credentials file, or macOS Keychain) and calls Claude Code's OAuth usage endpoint for 5-hour and 7-day percentages. It does **not** use or require an Anthropic API key. It then tries `ccquota --json` if that command is on PATH. A source can also return the same window shapes accepted by the statusLine helper, including a `rate_limits` wrapper. If no live source is reachable, refresh is a no-op with a stated reason, and the last reason is surfaced in `status --json.quota.reason` as `headless refresh unavailable`.

**HTTP 401/403 from the OAuth usage endpoint:** the cached OAuth token in the credentials file/keychain has expired, and only the Claude Code app itself can mint a fresh one — no headless command can recover. Refresh marks the `claude_oauth` attempt failed with the actionable reason `OAuth token expired/unauthorized — open Claude Code to refresh it` (plus an `unauthorized: true` flag in the attempt and refresh state) and falls through to the next configured source (`ccquota` etc.) instead of aborting. `quota probe` prints the same reason (and still exits non-zero when no source succeeds), and `quota doctor`'s refresh check shows the open-the-app hint for this case instead of the endpoint-unreachable wording. A 429 keeps the generic `returned HTTP 429` retry-later wording — that is rate limiting, not a stale token.

Dispatch behavior:

- `run` checks quota freshness before Claude admission control and refreshes when the snapshot is missing or stale.
- `plan --bulk` does the same before emitting the wave plan, and refuses to proceed when a successful refresh shows the reserve stop line is already reached.
- If refresh is impossible, dispatch degrades to the existing quota-blind path and auto-logs `decision log --choice quota_blind_dispatch` with the reason when decision auto-logging is enabled.
- A successful refresh that shows the window at/over the stop line prevents Claude from launching; existing fallback/wait behavior still applies.

`AI_TASK_CLAUDE_OAUTH_USAGE=0` turns the built-in `claude_oauth` source off wherever it is set: ai-task reads no stored Claude token and does not call the usage endpoint, and the attempt reason says `Claude OAuth usage source off (AI_TASK_CLAUDE_OAUTH_USAGE=0)`. Other configured sources still run. The test suite sets it so a test owns its quota snapshot: before that, dispatch refresh in about twenty tests wrote the developer's live usage into the test repository, and when that usage was at the stop line those tests failed with `quota reservation did not fit`.

### Freshness and fallbacks

- **Freshness:** a snapshot older than `[quota] max_snapshot_age_seconds` (default 900s) is treated as **stale → unavailable**, so routing falls back to limit-pattern/cooldown behavior. Set `0` to disable the age gate. Stale windows are still echoed in `quota status` and the compact `status --json` object for visibility, with `available: false`.
- **Headless live sources:** `quota status` never invokes external services; it reports the current snapshot only. `quota refresh` and dispatch refresh may use `[quota] refresh_sources` (default: built-in `claude_oauth`, then `ccquota --json`) to re-actualize the snapshot before admission control. Legacy policies with `["ccusage", "ccquota"]` are treated as `["claude_oauth", "ccquota", "ccusage"]` at runtime because `ccusage blocks` reports local token blocks, not official subscription quota percentages.
- **Unavailable behavior:** disabled policy (`[quota] enabled = false`), missing file, unreadable JSON, no valid windows, or a stale snapshot all yield `available: false` with a `reason`. In every case current limit/cooldown supervision is unaffected. `ai-task self-test` warns when `[quota]` is enabled but the source is unavailable, because that means admission control cannot reserve budget.

### `[quota]` policy

Defaults (added by `default_policy()`; `ai-task policy sync` adds any missing key while keeping your overrides):

| Key | Default | Meaning |
|-----|---------|---------|
| `enabled` | `true` | Master switch for quota supervision. |
| `reserve_percentage` | `5` | Headroom never spent by routine dispatch (stop line = `100 - reserve`). |
| `near_limit_start_threshold_percentage` | `85` | Used % at/above which plain `status` warns. |
| `resume_margin_seconds` | `60` | Extra wait after a window resets before treating it usable (added to `resume_after`). |
| `resume_max_attempts` | `3` | Auto-resume retry budget for `wait-runs --resume-on-quota`. `0` disables auto-resume. |
| `resume_max_wait_seconds` | `691200` | Hard wall-clock cap (8 days, covering a full `seven_day` reset) on budget-free re-arming, measured from the first quota pause. Past the cap auto-resume stops and the run stays `waiting_quota`. `0` disables the cap. |
| `max_snapshot_age_seconds` | `900` | Snapshot older than this is stale/unavailable (`0` disables). |
| `refresh_enabled` | `true` | Allow `quota refresh` to run configured headless live-source commands. |
| `refresh_on_dispatch` | `true` | Let `run` and `plan --bulk` refresh stale/missing quota before admission control. |
| `refresh_at_finalize` | `false` | Refresh a stale source when a **detached** run finalizes, before its completion telemetry takes the post snapshot. Opt-in: one live-source call per finished run; it never blocks work. Turn it on for a calibration window so detached waves yield high-confidence deltas. |
| `refresh_timeout_seconds` | `10` | Per-source timeout for headless quota refresh commands. |
| `refresh_sources` | `["claude_oauth", "ccquota"]` | Live sources tried by `quota refresh`; `claude_oauth` is built in and uses existing Claude Code OAuth credentials, `ccquota` maps to `ccquota --json`, and custom strings are split as shell-like command lines. |
| `login_expiry_warn_days` | `14` | `quota doctor` fails its `login` check and `quota probe` prints a warning when the headless claude.ai sign-in ends in fewer days than this, on Claude Code 2.1.318 or newer. |
| `calibration_min_samples` | `100` | Minimum **high-confidence** telemetry samples before `quota calibrate --apply` will rewrite `[quota.reservations]`. `stats` and `calibrate --dry-run` work with any data; only **apply** is gated. |
| `calibration_floor_percentage` | `3` | Calibration never recommends a reservation below this percent, so a few tiny-delta samples cannot drive the reserved budget toward zero. |
| `snapshot_path` | `.ai-task/quota-snapshot.json` | statusLine snapshot location (repo-relative or absolute). |
| `[quota.reservations] s_percentage` | `5` | Pessimistic reservation for `Size: S`. |
| `[quota.reservations] m_percentage` | `8` | Pessimistic reservation for `Size: M`. |
| `[quota.reservations] l_percentage` | `10` | Pessimistic reservation for `Size: L`. |
| `[quota.reservations] unknown_percentage` | `5` | Reservation when `Size:` is missing/unrecognized. |

Reservation percentages are **estimates (pessimistic upper bounds), not exact cost prediction**; observed telemetry can recommend new values via **`ai-task quota calibrate`** (advisory; see «Reservation calibration» below). Quota supervision sources snapshots, reports status, and exposes the reserve stop line; the admission control consumes these reservations (below).

### Quota admission control

Before a **Claude-backed `run`** launches, `ai-task` reserves the pessimistic `[quota.reservations]` percentage for the task's `Size:` so parallel runs cannot overbook the same budget:

- **Which backends are Claude-backed.** A backend is gated when its table says `quota_pool = "claude"`. The backend named `claude` has that pool by default, so a local policy written before the field keeps its supervision. Any other backend whose `command` runs `claude` (a cheaper tier, a wrapper path such as `/opt/bin/claude`) must declare `quota_pool = "claude"`, or `quota_pool = "none"` when it bills a separate pool such as an API key. Without the field the policy is refused at load with a line naming the backend, because a second backend on the same subscription would otherwise take no reservation and ignore the stop line. `cursor_*`, `codex` and `devin` declare nothing and stay ungated.
- **Effective budget** = the *minimum* room before the reserve stop line across fresh windows (`(100 - reserve) - used`), after subtracting already-active reservations. The tightest window binds.
- **Atomic acquire/release.** The reservation is written to `.ai-task/state.json` under the existing **state lock** (the same lock `save_state` uses — no second locking mechanism), so two concurrent `ai-task run` processes re-read the latest reservations and cannot both consume the same remaining budget. The reservation is **released** on success, failure, stop, limit-fallback, and stale-run cleanup; a **`--dry-run` never reserves**.
- **Visibility.** Active reservations appear in `status --json` under `quota_reservations` (keyed by run id: `task_id`, `size`, `backend`, `percentage`) and in `summary.quota_reserved_task_ids`.
- **Routing explanation.** The `routing` block in `status --json` reports `quota_reserved`, `quota_required`, `quota_available`, and `quota_blocked_reason` for the next eligible task.
- **Blocked vs fallback.** If the reservation would exceed budget, Claude does not launch. When `routing.limit_fallback_order` offers a non-Claude backend (Cursor uses a separate pool and is **not** quota-gated), the run can be **selected** onto that fallback — exactly as on a rate limit; Cursor fallback behavior is otherwise unchanged. When no fallback is allowed/available — the default, since `limit_fallback_order` ships empty — the run ends with status **`quota_blocked`** (not `failed`) — this is admission control, not failed work. Wait for the window to reset, raise the budget, or configure `limit_fallback_order`.
- **Inert without a fresh source.** With quota disabled or no fresh snapshot, admission control reserves nothing and dispatch degrades to the unchanged limit-pattern/cooldown path.

Operator rules for quota at W3 (preflight, sizing the sub-wave to reservations, wait/fallback/smaller sub-wave reporting, «a quota-blocked Claude task is not failed work») are normative in `skills/ai-task-teamlead/reference-operations.md` → W3 quota-aware dispatch; [`docs/ai-task-delivery-waves.md`](ai-task-delivery-waves.md) keeps only the command cheat-sheet.

### `waiting_quota` + auto-resume after reset

When Claude is blocked by a quota reservation **or** reports a real usage-limit message, that is a recoverable **wait**, not failed work:

- **`waiting_quota` status.** When a reset time is derivable — the **latest** `resets_at` among quota-snapshot windows at/over the stop line (all blocked windows must clear before a resume can succeed), or **parsed from the limit text** (e.g. "try again in 2h 30m") for repos with no snapshot — and auto-resume is enabled (`resume_max_attempts > 0`), the run is set to **`waiting_quota`** instead of terminal `quota_blocked`/`failed`. It records **`resume_after`** (reset/parsed time **+ `resume_margin_seconds`**), **`quota_window`**, and a clear **`status_note`**, surfaced in both `status --json` (per-run `resume_after` / `quota_window` / `resume_attempts_remaining`) and plain `status`.
- **Lease + worktree are kept.** A `waiting_quota` run **retains its task lease** (so resume reuses it — no duplicate lease) and its worktree (so the same packet re-runs in the same tree). Its quota **reservation is released** while it waits, freeing budget for other runs.
- **Resume receipt.** Before any re-launch, a compact receipt is written into the run record (`resume_receipts`) and the run log: the task in flight, why it paused, whether files changed in the worktree, how many auto-resume attempts remain, and why another Claude attempt is justified.
- **`wait-runs --resume-on-quota`.** This opt-in mode (used by long headless teamlead waves) keeps waiting through `waiting_quota`, sleeps until `resume_after`, **probes** Claude recovery, and **re-launches the same packet in the same worktree** reusing the lease. A clean exit moves the run to `needs_review` (lease + reservation released); a fresh limit re-arms the next wake or exhausts the budget. It exits only when target runs are inactive or on `--timeout`. Without the flag, a `waiting_quota` run is reported as inactive (nothing drives it forward in that call).
- **Re-derive on wake — budget-free re-arm.** On each wake the resume time is **re-derived from a fresh snapshot** (refreshing a stale one via the headless refresh path) **before** any retry attempt is consumed. If some window is still at/over the stop line with a later reset, the run **re-arms** `resume_after`/`quota_window` to the newly derived target **without decrementing the budget** — a `five_hour` reset can no longer burn attempts while `seven_day` is the real blocker. Re-arming is bounded by the hard **`resume_max_wait_seconds`** wall clock measured from the first quota pause (`first_paused_at` on the run record); past the cap the budget is closed (`resume_attempts_remaining` → 0, same shape as budget exhaustion so `wait-runs` stops waking the run) and the run stays `waiting_quota` with a clear note.
- **Retry budget — no infinite loops.** Each launched probe/re-launch consumes at most one attempt; after `resume_max_attempts` the run stays `waiting_quota` with a budget-exhausted note and is no longer treated as active, so the loop cannot wake/retry forever if Claude stays limited. A **failed probe re-arms** the next wake from the Claude cooldown rather than retrying immediately.
- **Limit-pattern cooldowns unchanged without a snapshot.** With no derivable reset time (or `resume_max_attempts = 0`), behavior is exactly as before auto-resume: `quota_blocked` for an admission-control block, and the existing `[cooldown]` limit-pattern path for a rate limit.

### Quota telemetry

The `[quota.reservations]` percentages above are **hand-picked pessimistic upper bounds**. To replace them later with observed values (see Reservation calibration below), every **Claude-backed run** appends one structured sample to **`.ai-task/quota-telemetry.jsonl`** — append-only JSONL, one object per line, each carrying a `schema_version`. The file lives under the gitignored `.ai-task/` runtime dir: it is **operator data, never committed**, and contains **no secrets and no absolute transcript content** (repo root, home, and worktree paths are redacted; the diffstat is a capped `git diff --stat` summary, not file content).

**What a sample records:** `run_id`, `task_id`, `size`, `backend`, `model`, `reservation_percentage`, `quota_reserved`, the **pre-launch** (`pre_quota`) and **post-finish** (`post_quota`) quota snapshots (window usage only), `elapsed_seconds`, `exit_status`, `exit_code`, retry/limit signals (`limited`, `stalled`, `attempts`, `blocked_reason`), a redacted `diffstat` summary, and the wave fields `sample_kind` + `confidence` + `partial`.

**Which samples calibration uses, and why parallel ones are treated carefully:**

- **High-confidence single-run samples** (`sample_kind: single`, `confidence: high`, `partial: false`) are the ones meant for estimating the observed quota delta by `Size:`. They carry both a pre- and a post-launch quota snapshot from a run that had **no concurrent Claude run**, so the change in window usage is attributable to that one task. These are the samples a calibrator should trust for p80/p95 reservation recommendations.
- **Parallel/wave samples are flagged `confidence: low`.** When a run launches while any other run is already holding a quota reservation or running on a quota-gated backend, the windows are moving because of **several tasks at once** and there is **no per-run usage metadata** to attribute spend to one task. The pre/post delta for such a sample reflects the whole wave, not the task, so it would bias a per-`Size:` estimate. These samples are kept (they are still useful for wave-level totals) but must be **excluded from high-confidence per-task delta math** unless reliable per-run attribution becomes available.
- **Partial samples are flagged `confidence: low` too.** Telemetry is **never required for delivery**: if there is no fresh quota source the snapshots degrade to `available: false`, if the diffstat cannot be collected it degrades to `available: false`, and a `quota_blocked` run (which never launched Claude) has no post snapshot. Any sample missing its pre- or post-snapshot is marked `partial: true` so the calibrator can drop it from delta estimates. A telemetry write failure is swallowed — it can never break or fail a run.

**Detached and wave runs self-finalize their cost sample.** A foreground `run --wait` takes the post-finish quota snapshot in-process, but a detached launch (and every wave sub-run) is still in flight when the launching command returns. Each detached launch therefore writes only a partial `launched` sample (pre-quota only) **and stores the pre-launch snapshot, wave classification, and `Size:` on its run record**. When the run later finishes, the **orphan reaper** (the liveness/finalize path that observes the backend pid go away during `status`/`refresh`/`wait-runs`) takes the **post** snapshot at that moment and appends the authoritative **completion sample** (`exit_status: needs_recovery`) pairing stored pre + fresh post — so a normal detached **wave now produces high-confidence cost deltas without forcing foreground mode**. Honest degradation is preserved: if the quota source is unavailable at finalize (stale/missing, or a usage-endpoint 429), the completion sample stays `partial` with the reason carried by `post_quota` — never fabricated. The earlier `launched` line and the completion line share a `run_id`; a reader should **prefer the completion sample** (it has both snapshots) per `run_id`. The dispatch decision is unchanged — this only adds an "after" snapshot at the finalize point that already existed.

**Refreshing the source at finalize (opt-in).** The completion sample above is only high-confidence when the quota source is fresh at finalize; on a long detached wave the statusLine snapshot has often gone stale by then, so the sample degrades to `partial` and calibration ignores it. On long detached waves this can leave zero high-confidence samples, so `quota calibrate --apply` stays out of reach. Set **`[quota] refresh_at_finalize = true`** to let the detached finalize path refresh the source once (via the same `refresh_sources`) before taking the post snapshot. It is **off by default** because it costs one live-source call per finished run; it can never block work, since the run is already over. Turn it on for a calibration window, watch the high-confidence count climb in `quota status`, then decide whether to leave it on. When the refresh fails, behavior is unchanged: the sample stays `partial` with the reason carried by `post_quota` - nothing is fabricated. Foreground runs are unaffected.

**Visibility.** Both `status --json` (under `quota_telemetry`) and `quota status --json` (under `telemetry`) expose the recent **sample count**, the **last sample time** (`last_sample_at`), and the recent high-vs-low confidence split, so an operator can see whether usable calibration data is accumulating. Plain `ai-task quota status` prints a one-line `Telemetry:` summary.

**Pooling telemetry across repos.** A solo operator running several repos rarely accumulates `calibration_min_samples` (default 100) high-confidence samples in any single repo. `[quota] telemetry_path` mirrors `snapshot_path` semantics: the relative default (`.ai-task/quota-telemetry.jsonl`) keeps per-repo isolation, while an **absolute path** (`~` expanded) is honored as-is — point several repos at one shared file and `quota calibrate` reads the merged samples. Every sample carries `repo_id` (the repo's `project_id`, falling back to the directory name) so pooled data stays attributable; the field is additive, `schema_version` stays 1, and readers tolerate its absence in older samples. Cheap interim before pooling: once `calibrate --dry-run` estimates stabilize, lower `calibration_min_samples` per repo.

### Reservation calibration

Once telemetry has accumulated, `ai-task` can **recommend** `[quota.reservations]` values from the observed quota deltas — but it is **advisory only and never auto-applies**. The hand-picked defaults (`S=5`, `M=8`, `L=10`, unknown=`5`) stay in force until an operator explicitly applies a change.

```bash
ai-task quota stats                 # sample counts, p50/p80/p95 by Size:, current vs recommended
ai-task quota stats --json          # machine-readable; same data plus by backend/model
ai-task quota calibrate --dry-run   # print the [quota.reservations] patch it would suggest (default)
ai-task quota calibrate --apply     # write the patch (refused below the sample minimum; backs up first)
```

- **What it computes.** For each backlog `Size:` (and, in `stats`, each backend/model) it takes the per-sample observed delta — the **largest non-negative `used_percentage` increase** across the windows a sample saw between its pre- and post-quota snapshots — and reports **p50 / p80 / p95**. The recommendation is **conservative: p95 rounded up** to a whole percent, with a **small floor** (`[quota] calibration_floor_percentage`, default 3) so a handful of tiny-delta samples cannot drive the reserved budget toward zero.
- **Only high-confidence samples by default.** `single`/`confidence: high`/non-`partial` samples (one task, no concurrent Claude run, both snapshots present) are the only ones that feed percentiles and recommendations. Low-confidence (parallel/wave) and partial samples are **counted in the confidence buckets but excluded from the math**, because they have no reliable per-task attribution. `stats --include-low-confidence` folds them in explicitly (less trustworthy) — never the default, and never used by `calibrate --apply`.
- **Sample-count guard.** `calibrate --apply` is **refused** when high-confidence samples are below `[quota] calibration_min_samples` (default **100**). `stats` and `calibrate --dry-run` work with any amount of data so you can watch the estimate form; a smaller **per-size display floor** (10 samples) only flags a size's recommendation as `(low n)` in `stats`/dry-run output — it does not gate apply, which is governed solely by the total minimum.
- **Apply is safe and reversible.** `--apply` first copies the policy to **`<policy>.toml.bak`** (the same backup-then-edit path `policy sync` uses), then updates only the reservation keys whose recommended value differs from the current one. It writes them into the existing file text, so only those lines change and every comment stays; a reservation key missing from the file is added with the template's comment. When an edit has no safe place (for example reservations written as an inline table), it rewrites the policy from the data as before and says so. A run that does not change any value reports "nothing to apply". Revert by restoring the backup.
- **Advisory, not proof.** Calibration summarizes what *recent* runs spent; it is **not a guarantee** and **must not be treated as proof after one unusual batch** (an outage, a giant refactor wave, or a stretch of trivial tasks can all skew a thin sample). Review the per-size sample counts before applying, and prefer keeping the pessimistic defaults when in doubt — overbooking the window is worse than reserving a little too much.

## Review, cleanup, and prune

### AI review (verify → review → verdict)

Delivery review is separate from implement `run`:

1. **`ai-task verify --run-id`** — deterministic gates (`docs/ai-task-verify.md`).
2. **`ai-task review <run-id>`** — writes `review-packet.md`, changed-file list, and **`review-skills.json`** (stack skills from the run diff). Optional **`--dry-run`** prints resolved skills only. With `[review.codex] enabled = true` or `--codex` it first runs the Codex review pass and puts its findings into `review-findings.md` (see Codex review pass below).
3. **ai-task-reviewer** skill — bug-finding passes run in a **fresh subagent context** (diff + task block + stack skills only, never the implementing conversation); the in-session reviewer assembles **`review-findings.md`** with finding ids and does not approve alone. Normative procedure: `skills/ai-task-reviewer/SKILL.md`.
4. **`ai-task verdict <run-id> approve|rework|…`** — teamlead records outcome. Approve is **autonomous** when verify passed and review has no blocking findings; the user gate is `escalate` only.
5. **Rework** — `verdict rework` → `note` → **`complete`** review run → **`run --wait`** same TASK-ID → verify → review again. The retry `run` rebuilds the packet itself and **includes the latest `review-findings.md`** — `packet refresh` is an optional preview, not a required step. Findings are **kept, not consumed**: they stay in the prior run's directory and are included in every subsequent packet for that task until the task is approved/closed; a newer review's findings supersede older ones. All actionable findings (including minor/nit) use this path.

**Stack routing:** registry in `skills/ai-task-reviewer/registry.json`, documented in **`docs/ai-task-review-registry.md`**.

| When | Stack source |
|------|----------------|
| `plan --json` / `dor --json` | **Predictive** — repo markers + Task Context (`review_stack`, `review_skills_status`, `review_skills_missing`) |
| `review` | **Authoritative** — changed paths in the run cwd/worktree |

Extend the registry when `review_skills_missing` is true or product adds a DoR gap for an unknown stack.

Review is also recommended when a task is high priority, changes contracts or security-sensitive areas, touches broad shared infrastructure, or when the implementing agent reports uncertainty. `review` uses the run cwd (main repo or worktree), not only the main working tree when a worktree run is active.

### Codex review pass

The three review passes run with the teamlead vendor. A repository that wants a second vendor turns on `[review.codex] enabled = true` in its policy, and then `ai-task review <run-id>` also runs `codex exec review` on the run diff before it writes the packet. The switch is off by default because every pass spends Codex quota. `policy sync` keeps a local `enabled` value even with `--force`. For one call, `--codex` adds the pass and `--no-codex` skips it whatever the policy says.

| Key | Default | Meaning |
|-----|---------|---------|
| `enabled` | `false` | run the pass on every `ai-task review` |
| `sandbox` | `"read-only"` | Codex sandbox of the pass; a review writes nothing |
| `timeout_seconds` | `1200` | the pass stops after this many seconds and is recorded as `timeout` |

ai-task builds the command from the `[backends.codex]` argv recipe, so the pass runs the way a Codex worker does: `--ignore-user-config` and `--strict-config`, the same `project_doc_max_bytes` budget, the home hooks trust as `-c hooks.state` and trust for the run directory as `-c projects`. It does so whether or not the `codex` backend implements tasks in that repository, and a policy that still holds the empty `args` placeholder of a never-enabled codex backend gets the bundled recipe instead. Two parts differ: the sandbox comes from `[review.codex]`, and the final message carries no worker-done schema, because Codex renders its own review text. The pass needs codex-cli 0.131.0 or later, like the worker.

The target is the run diff. Uncommitted changes in the run cwd give `codex exec review --uncommitted`, the same set the packet lists. A worktree run whose worker committed is reviewed with `--base <branch the repository root has checked out>`. `--codex-base BRANCH` or `--codex-commit SHA` names the target by hand, for example the merge commit of a finished run. With no diff the pass is recorded as `skipped`.

Codex writes its review to `codex-review.md` in the run directory, its event log to `codex-review.jsonl` and its stderr to `codex-review-stderr.log`. ai-task parses the findings and writes them into `review-findings.md` between the markers `<!-- codex-review:start -->` and `<!-- codex-review:end -->`. Each finding gets the id `CX-NNN`, the line `- **Source:** codex`, the file path relative to the run cwd and a suggested severity from the Codex priority: P0 blocking, P1 major, P2 minor, P3 nit. A repeated pass replaces only that block. The reviewer keeps the block, dedupes and calibrates it with its own findings (`skills/ai-task-reviewer/SKILL.md`), and the teamlead records the verdict as before: the pass never sets one.

The run record gets `codex_review` with `status` (`ok`, `failed`, `timeout` or `skipped`), `target`, `model`, the finding count and a `note` on failure, and the packet names the result. A failed pass leaves its reason in the findings block and does not stop `ai-task review`.

`ai-task review <run-id> --codex-only` runs only the pass. It writes the block and the run record and leaves the packet, the run status, the review queue and the verify gate alone, so a teamlead can add the pass after the reviewer finished or run it on a finished run:

```bash
ai-task review <run-id> --codex-only --codex-commit <merge sha>
```

**`cleanup`** is conservative. It records candidates and run metadata. It does not delete run logs automatically. Use `cleanup --remove-worktrees` after merged PRs to drop git worktrees for stale runs.

**Worktree removal is guarded twice.** Before removing any worktree, whatever the run status, `cleanup` asks two questions and keeps the worktree if either comes back positive:

| Question | How | Kept when |
|----------|-----|-----------|
| Does the working tree hold uncommitted work? | `git status --porcelain` inside the worktree, untracked files included | Anything is listed |
| Does the branch hold commits the base does not have? | `git rev-list --count <base>..<branch>` | Count above zero, or it cannot be determined |

A kept worktree is printed as `warning: skipped worktree for <run-id>: <reason>` and recorded in the cleanup report, never dropped silently. Untracked files count because the run release contract leaves the commit to the teamlead, so an implement run that ended early leaves real work sitting uncommitted, and nothing else signals it. `--force` is the single override for both guards and it discards that work. A worktree that is clean and not ahead is removed with no ceremony.

The same two questions gate the automatic prune on `complete`, so worktrees stop accumulating on the happy path without a manual sweep. `cleanup --remove-worktrees` stays the tool for whatever the happy path did not reach.

**The run branch goes with the worktree.** Removing a worktree - through `cleanup --remove-worktrees` or `complete --remove-worktree` - also deletes its `ai-task/<task-id>-<suffix>` branch, but only when that branch has no commits the base branch lacks. A branch that is ahead is kept, reported by run id, branch name and commits-ahead count, and stays in the run's `worktree_branch` so the tool can still find it. Refs outside the `ai-task/` namespace are never touched. `--force` deletes an ahead branch too, on both commands, and discards those commits. `prune` never deletes refs: it names any `ai-task/*` branch still alive for a run record it is about to drop, so removing the record cannot silently orphan one.

**`prune`** removes disk and state for finished runs (`done`, `dry_run`; optional `--include-failed`). It deletes `.ai-task/runs/<run-id>/`, drops the run from `state.json`, and clears leases pointing at that run. Runs whose worktree **still exists** are skipped until you merge and run `complete --remove-worktree`.

**A vanished worktree does not block prune.** The skip asks whether the directory is there, not merely whether the record names one. When `worktree_path` points at a directory that is gone - an operator's own `git worktree remove`, a deleted checkout, a moved repo - `prune` clears the stale `worktree_path` / `worktree_branch` fields, reports the run under "Cleared stale worktree_path", and lets the record through. Without that check a record could never be pruned again by any supported command.

```bash
ai-task prune --dry-run
ai-task prune --older-than 7d --yes
ai-task prune --keep-last 3 --yes
ai-task prune --run-id <run-id> --yes
ai-task prune --older-than 30d --cleanup-reports --yes
```

Destructive prune requires `--yes`. Preview with `--dry-run` first.

### Verify (before review)

Configurable stack profiles in policy (`docs/ai-task-verify.md`): **python**, **node**, **dotnet** (+ aliases `full`/`quick` for Python). Set `default_profile` per repo on init; use task `Verify:` when stacks mix. The bundled template default: **`python-full`**, **`allow_skip = false`**. Stack detection sees `package.json` at the repo root **or one level below it** (`web/`, `frontend/`, …; `node_modules/` and dot-dirs excluded) — deeper monorepo layouts are not auto-detected, use per-task `Verify:` there.

**Pipefail contract (custom profiles).** Profile commands run through bash/zsh with **`-o pipefail`**: a failing stage of any pipe **written in the profile command itself** fails the step with that stage's exit code, so `npm run build 2>&1 | tail -5` can no longer report PASS off tail's exit 0 while the build fails. **Nested-shell caveat:** the guard does *not* reach pipes inside a nested shell wrapper — `bash -c 'cd web && npm run build 2>&1 | tail -5'` starts an inner shell without pipefail, the pipe lives there, and tail's exit code wins again (`policy sync` preserves local profiles, so a repo that vendored a nested-wrapper profile keeps the hole until the profile is edited). Convention: write profile commands **flat** (`cd web && npm run build 2>&1 | tail -5`, no `bash -c '…'` wrapper); if a wrapper is unavoidable, start the inner command with `set -o pipefail;`. `verify` warns when a profile command nests a pipe inside `bash -c`/`sh -c`/`zsh -c`, naming the profile; set `[verify] nested_shell_pipe = "fail"` to refuse to run such profiles instead. On hosts without bash/zsh (Windows `cmd.exe`) there is no pipefail equivalent — avoid pipes in profile commands there (each result records `pipefail: true/false`).

```bash
ai-task verify --run-id <run-id>
ai-task verify --task-id TASK-001 --dry-run
ai-task review <run-id>   # fails until verify passed when require_before_review = true
```

Optional task field: `Verify: quick` in the backlog block.

### Out-of-scope backlog edit guard

Agent-authored scope creep through backlog edits must be visible **at run finalize**, not after merge-back (incident shape: an implement run silently appended a 44-task phase to the target repo's `BACKLOG.md`, discovered only by a manual tree diff).

How it works:

1. **Launch:** `ai-task run` snapshots the configured task files from the run working tree into `.ai-task/runs/<run-id>/scope-pre/` and records the manifest on the run (`scope_guard`). Dry runs are skipped.
2. **Finalize:** every terminal transition (waited success/failure, stalled auto-stop, quota-exhausted attempts, quota resume, and the orphan reaper that finalizes detached runs) diffs each configured file against its snapshot and writes **`out_of_scope_edits`** onto the run record (`[]` when clean).
3. **Visibility:** `status --json` includes `out_of_scope_edits` per run, plain `status` prints an operator alert, `run --wait` prints a summary line, and detection auto-logs a machine `out_of_scope_edits` decision row (`signals.auto = true`).

**In scope (never flagged):** any change confined to the run's **own task block** — the checkbox flip to `[x]`, DOD notes, edits between its checkbox line and the next checkbox/`## ` heading. **Flagged:** foreign task blocks added/modified/removed (`task_added` / `task_modified` / `task_removed` with the task id), new or removed `## ` sections (`section_added` / `section_removed`), other non-task content changes (`content_added` / `content_removed`, e.g. preamble text), and a deleted task file (`file_removed`). A configured file with no checkbox blocks flags every changed line. Lists longer than 200 entries are truncated with a final `truncated` marker.

**Policy (`[scope_guard]`):**

```toml
[scope_guard]
enabled = true
mode = "warn"                # warn | require_ack
task_files = ["BACKLOG.md"]  # relative to the run working tree
```

- `mode = "warn"` (default) reports without blocking.
- `mode = "require_ack"` blocks **`verdict approve`** and **`complete`** (the merge-back path) until the operator either reverts the edits or logs an acknowledgment decision row referencing the run:

```bash
ai-task decision log --phase verdict --choice scope_ack \
  --task-ids <TASK-ID> --run-ids <run-id> --reason "why the edits stay"
```

Best-effort: evaluation never fails the run itself; runs launched before the guard existed (no snapshot manifest) are skipped, and a missing/unreadable snapshot degrades to no report rather than an error. In non-worktree runs the diff covers the shared working tree, so operator edits made during the run are attributed to it — prefer worktrees for clean attribution.

**Default-mode posture:** `mode = "warn"` stays the shipped default. Rationale: in the solo-operator flow the backlog author, the run operator, and the reviewer are the same person — the guard's value is visibility, and a hard gate would only re-ask the person who wrote the edits, weakening headless throughput for no new information. Switch to `mode = "require_ack"` as soon as backlog text can come from someone other than the operator (second operator, shared `BACKLOG.md` via a git remote, externally contributed task blocks). This is a documented rule rather than an auto-switch because cheap per-block authorship detection does not exist: `operator_identity` identifies the *current* operator, but attributing a backlog block to its author would need git-blame heuristics that break across rebases and reflows. See «Two operators» and «Untrusted backlog input» below.

#### Sensitive control-file watch

Beyond the configured task files, the launch snapshot also records SHA-256 hashes of the **sensitive control files** — `.gitmodules`, `.ai-task/config.toml`, and `.ai-task/policies/*.toml`. These are config-as-code (verify command strings, backend argv with its permission flags, quota refresh sources, submodule URLs): an agent edit there changes what gets *executed* later, which a backlog-only diff never sees. At finalize the hashes are recomputed and changed/added/removed files land on the run record as **`sensitive_file_edits`** (`[]` when clean; kinds `file_modified` / `file_added` / `file_removed`), surfaced by `status --json`, a plain-`status` operator alert, the `run --wait` summary line, and an auto-logged `sensitive_file_edits` decision row (`signals.auto = true`).

The snapshot is hash-only (no policy copies in the run dir) and the watch is **informational in both modes** — `require_ack` gates only backlog `out_of_scope_edits`; sensitive edits warn, they do not gate merge-back. Runs launched before the watch existed (no `sensitive` key in the guard manifest) are skipped. Note that in worktree runs `.ai-task/` is gitignored and absent from the worktree, so an agent *creating* one there flags as `file_added`; `.gitmodules` is tracked and diffs normally. The window *between* runs is covered by the persistent policy-hash baseline (`.ai-task/policy-hashes.json`) checked at `run`/`verify`/`plan --bulk` entry — see "Policy sync" above.

#### Untrusted backlog input

The packet embeds the task's backlog block verbatim and the backend runs with per-action permission prompts disabled — whoever writes a task block writes instructions the agent will follow. When backlog text comes from someone other than the operator (second operator, shared `BACKLOG.md` pulled from a remote, a contributed PR, pasted text), verify before a headless run:

1. **Diff the block against its last reviewed state** (`git log -p -- BACKLOG.md`, or the remote diff at pull) and read the **whole block**, not the title — Task Context, DOD, `Verify:` and `Agent:` lines all reach the packet verbatim.
2. **Look for gate-bypass and egress instructions** — "skip verify", "push", "force", "ignore the policy", network calls (`curl`/`wget`) or secret-file reads in the DOD/verify text. The verify gate checks exit codes, not intent; a payload that keeps tests green sails through.
3. **Set `[scope_guard] mode = "require_ack"`** so out-of-scope backlog edits block merge-back instead of warning.
4. **Prefer a reviewed wave** (`verify` → `review` → `verdict` per run) over fire-and-forget, and never add `--confirm-risk` to a foreign-authored block without reading it.
5. **At finalize, read `out_of_scope_edits` and `sensitive_file_edits`** on the run record (plus the working-tree diff) before merge-back.

**Residual, out of scope (accepted):** mid-run network/push egress is unobserved. The CLI is a launcher/finalizer with no mid-run observation point, and no backend asks a person mid-run: the Claude worker lets auto mode decide, the others approve everything or rely on their own sandbox — egress control belongs to a sandbox/network layer around the backend process, not to post-hoc file diffs in this CLI.

### Teamlead decisions and parallel analysis

```bash
ai-task plan --auto-batch
ai-task parallel-plan --auto-batch --json
ai-task decision log --phase parallel --choice parallel_waves --reason "..." --signals-json '{}'
ai-task decision reflect --since 7d
ai-task decision analytics --since 30d --json
ai-task decision analytics --since 30d --format md
ai-task retro --since 30d
ai-task verdict <run-id> approve --reflection "verify passed"
```

Safe dispatch pattern:

1. Size a **wave batch** with `plan --auto-batch` or `plan --batch N`.
2. Run `parallel-plan --json` on that exact batch.
3. Execute returned **sub-waves** one by one.
4. Inside each sub-wave, launch up to `parallel.max_concurrent` separate `ai-task run TASK-ID` in worktrees **without** `--wait`.
5. For each run, complete `verify` → `review` → `verdict` before advancing to the next sub-wave.

Detached sub-wave monitoring:

- Record the run ids printed by each `ai-task run TASK-ID`.
- Prefer `ai-task wait-runs <run-id>...`; it polls the normal `status --json` path until all target run ids leave `running` / `paused`.
- For long unattended waves add `--resume-on-quota` so the helper also waits through `waiting_quota`, sleeps until the window resets, probes Claude, and re-launches the same packet in the same worktree.
- Use `--interval SECONDS`, `--timeout SECONDS`, and `--json` for scripts.
- Fallback shell shape: use `while active; do sleep; done`, where the predicate returns success only while at least one target run is still active.
- Do **not** use `until` with a predicate that returns success while runs are still active; `until` exits immediately on success and can falsely report completion.
- After the wait, run one final `status --json`, then continue with `verify` → `review` → `verdict`. Detached runs can have `exit_code: unknown`; review gates decide delivery readiness.

Anti-patterns:

- Launching all ids from all sub-waves at once when `parallel-plan` split them.
- Running `ai-task run TASK-A --wait`, then TASK-B, then TASK-C in one shell and calling it "parallel" (it is serial).

Terminology:

| Term | Meaning |
|------|---------|
| **Wave batch size** | How many eligible tasks go into planning input (`batch_size`, `auto_target`, capped by `max_size`). |
| **`parallel.max_concurrent`** | Max concurrent runs inside one returned sub-wave (often 3). |

Factual analytics writes `decisions-YYYY-MM.md` and `.html`. Interactive retro (blocking Q&A, backlog tasks) uses `ai-task retro` then skill **ai-task-retro**. See [ai-task-decisions.md](ai-task-decisions.md).

The journal is used by **ai-task-teamlead** and **ai-task-maintainer** for tuning.

### Delivery health SLO gates

`decision analytics` now checks four SLO thresholds against the run window and surfaces violations in plain text, JSON, and Markdown reports:

| Code | Metric | Default threshold | Recommendation |
|------|--------|-------------------|----------------|
| `slo_high_rework_rate` | `rework_rate` | > 50% | Pause wave → retro → product handoff |
| `slo_high_implicit_retry_rate` | `implicit_retry_count / runs_in_window` | > 50% | Retro → check verify/policy config |
| `slo_many_runs_without_verdict` | `runs_without_verdict` | > 5 | Run `verdict` for pending runs |
| `slo_many_failed_runs` | `failed_runs` | > 3 | Maintainer intervention |

Plain text alert format (appended after warnings):

```
SLO ALERT [slo_high_rework_rate]: rework_rate 60% exceeds SLO threshold 50%
  -> pause wave → run retro → handoff to product for backlog/DoR fixes
```

**Tuning thresholds** — add to `.ai-task/policies/default.toml`:

```toml
[slo]
max_rework_rate = 0.3          # tighten to 30%
max_implicit_retry_rate = 0.5
max_runs_without_verdict = 5
max_failed_runs = 3
```

The `[slo]` section is commented-out in the init template; uncomment and tune as needed. Setting a threshold to `0` effectively disables that gate (no value exceeds 0 as a greater-than check).

### Project analytics report (`report`)

Rich **HTML dashboard** from `BACKLOG.md` and run history (burndown, velocity, Gantt, backends, verify/verdict, phase breakdown, dependency graph, critical path). Distinct from **`decision analytics`** (journal tables) and **`status --json`** (operator snapshot).

```bash
ai-task report
ai-task report --output /tmp/my-report.html
ai-task report --since 7d                         # runs in the last 7 days
ai-task report --since 2026-05-20                 # runs since start of that date (UTC)
ai-task report --since 2026-05-20T14:00:00Z       # runs since an absolute timestamp
ai-task report --since 2026-05-20T17:00:00+03:00  # with timezone offset
ai-task report --last 10                          # last 10 runs regardless of age
ai-task report --last 5                           # last 5 deliveries
```

**`--since SPEC`** filters run-timeline charts and metrics to runs whose reference time
(`finished_at` → `completed_at` → `created_at`) is ≥ the cutoff. The backlog task table is
always full-repo (not filtered). The HTML header and CLI stdout show the active window
(e.g. "Runs since 2026-05-20 00:00 UTC · 12 runs").

**Rotated backlog archives.** The report and the recurrence metric are
**audit readers**: they merge the active `BACKLOG.md` with rotated archives
(`backlog/archive/BACKLOG-*.md` by default; override via policy `[analytics] archive_glob`)
so delivered history survives a sdlc-backlog-rotate. Ids de-duplicate with the **active file
winning** on collision; archived tasks are marked as history (milestone `ARCH`, phase
`Archived`, an **Archived** scorecard stat, excluded from the live M1/M2+ phase charts)
so charts distinguish live scope from rotated history. An unreadable archive file degrades
the report to the readable files with a visible warning banner in the HTML (plus a stdout
warning); the same warning reaches `decision analytics` output and the retro packet.
Delivery-path readers — `plan`, `backlog-order`, `dor` — stay **active-only** per the
archive policy and never read the archive (regression-tested; see the **sdlc-backlog-rotate**
skill for the full reader matrix).

SPEC accepts three shapes:
1. **Relative duration** — `7d`, `24h`, `30m`, `60s` (interpreted as *now minus duration*, UTC).
2. **Date only** — `YYYY-MM-DD` (interpreted as 00:00:00 UTC on that calendar day).
3. **Absolute ISO-8601** — e.g. `2026-05-20T14:00:00Z` or `2026-05-20T14:00:00+03:00`.
   Naive datetime (no timezone) is treated as UTC.

**`--last N`** keeps only the N most recent runs (sorted by `created_at`, tie-break
`run_sort_key`). Use when you want «last five deliveries» instead of a calendar window. The
HTML header shows "Last N runs · M runs". If N exceeds available runs, all runs are used
and a note is printed to stdout. **Mutually exclusive with `--since`** — combining both
exits with a non-zero code and an actionable error message.

- Requires `ai-task init` (writes under `.ai-task/reports/report.html` by default).
- First run installs optional deps from `requirements-analytics.txt` (plotly, networkx, numpy).
- **ai-task-teamlead** runs this when the user asks for a dashboard or project visualization; share a markdown link to `.ai-task/reports/report.html` (repo-relative, same as decision journal HTML — not a bare `file://` URL in chat).

Implementation: `scripts/ai_task/analytics.py` (networkx/numpy/plotly imported lazily; `scripts/analytics.py` is a thin shim kept for direct calls with `--repo`, `--output`, `--since`, and `--last`).

## User Notes

Use `ai-task note` while agents are running:

```bash
ai-task note "do not change the public API in this task" --run-id <run-id>
```

Notes are appended to `.ai-task/inbox.jsonl` and attached to the run when a run id is provided.

## Tests

This kit ships no test suite for the CLI.

`status --json` includes `dependency_cycles` when `Depends on` forms a loop (warnings also print on `plan`).
