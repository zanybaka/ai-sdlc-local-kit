"""Run-lifecycle layer for the ai-task CLI.

The layer ABOVE the extracted primitives: everything that drives a run from
routing through supervision to finalize, and the status snapshot that reports
on it.

- routing: backend recovery probes, cooldown refresh, `choose_backend_order`,
  `build_routing_info`, `routing_task_for_status`, `backend_env`
- leases: `acquire_task_lease` / `release_task_lease`
- telemetry glue: `telemetry_diffstat_summary`, `record_quota_telemetry`
- finalize, reap and the guards that run at finalize: policy baseline,
  sensitive-file watch, main-tree cleanliness, scope guard and its ack,
  `reap_orphaned_run`, `finalize_detached_run`, `refresh_runs`
- status snapshot builders: operator alerts, quota summary, `status_summary`,
  `backlog_summary`, `backends_health`, `refresh_status_state`,
  `build_status_snapshot`
- the waiting-quota lifecycle: `mark_run_waiting_quota`,
  `rearm_waiting_quota_run`, `resume_quota_run`

Why a new module rather than runs.py or quota.py: these clusters call into
runs, quota, decisions AND notify. `decisions` already imports `runs`, and
finalize calls both `maybe_auto_log_anomaly` and `notify_run_outcome`, so
hosting them in either sibling closes an import cycle. This module sits above
all of them and nothing in the package imports it - only the entrypoint (and,
after the cli.py slice, `cli`).

Imports: `_shared`, `backlog`, `decisions`, `notify`, `packets`, `policy`,
`quota`, `review`, `runs`, `scheduling`, `state`, `verify`.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from ai_task._shared import (
    APP_DIR,
    die,
    now,
    pid_alive,
)
from ai_task.backlog import Task, archived_done_ids, parse_backlog, risk_gates
from ai_task.claude_settings import claude_settings_launch_block
from ai_task.decisions import (
    POLICY_DRIFT_CHOICE,
    SCOPE_ACK_CHOICE,
    _policy_drift_already_logged,
    maybe_auto_log_anomaly,
    operator_identity,
    scope_ack_logged,
)
from ai_task.notify import _notify_suppress_implement_for_root, notify_run_outcome
from ai_task.quota import (
    QUOTA_TELEMETRY_DIFFSTAT_MAX_CHARS,
    _apply_resume_margin,
    _redact_abs_paths,
    active_quota_reservations,
    append_quota_telemetry_sample,
    backend_model_info,
    build_quota_telemetry_sample,
    compact_quota_status,
    is_quota_gated_backend,
    parse_limit_reset_after,
    prune_stale_quota_reservations,
    quota_enabled,
    quota_refresh,
    quota_refresh_at_finalize,
    quota_refresh_enabled,
    quota_reservations_view,
    quota_resume_after_from_status,
    quota_resume_margin_seconds,
    quota_resume_max_attempts,
    quota_resume_wait_cap_exceeded,
    quota_status,
    quota_status_warnings,
    quota_telemetry_summary,
    release_quota_reservation,
    reservation_decision,
    resume_after_is_due,
    telemetry_quota_snapshot,
)
from ai_task.runs import (
    CURSOR_COOLDOWN_BACKENDS,
    ORPHAN_PIDLESS_GRACE_SECONDS,
    POLICY_BASELINE_FILE,
    SCOPE_GUARD_MAX_EDITS,
    SCOPE_SNAPSHOT_DIR,
    SENSITIVE_EDITS_CHOICE,
    TEAMLEAD_MARKERS,
    WORKER_OUTCOMES,
    WORKER_REPORT_SCHEMA,
    _waiting_quota_task,
    agent_preferred_backends,
    append_run_log_note,
    apply_supervision,
    auth_failure_reason,
    backend_auth_fix,
    backend_available,
    backend_command,
    backend_cooled_down,
    backend_credential_dead,
    backend_input,
    backlog_out_of_scope_edits,
    build_resume_receipt,
    clear_backend_cooldown,
    clear_backend_credentials,
    collect_git_diff_summary,
    cooldown_active,
    cooldown_config,
    default_backend_order,
    detect_auth_failure,
    detect_limit,
    in_session_timeout_seconds,
    is_git_repository,
    is_in_session_backend,
    main_tree_tracked_dirty,
    mark_backend_credential_dead,
    policy_baseline_hashes,
    primary_backend_names,
    quota_resume_attempts_used,
    read_detached_exit_status,
    read_policy_baseline,
    read_run_logs,
    resolve_run_cwd,
    run_age_seconds,
    run_attempt_capturing_pid,
    run_elapsed_seconds,
    scope_guard_enabled,
    scope_guard_mode,
    sensitive_file_edits_between,
    sensitive_file_hashes,
    set_backend_cooldown,
    supervision_config,
    wait_subprocess_with_supervision,
    write_policy_baseline,
)
from ai_task.scheduling import (
    blocked_by_dependencies,
    dependency_cycles,
    eligible_tasks,
    prune_stale_leases,
)
from ai_task.state import repo_root, save_state


def acquire_task_lease(
    state: dict[str, Any], task_id: str, run_id: str, backend: str
) -> None:
    state.setdefault("leases", {})[task_id] = {
        "run_id": run_id,
        "backend": backend,
        "operator": operator_identity(),
        "created_at": now(),
    }


def release_task_lease(state: dict[str, Any], task_id: str) -> None:
    state.get("leases", {}).pop(task_id, None)


def probe_backend_recovery(
    root: Path, state: dict[str, Any], policy: dict[str, Any], name: str
) -> bool:
    cfg = cooldown_config(policy)
    if not cfg.get("probe_enabled", True):
        clear_backend_cooldown(state, name)
        return True
    backend = policy.get("backends", {}).get(name, {})
    if not backend.get("enabled", False) or not backend_available(backend):
        return False
    probe_prompt = str(backend.get("probe_prompt", "Reply with exactly OK."))
    command = backend_command(backend, probe_prompt)
    timeout = int(cfg.get("probe_timeout_seconds", 90) or 90)
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=backend_env(backend, root=root),
        )
    except subprocess.TimeoutExpired:
        set_backend_cooldown(
            state, name, policy, "probe timed out", from_active_attempt=True
        )
        return False
    log_text = (completed.stdout or "") + (completed.stderr or "")
    if detect_limit(log_text, backend):
        set_backend_cooldown(
            state, name, policy, "probe still rate-limited", from_active_attempt=True
        )
        return False
    if completed.returncode != 0 and detect_auth_failure(log_text, backend):
        # The cooldown probe is off the dispatch hot path, so it is a free place
        # to learn that the backend is credential-dead.
        mark_backend_credential_dead(
            state, name, backend, auth_failure_reason(name, backend, log_text)
        )
        set_backend_cooldown(
            state, name, policy, "probe: not authenticated", from_active_attempt=True
        )
        return False
    if completed.returncode == 0:
        clear_backend_cooldown(state, name)
        clear_backend_credentials(state, name)
        return True
    set_backend_cooldown(
        state,
        name,
        policy,
        f"probe exit {completed.returncode}",
        from_active_attempt=True,
    )
    return False


def refresh_cooldowns(
    root: Path, state: dict[str, Any], policy: dict[str, Any]
) -> None:
    cooldowns = state.setdefault("backend_cooldowns", {})
    for name, info in list(cooldowns.items()):
        if cooldown_active(info):
            continue
        if name == "claude":
            probe_backend_recovery(root, state, policy, name)
        elif name in CURSOR_COOLDOWN_BACKENDS:
            continue
        else:
            clear_backend_cooldown(state, name)


def telemetry_diffstat_summary(root: Path, cwd: Path) -> dict[str, Any]:
    """Cheap redacted changed-file/diffstat summary for a sample.

    Best-effort: any failure degrades to ``available: False`` rather than raising.
    Paths are redacted and the body is capped — this is a summary, not a transcript.
    """
    try:
        raw = collect_git_diff_summary(cwd)
    except (OSError, ValueError):
        return {"available": False, "reason": "diffstat unavailable"}
    if not raw or raw == "(no diff)":
        return {"available": True, "changed_files": 0, "diffstat": ""}
    redacted = _redact_abs_paths(raw, root)
    truncated = len(redacted) > QUOTA_TELEMETRY_DIFFSTAT_MAX_CHARS
    body = redacted[:QUOTA_TELEMETRY_DIFFSTAT_MAX_CHARS]
    # Count files changed from the git --stat lines (cheap, no content).
    changed_files = sum(
        1 for line in raw.splitlines() if "|" in line and "=>" not in line
    )
    summary: dict[str, Any] = {
        "available": True,
        "changed_files": changed_files,
        "diffstat": body,
    }
    if truncated:
        summary["truncated"] = True
    return summary


def record_quota_telemetry(
    *,
    root: Path,
    policy: dict[str, Any],
    run: dict[str, Any],
    task: Task,
    backend: str,
    backend_config: dict[str, Any],
    pre_quota: dict[str, Any] | None,
    exit_status: str,
    limited: bool = False,
    stalled: bool = False,
    blocked_reason: str | None = None,
    sample_kind: str = "single",
    run_cwd: Path | None = None,
    capture_post: bool = True,
    capture_diffstat: bool = True,
) -> bool:
    """High-level best-effort telemetry recorder for a finished/launched Claude run.

    Captures the post-launch quota snapshot and (cheaply) a redacted diffstat, then
    appends one sample. Wrapped so any failure is swallowed — telemetry is additive
    and must never fail a run. Only Claude (quota-gated) backends are sampled.
    """
    try:
        if not quota_enabled(policy):
            return False
        if not is_quota_gated_backend(backend, policy):
            return False
        post_quota: dict[str, Any] | None = None
        if capture_post:
            post_quota = telemetry_quota_snapshot(quota_status(root, policy))
        diffstat: dict[str, Any] | None = None
        if capture_diffstat:
            cwd = run_cwd if run_cwd is not None else resolve_run_cwd(root, run)
            diffstat = telemetry_diffstat_summary(root, cwd)
        elapsed = run_elapsed_seconds(run)
        attempts = len(run.get("attempts", []) or [])
        sample = build_quota_telemetry_sample(
            root=root,
            run_id=str(run.get("id", "")),
            task=task,
            backend=backend,
            backend_config=backend_config,
            reservation_percentage=run.get("quota_required"),
            quota_reserved=bool(run.get("quota_reserved")),
            pre_quota=pre_quota,
            post_quota=post_quota,
            elapsed_seconds=elapsed,
            exit_status=exit_status,
            exit_code=run.get("exit_code"),
            limited=limited,
            stalled=stalled,
            blocked_reason=blocked_reason,
            attempts=attempts,
            sample_kind=sample_kind,
            diffstat=diffstat,
        )
        return append_quota_telemetry_sample(root, policy, sample)
    except Exception:  # pragma: no cover - telemetry is strictly best-effort.
        return False


def choose_backend_order(
    task: Task,
    policy: dict[str, Any],
    requested: str,
    state: dict[str, Any],
    root: Path,
    *,
    confirm_risk: bool = False,
    for_run: bool = True,
) -> list[str]:
    routing = policy.get("routing", {})
    backends = policy.get("backends", {})
    disabled = set(routing.get("disabled_backends", []))
    # Wave-level backend pin: `ai-task pin <name>` stores the
    # teamlead's explicit backend choice in state; it overrides per-task Agent:
    # metadata for every run/plan until `pin --clear`. A conflicting explicit
    # --backend is a hard error, never a silent override. The pin never replaces
    # the owner-only gate: an Agent: human task still refuses to run.
    pinned = str(state.get("pinned_backend") or "")
    if requested != "auto":
        if pinned and requested != pinned:
            die(
                f"backend pinned to '{pinned}' for this wave; "
                f"--backend {requested} conflicts — clear the pin with "
                "`ai-task pin --clear` or pin that backend instead"
            )
        base = [requested]
    else:
        preferred = agent_preferred_backends(task, policy)
        if preferred is not None and not preferred:
            # Owner-only (Agent: human): the run path must refuse (no backend can
            # deliver it), but read/planning callers (status routing preview, plan
            # batch) pass for_run=False and get an empty backend order so they skip
            # or render the task instead of hard-failing the run-only guard on a
            # non-run command.
            if not for_run:
                return []
            die(
                f"task {task.id} has Agent: human — complete work manually; "
                "do not use ai-task run"
            )
        if pinned:
            base = [pinned]
        elif preferred:
            base = preferred
        else:
            base, _ = default_backend_order(task, policy)

    refresh_cooldowns(root, state, policy)
    cooldowns = state.get("backend_cooldowns", {})
    # A pinned wave never substitutes another vendor: a cooled-down
    # or credential-dead pin means wait/fail, not fallback.
    # An in-session executor is an explicit owner choice: a cooled
    # down subagent waits like a pin, it never opens a headless fallback.
    in_session_base = any(is_in_session_backend(backends.get(name, {})) for name in base)
    limit_fallback = (
        []
        if pinned or in_session_base
        else list(routing.get("limit_fallback_order", ["cursor_auto"]))
    )
    # Credential-dead backends are dropped from AUTO routing only:
    # a backend that cannot authenticate can never succeed, so keeping it in the
    # chain burns dispatches. An explicit `--backend NAME` still routes to it —
    # that is how an operator who just ran `agent login` proves it works again
    # (a clean attempt clears the mark), so the memory cannot deadlock itself.
    skip_credential_dead = requested == "auto"

    def credential_dead(name: str) -> bool:
        return skip_credential_dead and backend_credential_dead(state, name) is not None

    order: list[str] = []
    for name in base:
        if name in disabled or not backends.get(name, {}).get("enabled", False):
            continue
        if name in cooldowns and backend_cooled_down(name, cooldowns[name]):
            continue
        if credential_dead(name):
            continue
        order.append(name)

    # A primary that is cooled down OR credential-dead opens the fallback chain:
    # both mean "this backend cannot take the work right now", and
    # a credential-dead primary with no fallback appended would strand the task.
    if any(
        (name in cooldowns and backend_cooled_down(name, cooldowns[name]))
        or credential_dead(name)
        for name in base
        if name not in disabled and backends.get(name, {}).get("enabled", False)
    ):
        for name in limit_fallback:
            if name in disabled or not backends.get(name, {}).get("enabled", False):
                continue
            if name in cooldowns and backend_cooled_down(name, cooldowns[name]):
                continue
            if credential_dead(name):
                continue
            if (
                name == "cursor_auto"
                and policy.get("review", {}).get(
                    "ask_before_weaker_fallback_for_risky_tasks", True
                )
                and risk_gates(task, policy)
                and not confirm_risk
            ):
                continue
            if name not in order:
                order.append(name)

    return order


def build_routing_info(
    task: Task,
    policy: dict[str, Any],
    state: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    routing = policy.get("routing", {})
    backends = policy.get("backends", {})
    cooldowns = state.get("backend_cooldowns", {})
    disabled = set(routing.get("disabled_backends", []))
    # A wave pin replaces the task's normal primary chain and leaves
    # no fallback candidates — status should show exactly what a run would do.
    pinned = str(state.get("pinned_backend") or "")
    primaries = [pinned] if pinned else primary_backend_names(task, policy)
    primary_cooled_down = any(
        name in cooldowns and backend_cooled_down(name, cooldowns[name])
        for name in primaries
    )
    # Status routing preview is a read path: never hard-fail on an owner-only
    # (Agent: human) task — for_run=False yields an empty backend order.
    available_backends = choose_backend_order(
        task, policy, "auto", state, root, confirm_risk=False, for_run=False
    )
    available_with_confirm = choose_backend_order(
        task, policy, "auto", state, root, confirm_risk=True, for_run=False
    )
    fallback_candidates = (
        []
        if pinned
        else [
            name
            for name in routing.get("limit_fallback_order", ["cursor_auto"])
            if name not in disabled and backends.get(name, {}).get("enabled", False)
        ]
    )
    fallback_blocked_reason = "none"
    if primary_cooled_down and fallback_candidates:
        fallbacks_available = [
            name for name in fallback_candidates if name in available_backends
        ]
        fallbacks_with_confirm = [
            name for name in fallback_candidates if name in available_with_confirm
        ]
        if not fallbacks_available and fallbacks_with_confirm:
            fallback_blocked_reason = "confirm_risk_required"
        elif not fallbacks_available and not fallbacks_with_confirm:
            if all(
                name in cooldowns and backend_cooled_down(name, cooldowns[name])
                for name in fallback_candidates
            ):
                fallback_blocked_reason = "cooldown"
            else:
                fallback_blocked_reason = "disabled"
    earliest_ready_at: str | None = None
    for name in primaries + fallback_candidates:
        info = cooldowns.get(name)
        if not info or not backend_cooled_down(name, info):
            continue
        until = str(info.get("cooldown_until", ""))
        if until and (earliest_ready_at is None or until < earliest_ready_at):
            earliest_ready_at = until
    # Quota admission-control routing fields. Explain whether a
    # Claude-backed launch for this task would reserve quota, the pessimistic
    # required percent, the dual-window available budget, and why it is blocked.
    quota_primary = any(is_quota_gated_backend(name, policy) for name in primaries)
    quota_required: float | None = None
    quota_available: float | None = None
    quota_blocked_reason: str | None = None
    quota_reserved = False
    if quota_primary and quota_enabled(policy):
        decision = reservation_decision(task, policy, quota_status(root, policy), state)
        quota_required = decision["required"]
        quota_available = decision["available"]
        # available=None => no fresh source; admission control is inert (not blocked).
        if decision["available"] is not None:
            quota_reserved = decision["fits"]
            quota_blocked_reason = decision["blocked_reason"]
    return {
        "task_id": task.id,
        "selection_reason": (
            "wave pin" if pinned else "task Agent" if agent_preferred_backends(task, policy)
            is not None else default_backend_order(task, policy)[1]
        ),
        "quota_telemetry": (
            "Claude pool" if quota_primary else "unavailable: no configured quota source for this backend"
        ),
        "pinned_backend": pinned or None,
        "available_backends": available_backends,
        "primary_cooled_down": primary_cooled_down,
        "fallback_candidates": fallback_candidates,
        "fallback_blocked_reason": fallback_blocked_reason,
        "earliest_ready_at": earliest_ready_at,
        "quota_reserved": quota_reserved,
        "quota_required": quota_required,
        "quota_available": quota_available,
        "quota_blocked_reason": quota_blocked_reason,
    }


def routing_task_for_status(
    tasks: list[Task],
    state: dict[str, Any],
    policy: dict[str, Any],
    task_id: str | None,
    *,
    extra_done_ids: set[str] | None = None,
) -> Task | None:
    if task_id:
        matches = [task for task in tasks if task.id == task_id and task.is_open]
        return matches[0] if matches else None
    # Auto-selected routing preview shows what a headless runner would dispatch next,
    # so skip owner-only (Agent: human) tasks: resolve next-eligible past a pinned or
    # top-priority human task instead of surfacing one that cannot be run (and that the
    # run-only guard would then hard-fail on for status/wait-runs).
    eligible = eligible_tasks(
        tasks, state, policy, autonomous=True, extra_done_ids=extra_done_ids
    )
    return eligible[0] if eligible else None


def backend_env(backend: dict[str, Any], root: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    command = Path(str(backend.get("command", ""))).name
    if command in {"claude", "codex"}:
        # Independent workers must not inherit another session's identity or
        # Claude's nested-session guard. The selected executor remains explicit.
        for marker in (*TEAMLEAD_MARKERS, "CODEX_INTERNAL_ORIGINATOR_OVERRIDE"):
            env.pop(marker, None)
        env["AI_TASK_WORKER_BACKEND"] = command
    extra = backend.get("env", {})
    if isinstance(extra, dict):
        for key, value in extra.items():
            env[str(key)] = str(value)
    # Devin-CLI quirk: a Devin/Windsurf agent session exports
    # ACP_BACKEND so spawned agent CLIs route through the session's ACP backend.
    # A nested `devin -p` then authenticates against that backend instead of the
    # user's credentials and dies "Not logged in" even though `devin auth status`
    # passes in a plain shell. A dispatched headless devin is an independent run,
    # so the inherited session marker must not leak into it.
    if str(backend.get("command", "")) == "devin":
        env.pop("ACP_BACKEND", None)
    # Level B: when the operator opted to receive ONLY ai-task's
    # finalize outcome ping (`[notify] implement_ping = false`), tell the headless
    # child's Stop hook to stand down so the run is not double-pinged. Default
    # keeps the per-task implement-done ping — best-effort, never blocks launch.
    # Key the decision off the RUN's repo (passed in) — NOT Path.cwd(), which
    # under the documented `--repo <target>` teamlead workflow is a different repo
    # (often the profile checkout with no .ai-task), so the target's setting would
    # be silently ignored.
    try:
        target = root if root is not None else repo_root(Path.cwd())
        if _notify_suppress_implement_for_root(target):
            env.setdefault("AI_TASK_SUPPRESS_STOP_PING", "1")
    except Exception:  # noqa: S110 - an unreadable target policy leaves the ping at its default.
        pass
    return env


def check_policy_baseline(
    root: Path,
    policy: dict[str, Any],
    *,
    phase: str,
    state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Warn (never block) when policy/config drifted since the last sync.

    Missing baseline: record one now with
    a one-time notice instead of a warning storm. Returns the drift edit list
    ([] when clean) so callers/tests can inspect it.
    """
    baseline = read_policy_baseline(root)
    if baseline is None:
        write_policy_baseline(root)
        print(
            f"policy baseline recorded: {APP_DIR}/{POLICY_BASELINE_FILE} "
            "(integrity check for .ai-task config/policy files; "
            "`ai-task policy sync` re-baselines after reviewed edits)",
            file=sys.stderr,
        )
        return []
    drift = sensitive_file_edits_between(baseline, policy_baseline_hashes(root))
    if not drift:
        return []
    names = ", ".join(str(edit["path"]) for edit in drift)
    print(
        f"warning: policy changed since last sync — review {names}, then run "
        "`ai-task policy sync` to re-baseline (these files are config-as-code: "
        "verify commands, backend argv, quota refresh sources)",
        file=sys.stderr,
    )
    if not _policy_drift_already_logged(root, drift):
        maybe_auto_log_anomaly(
            root,
            policy,
            phase=phase,
            choice=POLICY_DRIFT_CHOICE,
            task_ids=[],
            run_ids=[],
            state=state,
            signals={
                "count": len(drift),
                "files": [str(edit["path"]) for edit in drift],
                "file_kinds": [str(edit["kind"]) for edit in drift],
            },
            reason=(
                f"{len(drift)} policy/config file(s) drifted from the "
                f"{POLICY_BASELINE_FILE} baseline outside a tracked run"
            ),
        )
    return drift


