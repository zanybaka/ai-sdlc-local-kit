---
name: ai-task-maintainer
description: Design or extend the opt-in ai-task CLI and .ai-task policy (scripts/ai-task.py, supervision, backends). Use when changing ai-task code, default policy, or ADR scope. For daily backlog runs and status in chat, use ai-task-teamlead instead.
---

# AI Task Maintainer

Wave docs ownership split:

- CLI and locking mechanics: maintainer scope.
- The delivery operational checklist: teamlead scope.
- The operator playbook: `docs/ai-task-delivery-waves.md`.

Use this skill to **design or extend** the `ai-task` runtime (CLI, policy, supervision). The product name is "ai-task orchestrator"; this skill is the **maintainer** guide for that codebase, not the user-facing operator.

For **daily operations** (run backlog, status, pause, notes), load **`ai-task-teamlead`** or `/ai-task-teamlead` so the user never memorizes CLI flags. For wave-level command and policy semantics, point operators to `docs/ai-task-delivery-waves.md`.

Do not require `.ai-task` for ordinary `AGENTS.md`, `BACKLOG.md`, Cursor command, or Claude Code skill workflows.

## Lean scope (required)

Treat `ai-task` as a **lean orchestrator**, not a full teamlead platform. Intelligence stays in Cursor, Claude Code, or Codex CLIs. `ai-task` only routes backlog work, builds task packets, launches configured backends, and records run state.

Do not design features that duplicate vendor capabilities unless they are cross-vendor glue (same `BACKLOG.md`, fallback policy, unified run logs). See `docs/ai-task.md`.

### Build vs delegate

| Build in `ai-task` | Delegate to native CLI / IDE |
|--------------------|------------------------------|
| Backlog selection, priority, batches | Agent reasoning and code edits |
| Task packets | Tool use and permissions UX |
| Backend policy and limit fallback | Streaming UI, resume, subagents |
| Run journal (pid, logs, review hooks) | Hooks, skills loaded inside agent |

### Non-goals

- Second agent brain or planning loop on top of vendor CLIs.
- Autonomous polling daemon without an explicit user or batch command.
- Semantic progress beyond pid/logs.
- Replacing `/sdlc-implement-task` or IDE chat for simple single-task work.
- Auto-injecting inbox notes into a running process (store only until a resume design exists).

Extend supervision only in scoped tasks (for example a task that adds one supervision check), not by reimplementing Cursor background agents.

## Operating Model

- `BACKLOG.md` remains the human-readable source of truth for planned work.
- `.ai-task/` is runtime state only: policies, task packets, run records, logs, inbox notes, cleanup metadata, and leases.
- Agents receive small task packets, not the whole backlog, unless the user asks for broad planning.
- The runtime owns process lifecycle: select, assign, start, pause, stop, resume, review, cleanup, and run status in `.ai-task/state.json`. Final backlog edits still come from agent output or the user.
- Maintainer scope owns the `.ai-task/state.json` lock helper and write-safety behavior.
- User notes during execution are first-class input. Record them, classify whether they affect queued, running, review, or future work, then adjust safely.

## Required Capabilities

When designing or implementing `ai-task`, cover these command families:

- `init`: create opt-in `.ai-task` infrastructure for the current repo.
- `plan`: parse backlog, apply priority policy, and prepare a batch.
- `run`: launch one or more task packets through the runtime router.
- `status`: report running, paused, failed, review, and completed runs (`--json` for teamlead); includes a compact `quota` object, with `available=false` and `reason` when the quota source is missing or stale.
- `quota status`: report Claude subscription quota windows, used %, reset time, reserve stop line, and source freshness (`--json`); best-effort and read-only.
- `quota refresh`: actively refresh `.ai-task/quota-snapshot.json` from configured headless live sources; no-op with a reason when no source is reachable.
- `quota setup-statusline`: print or check Claude Code statusLine wiring. Default output explains mode choice and recommends `--global`; `--global` prints a repo-agnostic dispatcher snippet, `--project` prints the repo-local helper snippet, and `--check` stays repo-scoped.
- `pause`, `stop`, `resume`: control active agents without losing run state.
- `note`: append user input to the run inbox and decide whether to interrupt, defer, or route to review.
- `review`: build review packet and `review-skills.json` from run diff; teamlead runs **ai-task-reviewer** in IDE/subagent (not a second headless `run`).
- `cleanup`: audit-only list of stale runs; optional `--remove-worktrees` after merge.
- `prune`: delete finished run dirs and state (`--yes`, `--older-than`, `--keep-last`, `--run-id`).
- `policy`: show or edit backend preference, fallback, batching, and review gates.
- `watch`: tail run logs; optional `--follow`.
- `self-test`: run built-in supervision pattern checks.
- `parallel-plan`: analyze batch for parallel waves (heuristics in `scripts/ai_task/scheduling.py` and `scripts/ai_task/decisions.py`).
- `decision log|result|reflect|analytics`: teamlead decision journal in `decisions.jsonl`.

