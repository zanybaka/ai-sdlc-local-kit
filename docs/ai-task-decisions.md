# ai-task decision journal

Append-only log of **teamlead choices** for later analytics and maintainer-driven CLI improvements.

File: `.ai-task/decisions.jsonl` (one JSON object per line).

## Auto vs manual logging

**Manual (teamlead judgment):** `ai-task decision log` for non-routine choices: parallel strategy, overrides (`override_parallel_plan`, `override_verify_profile`, `override_backend`), delivery retries you decided on, verdict narrative, cross-phase escalation. Use the judgment template in `--reason` (problem, options, choice, expected).

**Auto (anomaly stubs only):** when `[decisions] auto_log_anomalies = true` in policy (default on), the CLI appends rows on anomalies only — not every run:

| Trigger | Phase | Choice | `reason` |
|---------|-------|--------|----------|
| `verify` failed | `verify` | `verify_failed` | one-liner or empty |
| Second+ `run` for same `task_id` | `delivery` | `retry_run` | prior run count |
| Start on limit-fallback backend | `delivery` | `limit_fallback` | backend name |
| Limit during `run --wait`, switch backend | `delivery` | `limit_fallback` | from → to |
| `verdict` rework / split / escalate | `verdict` | same as verdict | one-liner |
| `run --confirm-risk` with risk gates | `assign` | `confirm_risk` | flag note |
| Quota source unavailable at dispatch | `plan` / `delivery` | `quota_blind_dispatch` | unavailable reason |
| Out-of-scope backlog edits at finalize | `delivery` | `out_of_scope_edits` | edit count + task |

Auto rows set `signals.auto = true`. `run_ids` and `task_ids` are filled like manual `decision log`. Teamlead enriches `reason` later or closes with `decision result`. Set `auto_log_anomalies = false` to disable.

When `verify_failed` or `retry_run` appears with a DoD/profile mismatch, treat the stub as a prompt to enrich the decision row and open cross-phase handoff (`delivery_feedback`) for judgment-bearing gaps. Mechanical, validator-named metadata fixes may be applied inline with a `mechanical_metadata_fix` row instead (see `docs/ai-task-backlog-contract.md` → Metadata ownership). For routine waves the auto stubs **are** the journal — no narrative duplicate is required.

## Judgment vs telemetry

The journal holds two populations that must not be mixed in analytics:

- **Operator judgment** — rows authored by the teamlead via `decision log` (`signals.auto` absent or false). Only these rows owe grading; ungraded judgment rows are real judgment debt.
- **Machine telemetry** — rows emitted by code paths without operator-authored text: every auto-anomaly trigger above **and `decision ingest` stubs**. They always carry `signals.auto = true` and exist for the audit trail, not for grading. (In one project 167 of 223 rows were "pending", where the tail was `quota_blind_dispatch`, `limit_fallback`, `confirm_risk`, and `retry_run` echoes that would never be graded.)

Analytics consequences (`decision analytics`, factual MD/HTML reports, `retro`):

- **Pending, stale-pending, and duplicate-reflection are computed over operator judgment rows only.** The headline `pending`, the `by_phase`/`by_choice` tables, weekly trends, top regrets, and journal-credibility heuristics cover judgment rows; `judgment_total` reports their count.
- **Machine-row volumes are reported separately**: JSON gains a `machine` object (`total`, `pending`, `events`, `by_choice`) and the factual report a **Machine-logged rows (telemetry)** section. `events` expands collapsed rows (`signals.count`), so telemetry volume stays visible.
- Machine rows remain in `entries` and can still be graded with `decision result` when a telemetry row deserves judgment; grading moves nothing — classification follows `signals.auto`, not `result`.

**`quota_blind_dispatch` dedupe:** repeated identical rows within one wave — same phase, same `reason`, same planned batch (`signals.wave`, the `last_batch` task ids) — collapse into the first row instead of appending: `signals.count` increments, `task_ids`/`run_ids` union, and `signals.last_at` records the latest echo. A different reason, a new wave, or a row already graded starts a fresh row.

## Retention

- **Stored on disk** in the target repo for the life of `.ai-task/` (created on `ai-task init`).
- **Append-only** for new rows; `decision result` updates the matching line in place (file stays).
- **`prune` and `cleanup` do not delete** `decisions.jsonl` (unlike old run logs).
- If `.ai-task/` is gitignored, the journal stays **local** unless you copy or commit it on purpose. For long-term analytics across machines, archive the file or track it in git in that project.

## Record a decision

