"""Command shells and argparse wiring for the ai-task CLI.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

# The ai-sdlc-local-kit checkout that hosts this package: scripts/ai_task/ -> parents[2].
# The entrypoint used Path(__file__).parent[.parent]; inside the package that
# is one level short.
PROFILE_ROOT = Path(__file__).resolve().parents[2]

from ai_task import backlog_store
from ai_task._shared import APP_DIR, app_path, die, now
from ai_task.backlog import (
    Task,
    archived_done_ids,
    collect_rebuild_invariant_reminders,
    dor_gaps_for_root,
    enforce_dor_gaps,
    format_rebuild_invariant_reminders,
    parse_backlog,
    print_dor_gaps,
    risk_gates,
)
from ai_task.claude_settings import claude_settings_canary, claude_settings_launch_block
from ai_task.codex_review import (
    codex_packet_section,
    codex_review_enabled,
    codex_review_line,
    run_codex_review_pass,
)
from ai_task.decisions import (
    SCENARIO_STALE_DAYS,
    VERDICT_VALUES,
    analyze_parallel_batch,
    append_decision,
    apply_ingest_stub,
    auto_log_credential_dead_fallback,
    auto_log_limit_fallback_switch,
    auto_log_run_start_anomalies,
    build_reflect_suggestions,
    check_bulk_scenario_confirmed,
    check_parallel_overrides,
    decision_analytics,
    decisions_path,
    detect_parallel_plan_override,
    enforce_risk_confirm,
    find_latest_delivery_scenario,
    format_value_trend_markdown,
    maybe_auto_log_anomaly,
    merge_parallel_override_signals,
    new_decision_entry,
    operator_identity,
    propose_decision_ingest_stubs,
    read_decisions,
    resolve_decision_run_ids,
    retro_journal_credibility_note,
    retro_packet_text,
    write_factual_decision_reports,
)
from ai_task.init import (
    INFRA_STACKS,
    OWNERSHIP_CHOICES,
    PROFILE_CONFIG_EXAMPLE,
    copy_bootstrap_docs,
    copy_bootstrap_scripts,
    decide_ownership,
    default_config,
    default_verify_profile_for_repo,
    detect_repo_stacks,
    ensure_app_dir_excluded,
    foreign_migration_notice,
    legacy_bootstrap_copies,
    missing_bootstrap_docs,
    missing_bootstrap_scripts,
    profile_config_path,
    quota_statusline_dispatcher_source_path,
    quota_statusline_helper_path,
    quota_statusline_project_settings_snippet,
    quota_statusline_shell_command,
    record_ownership,
    refresh_tracked_index_guard,
    stored_ownership,
)
from ai_task.lifecycle import (
    POLICY_BASELINE_FILE,
    acquire_task_lease,
    apply_scope_guard_at_finalize,
    apply_worker_report,
    backend_env,
    backends_health,
    build_status_snapshot,
    check_policy_baseline,
    choose_backend_order,
    enforce_main_tree_clean_at_finalize,
    enforce_scope_guard_ack,
    finalize_detached_run,
    mark_run_waiting_quota,
    print_operator_alerts,
    print_quota_status_summary,
    record_quota_telemetry,
    refresh_cooldowns,
    refresh_runs,
    release_task_lease,
    resume_quota_run,
    routing_task_for_status,
)
from ai_task.notify import notify_run_outcome
from ai_task.packets import (
    generate_packet,
    pending_inbox_notes,
    require_task_report,
    task_report_exists,
    task_report_relpath,
    warn_release_contract_gaps,
)
from ai_task.policy import (
    LIMIT_WORDS,
    bundled_template_policy,
    claude_permission_mode_report,
    collect_policy_drift,
    default_policy,
    load_toml,
    merge_policy_dicts,
    model_override_errors,
    print_policy_sync_report,
    read_config,
    read_policy,
    remove_worktree_on_complete,
    sync_model_overrides,
)
from ai_task.policy_edit import edit_policy_text, fallback_note
from ai_task.quota import (
    QUOTA_CALIBRATION_SIZE_ORDER,
    ClaudeOAuthUnauthorizedError,
    _ordered_windows,
    _quota_window_view,
    active_quota_reservations,
    aggregate_quota_calibration,
    apply_quota_calibration_patch,
    backend_model_info,
    claude_login_expiry,
    claude_login_expiry_line,
    compact_quota_status,
    fetch_claude_oauth_usage_json,
    in_session_model_request,
    is_quota_gated_backend,
    load_quota_snapshot,
    model_info_text,
    model_matches_request,
    other_active_quota_run,
    parse_claude_cli_version,
    parse_known_quota_usage_windows,
    parse_limit_reset_after,
    quota_available_budget,
    quota_calibration_patch,
    quota_enabled,
    quota_fallback_candidates,
    quota_max_snapshot_age_seconds,
    quota_near_limit_threshold,
    quota_refresh,
    quota_refresh_enabled,
    quota_refresh_on_dispatch,
    quota_refresh_sources,
    quota_reserve_percentage,
    quota_reserved_total,
    quota_resume_after_from_status,
    quota_resume_max_attempts,
    quota_status,
    quota_statusline_global_command,
    quota_statusline_global_settings_snippet,
    quota_telemetry_summary,
    read_quota_refresh_state,
    release_quota_reservation,
    reservation_decision,
    resume_after_is_due,
    subagent_transcript_model,
    subagent_transcript_path,
    telemetry_quota_snapshot,
    try_acquire_quota_reservation,
)
from ai_task.review import (
    collect_git_changed_paths,
    detect_stacks_from_paths,
    detect_stacks_from_task_context,
    find_review_findings_path,
    load_review_registry,
    resolve_review_skills,
    review_planning_for_task,
)
from ai_task.runs import (
    ACTIVE_WAIT_RUN_STATUSES,
    BLOCKED_WORDS,
    EXECUTOR_MODES,
    WORKER_OUTCOMES,
    analyze_supervision,
    apply_supervision,
    auth_failure_reason,
    backend_auth_fix,
    backend_available,
    backend_command,
    backend_credential_dead,
    backend_input,
    capture_scope_snapshot,
    clear_backend_cooldown,
    clear_backend_credentials,
    collect_git_diff_summary,
    collect_run_log_paths,
    default_backend_order,
    detect_auth_failure,
    detect_blocked,
    detect_limit,
    emit_wait_runs_json,
    executor_choice,
    find_run,
    format_run_activity_line,
    git_branch_exists,
    is_git_repository,
    is_in_session_backend,
    main_tree_tracked_dirty,
    mark_backend_credential_dead,
    parse_duration_spec,
    planned_worktree,
    policy_baseline_path,
    prepare_run_worktree,
    print_wait_run_rows,
    prune_old_cleanup_reports,
    quota_resume_attempts_used,
    record_phase_timing,
    release_run_worktree,
    remove_run_artifacts,
    resolve_run_cwd,
    run_attempt_capturing_pid,
    run_branch_name,
    select_prune_run_ids,
    set_backend_cooldown,
    supervision_config,
    teamlead_host,
    wait_run_rows,
    wait_subprocess_with_supervision,
    worktree_keep_reason,
    worktrees_enabled,
    write_policy_baseline,
)
from ai_task.scheduling import (
    autonomous_skip_reason,
    blocked_by_dependencies,
    eligible_tasks,
    format_owner_only_remaining,
    open_tasks_execution_order,
    resolve_wave_batch_size,
    task_lease_message,
    warn_dependency_cycles,
)
from ai_task.state import (
    default_state,
    load_state,
    require_initialized,
    save_state,
    selected_root,
    write_json,
)
from ai_task.verify import (
    resolve_verify_profile,
    run_verify_commands,
    verify_profile_commands,
    verify_settings,
    warn_nested_shell_pipes,
    write_verify_report,
)


def _ensure_analytics_deps() -> None:
    """Auto-install analytics deps on first use (plotly, networkx, numpy)."""
    import importlib.util

    missing = [
        pkg
        for pkg in ("plotly", "networkx", "numpy")
        if importlib.util.find_spec(pkg) is None
    ]
    if not missing:
        return

    req = (PROFILE_ROOT / "requirements-analytics.txt").resolve()
    print(f"Installing analytics dependencies ({', '.join(missing)})…")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req), "-q"],
        check=False,
    )
    if result.returncode != 0:
        sys.exit(
            f"Failed to install analytics dependencies.\nRun manually: pip install -r {req}"
        )


def report_cmd(args: argparse.Namespace) -> None:
    """Generate a rich HTML analytics report via analytics.py."""
    root = selected_root(args.repo)
    require_initialized(root)
    analytics_script = PROFILE_ROOT / "scripts" / "analytics.py"
    if not analytics_script.exists():
        sys.exit(f"analytics.py not found at {analytics_script}. Update ai-sdlc-local-kit.")
    since = getattr(args, "since", None)
    last = getattr(args, "last", None)
    if since and last is not None:
        sys.exit(
            "error: --since and --last are mutually exclusive. "
            "Use --since for a time window (e.g. 7d, 2026-05-20) "
            "or --last for the N most recent runs (e.g. --last 10)."
        )
    out = (
        Path(args.output).resolve()
        if getattr(args, "output", None)
        else (app_path(root) / "reports" / "report.html")
    )
    _ensure_analytics_deps()
    cmd = [
        sys.executable,
        str(analytics_script),
        "--repo",
        str(root),
        "--output",
        str(out),
    ]
    if since:
        cmd += ["--since", since]
    if last is not None:
        cmd += ["--last", str(last)]
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        sys.exit(f"analytics.py exited with code {result.returncode}.")


def init_repo(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    path = app_path(root)
    created: list[Path] = []

    if getattr(args, "no_worktrees", False):
        enable_worktrees = False
    else:
        enable_worktrees = bool(getattr(args, "worktrees", False)) or is_git_repository(
            root
        )

    # decide whose repository this is before anything is written,
    # so in a foreign one .ai-task/ is never visible to git, not even briefly.
    ownership_override = getattr(args, "ownership", "auto") or "auto"
    recorded_own = stored_ownership(root) == "own"
    ownership = decide_ownership(root, ownership_override)
    exclude_action = (
        ensure_app_dir_excluded(root) if ownership.mode == "foreign" else None
    )

    for directory in [
        path,
        path / "policies",
        path / "runs",
        path / "packets",
        path / "cleanup",
        path / "worktrees",
        path / "reports",
    ]:
        if not directory.exists():
            directory.mkdir(parents=True)
            created.append(directory)

    files = {
        path / "config.toml": default_config(root, enable_worktrees=enable_worktrees),
        path / "reports" / ".gitkeep": "",
        path / "worktrees" / ".gitkeep": "",
        path / "state.json": json.dumps(default_state(), indent=2) + "\n",
        path / "inbox.jsonl": "",
        path / "decisions.jsonl": "",
        path / "policies" / "default.toml": default_policy(
            default_verify_profile=default_verify_profile_for_repo(root)[0]
        ),
        path / "runs" / ".gitkeep": "",
        path / "packets" / ".gitkeep": "",
        path / "cleanup" / ".gitkeep": "",
    }
    for file_path, content in files.items():
        if file_path.exists() and not args.force:
            continue
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        created.append(file_path)

    # Remember an explicit answer; keep a recorded "own" across `--force`,
    # which rewrites config.toml from the template.
    if ownership_override in ("own", "foreign"):
        record_ownership(root, ownership_override)
    elif recorded_own:
        record_ownership(root, "own")

    bootstrap_created = copy_bootstrap_docs(root)
    created.extend(bootstrap_created)
    script_changes = copy_bootstrap_scripts(root)
    created.extend(dest for dest, _ in script_changes)

    # Policy-hash baseline: init is a reviewed state, record it.
    baseline_existed = policy_baseline_path(root).exists()
    write_policy_baseline(root)
    if not baseline_existed:
        created.append(policy_baseline_path(root))

    print(f"Initialized {APP_DIR} in {root}")
    print(f"Repository ownership: {ownership.mode} ({ownership.reason}).")
    if ownership.mode == "foreign":
        if exclude_action == "no-git":
            print(
                f"Not a git repository: nothing to exclude. If it becomes one, "
                f"re-run init so {APP_DIR}/ goes to .git/info/exclude."
            )
        else:
            state = "added to" if exclude_action == "added" else "already in"
            print(
                f"/{APP_DIR}/ {state} .git/info/exclude (local, never committed). "
                f"Do not add {APP_DIR} lines to .gitignore and do not commit any "
                f"{APP_DIR} file in this repository."
            )
        for line in foreign_migration_notice(root):
            print(line)
        if ownership.unconfigured:
            print(
                f"To mark your own repositories, copy {PROFILE_CONFIG_EXAMPLE} to "
                f"{profile_config_path()} and list them in own_remotes, or pass "
                "--ownership own."
            )
    else:
        print(
            f"Own repository: tracking {APP_DIR}/config.toml and policies/ "
            "stays your choice, as before."
        )
    if created:
        print("Created or refreshed:")
        for item in created:
            print(f"- {item.relative_to(root)}")
    else:
        print("No files changed.")
    if bootstrap_created:
        print("Bootstrap delivery docs copied from ai-sdlc-local-kit profile:")
        for item in bootstrap_created:
            print(f"- {item.relative_to(root)}")
    if script_changes:
        print("Bootstrap helper scripts vendored from ai-sdlc-local-kit profile:")
        for dest, action in script_changes:
            print(f"- {dest.relative_to(root)} ({action})")
    guard_change = refresh_tracked_index_guard(root)
    if guard_change is not None:
        guard_dest, guard_action = guard_change
        guard_rel = guard_dest.relative_to(root)
        if guard_action == "unchanged":
            print(f"Tracked backlog index guard up to date: {guard_rel}")
        else:
            print(
                f"Tracked backlog index guard {guard_action}: {guard_rel} - "
                "TRACKED on purpose (CI checks out only tracked files). Commit "
                f"it and run `python3 {guard_rel} check` in this repo's CI."
            )
    legacy = legacy_bootstrap_copies(root)
    if legacy:
        print(
            "Note: bootstrap files now live under .ai-task/ (gitignored). "
            "Tracked copies from an older ai-task layout remain at:"
        )
        for rel in legacy:
            print(f"- {rel}")
        print(
            "You may delete these old copies; init does not remove them. "
            "Delivery skills now use the .ai-task/ paths."
        )
    verify_profile, verify_reason = default_verify_profile_for_repo(root)
    print(f"Verify default_profile: {verify_profile} ({verify_reason})")
    if verify_profile == "none":
        stacks = detect_repo_stacks(root) - INFRA_STACKS
        if len(stacks) > 1:
            print(
                "Mixed stacks detected: set default_profile in .ai-task/policies/default.toml "
                "(e.g. python-full, node-full; or uncomment and edit the fullstack-example "
                "composite profile in the template) or use Verify: per task before verify."
            )
        elif not stacks:
            print(
                "No stack markers: edit default_profile in .ai-task/policies/default.toml before verify."
            )
    if enable_worktrees:
        print("worktrees_enabled = true (git repository detected)")
    policy = read_policy(root)
    if quota_enabled(policy):
        print(
            "Quota setup: helper vendored under .ai-task/scripts/. "
            "Run `ai-task quota setup-statusline --global` for global settings "
            "(recommended), or `ai-task quota setup-statusline --project` for "
            "repo-local settings, then `ai-task quota setup-statusline --check`."
        )
    print("Next: ai-task plan")


def dor_cmd(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    tasks = parse_backlog(root)
    gaps = dor_gaps_for_root(
        root,
        open_only=not args.all_tasks,
        task_id=args.task_id,
    )
    registry = load_review_registry(root)
    open_tasks = [task for task in tasks if task.is_open]
    if args.task_id:
        open_tasks = [task for task in open_tasks if task.id == args.task_id]
    policy = read_policy(root, getattr(args, "policy", None))
    review_planning = [
        review_planning_for_task(root, task, registry, policy) for task in open_tasks
    ]
    # advisory reminders (not DoR gaps) for shared-contract changes whose
    # cross-cutting rebuild invariant is not yet imprinted into the task DoD.
    rebuild_reminders = collect_rebuild_invariant_reminders(
        tasks, open_only=True, task_id=args.task_id
    )
    if args.json:
        payload: dict[str, Any] = {
            "gaps": [gap.as_dict() for gap in gaps],
            "review_planning": review_planning,
            "rebuild_invariant_reminders": [rem.as_dict() for rem in rebuild_reminders],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print_dor_gaps(gaps, as_json=False)
        for item in review_planning:
            missing = "yes" if item.get("review_skills_missing") else "no"
            print(
                f"Review plan {item['task_id']}: stacks={','.join(item.get('review_stack', [])) or 'none'} "
                f"risk={item.get('risk_class')} "
                f"status={item.get('review_skills_status')} missing_registry={missing}"
            )
    # Soft note (not a DoR gap): owner-only tasks are valid but autonomous runs skip
    # them, so a headless queue never dispatches them.
    owner_only_note = format_owner_only_remaining(open_tasks)
    if owner_only_note:
        print(owner_only_note, file=sys.stderr)
    # Soft note (not a DoR gap): shared-contract changes missing a rebuild invariant,
    # so a from-scratch rebuild does not silently drift.
    rebuild_note = format_rebuild_invariant_reminders(rebuild_reminders)
    if rebuild_note:
        print(rebuild_note, file=sys.stderr)
    if gaps:
        raise SystemExit(1)


def backlog_order_cmd(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    tasks = parse_backlog(root)
    warn_dependency_cycles(tasks)
    # on the file-per-task store, refuse to schedule a block that
    # never declared what the scheduler acts on. Reading a missing `Priority:`
    # as P2 made `backlog-order` report a value nobody wrote, and this is the
    # one place that runs with or without `.ai-task/`, so the gate belongs here
    # rather than behind `dor`.
    store_problems = backlog_store.block_problems(root)
    if store_problems:
        for problem in store_problems:
            print(problem, file=sys.stderr)
        die(
            "backlog store: open task blocks are missing metadata the scheduler "
            "acts on. Fix the blocks (or `backlog-store.py check` for the full "
            "list); nothing is scheduled on invented values."
        )
    if app_path(root).exists():
        require_initialized(root)
        policy = read_policy(root, getattr(args, "policy", None))
        if getattr(args, "strict", False):
            enforce_dor_gaps(dor_gaps_for_root(root, open_only=True))
    else:
        policy = {"priority": {"order": ["P0", "P1", "P2", "P3"]}}
    ordered = open_tasks_execution_order(
        tasks, policy, extra_done_ids=archived_done_ids(root)
    )
    # Autonomous dispatch: drop owner-only (Agent: human) tasks from the queue and
    # surface them separately, so a headless runner drains Agent: auto work and never
    # picks an owner-only task.
    autonomous = getattr(args, "autonomous", False)
    owner_only_note = format_owner_only_remaining(ordered) if autonomous else None
    if autonomous:
        ordered = [task for task in ordered if autonomous_skip_reason(task) is None]
    if getattr(args, "json", False):
        print(
            json.dumps(
                [
                    {
                        "id": task.id,
                        "priority": task.priority,
                        "depends_on": list(task.depends_on),
                    }
                    for task in ordered
                ],
                indent=2,
            )
        )
        if owner_only_note:
            print(owner_only_note, file=sys.stderr)
        return
    if not ordered:
        print("No autonomous-eligible open tasks." if autonomous else "No open tasks.")
        if owner_only_note:
            print(owner_only_note, file=sys.stderr)
        return
    for task in ordered:
        deps = ", ".join(task.depends_on) if task.depends_on else "none"
        print(f"{task.id} [{task.priority}/{task.size}] depends: {deps}")
    if owner_only_note:
        print(owner_only_note, file=sys.stderr)


def plan(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    policy = read_policy(root, args.policy)
    if getattr(args, "bulk", False):
        # Bulk plan executes quota refresh sources from policy — check drift.
        check_policy_baseline(root, policy, phase="plan")
    if getattr(args, "bulk", False) and not getattr(args, "no_bulk_check", False):
        ok, reason = check_bulk_scenario_confirmed(root, policy=policy)
        if not ok:
            die(f"bulk scenario not confirmed: {reason}")
        if "policy [scenario] default" in reason:
            print(f"scenario: {reason}", file=sys.stderr)
    state = load_state(root)
    tasks = parse_backlog(root)
    warn_dependency_cycles(tasks)
    if getattr(args, "strict", False):
        enforce_dor_gaps(dor_gaps_for_root(root, open_only=True))
    # A plan batch feeds packet generation and choose_backend_order, which cannot
    # dispatch an owner-only (Agent: human) task. Exclude them from EVERY plan batch,
    # not only --bulk/--autonomous: a pinned or
    # top-priority human task is skipped past instead of hard-failing the run-only
    # guard on plain `plan`, and the owner-only remainder is always surfaced separately
    # (`plan` has no explicit-id mode — that is `run <id>`, which stays addressable).
    eligible = eligible_tasks(
        tasks, state, policy, autonomous=True, extra_done_ids=archived_done_ids(root)
    )
    owner_only_note = format_owner_only_remaining(tasks)
    batch_size, batch_reasoning = resolve_wave_batch_size(
        explicit_batch=args.batch,
        auto_batch=getattr(args, "auto_batch", False),
        policy=policy,
        eligible_count=len(eligible),
    )
    selected = eligible[:batch_size]
    if owner_only_note:
        print(owner_only_note, file=sys.stderr)
    if not selected:
        blocked = blocked_by_dependencies(
            tasks, state, extra_done_ids=archived_done_ids(root)
        )
        if blocked:
            print("Blocked by dependencies:")
            for item in blocked:
                print(f"- {item['id']}: waiting for {', '.join(item['waiting_for'])}")
        print("No eligible open tasks.")
        return
    if getattr(args, "bulk", False):
        quota_tasks = [
            task
            for task in selected
            if any(
                is_quota_gated_backend(name, policy)
                for name in choose_backend_order(
                    task, policy, args.backend, state, root, for_run=False
                )
            )
        ]
        if quota_tasks:
            refresh_result = maybe_refresh_quota_for_dispatch(
                root,
                policy,
                task_ids=[task.id for task in quota_tasks],
                phase="plan",
                state=state,
            )
            status = refresh_result.get("status")
            if (
                isinstance(status, dict)
                and status.get("available")
                and status.get("at_or_over_stop")
            ):
                die(
                    "Claude quota is at/over the reserve stop line after refresh; "
                    "wait for reset, reduce the Claude sub-wave, or use an allowed fallback"
                )
    registry = load_review_registry(root)
    state["last_batch"] = [task.id for task in selected]
    batch_out: list[dict[str, Any]] = []
    for task in selected:
        backend_order = choose_backend_order(task, policy, args.backend, state, root)
        packet = generate_packet(root, task, policy, backend_order, state)
        planning = review_planning_for_task(root, task, registry, policy)
        entry = {
            "id": task.id,
            "priority": task.priority,
            "size": task.size,
            "title": task.title,
            "packet": str(packet.relative_to(root)),
            "backends": backend_order,
            "review_gates": risk_gates(task, policy),
            **planning,
        }
        batch_out.append(entry)
        if not getattr(args, "json", False):
            print(f"{task.id} [{task.priority}/{task.size}] {task.title}")
            print(f"  packet: {packet.relative_to(root)}")
            print(
                f"  backends: {', '.join(backend_order) if backend_order else 'none enabled'}"
            )
            gates = entry["review_gates"]
            if gates:
                print(f"  review gates: {', '.join(gates)}")
            print(
                f"  review plan: stacks={','.join(planning.get('review_stack', [])) or 'none'} "
                f"status={planning.get('review_skills_status')}"
            )
            if planning.get("review_skills_missing"):
                print(f"  review registry: extend {planning.get('registry_hint')}")
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "batch_size": batch_size,
                    "eligible_count": len(eligible),
                    "batch_reasoning": batch_reasoning,
                    "batch": batch_out,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    save_state(root, state)


def run(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    config = read_config(root)
    policy = read_policy(root, args.policy)
    check_policy_baseline(root, policy, phase="delivery")
    # Bulk scenario guard: when --bulk is set and no specific task is named.
    if (
        getattr(args, "bulk", False)
        and not args.task
        and not getattr(args, "no_bulk_check", False)
    ):
        ok, reason = check_bulk_scenario_confirmed(root, policy=policy)
        if not ok:
            die(f"bulk scenario not confirmed: {reason}")
        if "policy [scenario] default" in reason:
            print(f"scenario: {reason}", file=sys.stderr)
    state = load_state(root)
    refresh_runs(root, state, policy)
    tasks = parse_backlog(root)
    # The default `run` (no explicit id) is headless/autonomous dispatch: it must not
    # pick an owner-only (Agent: human) task. An explicit `run <id>`
    # bypasses this gate — the operator addressed the task by name — and an owner-only
    # id then still meets the coordination-only refusal below/in choose_backend_order.
    autonomous = getattr(args, "autonomous", False) or not args.task
    if args.task:
        selected = [task for task in tasks if task.id == args.task and task.is_open]
        if not selected:
            die(f"task not open in backlog: {args.task}")
    else:
        selected = eligible_tasks(
            tasks,
            state,
            policy,
            autonomous=autonomous,
            extra_done_ids=archived_done_ids(root),
        )[:1]
    if not selected:
        owner_only_note = format_owner_only_remaining(tasks) if autonomous else None
        if owner_only_note:
            die(f"no autonomous-eligible task matched the request; {owner_only_note}")
        die("no eligible task matched the request")
    task = selected[0]
    enforce_dor_gaps(dor_gaps_for_root(root, open_only=False, task_id=task.id))
    if task.agent == "human":
        die(f"task {task.id} has Agent: human (coordination only; do not ai-task run)")
    lease_msg = task_lease_message(state, task.id, args.take_lease)
    if lease_msg:
        die(lease_msg)
    if not args.dry_run:
        enforce_risk_confirm(
            task,
            policy,
            args.confirm_risk,
            risk_ack=getattr(args, "risk_ack", None),
            root=root,
            state=state,
        )
    refresh_cooldowns(root, state, policy)
    backend_order = choose_backend_order(
        task, policy, args.backend, state, root, confirm_risk=args.confirm_risk
    )
    if not args.dry_run and any(is_quota_gated_backend(name, policy) for name in backend_order):
        maybe_refresh_quota_for_dispatch(
            root,
            policy,
            task_ids=[task.id],
            phase="delivery",
            state=state,
        )
    # include the latest review-findings.md (rework section) like
    # `packet refresh` does — the run-side rebuild used to drop it, so retry runs
    # after `verdict rework` were blind to review findings. Findings are KEPT
    # (never auto-cleared): the newest per-task review-findings.md keeps being
    # included until the task is approved/closed; a newer review supersedes it.
    # No-op for tasks that have no findings.
    packet = generate_packet(
        root,
        task,
        policy,
        backend_order,
        state,
        include_notes=True,
        include_rework=True,
    )
    prompt = packet.read_text(encoding="utf-8")

    backends = policy.get("backends", {})
    chosen_name = ""
    chosen_backend: dict[str, Any] = {}
    for name in backend_order:
        backend = backends.get(name, {})
        if not backend.get("enabled", False):
            continue
        if backend_available(backend):
            chosen_name = name
            chosen_backend = backend
            break
        set_backend_cooldown(state, name, policy, "command unavailable")
    if not chosen_name:
        save_state(root, state)
        die(f"no available backend in order: {', '.join(backend_order) or 'none'}")
    # In-session executor: the teamlead's own subagent does
    # the work, so ai-task records the run and launches nothing. There is no
    # process to wait on; the subagent reports through `worker-done`.
    in_session = is_in_session_backend(chosen_backend)
    if in_session and args.wait:
        die(
            f"backend {chosen_name} is an in-session executor: start the run without "
            "--wait, hand the packet to a fresh subagent, then record its outcome "
            "with `ai-task worker-done`"
        )
    # refuse a claude worker whose settings JSON this Claude Code would
    # drop (print mode ignores an invalid settings file without a word). Cached per
    # CLI version, so this costs about two seconds once per new version.
    if not args.dry_run and not in_session:
        blocked = claude_settings_launch_block(chosen_backend, root)
        if blocked:
            save_state(root, state)
            die(f"claude settings canary refused the run of {task.id}: {blocked}")

    # Quota admission control routing decision. When the chosen backend
    # is Claude and a pessimistic Size-based reservation would not fit the remaining
    # budget, prefer a non-Claude fallback (same candidates as limit fallback) before
    # blocking. The reservation itself is acquired atomically under the state lock
    # just before launch; here we record the routing fields and, for the detached
    # (non --wait) path, pick the backend to launch. The --wait loop owns its own
    # per-attempt reservation + fallback. Dry runs never reserve.
    quota_routing: dict[str, Any] = {
        "quota_required": None,
        "quota_available": None,
        "quota_blocked_reason": None,
    }
    if (
        not args.dry_run
        and quota_enabled(policy)
        and is_quota_gated_backend(chosen_name, policy)
    ):
        decision = reservation_decision(task, policy, quota_status(root, policy), state)
        quota_routing["quota_required"] = decision["required"]
        quota_routing["quota_available"] = decision["available"]
        if not decision["fits"]:
            fallback_name = next(
                iter(
                    quota_fallback_candidates(
                        task, policy, state, root, confirm_risk=args.confirm_risk
                    )
                ),
                None,
            )
            quota_routing["quota_blocked_reason"] = decision["blocked_reason"]
            if fallback_name and not args.wait and not in_session:
                # Detached launch: hand off to the cursor fallback now. An
                # in-session choice is explicit and never moves to another vendor.
                chosen_name = fallback_name
                chosen_backend = backends.get(fallback_name, {})
            elif not args.wait and (not fallback_name or in_session):
                # No fallback. If a reset time is derivable and auto-resume is enabled,
                # fall through so the run record + worktree are created and the
                # reservation block below records the recoverable waiting_quota state.
                # Otherwise this is a terminal quota_blocked here.
                # An in-session run never waits for auto-resume: resuming would
                # launch a headless worker.
                resume_after, _resume_window = quota_resume_after_from_status(
                    quota_status(root, policy), policy
                )
                if in_session or not (quota_resume_max_attempts(policy) > 0 and resume_after):
                    save_state(root, state)
                    die(
                        f"Claude quota-blocked for task {task.id}: "
                        f"required {decision['required']}% > available "
                        f"{decision['available']}% ({decision['blocked_reason']}). "
                        "Not failed work — wait for the window to reset, raise budget, "
                        "or allow a non-Claude fallback. See `ai-task quota status`."
                    )

    run_id = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{task.id}-{uuid.uuid4().hex[:8]}"
    run_dir = app_path(root) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "packet.md").write_text(prompt, encoding="utf-8")
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    run_cwd = root.resolve()
    wt_rel = ""
    wt_branch = ""
    if args.dry_run:
        if worktrees_enabled(config):
            wt_rel, wt_branch = planned_worktree(root, task, run_id)
    else:
        run_cwd, wt_rel, wt_branch = prepare_run_worktree(root, config, task, run_id)
    workspace = run_cwd if wt_rel else None
    command = (
        []
        if in_session
        else backend_command(
            chosen_backend, prompt, workspace=workspace, output_dir=run_dir, run_cwd=run_cwd
        )
    )

    record = {
        "id": run_id,
        "task_id": task.id,
        "task_title": task.title,
        "backend": chosen_name,
        "backend_selection": (
            "explicit --backend" if args.backend != "auto" else
            "wave pin" if state.get("pinned_backend") else
            "task Agent" if task.agent != "auto" else default_backend_order(task, policy)[1]
        ),
        "final_message": (
            str((run_dir / "final.md").relative_to(root))
            if chosen_backend.get("output_last_message_arg") else None
        ),
        # Model and effort the backend launches with: the
        # teamlead reports them per stage, and the backend name alone does not
        # say which model wrote the code.
        **backend_model_info(chosen_backend),
        "backend_reasoning": chosen_backend.get("reasoning", ""),
        # Optional authorship: who launched this run. Informational;
        # legacy records without it aggregate as "unknown".
        "operator": operator_identity(),
        "status": "dry_run" if args.dry_run else "running",
        "created_at": now(),
        "started_at": None if args.dry_run else now(),
        "pid": None,
        "packet": str(packet.relative_to(root)),
        "run_dir": str(run_dir.relative_to(root)),
        "stdout": str(stdout_path.relative_to(root)),
        "stderr": str(stderr_path.relative_to(root)),
        "review_gates": risk_gates(task, policy),
        "risk_confirmed": bool(args.confirm_risk),
        "worktree_path": wt_rel or None,
        "worktree_branch": wt_branch or None,
        "command": command,
        "quota_required": quota_routing["quota_required"],
        "quota_available": quota_routing["quota_available"],
        "quota_reserved": False,
        "quota_blocked_reason": quota_routing["quota_blocked_reason"],
    }
    if in_session:
        record["in_session"] = True
        record["final_message"] = str((run_dir / "final.md").relative_to(root))
        # the subagent is started with the model and effort of the
        # same vendor's headless backend; worker-done records what it ran on.
        record.update(in_session_model_request(policy, chosen_name))
    state.setdefault("runs", {})[run_id] = record
    if not args.dry_run:
        # Pre-run task-file snapshot for the out-of-scope edit guard.
        record["scope_guard"] = capture_scope_snapshot(run_dir, run_cwd, policy)
        if wt_rel:
            # Launch baseline of the MAIN tree's tracked-dirty paths so
            # pre-existing/operator main-tree dirt is not flagged as a
            # main-checkout leak at finalize. Worktree runs only.
            record["main_tree_pre_dirty"] = sorted(main_tree_tracked_dirty(root))
        auto_log_run_start_anomalies(
            root,
            policy,
            state,
            task,
            run_id,
            chosen_name,
            confirm_risk=bool(args.confirm_risk),
        )

    if args.dry_run:
        save_state(root, state)
        print(f"Dry run prepared {run_id}")
        print(f"backend: {chosen_name}")
        print(f"selection: {record['backend_selection']}")
        if model_info_text(record):
            print(f"model: {model_info_text(record)}")
        print(f"packet: {packet.relative_to(root)}")
        if wt_rel:
            print(f"worktree: branch {wt_branch} at {wt_rel}")
        if in_session:
            print("command: none (in-session subagent)")
            if in_session_spawn_text(record):
                print(in_session_spawn_text(record))
        else:
            print("command:", " ".join(command))
        return

    acquire_task_lease(state, task.id, run_id, chosen_name)

    # Quota telemetry: capture the pre-launch quota snapshot and decide
    # whether this run is part of a parallel wave. A wave is detected when, at launch,
    # any OTHER run is already holding a quota reservation or actively running on a
    # quota-gated backend — there is no per-run usage metadata to attribute spend, so
    # such samples are flagged confidence: low. Best-effort and inert without a fresh
    # quota source (the sample then degrades to partial). The sample itself is written
    # at each terminal point below.
    telemetry_pre_quota = (
        telemetry_quota_snapshot(quota_status(root, policy))
        if is_quota_gated_backend(chosen_name, policy) else None
    )
    telemetry_sample_kind = (
        "parallel" if other_active_quota_run(state, run_id, policy) else "single"
    )

    if args.wait:
        record["status"] = "running"
        record["attempts"] = []
        save_state(root, state)
        attempted: set[str] = set()
        # Resume time parsed from a real Claude limit message, used to
        # set waiting_quota for repos with no fresh quota snapshot. None until a
        # Claude attempt is limited and its text carries a parseable reset hint.
        limit_resume_after: str | None = None
        while True:
            # Limit-fallback order (unchanged) plus quota-fallback candidates so a
            # Claude-quota-blocked attempt can hand off to cursor even when Claude is
            # not in cooldown.
            attempt_order = choose_backend_order(
                task, policy, args.backend, state, root, confirm_risk=args.confirm_risk
            )
            for fb in quota_fallback_candidates(
                task, policy, state, root, confirm_risk=args.confirm_risk
            ):
                if fb not in attempt_order:
                    attempt_order.append(fb)
            attempt_name = next(
                (name for name in attempt_order if name not in attempted), None
            )
            if not attempt_name:
                break
            attempted.add(attempt_name)
            attempt_backend = backends.get(attempt_name, {})
            if not attempt_backend.get("enabled", False) or not backend_available(
                attempt_backend
            ):
                continue
            # Quota admission control for a Claude attempt: reserve the
            # pessimistic Size budget atomically before launching. If it does not fit,
            # do not launch Claude — record the block and try the next (cursor)
            # attempt. Inert (reserved=False, available=None) without a fresh source.
            if is_quota_gated_backend(attempt_name, policy):
                reservation = try_acquire_quota_reservation(
                    root, policy, task, run_id, attempt_name
                )
                record["quota_required"] = reservation["required"]
                record["quota_available"] = reservation["available"]
                record["quota_reserved"] = reservation["reserved"]
                if reservation["reserved"]:
                    state.setdefault("quota_reservations", {})[run_id] = {
                        "run_id": run_id,
                        "task_id": task.id,
                        "size": task.size,
                        "backend": attempt_name,
                        "percentage": reservation["required"],
                        "created_at": now(),
                    }
                elif reservation["blocked_reason"] is not None:
                    record["quota_blocked_reason"] = reservation["blocked_reason"]
                    save_state(root, state)
                    continue
            attempt_stdout = run_dir / f"{attempt_name}-stdout.log"
            attempt_stderr = run_dir / f"{attempt_name}-stderr.log"
            attempt_command = backend_command(
                attempt_backend, prompt, workspace=workspace, output_dir=run_dir,
                run_cwd=run_cwd,
            )
            sup = supervision_config(policy)
            stall_timeout = int(sup.get("stall_timeout_seconds", 0) or 0)
            auto_stop = bool(sup.get("auto_stop_on_stall", False))

            def capture_pid(pid: int) -> None:
                # Persist the backend child pid so status/pid_alive and the orphan
                # reaper reflect reality if this --wait supervisor is killed mid-run.
                # The record stays "running" until the attempt exits.
                record["pid"] = pid
                save_state(root, state)

            if stall_timeout > 0:
                completed = wait_subprocess_with_supervision(
                    attempt_command,
                    cwd=run_cwd,
                    prompt_input=backend_input(attempt_backend, prompt),
                    stdout_path=attempt_stdout,
                    stderr_path=attempt_stderr,
                    policy=policy,
                    stall_timeout=stall_timeout,
                    auto_stop=auto_stop,
                    env=backend_env(attempt_backend, root=root),
                    on_start=capture_pid,
                )
            else:
                completed = run_attempt_capturing_pid(
                    attempt_command,
                    cwd=run_cwd,
                    prompt_input=backend_input(attempt_backend, prompt),
                    stdout_path=attempt_stdout,
                    stderr_path=attempt_stderr,
                    env=backend_env(attempt_backend, root=root),
                    on_start=capture_pid,
                )
            log_text = ""
            for path in (attempt_stdout, attempt_stderr):
                log_text += path.read_text(encoding="utf-8", errors="replace")[-8000:]
            limited = detect_limit(log_text, attempt_backend)
            stalled = completed.returncode == 124
            blocked = detect_blocked(log_text, policy)
            # Credential-dead attempt: gated on a nonzero exit so a
            # run that merely mentions authentication while succeeding is never
            # reclassified. Not a task failure — the backend cannot work here.
            auth_failed = completed.returncode != 0 and detect_auth_failure(
                log_text, attempt_backend
            )
            record["attempts"].append(
                {
                    "backend": attempt_name,
                    **backend_model_info(attempt_backend),
                    "command": attempt_command,
                    "exit_code": completed.returncode,
                    "limited": limited,
                    "stalled": stalled,
                    "blocked_on_user": blocked,
                    "auth_failed": auth_failed,
                    "stdout": str(attempt_stdout.relative_to(root)),
                    "stderr": str(attempt_stderr.relative_to(root)),
                    "finished_at": now(),
                }
            )
            if stalled:
                record["status_note"] = (
                    "stalled: auto-stopped after stall_timeout_seconds"
                )
                if auto_stop:
                    record["status"] = "failed"
                    apply_scope_guard_at_finalize(root, policy, state, record)
                    release_quota_reservation(state, run_id)
                    record["finished_at"] = now()
                    record["exit_code"] = completed.returncode
                    # Quota telemetry: a stalled, auto-stopped run still
                    # consumed budget; record it with the stalled signal.
                    record_quota_telemetry(
                        root=root,
                        policy=policy,
                        run=record,
                        task=task,
                        backend=attempt_name,
                        backend_config=attempt_backend,
                        pre_quota=telemetry_pre_quota,
                        exit_status="failed",
                        stalled=True,
                        sample_kind=telemetry_sample_kind,
                        run_cwd=run_cwd,
                    )
                    # Terminal-without-verdict: a stalled+auto-stopped
                    # run never reaches `verdict`, so this is its only outcome ping.
                    notify_run_outcome(root, state, record)
                    save_state(root, state)
                    die(record["status_note"])
            if limited:
                set_backend_cooldown(
                    state,
                    attempt_name,
                    policy,
                    "limit detected during waited run",
                    run_id,
                    from_active_attempt=True,
                )
                # Claude hit its limit — free its quota reservation before falling
                # back so the budget is available to other parallel runs.
                if is_quota_gated_backend(attempt_name, policy):
                    release_quota_reservation(state, run_id)
                    # Parse a reset hint from the limit text so a no-fallback outcome
                    # can become waiting_quota even with no quota snapshot.
                    parsed_resume = parse_limit_reset_after(log_text, policy)
                    if parsed_resume is not None:
                        limit_resume_after = parsed_resume
                    # Quota telemetry: a limited Claude attempt is a
                    # real sample (it consumed budget up to the limit). Record it now
                    # because the run may finish on a non-Claude fallback that is not
                    # otherwise sampled. exit_status=limited marks the limit signal.
                    record_quota_telemetry(
                        root=root,
                        policy=policy,
                        run={**record, "exit_code": completed.returncode},
                        task=task,
                        backend=attempt_name,
                        backend_config=attempt_backend,
                        pre_quota=telemetry_pre_quota,
                        exit_status="limited",
                        limited=True,
                        sample_kind=telemetry_sample_kind,
                        run_cwd=run_cwd,
                    )
                save_state(root, state)
                next_name = next(
                    (name for name in attempt_order if name not in attempted), None
                )
                if next_name:
                    auto_log_limit_fallback_switch(
                        root,
                        policy,
                        state,
                        task,
                        run_id,
                        from_backend=attempt_name,
                        to_backend=next_name,
                        limit_detected=True,
                    )
                continue
            if auth_failed:
                # Credential-dead attempt: remember the backend as
                # unusable, hand the work to the next backend in the chain, and
                # do NOT let this count as a task failure. Evaluated after the
                # limit branch on purpose — a limited attempt did authenticate.
                auth_reason = auth_failure_reason(
                    attempt_name, attempt_backend, log_text
                )
                mark_backend_credential_dead(
                    state, attempt_name, attempt_backend, auth_reason, run_id
                )
                # The attempt did zero work; free any budget it reserved so a
                # peer run can use it (mirrors the limit path).
                if is_quota_gated_backend(attempt_name, policy):
                    release_quota_reservation(state, run_id)
                save_state(root, state)
                # Recompute the chain AFTER the mark: marking a primary
                # credential-dead is what opens the fallback order, so the stale
                # pre-mark list would under-report the backend that actually
                # picks the work up (and mislabel the journal row).
                next_name = next(
                    (
                        name
                        for name in choose_backend_order(
                            task,
                            policy,
                            args.backend,
                            state,
                            root,
                            confirm_risk=args.confirm_risk,
                        )
                        if name not in attempted
                    ),
                    None,
                )
                print(f"backend unusable: {auth_reason}", file=sys.stderr)
                if next_name:
                    print(f"falling through to backend: {next_name}", file=sys.stderr)
                auto_log_credential_dead_fallback(
                    root,
                    policy,
                    state,
                    task,
                    run_id,
                    from_backend=attempt_name,
                    to_backend=next_name or "",
                    reason=auth_reason,
                )
                continue
            record["backend"] = attempt_name
            record.update(backend_model_info(attempt_backend))
            record["final_message"] = (
                str((run_dir / "final.md").relative_to(root))
                if attempt_backend.get("output_last_message_arg") else None
            )
            record["command"] = attempt_command
            record["stdout"] = str(attempt_stdout.relative_to(root))
            record["stderr"] = str(attempt_stderr.relative_to(root))
            record["exit_code"] = completed.returncode
            record["finished_at"] = now()
            if completed.returncode == 0:
                # A clean attempt proves the credentials work.
                clear_backend_credentials(state, attempt_name)
            apply_supervision(record, root, policy, backends)
            record["status"] = "needs_review" if completed.returncode == 0 else "failed"
            if completed.returncode == 0:
                # The worker-done report of a schema backend.
                apply_worker_report(
                    root, state, record, attempt_name, attempt_backend, policy
                )
            # Out-of-scope backlog edit guard at finalize.
            apply_scope_guard_at_finalize(root, policy, state, record)
            # Main-checkout leak guard: hard-fail if this worktree-isolated run
            # left NEW tracked edits on the MAIN checkout.
            enforce_main_tree_clean_at_finalize(
                root, state, policy, record, fatal=True
            )
            release_task_lease(state, task.id)
            release_quota_reservation(state, run_id)
            # Terminal-without-verdict: only the `failed` outcome is
            # terminal here — `needs_review` proceeds to verify/verdict and pings
            # later from verdict_cmd, so it must NOT ping now.
            if record["status"] == "failed":
                notify_run_outcome(root, state, record)
            save_state(root, state)
            # Quota telemetry: record the completed run. Best-effort and
            # only sampled for quota-gated (Claude) backends — a cursor fallback that
            # finished after Claude was limited is recorded under the Claude limit
            # terminal above, not here.
            record_quota_telemetry(
                root=root,
                policy=policy,
                run=record,
                task=task,
                backend=attempt_name,
                backend_config=attempt_backend,
                pre_quota=telemetry_pre_quota,
                exit_status=record["status"],
                limited=limited,
                stalled=stalled,
                sample_kind=telemetry_sample_kind,
                run_cwd=run_cwd,
            )
            print(f"Finished {run_id}")
            print(f"backend: {attempt_name}")
            if model_info_text(record):
                print(f"model: {model_info_text(record)}")
            print(f"status: {record['status']}")
            scope_edits = record.get("out_of_scope_edits") or []
            if scope_edits:
                print(
                    f"out_of_scope_edits: {len(scope_edits)} backlog edit(s) outside "
                    f"{task.id}'s own task block — see `status --json` before merge-back"
                )
            sensitive_edits = record.get("sensitive_file_edits") or []
            if sensitive_edits:
                print(
                    f"sensitive_file_edits: {len(sensitive_edits)} control-file "
                    "edit(s) (.gitmodules / .ai-task config or policies) — see "
                    "`status --json` before merge-back"
                )
            if wt_rel:
                print(f"worktree: {wt_rel} (branch {wt_branch})")
            return
        record["finished_at"] = now()
        quota_blocked_terminal = bool(
            not record["attempts"] and record.get("quota_blocked_reason")
        )
        # Chain exhausted with a credential-dead backend in it: every
        # attempt was either unauthenticated or rate-limited, so nothing ran and the
        # task did not fail. Requires at least one auth failure — an all-limited run
        # keeps its existing waiting_quota/failed handling below.
        credential_dead_terminal = bool(record["attempts"]) and (
            any(attempt.get("auth_failed") for attempt in record["attempts"])
            and all(
                attempt.get("auth_failed") or attempt.get("limited")
                for attempt in record["attempts"]
            )
        )
        # Earliest safe resume time: a fresh quota snapshot's reset (preferred) or a
        # reset hint parsed from the Claude limit text. When one exists
        # and auto-resume is enabled, this is a recoverable wait, not a terminal
        # block/failure — record waiting_quota so wait-runs --resume-on-quota can
        # re-launch the same packet after reset (and limit-pattern cooldowns still
        # apply for repos with no quota snapshot).
        snapshot_resume, snapshot_window = (
            quota_resume_after_from_status(quota_status(root, policy), policy)
            if quota_blocked_terminal or limit_resume_after is not None else (None, None)
        )
        resume_after = snapshot_resume or limit_resume_after
        resume_window = snapshot_window or ("five_hour" if limit_resume_after else None)
        if (
            quota_resume_max_attempts(policy) > 0
            and resume_after is not None
            and (quota_blocked_terminal or limit_resume_after is not None)
        ):
            if quota_blocked_terminal:
                reason = (
                    f"quota reservation did not fit (required "
                    f"{record.get('quota_required')}% > available "
                    f"{record.get('quota_available')}%, {record.get('quota_blocked_reason')})"
                )
            else:
                reason = "Claude reported a usage limit on every waited attempt"
            status_note = (
                f"waiting_quota: {reason}; auto-resume after {resume_after} — "
                "active wait state, not a failed verdict"
            )
            mark_run_waiting_quota(
                root,
                state,
                policy,
                record,
                task,
                reason=reason,
                resume_after=resume_after,
                quota_window=resume_window,
                status_note=status_note,
            )
            record_quota_telemetry(
                root=root,
                policy=policy,
                run=record,
                task=task,
                backend=chosen_name,
                backend_config=chosen_backend,
                pre_quota=telemetry_pre_quota,
                exit_status="waiting_quota",
                blocked_reason=record.get("quota_blocked_reason"),
                limited=limit_resume_after is not None,
                sample_kind=telemetry_sample_kind,
                capture_post=False,
                capture_diffstat=False,
            )
            save_state(root, state)
            die(str(record["status_note"]))
        if quota_blocked_terminal:
            # No attempt ran because Claude was quota-blocked and no fallback was
            # allowed/available, and no resume time is derivable. This is admission
            # control, not failed work: surface it as quota-blocked so
            # the teamlead waits, raises budget, or enables a fallback.
            record["status"] = "quota_blocked"
            record["status_note"] = (
                f"quota-blocked: required {record.get('quota_required')}% > available "
                f"{record.get('quota_available')}% "
                f"({record.get('quota_blocked_reason')}); not failed work — wait for "
                "the window to reset, raise budget, or allow a non-Claude fallback"
            )
        elif record["attempts"] and all(
            attempt.get("limited") and Path(str(backends.get(attempt["backend"], {}).get("command", ""))).name == "codex"
            for attempt in record["attempts"]
        ):
            record["status"] = "quota_blocked"
            record["status_note"] = (
                "Codex usage limit; backend cooldown active. Wait for Codex availability "
                "or explicitly choose another backend. No task failure consumed."
            )
        elif credential_dead_terminal:
            # Every backend in the chain was unauthenticated (or rate-limited) and
            # the chain is now exhausted. Refuse with the operator
            # fix — this is configuration, not a failed task, so it must not read
            # as one or consume the task's attempt budget.
            dead = [
                str(attempt.get("backend", ""))
                for attempt in record["attempts"]
                if attempt.get("auth_failed")
            ]
            fixes = "; ".join(
                dict.fromkeys(
                    f"{name}: "
                    f"{(backend_credential_dead(state, name) or {}).get('fix') or backend_auth_fix(backends.get(name, {}))}"
                    for name in dead
                    if name
                )
            )
            record["status"] = "backend_unusable"
            record["backend_unusable_reason"] = fixes
            record["status_note"] = (
                f"backend-unusable: no usable backend left in the chain — "
                f"{', '.join(dead)} not authenticated on this host; not failed work "
                f"and no task attempt consumed. Fix: {fixes}"
            )
        else:
            record["status"] = "failed"
            record["status_note"] = (
                "all available waited attempts were limited or unavailable"
            )
        # Limited attempts may have left partial edits behind.
        apply_scope_guard_at_finalize(root, policy, state, record)
        release_task_lease(state, task.id)
        release_quota_reservation(state, run_id)
        # Quota telemetry: a quota-blocked run never launched Claude, so
        # there is no post-launch delta or diffstat — record a partial sample (pre
        # snapshot + reservation + blocked reason) so the calibrator can account for
        # admission-control blocks without treating them as work samples.
        if record["status"] == "quota_blocked":
            record_quota_telemetry(
                root=root,
                policy=policy,
                run=record,
                task=task,
                backend=chosen_name,
                backend_config=chosen_backend,
                pre_quota=telemetry_pre_quota,
                exit_status="quota_blocked",
                blocked_reason=record.get("quota_blocked_reason"),
                sample_kind=telemetry_sample_kind,
                capture_post=False,
                capture_diffstat=False,
            )
        # Terminal-without-verdict: ping the `failed` outcome, and
        # `backend_unusable` — it is not a failure, but nothing resumes it either
        # (an operator must authenticate), so this is its only outcome ping.
        # `quota_blocked` still must NOT ping — it resumes (waiting_quota / re-run).
        if record["status"] in {"failed", "backend_unusable"}:
            notify_run_outcome(root, state, record)
        save_state(root, state)
        die(str(record["status_note"]))

    # Background (detached) launch. Atomically reserve quota for a Claude launch
    # under the state lock — the authoritative overbook check. If the
    # budget was consumed by a peer since the routing gate, release the lease and
    # block rather than overbook. Inert without a fresh quota source.
    if is_quota_gated_backend(chosen_name, policy):
        reservation = try_acquire_quota_reservation(
            root, policy, task, run_id, chosen_name
        )
        record["quota_required"] = reservation["required"]
        record["quota_available"] = reservation["available"]
        record["quota_reserved"] = reservation["reserved"]
        if reservation["reserved"]:
            state.setdefault("quota_reservations", {})[run_id] = {
                "run_id": run_id,
                "task_id": task.id,
                "size": task.size,
                "backend": chosen_name,
                "percentage": reservation["required"],
                "created_at": now(),
            }
        elif reservation["blocked_reason"] is not None:
            record["quota_blocked_reason"] = reservation["blocked_reason"]
            # A derivable reset time + enabled auto-resume makes this a recoverable
            # wait (waiting_quota), so wait-runs --resume-on-quota can re-launch this
            # detached run after reset; the lease is retained for that re-launch.
            # Otherwise it stays quota_blocked.
            snapshot_resume, snapshot_window = quota_resume_after_from_status(
                quota_status(root, policy), policy
            )
            if (
                quota_resume_max_attempts(policy) > 0
                and snapshot_resume is not None
                and not in_session
            ):
                reason = (
                    f"quota reservation did not fit (required "
                    f"{reservation['required']}% > available "
                    f"{reservation['available']}%, {reservation['blocked_reason']})"
                )
                status_note = (
                    f"waiting_quota: {reason}; auto-resume after {snapshot_resume} — "
                    "active wait state, not a failed verdict"
                )
                mark_run_waiting_quota(
                    root,
                    state,
                    policy,
                    record,
                    task,
                    reason=reason,
                    resume_after=snapshot_resume,
                    quota_window=snapshot_window,
                    status_note=status_note,
                )
                record_quota_telemetry(
                    root=root,
                    policy=policy,
                    run=record,
                    task=task,
                    backend=chosen_name,
                    backend_config=chosen_backend,
                    pre_quota=telemetry_pre_quota,
                    exit_status="waiting_quota",
                    blocked_reason=reservation["blocked_reason"],
                    sample_kind=telemetry_sample_kind,
                    capture_post=False,
                    capture_diffstat=False,
                )
                save_state(root, state)
                die(str(record["status_note"]))
            record["status"] = "quota_blocked"
            record["status_note"] = (
                f"quota-blocked: required {reservation['required']}% > available "
                f"{reservation['available']}% ({reservation['blocked_reason']}); "
                "not failed work — wait, raise budget, or allow a non-Claude fallback"
            )
            release_task_lease(state, task.id)
            # Quota telemetry: partial sample for a detached launch that
            # was admission-control blocked before it could start (no post/diffstat).
            record_quota_telemetry(
                root=root,
                policy=policy,
                run=record,
                task=task,
                backend=chosen_name,
                backend_config=chosen_backend,
                pre_quota=telemetry_pre_quota,
                exit_status="quota_blocked",
                blocked_reason=reservation["blocked_reason"],
                sample_kind=telemetry_sample_kind,
                capture_post=False,
                capture_diffstat=False,
            )
            save_state(root, state)
            die(str(record["status_note"]))

    if in_session:
        record["status_note"] = (
            "awaiting in-session worker: hand the run's packet to a fresh subagent "
            "working in the run's worktree, then record its outcome with worker-done"
        )
        record["telemetry_pre_quota"] = telemetry_pre_quota
        record["telemetry_sample_kind"] = telemetry_sample_kind
        record["telemetry_size"] = task.size
        save_state(root, state)
        record_quota_telemetry(
            root=root,
            policy=policy,
            run=record,
            task=task,
            backend=chosen_name,
            backend_config=chosen_backend,
            pre_quota=telemetry_pre_quota,
            exit_status="launched",
            sample_kind=telemetry_sample_kind,
            capture_post=False,
            capture_diffstat=False,
        )
        print(f"Started {run_id}")
        print(f"backend: {chosen_name} (in-session; no process launched)")
        print(f"packet: {run_dir / 'packet.md'}")
        print(f"workdir: {run_cwd}")
        if wt_rel:
            print(f"worktree: {wt_rel} (branch {wt_branch})")
        print(f"final answer: {root / record['final_message']}")
        if in_session_spawn_text(record):
            print(in_session_spawn_text(record))
        agent_hint = " --agent-id <agentId>" if chosen_name == "claude_subagent" else ""
        print(
            f"next: give a fresh subagent the packet and workdir, then run "
            f"`ai-task worker-done {run_id} --outcome success|failure|limited"
            f"{agent_hint} --final-file <path>`"
        )
        return

    prompt_input = backend_input(chosen_backend, prompt)
    stdin = subprocess.PIPE if prompt_input is not None else None
    # Capture the real backend exit code for this detached run. Once we
    # return the child reparents to init, so no ai-task process can waitpid it — its
    # completion is observed only by the orphan reaper, which previously defaulted
    # every clean detached run to needs_recovery/exit_code unknown. On POSIX, wrap the
    # backend in a tiny shell that writes its exit code to an `exit_status` sidecar in
    # the run dir before exiting; the reaper reads it to finalize needs_review (0) /
    # failed (nonzero) with the true code. The wrapper writes THEN exits, so a gone
    # pid guarantees the sidecar is already flushed (no race). Windows keeps the raw
    # command and no sidecar, so the reaper falls back to needs_recovery there.
    exit_status_path: Path | None = None
    launch_command = command
    if os.name != "nt":
        exit_status_path = run_dir / "exit_status"
        launch_command = [
            "/bin/sh",
            "-c",
            'rc=0; "$@" || rc=$?; printf %s "$rc" > "$0"; exit "$rc"',
            str(exit_status_path),
            *command,
        ]
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            launch_command,
            cwd=run_cwd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            start_new_session=(os.name != "nt"),
            env=backend_env(chosen_backend, root=root),
        )
        if prompt_input is not None and process.stdin is not None:
            process.stdin.write(prompt_input.encode("utf-8"))
            process.stdin.close()
        record["pid"] = process.pid
    # Mark the run detached so the reaper knows to read the sidecar and stop/pause/
    # resume signal the wrapper's process group (its recorded pid is the shell).
    record["detached"] = True
    if exit_status_path is not None:
        record["exit_status_path"] = str(exit_status_path.relative_to(root))
    # Persist the pre-launch quota snapshot, wave classification, and Size on the run
    # record so the orphan reaper can pair them with the post snapshot it takes when
    # it observes this detached run finish, finalizing a high-confidence cost sample.
    # Only meaningful for quota-gated launches; harmless otherwise.
    record["telemetry_pre_quota"] = telemetry_pre_quota
    record["telemetry_sample_kind"] = telemetry_sample_kind
    record["telemetry_size"] = task.size
    save_state(root, state)
    # Quota telemetry: a detached run is still in flight, so its
    # post-launch quota delta and diffstat are not yet known — record a partial
    # launch sample (pre snapshot + reservation) marked lifecycle=launched. The
    # authoritative completion sample (pre+post) is written later by the orphan
    # reaper when it observes this run finish.
    record_quota_telemetry(
        root=root,
        policy=policy,
        run=record,
        task=task,
        backend=chosen_name,
        backend_config=chosen_backend,
        pre_quota=telemetry_pre_quota,
        exit_status="launched",
        sample_kind=telemetry_sample_kind,
        capture_post=False,
        capture_diffstat=False,
    )
    print(f"Started {run_id}")
    print(f"backend: {chosen_name}")
    if model_info_text(record):
        print(f"model: {model_info_text(record)}")
    print(f"pid: {record['pid']}")
    print(f"packet: {packet.relative_to(root)}")
    if wt_rel:
        print(f"worktree: {wt_rel} (branch {wt_branch})")


def status(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    policy = read_policy(root, args.policy)
    state = load_state(root)
    snapshot = build_status_snapshot(
        root,
        policy,
        state,
        task_id=getattr(args, "task", None),
    )
    save_state(root, state)
    if getattr(args, "require_report", False):
        # Retired: a task report is written on demand, so a missing one
        # is not a gap. The flag stays accepted so existing scripts keep running.
        print(
            "status --require-report is retired: task reports are written on demand, "
            "so status no longer checks them",
            file=sys.stderr,
        )

    if getattr(args, "json", False):
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return

    summary = snapshot.get("summary", {})
    if summary:
        recovery_part = (
            f"needs_recovery={summary.get('needs_recovery_count', 0)} "
            if summary.get("needs_recovery_count", 0)
            else ""
        )
        print(
            "Summary: "
            f"running={summary.get('running_count', 0)} "
            f"failed={summary.get('failed_total', 0)} "
            f"needs_review={summary.get('needs_review_count', 0)} "
            f"{recovery_part}"
            f"leased={len(summary.get('leased_task_ids', []))}"
        )
        blocked = summary.get("blocked_by_deps", [])
        if blocked:
            print("Blocked by dependencies:")
            for item in blocked:
                print(
                    f"- {item.get('id')}: waiting for {', '.join(item.get('waiting_for', []))}"
                )
    cycles = snapshot.get("dependency_cycles", [])
    if cycles:
        print("Dependency cycles (fix BACKLOG.md):")
        for cycle in cycles:
            print(f"- {cycle}")

    print_operator_alerts(snapshot)
    print_quota_status_summary(root, policy)

    runs = snapshot.get("runs", [])
    if not runs:
        print("No runs.")
    else:
        for run in runs:
            signals = run.get("signals", [])
            signal_text = f"  signals: {', '.join(signals)}" if signals else ""
            pid_note = ""
            alive = run.get("pid_alive")
            if alive is False:
                pid_note = "  pid: not alive"
            elif alive is True:
                pid_note = "  pid: alive"
            idle_note = ""
            idle_val = run.get("idle_seconds")
            if idle_val is not None:
                idle_note = f"  idle: {idle_val}s"
            model_text = model_info_text(run)
            model_note = f"  model: {model_text}" if model_text else ""
            print(
                f"{run.get('id')}  {run.get('status')}  {run.get('task_id')}  {run.get('backend')}"
                f"{model_note}{signal_text}{pid_note}{idle_note}"
            )
            if run.get("status_note"):
                print(f"  note: {run.get('status_note')}")
            if run.get("status") == "waiting_quota":
                # Active wait state, not a failed verdict.
                remaining = run.get("resume_attempts_remaining")
                window = run.get("quota_window") or "n/a"
                print(
                    f"  waiting_quota: resume_after={run.get('resume_after') or 'unknown'}"
                    f"  window={window}  attempts_remaining={remaining}"
                )
                print(
                    "  note: active wait (not failed); "
                    "use `wait-runs --resume-on-quota` to auto-resume after reset"
                )
            if run.get("status") == "needs_recovery":
                changes = str(run.get("uncommitted_changes") or "(no diff)")
                first = changes.splitlines()[0] if changes else "(no diff)"
                worktree = run.get("worktree_path") or "main working tree"
                print(f"  recover: re-run {run.get('task_id')} in {worktree}")
                print(f"  uncommitted: {first}")
    cooldowns = snapshot.get("backend_cooldowns", {})
    if cooldowns:
        print("\nBackend cooldowns:")
        for name, info in cooldowns.items():
            until = info.get("cooldown_until", "?")
            active = "active" if info.get("active") else "expired (probe on next run)"
            print(f"- {name}: {info.get('reason')} until {until} [{active}]")
    next_eligible = snapshot.get("backlog", {}).get("next_eligible")
    if next_eligible:
        print(
            f"\nNext eligible: {next_eligible.get('id')} "
            f"[{next_eligible.get('priority')}/{next_eligible.get('size')}] "
            f"{next_eligible.get('title')}"
        )


def wait_runs(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    interval = float(args.interval)
    timeout = float(args.timeout)
    if interval <= 0:
        die("--interval must be greater than zero")
    if timeout < 0:
        die("--timeout must be zero or positive")

    policy = read_policy(root, args.policy)
    resume_on_quota = bool(getattr(args, "resume_on_quota", False))
    deadline = time.monotonic() + timeout
    while True:
        state = load_state(root)
        snapshot = build_status_snapshot(root, policy, state)
        # Auto-resume pass (opt-in): for each target run that is waiting_quota and
        # whose resume_after has passed, probe Claude and re-launch the same packet
        # in the same worktree, reusing its lease. Each call consumes
        # at most one attempt; a failed probe re-arms, an exhausted budget leaves the
        # run waiting_quota so the loop cannot wake/retry forever.
        if resume_on_quota:
            target_ids = set(args.run_ids)
            for run_id, run in state.get("runs", {}).items():
                if run_id not in target_ids:
                    continue
                if run.get("status") != "waiting_quota":
                    continue
                if quota_resume_attempts_used(run) >= quota_resume_max_attempts(policy):
                    continue
                if not resume_after_is_due(run.get("resume_after")):
                    continue
                resume_quota_run(root, state, policy, run)
            snapshot = build_status_snapshot(root, policy, state)
        save_state(root, state)
        rows, missing = wait_run_rows(snapshot, list(args.run_ids))
        if missing:
            if getattr(args, "json", False):
                emit_wait_runs_json(ok=False, rows=rows, missing=missing, timeout=False)
            else:
                print_wait_run_rows(rows)
            die(f"missing run id(s): {', '.join(missing)}")
        active = [row for row in rows if row.get("status") in ACTIVE_WAIT_RUN_STATUSES]
        # Without --resume-on-quota a waiting_quota run is still an active wait, but
        # there is nothing to drive it to completion here — surface a budget-exhausted
        # or non-resumable waiting_quota run as inactive so the caller does not block
        # forever (the resume loop, when enabled, owns re-launch).
        if not resume_on_quota:
            active = [row for row in active if row.get("status") != "waiting_quota"]
        else:
            # A waiting_quota run with no remaining auto-resume budget will never be
            # re-launched; stop treating it as active so wait-runs can exit.
            active = [
                row
                for row in active
                if not (
                    row.get("status") == "waiting_quota"
                    and (row.get("resume_attempts_remaining") or 0) <= 0
                )
            ]
        if not active:
            if getattr(args, "json", False):
                emit_wait_runs_json(ok=True, rows=rows, missing=[], timeout=False)
            else:
                print_wait_run_rows(rows)
            return
        if time.monotonic() >= deadline:
            if getattr(args, "json", False):
                emit_wait_runs_json(ok=False, rows=rows, missing=[], timeout=True)
            else:
                print_wait_run_rows(rows)
            die(
                f"timeout waiting for run id(s): {', '.join(str(row.get('id')) for row in active)}"
            )
        sleep_for = min(interval, max(0.0, deadline - time.monotonic()))
        if sleep_for > 0:
            time.sleep(sleep_for)


def parallel_plan_cmd(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    policy = read_policy(root, getattr(args, "policy", None))
    state = load_state(root)
    tasks = parse_backlog(root)
    # parallel-plan schedules headless agent waves — an owner-only (Agent: human) task
    # can never be a wave member, so autonomous selection always excludes it.
    eligible = eligible_tasks(
        tasks, state, policy, autonomous=True, extra_done_ids=archived_done_ids(root)
    )
    owner_only_note = format_owner_only_remaining(tasks)
    if owner_only_note:
        print(owner_only_note, file=sys.stderr)
    batch_size, batch_reasoning = resolve_wave_batch_size(
        explicit_batch=args.batch,
        auto_batch=getattr(args, "auto_batch", False),
        policy=policy,
        eligible_count=len(eligible),
    )
    selected = eligible[:batch_size]
    if not selected:
        die("no eligible tasks for parallel-plan")
    analysis = analyze_parallel_batch(root, selected, policy, state)
    analysis["batch_size"] = batch_size
    analysis["eligible_count"] = len(eligible)
    analysis["batch_reasoning"] = batch_reasoning
    if args.json:
        print(json.dumps(analysis, indent=2, ensure_ascii=False))
        return
    print(f"strategy: {analysis['strategy']}")
    for line in analysis["reasoning"]:
        print(f"- {line}")
    print("waves:")
    for wave in analysis["waves"]:
        print(f"  - {', '.join(wave)}")
    edges = analysis.get("collision_edges") or []
    if edges:
        print("collisions:")
        for edge in edges:
            pair = " x ".join(edge["tasks"])
            print(f"  - {pair}: {edge['reason']}")
    if analysis.get("ask_user"):
        print(f"ask_user: {analysis.get('ask_reason')}")


def scenario_check_cmd(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    policy = read_policy(root)
    max_stale = getattr(args, "max_stale_days", None)
    ok, reason = check_bulk_scenario_confirmed(
        root, max_stale_days=max_stale, policy=policy
    )
    if getattr(args, "json", False):
        choice, at_raw = find_latest_delivery_scenario(root)
        print(
            json.dumps(
                {"ok": ok, "reason": reason, "choice": choice, "at": at_raw},
                ensure_ascii=False,
            )
        )
    else:
        print(f"{'OK' if ok else 'BLOCKED'}: {reason}")
    if not ok:
        raise SystemExit(1)


def decision_log_cmd(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    signals: dict[str, Any] = {}
    if getattr(args, "signals_json", None):
        try:
            signals = json.loads(args.signals_json)
        except json.JSONDecodeError as exc:
            die(f"invalid --signals-json: {exc}")
    task_ids = []
    if getattr(args, "task_ids", None):
        task_ids = [part.strip() for part in args.task_ids.split(",") if part.strip()]
    explicit_run_ids: list[str] = []
    if getattr(args, "run_ids", None):
        explicit_run_ids = [
            part.strip() for part in args.run_ids.split(",") if part.strip()
        ]
    state = load_state(root)
    run_ids = resolve_decision_run_ids(state, task_ids, explicit_run_ids)
    entry = new_decision_entry(
        phase=args.phase,
        choice=args.choice,
        task_ids=task_ids,
        run_ids=run_ids,
        signals=signals,
        reason=args.reason,
    )
    if str(args.phase).lower() == "parallel":
        policy = read_policy(root, getattr(args, "policy", None))
        override_info = detect_parallel_plan_override(root, entry, policy, state)
        if override_info:
            merge_parallel_override_signals(entry, override_info)
    append_decision(root, entry)
    if args.json:
        print(json.dumps(entry, indent=2, ensure_ascii=False))
    else:
        print(f"recorded decision {entry['id']} ({entry['phase']} / {entry['choice']})")


def decision_result_cmd(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    if args.result not in {"good", "bad", "unknown", "pending"}:
        die("result must be good, bad, unknown, or pending")
    entries = read_decisions(root)
    target: dict[str, Any] | None = None
    if args.decision_id:
        for entry in reversed(entries):
            if entry.get("id") == args.decision_id:
                target = entry
                break
    else:
        for entry in reversed(entries):
            if entry.get("result") == "pending":
                target = entry
                break
    if not target:
        die("decision not found")
    run_ids = target.get("run_ids") or []
    if not isinstance(run_ids, list):
        run_ids = []
    run_ids = [str(r) for r in run_ids if r]
    if args.result == "good" and not run_ids and not getattr(args, "force", False):
        print(
            "warning: marking good with empty run_ids — use --force to acknowledge",
            file=sys.stderr,
        )
    target["result"] = args.result
    target["reflection"] = (args.reflection or "").strip()
    target["reflected_at"] = now()
    path = decisions_path(root)
    lines = []
    for entry in entries:
        if entry.get("id") == target.get("id"):
            lines.append(json.dumps(target, ensure_ascii=False))
        else:
            lines.append(json.dumps(entry, ensure_ascii=False))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(f"updated {target['id']} -> {args.result}")


def decision_check_overrides_cmd(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    policy = read_policy(root, getattr(args, "policy", None))
    since: int | None = None
    if getattr(args, "since", None):
        since = max(1, int(parse_duration_spec(args.since).total_seconds() // 86400))
    apply = not getattr(args, "dry_run", False)
    report = check_parallel_overrides(root, policy, since_days=since, apply=apply)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    window = f"last {since} days" if since is not None else "all time"
    print(f"parallel decisions ({window}): {report['checked_parallel']} checked")
    print(f"overrides detected: {report['override_count']}")
    if apply:
        print(f"signals updated: {report['updated']}")
    else:
        print("dry-run: no files changed")
    for item in report.get("overrides", [])[:20]:
        print(
            f"- {item.get('decision_id')}: logged {item.get('logged_choice')} "
            f"vs plan {item.get('plan_strategy')} -> {item.get('suggest_choice')}"
        )


def decision_reflect_cmd(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    state = load_state(root)
    policy = read_policy(root, getattr(args, "policy", None))
    since: int | None = None
    if getattr(args, "since", None):
        since = max(1, int(parse_duration_spec(args.since).total_seconds() // 86400))
    analytics = decision_analytics(root, since_days=since)
    suggestions, strict_violation, any_empty_run_ids = build_reflect_suggestions(
        state, analytics["entries"], root=root, policy=policy
    )
    payload = {
        "analytics": analytics,
        "suggestions": suggestions,
        "strict_violation": strict_violation,
    }
    if any_empty_run_ids:
        print("warning: no run_ids — manual review required", file=sys.stderr)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        if getattr(args, "strict", False) and strict_violation:
            raise SystemExit(1)
        return
    machine_block = analytics.get("machine")
    machine_note = ""
    if isinstance(machine_block, dict) and machine_block.get("total"):
        machine_note = f", {machine_block.get('total', 0)} machine rows"
    print(
        f"decisions: {analytics['total']} total, "
        f"{analytics['pending']} judgment pending{machine_note}"
    )
    for item in suggestions[:10]:
        suffix = " (no run_ids)" if item.get("empty_run_ids") else ""
        choice_hint = ""
        if item.get("parallel_plan_override"):
            choice_hint = f"; rename choice to {item.get('suggest_choice', 'override_parallel_plan')}"
        print(
            f"- {item['decision_id']}: {item['choice']}{choice_hint} -> suggest "
            f"{item['suggested_result']}{suffix} ({item['reason']})"
        )
    if getattr(args, "strict", False) and strict_violation:
        die("reflect --strict: pending would be good without run_ids on journal entry")


def decision_ingest_cmd(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    since = None
    if getattr(args, "since", None):
        since = max(1, int(parse_duration_spec(args.since).total_seconds() // 86400))
    apply = bool(getattr(args, "apply", False))
    confirm = bool(getattr(args, "confirm", False))
    if apply and not confirm:
        die("--apply requires --confirm (never silent backfill)")
    proposals = propose_decision_ingest_stubs(root, since_days=since)
    if apply:
        appended: list[dict[str, Any]] = []
        for stub in proposals:
            appended.append(apply_ingest_stub(root, stub))
        if args.json:
            print(
                json.dumps(
                    {"appended": appended, "count": len(appended)},
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            rel = decisions_path(root).relative_to(root)
            print(f"appended {len(appended)} ingest stub(s) to {rel}")
            for entry in appended:
                source_run_id = entry.get("signals", {}).get("source_run_id", "")
                print(
                    f"  {entry['id']} source_run_id={source_run_id} "
                    f"({entry['phase']} / {entry['choice']})"
                )
        return
    if args.json:
        print(
            json.dumps(
                {"proposed": proposals, "count": len(proposals), "dry_run": True},
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    if not proposals:
        print(
            "no ingest stubs proposed (journal may already cover state.json anomalies)"
        )
        return
    print(
        f"proposed {len(proposals)} ingest stub(s) (dry-run; use --apply --confirm to append)"
    )
    for stub in proposals:
        source_run_id = stub.get("signals", {}).get("source_run_id", "")
        print(
            f"  source_run_id={source_run_id} {stub['phase']}/{stub['choice']} "
            f"run_ids={stub.get('run_ids')}"
        )
        print(json.dumps(stub, ensure_ascii=False))


def decision_analytics_cmd(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    since = None
    if getattr(args, "since", None):
        since = max(1, int(parse_duration_spec(args.since).total_seconds() // 86400))
    analytics = decision_analytics(root, since_days=since)
    fmt = getattr(args, "format", "text") or "text"
    # --trend prints only the value-trend read (text or JSON).
    if getattr(args, "trend", False):
        trend = analytics.get("value_trend")
        if not isinstance(trend, dict):
            print("no value trend (state.json absent — no delivery runs to roll up)")
            return
        if fmt == "json" or args.json:
            print(json.dumps(trend, indent=2, ensure_ascii=False))
            return
        print("\n".join(format_value_trend_markdown(trend)).lstrip("\n"))
        return
    if fmt == "json" or args.json:
        print(json.dumps(analytics, indent=2, ensure_ascii=False))
        return
    if fmt in {"md", "html"}:
        md_path, html_path = write_factual_decision_reports(
            root, analytics, since_days=since
        )
        if fmt == "md":
            print(md_path.read_text(encoding="utf-8"), end="")
        print(f"Wrote {md_path.relative_to(root)}")
        print(f"Wrote {html_path.relative_to(root)}")
        return
    print(
        f"total={analytics['total']} "
        f"judgment={analytics.get('judgment_total', analytics['total'])} "
        f"pending(judgment)={analytics['pending']}"
    )
    machine = analytics.get("machine")
    if isinstance(machine, dict) and machine.get("total"):
        print(
            f"machine rows={machine.get('total', 0)} "
            f"pending={machine.get('pending', 0)} "
            f"events={machine.get('events', machine.get('total', 0))} "
            "(telemetry, excluded from judgment metrics)"
        )
    by_operator = analytics.get("by_operator")
    if isinstance(by_operator, dict) and by_operator:
        print(
            "operators: "
            + " ".join(f"{name}={count}" for name, count in sorted(by_operator.items()))
        )
    for phase, counts in sorted(analytics["by_phase"].items()):
        print(f"{phase}: {counts}")
    delivery = analytics.get("delivery")
    if isinstance(delivery, dict):
        print(
            f"delivery runs={delivery.get('runs_in_window', 0)} rework_rate={delivery.get('rework_rate')}"
        )
    report = analytics.get("report")
    if isinstance(report, dict) and report.get("warnings"):
        print(f"warnings: {report['warnings']}")
    slo_violations = analytics.get("slo_violations", [])
    for v in slo_violations:
        print(f"SLO ALERT [{v['code']}]: {v['message']}")
        print(f"  -> {v['recommendation']}")


def retro_cmd(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    since: int | None = None
    if getattr(args, "since", None):
        since = max(1, int(parse_duration_spec(args.since).total_seconds() // 86400))
    reflect_args = argparse.Namespace(
        repo=args.repo,
        since=getattr(args, "since", None),
        json=False,
    )
    try:
        decision_reflect_cmd(reflect_args)
    except SystemExit:
        pass
    analytics = decision_analytics(root, since_days=since)
    md_path, html_path = write_factual_decision_reports(
        root, analytics, since_days=since
    )
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    packet_dir = app_path(root) / "packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_path = packet_dir / f"retro-{stamp}.md"
    packet_path.write_text(
        retro_packet_text(
            root,
            analytics,
            since_days=since,
            factual_md=md_path,
            factual_html=html_path,
            stamp=stamp,
        ),
        encoding="utf-8",
    )
    print(f"Factual: {md_path.relative_to(root)}")
    print(f"Factual: {html_path.relative_to(root)}")
    print(f"Packet: {packet_path.relative_to(root)}")
    credibility = retro_journal_credibility_note(analytics)
    if credibility:
        print(credibility)
    print(
        "Next: open Cursor chat, load ai-task-retro, answer blocking questions, confirm new backlog task ids."
    )
    if getattr(args, "open", False):
        print(f"file://{md_path.resolve()}")
        print(f"file://{html_path.resolve()}")
        print(f"file://{packet_path.resolve()}")


def verdict_cmd(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    phase_started = now()
    state = load_state(root)
    run_record = find_run(state, args.run_id)
    verdict = args.verdict.strip().lower()
    if verdict not in VERDICT_VALUES:
        die(f"invalid verdict: {verdict} (use {', '.join(VERDICT_VALUES)})")
    if verdict == "approve":
        # Merge-back gate: with [scope_guard] mode = "require_ack",
        # unacknowledged out-of-scope backlog edits block the approve verdict.
        enforce_scope_guard_ack(
            root,
            read_policy(root, getattr(args, "policy", None)),
            run_record,
            args.run_id,
            action="verdict approve",
        )
    run_record["verdict"] = verdict
    run_record["verdict_at"] = now()
    reflection = (getattr(args, "reflection", "") or "").strip()
    if reflection:
        run_record["verdict_reflection"] = reflection
    record_phase_timing(run_record, "verdict", phase_started)
    save_state(root, state)
    # Level B: ai-task is the finalizer, so it sends the authoritative
    # OUTCOME ping (verify result + verdict + changed files) now that the verdict
    # is recorded — the Stop hook could not, it fires before verify/verdict exist.
    # notify_run_outcome stamps run_record["outcome_notified"] for dedupe:
    # a run that already pinged on a terminal-failure finalize path
    # skips here, and we persist the flag so a re-run verdict cannot re-ping.
    notify_run_outcome(root, state, run_record)
    if run_record.get("outcome_notified"):
        save_state(root, state)
    if verdict in {"rework", "split", "escalate"}:
        task_id = str(run_record.get("task_id", "") or "")
        maybe_auto_log_anomaly(
            root,
            read_policy(root, getattr(args, "policy", None)),
            phase="verdict",
            choice=verdict,
            task_ids=[task_id] if task_id else [],
            run_ids=[args.run_id],
            state=state,
            signals={"verdict": verdict, "run_status": run_record.get("status")},
            reason=f"verdict {verdict}",
        )
    print(f"verdict {verdict} recorded for {args.run_id}")
    if reflection:
        print(f"reflection: {reflection}")


def signal_run(args: argparse.Namespace, sig: signal.Signals, next_status: str) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    state = load_state(root)
    run_record = find_run(state, args.run_id)
    if run_record.get("in_session"):
        # No process belongs to an in-session run: stop closes the
        # record and frees the task; pause and resume happen in the host session.
        if next_status != "stopped":
            die(
                "in-session run has no process to pause or resume; control the "
                "subagent in the teamlead session"
            )
        if run_record.get("status") not in {"running", "paused"}:
            die(f"run {args.run_id} is {run_record.get('status')}, not active")
        run_record["status"] = "stopped"
        run_record["finished_at"] = now()
        run_record["status_note"] = "in-session run stopped by the operator"
        release_task_lease(state, str(run_record.get("task_id", "")))
        release_quota_reservation(state, str(run_record.get("id", "")))
        save_state(root, state)
        print(f"stopped: {args.run_id}")
        return
    pid = run_record.get("pid")
    if not isinstance(pid, int):
        die("run has no pid")
    try:
        # A detached run's recorded pid is the wrapper shell (a new-session group
        # leader), not the backend; signal its whole process group so
        # stop/pause/resume still reach the backend. Non-detached (--wait) runs keep
        # the byte-identical single-pid signal.
        if run_record.get("detached") and hasattr(os, "killpg"):
            os.killpg(os.getpgid(pid), sig)
        else:
            os.kill(pid, sig)
    except OSError as exc:
        die(f"failed to signal pid {pid}: {exc}")
    run_record["status"] = next_status
    run_record["updated_at"] = now()
    save_state(root, state)
    print(f"{next_status}: {args.run_id}")


def pause_run(args: argparse.Namespace) -> None:
    sig = getattr(signal, "SIGSTOP", None)
    if sig is None:
        die(
            "pause is not supported on this platform; use stop or backend-native controls"
        )
    signal_run(args, sig, "paused")


def resume_run(args: argparse.Namespace) -> None:
    sig = getattr(signal, "SIGCONT", None)
    if sig is None:
        die("resume is not supported on this platform; restart with ai-task run")
    signal_run(args, sig, "running")


def in_session_spawn_text(record: dict[str, Any]) -> str:
    """The line telling the teamlead how to start the subagent."""
    model = record.get("requested_model")
    effort = record.get("requested_effort")
    if not model and not effort:
        return ""
    parts = [f"model {model}"] if model else []
    if effort:
        parts.append(f"effort {effort}")
    source = record.get("requested_from") or "policy"
    return (
        f"subagent: {', '.join(parts)} (from [{source}]); pass them as the Agent "
        "tool's model and effort"
    )


def in_session_model_record(
    run_record: dict[str, Any], *, agent_id: str, model: str, effort: str
) -> tuple[dict[str, Any], str]:
    """What worker-done records as the subagent's model and effort, and a note.

    The subagent's own transcript is the evidence: Claude Code writes the model
    that answered and the effort of every turn there. Without it the teamlead's
    report is taken, and without a report the requested values, marked as such.
    """
    requested_model = run_record.get("requested_model")
    requested_effort = run_record.get("requested_effort")
    note = ""
    if agent_id:
        path = subagent_transcript_path(agent_id)
        served = subagent_transcript_model(path) if path else None
        if served:
            result: dict[str, Any] = {
                "model": served["model"],
                "effort": served["effort"],
                "model_source": "transcript",
                "agent_id": agent_id,
            }
            if len(served["models_seen"]) > 1:
                result["models_seen"] = served["models_seen"]
            mismatch = []
            if not model_matches_request(served["model"], requested_model):
                mismatch.append(f"model {served['model']} instead of {requested_model}")
            if requested_effort and served["effort"] != requested_effort:
                mismatch.append(f"effort {served['effort']} instead of {requested_effort}")
            result["model_mismatch"] = "; ".join(mismatch) or None
            return result, result["model_mismatch"] or ""
        note = f"no readable transcript for subagent {agent_id}"
    if model or effort:
        return {
            "model": model or None,
            "effort": effort or None,
            "model_source": "reported",
            "agent_id": agent_id or None,
            "model_mismatch": None,
        }, note
    return {
        "model": requested_model,
        "effort": requested_effort,
        "model_source": "requested" if requested_model or requested_effort else None,
        "agent_id": agent_id or None,
        "model_mismatch": None,
    }, note


def worker_done_cmd(args: argparse.Namespace) -> None:
    """`ai-task worker-done` - record an in-session subagent's outcome.

    The in-session executor launches no process, so nothing observes the work
    finish. The teamlead reports what its subagent returned; this finalizes the
    run through the same path as a detached run, so verify, review and verdict
    see an ordinary needs_review, failed or quota_blocked record.
    """
    root = selected_root(args.repo)
    require_initialized(root)
    policy = read_policy(root, args.policy)
    state = load_state(root)
    run_record = find_run(state, args.run_id)
    if not run_record.get("in_session"):
        die(
            f"run {args.run_id} is not an in-session run; headless runs finalize "
            "when their process exits"
        )
    # needs_recovery is accepted so a worker that reports after the timeout
    # reaped its run still lands its outcome instead of losing the work.
    if run_record.get("status") not in {"running", "paused", "needs_recovery"}:
        die(
            f"run {args.run_id} is {run_record.get('status')}, not awaiting an "
            "in-session worker"
        )
    final_rel = str(
        run_record.get("final_message") or Path(str(run_record["run_dir"])) / "final.md"
    )
    final_path = root / final_rel
    if args.final_file:
        source = Path(args.final_file).expanduser()
        if not source.is_absolute() and not source.is_file():
            # A path as `run` prints it relative to the repo, under --repo too.
            source = root / source
        if not source.is_file():
            die(f"final answer file not found: {args.final_file}")
        if source.resolve() != final_path.resolve():
            final_path.write_text(
                source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
            )
    elif args.final_text:
        final_path.write_text(args.final_text, encoding="utf-8")
    if args.outcome == "success" and not final_path.is_file():
        die(
            "a successful worker needs its final answer: pass --final-file or "
            f"--final-text, or have the subagent write {final_rel}"
        )
    run_record["final_message"] = final_rel if final_path.is_file() else None
    model_fields, model_note = in_session_model_record(
        run_record, agent_id=args.agent_id, model=args.model, effort=args.effort
    )
    run_record.update(model_fields)
    if args.note:
        run_record["worker_note"] = args.note
    limited = args.outcome == "limited"
    if limited:
        set_backend_cooldown(
            state,
            str(run_record.get("backend", "")),
            policy,
            "usage limit reported by in-session worker",
            str(run_record.get("id", "")),
            from_active_attempt=True,
        )
    # A late report on a reaped run must not free the lease of a newer run of
    # the same task: finalize releases leases by task id.
    task_id = str(run_record.get("task_id", ""))
    lease = state.get("leases", {}).get(task_id)
    foreign_lease = (
        lease if isinstance(lease, dict) and lease.get("run_id") != run_record.get("id") else None
    )
    detail = f": {args.note}" if args.note else ""
    note = {
        "success": "in-session worker reported success; verify, review and verdict next",
        "failure": f"in-session worker reported failure{detail}",
        "limited": (
            f"in-session worker hit a usage limit{detail}; backend cooldown active. "
            "Wait for the window or explicitly choose another executor. No task "
            "failure consumed."
        ),
    }[args.outcome]
    finalize_detached_run(
        root,
        state,
        run_record,
        0 if args.outcome == "success" else 1,
        policy,
        note=note,
        limited=limited,
    )
    if foreign_lease is not None:
        state.setdefault("leases", {})[task_id] = foreign_lease
    save_state(root, state)
    print(f"{run_record['status']}: {args.run_id}")
    if model_info_text(run_record):
        print(f"model: {model_info_text(run_record)} ({run_record.get('model_source')})")
    if model_note:
        print(f"warning: {model_note}")
    if run_record.get("final_message"):
        print(f"final answer: {run_record['final_message']}")
    print(f"note: {run_record['status_note']}")


def executor_cmd(args: argparse.Namespace) -> None:
    """`ai-task executor` - which executor mode a batch uses, and whether to ask."""
    root = selected_root(args.repo)
    require_initialized(root)
    policy = read_policy(root, args.policy)
    host, host_reason = teamlead_host()
    choice = executor_choice(
        policy,
        tasks=args.tasks,
        waves=args.waves,
        named=args.named,
        no_questions=args.no_questions,
        host=host,
    )
    choice["host"] = host
    choice["host_reason"] = host_reason
    if choice["mode"] == "in_session" and not choice["in_session_backend"]:
        choice["reason"] += (
            f"; {host_reason}: choose claude_subagent or codex_subagent explicitly"
        )
    if args.json:
        print(json.dumps(choice, ensure_ascii=False, indent=2))
        return
    print(f"mode: {choice['mode']} (source: {choice['source']})")
    if choice["ask"]:
        print(f"ask: yes, recommend {choice['recommended']}")
    else:
        print("ask: no")
    if choice["in_session_backend"]:
        print(f"in-session backend: {choice['in_session_backend']}")
    print(f"reason: {choice['reason']}")


def supersede_run(args: argparse.Namespace) -> None:
    """Close a stale run record delivered by a later run.

    Flips a lingering ``needs_recovery``/``failed`` record to a terminal
    ``superseded`` status so it stops counting toward ``needs_recovery_count``,
    releasing any lingering task lease and quota reservation. Refuses to touch a
    still-active run (running/paused) — stop it first.
    """
    root = selected_root(args.repo)
    require_initialized(root)
    state = load_state(root)
    run_record = find_run(state, args.run_id)
    prev = str(run_record.get("status", ""))
    if prev in {"running", "paused"}:
        die(f"run {args.run_id} is {prev}; stop the run first")
    run_record["status"] = "superseded"
    run_record["superseded_at"] = now()
    if getattr(args, "by", None):
        run_record["superseded_by"] = args.by
    if getattr(args, "reason", None):
        run_record["status_note"] = args.reason
    release_task_lease(state, str(run_record.get("task_id", "")))
    release_quota_reservation(state, str(run_record.get("id", "")))
    save_state(root, state)
    print(f"Superseded {args.run_id} (was {prev})")


def note(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    entry = {
        "created_at": now(),
        "run_id": args.run_id,
        "task_id": getattr(args, "task_id", None) or "",
        "scope": args.scope,
        "message": args.message,
    }
    inbox = app_path(root) / "inbox.jsonl"
    with inbox.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    state = load_state(root)
    if args.run_id:
        run_record = find_run(state, args.run_id)
        run_record.setdefault("notes", []).append(entry)
        save_state(root, state)
    print(f"Recorded note in {inbox.relative_to(root)}")
    print(
        "Notes are not auto-injected into a running CLI process. Stop or start a new run to apply them."
    )


def verify_cmd(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    policy = read_policy(root, getattr(args, "policy", None))
    check_policy_baseline(root, policy, phase="verify")
    settings = verify_settings(policy)
    if not settings.get("enabled", True):
        print("verify disabled in policy")
        return

    if getattr(args, "skip", False):
        if not settings.get("allow_skip", False):
            die("verify skip is disabled (allow_skip = false in policy)")
        print("verify skipped")
        return

    phase_started = now()
    state = load_state(root)
    run_record: dict[str, Any] | None = None
    task: Task | None = None
    if args.run_id:
        run_record = find_run(state, args.run_id)
        tasks = parse_backlog(root)
        task = next(
            (item for item in tasks if item.id == run_record.get("task_id")), None
        )
    elif args.task_id:
        tasks = parse_backlog(root)
        task = next((item for item in tasks if item.id == args.task_id), None)
        if not task:
            die(f"task not found: {args.task_id}")
    else:
        die("provide --run-id or --task-id")

    profile_name, resolution = resolve_verify_profile(
        policy,
        task=task,
        run_record=run_record,
        cli_profile=getattr(args, "profile", None),
    )
    commands = verify_profile_commands(policy, profile_name)
    cwd = resolve_run_cwd(root, run_record) if run_record else root.resolve()

    print(f"verify profile: {profile_name} ({resolution})")
    warn_nested_shell_pipes(settings, profile_name, commands)
    if not commands:
        print("no commands in profile")
        if run_record and not args.dry_run:
            status = "passed"
            payload = {
                "profile": profile_name,
                "resolution": resolution,
                "status": status,
                "cwd": str(cwd),
                "generated_at": now(),
                "results": [],
                "require_before_review": bool(
                    settings.get("require_before_review", True)
                ),
            }
            run_dir = root / str(run_record["run_dir"])
            report_path = run_dir / "verify-report.md"
            write_verify_report(report_path, payload)
            report_rel = str(report_path.relative_to(root))
            run_record["verify_profile"] = profile_name
            run_record["verify_status"] = status
            run_record["verify_report"] = report_rel
            record_phase_timing(run_record, "verify", phase_started)
            save_state(root, state)
            print(f"verify {status}: {report_rel} (no commands)")
        return

    if args.dry_run:
        print("dry-run commands:")
        for command in commands:
            print(f"- {command}")
        return

    results = run_verify_commands(commands, cwd=cwd, dry_run=False)
    failed = [item for item in results if item.get("exit_code", 1) != 0]
    status = "passed" if not failed else "failed"
    payload = {
        "profile": profile_name,
        "resolution": resolution,
        "status": status,
        "cwd": str(cwd),
        "generated_at": now(),
        "results": results,
        "require_before_review": bool(settings.get("require_before_review", True)),
    }

    report_rel = ""
    if run_record:
        run_dir = root / str(run_record["run_dir"])
        report_path = run_dir / "verify-report.md"
        write_verify_report(report_path, payload)
        report_rel = str(report_path.relative_to(root))
        run_record["verify_profile"] = profile_name
        run_record["verify_status"] = status
        run_record["verify_report"] = report_rel
        record_phase_timing(run_record, "verify", phase_started)
        save_state(root, state)
        print(f"verify {status}: {report_rel}")
        if status == "failed":
            task_id = str(run_record.get("task_id", "") or "")
            maybe_auto_log_anomaly(
                root,
                policy,
                phase="verify",
                choice="verify_failed",
                task_ids=[task_id] if task_id else [],
                run_ids=[args.run_id],
                state=state,
                signals={
                    "profile": profile_name,
                    "resolution": resolution,
                    "failed_commands": [
                        item.get("command") for item in failed if item.get("command")
                    ],
                },
                reason=f"verify failed ({profile_name})",
            )
    else:
        report_path = app_path(root) / "verify-last.md"
        write_verify_report(report_path, payload)
        print(f"verify {status}: {report_path.relative_to(root)}")

    if failed:
        for item in failed:
            print(
                f"failed: {item.get('command')} (exit {item.get('exit_code')})",
                file=sys.stderr,
            )
        raise SystemExit(1)


def review(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    phase_started = now()
    policy = read_policy(root, getattr(args, "policy", None))
    state = load_state(root)
    run_record = find_run(state, args.run_id)
    codex_only = bool(getattr(args, "codex_only", False))
    if codex_only and getattr(args, "codex", None) is False:
        die("--codex-only and --no-codex contradict each other")
    task_id = str(run_record.get("task_id", "") or "")
    tasks = parse_backlog(root)
    task_matches = [task for task in tasks if task.id == task_id]
    task = task_matches[0] if task_matches else None
    verify_settings_block = verify_settings(policy)
    verify_required = verify_settings_block.get(
        "enabled", True
    ) and verify_settings_block.get("require_before_review", True)
    if not getattr(args, "dry_run", False) and not codex_only and verify_required:
        status = str(run_record.get("verify_status", "") or "")
        if status != "passed":
            die(
                f"run verify has not passed (ai-task verify {args.run_id}); "
                f"verify_status={status or 'unset'}"
            )
    review_dir = Path(root / str(run_record["run_dir"]))
    diff_cwd = resolve_run_cwd(root, run_record)
    registry = load_review_registry(root)
    changed_paths = collect_git_changed_paths(diff_cwd)
    stacks = detect_stacks_from_paths(changed_paths, registry)
    stacks |= detect_stacks_from_task_context(task, registry)
    resolved = resolve_review_skills(
        registry,
        stacks=stacks,
        task=task,
        run_record=run_record,
        policy=policy,
        root=root,
        changed_paths=changed_paths,
    )
    skills_path = review_dir / "review-skills.json"
    skills_path.write_text(
        json.dumps(resolved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if getattr(args, "dry_run", False):
        print(json.dumps(resolved, indent=2, ensure_ascii=False))
        return
    codex_summary = None
    if codex_review_enabled(policy, True if codex_only else getattr(args, "codex", None)):
        codex_summary = run_codex_review_pass(
            root,
            policy,
            run_record,
            run_dir=review_dir,
            run_cwd=diff_cwd,
            base=getattr(args, "codex_base", None),
            commit=getattr(args, "codex_commit", None),
        )
        run_record["codex_review"] = codex_summary
        print(codex_review_line(codex_summary))
    if codex_only:
        save_state(root, state)
        return
    prompt_path = review_dir / "review-packet.md"
    diff_text = collect_git_diff_summary(diff_cwd)
    packet_rel = ""
    matches = [t for t in tasks if t.id == task_id]
    if matches:
        packet_rel = str(
            (app_path(root) / "packets" / f"{task_id}.md").relative_to(root)
        )
    verify_rel = str(run_record.get("verify_report", "") or "")
    changed_list = "\n".join(f"- {path}" for path in changed_paths) or "- (none)"
    prompt = f"""# ai-task review packet