def _apply_sensitive_guard_at_finalize(
    root: Path,
    policy: dict[str, Any],
    state: dict[str, Any] | None,
    run: dict[str, Any],
    guard: dict[str, Any],
    run_cwd: Path,
    task_id: str,
) -> None:
    """Flag agent-authored edits to sensitive control files.

    Sets run["sensitive_file_edits"] ([] when clean) by re-hashing the watched
    files against the launch manifest, and auto-logs a `sensitive_file_edits`
    decision row when edits are found. Informational in both modes — does not
    gate merge-back.
    """
    pre_hashes = guard.get("sensitive")
    if not isinstance(pre_hashes, dict):
        return  # launched before the sensitive watch existed
    edits = sensitive_file_edits_between(pre_hashes, sensitive_file_hashes(run_cwd))
    run["sensitive_file_edits"] = edits
    if not edits:
        return
    maybe_auto_log_anomaly(
        root,
        policy,
        phase="delivery",
        choice=SENSITIVE_EDITS_CHOICE,
        task_ids=[task_id] if task_id else [],
        run_ids=[str(run.get("id"))] if run.get("id") else [],
        state=state,
        signals={
            "count": len(edits),
            "files": [str(edit["path"]) for edit in edits],
            "kinds": sorted({str(edit["kind"]) for edit in edits}),
        },
        reason=(
            f"run finalize found {len(edits)} edit(s) to sensitive control files "
            "(.gitmodules / .ai-task config or policies) outside "
            f"{task_id or 'the task'}'s scope"
        ),
    )