```bash
ai-task decision log \
  --phase parallel \
  --choice parallel_waves \
  --reason "worktrees on; layers frontend+backend; paths disjoint" \
  --task-ids OPEN-001,OPEN-002 \
  --signals-json '{"worktrees":true,"waves":[["OPEN-001","OPEN-002"]]}'
```

When `--run-ids` is omitted, `decision log` auto-collects run ids from `.ai-task/state.json` for the logged `--task-ids`: all matching runs when `task_ids` equals `last_batch`, otherwise the most recent run per task (status `done`, `needs_review`, `failed`, or `running`). Pass `--run-ids id1,id2` to override.

**Phases:** `plan`, `assign`, `parallel`, `verify`, `review`, `delivery`, `verdict`, `release`, `reflect`, `cross` (product↔teamlead or user escalation). Teamlead journal discipline (no per-wave minimum, when the full judgment template is required, grading cadence) — normative: `skills/ai-task-teamlead/reference-journal.md`.

`cross` remains required in monolithic mode. Monolithic removes only user confirmation between waves, not W6 handoff. Log `delivery_feedback` before product edits (judgment calls) — or `mechanical_metadata_fix` for an inline validator-named fix — then `product_response` after backlog updates, and rerun `dor` or `plan --strict` before continuing. See `skills/ai-task-teamlead/SKILL.md` and `cursor-commands/ai-task-teamlead.md`.

**Judgment template (teamlead):** normative: `skills/ai-task-teamlead/reference-journal.md` → Judgment template (problem, options, choice, reason, expected; close with `decision result` + reflection; override choices).

**Choices:** free text (`sequential`, `auto_parallel`, `profile:node-full`, `verdict:rework`, …).

## Close the loop (result + reflection)

After verify/review/merge, mark whether the choice worked:

```bash
ai-task decision result good --reflection "both runs passed verify; no file conflicts"
ai-task decision result dec-20260525T120000Z-abc123 bad --reflection "merge conflict in src/api"
```

Results: `good`, `bad`, `unknown`, `pending`.

## Self-analysis (teamlead)

**At engagement end (retro)** — once per engagement, not per wave:

```bash
ai-task decision reflect --since 7d
ai-task decision reflect --json
ai-task decision reflect --since 7d --strict
```

Suggests `good`/`bad` for **pending** rows by linking stored `run_ids` to `verify_status` and run `status`. When `run_ids` is empty, reflect suggests **`unknown`** (not `good`) and prints `warning: no run_ids — manual review required`. `--strict` exits non-zero if runs for `task_ids` would suggest `good` but the journal row has no stored `run_ids` (bulk-good without linkage).

`decision result good` on a row with empty `run_ids` prints a warning unless you pass `--force`.

Teamlead should then run `decision result` for each suggestion (or override with reason in `--reflection`). Do **not** bulk-mark all pending rows `good` in one identical shot.

When `decision reflect` flags a parallel-plan override, rename the logged choice to `override_parallel_plan` (or re-log with that choice). Scan older rows with `ai-task decision check-overrides --since 7d` (`--dry-run` to preview).

## Maintainer analytics

```bash
ai-task decision analytics --since 30d
ai-task decision analytics --json
ai-task decision analytics --since 30d --format md
```

`--format md` writes `.ai-task/reports/decisions-YYYY-MM.md` and prints the report. Storage stays **JSONL only** (no SQLite).

Use aggregates (`by_phase`, `by_choice`, good/bad counts) to tune policy, heuristics in `parallel-plan`, and defaults.

## Delivery metrics

`ai-task decision analytics --json` (and `--format md`) includes a **`delivery`** object when `.ai-task/state.json` exists:

| Field | Meaning |
|-------|---------|
| `runs_in_window` | Runs in the `--since` window (or all) |
| `by_verdict` | Counts for approve, rework, split, defer, escalate |
| `rework_rate` | `rework` verdicts / runs with any verdict |
| `implicit_retry_count` | Tasks with more than one run where an earlier run had status `failed` or `needs_review` |
| `runs_without_verdict` | Runs in the window with no verdict (or not one of approve, rework, split, defer, escalate) |
| `failed_runs` | Runs in the window with `status` `failed` |
| `verify.passed` / `failed` / `skipped` | From run `verify_status` |
| `median_run_duration_seconds` | Median of `created_at` → `finished_at` when both exist |
| `by_backend` | Per-backend breakdown: `runs`, `failed_runs`, `verify_failed`, `rework` per backend name (quota-gated vs fallback runs are distinguishable by backend name; legacy runs missing `backend` count under `unknown`) |
| `by_verify_profile` | Same breakdown keyed by run `verify_profile` (`unknown` for legacy runs) |

