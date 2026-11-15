# Teamlead reference — project analytics report and decision journal

Companion to `SKILL.md` (ai-task-teamlead); loaded on demand. Normative.

## Project analytics report (`ai-task report`)

Use when the user wants a **visual HTML dashboard** of delivery health (backlog progress, run timeline, backends, verify/verdict, critical path). Do **not** use it for interactive retro Q&A (**ai-task-retro**) or for the decision journal alone (**decision analytics**).

| Need | Command |
|------|---------|
| Plotly dashboard (burndown, velocity, Gantt, heatmap, DAG, critical path) | `ai-task report` |
| Dashboard filtered to recent runs (time window) | `ai-task report --since 7d` |
| Dashboard from specific date | `ai-task report --since 2026-05-20` |
| Dashboard from absolute timestamp | `ai-task report --since 2026-05-20T14:00:00Z` |
| Dashboard for last N deliveries (count, not time) | `ai-task report --last 10` |
| Decision journal tables, regrets, weekly trends | `decision analytics --since 30d --format md` |
| Live runs, cooldowns, next task | `status --json` (status template) |

**Preconditions:** `.ai-task/` exists (`init` if missing). `BACKLOG.md` at repo root. Runs are read via `status --json` inside `scripts/analytics.py`.

**Run (you, not the user):**

```bash
ai-task --repo "$REPO_ROOT" report
# optional: --output /path/to/custom.html
# optional: --since SPEC  (7d / YYYY-MM-DD / ISO-8601 datetime) — time window
# optional: --last N      (e.g. --last 10) — last N runs by recency; mutually exclusive with --since
```

- Default output: **`.ai-task/reports/report.html`** (created on first `init`).
- First run may **`pip install`** plotly, networkx, numpy from `requirements-analytics.txt` (can take a minute; say so if the user is waiting).
- On success, stdout includes `Report → …` with run count and critical-path length.

**Reply to the user:** one or two sentences on what the report shows (progress %, open count, optional ETA/pace if visible in stdout). Hand off the file with the **same link style as the decision journal** (see **HTML report handoff** below). Do **not** paste the HTML or dump CLI install logs unless debugging.

**When to offer or run without being asked:** end of a long engagement, after «как мы продвигаемся в целом?», «дашборд», «визуализация», «project analytics», or when status text is not enough and charts would help. Skip if `.ai-task` is absent and the user only wanted IDE backlog work (suggest `init` first).

### HTML report handoff (report + decision journal)

Use **one format** for every HTML under `.ai-task/reports/` (`report.html`, `decisions-YYYY-MM.html`, `decisions-YYYY-MM-retro.html`):

1. **Repo-relative path** from the target repo root (not a bare `file://` URL — Claude/Cursor chat usually does **not** make those clickable).
2. **Markdown link** so the UI can open the file:

```markdown
- [Project dashboard](.ai-task/reports/report.html)
- [Decision journal (May 2026)](.ai-task/reports/decisions-2026-05.html)
```

3. Do **not** put `file:///…` in the chat unless the user explicitly asked for a copy-paste `open` command.
4. Do **not** mix styles in one summary (report as `file://`, journal as relative path).
5. Absolute host paths only when the repo is outside the workspace and a relative link cannot resolve; still prefer markdown `[label](path)` over raw `file://`.

Open in system browser: user Cmd-clicks the link in the IDE, or runs `open` / `xdg-open` themselves — do not teach that unless they ask.


## Decision journal (required for learning)

Record **teamlead judgment** (problem, options, choice, self-grade), not only what ran. File: `.ai-task/decisions.jsonl`. Phases and CLI: **`docs/ai-task-decisions.md`** (includes `verify`, `delivery`, `verdict`).

**Primary value:** how you think under pressure — for improving this skill, product DoR, and ai-task CLI. Run telemetry in `state.json` is an **anchor**, not a substitute for `reason` / `reflection`.

### Judgment template (non-trivial decisions)

Embed in `--reason` (or structured bullets inside it):

| Field | Content |
|-------|---------|
| **problem** | What blocked, surprised, or forced a choice |
| **options** | At least two paths (including defer / ask user) |
| **choice** | What you picked |
| **reason** | Why now |
| **expected** | What success looks like |