Run: {args.run_id}
Task: {task_id} {run_record.get("task_title")}
Backend: {run_record.get("backend")}
Model: {model_info_text(run_record) or "(not recorded)"}
Review gates: {", ".join(run_record.get("review_gates", [])) or "requested"}

## Artifacts

- Task packet: `{packet_rel or "(missing)"}`
- Verify report: `{verify_rel or "(run verify first)"}`
- Review skills: `{skills_path.relative_to(root)}`
- Load skill: **ai-task-reviewer** plus stacks: {", ".join(resolved.get("skills", [])) or "none"}

## Changed files (run cwd)

{changed_list}

## Diff stat

```text
{diff_text}
```

{codex_packet_section(codex_summary)}Produce `review-findings.md` in this run directory (see **ai-task-reviewer** skill).
Teamlead records `verdict` after review; do not approve from the implementer run alone.
"""
    prompt_path.write_text(prompt, encoding="utf-8")
    run_record["status"] = "needs_review"
    run_record["review_packet"] = str(prompt_path.relative_to(root))
    run_record["review_skills"] = resolved.get("skills", [])
    run_record["review_stack"] = resolved.get("stacks", [])
    run_record["review_skills_status"] = resolved.get("status")
    record_phase_timing(run_record, "review", phase_started)
    if args.run_id not in state.setdefault("review_queue", []):
        state["review_queue"].append(args.run_id)
    save_state(root, state)
    print(f"Created review packet: {prompt_path.relative_to(root)}")
    print(f"Review skills: {skills_path.relative_to(root)}")
    if resolved.get("status") == "none-detected":
        print(
            "review skills: no stack skill matched these files (none-detected); "
            "run built-in /code-review or extend the registry"
        )
    if resolved.get("missing_skills"):
        print(
            "review skills absent from skills/: "
            f"{', '.join(resolved['missing_skills'])} "
            "(fallback: engineering:code-review or built-in /code-review)"
        )


def prune_runs(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    state = load_state(root)
    refresh_runs(root, state, read_policy(root))

    older_than: dt.timedelta | None = None
    if args.older_than:
        older_than = parse_duration_spec(args.older_than)
    if args.cleanup_reports and older_than is None:
        die("--cleanup-reports requires --older-than")

    if not args.dry_run and not args.yes:
        die("refusing to prune without --yes (use --dry-run to preview)")

    run_ids, skipped_worktrees, healed_worktrees = select_prune_run_ids(
        state,
        root=root,
        run_id=args.run_id,
        older_than=older_than,
        keep_last=args.keep_last,
        include_failed=args.include_failed,
    )

    if skipped_worktrees:
        print("Skipped runs whose worktree still exists (merge and remove it first):")
        for run_id in skipped_worktrees:
            run = state["runs"][run_id]
            print(f"- {run_id} ({run.get('worktree_branch', '?')})")
    if healed_worktrees:
        print("Cleared stale worktree_path (directory already gone):")
        for run_id in healed_worktrees:
            print(f"- {run_id}")
        # Persist here as well: a healed record can be held back by --keep-last
        # or --older-than, and the early return below would drop the repair.
        if not args.dry_run:
            save_state(root, state)

    if not run_ids and not (args.cleanup_reports and older_than is not None):
        print("Nothing to prune.")
        return

    mode = "dry-run" if args.dry_run else "prune"
    if run_ids:
        # Dropping the record orphans any surviving ref, so name them first.
        # prune reports branches, it never deletes them.
        orphaned_branches = [
            (run_id, branch)
            for run_id in run_ids
            if (branch := run_branch_name(state["runs"][run_id]))
            and git_branch_exists(root, branch)
        ]
        if orphaned_branches:
            print(
                "Run branches left behind (delete with cleanup --remove-worktrees "
                "or git branch -d):"
            )
            for run_id, branch in orphaned_branches:
                print(f"- {run_id} ({branch})")
        print(f"{mode}: {len(run_ids)} run record(s)")
        for run_id in run_ids:
            run = state["runs"][run_id]
            task_id = run.get("task_id", "?")
            status = run.get("status", "?")
            print(f"- {run_id} ({task_id}, {status})")
            if not args.dry_run:
                remove_run_artifacts(root, state, run_id)

    report_paths: list[str] = []
    if args.cleanup_reports and older_than is not None:
        report_paths = prune_old_cleanup_reports(
            root, older_than=older_than, dry_run=args.dry_run
        )
        if report_paths:
            label = (
                "cleanup reports (dry-run)"
                if args.dry_run
                else "cleanup reports removed"
            )
            print(f"{label}: {len(report_paths)}")
            for rel in report_paths:
                print(f"- {rel}")

    if not args.dry_run:
        save_state(root, state)
        print("Prune complete.")
    elif run_ids or report_paths:
        print("Dry-run only; no files removed.")


def cleanup(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    cleanup_dir = app_path(root) / "cleanup"
    cleanup_dir.mkdir(parents=True, exist_ok=True)
    report = (
        cleanup_dir
        / f"cleanup-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    state = load_state(root)
    refresh_runs(root, state, read_policy(root))
    stale = [
        run_id
        for run_id, run in state.get("runs", {}).items()
        if run.get("status")
        in {
            "needs_review",
            "needs_recovery",
            "failed",
            "done",
            "dry_run",
            # Terminal and workless, but it can still own a worktree
            # from a detached launch — leaving it out would leak that worktree.
            "backend_unusable",
        }
    ]
    worktree_removals: list[dict[str, str]] = []
    if getattr(args, "remove_worktrees", False) and not args.dry_run:
        force_cleanup = bool(getattr(args, "force", False))
        for run_id in stale:
            run = state.get("runs", {}).get(run_id, {})
            worktree_path = str(run.get("worktree_path", "") or "")
            if not worktree_path:
                continue
            keep_reason = worktree_keep_reason(root, run, force=force_cleanup)
            if keep_reason:
                message = f"warning: skipped worktree for {run_id}: {keep_reason}"
                print(message)
                worktree_removals.append(
                    {
                        "run_id": run_id,
                        "worktree_path": worktree_path,
                        "error": message,
                    }
                )
                continue
            released = release_run_worktree(root, run, force=force_cleanup)
            entry = {
                "run_id": run_id,
                "worktree_path": worktree_path,
                "error": released["error"],
            }
            if released["branch_deleted"]:
                entry["branch_deleted"] = released["branch_deleted"]
            if released["branch_kept"]:
                entry["branch_kept"] = released["branch"]
                entry["branch_kept_reason"] = released["branch_kept"]
                print(
                    f"warning: kept branch {released['branch']} for {run_id}: "
                    f"{released['branch_kept']}; pass --force to delete it"
                )
            worktree_removals.append(entry)
        save_state(root, state)
    data = {
        "created_at": now(),
        "dry_run": args.dry_run,
        "stale_run_records": stale,
        "worktree_removals": worktree_removals,
        "message": "cleanup is conservative; it records candidates and never deletes source files automatically",
    }
    write_json(report, data)
    save_state(root, state)
    print(f"Cleanup report: {report.relative_to(root)}")
    if stale:
        print("Candidate run records:")
        for run_id in stale:
            print(f"- {run_id}")
    if worktree_removals:
        print("Worktree removals:")
        for item in worktree_removals:
            if not item["error"]:
                status = "removed"
            elif item["error"].startswith("warning: skipped"):
                status = "skipped"
            else:
                status = f"failed: {item['error']}"
            if item.get("branch_deleted"):
                status += f", branch {item['branch_deleted']} deleted"
            elif item.get("branch_kept"):
                status += f", branch {item['branch_kept']} kept"
            print(f"- {item['run_id']}: {status}")


def packet_refresh(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    policy = read_policy(root, args.policy)
    state = load_state(root)
    tasks = parse_backlog(root)
    matches = [task for task in tasks if task.id == args.task_id]
    if not matches:
        die(f"task not found in backlog: {args.task_id}")
    task = matches[0]
    backend_order = choose_backend_order(task, policy, args.backend, state, root)
    packet = generate_packet(
        root,
        task,
        policy,
        backend_order,
        state,
        include_notes=True,
        include_rework=True,
    )
    notes = pending_inbox_notes(root, task.id, state)
    findings = find_review_findings_path(root, state, task.id)
    print(f"Refreshed packet: {packet.relative_to(root)}")
    if notes:
        print(f"Included {len(notes)} pending inbox note(s).")
    else:
        print("No pending inbox notes for this task.")
    if findings:
        print(f"Included rework from {findings.relative_to(root)}.")
    else:
        print("No review-findings.md found for this task (run review first).")


def cooldown_cmd(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    state = load_state(root)
    policy = read_policy(root, args.policy)
    action = getattr(args, "cooldown_action", None)
    if action == "clear":
        if not args.force:
            die(
                "cooldown clear requires --force (API limits may still apply; probe may re-arm)"
            )
        name = str(args.backend)
        if name not in policy.get("backends", {}):
            die(f"unknown backend: {name}")
        # A credential-dead mark is also cleared here — this is the
        # operator's "I have authenticated it" switch, and it is accepted even when
        # no timer cooldown exists, so a credential-dead backend is never stuck.
        credential = backend_credential_dead(state, name)
        if name not in state.get("backend_cooldowns", {}) and credential is None:
            die(f"no active cooldown or credential entry for backend: {name}")
        clear_backend_cooldown(state, name)
        clear_backend_credentials(state, name)
        save_state(root, state)
        print(
            f"warning: cleared cooldown for {name}; vendor rate limits may still apply",
            file=sys.stderr,
        )
        print(f"Cleared cooldown for {name}")
        if credential is not None:
            print(
                f"Cleared credential-dead mark for {name} "
                "(auto routing will dispatch to it again)"
            )
        return
    die("unknown cooldown action")


def pin_cmd(args: argparse.Namespace) -> None:
    """`ai-task pin` — pin one backend for the whole wave.

    The pin lives in state.json and overrides per-task `Agent:` routing for every
    subsequent run/plan until `pin --clear`. While pinned, limit and quota
    fallback are suppressed: an unavailable pinned backend fails or waits, it
    never substitutes another vendor.
    """
    root = selected_root(args.repo)
    require_initialized(root)
    state = load_state(root)
    policy = read_policy(root, args.policy)
    if args.clear:
        current = str(state.get("pinned_backend") or "")
        if not current:
            print("no backend pin set")
            return
        # save_state's three-way merge only writes incoming keys — a popped key
        # would silently survive, so clearing is an explicit null write.
        state["pinned_backend"] = None
        save_state(root, state)
        print("cleared backend pin; routing returns to Agent:/auto rules")
        return
    name = args.backend
    if not name:
        current = str(state.get("pinned_backend") or "")
        print(f"pinned backend: {current}" if current else "no backend pin set")
        return
    if name == "auto":
        # Reuse an existing wave choice. Resolve only once, before dispatch;
        # a new wave starts with pin --clear.
        if state.get("pinned_backend"):
            print(f"pinned backend: {state['pinned_backend']} (existing wave choice)")
            return
        task = routing_task_for_status(
            parse_backlog(root), state, policy, None,
            extra_done_ids=archived_done_ids(root),
        )
        if task is None:
            die("no eligible worker task to resolve a wave backend")
        order = choose_backend_order(task, policy, "auto", state, root)
        if not order:
            die("no usable wave backend; inspect `ai-task status --json` routing")
        name = order[0]
        reason = "task Agent" if task.agent != "auto" else default_backend_order(task, policy)[1]
        print(f"selection: {reason}; first task: {task.id}")
    backends = policy.get("backends", {})
    if name not in backends:
        die(f"unknown backend: {name} (known: {', '.join(sorted(backends))})")
    if not backends[name].get("enabled", False):
        die(f"backend {name} is disabled in policy; enable it before pinning")
    state["pinned_backend"] = name
    save_state(root, state)
    if not backend_available(backends[name]):
        print(
            f"warning: pinned {name}, but its command is not available on PATH",
            file=sys.stderr,
        )
    print(
        f"pinned backend: {name} "
        "(applies to every run/plan until `ai-task pin --clear`)"
    )


def quota_cmd(args: argparse.Namespace) -> None:
    """`ai-task quota status` — report Claude quota windows and the reserve stop line.

    Reads only the configured snapshot source (no network, no nonconfigured
    services). Reports quota as unavailable when disabled or no fresh source.
    """
    root = selected_root(args.repo)
    require_initialized(root)
    policy = read_policy(root, args.policy)
    action = getattr(args, "quota_action", None)
    if action == "doctor":
        quota_doctor_cmd(args, root, policy)
        return
    if action == "setup-statusline":
        quota_setup_statusline_cmd(args, root, policy)
        return
    if action == "refresh":
        quota_refresh_cmd(args, root, policy)
        return
    if action == "stats":
        quota_stats_cmd(args, root, policy)
        return
    if action == "calibrate":
        quota_calibrate_cmd(args, root, policy)
        return
    if action != "status":
        die("unknown quota action")
    status = quota_status(root, policy)
    # Recent telemetry count + last sample time: exposed on the quota
    # status surface so an operator can see calibration data accumulating even when
    # the quota source itself is currently unavailable.
    status["telemetry"] = quota_telemetry_summary(root, policy)
    if getattr(args, "json", False):
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return
    telemetry = status.get("telemetry", {})
    if telemetry.get("available"):
        print(
            f"Telemetry: {telemetry.get('count', 0)} samples "
            f"(last {telemetry.get('last_sample_at') or '?'}; recent "
            f"{telemetry.get('recent_high_confidence', 0)} high / "
            f"{telemetry.get('recent_low_confidence', 0)} low confidence)"
        )
    if not status.get("enabled"):
        print("Quota supervision: disabled in policy ([quota] enabled = false).")
        return
    if not status.get("available"):
        reason = status.get("reason") or "no fresh quota source"
        print(f"Quota: unavailable ({reason}).")
        print(f"  source: {status.get('source')} at {status.get('source_path')}")
        print(
            "  limit-pattern detection and cooldowns continue; "
            "see docs/ai-task.md and run `ai-task quota setup-statusline --global`."
        )
        return
    age = status.get("age_seconds")
    age_note = f"{int(age)}s old" if isinstance(age, (int, float)) else "age unknown"
    print(
        f"Quota: available (source {status.get('source')}, {age_note}; "
        f"reserve {status.get('reserve_percentage')}% → stop line "
        f"{status.get('stop_line_percentage')}% used)"
    )
    for view in status.get("windows", []):
        flag = ""
        if view.get("at_or_over_stop"):
            flag = "  [AT/OVER STOP]"
        elif view.get("near_limit"):
            flag = "  [near limit]"
        resets = view.get("resets_at") or "?"
        print(
            f"- {view.get('window')}: used {view.get('used_percentage')}% "
            f"({view.get('remaining_before_stop')}% before stop, resets {resets})"
            f"{flag}"
        )


def quota_probe_payload() -> dict[str, Any]:
    """Live global quota read against built-in defaults; never touches disk.

    Uses an empty policy: every helper falls back to its default (reserve 5%,
    near-limit 85%, refresh timeout 10s). ``available`` is False with a
    ``reason`` when the token, endpoint, or response shape is missing.
    """
    policy: dict[str, Any] = {}
    reserve = quota_reserve_percentage(policy)
    near_limit_threshold = quota_near_limit_threshold(policy)
    payload: dict[str, Any] = {
        "available": False,
        "source": "claude_oauth",
        "reserve_percentage": reserve,
        "stop_line_percentage": max(0.0, 100.0 - reserve),
        "near_limit_start_threshold_percentage": near_limit_threshold,
        "captured_at": now(),
        "windows": [],
        "near_limit": False,
        "at_or_over_stop": False,
        "reason": None,
        "unauthorized": False,
        # When the headless claude.ai sign-in ends, default threshold.
        "login": claude_login_expiry(policy),
    }
    try:
        raw_output = fetch_claude_oauth_usage_json(policy)
    except ClaudeOAuthUnauthorizedError as exc:
        # Token stale (HTTP 401/403): the reason carries the open-the-app hint.
        payload["reason"] = str(exc)
        payload["unauthorized"] = True
        return payload
    except RuntimeError as exc:
        payload["reason"] = str(exc)
        return payload
    try:
        data = json.loads(raw_output)
    except json.JSONDecodeError:
        payload["reason"] = "usage endpoint returned invalid JSON"
        return payload
    windows = parse_known_quota_usage_windows(data) if isinstance(data, dict) else {}
    if not windows:
        payload["reason"] = "no known quota windows in usage endpoint response"
        return payload
    window_views = [
        _quota_window_view(window, reserve, near_limit_threshold)
        for window in _ordered_windows(windows)
    ]
    payload["available"] = True
    payload["windows"] = window_views
    payload["near_limit"] = any(view["near_limit"] for view in window_views)
    payload["at_or_over_stop"] = any(view["at_or_over_stop"] for view in window_views)
    return payload


def quota_probe_cmd(args: argparse.Namespace) -> None:
    """`ai-task quota probe` — live global quota read, usable without `.ai-task/`.

    Pre-fan-out check for any agent workflow: resolves the
    Claude OAuth token via the env → credentials file → keychain chain,
    queries the usage endpoint, and assesses windows against the default 5%
    reserve. Read-only: bypasses init/policy and never writes state.
    """
    payload = quota_probe_payload()
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if not payload["available"]:
            raise SystemExit(1)
        return
    login = payload["login"]
    login_line = f"Login: {'WARNING: ' if login.get('warn') else ''}"
    login_line += claude_login_expiry_line(login)
    if not payload["available"]:
        print(login_line)
        die(f"quota probe failed: {payload['reason']}")
    print(
        f"Quota probe: live (source {payload['source']}; "
        f"reserve {payload['reserve_percentage']}% → stop line "
        f"{payload['stop_line_percentage']}% used)"
    )
    for view in payload["windows"]:
        flag = ""
        if view.get("at_or_over_stop"):
            flag = "  [AT/OVER STOP]"
        elif view.get("near_limit"):
            flag = "  [near limit]"
        resets = view.get("resets_at") or "?"
        print(
            f"- {view.get('window')}: used {view.get('used_percentage')}% "
            f"({view.get('remaining_before_stop')}% before stop, resets {resets})"
            f"{flag}"
        )
    print(login_line)
    if payload["at_or_over_stop"]:
        print("Assessment: at/over the reserve stop line — do not fan out.")
    elif payload["near_limit"]:
        print("Assessment: near limit — fan out conservatively.")
    else:
        print("Assessment: headroom available — safe to fan out.")


def quota_setup_statusline_check(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    helper = quota_statusline_helper_path(root)
    status = quota_status(root, policy)
    return {
        "ok": bool(helper.is_file() and status.get("available")),
        "helper_path": str(helper),
        "helper_exists": helper.is_file(),
        "snapshot_path": status.get("source_path"),
        "quota": compact_quota_status(status),
        "project_command": quota_statusline_shell_command(root),
        "global_command": quota_statusline_global_command(),
    }


def quota_setup_statusline_cmd(
    args: argparse.Namespace, root: Path, policy: dict[str, Any]
) -> None:
    """Print or validate Claude Code statusLine wiring for quota snapshots."""
    mode_global = bool(getattr(args, "global_mode", False))
    mode_project = bool(getattr(args, "project_mode", False))
    if mode_global and mode_project:
        die("choose only one mode: --global or --project")
    if getattr(args, "check", False) and (mode_global or mode_project):
        die("--check is repo-scoped; do not combine it with --global/--project")
    if getattr(args, "check", False):
        result = quota_setup_statusline_check(root, policy)
        if getattr(args, "json", False):
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            helper_state = "ok" if result["helper_exists"] else "missing"
            quota = result.get("quota", {})
            quota_state = "fresh" if quota.get("available") else "unavailable"
            print(f"Quota statusLine helper: {helper_state} ({result['helper_path']})")
            print(
                f"Quota snapshot: {quota_state} ({result.get('snapshot_path')}; "
                f"{quota.get('reason') or 'fresh'})"
            )
            if not result["ok"]:
                print("Next step: install the recommended global statusLine wiring:")
                print("  ai-task quota setup-statusline --global")
                print("Then open Claude Code in this repo and re-run:")
                print("  ai-task quota setup-statusline --check")
        if not result["ok"]:
            raise SystemExit(1)
        return

    if mode_global:
        dispatcher = quota_statusline_dispatcher_source_path()
        print("Claude Code statusLine setup for ai-task quota supervision")
        print()
        print("Global settings snippet (recommended)")
        print(quota_statusline_global_settings_snippet())
        print()
        print("Install the dispatcher on PATH (example):")
        print('  mkdir -p "$HOME/.local/bin"')
        print(
            f'  ln -sf "{dispatcher}" '
            '"$HOME/.local/bin/ai-task-quota-statusline-dispatch.py"'
        )
        print('  chmod +x "$HOME/.local/bin/ai-task-quota-statusline-dispatch.py"')
        print()
        print(
            "This snippet is repo-agnostic and safe for global Cursor/Claude settings."
        )
        print("Validate from each target repo after Claude Code renders once:")
        print("  ai-task quota setup-statusline --check")
        return

    if mode_project:
        helper = quota_statusline_helper_path(root)
        print("Claude Code statusLine setup for ai-task quota supervision")
        print()
        print("Project-local settings snippet (this repo only)")
        print(quota_statusline_project_settings_snippet(root))
        print()
        print(f"Project helper command: {quota_statusline_shell_command(root)}")
        print(
            "Warning: this snippet is repo-specific and should stay in project-local settings."
        )
        if not helper.is_file():
            print(
                f"Helper is missing at {helper}. Re-run `ai-task init` in this repo first."
            )
        print("Validate after Claude Code has rendered the status line:")
        print("  ai-task quota setup-statusline --check")
        return

    helper = quota_statusline_helper_path(root)
    print("Claude Code statusLine setup for ai-task quota supervision")
    print()
    print("Choose setup mode:")
    print("- Recommended global setup: ai-task quota setup-statusline --global")
    print(
        "- Project-local setup for this repo only: ai-task quota setup-statusline --project"
    )
    print()
    print("Use --global for ~/.claude/settings.json or ~/.cursor/cli-config.json.")
    print("Use --project only for repo-local settings.")
    print()
    if not helper.is_file():
        print(
            f"Helper is missing at {helper}. Re-run `ai-task init` in this repo first."
        )
    print("Validate after Claude Code has rendered the status line:")
    print("  ai-task quota setup-statusline --check")


def quota_refresh_cmd(
    args: argparse.Namespace, root: Path, policy: dict[str, Any]
) -> None:
    """`ai-task quota refresh` — actively update the quota snapshot."""
    result = quota_refresh(root, policy, force=bool(getattr(args, "force", False)))
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if result.get("refreshed"):
        status = result.get("status", {})
        print(
            f"Quota snapshot refreshed from {result.get('source')} "
            f"at {result.get('snapshot_path')}"
        )
        windows = status.get("windows", []) if isinstance(status, dict) else []
        for view in windows:
            print(
                f"- {view.get('window')}: used {view.get('used_percentage')}% "
                f"({view.get('remaining_before_stop')}% before stop, "
                f"resets {view.get('resets_at') or '?'})"
            )
        return
    print(f"Quota refresh: no-op ({result.get('reason') or 'not refreshed'}).")
    attempts = result.get("attempts", [])
    if isinstance(attempts, list):
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            command = " ".join(str(part) for part in attempt.get("command", []))
            print(f"- {attempt.get('source')}: {attempt.get('reason')} ({command})")


def maybe_refresh_quota_for_dispatch(
    root: Path,
    policy: dict[str, Any],
    *,
    task_ids: list[str],
    phase: str,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Refresh stale/missing quota before dispatch surfaces make decisions."""
    if not quota_enabled(policy) or not quota_refresh_on_dispatch(policy):
        return {"attempted": False, "reason": "refresh disabled or quota disabled"}
    before = quota_status(root, policy)
    if before.get("available"):
        return {
            "attempted": False,
            "reason": "snapshot already fresh",
            "status": before,
        }
    result = quota_refresh(root, policy)
    after = quota_status(root, policy)
    if after.get("available"):
        return {"attempted": True, "refreshed": True, "status": after, "result": result}
    reason = result.get("reason") or after.get("reason") or "no fresh quota source"
    maybe_auto_log_anomaly(
        root,
        policy,
        phase=phase,
        choice="quota_blind_dispatch",
        task_ids=task_ids,
        run_ids=[],
        state=state,
        signals={
            "before_reason": before.get("reason"),
            "after_reason": after.get("reason"),
            "refresh_result": result,
        },
        reason=f"quota source unavailable at dispatch: {reason}",
    )
    print(
        f"warning: quota refresh unavailable at dispatch ({reason}); "
        "Claude quota admission control remains blind",
        file=sys.stderr,
    )
    return {"attempted": True, "refreshed": False, "status": after, "result": result}