`note` is stored in `inbox.jsonl` but is not auto-injected into a running CLI process.

## Improve from teamlead analytics

When the user asks to tune orchestration using real choices (not guesses):

1. Read `.ai-task/decisions.jsonl` in the target repo (or export path they give).
2. Run `ai-task decision analytics --since 30d --format md` (or `--json`) if CLI is available.
3. Count `bad` / `good` by `phase` and `choice` (especially `parallel`, `assign`, `verdict`).
4. Read `--reflection` on `bad` rows for recurring regrets.
5. Propose minimal changes: `[parallel]` policy, `parallel-plan` heuristics, verify profiles, or teamlead skill wording — not a new platform layer.
6. Ship changes with tests; document in `docs/ai-task-decisions.md` and CHANGELOG.

Do not auto-train on a single bad decision; look for patterns (≥3 similar bad outcomes).

For discovery beyond analytics — what to audit or harden next — consult the standing audit-question catalog in `docs/audit-questions.md` when the profile clone keeps one (open rows are unprobed health-check questions; update statuses when you file or execute one).

In this repo, the reusable CLI entrypoint is `scripts/ai-task.py`, with wrappers at `scripts/ai-task.sh`, `scripts/ai-task.ps1`, and `bin/ai-task`.

Code navigation: `scripts/ai-task.py` is a 27-line shim - sys.path bootstrap plus `from ai_task.cli import main`. Everything lives in the `scripts/ai_task/` package, and `ai_task` is the import surface (the facade re-exports every public name eagerly; there is no lazy fallback). Never import internals from the shim by path: that executes a second module object.

- `ai_task/backlog.py` - backlog parsing, DoR, provenance, rebuild invariants, risk gates
- `ai_task/backlog_store.py` - the file-per-task store tool: `split`, `regenerate`, `check`, `rotate`, `guard`; CLI shim `scripts/backlog-store.py`
- `ai_task/index_guard.py` - bundles the store modules into a consumer's TRACKED `scripts/backlog-index-guard.py`, plus its freshness check
- `ai_task/scheduling.py` - eligibility, execution order, wave packing, batch sizing
- `ai_task/runs.py` - launch, supervision, worktrees, phase timing, prune helpers
- `ai_task/quota.py` - quota windows, admission control, reservations, telemetry, calibration, and the Claude OAuth cluster (token load, usage fetch, refresh sources, `try_acquire_quota_reservation`)
- `ai_task/decisions.py` - decision journal read AND write path: `operator_identity` + its cache, `new_decision_entry`, auto-log triggers, `apply_ingest_stub`, `enforce_risk_confirm`, analytics core (scorecard/trend/recurrence), parallel-override audit
- `ai_task/analytics.py` - the `ai-task report` dashboard (networkx/numpy/plotly lazy; `scripts/analytics.py` is a thin shim)
- `ai_task/policy.py` - TOML read/render/merge, policy sync
- `ai_task/state.py` - state.json read AND write side: roots, JSON primitives, the cross-process `_state_lock` (fcntl/msvcrt) and `save_state`. Charter: imports nothing above `_shared`
- `ai_task/init.py` - init template, stack detection, bootstrap manifests, profile root, statusline paths
- `ai_task/verify.py` - verify profiles, pipefail runner, report writer
- `ai_task/notify.py` - Telegram finalize outcome ping: config gates, sender, message builder
- `ai_task/cli.py` - every command shell, `build_parser`, `main`
- `ai_task/lifecycle.py` - the layer ABOVE the primitives: routing and `backend_env`, leases, telemetry glue, finalize/reap and the finalize-time guards, `refresh_runs`, status snapshot builders, waiting-quota lifecycle
- `ai_task/review.py` - review registry, stack detection, conditional rows, review planning, changed paths, rework block
- `ai_task/codex_review.py` - the opt-in `codex exec review` pass of `ai-task review`: command from the `[backends.codex]` recipe with a read-only sandbox, diff target, findings block in `review-findings.md`
- `ai_task/claude_settings.py` - the settings canary of the headless Claude worker: `claude --settings <file> doctor` plus a key-name search in the binary, the `quota doctor` `settings` check and the launch refusal in `run`
- `ai_task/packets.py` - handoff config, task-report contract, inbox notes, packet text and `generate_packet`
- `ai_task/_shared.py` - tiny cross-domain primitives (`die`, `APP_DIR`, `app_path`, `now`, `pid_alive`)