def enforce_main_tree_clean_at_finalize(
    root: Path,
    state: dict[str, Any] | None,
    policy: dict[str, Any] | None,
    run: dict[str, Any],
    *,
    fatal: bool,
) -> None:
    """Fail a worktree-isolated run that left NEW tracked edits on MAIN.

    During a worktree-isolated headless run, file tools sometimes resolve to the
    MAIN checkout so edits land on `main` while Bash works in the worktree.
    Pinning the harness file-tool cwd is out of scope for this Python CLI, so
    finalize diffs `git status --porcelain` on the main root against the
    launch-time baseline (`main_tree_pre_dirty`, captured at run start): any
    tracked-dirty path present now but not at launch is a leak. On a leak the run
    records `main_tree_leak` and auto-logs a `main_tree_leak` anomaly; with
    `fatal` the supervised complete path then `die()`s. Only applies to runs that
    executed in a worktree; non-worktree runs return early, so single-tree
    workflows are never affected.
    """
    rel = str(run.get("worktree_path", "") or "")
    if not rel:
        return
    if not is_git_repository(root):
        return
    baseline = set(run.get("main_tree_pre_dirty") or [])
    leaked = sorted(main_tree_tracked_dirty(root) - baseline)
    if not leaked:
        return
    run["main_tree_leak"] = leaked
    task_id = str(run.get("task_id", "") or "")
    if policy:
        try:
            maybe_auto_log_anomaly(
                root,
                policy,
                phase="delivery",
                choice="main_tree_leak",
                task_ids=[task_id] if task_id else [],
                run_ids=[str(run.get("id"))] if run.get("id") else [],
                state=state,
                signals={"files": leaked, "count": len(leaked)},
                reason="worktree-isolated run left tracked edits on the MAIN checkout",
            )
        except Exception:  # pragma: no cover  # noqa: S110 - anomaly logging must not break finalize
            pass
    if fatal:
        if state is not None:
            save_state(root, state)
        die(
            f"main-checkout leak: run {run.get('id')} is worktree-isolated ({rel}) "
            f"but left {len(leaked)} tracked file(s) modified on the MAIN working "
            f"tree: {', '.join(leaked)}. Revert them on main and re-run in the "
            "worktree."
        )