def _resolve_policy_path(root: Path, policy_name: str | None) -> Path:
    """Locate the policy TOML the same way `read_policy` selects it."""
    selected = policy_name or str(read_config(root).get("default_policy", "default"))
    return app_path(root) / "policies" / f"{selected}.toml"


def _fmt_pct(value: Any) -> str:
    """Format a percentage cell for plain output ('-' when absent)."""
    return "-" if value is None else f"{value:g}"


def _print_calibration_size_table(calibration: dict[str, Any]) -> None:
    print("Observed quota delta by Size: (high-confidence single-run samples)")
    print("  size  n   p50    p80    p95    current  recommended")
    for label, _ in QUOTA_CALIBRATION_SIZE_ORDER:
        block = calibration.get("by_size", {}).get(label, {})
        rec = block.get("recommended_percentage")
        rec_note = ""
        if rec is not None and not block.get("enough_for_recommendation"):
            rec_note = " (low n)"
        print(
            f"  {label:<5} {block.get('count', 0):<3} "
            f"{_fmt_pct(block.get('p50')):<6} {_fmt_pct(block.get('p80')):<6} "
            f"{_fmt_pct(block.get('p95')):<6} {_fmt_pct(block.get('current_percentage')):<8} "
            f"{_fmt_pct(rec)}{rec_note}"
        )