The facade `ai_task/__init__.py` re-exports every public name (tests import `ai_task` through `tests/ai_task_loader.py`).

Test patch contract (since the split into modules): tests patch through `patch_ai_task(name, ...)` from `tests/ai_task_loader.py`, never `mock.patch.object(at, "<name>", ...)` and never `at.<name> = ...`. The helper resolves the module that owns a name (functions via `__module__`, data globals via the `_DATA_GLOBAL_OWNERS` registry in the loader), patches every namespace carrying it, and raises `PatchTargetNotFound` when it resolves nowhere. `set_ai_task_global` / `reset_ai_task_globals` are the unscoped counterparts for setUp/tearDown seams. Only stdlib singletons the CLI imports (`at.shutil`, `at.subprocess`, `at.sys`, `at.urlrequest`) stay on plain `mock.patch.object`.

Before moving a cluster OUT of the entrypoint, re-run the survey (AST-based, multiline-aware) and expect zero hits outside that stdlib list:

```bash
python3 - <<'PY'
import ast, pathlib
STDLIB = {"shutil", "subprocess", "sys", "urlrequest", "urlerror", "os", "time", "json"}
for p in sorted(pathlib.Path("tests").glob("*.py")):
    for node in ast.walk(ast.parse(p.read_text())):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Attribute) and getattr(t.value, "id", "") == "at":
                    print(f"{p}:{node.lineno} assign at.{t.attr}")
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "object" and node.args:
            a0 = node.args[0]
            if getattr(a0, "id", "") == "at" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                if node.args[1].value not in STDLIB:
                    print(f"{p}:{node.lineno} patch.object at.{node.args[1].value}")
PY
```

Then move the code verbatim and retarget the registry entry for any data global in the cluster, in the same commit. `patch_targets` patches every loaded `ai_task` module whose globals carry the name, so a sibling module that from-imported it is covered too. The fail-loud resolution catches a missed or stale retarget; it cannot catch a live-but-wrong one, so classify each patching test by the chain it exercises before retargeting a name that several chains read.

## Runtime Router Policy

Default backend policy:

1. **`Agent: auto`:** preserve explicit choices, then infer the teamlead's vendor when `routing.default_source = "host"`. New policies enable this mode; existing policies keep their routing on sync. Claude uses `sonnet`, high effort and print mode. Native Codex uses `codex exec`, its configured model and effort, stdin packets, JSONL logs and a final-message file.
2. **`Agent: cursor` or `--backend cursor_codex`:** opt-in Codex (`gpt-5.3-codex-high`). Draws Cursor API pool; monthly billing reset, not short probe recovery.
3. On Claude limit, cooldown per `[cooldown] default_seconds`; probe before reuse when cooldown expires.
4. **Cursor backends** (`cursor_codex`, `cursor_auto`): sticky cooldown until `cooldown clear --force` (no timer auto-clear).
5. Native Codex is enabled in new policies. Keep its workspace-write sandbox and noninteractive approval refusal separate from Claude permissions. Codex never uses Claude quota reservations or reset times; report unavailable telemetry and use its own limit/cooldown signals. Preserve old Agent: codex Cursor aliases during policy sync.
6. In-session backends `claude_subagent` and `codex_subagent` have `in_session = true` and no command. `run` records the run and launches nothing; `worker-done` finalizes it through `finalize_detached_run`. Keep them out of auto routing and fallback orders, keep `run --wait` refused, keep pid-less in-session runs out of the orphan reaper and lease pruning, and keep `[executor]` values local on sync.
7. Fallback is disabled by default. A wave pin suppresses substitution; the teamlead resolves it once with `pin auto` or an explicit backend. Apply the configured risk gate before a permitted fallback.

Treat backend limits as recoverable state, not task failure. Record the limit signal, cooldown when known, selected fallback, and whether user approval was needed.
Detached runs can only fall back before launch when a backend command is unavailable. Waited runs should also scan output for limit patterns and try the next backend in policy order.