Text output prints a one-line delivery summary after decision counts. The factual MD/HTML report renders `by_backend` and `by_verify_profile` as small tables under **Delivery (runs)**. Worked read: if `by_backend` shows the cursor fallback failing verify 2x more than claude on node tasks (cross-check `by_verify_profile`), route node tasks to claude in policy instead of the fallback.

## Value scorecard

`ai-task decision analytics --json` (and `--format md`/`html`) includes a **`scorecard`** object that puts **cost next to benefit** for one *engagement* — the answer to "is ai-task worth it here". The factual report renders it as a **Value scorecard** table under Delivery (runs).

**Engagement = the analyzed window** (the `--since` window, or all-time when none). Run records carry no clean wave/engagement boundary (no per-wave stamp survives on the run), so the window is the cheapest defensible unit and is named in the `engagement` field. Every cell is **either a number or `{"unmeasured": "<reason>"}`** — it degrades to "unmeasured (reason)" rather than printing a wrong number.

| Cell | Meaning | Grounded in |
|------|---------|-------------|
| `tasks_delivered` | Runs completed in the window | `delivery.runs_in_window` |
| `gate_caught_reworks` | Verdicts == `rework` — the review/verdict gate's real catches, distinct from clean approves | `delivery.by_verdict.rework` |
| `operator_interventions` | Judgment journal rows (machine `signals.auto` stubs excluded) with choice `escalate` / `confirm_risk` / `override_*` — operator judgment, not auto-stubs | decisions journal |
| `overhead_ratio` | (verify+review+verdict elapsed) / implement elapsed | **measured from phase stamps**; fully-legacy windows still read `unmeasured` |
| `quota_cost` | Sum of high-confidence per-run quota deltas (`delta_percentage`, % of quota); `partial: true` when any matched run's cost is incomplete | Completion samples |

**`overhead_ratio` is measured from per-phase stamps.** The run's own wall-clock (`created_at`→`finished_at`) is the **implement** phase. `verify` / `review` / `verdict` are separate CLI invocations that run *after* the implement run against the run record; each stamps its elapsed wall-clock onto `run["phase_timing"][phase]` (`elapsed_seconds`, `runs`, `first_started_at`, `last_finished_at`). The cell is then **`ratio = (summed verify+review+verdict elapsed) / (summed implement elapsed)`** over the window's runs.

- **Accumulate across repeats.** A rework loop re-runs verify/review, so each invocation *adds* to `elapsed_seconds` (and increments `runs`) rather than overwriting — the ratio reflects the *true total* orchestration cost of a task that needed three review rounds, not the last round only.
- **Honest degradation.** A phase that never ran in the window is marked `unmeasured` per-component and the ratio is flagged `partial` (computed from the phases that did run). A window where **no** run carries `phase_timing` (all legacy) degrades to the original `{"unmeasured": "no phase timing ..."}` — never a wrong number. The trend computes the same ratio per ISO-week bucket on the same rule.

**`quota_cost` consumes the same authoritative-per-`run_id` samples calibration trusts.** The calibration writer emits two lines per detached/wave run sharing a `run_id` (a partial `launched` trace + the completion sample with both snapshots); the scorecard de-duplicates by `run_id`, prefers the non-partial completion line, and never double-counts the `launched` line. A matched run that is partial / low-confidence / has no usable delta marks the engagement cost `partial`.

Worked read: an **overhead ratio of 4.0× on a 5-task wave of trivial tasks** (orchestration spending four minutes of verify/review/verdict per minute of implement) means those tasks did not earn the gate — they belong in a plain `sdlc-implement-all` run, not the supervised wave. Conversely, a wave where `gate_caught_reworks` is high and `overhead_ratio` + `quota_cost` are modest is the gate paying for itself — keep supervising.

## Recurrence / sibling-rate

`rework_rate` and good/bad measure teamlead **judgment** and re-delivery, not whether fixes **generalize**. A wave can show `rework_rate`≈0 while most tasks just re-patch siblings of already-fixed bugs (one delivery phase: ~88% siblings, `rework_rate` 0.077). `ai-task decision analytics --json` (and `--format md`) includes a **`recurrence`** object computed from the **backlog** (not run state), so it is present even without `state.json`:

| Field | Meaning |
|-------|---------|
| `available` | `false` when the source backlog is missing/unreadable (all counts zero) |
| `delivered_count` | Delivered (`- [x]`) tasks scanned in the backlog |
| `recurrence_count` | Delivered tasks whose block matches a sibling/regression marker |
| `sibling_rate` | `recurrence_count / delivered_count` (rounded; `null` when none delivered) |
| `sibling_task_ids` | Ids of the matched delivered tasks |
| `markers` | Marker phrases used (lowercased) |
| `threshold` | Warn threshold for `high_sibling_rate` |
| `backlog` | Source backlog path (relative to repo root) |
| `archive_glob` | Rotated-archive glob merged into the delivered population |
| `archive_files` | Archive files successfully merged (repo-relative) |
| `archived_delivered_count` | Delivered tasks that exist only in the archive |
| `archive_warnings` | Unreadable archive files skipped (recurrence degraded to readable files) |

A delivered task counts as a sibling when its block text (title + Task Context + DoD) contains any configured marker (default: `sibling of`, `regression of`, `root cause of`, `re-drift`). Open (`- [ ]`) and deferred (`- [~]`) tasks are **not** counted even if they match. The backlog has no per-task timestamps, so the rate is computed over the whole backlog file and is **independent of the `--since` window**.

**Rotated archives are merged.** Recurrence is an **audit reader**: the delivered population is the active backlog **plus** rotated archives (`backlog/archive/BACKLOG-*.md` by default), de-duplicated by task id with the **active file winning** on collision — so the sibling rate keeps measuring the full delivered history after a sdlc-backlog-rotate instead of the small active set (selection bias the ai-task-retro skill warns about). An unreadable archive degrades gracefully to the readable files: each failure lands in `archive_warnings`, a `backlog_archive_unreadable` entry appears in `report.warnings`, and the factual MD/HTML report and retro packet show the warning. Delivery-path readers (`plan`, `backlog-order`, `dor`) never read the archive.

When `sibling_rate >= threshold` (default 0.5), `report.warnings` gains a **`high_sibling_rate`** entry and the factual MD/HTML report shows a **Recurrence (siblings)** section. The `ai-task report` dashboard surfaces a **Sibling rate** scorecard stat (red at/above threshold).

**Tuning** — add `[analytics]` to `.ai-task/policies/default.toml` (block is in the init template):
```toml
[analytics]
recurrence_warn_rate = 0.5
recurrence_markers = ["sibling of", "regression of", "root cause of", "re-drift"]
# recurrence_backlog = "BACKLOG.md"  # source backlog path, relative to repo root
# archive_glob = "backlog/archive/BACKLOG-*.md"  # rotated archives merged by audit readers
```
Set `recurrence_warn_rate = 0` to disable the warning while keeping the metric. See teamlead **Sibling-DoD** / **honest `bad`-grading** for the judgment-side counterpart.

## SLO gates

`decision analytics` evaluates four delivery health SLO thresholds and emits violations alongside delivery metrics:

| Code | Metric | Default threshold | Escalation |
|------|--------|-------------------|------------|
| `slo_high_rework_rate` | `rework_rate` | > 50% | W6 → product handoff (DoR/backlog quality) |
| `slo_high_implicit_retry_rate` | `implicit_retry_count / runs_in_window` | > 50% | Retro → check verify/policy config |
| `slo_many_runs_without_verdict` | `runs_without_verdict` | > 5 | Teamlead: run `verdict` before next wave |
| `slo_many_failed_runs` | `failed_runs` | > 3 | Maintainer: investigate backend/policy |
| `[parallel] overlap_warn_share` | W2 overlap gate: tasks on most-contended predicted file ÷ batch size | ≥ 30% | Teamlead recommends sequential / pre-split waves before dispatch (skill-side gate; no analytics violation emitted) |

The last row is read by the teamlead W2 overlap gate (`parallel_overlap_warn_share`, clamped 0–1), not evaluated by `decision analytics`; calibrate it per repo in `[parallel] overlap_warn_share` — local value wins on policy sync.

**Text output** (appended after `warnings:`):
```
SLO ALERT [slo_high_rework_rate]: rework_rate 60% exceeds SLO threshold 50%
  -> pause wave → run retro → handoff to product for backlog/DoR fixes
```

**JSON** — top-level `slo_violations` list; **Markdown/HTML** — `## SLO gate violations` section when non-empty.

**Threshold tuning** — add `[slo]` to `.ai-task/policies/default.toml` (commented-out block is in the init template):
```toml
[slo]
max_rework_rate = 0.3
max_implicit_retry_rate = 0.5
max_runs_without_verdict = 5
max_failed_runs = 3
```

## Factual reports (MD + HTML)

`ai-task decision analytics --format md` writes **both**:

- `.ai-task/reports/decisions-YYYY-MM.md`
- `.ai-task/reports/decisions-YYYY-MM.html`