def quota_stats_cmd(
    args: argparse.Namespace, root: Path, policy: dict[str, Any]
) -> None:
    """`ai-task quota stats [--json]` — report observed quota deltas and recommendations.

    Advisory only: prints sample counts, p50/p80/p95 observed delta by `Size:` and by
    backend/model, the high/low confidence split, and current-vs-recommended
    reservations. Low-confidence (parallel/partial) samples are excluded from the
    percentiles by default; pass --include-low-confidence to fold them in (less
    trustworthy). Never writes policy.
    """
    include_low = bool(getattr(args, "include_low_confidence", False))
    calibration = aggregate_quota_calibration(
        root, policy, include_low_confidence=include_low
    )
    if getattr(args, "json", False):
        print(json.dumps(calibration, ensure_ascii=False, indent=2))
        return
    buckets = calibration.get("confidence_buckets", {})
    print(
        f"Quota telemetry: {calibration.get('total_samples', 0)} samples "
        f"({buckets.get('high_confidence', 0)} high-confidence, "
        f"{buckets.get('low_confidence', 0)} low-confidence"
        + (
            f", {buckets.get('single_run_without_delta', 0)} without usable delta"
            if buckets.get("single_run_without_delta")
            else ""
        )
        + ")"
    )
    if include_low:
        print("  (including low-confidence samples in percentiles — less trustworthy)")
    _print_calibration_size_table(calibration)
    by_model = calibration.get("by_model", {})
    if by_model:
        print("Observed quota delta by backend/model")
        for model_key, block in by_model.items():
            print(
                f"  {model_key}: n={block.get('count', 0)} "
                f"p50={_fmt_pct(block.get('p50'))} p80={_fmt_pct(block.get('p80'))} "
                f"p95={_fmt_pct(block.get('p95'))}"
            )
    min_samples = calibration.get("min_samples_for_apply")
    high_count = buckets.get("high_confidence", 0)
    if calibration.get("enough_for_apply"):
        print(
            f"Recommendations are advisory. {high_count} high-confidence samples "
            f"meet the {min_samples}-sample apply minimum; review before "
            "`quota calibrate --apply`."
        )
    else:
        print(
            f"Advisory only: {high_count}/{min_samples} high-confidence samples — "
            "below the apply minimum. Calibration is not proof after one unusual "
            "batch; keep the current defaults until more data accumulates."
        )