def apply_scope_guard_at_finalize(
    root: Path,
    policy: dict[str, Any] | None,
    state: dict[str, Any] | None,
    run: dict[str, Any],
) -> None:
    """Diff configured task files against the pre-run snapshot.

    Sets run["out_of_scope_edits"] ([] when clean) and auto-logs an
    `out_of_scope_edits` decision row when edits are found; also re-checks the
    sensitive control-file hashes. Best-effort: any failure
    leaves the run record untouched and never blocks finalize.
    """
    if not policy or not scope_guard_enabled(policy):
        return
    guard = run.get("scope_guard")
    if not isinstance(guard, dict):
        return  # launched before the guard existed, or a dry run
    try:
        run_cwd = resolve_run_cwd(root, run)
        task_id = str(run.get("task_id", "") or "")
        _apply_sensitive_guard_at_finalize(
            root, policy, state, run, guard, run_cwd, task_id
        )
        files = [str(item) for item in guard.get("files", []) if str(item).strip()]
        if not files:
            run["out_of_scope_edits"] = []
            return
        pre_dir = root / str(run.get("run_dir", "")) / SCOPE_SNAPSHOT_DIR
        edits: list[dict[str, Any]] = []
        for rel in files:
            pre_path = pre_dir / rel
            post_path = run_cwd / rel
            pre_text = (
                pre_path.read_text(encoding="utf-8", errors="replace")
                if pre_path.is_file()
                else ""
            )
            if pre_text and not post_path.is_file():
                edits.append(
                    {
                        "path": rel,
                        "kind": "file_removed",
                        "detail": "configured task file deleted during the run",
                    }
                )
                continue
            post_text = (
                post_path.read_text(encoding="utf-8", errors="replace")
                if post_path.is_file()
                else ""
            )
            edits.extend(
                backlog_out_of_scope_edits(pre_text, post_text, task_id, path=rel)
            )
        total = len(edits)
        if total > SCOPE_GUARD_MAX_EDITS:
            edits = edits[:SCOPE_GUARD_MAX_EDITS]
            edits.append(
                {
                    "path": "",
                    "kind": "truncated",
                    "detail": f"+{total - SCOPE_GUARD_MAX_EDITS} more out-of-scope edits",
                }
            )
        run["out_of_scope_edits"] = edits
        if not edits:
            return
        files_hit = sorted({str(e.get("path")) for e in edits if e.get("path")})
        kinds = sorted({str(e.get("kind")) for e in edits})
        maybe_auto_log_anomaly(
            root,
            policy,
            phase="delivery",
            choice="out_of_scope_edits",
            task_ids=[task_id] if task_id else [],
            run_ids=[str(run.get("id"))] if run.get("id") else [],
            state=state,
            signals={"count": total, "files": files_hit, "kinds": kinds},
            reason=(
                f"run finalize found {total} backlog edit(s) outside "
                f"{task_id or 'the task'}'s own task block"
            ),
        )
    except Exception:  # pragma: no cover - guard must never break finalize
        return


def enforce_scope_guard_ack(
    root: Path,
    policy: dict[str, Any],
    run: dict[str, Any],
    run_id: str,
    *,
    action: str,
) -> None:
    """Block merge-back actions until out-of-scope edits are acknowledged.

    Active only with [scope_guard] mode = "require_ack": when the run carries
    out_of_scope_edits and no scope_ack decision row references it, die with the
    exact acknowledgment command. Warn mode never blocks.
    """
    if scope_guard_mode(policy) != "require_ack":
        return
    edits = run.get("out_of_scope_edits") or []
    if not edits or scope_ack_logged(root, run_id):
        return
    task_id = str(run.get("task_id", "") or "")
    die(
        f"{action} blocked: run {run_id} carries {len(edits)} out-of-scope backlog "
        f"edit(s) outside {task_id or 'the task'}'s own task block and "
        '[scope_guard] mode = "require_ack". Inspect out_of_scope_edits in '
        "`ai-task status --json`, then revert the edits or acknowledge them: "
        f"ai-task decision log --phase verdict --choice {SCOPE_ACK_CHOICE} "
        f"--task-ids {task_id or '<TASK-ID>'} --run-ids {run_id} "
        '--reason "<why the edits stay>"'
    )


def reap_orphaned_run(
    root: Path,
    state: dict[str, Any],
    run: dict[str, Any],
    note: str,
    policy: dict[str, Any] | None = None,
) -> None:
    """Mark a run whose backend/supervisor is gone as recoverable.

    The run is surfaced as ``needs_recovery`` (not silently left ``running`` and
    not silently ``failed``) so the teamlead can re-run deterministically, with a
    summary of any uncommitted changes left behind in the run's working tree.
    """
    run["status"] = "needs_recovery"
    run["finished_at"] = now()
    run["exit_code"] = "unknown"
    run["status_note"] = note
    # Detached runs finalize through this reaper (their exit is only observed
    # here), so the scope guard evaluates the backlog diff now.
    apply_scope_guard_at_finalize(root, policy, state, run)
    # Main-checkout leak guard, record-only here: the reaper runs
    # inside the shared refresh_runs sweep that almost every status/wait-runs call
    # triggers, so a die() would brick the CLI; and long detached runs invite
    # concurrent operator edits to main that would false-positive. Recording the
    # leak + auto-logged anomaly still surfaces it loudly in status.
    enforce_main_tree_clean_at_finalize(root, state, policy, run, fatal=False)
    try:
        run["uncommitted_changes"] = collect_git_diff_summary(
            resolve_run_cwd(root, run)
        )
    except OSError:
        run["uncommitted_changes"] = "(unavailable)"
    # Quota telemetry: the reaper is the only point at which a detached
    # run's completion is observed, so it takes the "after" quota snapshot now and
    # finalizes the run's cost sample. The launch (line) wrote a partial sample with
    # pre-quota only; this writes the authoritative completion sample carrying pre
    # (stored on the record at launch) + post (taken now), so a detached wave yields
    # high-confidence deltas without foreground mode. Degrades honestly: if no fresh
    # quota source exists at finalize, the completion sample stays partial with the
    # reason (record_quota_telemetry never fabricates a snapshot).
    record_detached_finalize_telemetry(root, policy, run, exit_status="needs_recovery")
    release_task_lease(state, str(run.get("task_id", "")))
    release_quota_reservation(state, str(run.get("id", "")))
    # Terminal-without-verdict: a reaped run never reaches `verdict`,
    # so this is its only outcome ping. notify_run_outcome dedupes via
    # run_record["outcome_notified"]; the reaper's caller persists `state`.
    notify_run_outcome(root, state, run)


def refresh_quota_source_at_finalize(root: Path, policy: dict[str, Any]) -> str:
    """Refresh a stale quota source before a detached run's post snapshot.

    Gated on `[quota] refresh_at_finalize` (default off) so an operator opts in
    to one live-source call per finished run. It cannot block work: the run is
    already over. Returns a short reason string for the caller's telemetry
    breadcrumbs; never raises.
    """
    if not quota_refresh_at_finalize(policy):
        return "disabled"
    if not quota_refresh_enabled(policy):
        return "refresh_disabled"
    try:
        if quota_status(root, policy).get("available"):
            return "fresh"
        result = quota_refresh(root, policy)
        return "refreshed" if result.get("ok") else "refresh_failed"
    except Exception:  # pragma: no cover - strictly best-effort.
        return "refresh_failed"


def record_detached_finalize_telemetry(
    root: Path,
    policy: dict[str, Any] | None,
    run: dict[str, Any],
    *,
    exit_status: str,
) -> bool:
    """Write a detached run's completion telemetry sample at finalize.

    Honest degradation: ``record_quota_telemetry`` takes the post snapshot via the
    live quota source, so when that source is unavailable at finalize (stale/missing
    or a usage-endpoint 429) the completion sample stays ``partial`` with the reason
    carried by ``post_quota`` — never fabricated. Best-effort throughout: returns
    False (and writes nothing) when telemetry is off, the backend is not quota-gated,
    the run carries no stored pre snapshot (legacy or foreground run), or any step
    fails. The reader prefers this completion sample over the earlier
    ``launched`` line per ``run_id``.
    """
    if policy is None:
        return False
    pre_quota = run.get("telemetry_pre_quota")
    if not isinstance(pre_quota, dict):
        # No pre snapshot stored at launch → this is a legacy/foreground run, not a
        # detached launch we can finalize into a high-confidence delta. Skip rather
        # than emit a useless post-only sample.
        return False
    refresh_quota_source_at_finalize(root, policy)
    task = Task(
        id=str(run.get("task_id", "")),
        title=str(run.get("task_title", "")),
        status=" ",
        phase="",
        index=0,
        block="",
        priority="",
        size=str(run.get("telemetry_size") or run.get("size") or ""),
        depends_on=(),
        agent="",
    )
    backend = str(run.get("backend", ""))
    backend_config = (policy.get("backends", {}) or {}).get(backend, {})
    sample_kind = str(run.get("telemetry_sample_kind") or "single")
    return record_quota_telemetry(
        root=root,
        policy=policy,
        run=run,
        task=task,
        backend=backend,
        backend_config=backend_config,
        pre_quota=pre_quota,
        exit_status=exit_status,
        sample_kind=sample_kind,
        capture_post=True,
    )