Same factual content: phase/choice tables (judgment rows), the **Machine-logged rows (telemetry)** section, delivery metrics (including implicit retries, runs without verdict, failed runs), **Judgment quality** (empty reasons, duplicate reflections, phase coverage, overrides, auto vs manual), weekly good/bad trends, **Top regrets** (`bad` + reflection), **Stale pending** (judgment rows pending older than 7 days), and **Warnings** (for example high `rework_rate`, empty-reason rate, duplicate-reflection rate, formal rework zero with implicit retries detected, or `high_sibling_rate`), plus the **Recurrence (siblings)** section. `--format html` writes only the HTML pair.

`--json` includes a `report` object with these summaries (full `entries` list remains for tooling).

### Judgment quality

`report.judgment_quality` summarizes journal hygiene (complements delivery metrics and coverage ratios):

| Field | Meaning |
|-------|---------|
| `empty_reason_count` | Decisions with blank `reason` |
| `duplicate_reflection_count` | Reflection lines that repeat an earlier non-empty reflection (each extra copy counts once); operator judgment rows only — machine rows (`signals.auto`) are excluded |
| `reflection_count` | Judgment decisions with non-empty `reflection` (denominator for duplicate rate) |
| `phases_present` / `phases_missing` | Against expected phases: plan, assign, parallel, verify, delivery, verdict, review, cross |
| `override_count` | Rows where `choice` starts with `override_` or `signals.override` is true |
| `auto_count` / `manual_count` / `auto_vs_manual_ratio` | From `signals.auto` (missing = manual) |

**Warnings** (also in factual MD/HTML): `high_empty_reason_rate` when empty reasons exceed 20% of decisions in the window; `high_duplicate_reflection_rate` when duplicate reflections exceed 50% of reflected rows.

## Interactive retro (`ai-task retro` + ai-task-retro)

```bash
ai-task retro --since 30d
```

Runs `decision reflect` (non-fatal), generates factual MD/HTML (including a **Journal credibility** subsection when sparse journal, implicit rework, or bulk `reflected_at` apply), and writes `.ai-task/packets/retro-YYYY-MM.md`. When the same flags apply, the CLI prints a short **journal credibility** note: do not treat all-good counts as proof of smooth delivery. Then load **ai-task-retro** in chat (cursor command `ai-task-retro.md` or say «ревью decisionов»): one blocking question at a time, improvement tasks in **ai-sdlc-local-kit** `BACKLOG.md`, and `decisions-YYYY-MM-retro.md` / `.html` in the target repo. Factual and retro files stay separate.

**Purpose:** teamlead **judgment** (problem, options, choice, self-grade) for improving teamlead/product skills and ai-task CLI — not a run event log. See `skills/ai-task-retro/SKILL.md`.

Optional third-party skills (profile setup): **kaizen** (process improvements), **lessons-learned** (incident-style 5-Whys when `bad` / rework spikes). **[agent-retro](https://github.com/giannimassi/agent-retro)** analyzes Claude Code session JSONL transcripts (not `decisions.jsonl`); useful in parallel, not wired into `ai-task retro`.

Load **ai-task-maintainer** when changing `scripts/ai-task.py` from this data.

## Parallel thinking helper

```bash
ai-task plan --auto-batch
ai-task parallel-plan --auto-batch --json
```

Returns `strategy`, `waves`, `reasoning`, per-task `signals` (paths, layers, broad scope). Teamlead **must** run this before auto-parallel and log the outcome with `decision log`.

## Parallel phase dispatch semantics

`parallel` decisions are about **sub-wave dispatch**, not a single "start everything now" switch.

1. Create one wave batch (`plan --auto-batch` or `plan --batch N`).
2. Run `parallel-plan --json` on that same batch.
3. Execute each returned sub-wave in order.
4. Inside one sub-wave, run up to `parallel.max_concurrent` detached `ai-task run TASK-ID` commands in separate worktrees (no `--wait`).
5. Complete `verify` → `review` → `verdict` for those runs, then move to the next sub-wave.

Two safety layers stay separate:

- **Git/worktree safety** isolates code edits and merge surfaces.
- **State safety** (`.ai-task/state.json`) uses the file lock helper and leases to serialize metadata writes only.

A state lock does not mean "no parallel runs". It only means state updates are serialized.

Terminology reminder:

- **Wave batch size** (`batch_size`, `auto_target`, up to `max_size`) selects planning input.
- **`parallel.max_concurrent`** limits concurrent runs inside one sub-wave.

Anti-pattern: three `ai-task run TASK-ID --wait` calls in one shell are always serial.

See teamlead `reference-journal.md` (decision journal discipline) and `reference.md` (parallel reasoning).