def quota_calibrate_cmd(
    args: argparse.Namespace, root: Path, policy: dict[str, Any]
) -> None:
    """`ai-task quota calibrate` — suggest (and optionally apply) reservation values.

    Default and `--dry-run`: print the conservative `[quota.reservations]` patch that
    observed telemetry would suggest (p95 rounded up, with a floor), without touching
    policy. `--apply`: write the patch, but only when high-confidence sample count
    meets `[quota] calibration_min_samples` (default 100), and always after creating a
    `<policy>.toml.bak` backup (the same backup path `policy sync` uses). Calibration
    is advisory; it never auto-applies and never overrides the operator's defaults.
    """
    apply = bool(getattr(args, "apply", False))
    as_json = bool(getattr(args, "json", False))
    # --dry-run is the default behavior; only --apply writes. Low-confidence samples
    # are never folded into an apply.
    calibration = aggregate_quota_calibration(
        root, policy, include_low_confidence=False
    )
    patch = quota_calibration_patch(calibration)
    min_samples = calibration.get("min_samples_for_apply")
    high_count = calibration.get("confidence_buckets", {}).get("high_confidence", 0)
    enough = bool(calibration.get("enough_for_apply"))
    result: dict[str, Any] = {
        "applied": False,
        "dry_run": not apply,
        "total_samples": calibration.get("total_samples", 0),
        "high_confidence_samples": high_count,
        "min_samples_for_apply": min_samples,
        "enough_for_apply": enough,
        "patch": patch,
        "recommendations": calibration.get("recommendations", {}),
        "advisory": (
            "Calibration is advisory. Do not treat one unusual batch as proof; "
            "review the per-size sample counts before applying."
        ),
    }

    if not apply:
        if as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        print("Calibration is advisory (dry-run): no policy changes written.")
        print(f"High-confidence samples: {high_count} (apply minimum {min_samples}).")
        if not patch:
            print(
                "Suggested [quota.reservations] patch: none — observed p95 matches "
                "the current values, or not enough per-size samples yet."
            )
        else:
            print("Suggested [quota.reservations] patch (p95 rounded up, floored):")
            for policy_key, change in patch.items():
                print(
                    f"  {policy_key} ({change.get('size')}): "
                    f"{change.get('from')} -> {change.get('to')}"
                )
            if not enough:
                print(
                    f"  NOTE: {high_count}/{min_samples} samples — `--apply` is "
                    "refused below the minimum. This is a preview, not proof."
                )
        return

    # --apply path: refuse below the configured minimum; never auto-apply on a thin,
    # possibly unusual batch.
    if not enough:
        die(
            f"refusing to apply calibration: only {high_count} high-confidence "
            f"samples (< {min_samples}). Calibration is advisory and must not be "
            "applied after one unusual batch. Set [quota] calibration_min_samples "
            "lower only if you understand the risk, or wait for more telemetry."
        )
    policy_path = _resolve_policy_path(root, getattr(args, "policy", None))
    if not policy_path.exists():
        die(f"policy not found: {policy_path}")
    if not patch:
        if as_json:
            result["reason"] = "no change"
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        print("Calibration: recommended values already match policy; nothing to apply.")
        return
    backup_path, fallback_reason = apply_quota_calibration_patch(policy_path, patch)
    result["applied"] = True
    result["backup_path"] = str(backup_path)
    result["policy_path"] = str(policy_path)
    # calibrate edits the policy in place like policy sync.
    result["edit_fallback_reason"] = fallback_reason
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"Backup: {backup_path}")
    if fallback_reason:
        print(fallback_note(fallback_reason, backup_path))
    print("Applied advisory [quota.reservations] calibration:")
    for policy_key, change in patch.items():
        print(
            f"  {policy_key} ({change.get('size')}): "
            f"{change.get('from')} -> {change.get('to')}"
        )
    print(
        "These are advisory estimates from observed telemetry, not a guarantee; "
        "revert with the backup if a later batch shows they were too low."
    )