def parse_worker_report(text: str) -> tuple[dict[str, str] | None, str]:
    """The worker-done report in a final message, or None and the reason."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"final message is not JSON: {exc.msg}"
    if not isinstance(data, dict):
        return None, "final message is not a JSON object"
    expected = set(WORKER_REPORT_SCHEMA["required"])
    if set(data) != expected:
        return None, f"final message keys {sorted(data)} instead of {sorted(expected)}"
    if not all(isinstance(data[key], str) for key in expected):
        return None, "final message fields must be strings"
    if data["outcome"] not in WORKER_OUTCOMES:
        return None, f"unknown outcome {data['outcome']!r}"
    return {key: data[key] for key in sorted(expected)}, ""


def apply_worker_report(
    root: Path,
    state: dict[str, Any],
    run: dict[str, Any],
    backend_name: str,
    backend_config: dict[str, Any],
    policy: dict[str, Any] | None,
) -> None:
    """Read a clean headless worker's schema report into the run.

    Only for a backend with ``output_schema_arg``. A valid report leaves its raw
    JSON in final.json and its final_answer in final.md, so review reads the
    same Markdown as before. A reported failure makes the run ``failed``; a
    reported limit is believed only when the log carries a limit text, because a
    real Codex usage limit ends the process with an error, not a clean exit. An
    invalid report is recorded and warned about, and the run keeps its exit-code
    status: the work in the worktree may still be good.
    """
    if not backend_config.get("output_schema_arg") or not run.get("final_message"):
        return
    final_path = root / str(run["final_message"])
    try:
        text = final_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        run["worker_report"] = {"valid": False, "error": "no final message written"}
        return
    report, error = parse_worker_report(text)
    if report is None:
        run["worker_report"] = {"valid": False, "error": error}
        run["status_note"] = (
            f"{run.get('status_note') or 'finished'}; worker report invalid: {error}"
        )
        return
    final_path.with_suffix(".json").write_text(text, encoding="utf-8")
    final_path.write_text(report["final_answer"], encoding="utf-8")
    run["worker_report"] = {"valid": True, "outcome": report["outcome"], "note": report["note"]}
    detail = f": {report['note']}" if report["note"] else ""
    if report["outcome"] == "failure":
        run["status"] = "failed"
        run["status_note"] = f"worker reported failure{detail}"
    elif report["outcome"] == "limited":
        if detect_limit(read_run_logs(run, root), backend_config):
            if policy is not None:
                set_backend_cooldown(
                    state, backend_name, policy, "usage limit reported by worker",
                    str(run.get("id", "")), from_active_attempt=True,
                )
            run["status"] = "quota_blocked"
            run["status_note"] = (
                f"worker reported a usage limit{detail}; backend cooldown active. "
                "No task failure consumed."
            )
        else:
            run["status"] = "failed"
            run["status_note"] = (
                f"worker reported a usage limit{detail}, but the log has no limit "
                "text; treated as failure"
            )


def finalize_detached_run(
    root: Path,
    state: dict[str, Any],
    run: dict[str, Any],
    exit_code: int,
    policy: dict[str, Any] | None = None,
    *,
    note: str | None = None,
    limited: bool | None = None,
) -> None:
    """Finalize a detached run from its exit-status sidecar.

    Mirrors the --wait terminal path: a clean exit (0) becomes ``needs_review``
    (proceeds to verify/verdict), a nonzero exit becomes ``failed`` — both carry
    the real ``exit_code`` instead of the reaper's ``unknown``. Runs the same
    finalize bookkeeping as reap_orphaned_run (scope guard, main-tree leak guard,
    git-diff summary, completion telemetry, lease/reservation release, outcome
    ping) so no lease or quota hold leaks and telemetry stays consistent.

    Credential-dead exception: a detached attempt that died because
    its backend is unauthenticated did zero work and is not the task's fault, so
    it finalizes as ``backend_unusable`` — not ``failed`` — and remembers the
    backend as credential-dead, which routes the next auto dispatch past it. A
    detached run cannot fall through in-process (it has already returned); the
    fall-through happens at the next dispatch instead.

    An in-session run finalizes here from `worker-done`: the
    caller passes the reported ``limited`` outcome and its own ``note``, because
    there is no log for the pattern checks to read.
    """
    backend_name = str(run.get("backend", "") or "")
    backend_config = (policy or {}).get("backends", {}).get(backend_name, {})
    credential_dead = False
    log_text = ""
    if limited is None:
        limited = False
        if exit_code != 0 and backend_name:
            log_text = read_run_logs(run, root)
            credential_dead = detect_auth_failure(log_text, backend_config)
            limited = detect_limit(log_text, backend_config)
    if limited and policy is not None:
        set_backend_cooldown(
            state, backend_name, policy, "limit detected at detached completion",
            str(run.get("id", "")), from_active_attempt=True,
        )
    if credential_dead:
        reason = auth_failure_reason(backend_name, backend_config, log_text)
        mark_backend_credential_dead(
            state, backend_name, backend_config, reason, str(run.get("id", ""))
        )
        run["status"] = "backend_unusable"
        run["backend_unusable_reason"] = reason
        run["status_note"] = (
            f"backend-unusable: {reason}; not failed work — no task attempt was "
            "consumed. Fix credentials, or re-run to route to the next backend."
        )
    elif limited and run.get("in_session"):
        run["status"] = "quota_blocked"
        run["status_note"] = note or (
            "in-session worker hit a usage limit; backend cooldown active. Wait for "
            "the window or explicitly choose another executor. No task failure consumed."
        )
    elif limited and Path(str(backend_config.get("command", ""))).name == "codex":
        run["status"] = "quota_blocked"
        run["status_note"] = (
            "Codex usage limit; backend cooldown active. Wait for Codex availability "
            "or explicitly choose another backend. No task failure consumed."
        )
    else:
        run["status"] = "needs_review" if exit_code == 0 else "failed"
        run["status_note"] = note or (
            f"detached run exited {exit_code}; finalized from exit-status sidecar"
        )
        if exit_code == 0 and not run.get("in_session"):
            apply_worker_report(root, state, run, backend_name, backend_config, policy)
    if exit_code == 0 and backend_name:
        # A clean attempt proves the credentials work again.
        clear_backend_credentials(state, backend_name)
    run["finished_at"] = now()
    run["exit_code"] = exit_code
    apply_scope_guard_at_finalize(root, policy, state, run)
    enforce_main_tree_clean_at_finalize(root, state, policy, run, fatal=False)
    try:
        run["uncommitted_changes"] = collect_git_diff_summary(resolve_run_cwd(root, run))
    except OSError:
        run["uncommitted_changes"] = "(unavailable)"
    record_detached_finalize_telemetry(root, policy, run, exit_status=run["status"])
    release_task_lease(state, str(run.get("task_id", "")))
    release_quota_reservation(state, str(run.get("id", "")))
    notify_run_outcome(root, state, run)


def refresh_runs(
    root: Path, state: dict[str, Any], policy: dict[str, Any] | None = None
) -> None:
    backends = policy.get("backends", {}) if policy else {}
    for run in state.get("runs", {}).values():
        if run.get("status") not in {"running", "paused"}:
            continue
        if run.get("in_session"):
            # No process to watch: the teamlead's subagent reports through
            # worker-done. Only the timeout ends a run nobody completes.
            timeout = in_session_timeout_seconds(policy)
            age = run_age_seconds(run)
            if timeout and age is not None and age >= timeout:
                reap_orphaned_run(
                    root,
                    state,
                    run,
                    f"in-session worker did not report within {timeout}s; record "
                    "its outcome with `ai-task worker-done` or re-run",
                    policy,
                )
            continue
        pid = run.get("pid")
        if not isinstance(pid, int):
            # No backend pid recorded. A genuinely in-flight run captures its pid
            # within milliseconds of going "running"; a pid-less run older than the
            # grace window means the supervising --wait process died before/at
            # launch and left an orphan — reap it instead of leaving it stuck.
            age = run_age_seconds(run)
            if age is not None and age >= ORPHAN_PIDLESS_GRACE_SECONDS:
                reap_orphaned_run(
                    root,
                    state,
                    run,
                    "orphaned: run is running with no live backend pid "
                    "(supervisor likely killed); recover or re-run",
                    policy,
                )
            continue
        try:
            os.kill(pid, 0)
            if policy:
                apply_supervision(run, root, policy, backends)
        except OSError:
            # The backend pid is gone. Prefer the detached exit-status sidecar:
            # if it holds a real exit code, finalize to needs_review
            # (0) / failed (nonzero) instead of the blanket needs_recovery/unknown.
            # Only a genuine kill/crash with no readable sidecar falls back to the
            # reaper.
            exit_code = read_detached_exit_status(root, run)
            if exit_code is not None:
                finalize_detached_run(root, state, run, exit_code, policy)
            else:
                reap_orphaned_run(
                    root,
                    state,
                    run,
                    "process exited; exact exit code unavailable for detached run — "
                    "recover or re-run",
                    policy,
                )


def print_operator_alerts(snapshot: dict[str, Any]) -> bool:
    """Human summary for limit/cooldown before the run list."""
    lines: list[str] = []
    # Credential-dead backends first: the chain is known-broken
    # before a limit forces the fallback onto a backend that can never work.
    for name, info in snapshot.get("backend_credentials", {}).items():
        lines.append(
            f"- backend unusable {name}: {info.get('reason')} — auto routing skips "
            f"it until fixed ({info.get('fix')}); not failed work"
        )
    for name, info in snapshot.get("backend_cooldowns", {}).items():
        if info.get("active"):
            lines.append(
                f"- cooldown {name}: {info.get('reason')} until {info.get('cooldown_until')}"
            )
    for run in snapshot.get("runs", []):
        if run.get("status") not in {"running", "paused"}:
            continue
        if "limit" in run.get("signals", []):
            lines.append(
                f"- limit on run {run.get('id')} ({run.get('task_id')}): wait or switch backend"
            )
    for run in snapshot.get("runs", []):
        scope_edits = run.get("out_of_scope_edits") or []
        if scope_edits and run.get("status") != "done":
            lines.append(
                f"- out-of-scope backlog edits on run {run.get('id')} "
                f"({run.get('task_id')}): {len(scope_edits)} edit(s) outside the "
                "task's own block — review before merge-back"
            )
        sensitive_edits = run.get("sensitive_file_edits") or []
        if sensitive_edits and run.get("status") != "done":
            lines.append(
                f"- sensitive control-file edits on run {run.get('id')} "
                f"({run.get('task_id')}): {len(sensitive_edits)} file(s) "
                "(.gitmodules / .ai-task config or policies) — review before "
                "merge-back"
            )
    pinned = snapshot.get("pinned_backend")
    if pinned:
        lines.append(
            f"- backend pinned for this wave: {pinned} "
            "(no fallback; `ai-task pin --clear` releases it)"
        )
    routing = snapshot.get("routing")
    if isinstance(routing, dict) and routing.get("primary_cooled_down"):
        reason = str(routing.get("fallback_blocked_reason", "none"))
        fallbacks = routing.get("fallback_candidates") or []
        fallback_label = ", ".join(fallbacks) if fallbacks else "fallback"
        if reason == "confirm_risk_required":
            lines.append(
                f"- fallback blocked: confirm-risk required for {fallback_label} "
                f"(task {routing.get('task_id')})"
            )
        elif reason == "cooldown":
            lines.append(f"- fallback {fallback_label} in cooldown")
        elif reason == "disabled":
            lines.append(f"- fallback {fallback_label} disabled or unavailable")
        elif fallbacks:
            available = [
                name
                for name in fallbacks
                if name in (routing.get("available_backends") or [])
            ]
            if available:
                lines.append(f"- fallback available: {', '.join(available)}")
    if isinstance(routing, dict) and routing.get("quota_blocked_reason"):
        lines.append(
            f"- Claude quota-blocked (task {routing.get('task_id')}): required "
            f"{routing.get('quota_required')}% > available "
            f"{routing.get('quota_available')}% "
            f"({routing.get('quota_blocked_reason')}); not failed work — wait, "
            "raise budget, or allow fallback"
        )
    if not lines:
        return False
    print("Operator alerts:")
    for line in lines:
        print(line)
    print()
    return True


def print_quota_status_summary(root: Path, policy: dict[str, Any]) -> bool:
    """Plain-status quota line: warn when blind, near, or over threshold.

    Best-effort: prints nothing when quota is disabled.
    """
    if not quota_enabled(policy):
        return False
    status = quota_status(root, policy)
    warnings = quota_status_warnings(status)
    if not warnings:
        return False
    print("Quota alerts:")
    for line in warnings:
        print(line)
    print()
    return True


def status_summary(
    root: Path, state: dict[str, Any], policy: dict[str, Any], tasks: list[Task]
) -> dict[str, Any]:
    refresh_runs(root, state, policy)
    runs = list(state.get("runs", {}).values())
    running = 0
    in_session_waiting = 0
    for run in runs:
        if run.get("status") not in {"running", "paused"}:
            continue
        if run.get("in_session"):
            running += 1
            in_session_waiting += 1
        elif pid_alive(run.get("pid")) is True:
            running += 1
    failed = sum(1 for run in runs if run.get("status") == "failed")
    needs_review = sum(1 for run in runs if run.get("status") == "needs_review")
    needs_recovery = sum(1 for run in runs if run.get("status") == "needs_recovery")
    # Counted separately from failed_total on purpose: these runs did
    # no work and did not fail — they need an operator to authenticate a backend.
    backend_unusable = sum(
        1 for run in runs if run.get("status") == "backend_unusable"
    )
    prune_stale_leases(state)
    prune_stale_quota_reservations(state)
    leased = list(state.get("leases", {}).keys())
    return {
        "active_runs": running,
        "running_count": running,
        "failed_total": failed,
        "needs_review_count": needs_review,
        "needs_recovery_count": needs_recovery,
        "backend_unusable_count": backend_unusable,
        "awaiting_in_session_count": in_session_waiting,
        "leased_task_ids": leased,
        "quota_reserved_task_ids": [
            str(reservation.get("task_id", ""))
            for reservation in active_quota_reservations(state)
        ],
        "blocked_by_deps": blocked_by_dependencies(
            tasks, state, extra_done_ids=archived_done_ids(root)
        ),
    }


def backlog_summary(
    root: Path, state: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    tasks = parse_backlog(root)
    open_ids = [task.id for task in tasks if task.is_open]
    deferred_ids = [task.id for task in tasks if task.status == "~"]
    done_ids = [task.id for task in tasks if task.status == "x"]
    eligible = eligible_tasks(
        tasks, state, policy, extra_done_ids=archived_done_ids(root)
    )
    next_task = eligible[0] if eligible else None
    return {
        "counts": {
            "open": len(open_ids),
            "deferred": len(deferred_ids),
            "done": len(done_ids),
        },
        "open_ids": open_ids,
        "deferred_ids": deferred_ids,
        "done_ids": done_ids,
        "next_eligible": (
            {
                "id": next_task.id,
                "title": next_task.title,
                "priority": next_task.priority,
                "size": next_task.size,
                "depends_on": list(next_task.depends_on),
            }
            if next_task
            else None
        ),
    }


def backends_health(
    policy: dict[str, Any], state: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Per-backend health rows.
    """
    rows: list[dict[str, Any]] = []
    for name, backend in policy.get("backends", {}).items():
        enabled = bool(backend.get("enabled", False))
        available = backend_available(backend)
        credential = (
            backend_credential_dead(state, name) if state is not None else None
        )
        reason: str | None = None
        if not enabled:
            reason = "disabled in policy"
        elif not available:
            reason = f"command not found on PATH: {backend.get('command', '')}"
        elif credential is not None:
            reason = str(credential.get("reason") or "credential failure")
        rows.append(
            {
                "name": name,
                "enabled": enabled,
                "available": available,
                "usable": enabled and available and credential is None,
                "unusable_reason": reason,
                "credential_dead": credential is not None,
                "fix": (
                    str(credential.get("fix") or backend_auth_fix(backend))
                    if credential is not None
                    else None
                ),
                "command": str(backend.get("command", "")),
            }
        )
    return rows