When changing policy fields, update `default_policy()` in `scripts/ai_task/policy.py` and the adoption instructions together. The template wins for `POLICY_TEMPLATE_SCALAR_PATHS` and Claude args. Routing orders and disabled-backend lists are kept whole as recipes; `routing.default_source` and the `[executor]` keys in `POLICY_LOCAL_CHOICE_PATHS` stay local even with `--force`. Older policies gain policy mode and an explicit legacy Codex alias on sync. Pattern lists append missing entries. Include new limit phrases in `LIMIT_WORDS` / `DEFAULT_LIMIT_PATTERNS`. Register nested sections in `POLICY_NESTED_TABLE_SECTIONS` so rendering preserves their tables.

## Claude quota policy

Maintainer scope owns the `[quota]` policy block and the whole quota source layer in `scripts/ai_task/quota.py` - snapshot parsing, freshness, `quota_status`, the OAuth fetch cluster and headless `quota refresh` (all moved off the entrypoint). The `quota setup-statusline` wiring and the `quota status` shell stay in the entrypoint until the cli.py slice.

- **Policy ownership.** `[quota]` defaults live in `default_policy()`: `enabled`, `reserve_percentage`, `near_limit_start_threshold_percentage`, `resume_margin_seconds`, `max_snapshot_age_seconds`, `refresh_enabled`, `refresh_on_dispatch`, `refresh_timeout_seconds`, `refresh_sources`, `snapshot_path`, and `[quota.reservations]` (`s/m/l/unknown_percentage`). Document operator-facing meaning in `docs/ai-task.md`, not just code comments.
- **Policy sync rules.** All `[quota]` scalars are **local-wins** (operators tune reserve/threshold/reservations per repo); `policy sync` only *adds missing* keys and never overwrites a local value. Do **not** add quota keys to `POLICY_TEMPLATE_SCALAR_PATHS` unless a value must be force-upgraded across all repos. Nested `[quota.reservations]` merges key-by-key like any sub-table.
- **Best-effort contract.** Quota is inert without a fresh source after refresh: never make delivery depend on it. A missing/stale/disabled/unreachable source must degrade to existing limit-pattern + `[cooldown]` behavior, and `status` must report quota `unavailable` rather than failing.
- **Boundary — runtime routing, not a second brain.** Quota supervision *sources snapshots, reserves a budget, reports a stop line, and (in later tasks) waits for reset*. It must not estimate task cost by reasoning about the work, plan the backlog, or grow into an autonomous scheduler. Reservation percentages are pessimistic **estimates**, not cost prediction. Keep the intelligence in the vendor CLIs; `ai-task` only routes. Never invoke a nonconfigured external service or credential-backed source (for example `claude_oauth` / `ccquota`) from a status read.
- **Global settings must stay repo-agnostic.** Do not print repo-specific absolute helper paths for global settings. Use the dispatcher pattern (`scripts/ai-task-quota-statusline-dispatch.py` on PATH) for global `statusLine`, and keep `--project` explicitly repo-local with `--repo`.

## Task Packet

Each packet should include:

- Task id, title, priority, size, dependencies, and selected backend policy.
- Task context and DoD copied from `BACKLOG.md`.
- Scope boundaries, relevant files, and forbidden areas.
- Required skills and project rules to load.
- Verification expectations and review gates.
- Instructions to update only the assigned task status, related docs, and task artifacts.

## Review Gates

Trigger review when any of these are true:

- Public contracts, schemas, protocols, migrations, auth, security, or data boundaries change.
- The diff is broad, touches tests heavily, or changes shared infrastructure.
- The task is high priority.
- The implementing agent reports uncertainty, skipped checks, or residual risk.
- The user asks for review.

Reviewers should receive the task packet, diff, verification output, and user notes, not the entire backlog by default.

## Initialization

If `.ai-task` is missing and the user asks to set it up, load `ai-task-init`, then hand off routine operations to `ai-task-teamlead`. If the user does not want `.ai-task` in a repo, continue using ordinary `BACKLOG.md`, `AGENTS.md`, shared skills, and commands without changes.

## User operations (delegate)

| User intent | Skill |
|-------------|-------|
| Run backlog, status, batch, notes, review ops | `ai-task-teamlead` |
| Change `scripts/ai-task.py`, policy defaults, ADR scope | This skill |
| One-time `.ai-task` scaffold | `ai-task-init` |