def statusline_settings_command(root: Path) -> str | None:
    """Best-effort probe for a statusLine settings command that feeds quota snapshots.

    Looks for a ``statusLine.command`` referencing the ai-task quota helper or
    dispatcher in project-local then global Claude settings (and the Cursor CLI
    config). Diagnostics only: unreadable or unexpected files are skipped.
    """
    candidates = (
        root / ".claude" / "settings.json",
        root / ".claude" / "settings.local.json",
        Path("~/.claude/settings.json").expanduser(),
        Path("~/.cursor/cli-config.json").expanduser(),
    )
    for path in candidates:
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        status_line = raw.get("statusLine") if isinstance(raw, dict) else None
        command = status_line.get("command") if isinstance(status_line, dict) else None
        if isinstance(command, str) and "ai-task-quota-statusline" in command:
            return command
    return None


def quota_doctor_report(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    """`quota doctor` payload: pass/fail per check with a one-line why.

    Explains why Claude quota admission control did or did not gate: [quota]
    policy switch, statusLine wiring (vendored helper + reachable dispatcher),
    snapshot freshness vs max_snapshot_age_seconds, last headless refresh
    attempt, active reservations vs current windows, and a dry
    ``reservation_decision`` view per Size:. Read-only — never shells out to
    refresh sources and never mutates state. ``blind`` is True when supervision
    is enabled but has no fresh source and headless refresh is unavailable: the
    silent state where waves run to 100% of the window with no pause.
    """
    checks: list[dict[str, Any]] = []

    section_present = isinstance(policy.get("quota"), dict)
    enabled = quota_enabled(policy)
    if not section_present:
        policy_why = (
            "policy has no [quota] section (created by an older ai-task), so quota "
            "supervision defaults to disabled; run `ai-task policy sync` to add "
            "the missing keys"
        )
    elif not enabled:
        policy_why = "[quota] enabled = false — admission control is off in policy"
    else:
        policy_why = "[quota] section present and enabled = true"
    checks.append(
        {"name": "policy", "ok": section_present and enabled, "why": policy_why}
    )

    # statusLine wiring: vendored repo helper + a reachable dispatcher (on PATH
    # or already wired as a settings statusLine command).
    helper = quota_statusline_helper_path(root)
    helper_exists = helper.is_file()
    dispatcher_name = quota_statusline_global_command()
    dispatcher_path = shutil.which(dispatcher_name)
    settings_command = statusline_settings_command(root)
    parts: list[str] = []
    if helper_exists:
        parts.append(f"helper vendored at {helper}")
    else:
        parts.append(f"helper missing at {helper} (run `ai-task init`)")
    if dispatcher_path:
        parts.append(f"dispatcher on PATH at {dispatcher_path}")
    elif settings_command:
        parts.append(f"statusLine wired via settings command: {settings_command}")
    else:
        parts.append(
            f"dispatcher {dispatcher_name} not on PATH and no statusLine settings "
            "command found (run `ai-task quota setup-statusline --global`)"
        )
    checks.append(
        {
            "name": "statusline",
            "ok": bool(helper_exists and (dispatcher_path or settings_command)),
            "why": "; ".join(parts),
        }
    )

    # Snapshot path, freshness, age vs max_snapshot_age_seconds.
    snapshot = load_quota_snapshot(root, policy)
    max_age = quota_max_snapshot_age_seconds(policy)
    age = snapshot.get("age_seconds")
    age_note = f"{int(age)}s" if isinstance(age, (int, float)) else "unknown"
    if snapshot.get("available"):
        snapshot_why = (
            f"snapshot fresh at {snapshot.get('source_path')} "
            f"(age {age_note} <= max {max_age}s)"
        )
    else:
        snapshot_why = (
            f"{snapshot.get('reason') or 'no fresh quota source'} "
            f"at {snapshot.get('source_path')} (max age {max_age}s)"
        )
    checks.append(
        {"name": "snapshot", "ok": bool(snapshot.get("available")), "why": snapshot_why}
    )

    # Last headless refresh attempt result and source. Refresh counts as
    # unavailable when disabled, unconfigured, or its last attempt failed.
    refresh_enabled = quota_refresh_enabled(policy)
    sources = quota_refresh_sources(policy)
    refresh_state = read_quota_refresh_state(root)
    last_failed = bool(
        refresh_state is not None
        and not refresh_state.get("refreshed")
        and not refresh_state.get("available")
    )
    refresh_available = refresh_enabled and bool(sources) and not last_failed
    if not refresh_enabled:
        refresh_why = (
            "[quota] refresh_enabled = false — headless refresh cannot "
            "re-actualize a stale snapshot"
        )
    elif not sources:
        refresh_why = "no [quota] refresh_sources configured"
    elif refresh_state is None:
        refresh_why = f"no refresh attempt recorded yet (sources: {', '.join(sources)})"
    elif refresh_state.get("refreshed"):
        refresh_why = (
            f"last refresh at {refresh_state.get('at') or '?'} succeeded "
            f"via {refresh_state.get('source') or '?'}"
        )
    elif refresh_state.get("available"):
        refresh_why = (
            f"last refresh at {refresh_state.get('at') or '?'}: snapshot already fresh"
        )
    else:
        refresh_why = (
            f"last refresh at {refresh_state.get('at') or '?'} failed: "
            f"{refresh_state.get('reason') or 'unknown reason'}"
        )
        # Token-stale vs endpoint-down need different operator actions: a 401/403
        # is only fixable by opening the Claude Code app.
        if refresh_state.get("unauthorized"):
            refresh_why += (
                " — OAuth token stale; open the Claude Code app to refresh it"
            )
        else:
            refresh_why += " — endpoint or refresh source unreachable"
    checks.append({"name": "refresh", "ok": refresh_available, "why": refresh_why})

    # When the headless claude.ai sign-in ends. A stale login makes
    # `claude -p` fail while the interactive app still works, so the
    # date is shown here and fails below [quota] login_expiry_warn_days. Reads
    # `claude auth status` locally; an old CLI reports the expiry as unknown.
    login = claude_login_expiry(policy)
    checks.append(
        {"name": "login", "ok": bool(login["ok"]), "why": claude_login_expiry_line(login)}
    )

    # How the headless worker answers permission checks. The bundled
    # no-prompt mode needs Claude Code >= 2.1.319; an older CLI fails here instead
    # of failing every run on an unknown option. Reuses the version read above.
    permissions = claude_permission_mode_report(
        policy.get("backends", {}).get("claude", {}) or {},
        parse_claude_cli_version(login.get("cli_version")),
    )
    checks.append(
        {"name": "permissions", "ok": bool(permissions["ok"]), "why": permissions["why"]}
    )

    # Whether the local Claude Code still accepts that settings JSON.
    # Print mode drops a settings file that fails validation without a word, so the
    # write block and the sandbox would go while runs keep passing. Runs `claude
    # --settings <file> doctor` locally, no model call; always fresh here.
    settings_canary = claude_settings_canary(
        policy.get("backends", {}).get("claude", {}) or {}, root, use_cache=False
    )
    settings_why = settings_canary["why"]
    if settings_canary["ok"] and settings_canary.get("last_passed_version"):
        settings_why += f"; last pass recorded on {settings_canary['last_passed_version']}"
    checks.append(
        {"name": "settings", "ok": bool(settings_canary["ok"]), "why": settings_why}
    )

    # Active reservations vs current windows (informational; stale ones pruned).
    state = load_state(root)
    reservations = active_quota_reservations(state)
    reserved_total = round(quota_reserved_total(state), 3)
    status = quota_status(root, policy)
    window_notes = [
        f"{view.get('window')} {view.get('remaining_before_stop')}% before stop"
        for view in status.get("windows", [])
    ]
    windows_note = (
        f"; windows: {', '.join(window_notes)}" if window_notes else "; no window data"
    )
    if reservations:
        reservations_why = (
            f"{len(reservations)} active reservation(s) holding "
            f"{reserved_total}%{windows_note}"
        )
    else:
        reservations_why = f"no active reservations{windows_note}"
    checks.append({"name": "reservations", "ok": True, "why": reservations_why})

    # Effective stop line and what would gate right now: dry reservation_decision
    # per Size: (no state mutation, nothing reserved).
    available_budget = quota_available_budget(status, state)
    gating: list[dict[str, Any]] = []
    for label, size in (("S", "s"), ("M", "m"), ("L", "l"), ("unknown", "")):
        probe = Task(
            id=f"DOCTOR-{label}",
            title="quota doctor probe",
            status=" ",
            phase="",
            index=0,
            block="",
            priority="",
            size=size,
            depends_on=(),
            agent="auto",
        )
        gating.append(
            {"size": label, **reservation_decision(probe, policy, status, state)}
        )
    admission_active = bool(enabled and status.get("available"))
    if not enabled:
        admission_why = "admission control inactive: quota supervision disabled"
    elif not status.get("available"):
        admission_why = (
            "admission control inert: no fresh quota source, so nothing would "
            "gate right now (documented fail-open)"
        )
    else:
        gated = [item["size"] for item in gating if not item["fits"]]
        admission_why = (
            f"stop line {status.get('stop_line_percentage')}% used; available "
            f"budget {round(available_budget or 0.0, 3)}%"
            + (
                f"; would gate right now: {', '.join(gated)}"
                if gated
                else "; nothing would gate right now"
            )
        )
    checks.append({"name": "admission", "ok": admission_active, "why": admission_why})

    blind = bool(enabled and not status.get("available") and not refresh_available)
    return {
        "ok": all(check["ok"] for check in checks),
        "blind": blind,
        "enabled": enabled,
        "stop_line_percentage": status.get("stop_line_percentage"),
        "available_budget": (
            None if available_budget is None else round(available_budget, 3)
        ),
        "gating": gating,
        "login": login,
        "permissions": permissions,
        "settings_canary": settings_canary,
        "checks": checks,
    }


def quota_doctor_cmd(
    args: argparse.Namespace, root: Path, policy: dict[str, Any]
) -> None:
    """`ai-task quota doctor` — one-command diagnosis of quota admission control.

    Prints pass/fail per check with a one-line why plus the dry gating view per
    Size:. Exits non-zero only when supervision is enabled but blind (no fresh
    source and headless refresh unavailable), because that is the silent state
    where waves run to 100% of the window with no pause.
    """
    report = quota_doctor_report(root, policy)
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        if report["blind"]:
            verdict = "ENABLED BUT BLIND — admission control cannot gate"
        elif not report["enabled"]:
            verdict = "quota supervision disabled — admission control off"
        elif report["ok"]:
            verdict = "quota admission control is active"
        else:
            verdict = "degraded — see failing checks below"
        print(f"Quota doctor: {verdict}")
        for check in report["checks"]:
            mark = "PASS" if check["ok"] else "FAIL"
            print(f"[{mark}] {check['name']}: {check['why']}")
        print("Reservation dry view (what would gate right now):")
        for item in report["gating"]:
            if not item["fits"]:
                outcome = f"would gate ({item['blocked_reason']})"
            elif report["available_budget"] is None:
                outcome = "would dispatch (quota-blind, nothing gates)"
            else:
                outcome = "would dispatch"
            print(f"- Size {item['size']}: requires {item['required']}% -> {outcome}")
        if report["blind"]:
            print(
                "Next step: restore a quota source — run `ai-task quota refresh`, "
                "then `ai-task quota setup-statusline --check`, and re-run "
                "`ai-task quota doctor`. If refresh keeps failing, check whether "
                "the vendor contract drifted "
                "(see docs/vendor-contract.md)."
            )
    if report["blind"]:
        raise SystemExit(1)


def policy_cmd(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    policy_path = app_path(root) / "policies" / f"{args.policy}.toml"
    if not policy_path.exists():
        die(f"policy not found: {args.policy}")
    if args.action == "path":
        print(policy_path)
        return
    if args.action == "sync":
        local = load_toml(policy_path)
        override_errors = model_override_errors(local)
        if override_errors:
            die(f"policy {args.policy}: " + "\n  ".join(override_errors))
        profile = str(local.get("verify", {}).get("default_profile", "none"))
        template = bundled_template_policy(default_verify_profile=profile)
        force = bool(getattr(args, "force", False))
        merged, changes = merge_policy_dicts(template, local, force=force)
        drifts = collect_policy_drift(template, local, force=force)
        # a model_override is kept and reported on every sync, and the
        # bundled model it was checked against is recorded in the merged policy.
        overrides = sync_model_overrides(template, local, merged)
        changes += overrides.changes
        drifts += overrides.drifts
        warnings = overrides.warnings
        if force and (changes or drifts or args.dry_run):
            print(
                "warning: --force overwrites bundled fields from template "
                "(local-only keys/backends and overridden recipe lists such as "
                "verify profile commands are kept)",
                file=sys.stderr,
            )
        if not changes and not drifts:
            write_policy_baseline(root)
            print("Policy already in sync.")
            print(f"Policy baseline updated: {APP_DIR}/{POLICY_BASELINE_FILE}")
            return
        if args.dry_run:
            print_policy_sync_report(
                policy_path=policy_path,
                changes=changes,
                drifts=drifts,
                dry_run=True,
                force=force,
                warnings=warnings,
            )
            return
        if not changes:
            write_policy_baseline(root)
            print_policy_sync_report(
                policy_path=policy_path,
                changes=changes,
                drifts=drifts,
                dry_run=False,
                force=force,
                warnings=warnings,
            )
            print(f"Policy baseline updated: {APP_DIR}/{POLICY_BASELINE_FILE}")
            return
        backup_path = policy_path.with_suffix(".toml.bak")
        shutil.copy2(policy_path, backup_path)
        # edit the file text in place so comments and layout survive;
        # the full render is only the fallback, and the report says when it ran.
        edited, fallback_reason = edit_policy_text(
            policy_path.read_text(encoding="utf-8"),
            local,
            merged,
            default_policy(default_verify_profile=profile),
        )
        policy_path.write_text(edited, encoding="utf-8")
        write_policy_baseline(root)
        print(f"Backup: {backup_path}")
        if fallback_reason:
            print(fallback_note(fallback_reason, backup_path))
        print_policy_sync_report(
            policy_path=policy_path,
            changes=changes,
            drifts=drifts,
            dry_run=False,
            force=force,
            warnings=warnings,
        )
        print(f"Policy baseline updated: {APP_DIR}/{POLICY_BASELINE_FILE}")
        return
    if args.action == "show":
        print(policy_path.read_text(encoding="utf-8"))
        return
    policy = load_toml(policy_path)
    # `available` is binary-on-PATH; `usable` adds "and it can actually work"
    # — an unauthenticated backend used to read as plain available.
    for row in backends_health(policy, load_state(root)):
        line = (
            f"{row['name']}: enabled={'yes' if row['enabled'] else 'no'} "
            f"available={'yes' if row['available'] else 'no'} "
            f"usable={'yes' if row['usable'] else 'no'} command={row['command']}"
        )
        if not row["usable"] and row["unusable_reason"]:
            line += f" ({row['unusable_reason']})"
        if row["credential_dead"]:
            line += f" [fix: {row['fix']}]"
        print(line)


def watch_run(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    policy = read_policy(root, args.policy)
    state = load_state(root)
    backends = policy.get("backends", {})
    refresh_runs(root, state, policy)
    run_record = find_run(state, args.run_id)
    paths = collect_run_log_paths(run_record, root)
    if not paths:
        die(f"no log files for run {args.run_id}")

    def emit_tail(path: Path) -> None:
        rel = path.relative_to(root)
        print(f"=== {rel} ===")
        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        for line in lines[-args.lines :]:
            print(line)

    for path in paths:
        emit_tail(path)
    analysis = apply_supervision(run_record, root, policy, backends)
    if analysis.get("signals"):
        print(f"signals: {', '.join(analysis['signals'])}")
    print(format_run_activity_line(analysis, policy))
    print("Pid alive is not semantic progress. Use IDE chat for interactive work.")

    if not args.follow:
        return

    offsets = {path: path.stat().st_size for path in paths}
    last_activity_line = format_run_activity_line(analysis, policy)
    try:
        while True:
            changed = False
            for path in paths:
                size = path.stat().st_size
                if size <= offsets[path]:
                    continue
                changed = True
                with path.open(encoding="utf-8", errors="replace") as handle:
                    handle.seek(offsets[path])
                    chunk = handle.read()
                    offsets[path] = size
                    if chunk:
                        rel = path.relative_to(root)
                        print(f"=== {rel} (new) ===")
                        print(chunk, end="" if chunk.endswith("\n") else "\n")
            analysis = apply_supervision(run_record, root, policy, backends)
            activity_line = format_run_activity_line(analysis, policy)
            if changed or activity_line != last_activity_line:
                if analysis.get("signals"):
                    print(f"signals: {', '.join(analysis['signals'])}")
                print(activity_line)
                last_activity_line = activity_line
            refresh_runs(root, state, policy)
            time.sleep(1)
    except KeyboardInterrupt:
        print("watch stopped")


def self_test_supervision() -> None:
    policy: dict[str, Any] = {
        "supervision": {"blocked_patterns": list(BLOCKED_WORDS)},
        "backends": {"test": {"limit_patterns": list(LIMIT_WORDS)}},
    }
    assert detect_blocked("Workspace Trust Required", policy)
    assert not detect_blocked("completed successfully", policy)
    assert detect_limit("rate limit exceeded", policy["backends"]["test"])
    # the live cursor-agent wording, and the negative control that
    # keeps an ordinary task failure reading as a task failure.
    assert detect_auth_failure(
        "Error: Authentication required. Please run 'agent login' first, "
        "or set CURSOR_API_KEY environment variable.",
        {},
    )
    assert not detect_auth_failure("Traceback: assertion failed in test_x", {})
    risky = Task(
        id="RISK-001",
        title="migration auth",
        status=" ",
        phase="",
        index=0,
        block="database migration",
        priority="P0",
        size="M",
        depends_on=(),
        agent="auto",
    )
    assert risk_gates(
        risky,
        {"review": {"high_priority": ["P0", "P1"], "require_for_risk_keywords": True}},
    )
    state: dict[str, Any] = {"runs": {}, "leases": {}, "quota_reservations": {}}
    acquire_task_lease(state, "RISK-001", "run-a", "claude")
    assert task_lease_message(state, "RISK-001", False)
    assert task_lease_message(state, "RISK-001", True) is None
    # Quota reservation acquire/release smoke check.
    state["runs"]["run-a"] = {"id": "run-a", "status": "running", "pid": os.getpid()}
    state["quota_reservations"]["run-a"] = {
        "run_id": "run-a",
        "task_id": "RISK-001",
        "percentage": 8.0,
    }
    assert quota_reserved_total(state) == 8.0
    release_quota_reservation(state, "run-a")
    assert quota_reserved_total(state) == 0.0
    # every file lives in a private temp directory. Fixed /tmp
    # paths let two self-tests (pytest -n auto workers, or a live self-test on
    # the same machine) unlink each other's log in the middle of the wait.
    with tempfile.TemporaryDirectory(prefix="ai-task-selftest-") as tmp_name:
        tmp = Path(tmp_name)
        log = tmp / "selftest.log"
        log.write_text("still working\n", encoding="utf-8")
        run = {
            "backend": "test",
            "status": "running",
            "started_at": now(),
            "stdout": str(log),
        }
        analysis = analyze_supervision(run, tmp, policy, policy["backends"])
        assert "blocked_on_user" not in analysis["signals"]

        script = tmp / "stall-test.sh"
        script.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
        script.chmod(0o755)
        out = tmp / "stall-out.log"
        err = tmp / "stall-err.log"
        out.touch()
        completed = wait_subprocess_with_supervision(
            [str(script)],
            cwd=tmp,
            prompt_input=None,
            stdout_path=out,
            stderr_path=err,
            policy={
                "supervision": {"stall_timeout_seconds": 2, "auto_stop_on_stall": True}
            },
            stall_timeout=2,
            auto_stop=True,
        )
    assert completed.returncode == 124, completed.returncode
    print("self-test supervision: passed")


def self_test_cmd(args: argparse.Namespace) -> None:
    self_test_supervision()
    root = selected_root(args.repo)
    if app_path(root).exists():
        missing = missing_bootstrap_docs(root)
        if missing:
            print(
                "self-test warning: bootstrap delivery docs missing under this repo: "
                f"{', '.join(missing)}. Re-run `ai-task init` to copy them from the "
                "ai-sdlc-local-kit profile into .ai-task/docs/.",
                file=sys.stderr,
            )
        missing_scripts = missing_bootstrap_scripts(root)
        if missing_scripts:
            print(
                "self-test warning: bootstrap helper scripts missing under this "
                f"repo: {', '.join(missing_scripts)}. Re-run `ai-task init` to "
                "vendor them from the ai-sdlc-local-kit profile into .ai-task/scripts/.",
                file=sys.stderr,
            )
        policy = read_policy(root)
        # Backend usability, reported without probing the dispatch
        # hot path: an enabled backend whose command is missing, or one remembered
        # as credential-dead, is named here with its fix so the chain is known
        # broken before a limit forces the fallback onto it.
        for row in backends_health(policy, load_state(root)):
            if not row["enabled"] or row["usable"]:
                continue
            fix = f" Fix: {row['fix']}." if row["fix"] else ""
            print(
                f"self-test warning: backend {row['name']} is enabled but not "
                f"usable — {row['unusable_reason']}.{fix} Auto routing skips it; "
                "a run that dies on it is reported as backend_unusable, not a "
                "task failure.",
                file=sys.stderr,
            )
        status = quota_status(root, policy)
        if quota_enabled(policy):
            helper = quota_statusline_helper_path(root)
            if not helper.is_file():
                print(
                    "self-test warning: Claude quota statusLine helper missing "
                    f"at {helper.relative_to(root)}. Re-run `ai-task init` to "
                    "vendor it, then run `ai-task quota setup-statusline --global`.",
                    file=sys.stderr,
                )
            if status.get("available"):
                print("self-test quota source: fresh statusLine snapshot available.")
            else:
                reason = status.get("reason") or "no fresh quota source"
                print(
                    "self-test warning: Claude quota source unavailable "
                    f"({reason}); quota admission control is inactive until the "
                    "statusLine snapshot is fresh. Run "
                    "`ai-task quota setup-statusline --global` for setup instructions.",
                    file=sys.stderr,
                )


def complete(args: argparse.Namespace) -> None:
    root = selected_root(args.repo)
    require_initialized(root)
    policy = read_policy(root, args.policy)
    state = load_state(root)
    run_record = find_run(state, args.run_id)
    # Merge-back gate: with [scope_guard] mode = "require_ack",
    # unacknowledged out-of-scope backlog edits block complete.
    enforce_scope_guard_ack(root, policy, run_record, args.run_id, action="complete")
    task_id = str(run_record.get("task_id", "")).strip()
    if task_id:
        if getattr(args, "require_report", False):
            require_task_report(root, policy, task_id)
        release_gaps = warn_release_contract_gaps(root, policy, task_id)
        if release_gaps:
            print(
                "release contract reminder (implement run should finish before teamlead commit):",
                file=sys.stderr,
            )
            for gap in release_gaps:
                print(f"  - {gap}", file=sys.stderr)
    run_record["status"] = "done"
    run_record["completed_at"] = now()
    # A complete run's work is merged, so its worktree is disposable and this is
    # the one moment the tool knows that without asking the operator.
    # --remove-worktree stays as the explicit request, and overrides a policy
    # opt-out; the guard below is the same one `cleanup --remove-worktrees` uses.
    force_release = bool(getattr(args, "force", False))
    remove_requested = getattr(args, "remove_worktree", False)
    if run_record.get("worktree_path") and (
        remove_requested or remove_worktree_on_complete(policy)
    ):
        keep_reason = worktree_keep_reason(root, run_record, force=force_release)
        if keep_reason:
            print(f"worktree kept: {keep_reason}")
        else:
            released = release_run_worktree(root, run_record, force=force_release)
            if released["error"]:
                print(f"worktree remove warning: {released['error']}")
            else:
                print("worktree removed")
            if released["branch_deleted"]:
                print(f"branch removed: {released['branch_deleted']}")
            elif released["branch_kept"]:
                print(
                    f"branch kept: {released['branch']} ({released['branch_kept']}); "
                    "pass --force to delete it"
                )
    save_state(root, state)
    print(f"Marked done: {args.run_id}")
    if task_id:
        report_rel = task_report_relpath(task_id, policy)
        written = "present" if task_report_exists(root, task_id, policy) else "not written"
        print(f"Task report (on demand): {report_rel} ({written})")
    print(
        "Release contract: implement run supplies [x], the Progress line, and CHANGELOG; "
        "teamlead owns the git commit before or after complete."
    )
    if run_record.get("worktree_path"):
        print(
            f"Merge from branch {run_record.get('worktree_branch', '?')} before deleting the worktree."
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-task", description="Opt-in multi-agent backlog orchestrator"
    )
    parser.add_argument(
        "--repo", help="Repository root. Defaults to current git repository."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Initialize .ai-task in the current repo")
    init_p.add_argument(
        "--force", action="store_true", help="Refresh generated defaults"
    )
    init_p.add_argument(
        "--worktrees",
        action="store_true",
        help="Force worktrees_enabled = true (default: true when cwd is a git repo)",
    )
    init_p.add_argument(
        "--no-worktrees",
        action="store_true",
        help="Set worktrees_enabled = false even in a git repo",
    )
    init_p.add_argument(
        "--ownership",
        choices=OWNERSHIP_CHOICES,
        default="auto",
        help=(
            "Whose repository this is. auto: own when origin "
            "matches own_remotes in the profile config, foreign otherwise. "
            "foreign keeps .ai-task/ out of git through .git/info/exclude."
        ),
    )
    init_p.set_defaults(func=init_repo)

    dor_p = sub.add_parser(
        "dor", help="Check backlog Definition of Ready (metadata and deps)"
    )
    dor_p.add_argument("--task-id", help="Check one task id only")
    dor_p.add_argument(
        "--all-tasks", action="store_true", help="Include done and deferred tasks"
    )
    dor_p.add_argument("--json", action="store_true", help="Print gaps as JSON")
    dor_p.set_defaults(func=dor_cmd)

    order_p = sub.add_parser(
        "backlog-order",
        help="List open tasks in execution order (explicit-deps: deps, then priority, then file)",
    )
    order_p.add_argument("--policy")
    order_p.add_argument(
        "--strict",
        action="store_true",
        help="When .ai-task exists: exit 1 if any open task fails DoR",
    )
    order_p.add_argument(
        "--json", action="store_true", help="Print ordered task objects as JSON"
    )
    order_p.add_argument(
        "--autonomous",
        action="store_true",
        help="Headless dispatch: exclude Agent: human (owner-only) tasks; list them separately",
    )
    order_p.set_defaults(func=backlog_order_cmd)

    plan_p = sub.add_parser("plan", help="Prepare prioritized task packets")
    plan_batch = plan_p.add_mutually_exclusive_group()
    plan_batch.add_argument("--batch", type=int)
    plan_batch.add_argument(
        "--auto-batch",
        action="store_true",
        help="Use policy [batch].auto_target as wave size cap",
    )
    plan_p.add_argument("--backend", default="auto")
    plan_p.add_argument("--policy")
    plan_p.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any open task fails DoR (metadata lines, deps, P0/P1 Risk)",
    )
    plan_p.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable batch with predictive review_stack fields",
    )
    plan_p.add_argument(
        "--bulk",
        action="store_true",
        help="Enforce delivery scenario handshake before planning",
    )
    plan_p.add_argument(
        "--no-bulk-check",
        action="store_true",
        help="Skip scenario handshake when --bulk is set (for testing or manual override)",
    )
    plan_p.add_argument(
        "--autonomous",
        action="store_true",
        help="Exclude Agent: human (owner-only) tasks from the batch; implied by --bulk",
    )
    plan_p.set_defaults(func=plan)

    parallel_p = sub.add_parser(
        "parallel-plan",
        help="Analyze batch for safe parallel waves (decision support for teamlead)",
    )
    parallel_batch = parallel_p.add_mutually_exclusive_group()
    parallel_batch.add_argument("--batch", type=int)
    parallel_batch.add_argument(
        "--auto-batch",
        action="store_true",
        help="Use policy [batch].auto_target as wave size cap",
    )
    parallel_p.add_argument("--policy")
    parallel_p.add_argument("--json", action="store_true")
    parallel_p.set_defaults(func=parallel_plan_cmd)

    decision_p = sub.add_parser(
        "decision", help="Teamlead decision journal for analytics"
    )
    decision_sub = decision_p.add_subparsers(dest="decision_action", required=True)
    dlog = decision_sub.add_parser("log", help="Append a decision record")
    dlog.add_argument("--phase", required=True)
    dlog.add_argument("--choice", required=True)
    dlog.add_argument("--reason", required=True)
    dlog.add_argument("--task-ids", help="Comma-separated task ids")
    dlog.add_argument("--run-ids", help="Comma-separated run ids")
    dlog.add_argument("--signals-json", help="JSON object with signals/evidence")
    dlog.add_argument("--json", action="store_true")
    dlog.set_defaults(func=decision_log_cmd)
    dresult = decision_sub.add_parser(
        "result", help="Set result and reflection on a decision"
    )
    dresult.add_argument(
        "decision_id", nargs="?", help="Decision id (default: latest pending)"
    )
    dresult.add_argument("result", choices=["good", "bad", "unknown", "pending"])
    dresult.add_argument("--reflection", default="")
    dresult.add_argument(
        "--force",
        action="store_true",
        help="Allow marking good when run_ids is empty (suppresses warning)",
    )
    dresult.set_defaults(func=decision_result_cmd)
    dreflect = decision_sub.add_parser(
        "reflect", help="Suggest results for pending decisions"
    )
    dreflect.add_argument("--since", metavar="DURATION", help="e.g. 7d")
    dreflect.add_argument("--json", action="store_true")
    dreflect.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if pending would be good without stored run_ids",
    )
    dreflect.set_defaults(func=decision_reflect_cmd)
    dcheck = decision_sub.add_parser(
        "check-overrides",
        help="Detect parallel-plan vs logged parallel choices",
    )
    dcheck.add_argument("--since", metavar="DURATION", help="e.g. 7d")
    dcheck.add_argument("--policy")
    dcheck.add_argument("--json", action="store_true")
    dcheck.add_argument(
        "--dry-run",
        action="store_true",
        help="Report overrides without updating decisions.jsonl",
    )
    dcheck.set_defaults(func=decision_check_overrides_cmd)
    danalytics = decision_sub.add_parser(
        "analytics", help="Aggregate decision outcomes"
    )
    danalytics.add_argument("--since", metavar="DURATION")
    danalytics.add_argument(
        "--trend",
        action="store_true",
        help="Print only the value trend across engagements/repos",
    )
    danalytics.add_argument(
        "--json", action="store_true", help="JSON to stdout (same as --format json)"
    )
    danalytics.add_argument(
        "--format",
        choices=["text", "json", "md", "html"],
        default="text",
        help="text, json, md (md+html files), or html (factual html+md files only)",
    )
    danalytics.set_defaults(func=decision_analytics_cmd)
    dingest = decision_sub.add_parser(
        "ingest",
        help="Propose judgment stubs from state.json (retries, verify fail, verdicts)",
    )
    dingest.add_argument("--since", metavar="DURATION", help="e.g. 30d")
    dingest.add_argument(
        "--dry-run",
        action="store_true",
        help="Print proposed stubs only (default when --apply is omitted)",
    )
    dingest.add_argument(
        "--apply",
        action="store_true",
        help="Append proposed stubs to decisions.jsonl (requires --confirm)",
    )
    dingest.add_argument(
        "--confirm",
        action="store_true",
        help="Acknowledge append; required with --apply",
    )
    dingest.add_argument("--json", action="store_true")
    dingest.set_defaults(func=decision_ingest_cmd)

    retro_p = sub.add_parser(
        "retro",
        help="Factual decision reports + retro packet for ai-task-retro",
    )
    retro_p.add_argument("--since", metavar="DURATION", help="e.g. 30d")
    retro_p.add_argument(
        "--open", action="store_true", help="Print file:// paths to reports and packet"
    )
    retro_p.set_defaults(func=retro_cmd)

    verdict_p = sub.add_parser(
        "verdict", help="Record delivery verdict on a run"
    )
    verdict_p.add_argument("run_id")
    verdict_p.add_argument("verdict", choices=list(VERDICT_VALUES))
    verdict_p.add_argument(
        "--reflection", default="", help="Optional note stored on the run record"
    )
    verdict_p.set_defaults(func=verdict_cmd)

    run_p = sub.add_parser("run", help="Start an agent run for an eligible task")
    run_p.add_argument(
        "task", nargs="?", help="Task id. Defaults to highest-priority eligible task."
    )
    run_p.add_argument("--backend", default="auto")
    run_p.add_argument("--policy")
    run_p.add_argument("--dry-run", action="store_true")
    run_p.add_argument(
        "--wait",
        action="store_true",
        help="Wait for completion and fall back on detected limit errors",
    )
    run_p.add_argument(
        "--confirm-risk",
        action="store_true",
        help="Allow run when review/risk gates match (P0/P1, risk keywords)",
    )
    run_p.add_argument(
        "--risk-ack",
        metavar="REASON",
        help=(
            "Clear risk-keyword gates only (not P0/P1 approval) with a logged "
            "reason; distinct from --confirm-risk"
        ),
    )
    run_p.add_argument(
        "--take-lease",
        action="store_true",
        help="Override an existing task lease held by another run",
    )
    run_p.add_argument(
        "--bulk",
        action="store_true",
        help="Enforce delivery scenario handshake before run; applies only when no specific task is given",
    )
    run_p.add_argument(
        "--no-bulk-check",
        action="store_true",
        help="Skip scenario handshake when --bulk is set",
    )
    run_p.add_argument(
        "--autonomous",
        action="store_true",
        help="Headless dispatch: exclude Agent: human tasks from default selection (implied when no task id is given); explicit run <id> is unaffected",
    )
    run_p.set_defaults(func=run)

    packet_p = sub.add_parser("packet", help="Regenerate task packets")
    packet_sub = packet_p.add_subparsers(dest="packet_action", required=True)
    refresh_p = packet_sub.add_parser(
        "refresh", help="Rebuild packet with pending inbox notes"
    )
    refresh_p.add_argument("task_id", help="Backlog task id")
    refresh_p.add_argument("--backend", default="auto")
    refresh_p.add_argument("--policy")
    refresh_p.set_defaults(func=packet_refresh)

    status_p = sub.add_parser("status", help="Show run and backend status")
    status_p.add_argument("--policy")
    status_p.add_argument(
        "--task", help="Backlog task id for routing hints (default: next eligible)"
    )
    status_p.add_argument(
        "--json", action="store_true", help="Machine-readable status snapshot"
    )
    status_p.add_argument(
        "--require-report",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    status_p.set_defaults(func=status)

    wait_runs_p = sub.add_parser(
        "wait-runs",
        help="Wait until named detached runs are no longer running or paused",
    )
    wait_runs_p.add_argument(
        "run_ids", nargs="+", help="Run ids returned by ai-task run"
    )
    wait_runs_p.add_argument("--policy")
    wait_runs_p.add_argument(
        "--interval", type=float, default=30.0, help="Polling interval in seconds"
    )
    wait_runs_p.add_argument(
        "--timeout", type=float, default=3600.0, help="Maximum wait time in seconds"
    )
    wait_runs_p.add_argument(
        "--json", action="store_true", help="Print final run statuses as JSON"
    )
    wait_runs_p.add_argument(
        "--resume-on-quota",
        action="store_true",
        help=(
            "Keep waiting through waiting_quota: sleep until the window resets "
            "(+resume_margin_seconds), probe Claude, and re-launch the same packet "
            "in the same worktree up to the resume_max_attempts budget"
        ),
    )
    wait_runs_p.set_defaults(func=wait_runs)

    scenario_p = sub.add_parser(
        "scenario", help="Delivery scenario handshake helpers"
    )
    scenario_sub = scenario_p.add_subparsers(dest="scenario_action", required=True)
    scenario_check_p = scenario_sub.add_parser(
        "check",
        help=(
            "Verify a fresh delivery_scenario:* decision is present in decisions.jsonl "
            "(or pass on policy [scenario] default)"
        ),
    )
    scenario_check_p.add_argument(
        "--max-stale-days",
        type=int,
        default=None,
        help=(
            "Max age in days before scenario is considered stale "
            f"(default: policy [scenario] stale_days, {SCENARIO_STALE_DAYS})"
        ),
    )
    scenario_check_p.add_argument("--json", action="store_true")
    scenario_check_p.set_defaults(func=scenario_check_cmd)

    cooldown_p = sub.add_parser(
        "cooldown", help="Inspect or clear backend cooldown state"
    )
    cooldown_sub = cooldown_p.add_subparsers(dest="cooldown_action")
    cooldown_clear = cooldown_sub.add_parser(
        "clear", help="Remove a backend cooldown entry"
    )
    cooldown_clear.add_argument("backend", help="Backend name from policy")
    cooldown_clear.add_argument("--policy")
    cooldown_clear.add_argument(
        "--force",
        action="store_true",
        help="Required; does not bypass vendor rate limits",
    )
    cooldown_clear.set_defaults(func=cooldown_cmd)

    worker_done_p = sub.add_parser(
        "worker-done",
        help="Record an in-session subagent's outcome on its run",
    )
    worker_done_p.add_argument("run_id")
    worker_done_p.add_argument("--outcome", required=True, choices=list(WORKER_OUTCOMES))
    worker_done_p.add_argument(
        "--agent-id",
        default="",
        help="Agent id the Agent tool returned; model and effort are read from that "
        "subagent's Claude Code transcript",
    )
    worker_done_p.add_argument(
        "--model", default="", help="Model the subagent ran on, when no transcript is read"
    )
    worker_done_p.add_argument(
        "--effort", default="", help="Reasoning effort, when no transcript is read"
    )
    worker_done_p.add_argument(
        "--final-file", default="", help="File holding the subagent's final answer"
    )
    worker_done_p.add_argument(
        "--final-text", default="", help="The subagent's final answer as text"
    )
    worker_done_p.add_argument("--note", default="", help="Short cause, e.g. for a failure")
    worker_done_p.add_argument("--policy")
    worker_done_p.set_defaults(func=worker_done_cmd)

    executor_p = sub.add_parser(
        "executor",
        help="Executor mode for a batch (headless or in_session) and whether to ask",
    )
    executor_p.add_argument("--tasks", type=int, default=1, help="Tasks in the batch")
    executor_p.add_argument("--waves", type=int, default=1, help="Waves in the batch")
    executor_p.add_argument(
        "--named",
        choices=list(EXECUTOR_MODES),
        help="Mode the owner's request names; it is never re-asked",
    )
    executor_p.add_argument(
        "--no-questions",
        action="store_true",
        help="An owner's intent forbids questions: take the default and report it",
    )
    executor_p.add_argument("--json", action="store_true")
    executor_p.add_argument("--policy")
    executor_p.set_defaults(func=executor_cmd)

    pin_p = sub.add_parser(
        "pin",
        help="Pin one backend for the whole wave (overrides Agent:, no fallback)",
    )
    pin_p.add_argument(
        "backend",
        nargs="?",
        help="Backend name, or auto to resolve the next task's worker once; omit to show the pin",
    )
    pin_p.add_argument(
        "--clear",
        action="store_true",
        help="Remove the wave-level backend pin",
    )
    pin_p.add_argument("--policy")
    pin_p.set_defaults(func=pin_cmd)

    quota_p = sub.add_parser(
        "quota", help="Inspect Claude subscription quota windows and reserve stop line"
    )
    quota_sub = quota_p.add_subparsers(dest="quota_action", required=True)
    quota_status_p = quota_sub.add_parser(
        "status",
        help="Report quota windows, used percent, reset, reserve stop line, freshness",
    )
    quota_status_p.add_argument("--policy")
    quota_status_p.add_argument(
        "--json", action="store_true", help="Machine-readable quota status"
    )
    quota_status_p.set_defaults(func=quota_cmd)

    quota_doctor_p = quota_sub.add_parser(
        "doctor",
        help="Explain why quota admission control did or did not gate (pass/fail per check)",
    )
    quota_doctor_p.add_argument("--policy")
    quota_doctor_p.add_argument(
        "--json", action="store_true", help="Machine-readable doctor report"
    )
    quota_doctor_p.set_defaults(func=quota_cmd)

    quota_probe_p = quota_sub.add_parser(
        "probe",
        help="Live global quota read (works without .ai-task/); pre-fan-out check",
    )
    quota_probe_p.add_argument(
        "--json", action="store_true", help="Machine-readable probe result"
    )
    quota_probe_p.set_defaults(func=quota_probe_cmd)

    quota_setup_p = quota_sub.add_parser(
        "setup-statusline",
        help="Print or check Claude Code statusLine wiring for quota snapshots",
    )
    quota_setup_p.add_argument("--policy")
    mode_group = quota_setup_p.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--global",
        dest="global_mode",
        action="store_true",
        help="Print repo-agnostic snippet for global settings (recommended)",
    )
    mode_group.add_argument(
        "--project",
        dest="project_mode",
        action="store_true",
        help="Print repo-local snippet with absolute --repo helper path",
    )
    quota_setup_p.add_argument(
        "--check",
        action="store_true",
        help="Validate helper presence and a fresh quota snapshot",
    )
    quota_setup_p.add_argument(
        "--json", action="store_true", help="Machine-readable setup check result"
    )
    quota_setup_p.set_defaults(func=quota_cmd)

    quota_refresh_p = quota_sub.add_parser(
        "refresh",
        help="Actively refresh the quota snapshot from configured headless sources",
    )
    quota_refresh_p.add_argument("--policy")
    quota_refresh_p.add_argument(
        "--force",
        action="store_true",
        help="Run a live-source refresh even when the current snapshot is fresh",
    )
    quota_refresh_p.add_argument(
        "--json", action="store_true", help="Machine-readable refresh result"
    )
    quota_refresh_p.set_defaults(func=quota_cmd)

    quota_stats_p = quota_sub.add_parser(
        "stats",
        help="Observed quota deltas (p50/p80/p95) by Size: and current vs recommended reservations",
    )
    quota_stats_p.add_argument("--policy")
    quota_stats_p.add_argument(
        "--json", action="store_true", help="Machine-readable calibration stats"
    )
    quota_stats_p.add_argument(
        "--include-low-confidence",
        action="store_true",
        help="Fold low-confidence (parallel/partial) samples into percentiles (less trustworthy)",
    )
    quota_stats_p.set_defaults(func=quota_cmd)

    quota_calibrate_p = quota_sub.add_parser(
        "calibrate",
        help="Suggest (or, with --apply, write) [quota.reservations] from observed telemetry",
    )
    quota_calibrate_p.add_argument("--policy")
    quota_calibrate_p.add_argument(
        "--json", action="store_true", help="Machine-readable calibration result"
    )
    quota_calibrate_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the suggested patch without writing (default behavior)",
    )
    quota_calibrate_p.add_argument(
        "--apply",
        action="store_true",
        help="Write the patch to policy (refused below [quota] calibration_min_samples; backs up first)",
    )
    quota_calibrate_p.set_defaults(func=quota_cmd)

    watch_p = sub.add_parser("watch", help="Tail run logs and show supervision signals")
    watch_p.add_argument("run_id")
    watch_p.add_argument("--lines", type=int, default=20)
    watch_p.add_argument(
        "--follow", action="store_true", help="Keep tailing until Ctrl+C"
    )
    watch_p.add_argument("--policy")
    watch_p.set_defaults(func=watch_run)

    test_p = sub.add_parser("self-test", help="Run built-in supervision checks")
    test_p.set_defaults(func=self_test_cmd)

    pause_p = sub.add_parser("pause", help="Pause a running process")
    pause_p.add_argument("run_id")
    pause_p.set_defaults(func=pause_run)

    stop_p = sub.add_parser("stop", help="Stop a running process")
    stop_p.add_argument("run_id")
    stop_p.set_defaults(func=lambda args: signal_run(args, signal.SIGTERM, "stopped"))

    resume_p = sub.add_parser("resume", help="Resume a paused process")
    resume_p.add_argument("run_id")
    resume_p.set_defaults(func=resume_run)

    sup_p = sub.add_parser(
        "supersede", help="Close a stale run record delivered by a later run"
    )
    sup_p.add_argument("run_id")
    sup_p.add_argument("--by", help="Run id that delivered the task instead")
    sup_p.add_argument("--reason", help="Why the stale record is closed")
    sup_p.set_defaults(func=supersede_run)

    note_p = sub.add_parser("note", help="Record a user note for active or future work")
    note_p.add_argument("message")
    note_p.add_argument("--run-id")
    note_p.add_argument(
        "--task-id", help="Backlog task id to attach note to (for next packet)"
    )
    note_p.add_argument(
        "--scope", choices=["queued", "running", "review", "future"], default="running"
    )
    note_p.set_defaults(func=note)

    verify_p = sub.add_parser(
        "verify", help="Run configured verify profile (lint/tests)"
    )
    verify_p.add_argument(
        "--run-id", help="Run id (preferred; writes verify-report.md)"
    )
    verify_p.add_argument(
        "--task-id", help="Resolve profile from task block; cwd is repo root"
    )
    verify_p.add_argument("--profile", help="Override profile for this invocation")
    verify_p.add_argument("--policy")
    verify_p.add_argument(
        "--dry-run", action="store_true", help="Print profile and commands only"
    )
    verify_p.add_argument(
        "--skip",
        action="store_true",
        help="Skip verify (only if allow_skip = true in policy)",
    )
    verify_p.set_defaults(func=verify_cmd)

    review_p = sub.add_parser("review", help="Create a review packet for a run")
    review_p.add_argument("run_id")
    review_p.add_argument("--policy")
    review_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve review_skills from run diff only; do not write review-packet.md",
    )
    review_p.add_argument(
        "--codex",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Add (or skip) the codex exec review pass for this call; "
            "default: [review.codex] enabled in the policy"
        ),
    )
    review_p.add_argument(
        "--codex-only",
        action="store_true",
        help=(
            "Run only the Codex pass and update review-findings.md; "
            "leave the packet, run status and review queue as they are"
        ),
    )
    codex_target = review_p.add_mutually_exclusive_group()
    codex_target.add_argument(
        "--codex-base", metavar="BRANCH", help="Codex pass target: changes against BRANCH"
    )
    codex_target.add_argument(
        "--codex-commit",
        metavar="SHA",
        help="Codex pass target: the changes of one commit (a merged run)",
    )
    review_p.set_defaults(func=review)

    cleanup_p = sub.add_parser("cleanup", help="Record conservative cleanup candidates")
    cleanup_p.add_argument("--dry-run", action="store_true")
    cleanup_p.add_argument(
        "--remove-worktrees",
        action="store_true",
        help="Remove git worktrees for stale runs that recorded worktree_path",
    )
    cleanup_p.add_argument(
        "--force",
        action="store_true",
        help=(
            "With --remove-worktrees, also remove worktrees that are guarded: "
            "uncommitted changes in the working tree, or a branch with commits "
            "ahead of the default branch. Discards that work"
        ),
    )
    cleanup_p.set_defaults(func=cleanup)

    prune_p = sub.add_parser(
        "prune",
        help="Remove finished run dirs and state (done/dry_run; destructive with --yes)",
    )
    prune_p.add_argument("--run-id", help="Prune one run id")
    prune_p.add_argument(
        "--older-than",
        metavar="DURATION",
        help="Prune runs finished before now-DURATION (e.g. 7d, 24h)",
    )
    prune_p.add_argument(
        "--keep-last",
        type=int,
        metavar="N",
        help="Per task_id, keep N newest prune-eligible runs",
    )
    prune_p.add_argument(
        "--include-failed",
        action="store_true",
        help="Also prune runs in failed status",
    )
    prune_p.add_argument(
        "--cleanup-reports",
        action="store_true",
        help="Remove cleanup-*.json older than --older-than",
    )
    prune_p.add_argument(
        "--dry-run", action="store_true", help="List targets without deleting"
    )
    prune_p.add_argument("--yes", action="store_true", help="Confirm destructive prune")
    prune_p.set_defaults(func=prune_runs)

    policy_p = sub.add_parser(
        "policy", help="Inspect or sync policy and backend availability"
    )
    policy_p.add_argument(
        "action",
        choices=["show", "path", "backends", "sync"],
        nargs="?",
        default="show",
    )
    policy_p.add_argument("--policy", default="default")
    policy_p.add_argument(
        "--dry-run",
        action="store_true",
        help="With sync: print merge diff without writing policy",
    )
    policy_p.add_argument(
        "--force",
        action="store_true",
        help="With sync: overwrite all bundled fields from template (local-only keys kept)",
    )
    policy_p.set_defaults(func=policy_cmd)

    done_p = sub.add_parser("complete", help="Mark a run done in .ai-task state")
    done_p.add_argument("run_id")
    done_p.add_argument("--policy")
    done_p.add_argument(
        "--remove-worktree",
        action="store_true",
        help=(
            "Run git worktree remove for this run after marking done, and "
            "delete its ai-task/ branch when the branch has no commits ahead"
        ),
    )
    done_p.add_argument(
        "--force",
        action="store_true",
        help=(
            "With --remove-worktree, also delete the run branch when it has "
            "commits ahead of the default branch. Discards those commits"
        ),
    )
    done_p.add_argument(
        "--require-report",
        action="store_true",
        help=(
            "Exit 1 when the task report (tasks/<TASK-ID>.md by default) is missing "
            "for this run's task. Reports are optional unless this flag is passed"
        ),
    )
    done_p.set_defaults(func=complete)

    report_p = sub.add_parser(
        "report",
        help="Generate rich HTML analytics report to .ai-task/reports/report.html",
    )
    report_p.add_argument("--output", metavar="FILE", help="Override output path.")
    report_p.add_argument(
        "--since",
        metavar="SPEC",
        default=None,
        help=(
            "Filter run-timeline sections to runs >= cutoff; backlog table always full-repo. "
            "SPEC: (1) relative — '7d', '24h', '30m'; "
            "(2) date only — 'YYYY-MM-DD' (00:00:00 UTC on that day); "
            "(3) ISO-8601 datetime — '2026-05-20T14:00:00Z' or '2026-05-20T14:00:00+03:00' "
            "(naive datetime treated as UTC). "
            "Mutually exclusive with --last."
        ),
    )
    report_p.add_argument(
        "--last",
        metavar="N",
        type=int,
        default=None,
        help=(
            "Keep only the N most recent runs (by created_at, tie-break run_sort_key). "
            "Use when you want «last five deliveries» instead of a calendar window. "
            "Mutually exclusive with --since."
        ),
    )
    report_p.set_defaults(func=report_cmd)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0