def refresh_status_state(
    root: Path, state: dict[str, Any], policy: dict[str, Any]
) -> None:
    backends = policy.get("backends", {})
    refresh_runs(root, state, policy)
    refresh_cooldowns(root, state, policy)
    for run in state.get("runs", {}).values():
        if run.get("status") not in {"running", "paused"}:
            continue
        if run.get("in_session"):
            # No logs or pid to supervise; the timeout in refresh_runs is the
            # only stall rule for these runs.
            continue
        analysis = apply_supervision(run, root, policy, backends)
        if "limit" in analysis.get("signals", []):
            set_backend_cooldown(
                state,
                str(run.get("backend", "")),
                policy,
                "limit detected in logs",
                str(run.get("id")),
                from_active_attempt=True,
            )


def build_status_snapshot(
    root: Path,
    policy: dict[str, Any],
    state: dict[str, Any],
    *,
    task_id: str | None = None,
) -> dict[str, Any]:
    tasks = parse_backlog(root)
    refresh_status_state(root, state, policy)
    summary = status_summary(root, state, policy, tasks)
    runs_out: list[dict[str, Any]] = []
    for run in sorted(
        state.get("runs", {}).values(), key=lambda item: str(item.get("created_at", ""))
    ):
        supervision = run.get("supervision", {})
        run_status = run.get("status")
        idle_seconds = (
            supervision.get("idle_seconds")
            if run_status in {"running", "paused"}
            else None
        )
        runs_out.append(
            {
                "id": run.get("id"),
                "task_id": run.get("task_id"),
                "task_title": run.get("task_title"),
                "status": run_status,
                "backend": run.get("backend"),
                "model": run.get("model"),
                "effort": run.get("effort"),
                # In-session runs: where model and effort came from
                # (transcript, reported or requested) and a gap to the request.
                "model_source": run.get("model_source"),
                "requested_model": run.get("requested_model"),
                "requested_effort": run.get("requested_effort"),
                "model_mismatch": run.get("model_mismatch"),
                "pid": run.get("pid"),
                "pid_alive": pid_alive(run.get("pid")),
                "exit_code": run.get("exit_code"),
                "signals": list(supervision.get("signals", [])),
                "idle_seconds": idle_seconds,
                "status_note": run.get("status_note"),
                "resume_after": run.get("resume_after"),
                "quota_window": run.get("quota_window"),
                "resume_attempts": run.get("resume_attempts"),
                "resume_attempts_remaining": run.get("resume_attempts_remaining"),
                "created_at": run.get("created_at"),
                "finished_at": run.get("finished_at"),
                "review_gates": list(run.get("review_gates", [])),
                "review_skills_status": run.get("review_skills_status"),
                "worktree_path": run.get("worktree_path"),
                "worktree_branch": run.get("worktree_branch"),
                "verdict": run.get("verdict"),
                "verdict_at": run.get("verdict_at"),
                "verify_status": run.get("verify_status"),
                "uncommitted_changes": run.get("uncommitted_changes"),
                "out_of_scope_edits": run.get("out_of_scope_edits"),
                "sensitive_file_edits": run.get("sensitive_file_edits"),
                "backend_unusable_reason": run.get("backend_unusable_reason"),
            }
        )
    cooldowns_out: dict[str, Any] = {}
    for name, info in state.get("backend_cooldowns", {}).items():
        cooldowns_out[name] = {
            "reason": info.get("reason"),
            "cooldown_until": info.get("cooldown_until"),
            "active": backend_cooled_down(name, info),
            "sticky": name in CURSOR_COOLDOWN_BACKENDS,
        }
    credentials_out = {
        name: dict(info)
        for name, info in state.get("backend_credentials", {}).items()
        if isinstance(info, dict) and info.get("status") == "credential_dead"
    }
    leases_out = {
        task_id: dict(info) for task_id, info in state.get("leases", {}).items()
    }
    # Active quota reservations are visible admission-control state;
    # prune any whose run has finished/stopped before exposing them.
    prune_stale_quota_reservations(state)
    reservations_out = quota_reservations_view(state)
    routing_out: dict[str, Any] | None = None
    routing_task = routing_task_for_status(
        tasks, state, policy, task_id, extra_done_ids=archived_done_ids(root)
    )
    if routing_task is not None:
        routing_out = build_routing_info(routing_task, policy, state, root)
    snapshot_out: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": now(),
        "repo_root": str(root),
        "last_batch": list(state.get("last_batch", [])),
        "dependency_cycles": dependency_cycles(tasks),
        "summary": summary,
        "backlog": backlog_summary(root, state, policy),
        "runs": runs_out,
        "backend_cooldowns": cooldowns_out,
        "backend_credentials": credentials_out,
        "backends": backends_health(policy, state),
        "pinned_backend": str(state.get("pinned_backend") or "") or None,
        "review_queue": list(state.get("review_queue", [])),
        "leases": leases_out,
        "quota_reservations": reservations_out,
        "routing": routing_out,
    }
    # Always include the compact quota object so operators can see quota-blind mode
    # (`available=false` + reason) before launching Claude-heavy waves.
    snapshot_out["quota"] = compact_quota_status(quota_status(root, policy))
    # Recent quota telemetry count + last-sample time so an operator
    # can see whether calibration data is accumulating. Always present (best-effort,
    # available=False until the first sample is written).
    snapshot_out["quota_telemetry"] = quota_telemetry_summary(root, policy)
    return snapshot_out