After outcomes: `decision result good|bad|unknown --reflection "..."` (what happened vs expected; what you'd do differently).

For **`phase=parallel` rows the reflection is a parallelism-ROI record**: expected vs actual — hot-file overlap predicted vs merge conflicts/friction actually hit, wall-clock saved vs a sequential estimate (e.g. «expected 3-way parallel ≈ 0.5× wall-clock, no shared files; actual: 2 merge-backs conflicted on one shared state module, saving ≈ 0»). This is what calibrates the W2 overlap-gate threshold over time.

### When the full template is required (no per-wave minimum)

There is **no per-wave entry minimum**. The full judgment template is **required only** for:

| When | Phase / choice |
|------|----------------|
| Strategy differs from `parallel-plan` | `override_parallel_plan` |
| Profile differs from task `Verify:` / auto-detect | `override_verify_profile` |
| Backend differs from policy default for `Agent: auto` | `override_backend` |
| Escalation (user or cross-role) | `user_escalation`, verdict `escalate` |
| Product handoff | `delivery_feedback` |
| Inline mechanical metadata fix | `mechanical_metadata_fix` (task id + field + old→new) |

Routine waves rely on the CLI's **auto-emitted anomaly stubs** (`verify_failed`, `retry_run`, `limit_fallback`, rework/split/escalate verdicts, `confirm_risk` — `signals.auto=true`); do not duplicate them with narrative rows. W1 sizing (`wave_batch:auto|N`) and `phase=parallel` strategy rows stay (they carry `--signals-json` evidence) but need only a one-line reason when nothing was overridden.

### Override choices (first-class)

When you **disagree with tooling**, use explicit choice names (not generic `parallel_waves`):

- `override_parallel_plan` — logged strategy differs from `parallel-plan --json`
- `override_verify_profile` — profile differs from task `Verify:` or auto-detect
- `override_backend` — backend differs from policy default for `Agent: auto`

Always paste `parallel-plan` evidence in `--signals-json` when overriding.

### When to log

| Phase | Example choice |
|-------|----------------|
| `plan` | `wave_batch:auto`, `wave_batch:3` |
| `parallel` | `parallel_waves`, `sequential`, `sequential_waves` |
| `parallel` (override) | **`override_parallel_plan`** |
| `assign` | `backend:claude`, **`override_backend`** |
| `verify` | `profile:node-full`, **`override_verify_profile`**, **`manual_state_patch`** |
| `delivery` | `retry_after_needs_review`, `run_failed`, `limit_fallback` |
| `verdict` | `approve`, **`rework`**, `split`, `defer`, `escalate` |
| `reflect` | `wave_N_retro` |
| `cross` | `delivery_feedback`, `mechanical_metadata_fix`, `user_escalation`, `retro_complete` |

Always include **`--reason`** (full sentences, judgment template) and **`--signals-json`** with evidence. After wave runs exist, omit **`--run-ids`** — CLI auto-collects from `state.json` when `--task-ids` match `last_batch` or the latest run per task. Use **`--run-ids`** to override. Rows logged **before** the sub-wave launches (typical W1 plan / W2 parallel) get `run_ids []`; backfill them by re-emitting the row with explicit **`--run-ids`** at the W5 wave gate.

### Bad examples (do not)

- Bulk `decision result good` at end of batch with identical reflection
- Empty `--reason` or copy-paste reflection across waves
- Only `phase=parallel` for a batch with verify fixes, retries, or verdict rework
- Marking `good` without linked runs when they exist (CLI auto-fills `run_ids` from `state.json`; use `--run-ids` to override)

**Full template after:** any override (`override_parallel_plan` / `override_verify_profile` / `override_backend`), escalation, `delivery_feedback`, inline `mechanical_metadata_fix`. Verify anomalies, retries, limit fallbacks, and rework/split verdicts are **auto-stubbed** — enrich a stub only when real judgment was involved.

```bash
ai-task decision log --phase parallel --choice parallel_waves \
  --reason "problem: 3 tasks eligible. options: parallel_waves vs sequential (schema risk). choice: parallel_waves. reason: disjoint paths. expected: both verify green." \
  --task-ids A,B --signals-json '{...}'
ai-task decision log --phase verify --choice override_verify_profile \
  --reason "problem: INFRA-001 needs node-web not node-full. options: override vs defer. choice: node-web. expected: verify passes." \
  --task-ids INFRA-001 --signals-json '{"requested":"node-full","used":"node-web"}'
ai-task decision log --phase delivery --choice retry_after_needs_review \
  --reason "problem: review F-002 blocking. options: rework run vs split. choice: rework run. expected: verify green on retry." \
  --task-ids TASK-001
ai-task decision log --phase verdict --choice rework \
  --reason "problem: major finding F-003. options: rework vs split. choice: rework. expected: clean re-review." \
  --task-ids TASK-001 --run-ids RUN-REVIEW
ai-task decision result good --reflection "both passed verify; no merge conflicts"
```

**Self-analysis (engagement end — retro, not per wave):**

Reflect-and-grade runs **once per engagement** at retro time, not at every wave gate:

1. **`decision reflect --since 7d`** — apply suggested results row by row.
2. **`decision result good|bad|unknown`** per suggestion (or override with `--reflection`); **prohibit** identical bulk `good` on all pending rows in one minute. For `phase=parallel` rows, the reflection records **expected vs actual parallelism ROI** (Judgment template) — this calibrates the W2 overlap-gate threshold.
3. **`decision analytics`** — check `slo_violations` in text or JSON output; if any SLO gate fires: see routing table below.
4. Full retro after large batch: **`ai-task retro`** then **ai-task-retro**. Facts only: `decision analytics --format md`.

SLO violation routing (step 3):

| SLO code | Action |
|----------|--------|
| `slo_high_rework_rate` | W6 handoff → product (DoR/backlog quality) |
| `slo_high_implicit_retry_rate` | Schedule retro; check verify profile and policy config |
| `slo_many_runs_without_verdict` | Run `verdict` for pending runs before next wave |
| `slo_many_failed_runs` | Pause; maintainer intervention (`ai-task-maintainer`) |

If you would choose differently in hindsight, log `decision result bad` with reflection anyway.

**Grade `bad` (not `good`) when — so `bad=0` means something:**

- The owner **overruled** the call (e.g. you inline-fixed metadata and the owner said "always to product"). `bad`-count must reflect disagreement, not hide it behind a later `good`.
- A fix **knowingly leaves siblings** of the same class open (a point-fix where a class-guard was reachable) — see *Sibling tasks must close the class* (`reference-review-gates.md`).
- An **all-`good` self-graded wave is a smell**: you are the interested party grading your own calls, so a journal where the only `bad` came from the owner is measuring *owner disagreement*, not call quality. Challenge it — find the one call you'd redo and grade it honestly.

### Maintainer handoff

Tell the user: «Analytics in `.ai-task/decisions.jsonl`; ask maintainer to improve `parallel-plan` / policy if many `bad` on the same `choice`.»