def mark_run_waiting_quota(
    root: Path,
    state: dict[str, Any],
    policy: dict[str, Any],
    run: dict[str, Any],
    task: Task,
    *,
    reason: str,
    resume_after: str | None,
    quota_window: str | None,
    status_note: str,
) -> None:
    """Move a quota/limit-blocked run into the recoverable ``waiting_quota`` state.

    Records ``resume_after`` / ``quota_window`` / a clear ``status_note`` and writes
    a resume receipt. The task lease is *retained* so a later --resume-on-quota
    re-launch reuses it without acquiring a duplicate lease; the worktree is kept
    (never removed here) so the same packet runs in the same tree. Any held quota
    reservation is released — the budget is freed while the run waits for reset.
    """
    run["status"] = "waiting_quota"
    run["finished_at"] = now()
    # First quota pause starts the resume_max_wait_seconds wall clock.
    if not run.get("first_paused_at"):
        run["first_paused_at"] = run["finished_at"]
    run["resume_after"] = resume_after
    run["quota_window"] = quota_window
    run["status_note"] = status_note
    attempts_used = quota_resume_attempts_used(run)
    attempts_remaining = max(0, quota_resume_max_attempts(policy) - attempts_used)
    try:
        diff_summary = collect_git_diff_summary(resolve_run_cwd(root, run))
    except OSError:
        diff_summary = "(unavailable)"
    files_changed = bool(diff_summary) and diff_summary != "(no diff)"
    receipt = build_resume_receipt(
        run,
        task,
        reason=reason,
        resume_after=resume_after,
        quota_window=quota_window,
        attempts_remaining=attempts_remaining,
        files_changed=files_changed,
        diff_summary=diff_summary,
    )
    run.setdefault("resume_receipts", []).append(receipt)
    run["resume_attempts_remaining"] = attempts_remaining
    # Free reserved budget while waiting; the lease stays so resume reuses it.
    release_quota_reservation(state, str(run.get("id", "")))
    append_run_log_note(
        root,
        run,
        "waiting_quota: "
        f"{reason}; resume_after={resume_after or 'unknown'} "
        f"window={quota_window or 'n/a'} attempts_remaining={attempts_remaining}",
    )


def rearm_waiting_quota_run(
    root: Path,
    state: dict[str, Any],
    policy: dict[str, Any],
    run: dict[str, Any],
    *,
    reason: str,
) -> None:
    """Push a waiting_quota run's resume time forward after a failed probe.

    Consumes one auto-resume attempt and recomputes ``resume_after`` from the
    backend cooldown the probe just set (or one resume-margin window). When the
    retry budget is exhausted the run stays waiting_quota but its receipt records
    that auto-resume stopped — it will not wake/retry again.
    """
    used = quota_resume_attempts_used(run) + 1
    run["resume_attempts"] = used
    remaining = max(0, quota_resume_max_attempts(policy) - used)
    run["resume_attempts_remaining"] = remaining
    cooldown_info = state.get("backend_cooldowns", {}).get("claude", {})
    next_resume = cooldown_info.get("cooldown_until")
    if not next_resume:
        next_resume = _apply_resume_margin(
            dt.datetime.now(dt.timezone.utc), quota_resume_margin_seconds(policy)
        )
    run["resume_after"] = next_resume
    if remaining <= 0:
        run["status_note"] = (
            f"waiting_quota: {reason}; auto-resume budget exhausted after {used} "
            "attempt(s) — left waiting for operator (raise resume_max_attempts, "
            "wait, or allow a non-Claude fallback)"
        )
    else:
        run["status_note"] = (
            f"waiting_quota: {reason}; re-armed, next auto-resume after "
            f"{next_resume} ({remaining} attempt(s) remain)"
        )
    receipt = build_resume_receipt(
        run,
        _waiting_quota_task(state, run),
        reason=reason,
        resume_after=run["resume_after"],
        quota_window=run.get("quota_window"),
        attempts_remaining=remaining,
        files_changed=False,
        diff_summary="(probe failed; no new attempt launched)",
    )
    run.setdefault("resume_receipts", []).append(receipt)
    append_run_log_note(root, run, run["status_note"])


def resume_quota_run(
    root: Path,
    state: dict[str, Any],
    policy: dict[str, Any],
    run: dict[str, Any],
) -> str:
    """Attempt to auto-resume one waiting_quota run after its window reset.

    Reuses the SAME packet and worktree and the SAME task lease (no new run id,
    worktree, or lease). First re-derives the resume time from a fresh quota
    snapshot — a still-blocked window re-arms WITHOUT consuming budget, bounded
    by the resume_max_wait_seconds wall clock. Then probes Claude
    recovery; on a failed probe the run is re-armed (consuming one attempt,
    budget permitting) and stays waiting_quota. On a recovered probe it
    re-launches Claude once on the existing packet — a clean exit moves the run to
    needs_review (lease + reservation released); a fresh limit re-arms or exhausts
    the budget. Returns a short outcome label for logging/JSON.
    """
    run_id = str(run.get("id", ""))
    if run.get("in_session"):
        # Resuming would launch a headless worker on the packet, the token path
        # the in-session executor exists to avoid.
        run["status_note"] = (
            "waiting_quota: in-session run is never auto-resumed; re-run it with an "
            "in-session backend after the window resets"
        )
        return "in_session_not_resumed"
    if quota_resume_attempts_used(run) >= quota_resume_max_attempts(policy):
        run["status_note"] = (
            "waiting_quota: auto-resume budget exhausted — left waiting for operator"
        )
        return "budget_exhausted"
    # Re-derive the resume time from a fresh snapshot BEFORE consuming a retry
    # attempt. A wake driven by one window's reset while a longer
    # window is still at/over stop (five_hour reset, seven_day still blocked) must
    # not burn the bounded budget on a probe that cannot succeed: re-arm
    # resume_after to the newly derived (latest) reset instead. Re-arming is
    # bounded by the resume_max_wait_seconds wall-clock cap measured from
    # first_paused_at; past the cap the budget is closed (attempts_remaining -> 0,
    # consistent with budget exhaustion so wait-runs stops waking this run) and
    # the run stays waiting_quota for the operator.
    fresh = quota_status(root, policy)
    if not fresh.get("available"):
        # The snapshot has usually gone stale during the wait; reuse the headless
        # refresh path before declaring quota state unknown (unknown → probe).
        quota_refresh(root, policy)
        fresh = quota_status(root, policy)
    derived_resume, derived_window = quota_resume_after_from_status(fresh, policy)
    if derived_resume is not None and not resume_after_is_due(derived_resume):
        if not run.get("first_paused_at"):
            run["first_paused_at"] = now()
        max_attempts = quota_resume_max_attempts(policy)
        if quota_resume_wait_cap_exceeded(run, policy):
            run["resume_attempts"] = max_attempts
            run["resume_attempts_remaining"] = 0
            run["status_note"] = (
                "waiting_quota: still quota-blocked past the resume_max_wait_seconds "
                f"cap (first paused {run.get('first_paused_at')}) — auto-resume "
                "stopped; left waiting for operator (raise resume_max_wait_seconds, "
                "wait, or allow a non-Claude fallback)"
            )
            append_run_log_note(root, run, run["status_note"])
            return "wait_cap_exceeded"
        run["resume_after"] = derived_resume
        run["quota_window"] = derived_window
        remaining = max(0, max_attempts - quota_resume_attempts_used(run))
        run["status_note"] = (
            f"waiting_quota: window {derived_window} still at/over stop on wake; "
            f"re-armed without consuming budget, next auto-resume after "
            f"{derived_resume} ({remaining} attempt(s) remain)"
        )
        receipt = build_resume_receipt(
            run,
            _waiting_quota_task(state, run),
            reason="window still at/over stop on wake",
            resume_after=derived_resume,
            quota_window=derived_window,
            attempts_remaining=remaining,
            files_changed=False,
            diff_summary="(still blocked on wake; no attempt launched)",
        )
        run.setdefault("resume_receipts", []).append(receipt)
        append_run_log_note(root, run, run["status_note"])
        return "rearmed_still_blocked"
    backends = policy.get("backends", {})
    claude_backend = backends.get("claude", {})
    if not claude_backend.get("enabled", False) or not backend_available(
        claude_backend
    ):
        rearm_waiting_quota_run(
            root, state, policy, run, reason="Claude backend unavailable on probe"
        )
        return "probe_failed"
    # Probe Claude recovery using the same cooldown probe path. A
    # successful probe clears any Claude cooldown; a failed probe sets one we reuse
    # to schedule the next wake.
    if not probe_backend_recovery(root, state, policy, "claude"):
        rearm_waiting_quota_run(
            root, state, policy, run, reason="Claude still limited on probe"
        )
        return "probe_failed"

    packet_rel = str(run.get("packet", "") or "")
    packet_path = root / packet_rel if packet_rel else None
    if packet_path is None or not packet_path.exists():
        run["status_note"] = "waiting_quota: original packet missing; cannot resume"
        return "packet_missing"
    prompt = packet_path.read_text(encoding="utf-8")
    # a CLI updated while the run waited may drop the settings JSON.
    blocked = claude_settings_launch_block(claude_backend, root)
    if blocked:
        run["status_note"] = f"waiting_quota: claude settings canary refused the resume: {blocked}"
        append_run_log_note(root, run, run["status_note"])
        return "settings_canary_failed"
    run_cwd = resolve_run_cwd(root, run)
    workspace = run_cwd if run.get("worktree_path") else None
    used = quota_resume_attempts_used(run) + 1
    run["resume_attempts"] = used
    run["status"] = "running"
    run["finished_at"] = None
    run["resume_attempts_remaining"] = max(0, quota_resume_max_attempts(policy) - used)
    append_run_log_note(
        root,
        run,
        f"resume attempt {used}: Claude recovered, re-launching same packet in "
        f"{run.get('worktree_path') or 'main working tree'}",
    )
    save_state(root, state)

    run_dir = root / str(run.get("run_dir", ""))
    run_dir.mkdir(parents=True, exist_ok=True)
    attempt_stdout = run_dir / f"resume-{used}-stdout.log"
    attempt_stderr = run_dir / f"resume-{used}-stderr.log"
    attempt_command = backend_command(claude_backend, prompt, workspace=workspace)
    sup = supervision_config(policy)
    stall_timeout = int(sup.get("stall_timeout_seconds", 0) or 0)
    auto_stop = bool(sup.get("auto_stop_on_stall", False))

    def capture_pid(pid: int) -> None:
        run["pid"] = pid
        save_state(root, state)

    if stall_timeout > 0:
        completed = wait_subprocess_with_supervision(
            attempt_command,
            cwd=run_cwd,
            prompt_input=backend_input(claude_backend, prompt),
            stdout_path=attempt_stdout,
            stderr_path=attempt_stderr,
            policy=policy,
            stall_timeout=stall_timeout,
            auto_stop=auto_stop,
            env=backend_env(claude_backend, root=root),
            on_start=capture_pid,
        )
    else:
        completed = run_attempt_capturing_pid(
            attempt_command,
            cwd=run_cwd,
            prompt_input=backend_input(claude_backend, prompt),
            stdout_path=attempt_stdout,
            stderr_path=attempt_stderr,
            env=backend_env(claude_backend, root=root),
            on_start=capture_pid,
        )
    log_text = ""
    for path in (attempt_stdout, attempt_stderr):
        log_text += path.read_text(encoding="utf-8", errors="replace")[-8000:]
    run.setdefault("attempts", []).append(
        {
            "backend": "claude",
            **backend_model_info(claude_backend),
            "command": attempt_command,
            "exit_code": completed.returncode,
            "limited": detect_limit(log_text, claude_backend),
            "stalled": completed.returncode == 124,
            "resumed": True,
            "stdout": str(attempt_stdout.relative_to(root)),
            "stderr": str(attempt_stderr.relative_to(root)),
            "finished_at": now(),
        }
    )
    if detect_limit(log_text, claude_backend):
        set_backend_cooldown(
            state,
            "claude",
            policy,
            "limit detected during quota resume",
            run_id,
            from_active_attempt=True,
        )
        run["status"] = "waiting_quota"
        run["finished_at"] = now()
        # Prefer a parsed reset hint from the new limit text, else cooldown timer.
        parsed = parse_limit_reset_after(log_text, policy)
        if parsed is not None:
            run["resume_after"] = parsed
        rearm_waiting_quota_run(
            root,
            state,
            policy,
            run,
            reason="Claude limited again after resume",
        )
        return "limited_again"
    run["backend"] = "claude"
    run.update(backend_model_info(claude_backend))
    run["command"] = attempt_command
    run["stdout"] = str(attempt_stdout.relative_to(root))
    run["stderr"] = str(attempt_stderr.relative_to(root))
    run["exit_code"] = completed.returncode
    run["finished_at"] = now()
    run["status"] = "needs_review" if completed.returncode == 0 else "failed"
    run["status_note"] = (
        f"resumed after quota wait on attempt {used}: "
        f"{'completed' if completed.returncode == 0 else 'failed'}"
    )
    # Out-of-scope backlog edit guard at finalize.
    apply_scope_guard_at_finalize(root, policy, state, run)
    # Main-checkout leak guard: hard-fail if this worktree-isolated run left NEW
    # tracked edits on the MAIN checkout.
    enforce_main_tree_clean_at_finalize(root, state, policy, run, fatal=True)
    release_task_lease(state, str(run.get("task_id", "")))
    release_quota_reservation(state, run_id)
    append_run_log_note(root, run, run["status_note"])
    return "resumed" if completed.returncode == 0 else "resume_failed"
