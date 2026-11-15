"""Decision journal domain for the ai-task CLI.

`decisions.jsonl` IO and settings, scenario confirmations, SLO gates, the
decision analytics core (judgment quality, delivery metrics, value
scorecard/trend, recurrence over rotated backlog archives), ingest stubs,
parallel-override auditing (including the parallel-batch analyzer shared
with the `parallel-plan` command), journal credibility flags, and the
factual MD/HTML report renderers.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from ai_task._shared import app_path, die, now
from ai_task.backlog import (
    Task,
    archive_task_files,
    parse_backlog,
    parse_backlog_blocks,
    parse_task_files,
    risk_gates,
)
from ai_task.policy import read_config, read_policy
from ai_task.quota import (
    is_high_confidence_sample,
    quota_telemetry_repo_id,
    read_quota_telemetry_samples,
    sample_observed_delta,
)
from ai_task.runs import (
    POLICY_DRIFT_CHOICE,
    SCOPE_ACK_CHOICE,
    enrich_signals_with_predictions,
    overhead_ratio_cell,
    parse_iso_timestamp,
    primary_backend_names,
    run_reference_time,
    run_sort_key,
    worktrees_enabled,
)
from ai_task.scheduling import (
    build_parallel_waves,
    parallel_policy,
    task_scope_signals,
)
from ai_task.state import load_state

VERDICT_VALUES = ("approve", "rework", "split", "defer", "escalate")
INGEST_VERDICT_CHOICES = frozenset({"rework", "split", "escalate"})


# journal choices that mean the operator stepped in (vs the run
# flowing clean). Counted only for judgment rows (machine auto-stubs excluded),
# plus any choice starting with ``override_`` (override_parallel_plan, etc.).
INTERVENTION_CHOICES = frozenset({"escalate", "confirm_risk"})
# a trend bucket (an engagement window) with fewer than this many
# delivered runs is labelled ``insufficient`` and never trend-lined — too thin to
# read a ratio off. A trend with <2 sufficient buckets is "insufficient history".
TREND_MIN_DELIVERED = 3


IMPLICIT_RETRY_STATUSES = frozenset({"failed", "needs_review"})


def decisions_path(root: Path) -> Path:
    return app_path(root) / "decisions.jsonl"


def read_decisions(root: Path) -> list[dict[str, Any]]:
    path = decisions_path(root)
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def write_decisions(root: Path, entries: list[dict[str, Any]]) -> None:
    path = decisions_path(root)
    lines = [json.dumps(entry, ensure_ascii=False) for entry in entries]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def append_decision(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    path = decisions_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def decisions_settings(policy: dict[str, Any]) -> dict[str, Any]:
    section = policy.get("decisions", {})
    return section if isinstance(section, dict) else {}


def auto_log_anomalies_enabled(policy: dict[str, Any]) -> bool:
    return bool(decisions_settings(policy).get("auto_log_anomalies", True))


def slo_policy(policy: dict[str, Any]) -> dict[str, Any]:
    section = policy.get("slo", {})
    return section if isinstance(section, dict) else {}


def check_slo_gates(
    delivery: dict[str, Any] | None,
    *,
    policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return list of SLO gate violations with recommended next actions.

    Each violation: {code, message, recommendation, value, threshold}
    """
    slo = slo_policy(policy or {})
    max_rework = float(slo.get("max_rework_rate", SLO_DEFAULT_MAX_REWORK_RATE))
    max_retry_rate = float(
        slo.get("max_implicit_retry_rate", SLO_DEFAULT_MAX_IMPLICIT_RETRY_RATE)
    )
    max_no_verdict = int(
        slo.get("max_runs_without_verdict", SLO_DEFAULT_MAX_RUNS_WITHOUT_VERDICT)
    )
    max_failed = int(slo.get("max_failed_runs", SLO_DEFAULT_MAX_FAILED_RUNS))

    violations: list[dict[str, Any]] = []
    if not isinstance(delivery, dict):
        return violations

    rework_rate = delivery.get("rework_rate")
    if isinstance(rework_rate, (int, float)) and rework_rate > max_rework:
        violations.append(
            {
                "code": "slo_high_rework_rate",
                "message": f"rework_rate {rework_rate:.0%} exceeds SLO threshold {max_rework:.0%}",
                "recommendation": "pause wave → run retro → handoff to product for backlog/DoR fixes",
                "value": rework_rate,
                "threshold": max_rework,
            }
        )

    runs_in_window = int(delivery.get("runs_in_window", 0))
    implicit_retry_count = int(delivery.get("implicit_retry_count", 0))
    if runs_in_window > 0:
        implicit_retry_rate = implicit_retry_count / runs_in_window
        if implicit_retry_rate > max_retry_rate:
            violations.append(
                {
                    "code": "slo_high_implicit_retry_rate",
                    "message": (
                        f"implicit retry rate {implicit_retry_rate:.0%} exceeds SLO threshold {max_retry_rate:.0%} "
                        f"({implicit_retry_count}/{runs_in_window} tasks with retries)"
                    ),
                    "recommendation": "run retro to investigate recurring failures; check verify/policy config",
                    "value": implicit_retry_rate,
                    "threshold": max_retry_rate,
                }
            )

    runs_without_verdict = int(delivery.get("runs_without_verdict", 0))
    if runs_without_verdict > max_no_verdict:
        violations.append(
            {
                "code": "slo_many_runs_without_verdict",
                "message": (
                    f"{runs_without_verdict} runs missing verdict exceed SLO threshold {max_no_verdict}"
                ),
                "recommendation": "run verdict for pending runs before next wave to maintain audit trail",
                "value": runs_without_verdict,
                "threshold": max_no_verdict,
            }
        )

    failed_runs = int(delivery.get("failed_runs", 0))
    if failed_runs > max_failed:
        violations.append(
            {
                "code": "slo_many_failed_runs",
                "message": f"{failed_runs} failed runs exceed SLO threshold {max_failed}",
                "recommendation": "investigate failures; check policy, backend health, or run maintainer intervention",
                "value": failed_runs,
                "threshold": max_failed,
            }
        )

    return violations


def _policy_drift_already_logged(root: Path, drift: list[dict[str, Any]]) -> bool:
    """True when the latest drift row already covers this exact fingerprint."""
    fingerprint = sorted((str(e["path"]), str(e["kind"])) for e in drift)
    for existing in reversed(read_decisions(root)):
        if not isinstance(existing, dict):
            continue
        if str(existing.get("choice", "")) != POLICY_DRIFT_CHOICE:
            continue
        signals = existing.get("signals")
        if not isinstance(signals, dict):
            return False
        return (
            # strict=False: a malformed prior record must compare unequal here,
            # not raise out of a boolean check.
            sorted(
                zip(
                    signals.get("files", []),
                    signals.get("file_kinds", []),
                    strict=False,
                )
            )
            == fingerprint
        )
    return False


def scope_ack_logged(root: Path, run_id: str) -> bool:
    """True when an operator scope_ack decision row references this run."""
    for entry in read_decisions(root):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("choice", "")) != SCOPE_ACK_CHOICE:
            continue
        run_ids = entry.get("run_ids") or []
        if isinstance(run_ids, list) and run_id in {str(item) for item in run_ids}:
            return True
    return False


def find_latest_delivery_scenario(root: Path) -> tuple[str | None, str | None]:
    """Return (choice, at) for the most recent delivery_scenario:* decision, or (None, None)."""
    entries = read_decisions(root)
    found_choice: str | None = None
    found_at: str | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        choice = entry.get("choice", "")
        if not isinstance(choice, str) or not choice.startswith("delivery_scenario:"):
            continue
        at_raw = entry.get("at", "")
        if found_at is None or (at_raw and at_raw > found_at):
            found_choice = choice
            found_at = at_raw
    return found_choice, found_at


SCENARIO_STALE_DAYS = 7
# Scenario ids the teamlead picker can confirm; [scenario] default
# must be one of these to count.
VALID_SCENARIO_IDS = (
    "wave_full",
    "wave_monolithic",
    "wave_monolithic_sequential",
    "single_next",
    "isolated_worktree_batch",
)


def scenario_settings(policy: dict[str, Any]) -> dict[str, Any]:
    section = policy.get("scenario", {})
    return section if isinstance(section, dict) else {}


def scenario_stale_days(policy: dict[str, Any]) -> float:
    """Staleness window in days from policy [scenario] stale_days."""
    raw = scenario_settings(policy).get("stale_days", SCENARIO_STALE_DAYS)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(SCENARIO_STALE_DAYS)
    return value if value > 0 else float(SCENARIO_STALE_DAYS)


def scenario_policy_default(policy: dict[str, Any]) -> tuple[str, str]:
    """Return (default_id, warning) for policy [scenario] default.

    default_id is "" when unset; warning is set when the configured value is not
    a valid scenario id (then treated as unset).
    """
    raw = scenario_settings(policy).get("default", "")
    candidate = raw.strip() if isinstance(raw, str) else ""
    if not candidate:
        return "", ""
    if candidate not in VALID_SCENARIO_IDS:
        return "", (
            f"[scenario] default '{candidate}' is not a valid scenario id "
            f"(valid: {', '.join(VALID_SCENARIO_IDS)}) — treating as unset"
        )
    return candidate, ""


def check_bulk_scenario_confirmed(
    root: Path,
    *,
    max_stale_days: float | None = None,
    policy: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Return (ok, reason).

    ok=True when a fresh delivery_scenario:* decision exists (within
    max_stale_days, default policy [scenario] stale_days) — a fresh explicit
    decision always wins. Otherwise, when policy [scenario] default names a
    valid scenario id, ok=True with a one-line announcement.
    ok=False with a human-readable reason otherwise.
    """
    if policy is None:
        policy = read_policy(root)
    if max_stale_days is None:
        max_stale_days = scenario_stale_days(policy)
    default_id, default_warning = scenario_policy_default(policy)
    if default_warning:
        print(f"warning: {default_warning}", file=sys.stderr)

    choice, at_raw = find_latest_delivery_scenario(root)
    if choice is None:
        failure = (
            "no delivery_scenario:* found in decisions.jsonl — run the scenario picker in teamlead first "
            "(or skip with --no-bulk-check if the scenario is stored elsewhere)"
        )
    else:
        try:
            recorded_at = parse_iso_timestamp(at_raw or "")
        except Exception:  # noqa: BLE001 - best-effort timestamp read
            recorded_at = None
        if recorded_at is None:
            failure = f"delivery_scenario:* entry has invalid timestamp '{at_raw}'"
        else:
            age_days = (
                dt.datetime.now(dt.timezone.utc) - recorded_at
            ).total_seconds() / 86400.0
            if age_days <= max_stale_days:
                return True, f"confirmed ({choice}, recorded {at_raw})"
            failure = (
                f"delivery_scenario:* is stale ({age_days:.0f}d old, limit {max_stale_days:.0f}d) — "
                "re-run the scenario picker or mini-interview in teamlead "
                "(or skip with --no-bulk-check if the scenario is still valid)"
            )
    if default_id:
        return True, (
            f"running {default_id} (policy [scenario] default); "
            "say «настрой сценарий» to change"
        )
    return False, failure


def is_machine_decision(entry: dict[str, Any]) -> bool:
    """True for machine-emitted telemetry rows (``signals.auto`` truthy).

    Operator judgment rows (manual ``decision log``; ``signals.auto`` absent
    or false) return False.
    """
    if not isinstance(entry, dict):
        return False
    signals = entry.get("signals")
    return isinstance(signals, dict) and bool(signals.get("auto"))


QUOTA_BLIND_DISPATCH_CHOICE = "quota_blind_dispatch"


def decision_wave_key(state: dict[str, Any] | None) -> str:
    """Wave identity for telemetry dedupe: the planned batch task ids."""
    if not isinstance(state, dict):
        return ""
    last_batch = state.get("last_batch")
    if not isinstance(last_batch, list):
        return ""
    return ",".join(str(item) for item in last_batch)


def collapse_repeat_quota_blind_dispatch(
    root: Path, entry: dict[str, Any]
) -> dict[str, Any] | None:
    """Collapse repeated identical quota_blind_dispatch rows within one wave.

    Identical = the most recent quota_blind_dispatch row in the journal has
    the same phase, the same reason, the same wave key (``signals.wave``),
    and is still pending. The surviving row bumps ``signals.count``, unions
    ``task_ids``/``run_ids``, and records ``signals.last_at`` instead of
    appending another telemetry duplicate. Returns the updated
    row, or None when no collapse target exists.
    """
    signals = entry.get("signals")
    if not isinstance(signals, dict):
        return None
    entries = read_decisions(root)
    for existing in reversed(entries):
        if not isinstance(existing, dict):
            continue
        if str(existing.get("choice", "")) != QUOTA_BLIND_DISPATCH_CHOICE:
            continue
        prev_signals = existing.get("signals")
        if (
            not isinstance(prev_signals, dict)
            or not prev_signals.get("auto")
            or str(existing.get("phase", "")) != str(entry.get("phase", ""))
            or str(existing.get("reason", "")) != str(entry.get("reason", ""))
            or str(prev_signals.get("wave", "")) != str(signals.get("wave", ""))
            or existing.get("result") != "pending"
        ):
            return None
        try:
            count = int(prev_signals.get("count", 1) or 1)
        except (TypeError, ValueError):
            count = 1
        prev_signals["count"] = count + 1
        prev_signals["last_at"] = entry.get("at")
        for key in ("task_ids", "run_ids"):
            merged = [str(item) for item in (existing.get(key) or []) if item]
            for value in entry.get(key) or []:
                if str(value) not in merged:
                    merged.append(str(value))
            existing[key] = merged
        existing["signals"] = prev_signals
        write_decisions(root, entries)
        return existing
    return None


def prior_run_count_for_task(
    state: dict[str, Any], task_id: str, *, exclude_run_id: str | None = None
) -> int:
    count = 0
    for run_id, run in state.get("runs", {}).items():
        if exclude_run_id and run_id == exclude_run_id:
            continue
        if run.get("task_id") == task_id:
            count += 1
    return count


def is_limit_fallback_backend(
    task: Task, policy: dict[str, Any], backend_name: str
) -> bool:
    routing = policy.get("routing", {})
    fallbacks = set(routing.get("limit_fallback_order", ["cursor_auto"]))
    primaries = set(primary_backend_names(task, policy))
    return backend_name in fallbacks and backend_name not in primaries


DECISION_RUN_STATUSES = frozenset({"done", "needs_review", "failed", "running"})


def resolve_decision_run_ids(
    state: dict[str, Any],
    task_ids: list[str],
    explicit_run_ids: list[str] | None = None,
) -> list[str]:
    if explicit_run_ids:
        return list(explicit_run_ids)
    if not task_ids:
        return []
    task_set = set(task_ids)
    eligible: list[tuple[str, dict[str, Any]]] = []
    for run_id, run in state.get("runs", {}).items():
        if run.get("task_id") not in task_set:
            continue
        if run.get("status") not in DECISION_RUN_STATUSES:
            continue
        eligible.append((run_id, run))
    if not eligible:
        return []

    def run_sort_key(item: tuple[str, dict[str, Any]]) -> tuple[str, str]:
        run_id, run = item
        stamp = str(run.get("created_at") or run.get("started_at") or run_id)
        return (stamp, run_id)

    last_batch = state.get("last_batch") or []
    if sorted(task_ids) == sorted(last_batch):
        return [run_id for run_id, _ in sorted(eligible, key=run_sort_key)]

    latest_by_task: dict[str, tuple[str, str]] = {}
    for run_id, run in eligible:
        task_id = str(run.get("task_id", ""))
        stamp = str(run.get("created_at") or run.get("started_at") or run_id)
        prev = latest_by_task.get(task_id)
        if prev is None or stamp > prev[1]:
            latest_by_task[task_id] = (run_id, stamp)
    return [
        latest_by_task[task_id][0] for task_id in task_ids if task_id in latest_by_task
    ]


REWORK_RATE_WARN_THRESHOLD = 0.3
PENDING_STALE_DAYS = 7
EMPTY_REASON_WARN_RATIO = 0.2
DUPLICATE_REFLECTION_WARN_RATIO = 0.5

# Recurrence / sibling-rate: share of delivered backlog tasks that fix a
# sibling/regression of earlier work rather than generalize. Defaults are
# overridable via policy [analytics] (markers, warn rate, backlog path).
SIBLING_RATE_WARN_THRESHOLD = 0.5
DEFAULT_SIBLING_MARKERS = (
    "sibling of",
    "regression of",
    "root cause of",
    "re-drift",
)
# Rotated backlog archives (sdlc-backlog-rotate skill). AUDIT readers only —
# recurrence_metrics and the analytics report merge these so delivered history
# survives rotation. Delivery-path readers (`plan`,
# `backlog-order`, `dor`) schedule from the active BACKLOG.md only and must
# never read the archive. Overridable via policy [analytics] archive_glob.
DEFAULT_BACKLOG_ARCHIVE_GLOB = "backlog/archive/BACKLOG-*.md"

# SLO default thresholds — override in policy [slo] section
SLO_DEFAULT_MAX_REWORK_RATE = 0.5
SLO_DEFAULT_MAX_IMPLICIT_RETRY_RATE = 0.5
SLO_DEFAULT_MAX_RUNS_WITHOUT_VERDICT = 5
SLO_DEFAULT_MAX_FAILED_RUNS = 3
EXPECTED_JUDGMENT_PHASES = (
    "plan",
    "assign",
    "parallel",
    "verify",
    "delivery",
    "verdict",
    "review",
    "cross",
)


def html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def judgment_quality_metrics(entries: list[dict[str, Any]]) -> dict[str, Any]:
    empty_reason_count = 0
    override_count = 0
    auto_count = 0
    manual_count = 0
    phases_seen: set[str] = set()
    reflections: list[str] = []
    for entry in entries:
        reason = str(entry.get("reason", "") or "").strip()
        if not reason:
            empty_reason_count += 1
        phase = str(entry.get("phase", "") or "").strip().lower()
        if phase:
            phases_seen.add(phase)
        choice = str(entry.get("choice", "") or "").strip()
        signals = entry.get("signals")
        is_override = choice.lower().startswith("override_")
        if isinstance(signals, dict) and signals.get("override"):
            is_override = True
        if is_override:
            override_count += 1
        if isinstance(signals, dict) and "auto" in signals:
            if signals.get("auto"):
                auto_count += 1
            else:
                manual_count += 1
        else:
            manual_count += 1
        reflection = str(entry.get("reflection", "") or "").strip()
        # Duplicate-reflection measures operator judgment hygiene; machine
        # telemetry rows are excluded so auto duplicates do not lead the
        # count.
        if reflection and not is_machine_decision(entry):
            reflections.append(reflection)
    reflection_counts: dict[str, int] = {}
    for reflection in reflections:
        reflection_counts[reflection] = reflection_counts.get(reflection, 0) + 1
    duplicate_reflection_count = sum(
        count - 1 for count in reflection_counts.values() if count > 1
    )
    expected = set(EXPECTED_JUDGMENT_PHASES)
    phases_present = sorted(phases_seen & expected)
    phases_missing = sorted(expected - phases_seen)
    auto_manual_total = auto_count + manual_count
    auto_vs_manual_ratio: float | None = None
    if auto_manual_total:
        auto_vs_manual_ratio = round(auto_count / auto_manual_total, 4)
    return {
        "empty_reason_count": empty_reason_count,
        "duplicate_reflection_count": duplicate_reflection_count,
        "reflection_count": len(reflections),
        "phases_present": phases_present,
        "phases_missing": phases_missing,
        "override_count": override_count,
        "auto_count": auto_count,
        "manual_count": manual_count,
        "auto_vs_manual_ratio": auto_vs_manual_ratio,
    }


def decision_report_insights(
    entries: list[dict[str, Any]],
    delivery: dict[str, Any] | None,
    recurrence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Weekly trends, regrets, and stale-pending measure operator judgment;
    # machine telemetry rows (signals.auto) are excluded so they do not
    # drown real judgment debt.
    judgment_entries = [
        entry
        for entry in entries
        if isinstance(entry, dict) and not is_machine_decision(entry)
    ]
    weekly: dict[str, dict[str, int]] = {}
    top_regrets: list[dict[str, Any]] = []
    stale_pending: list[dict[str, Any]] = []
    now_utc = dt.datetime.now(dt.timezone.utc)
    for entry in judgment_entries:
        raw_at = str(entry.get("at", "") or "")
        try:
            stamp = parse_iso_timestamp(raw_at)
        except (ValueError, TypeError):
            continue
        week = stamp.strftime("%Y-W%W")
        bucket = weekly.setdefault(
            week, {"good": 0, "bad": 0, "unknown": 0, "pending": 0}
        )
        result = str(entry.get("result", "pending"))
        if result not in bucket:
            result = "unknown"
        bucket[result] += 1
        reflection = str(entry.get("reflection", "") or "").strip()
        if result == "bad" and reflection:
            top_regrets.append(
                {
                    "id": entry.get("id"),
                    "at": raw_at,
                    "phase": entry.get("phase"),
                    "choice": entry.get("choice"),
                    "reflection": reflection,
                }
            )
        if result == "pending":
            age_days = (now_utc - stamp).days
            if age_days >= PENDING_STALE_DAYS:
                stale_pending.append(
                    {
                        "id": entry.get("id"),
                        "at": raw_at,
                        "age_days": age_days,
                        "phase": entry.get("phase"),
                        "choice": entry.get("choice"),
                        "reason": str(entry.get("reason", "") or "")[:300],
                    }
                )
    top_regrets.sort(key=lambda item: str(item.get("at", "")), reverse=True)
    stale_pending.sort(key=lambda item: int(item.get("age_days", 0)), reverse=True)
    warnings: list[dict[str, Any]] = []
    if delivery:
        rate = delivery.get("rework_rate")
        if isinstance(rate, (int, float)) and rate >= REWORK_RATE_WARN_THRESHOLD:
            warnings.append(
                {
                    "code": "high_rework_rate",
                    "message": f"rework_rate {rate} >= {REWORK_RATE_WARN_THRESHOLD}",
                }
            )
        verify = delivery.get("verify", {})
        if isinstance(verify, dict) and verify.get("failed", 0) > verify.get(
            "passed", 0
        ):
            warnings.append(
                {
                    "code": "verify_failures_exceed_passes",
                    "message": "more failed verify runs than passed in window",
                }
            )
        implicit_retry = delivery.get("implicit_retry_count", 0)
        rate = delivery.get("rework_rate")
        if (
            isinstance(implicit_retry, int)
            and implicit_retry > 0
            and (rate is None or rate == 0 or rate == 0.0)
        ):
            warnings.append(
                {
                    "code": "implicit_rework_detected",
                    "message": "formal rework zero but retries detected",
                }
            )
    if isinstance(recurrence, dict) and recurrence.get("available"):
        rate = recurrence.get("sibling_rate")
        threshold = recurrence.get("threshold", SIBLING_RATE_WARN_THRESHOLD)
        if (
            isinstance(rate, (int, float))
            and isinstance(threshold, (int, float))
            and threshold > 0
            and rate >= threshold
        ):
            warnings.append(
                {
                    "code": "high_sibling_rate",
                    "message": (
                        f"sibling_rate {rate:.0%} >= {threshold:.0%} "
                        f"({recurrence.get('recurrence_count', 0)}/"
                        f"{recurrence.get('delivered_count', 0)} delivered tasks are "
                        "siblings/regressions, not generalized fixes)"
                    ),
                }
            )
    if isinstance(recurrence, dict):
        # Archive read failures: recurrence degraded to the
        # readable backlog files; keep the gap visible in reports and retro.
        for archive_warning in recurrence.get("archive_warnings") or []:
            warnings.append(
                {
                    "code": "backlog_archive_unreadable",
                    "message": str(archive_warning),
                }
            )
    judgment_quality = judgment_quality_metrics(entries)
    total = len(entries)
    if total:
        empty_rate = judgment_quality["empty_reason_count"] / total
        if empty_rate > EMPTY_REASON_WARN_RATIO:
            warnings.append(
                {
                    "code": "high_empty_reason_rate",
                    "message": (
                        f"empty reasons {judgment_quality['empty_reason_count']}/{total} "
                        f"({empty_rate:.0%}) > {EMPTY_REASON_WARN_RATIO:.0%}"
                    ),
                }
            )
    reflection_count = judgment_quality.get("reflection_count", 0)
    if reflection_count:
        dup_rate = judgment_quality["duplicate_reflection_count"] / reflection_count
        if dup_rate > DUPLICATE_REFLECTION_WARN_RATIO:
            warnings.append(
                {
                    "code": "high_duplicate_reflection_rate",
                    "message": (
                        f"duplicate reflections "
                        f"{judgment_quality['duplicate_reflection_count']}/{reflection_count} "
                        f"({dup_rate:.0%}) > {DUPLICATE_REFLECTION_WARN_RATIO:.0%}"
                    ),
                }
            )
    return {
        "weekly_trends": dict(sorted(weekly.items())),
        "top_regrets": top_regrets[:10],
        "stale_pending": stale_pending[:20],
        "judgment_quality": judgment_quality,
        "warnings": warnings,
    }


def decision_analytics(root: Path, *, since_days: int | None = None) -> dict[str, Any]:
    """Aggregate the decision journal.

    Headline metrics (``pending``, ``by_phase``, ``by_choice``) cover operator
    judgment rows only; machine telemetry rows (``signals.auto``) are counted
    separately under ``machine``.
    """
    entries = read_decisions(root)
    if since_days is not None:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=since_days)
        filtered = []
        for entry in entries:
            try:
                stamp = parse_iso_timestamp(str(entry.get("at", "")))
            except (ValueError, TypeError):
                continue
            if stamp >= cutoff:
                filtered.append(entry)
        entries = filtered
    judgment_entries: list[dict[str, Any]] = []
    machine_entries: list[dict[str, Any]] = []
    for entry in entries:
        if is_machine_decision(entry):
            machine_entries.append(entry)
        else:
            judgment_entries.append(entry)
    by_phase: dict[str, dict[str, int]] = {}
    by_choice: dict[str, dict[str, int]] = {}
    pending = 0
    for entry in judgment_entries:
        phase = str(entry.get("phase", "unknown"))
        choice = str(entry.get("choice", "unknown"))
        result = str(entry.get("result", "pending"))
        by_phase.setdefault(phase, {"good": 0, "bad": 0, "unknown": 0, "pending": 0})
        by_choice.setdefault(choice, {"good": 0, "bad": 0, "unknown": 0, "pending": 0})
        if result not in by_phase[phase]:
            result = "unknown"
        by_phase[phase][result] += 1
        by_choice[choice][result] += 1
        if result == "pending":
            pending += 1
    # Authorship breakdown: rows per operator across ALL rows in the
    # window (judgment + machine). Legacy rows without the field count as
    # "unknown" — cheap visibility for the two-operator case, not full grouping.
    by_operator: dict[str, int] = {}
    for entry in entries:
        operator = str(entry.get("operator", "") or "").strip() or "unknown"
        by_operator[operator] = by_operator.get(operator, 0) + 1
    machine_by_choice: dict[str, int] = {}
    machine_pending = 0
    machine_events = 0
    for entry in machine_entries:
        choice = str(entry.get("choice", "unknown"))
        machine_by_choice[choice] = machine_by_choice.get(choice, 0) + 1
        signals = entry.get("signals")
        count = 1
        if isinstance(signals, dict):
            try:
                count = max(1, int(signals.get("count", 1) or 1))
            except (TypeError, ValueError):
                count = 1
        machine_events += count
        if str(entry.get("result", "pending")) == "pending":
            machine_pending += 1
    payload: dict[str, Any] = {
        "total": len(entries),
        "judgment_total": len(judgment_entries),
        "pending": pending,
        "by_phase": by_phase,
        "by_choice": by_choice,
        "by_operator": by_operator,
        "machine": {
            "total": len(machine_entries),
            "pending": machine_pending,
            "events": machine_events,
            "by_choice": machine_by_choice,
        },
        "entries": entries,
    }
    policy: dict[str, Any] | None = None
    try:
        policy = read_policy(root)
    except Exception:  # noqa: BLE001 - analytics must render without a policy
        policy = None
    delivery: dict[str, Any] | None = None
    if (app_path(root) / "state.json").exists():
        delivery = delivery_metrics(root, since_days=since_days)
        payload["delivery"] = delivery
        # per-engagement value scorecard (cost next to benefit).
        # Reuses the already-windowed delivery + journal entries so it costs no
        # extra state/journal read.
        payload["scorecard"] = value_scorecard(
            root,
            since_days=since_days,
            delivery=delivery,
            entries=entries,
            policy=policy,
        )
        # roll the scorecard across engagements over time + by repo.
        # Reuses the already-read entries + the pooled telemetry plumbing; no new
        # storage. Cost can be cross-repo (pooled telemetry repo_id); benefit is
        # per-repo (this repo's state/journal) — see value_trend docstring.
        payload["value_trend"] = value_trend(
            root,
            since_days=since_days,
            entries=entries,
            policy=policy,
        )
    recurrence = recurrence_metrics(root, policy=policy)
    payload["recurrence"] = recurrence
    payload["report"] = decision_report_insights(entries, delivery, recurrence)
    payload["slo_violations"] = check_slo_gates(delivery, policy=policy)
    return payload


def delivery_metrics(root: Path, *, since_days: int | None = None) -> dict[str, Any]:
    state = load_state(root)
    runs = state.get("runs", {})
    if not isinstance(runs, dict):
        runs = {}
    cutoff: dt.datetime | None = None
    if since_days is not None:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=since_days)
    filtered: list[dict[str, Any]] = []
    for run in runs.values():
        if not isinstance(run, dict):
            continue
        if cutoff is not None:
            ref = run_reference_time(run)
            if ref is None or ref < cutoff:
                continue
        filtered.append(run)
    by_verdict = dict.fromkeys(VERDICT_VALUES, 0)
    for run in filtered:
        verdict = str(run.get("verdict", "") or "").strip().lower()
        if verdict in by_verdict:
            by_verdict[verdict] += 1
    with_verdict = sum(by_verdict.values())
    rework_count = by_verdict.get("rework", 0)
    rework_rate: float | None = None
    if with_verdict:
        rework_rate = round(rework_count / with_verdict, 4)
    verify_pass = sum(1 for run in filtered if run.get("verify_status") == "passed")
    verify_fail = sum(1 for run in filtered if run.get("verify_status") == "failed")
    verify_skipped = sum(1 for run in filtered if run.get("verify_status") == "skipped")
    durations: list[float] = []
    for run in filtered:
        created = run.get("created_at")
        finished = run.get("finished_at") or run.get("completed_at")
        if not isinstance(created, str) or not isinstance(finished, str):
            continue
        try:
            start = parse_iso_timestamp(created)
            end = parse_iso_timestamp(finished)
        except (ValueError, TypeError):
            continue
        if end >= start:
            durations.append((end - start).total_seconds())
    median_seconds: float | None = None
    if durations:
        ordered = sorted(durations)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            median_seconds = round(ordered[mid], 2)
        else:
            median_seconds = round((ordered[mid - 1] + ordered[mid]) / 2, 2)
    runs_without_verdict = 0
    failed_runs = 0
    for run in filtered:
        verdict = str(run.get("verdict", "") or "").strip().lower()
        if verdict not in by_verdict:
            runs_without_verdict += 1
        if run.get("status") == "failed":
            failed_runs += 1
    # per-backend / per-verify-profile outcome breakdown so the
    # teamlead can learn which backends or task shapes fail verify per stack.
    # Legacy runs missing the fields aggregate under "unknown".
    by_backend: dict[str, dict[str, int]] = {}
    by_verify_profile: dict[str, dict[str, int]] = {}
    for run in filtered:
        backend = str(run.get("backend", "") or "").strip() or "unknown"
        profile = str(run.get("verify_profile", "") or "").strip() or "unknown"
        for bucket, key in ((by_backend, backend), (by_verify_profile, profile)):
            counts = bucket.setdefault(
                key, {"runs": 0, "failed_runs": 0, "verify_failed": 0, "rework": 0}
            )
            counts["runs"] += 1
            if run.get("status") == "failed":
                counts["failed_runs"] += 1
            if run.get("verify_status") == "failed":
                counts["verify_failed"] += 1
            if str(run.get("verdict", "") or "").strip().lower() == "rework":
                counts["rework"] += 1
    by_task: dict[str, list[dict[str, Any]]] = {}
    for run in filtered:
        task_id = str(run.get("task_id", "") or "").strip()
        if not task_id:
            continue
        by_task.setdefault(task_id, []).append(run)
    implicit_retry_count = 0
    for task_runs in by_task.values():
        if len(task_runs) <= 1:
            continue
        ordered_runs = sorted(task_runs, key=run_sort_key)
        if any(
            run.get("status") in IMPLICIT_RETRY_STATUSES for run in ordered_runs[:-1]
        ):
            implicit_retry_count += 1
    return {
        "runs_in_window": len(filtered),
        "by_verdict": by_verdict,
        "by_backend": by_backend,
        "by_verify_profile": by_verify_profile,
        "rework_rate": rework_rate,
        "implicit_retry_count": implicit_retry_count,
        "runs_without_verdict": runs_without_verdict,
        "failed_runs": failed_runs,
        "verify": {
            "passed": verify_pass,
            "failed": verify_fail,
            "skipped": verify_skipped,
        },
        "median_run_duration_seconds": median_seconds,
    }


def authoritative_quota_samples_by_run(
    samples: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """De-duplicate telemetry samples by ``run_id``, preferring the completion sample.
    """
    chosen: dict[str, dict[str, Any]] = {}
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        run_id = str(sample.get("run_id") or "").strip()
        key = run_id or f"#{id(sample)}"
        current = chosen.get(key)
        if current is None:
            chosen[key] = sample
            continue
        # Prefer the more authoritative line: non-partial over partial, then the
        # later recorded_at.
        cur_partial = bool(current.get("partial"))
        new_partial = bool(sample.get("partial"))
        if (cur_partial and not new_partial) or (cur_partial == new_partial and str(sample.get("recorded_at") or "") >= str(
            current.get("recorded_at") or ""
        )):
            chosen[key] = sample
    return chosen


def engagement_quota_cost(
    root: Path,
    policy: dict[str, Any] | None,
    *,
    run_ids: set[str],
) -> dict[str, Any]:
    """Sum high-confidence per-run quota deltas for the runs in an engagement.

    Consumes the SAME authoritative-per-run_id telemetry samples calibration
    trusts. For each run in ``run_ids`` with a
    sample: a high-confidence, non-partial sample with a usable observed delta
    contributes its delta; any other matched sample (partial / low-confidence /
    no delta) marks the cost ``partial`` because that run's spend is not fully
    measured. Returns ``{"unmeasured": reason}`` when telemetry is off/absent or
    no run in the window has a sample at all.
    """
    if not isinstance(policy, dict):
        return {"unmeasured": "quota telemetry unavailable (no policy)"}
    samples = read_quota_telemetry_samples(root, policy)
    if not samples:
        return {"unmeasured": "no quota telemetry samples"}
    by_run = authoritative_quota_samples_by_run(samples)
    total = 0.0
    high_runs = 0
    partial = False
    matched = 0
    for run_id in run_ids:
        sample = by_run.get(run_id)
        if sample is None:
            continue
        matched += 1
        if is_high_confidence_sample(sample):
            delta = sample_observed_delta(sample)
            if delta is not None:
                total += delta
                high_runs += 1
                continue
        # Matched but not a usable high-confidence delta: cost is incomplete.
        partial = True
    if matched == 0:
        return {"unmeasured": "no quota telemetry for runs in this engagement"}
    return {
        "delta_percentage": round(total, 3),
        "high_confidence_runs": high_runs,
        "runs_with_sample": matched,
        "partial": partial,
    }


def value_scorecard(
    root: Path,
    *,
    since_days: int | None = None,
    delivery: dict[str, Any] | None = None,
    entries: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Per-engagement value scorecard: cost next to benefit.

    An *engagement* is the analyzed window (the ``--since`` window, or all-time
    when no window is given). Run records carry no clean wave/engagement
    boundary, so the window is the cheapest defensible unit and is named in the
    payload. Each cell is either a number or ``{"unmeasured": "<reason>"}`` —
    never a wrong number:

    - ``tasks_delivered`` — runs completed in the window.
    - ``gate_caught_reworks`` — verdicts == rework (the review/verdict gate's
      real catches, distinct from clean approves).
    - ``operator_interventions`` — judgment journal rows (machine auto-stubs
      excluded) with choice ``escalate`` / ``confirm_risk`` / ``override_*``.
    - ``overhead_ratio`` — (summed verify+review+verdict elapsed) / (summed
      implement elapsed) across the window's runs. The run's own
      wall-clock (created→finished) is the implement phase; verify/review/verdict
      are separate command invocations AFTER the run that stamp their elapsed
      onto ``run["phase_timing"]`` (accumulated across rework repeats). Degrades
      to ``unmeasured`` only for fully-legacy windows where no run carries phase
      timing, and marks a never-run phase as a partial component.
    - ``quota_cost`` — sum of high-confidence per-run quota deltas from the
      completion samples; ``partial`` when any matched run's cost is
      incomplete.
    """
    state = load_state(root)
    runs = state.get("runs", {})
    if not isinstance(runs, dict):
        runs = {}
    cutoff: dt.datetime | None = None
    if since_days is not None:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=since_days)
    window_runs: list[dict[str, Any]] = []
    for run in runs.values():
        if not isinstance(run, dict):
            continue
        if cutoff is not None:
            ref = run_reference_time(run)
            if ref is None or ref < cutoff:
                continue
        window_runs.append(run)

    if delivery is None:
        delivery = delivery_metrics(root, since_days=since_days)
    tasks_delivered = int(delivery.get("runs_in_window", len(window_runs)))
    by_verdict = delivery.get("by_verdict", {})
    gate_caught = (
        int(by_verdict.get("rework", 0)) if isinstance(by_verdict, dict) else 0
    )

    if entries is None:
        entries = read_decisions(root)
        if since_days is not None:
            kept: list[dict[str, Any]] = []
            for entry in entries:
                try:
                    stamp = parse_iso_timestamp(str(entry.get("at", "")))
                except (ValueError, TypeError):
                    continue
                if stamp >= cutoff:  # type: ignore[operator]
                    kept.append(entry)
            entries = kept
    interventions = 0
    for entry in entries:
        if not isinstance(entry, dict) or is_machine_decision(entry):
            continue
        choice = str(entry.get("choice", "") or "").strip().lower()
        signals = entry.get("signals")
        is_override = choice.startswith("override_") or (
            isinstance(signals, dict) and bool(signals.get("override"))
        )
        if choice in INTERVENTION_CHOICES or is_override:
            interventions += 1

    run_ids = {
        str(run.get("id") or "").strip()
        for run in window_runs
        if str(run.get("id") or "").strip()
    }
    if policy is None:
        try:
            policy = read_policy(root)
        except Exception:  # noqa: BLE001 - analytics must render without a policy
            policy = None
    quota_cost = engagement_quota_cost(root, policy, run_ids=run_ids)

    return {
        "engagement": (
            f"last {since_days} days"
            if since_days is not None
            else "all runs (all time)"
        ),
        "engagement_basis": "analyzed window (no wave boundary in run data)",
        "tasks_delivered": tasks_delivered,
        "gate_caught_reworks": gate_caught,
        "operator_interventions": interventions,
        "overhead_ratio": overhead_ratio_cell(window_runs),
        "quota_cost": quota_cost,
    }


def _trend_week_key(stamp: dt.datetime) -> str:
    """ISO-week bucket label (``YYYY-Www``) for a timestamp — the trend grain."""
    iso = stamp.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def _trend_direction(current: float | None, previous: float | None) -> str:
    """up / down / flat vs the previous sufficient bucket; ``n/a`` when either missing.

    Direction is reported on the raw metric value — interpretation (is "up" good?
    depends on the metric) is left to the reader and documented per metric.
    """
    if current is None or previous is None:
        return "n/a"
    if current > previous:
        return "up"
    if current < previous:
        return "down"
    return "flat"


def value_trend(
    root: Path,
    *,
    since_days: int | None = None,
    entries: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
    grain: str = "week",
) -> dict[str, Any]:
    """**Cross-repo vs per-repo (honest asymmetry).** Pooled telemetry carries a
    ``repo_id`` per sample, so the **cost** trend can be
    cross-repo today: cost-per-task buckets are attributed by ``repo_id``. The
    **benefit** signals — tasks delivered, gate-caught reworks, operator
    interventions — come from this repo's ``state.json`` and decision journal,
    which are per-repo unless the operator aggregates the journals (not done by
    default). So benefit buckets are attributed to this repo's ``repo_id`` only;
    other repos' costs appear cost-only until their journals are pooled too.

    **Insufficient-data guard.** A bucket with fewer than ``TREND_MIN_DELIVERED``
    delivered runs is labelled ``insufficient`` (carries its counts but no
    cost-per-task / gate-catch rate and is skipped for direction). A trend with
    fewer than 2 sufficient buckets is ``insufficient history`` — the direction
    indicators stay ``n/a``.

    ``overhead_ratio`` is measured per bucket from the phase stamps written by
    the verify/review/verdict commands: (summed verify+review+
    verdict elapsed) / (summed implement elapsed) over that bucket's runs.
    Buckets whose runs all predate phase timing still read ``unmeasured``.
    """
    if grain != "week":
        grain = "week"
    cutoff: dt.datetime | None = None
    if since_days is not None:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=since_days)
    this_repo = quota_telemetry_repo_id(root)

    # --- Benefit (per-repo): delivered + gate-caught + interventions, bucketed ---
    state = load_state(root)
    runs = state.get("runs", {})
    if not isinstance(runs, dict):
        runs = {}
    # bucket key -> {delivered, reworks, run_ids}
    benefit: dict[str, dict[str, Any]] = {}
    for run in runs.values():
        if not isinstance(run, dict):
            continue
        ref = run_reference_time(run)
        if ref is None or (cutoff is not None and ref < cutoff):
            continue
        key = _trend_week_key(ref)
        cell = benefit.setdefault(
            key, {"delivered": 0, "reworks": 0, "run_ids": set(), "runs": []}
        )
        cell["delivered"] += 1
        if str(run.get("verdict", "") or "").strip().lower() == "rework":
            cell["reworks"] += 1
        run_id = str(run.get("id") or "").strip()
        if run_id:
            cell["run_ids"].add(run_id)
        cell["runs"].append(run)

    if entries is None:
        entries = read_decisions(root)
        if cutoff is not None:
            kept: list[dict[str, Any]] = []
            for entry in entries:
                try:
                    stamp = parse_iso_timestamp(str(entry.get("at", "")))
                except (ValueError, TypeError):
                    continue
                if stamp >= cutoff:
                    kept.append(entry)
            entries = kept
    interventions_by_bucket: dict[str, int] = {}
    for entry in entries:
        if not isinstance(entry, dict) or is_machine_decision(entry):
            continue
        try:
            stamp = parse_iso_timestamp(str(entry.get("at", "")))
        except (ValueError, TypeError):
            continue
        if cutoff is not None and stamp < cutoff:
            continue
        choice = str(entry.get("choice", "") or "").strip().lower()
        signals = entry.get("signals")
        is_override = choice.startswith("override_") or (
            isinstance(signals, dict) and bool(signals.get("override"))
        )
        if choice in INTERVENTION_CHOICES or is_override:
            key = _trend_week_key(stamp)
            interventions_by_bucket[key] = interventions_by_bucket.get(key, 0) + 1

    # --- Cost (cross-repo via pooled telemetry): per (bucket, repo_id) delta ---
    if policy is None:
        try:
            policy = read_policy(root)
        except Exception:  # noqa: BLE001 - analytics must render without a policy
            policy = None
    samples = (
        read_quota_telemetry_samples(root, policy) if isinstance(policy, dict) else []
    )
    by_run = authoritative_quota_samples_by_run(samples)
    # (bucket, repo_id) -> {delta, high_runs, matched, partial}
    cost_cells: dict[tuple[str, str], dict[str, Any]] = {}
    repo_ids: set[str] = set()
    for sample in by_run.values():
        recorded = str(sample.get("recorded_at") or "").strip()
        try:
            stamp = parse_iso_timestamp(recorded)
        except (ValueError, TypeError):
            continue
        if cutoff is not None and stamp < cutoff:
            continue
        repo = str(sample.get("repo_id") or "").strip() or this_repo
        repo_ids.add(repo)
        cost_key = (_trend_week_key(stamp), repo)
        cell = cost_cells.setdefault(
            cost_key, {"delta": 0.0, "high_runs": 0, "matched": 0, "partial": False}
        )
        cell["matched"] += 1
        if is_high_confidence_sample(sample):
            delta = sample_observed_delta(sample)
            if delta is not None:
                cell["delta"] += delta
                cell["high_runs"] += 1
                continue
        cell["partial"] = True

    bucket_keys = sorted(
        set(benefit) | set(interventions_by_bucket) | {k[0] for k in cost_cells}
    )
    buckets: list[dict[str, Any]] = []
    for key in bucket_keys:
        b = benefit.get(
            key, {"delivered": 0, "reworks": 0, "run_ids": set(), "runs": []}
        )
        delivered = int(b["delivered"])
        reworks = int(b["reworks"])
        interventions = int(interventions_by_bucket.get(key, 0))
        # Cost per repo for this bucket (cross-repo). Sum only this-repo runs'
        # cost into the headline cost-per-task (benefit is this-repo only).
        per_repo: dict[str, dict[str, Any]] = {}
        for (bk, repo), cell in cost_cells.items():
            if bk != key:
                continue
            per_repo[repo] = {
                "delta_percentage": round(cell["delta"], 3),
                "high_confidence_runs": cell["high_runs"],
                "runs_with_sample": cell["matched"],
                "partial": bool(cell["partial"]),
            }
        sufficient = delivered >= TREND_MIN_DELIVERED
        bucket: dict[str, Any] = {
            "bucket": key,
            "grain": grain,
            "tasks_delivered": delivered,
            "gate_caught_reworks": reworks,
            "operator_interventions": interventions,
            "overhead_ratio": overhead_ratio_cell(b["runs"]),
            "cost_by_repo": per_repo,
            "sufficient": sufficient,
        }
        if not sufficient:
            bucket["insufficient"] = (
                f"{delivered} delivered < {TREND_MIN_DELIVERED} (too few to trend-line)"
            )
            buckets.append(bucket)
            continue
        bucket["gate_catch_rate"] = round(reworks / delivered * 100, 2)
        this_cost = per_repo.get(this_repo)
        if this_cost is not None:
            bucket["cost_per_delivered_task"] = {
                "value": round(this_cost["delta_percentage"] / delivered, 4),
                "partial": this_cost["partial"]
                or this_cost["high_confidence_runs"] < delivered,
                "repo_id": this_repo,
            }
        else:
            bucket["cost_per_delivered_task"] = {
                "unmeasured": "no quota telemetry for this repo in this bucket"
            }
        buckets.append(bucket)

    # Direction indicators across the sufficient buckets (chronological).
    sufficient_buckets = [b for b in buckets if b.get("sufficient")]
    enough_history = len(sufficient_buckets) >= 2
    if enough_history:
        prev: dict[str, Any] | None = None
        for b in sufficient_buckets:
            cost_now = b.get("cost_per_delivered_task", {})
            cost_val = cost_now.get("value") if isinstance(cost_now, dict) else None
            prev_cost = (
                prev.get("cost_per_delivered_task", {}) if prev is not None else {}
            )
            prev_cost_val = (
                prev_cost.get("value") if isinstance(prev_cost, dict) else None
            )
            b["direction"] = {
                "gate_catch_rate": _trend_direction(
                    b.get("gate_catch_rate"),
                    prev.get("gate_catch_rate") if prev is not None else None,
                ),
                "cost_per_delivered_task": _trend_direction(cost_val, prev_cost_val),
            }
            prev = b

    return {
        "grain": grain,
        "engagement_basis": "ISO-week bucket (no wave boundary in run data)",
        "this_repo_id": this_repo,
        "repo_ids_with_cost": sorted(repo_ids),
        "cross_repo": {
            "cost": "cross-repo via pooled telemetry repo_id",
            "benefit": (
                "per-repo (this repo's state.json + journal); other repos' "
                "verdicts/interventions appear only when journals are aggregated"
            ),
        },
        "min_delivered_per_bucket": TREND_MIN_DELIVERED,
        "sufficient_buckets": len(sufficient_buckets),
        "buckets": buckets,
        "history": "sufficient" if enough_history else "insufficient history",
    }


def analytics_policy_section(policy: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(policy, dict):
        section = policy.get("analytics")
        if isinstance(section, dict):
            return section
    return {}


def backlog_archive_paths(root: Path, glob_pattern: str) -> list[Path]:
    """Rotated backlog archives matching ``glob_pattern`` under ``root``.

    Sorted by name so a later rotation wins an (unexpected) id collision
    between archives before the active file takes final precedence. Returns
    ``[]`` when the archive directory is missing — a repo that never rotated
    is the normal case, not a failure.
    """
    try:
        return sorted(path for path in root.glob(glob_pattern) if path.is_file())
    except (OSError, ValueError):
        return []


def recurrence_metrics(
    root: Path, *, policy: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Sibling / regression recurrence over *delivered* backlog tasks.

    Counts delivered (``- [x]``) tasks whose block text matches a configured
    marker (default: "sibling of", "regression of", "root cause of",
    "re-drift"). ``rework_rate`` measures judgment and re-delivery; this
    measures whether fixes generalize or keep patching siblings of earlier
    bugs. Marker set and backlog path are configurable via policy
    ``[analytics]``. The backlog has no per-task timestamps, so the rate is
    computed over the whole backlog file and is independent of the analytics
    ``--since`` window.

    Audit reader: merges the active backlog with rotated
    archives (policy ``[analytics] archive_glob``, default
    ``backlog/archive/BACKLOG-*.md``), de-duplicating by task id with the
    active file taking precedence, so the delivered population survives
    sdlc-backlog-rotate instead of shrinking to the small active set. Unreadable
    archive files degrade gracefully to the readable subset (active-only in
    the worst case) and are listed in ``archive_warnings``. Delivery-path
    readers (``plan``, ``backlog-order``, ``dor``) stay active-only per the
    archive policy.
    """
    section = analytics_policy_section(policy)
    raw_markers = section.get("recurrence_markers")
    if isinstance(raw_markers, list) and any(str(m).strip() for m in raw_markers):
        markers = [str(m).strip().lower() for m in raw_markers if str(m).strip()]
    else:
        markers = [marker.lower() for marker in DEFAULT_SIBLING_MARKERS]
    try:
        threshold = float(
            section.get("recurrence_warn_rate", SIBLING_RATE_WARN_THRESHOLD)
        )
    except (TypeError, ValueError):
        threshold = SIBLING_RATE_WARN_THRESHOLD
    backlog_rel = str(section.get("recurrence_backlog", "BACKLOG.md") or "BACKLOG.md")
    archive_glob = str(
        section.get("archive_glob", DEFAULT_BACKLOG_ARCHIVE_GLOB)
        or DEFAULT_BACKLOG_ARCHIVE_GLOB
    )
    result: dict[str, Any] = {
        "available": False,
        "backlog": backlog_rel,
        "markers": markers,
        "threshold": round(threshold, 4),
        "delivered_count": 0,
        "recurrence_count": 0,
        "sibling_rate": None,
        "sibling_task_ids": [],
        "archive_glob": archive_glob,
        "archive_files": [],
        "archived_delivered_count": 0,
        "archive_warnings": [],
    }
    backlog_path = root / backlog_rel
    if not backlog_path.exists():
        return result
    try:
        lines = backlog_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    # the active store may be file-per-task; the root backlog
    # file is then a generated index with no parseable blocks.
    active_tasks = parse_task_files(root) or parse_backlog_blocks(lines)
    merged: dict[str, Task] = {}
    archive_files: list[str] = []
    archive_warnings: list[str] = []
    archive_sources = list(backlog_archive_paths(root, archive_glob))
    archive_sources.extend(archive_task_files(root))
    for archive_path in archive_sources:
        rel = archive_path.relative_to(root).as_posix()
        try:
            archive_lines = archive_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            archive_warnings.append(
                f"backlog archive unreadable, recurrence degraded to remaining "
                f"files: {rel} ({exc.__class__.__name__})"
            )
            continue
        for task in parse_backlog_blocks(archive_lines):
            merged[task.id] = task
        archive_files.append(rel)
    active_ids = {task.id for task in active_tasks}
    for task in active_tasks:
        merged[task.id] = task  # active file wins on id collision
    delivered = [task for task in merged.values() if task.status == "x"]
    matched = [
        task.id
        for task in delivered
        if any(marker in task.block.lower() for marker in markers)
    ]
    delivered_count = len(delivered)
    result.update(
        available=True,
        delivered_count=delivered_count,
        recurrence_count=len(matched),
        sibling_rate=round(len(matched) / delivered_count, 4)
        if delivered_count
        else None,
        sibling_task_ids=matched,
        archive_files=archive_files,
        archived_delivered_count=sum(
            1 for task in delivered if task.id not in active_ids
        ),
        archive_warnings=archive_warnings,
    )
    return result


def suggest_result_from_run_ids(state: dict[str, Any], run_ids: list[str]) -> str:
    outcome = "unknown"
    for run_id in run_ids:
        run = state.get("runs", {}).get(run_id, {})
        if run.get("verify_status") == "failed" or run.get("status") == "failed":
            outcome = "bad"
        elif (
            run.get("status") in {"done", "needs_review"}
            and run.get("verify_status") == "passed"
        ):
            outcome = "good"
    return outcome


def _normalize_decision_run_ids(raw: Any) -> list[str]:
    if not raw:
        return []
    if not isinstance(raw, list):
        return []
    return [str(r) for r in raw if r]


def _normalize_decision_task_ids(raw: Any) -> list[str]:
    if not raw:
        return []
    if not isinstance(raw, list):
        return []
    return [str(t) for t in raw if t]


def decision_coverage_keys(entries: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    for entry in entries:
        phase = str(entry.get("phase", "") or "")
        choice = str(entry.get("choice", "") or "")
        for run_id in _normalize_decision_run_ids(entry.get("run_ids")):
            keys.add((phase, choice, run_id))
    return keys


def runs_in_state_window(
    state: dict[str, Any], *, since_days: int | None
) -> list[tuple[str, dict[str, Any]]]:
    runs = state.get("runs", {})
    if not isinstance(runs, dict):
        return []
    cutoff: dt.datetime | None = None
    if since_days is not None:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=since_days)
    window: list[tuple[str, dict[str, Any]]] = []
    for run_id, run in runs.items():
        if not isinstance(run, dict):
            continue
        if cutoff is not None:
            ref = run_reference_time(run)
            if ref is None or ref < cutoff:
                continue
        window.append((str(run_id), run))
    return window


def ingest_stub_timestamp(run: dict[str, Any], *, prefer_keys: tuple[str, ...]) -> str:
    for key in prefer_keys:
        raw = run.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    ref = run_reference_time(run)
    if ref is not None:
        return ref.replace(microsecond=0).isoformat()
    return now()


def make_ingest_stub(
    *,
    phase: str,
    choice: str,
    task_ids: list[str],
    run_id: str,
    reason: str,
    signals: dict[str, Any],
    at: str,
) -> dict[str, Any]:
    payload = dict(signals)
    payload["ingest"] = True
    # Ingest stubs reconstruct telemetry without operator-authored text, so
    # they carry the machine marker like other auto rows.
    payload["auto"] = True
    payload["source"] = "state.json"
    payload["source_run_id"] = run_id
    return {
        "schema_version": 1,
        "id": "(proposed)",
        "at": at,
        "phase": phase,
        "choice": choice,
        "reason": reason.strip(),
        "signals": payload,
        "task_ids": task_ids,
        "run_ids": [run_id],
        "result": "pending",
        "reflection": "",
        "reflected_at": None,
    }


def propose_decision_ingest_stubs(
    root: Path,
    *,
    since_days: int | None = None,
) -> list[dict[str, Any]]:
    state = load_state(root)
    existing = decision_coverage_keys(read_decisions(root))
    all_by_task: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    runs = state.get("runs", {})
    if isinstance(runs, dict):
        for run_id, run in runs.items():
            if not isinstance(run, dict):
                continue
            task_id = str(run.get("task_id", "") or "").strip()
            if not task_id:
                continue
            all_by_task.setdefault(task_id, []).append((str(run_id), run))
    for task_runs in all_by_task.values():
        task_runs.sort(key=lambda item: run_sort_key(item[1]))
    proposals: list[dict[str, Any]] = []
    for run_id, run in runs_in_state_window(state, since_days=since_days):
        task_id = str(run.get("task_id", "") or "").strip()
        task_ids = [task_id] if task_id else []
        if run.get("verify_status") == "failed":
            key = ("verify", "verify_failed", run_id)
            if key not in existing:
                proposals.append(
                    make_ingest_stub(
                        phase="verify",
                        choice="verify_failed",
                        task_ids=task_ids,
                        run_id=run_id,
                        reason="verify failed (reconstructed from state.json)",
                        signals={"verify_status": "failed"},
                        at=ingest_stub_timestamp(
                            run,
                            prefer_keys=("finished_at", "completed_at", "created_at"),
                        ),
                    )
                )
        verdict = str(run.get("verdict", "") or "").strip().lower()
        if verdict in INGEST_VERDICT_CHOICES:
            key = ("verdict", verdict, run_id)
            if key not in existing:
                reflection = str(run.get("verdict_reflection", "") or "").strip()
                stub = make_ingest_stub(
                    phase="verdict",
                    choice=verdict,
                    task_ids=task_ids,
                    run_id=run_id,
                    reason=f"verdict {verdict}",
                    signals={
                        "verdict": verdict,
                        "run_status": run.get("status"),
                    },
                    at=ingest_stub_timestamp(
                        run, prefer_keys=("verdict_at", "created_at")
                    ),
                )
                if reflection:
                    stub["reflection"] = reflection
                proposals.append(stub)
        if task_id in all_by_task:
            prior = 0
            for prior_id, _prior_run in all_by_task[task_id]:
                if prior_id == run_id:
                    break
                prior += 1
            if prior >= 1:
                key = ("delivery", "retry_run", run_id)
                if key not in existing:
                    proposals.append(
                        make_ingest_stub(
                            phase="delivery",
                            choice="retry_run",
                            task_ids=task_ids,
                            run_id=run_id,
                            reason=f"retry run for {task_id} (prior runs: {prior})",
                            signals={"prior_run_count": prior, "task_id": task_id},
                            at=ingest_stub_timestamp(run, prefer_keys=("created_at",)),
                        )
                    )
    proposals.sort(key=lambda item: str(item.get("at", "")))
    return proposals


def normalize_parallel_logged_choice(choice: str) -> str | None:
    key = choice.strip().lower()
    if key in {"parallel_waves", "parallel"}:
        return "parallel_waves"
    if key in {"sequential", "sequential_waves"}:
        return "sequential"
    return None


def analyze_parallel_batch(
    root: Path,
    tasks: list[Task],
    policy: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    config = read_config(root)
    par = parallel_policy(policy)
    signals = {task.id: task_scope_signals(task) for task in tasks}
    enrich_signals_with_predictions(root, tasks, signals)
    for task in tasks:
        signals[task.id]["risk_gates"] = risk_gates(task, policy)
    worktrees = worktrees_enabled(config)
    reasoning: list[str] = []
    ask_user = False
    ask_reason = ""

    if not par.get("enabled", True):
        return {
            "strategy": "sequential",
            "waves": [[task.id] for task in tasks],
            "reasoning": ["parallel.disabled in policy"],
            "signals": signals,
            "collision_edges": [],
            "ask_user": False,
        }
    if par.get("require_worktrees", True) and not worktrees:
        reasoning.append("worktrees_enabled is false")
    if any(sig["scope_broad"] for sig in signals.values()) and par.get(
        "sequential_on_broad_scope", True
    ):
        reasoning.append("at least one task has broad scope")
    if any(sig["risk_gates"] for sig in signals.values()):
        reasoning.append("review gates present on one or more tasks")
    if any(sig["priority"] == "P0" for sig in signals.values()) and par.get(
        "sequential_on_any_p0_risk", True
    ):
        reasoning.append("P0 in batch")

    for task in tasks:
        for dep in task.depends_on:
            if any(other.id == dep for other in tasks):
                reasoning.append(f"in-batch dependency: {task.id} depends on {dep}")

    waves, wave_reasoning, collision_edges = build_parallel_waves(
        tasks, signals, policy
    )
    reasoning.extend(wave_reasoning)
    if collision_edges:
        reasoning.append(
            f"{len(collision_edges)} collision edge(s) separate tasks "
            "(see collision_edges for per-pair reasons)"
        )

    multi_wave_parallel = len(waves) > 1 or any(len(wave) > 1 for wave in waves)
    auto_ok = (
        par.get("auto_dispatch", True)
        and worktrees
        and multi_wave_parallel
        and not any("dependency" in item for item in reasoning)
        and not any("broad scope" in item for item in reasoning)
        and not any("P0 in batch" in item for item in reasoning)
    )

    if not worktrees and multi_wave_parallel:
        ask_user = True
        ask_reason = "parallel plan needs worktrees but worktrees_enabled is false"

    strategy = "parallel_waves" if auto_ok else "sequential"
    if not multi_wave_parallel:
        strategy = "sequential"
        waves = [[task.id] for task in tasks]

    return {
        "strategy": strategy,
        "waves": waves,
        "reasoning": reasoning,
        "signals": signals,
        "collision_edges": collision_edges,
        "policy": {
            "max_concurrent": int(par.get("max_concurrent", 3)),
            "worktrees_enabled": worktrees,
            "auto_dispatch": bool(par.get("auto_dispatch", True)),
        },
        "ask_user": ask_user,
        "ask_reason": ask_reason,
    }


def parallel_plan_for_task_ids(
    root: Path,
    task_ids: list[str],
    policy: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any] | None:
    tasks = parse_backlog(root)
    by_id = {task.id: task for task in tasks}
    selected = [by_id[task_id] for task_id in task_ids if task_id in by_id]
    if not selected:
        return None
    return analyze_parallel_batch(root, selected, policy, state)


def merge_parallel_override_signals(
    entry: dict[str, Any], info: dict[str, Any]
) -> None:
    signals = entry.get("signals")
    payload = dict(signals) if isinstance(signals, dict) else {}
    payload["override"] = True
    payload["plan_strategy"] = info["plan_strategy"]
    payload["logged_choice"] = info["logged_choice"]
    if info.get("logged_strategy"):
        payload["logged_strategy"] = info["logged_strategy"]
    entry["signals"] = payload


def parallel_override_from_signals(entry: dict[str, Any]) -> dict[str, Any] | None:
    signals = entry.get("signals")
    if not isinstance(signals, dict) or not signals.get("override"):
        return None
    plan_strategy = signals.get("plan_strategy")
    if not plan_strategy:
        return None
    return {
        "override": True,
        "plan_strategy": str(plan_strategy),
        "logged_choice": str(signals.get("logged_choice") or entry.get("choice") or ""),
        "suggest_choice": "override_parallel_plan",
    }


def detect_parallel_plan_override(
    root: Path,
    entry: dict[str, Any],
    policy: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any] | None:
    if str(entry.get("phase", "")).lower() != "parallel":
        return None
    choice = str(entry.get("choice", "") or "").strip()
    if choice.lower().startswith("override_"):
        return None
    logged_strategy = normalize_parallel_logged_choice(choice)
    if logged_strategy is None:
        return None
    task_ids = _normalize_decision_task_ids(entry.get("task_ids"))
    if not task_ids:
        return None
    analysis = parallel_plan_for_task_ids(root, task_ids, policy, state)
    if not analysis:
        return None
    plan_strategy = str(analysis.get("strategy", "sequential"))
    if logged_strategy == plan_strategy:
        return None
    return {
        "override": True,
        "plan_strategy": plan_strategy,
        "logged_choice": choice,
        "logged_strategy": logged_strategy,
        "suggest_choice": "override_parallel_plan",
        "task_ids": task_ids,
    }


def parallel_override_hint(
    root: Path,
    policy: dict[str, Any],
    state: dict[str, Any],
    entry: dict[str, Any],
) -> dict[str, Any] | None:
    stored = parallel_override_from_signals(entry)
    if stored:
        return stored
    return detect_parallel_plan_override(root, entry, policy, state)


def check_parallel_overrides(
    root: Path,
    policy: dict[str, Any],
    *,
    since_days: int | None = None,
    apply: bool = True,
) -> dict[str, Any]:
    entries = read_decisions(root)
    state = load_state(root)
    cutoff: dt.datetime | None = None
    if since_days is not None:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=since_days)
    findings: list[dict[str, Any]] = []
    updated = 0
    checked_parallel = 0
    for entry in entries:
        if str(entry.get("phase", "")).lower() != "parallel":
            continue
        if cutoff is not None:
            try:
                stamp = parse_iso_timestamp(str(entry.get("at", "")))
            except (ValueError, TypeError):
                continue
            if stamp < cutoff:
                continue
        checked_parallel += 1
        info = detect_parallel_plan_override(root, entry, policy, state)
        if not info:
            continue
        findings.append(
            {
                "decision_id": entry.get("id"),
                "choice": entry.get("choice"),
                "plan_strategy": info["plan_strategy"],
                "logged_choice": info["logged_choice"],
                "suggest_choice": info["suggest_choice"],
                "task_ids": info.get("task_ids", []),
            }
        )
        if apply:
            before = json.dumps(entry.get("signals"), sort_keys=True)
            merge_parallel_override_signals(entry, info)
            after = json.dumps(entry.get("signals"), sort_keys=True)
            if before != after:
                updated += 1
    if apply and updated:
        write_decisions(root, entries)
    return {
        "checked_parallel": checked_parallel,
        "override_count": len(findings),
        "updated": updated,
        "overrides": findings,
    }


def build_reflect_suggestions(
    state: dict[str, Any],
    entries: list[dict[str, Any]],
    *,
    root: Path | None = None,
    policy: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], bool, bool]:
    """Suggest results for pending entries.

    Returns (suggestions, strict_violation, any_empty_run_ids).
    Empty journal run_ids always suggest unknown; strict_violation is True when
    resolved runs from task_ids would suggest good but run_ids were not stored.
    """
    suggestions: list[dict[str, Any]] = []
    strict_violation = False
    any_empty_run_ids = False
    for entry in entries:
        if entry.get("result") != "pending":
            continue
        run_ids = _normalize_decision_run_ids(entry.get("run_ids"))
        task_ids = _normalize_decision_task_ids(entry.get("task_ids"))
        if not run_ids:
            any_empty_run_ids = True
            resolved = resolve_decision_run_ids(state, task_ids)
            if suggest_result_from_run_ids(state, resolved) == "good":
                strict_violation = True
            outcome = "unknown"
            empty_run_ids = True
        else:
            outcome = suggest_result_from_run_ids(state, run_ids)
            empty_run_ids = False
        item: dict[str, Any] = {
            "decision_id": str(entry.get("id")),
            "phase": str(entry.get("phase")),
            "choice": str(entry.get("choice")),
            "suggested_result": outcome,
            "empty_run_ids": empty_run_ids,
            "reason": str(entry.get("reason", ""))[:200],
        }
        if root is not None and policy is not None:
            override_info = parallel_override_hint(root, policy, state, entry)
            if override_info:
                item["parallel_plan_override"] = True
                item["suggest_choice"] = override_info.get(
                    "suggest_choice", "override_parallel_plan"
                )
                item["override_reason"] = (
                    f"logged {override_info.get('logged_choice')} but parallel-plan "
                    f"said {override_info.get('plan_strategy')}"
                )
        suggestions.append(item)
    return suggestions, strict_violation, any_empty_run_ids


def _analytics_bad_total(analytics: dict[str, Any]) -> int:
    bad_total = 0
    for counts in analytics.get("by_phase", {}).values():
        if isinstance(counts, dict):
            bad_total += int(counts.get("bad", 0))
    return bad_total


def _analytics_judgment_total(analytics: dict[str, Any]) -> int:
    """Judgment-row count; falls back to total for pre-split payloads."""
    return int(analytics.get("judgment_total", analytics.get("total", 0)))


def _analytics_all_good(analytics: dict[str, Any]) -> bool:
    if int(analytics.get("pending", 0)) != 0:
        return False
    if _analytics_bad_total(analytics) != 0:
        return False
    return _analytics_judgment_total(analytics) > 0


def _reflected_at_minute_key(raw: Any) -> str | None:
    if not raw:
        return None
    try:
        stamp = parse_iso_timestamp(str(raw))
    except (ValueError, TypeError):
        return None
    return stamp.strftime("%Y-%m-%dT%H:%M")


def journal_credibility_flags(analytics: dict[str, Any]) -> list[dict[str, str]]:
    """Flags when aggregate good counts may not match delivery telemetry.

    Credibility heuristics run over operator judgment rows; machine telemetry
    rows do not count toward journal coverage.
    """
    flags: list[dict[str, str]] = []
    total = _analytics_judgment_total(analytics)
    delivery = analytics.get("delivery")
    runs = 0
    if isinstance(delivery, dict):
        runs = int(delivery.get("runs_in_window", 0) or 0)

    if _analytics_all_good(analytics) and runs > 0 and total < runs / 10:
        flags.append(
            {
                "code": "sparse_journal",
                "message": (
                    f"all {total} decision(s) are good with zero bad, but only "
                    f"{total} decisions vs {runs} runs in window (below runs/10). "
                    "Aggregate good counts under-cover delivery volume."
                ),
            }
        )

    report = analytics.get("report")
    if isinstance(report, dict):
        warnings = report.get("warnings", [])
        if isinstance(warnings, list) and any(
            isinstance(item, dict) and item.get("code") == "implicit_rework_detected"
            for item in warnings
        ):
            flags.append(
                {
                    "code": "implicit_rework",
                    "message": (
                        "delivery analytics report implicit rework while formal "
                        "rework rate may be zero. Do not treat the "
                        "journal as proof of smooth delivery."
                    ),
                }
            )

    entries = analytics.get("entries", [])
    if isinstance(entries, list) and total > 0:
        minute_counts: dict[str, int] = {}
        for entry in entries:
            if not isinstance(entry, dict) or is_machine_decision(entry):
                continue
            minute = _reflected_at_minute_key(entry.get("reflected_at"))
            if minute:
                minute_counts[minute] = minute_counts.get(minute, 0) + 1
        if minute_counts:
            peak = max(minute_counts.values())
            if peak / total > 0.8:
                dominant = max(minute_counts, key=lambda m: minute_counts[m])
                pct = round(100 * peak / total)
                flags.append(
                    {
                        "code": "bulk_reflected_at",
                        "message": (
                            f"{peak} of {total} decisions ({pct}%) share reflected_at "
                            f"minute {dominant}. Bulk reflection may not capture "
                            "per-decision judgment."
                        ),
                    }
                )

    return flags


def retro_journal_credibility_note(analytics: dict[str, Any]) -> str | None:
    """Credibility note when factual report would include journal credibility flags."""
    flags = journal_credibility_flags(analytics)
    if not flags:
        return None
    codes = ", ".join(item["code"] for item in flags)
    return (
        f"Journal credibility: {codes}. See factual report «Journal credibility» "
        "section. Do not treat aggregate good counts as proof of smooth delivery; "
        "review runs in state.json before trusting the decision journal."
    )


def _scorecard_cell_text(value: Any) -> str:
    """Render one scorecard cell: a number, or ``unmeasured (reason)``."""
    if isinstance(value, dict):
        reason = value.get("unmeasured")
        if reason is not None:
            return f"unmeasured ({reason})"
        return str(value)
    return str(value)


def _scorecard_overhead_text(cell: Any) -> str:
    """Render the overhead-ratio cell: ``N.NNN× (orchestration/implement)`` or unmeasured.

    The ratio is (verify+review+verdict elapsed) / (implement elapsed). When a
    phase never ran in the window the ratio is marked partial; a fully-legacy
    window with no phase stamps reads ``unmeasured (reason)``.
    """
    if not isinstance(cell, dict):
        return str(cell)
    if "unmeasured" in cell and cell.get("ratio") is None:
        return f"unmeasured ({cell['unmeasured']})"
    ratio = cell.get("ratio")
    orch = cell.get("orchestration_seconds")
    impl = cell.get("implement_seconds")
    text = f"{ratio}× ({orch}s orchestration / {impl}s implement)"
    missing = [
        phase
        for phase, comp in (cell.get("components") or {}).items()
        if isinstance(comp, dict) and "unmeasured" in comp
    ]
    if cell.get("partial") and missing:
        return f"{text} — partial (unmeasured: {', '.join(sorted(missing))})"
    return text


def _scorecard_quota_text(cost: Any) -> str:
    """Render the quota-cost cell: a percentage delta (marked partial) or unmeasured."""
    if not isinstance(cost, dict):
        return str(cost)
    if "unmeasured" in cost:
        return f"unmeasured ({cost['unmeasured']})"
    delta = cost.get("delta_percentage")
    text = f"{delta}% of quota"
    detail = (
        f" (high-confidence runs: {cost.get('high_confidence_runs', 0)}"
        f"/{cost.get('runs_with_sample', 0)} with samples)"
    )
    if cost.get("partial"):
        return f"{text} — partial{detail}"
    return f"{text}{detail}"


def format_value_scorecard_markdown(scorecard: dict[str, Any]) -> list[str]:
    """Markdown lines for the per-engagement value scorecard."""
    engagement = scorecard.get("engagement", "analyzed window")
    basis = scorecard.get("engagement_basis", "")
    lines = [
        "",
        "## Value scorecard",
        "",
        ("Cost next to benefit for one engagement (a delivery wave / window). "
        "Engagement = the analyzed window — run records carry no clean wave "
        "boundary, so the window is the unit. Each cell is a number or "
        "`unmeasured (reason)`, never a wrong number."),
        "",
        f"- Engagement: {engagement} ({basis})"
        if basis
        else f"- Engagement: {engagement}",
        "",
        "| Cell | Value |",
        "|------|-------|",
        f"| Tasks delivered | {_scorecard_cell_text(scorecard.get('tasks_delivered'))} |",
        ("| Reworks the gate caught | "
        f"{_scorecard_cell_text(scorecard.get('gate_caught_reworks'))} |"),
        ("| Operator interventions | "
        f"{_scorecard_cell_text(scorecard.get('operator_interventions'))} |"),
        f"| Orchestration overhead ratio | {_scorecard_overhead_text(scorecard.get('overhead_ratio'))} |",
        f"| Quota cost | {_scorecard_quota_text(scorecard.get('quota_cost'))} |",
    ]
    return lines


def _trend_cost_per_task_text(cell: Any) -> str:
    """Render a bucket's cost-per-delivered-task cell."""
    if not isinstance(cell, dict):
        return str(cell)
    if "unmeasured" in cell:
        return f"unmeasured ({cell['unmeasured']})"
    value = cell.get("value")
    suffix = " (partial)" if cell.get("partial") else ""
    return f"{value} pp/task{suffix}"


def _trend_overhead_text(cell: Any) -> str:
    """Compact overhead-ratio cell for the trend table: ``N.NNN×`` or unmeasured."""
    if not isinstance(cell, dict):
        return str(cell)
    if "unmeasured" in cell and cell.get("ratio") is None:
        return "unmeasured"
    ratio = cell.get("ratio")
    suffix = " (partial)" if cell.get("partial") else ""
    return f"{ratio}×{suffix}"


def _trend_arrow(direction: Any, metric: str) -> str:
    """Render a per-metric direction indicator from a bucket's ``direction`` map."""
    if not isinstance(direction, dict):
        return "—"
    return {"up": "▲", "down": "▼", "flat": "▬"}.get(
        str(direction.get(metric, "")), "—"
    )


def format_value_trend_markdown(trend: dict[str, Any]) -> list[str]:
    """Markdown lines for the value trend across engagements + repos."""
    cross = trend.get("cross_repo", {})
    lines = [
        "",
        "## Value trend (across engagements)",
        "",
        ("Rolls the per-engagement Value scorecard across time "
        f"(grain: {trend.get('grain', 'week')}) so the direction shows, not just one "
        "snapshot."),
        "",
        f"- Cost: {cross.get('cost', 'n/a')}",
        f"- Benefit: {cross.get('benefit', 'n/a')}",
        (f"- This repo id: {trend.get('this_repo_id', 'unknown')}; "
        f"repos with cost data: {', '.join(trend.get('repo_ids_with_cost', [])) or 'none'}"),
        (f"- History: {trend.get('history', 'insufficient history')} "
        f"({trend.get('sufficient_buckets', 0)} sufficient bucket(s); "
        f"a bucket needs ≥{trend.get('min_delivered_per_bucket', TREND_MIN_DELIVERED)} "
        "delivered or it is labelled insufficient)"),
        "",
        "| Bucket | Delivered | Gate-catch /100 | Cost/task | Overhead | Trend |",
        "|--------|-----------|-----------------|-----------|----------|-------|",
    ]
    for bucket in trend.get("buckets", []):
        if not isinstance(bucket, dict):
            continue
        name = bucket.get("bucket", "?")
        delivered = bucket.get("tasks_delivered", 0)
        if not bucket.get("sufficient"):
            lines.append(
                f"| {name} | {delivered} | insufficient | insufficient | "
                "unmeasured | — |"
            )
            continue
        rate = bucket.get("gate_catch_rate", "n/a")
        cost = _trend_cost_per_task_text(bucket.get("cost_per_delivered_task"))
        overhead = _trend_overhead_text(bucket.get("overhead_ratio"))
        direction = bucket.get("direction")
        arrows = (
            f"catch {_trend_arrow(direction, 'gate_catch_rate')} "
            f"cost {_trend_arrow(direction, 'cost_per_delivered_task')}"
            if direction
            else "—"
        )
        lines.append(
            f"| {name} | {delivered} | {rate} | {cost} | {overhead} | {arrows} |"
        )
    return lines


def format_decision_analytics_markdown(
    analytics: dict[str, Any], *, since_days: int | None
) -> str:
    window = f"last {since_days} days" if since_days is not None else "all time"
    machine = analytics.get("machine")
    if not isinstance(machine, dict):
        machine = None
    lines = [
        "# ai-task decision analytics",
        "",
        f"Generated: {now()}",
        f"Window: {window}",
        "",
        f"- Total decisions: {analytics['total']}",
    ]
    if machine is not None:
        lines.extend(
            [
                ("- Operator judgment rows: "
                f"{analytics.get('judgment_total', analytics['total'])}"),
                f"- Machine-logged rows (telemetry): {machine.get('total', 0)}",
                f"- Pending (judgment rows): {analytics['pending']}",
            ]
        )
    else:
        lines.append(f"- Pending: {analytics['pending']}")
    by_operator = analytics.get("by_operator")
    if isinstance(by_operator, dict) and by_operator:
        lines.append(
            "- Operators: "
            + ", ".join(
                f"{name} ({count})" for name, count in sorted(by_operator.items())
            )
        )
    lines.extend(
        [
            "",
            "## By phase",
            "",
            "| Phase | good | bad | unknown | pending |",
            "|-------|------|-----|---------|---------|",
        ]
    )
    for phase, counts in sorted(analytics["by_phase"].items()):
        lines.append(
            f"| {phase} | {counts.get('good', 0)} | {counts.get('bad', 0)} | "
            f"{counts.get('unknown', 0)} | {counts.get('pending', 0)} |"
        )
    lines.extend(
        [
            "",
            "## By choice",
            "",
            "| Choice | good | bad | unknown | pending |",
            "|--------|------|-----|---------|---------|",
        ]
    )
    for choice, counts in sorted(analytics["by_choice"].items()):
        lines.append(
            f"| {choice} | {counts.get('good', 0)} | {counts.get('bad', 0)} | "
            f"{counts.get('unknown', 0)} | {counts.get('pending', 0)} |"
        )
    if machine is not None and machine.get("total"):
        lines.extend(
            [
                "",
                "## Machine-logged rows (telemetry)",
                "",
                ("Auto-emitted rows (`signals.auto = true`) are run telemetry, not "
                "operator judgment. Pending, stale-pending, and duplicate-reflection "
                "metrics in this report exclude them."),
                "",
                f"- Rows: {machine.get('total', 0)}",
                ("- Events (incl. collapsed repeats): "
                f"{machine.get('events', machine.get('total', 0))}"),
                f"- Pending rows: {machine.get('pending', 0)}",
                "",
                "| Choice | rows |",
                "|--------|------|",
            ]
        )
        machine_by_choice = machine.get("by_choice")
        if isinstance(machine_by_choice, dict):
            for choice, count in sorted(machine_by_choice.items()):
                lines.append(f"| {choice} | {count} |")
    delivery = analytics.get("delivery")
    if isinstance(delivery, dict):
        lines.extend(
            [
                "",
                "## Delivery (runs)",
                "",
                f"- Runs in window: {delivery.get('runs_in_window', 0)}",
                f"- Rework rate: {delivery.get('rework_rate', 'n/a')}",
                f"- Implicit retries (tasks): {delivery.get('implicit_retry_count', 0)}",
                f"- Runs without verdict: {delivery.get('runs_without_verdict', 0)}",
                f"- Failed runs: {delivery.get('failed_runs', 0)}",
            ]
        )
        verify = delivery.get("verify", {})
        if isinstance(verify, dict):
            lines.append(
                f"- Verify: passed={verify.get('passed', 0)} failed={verify.get('failed', 0)} "
                f"skipped={verify.get('skipped', 0)}"
            )
        median = delivery.get("median_run_duration_seconds")
        if median is not None:
            lines.append(f"- Median run duration (s): {median}")
        by_verdict = delivery.get("by_verdict", {})
        if isinstance(by_verdict, dict) and by_verdict:
            lines.append("")
            lines.append("| Verdict | count |")
            lines.append("|---------|-------|")
            for verdict, count in sorted(by_verdict.items()):
                if count:
                    lines.append(f"| {verdict} | {count} |")
        for title, label, key in (
            ("By backend", "Backend", "by_backend"),
            ("By verify profile", "Profile", "by_verify_profile"),
        ):
            breakdown = delivery.get(key)
            if not isinstance(breakdown, dict) or not breakdown:
                continue
            lines.extend(
                [
                    "",
                    f"### {title}",
                    "",
                    f"| {label} | runs | failed | verify failed | rework |",
                    "|---------|------|--------|---------------|--------|",
                ]
            )
            for name, counts in sorted(breakdown.items()):
                if not isinstance(counts, dict):
                    continue
                lines.append(
                    f"| {name} | {counts.get('runs', 0)} | "
                    f"{counts.get('failed_runs', 0)} | "
                    f"{counts.get('verify_failed', 0)} | {counts.get('rework', 0)} |"
                )
    scorecard = analytics.get("scorecard")
    if isinstance(scorecard, dict):
        lines.extend(format_value_scorecard_markdown(scorecard))
    trend = analytics.get("value_trend")
    if isinstance(trend, dict) and trend.get("buckets"):
        lines.extend(format_value_trend_markdown(trend))
    recurrence = analytics.get("recurrence")
    if isinstance(recurrence, dict) and recurrence.get("available"):
        rate = recurrence.get("sibling_rate")
        rate_text = f"{rate:.0%}" if isinstance(rate, (int, float)) else "n/a"
        threshold = recurrence.get("threshold")
        thr_text = f"{threshold:.0%}" if isinstance(threshold, (int, float)) else "n/a"
        lines.extend(
            [
                "",
                "## Recurrence (siblings)",
                "",
                ("Share of delivered backlog tasks that fix a sibling/regression of "
                "earlier work rather than generalize. High rates mean the dashboard's "
                "rework_rate can look healthy while the batch keeps re-patching."),
                "",
                f"- Delivered tasks scanned: {recurrence.get('delivered_count', 0)}",
                f"- Sibling/regression tasks: {recurrence.get('recurrence_count', 0)}",
                f"- Sibling rate: {rate_text} (warn >= {thr_text})",
                f"- Markers: {', '.join(recurrence.get('markers', [])) or 'none'}",
            ]
        )
        archive_files = recurrence.get("archive_files") or []
        if archive_files:
            lines.append(
                f"- Rotated archives merged: {len(archive_files)} file(s), "
                f"{recurrence.get('archived_delivered_count', 0)} delivered tasks "
                "from archive (active file wins on id collision): "
                f"{', '.join(archive_files)}"
            )
        for archive_warning in recurrence.get("archive_warnings") or []:
            lines.append(f"- **WARNING**: {archive_warning}")
        sibling_ids = recurrence.get("sibling_task_ids", [])
        if sibling_ids:
            lines.append(f"- Sibling task ids: {', '.join(sibling_ids)}")
    cred_flags = journal_credibility_flags(analytics)
    if cred_flags:
        lines.extend(
            [
                "",
                "## Journal credibility",
                "",
                ("These flags mean the judgment log may look healthier than run "
                "telemetry. They are not delivery failure signals."),
                "",
            ]
        )
        for item in cred_flags:
            lines.append(f"- **{item['code']}**: {item['message']}")
    report = analytics.get("report")
    if isinstance(report, dict):
        judgment_quality = report.get("judgment_quality")
        if isinstance(judgment_quality, dict):
            total = analytics.get("total", 0)
            empty = judgment_quality.get("empty_reason_count", 0)
            empty_pct = f"{empty / total:.0%}" if total else "n/a"
            reflection_count = judgment_quality.get("reflection_count", 0)
            dup = judgment_quality.get("duplicate_reflection_count", 0)
            dup_pct = f"{dup / reflection_count:.0%}" if reflection_count else "n/a"
            phases_present = judgment_quality.get("phases_present", [])
            phases_missing = judgment_quality.get("phases_missing", [])
            auto_count = judgment_quality.get("auto_count", 0)
            manual_count = judgment_quality.get("manual_count", 0)
            ratio = judgment_quality.get("auto_vs_manual_ratio")
            ratio_text = ratio if ratio is not None else "n/a"
            lines.extend(
                [
                    "",
                    "## Judgment quality",
                    "",
                    f"- Empty reasons: {empty} / {total} ({empty_pct})",
                    f"- Duplicate reflections: {dup} / {reflection_count} ({dup_pct})",
                    f"- Phases present: {', '.join(phases_present) if phases_present else 'none'}",
                    f"- Phases missing: {', '.join(phases_missing) if phases_missing else 'none'}",
                    f"- Overrides: {judgment_quality.get('override_count', 0)}",
                    f"- Auto vs manual: auto={auto_count} manual={manual_count} ratio={ratio_text}",
                ]
            )
        warnings = report.get("warnings", [])
        if warnings:
            lines.extend(["", "## Warnings", ""])
            for item in warnings:
                if isinstance(item, dict):
                    lines.append(
                        f"- **{item.get('code', 'warn')}**: {item.get('message', '')}"
                    )
        weekly = report.get("weekly_trends", {})
        if isinstance(weekly, dict) and weekly:
            lines.extend(
                [
                    "",
                    "## Weekly trends (good / bad)",
                    "",
                    "| Week | good | bad | pending | unknown |",
                    "|------|------|-----|---------|---------|",
                ]
            )
            for week, counts in weekly.items():
                if isinstance(counts, dict):
                    lines.append(
                        f"| {week} | {counts.get('good', 0)} | {counts.get('bad', 0)} | "
                        f"{counts.get('pending', 0)} | {counts.get('unknown', 0)} |"
                    )
        regrets = report.get("top_regrets", [])
        if isinstance(regrets, list) and regrets:
            lines.extend(["", "## Top regrets", ""])
            for item in regrets:
                if not isinstance(item, dict):
                    continue
                lines.append(f"### {item.get('id', 'decision')}")
                lines.append(
                    f"- Phase: {item.get('phase')} | Choice: {item.get('choice')}"
                )
                lines.append(f"- Reflection: {item.get('reflection', '')}")
                lines.append("")
        stale = report.get("stale_pending", [])
        if isinstance(stale, list) and stale:
            lines.extend(["", "## Stale pending", ""])
            for item in stale:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"- `{item.get('id')}` ({item.get('age_days')}d): {item.get('choice')} — "
                    f"{item.get('reason', '')}"
                )
    slo_violations = analytics.get("slo_violations", [])
    if slo_violations:
        lines.extend(["", "## SLO gate violations", ""])
        for v in slo_violations:
            lines.append(f"- **{v.get('code', 'slo')}**: {v.get('message', '')}")
            lines.append(f"  - Recommendation: {v.get('recommendation', '')}")
    return "\n".join(lines) + "\n"


def format_decision_analytics_html(
    analytics: dict[str, Any], *, since_days: int | None
) -> str:
    md_body = format_decision_analytics_markdown(analytics, since_days=since_days)
    parts: list[str] = []
    in_table = False
    for line in md_body.splitlines():
        if line.startswith("|") and "|" in line[1:]:
            cells = [html_escape(c.strip()) for c in line.strip("|").split("|")]
            if all(set(c) <= set("- ") for c in cells):
                continue
            tag = "th" if not in_table else "td"
            if not in_table:
                parts.append("<table>")
                in_table = True
            parts.append(
                "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>"
            )
            continue
        if in_table:
            parts.append("</table>")
            in_table = False
        if line.startswith("### "):
            parts.append(f"<h3>{html_escape(line[4:])}</h3>")
        elif line.startswith("## "):
            parts.append(f"<h2>{html_escape(line[3:])}</h2>")
        elif line.startswith("# "):
            parts.append(f"<h1>{html_escape(line[2:])}</h1>")
        elif line.startswith("- "):
            parts.append(f"<li>{html_escape(line[2:])}</li>")
        elif line.strip() == "":
            parts.append("<br/>")
        else:
            parts.append(f"<p>{html_escape(line)}</p>")
    if in_table:
        parts.append("</table>")
    body = "\n".join(parts)
    window = html_escape(
        f"last {since_days} days" if since_days is not None else "all time"
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>ai-task decision analytics</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; max-width: 52rem; line-height: 1.45; }}
table {{ border-collapse: collapse; margin: 1rem 0; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }}
th {{ background: #f4f4f4; }}
h1 {{ font-size: 1.5rem; }}
h2 {{ font-size: 1.2rem; margin-top: 1.5rem; }}
</style>
</head>
<body>
<p><em>Window: {window}. Generated: {html_escape(now())}</em></p>
{body}
</body>
</html>
"""


def write_factual_decision_reports(
    root: Path, analytics: dict[str, Any], *, since_days: int | None
) -> tuple[Path, Path]:
    report_dir = app_path(root) / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    md_path = report_dir / f"decisions-{stamp}.md"
    html_path = report_dir / f"decisions-{stamp}.html"
    md_path.write_text(
        format_decision_analytics_markdown(analytics, since_days=since_days),
        encoding="utf-8",
    )
    html_path.write_text(
        format_decision_analytics_html(analytics, since_days=since_days),
        encoding="utf-8",
    )
    return md_path, html_path


def retro_packet_text(
    root: Path,
    analytics: dict[str, Any],
    *,
    since_days: int | None,
    factual_md: Path,
    factual_html: Path,
    stamp: str,
) -> str:
    report_dir = app_path(root) / "reports"
    retro_md = report_dir / f"decisions-{stamp}-retro.md"
    retro_html = report_dir / f"decisions-{stamp}-retro.html"
    window = f"last {since_days} days" if since_days is not None else "all time"
    snapshot = {k: v for k, v in analytics.items() if k != "entries"}
    return f"""# ai-task retro packet ({stamp})

Window: {window}
Repo: {root.resolve()}

## Factual reports (already generated)

- Markdown: `{factual_md.relative_to(root)}`
- HTML: `{factual_html.relative_to(root)}`

## Retro outputs (create in chat with ai-task-retro)

- `{retro_md.relative_to(root)}`
- `{retro_html.relative_to(root)}`

## Next steps (blocking interview)

1. Load skill **ai-task-retro** (not ai-task-teamlead delivery loop).
2. Read analytics snapshot below and factual report paths.
3. Ask **one question at a time** until retro scope is clear; wait for user answers.
4. If incident signals (many `bad`, rework, escalate): load **lessons-learned** when installed.
5. Else load **kaizen** when installed for process improvements.
6. Add **3–7** improvement tasks to `BACKLOG.md` (phase «Retro improvements») via **sdlc-backlog-add**.
7. Write retro MD/HTML with executive summary, Q&A log, task ids, policy tweak notes.

## Analytics snapshot (JSON)

```json
{json.dumps(snapshot, indent=2, ensure_ascii=False)}
```
"""


_operator_identity_cache: str | None = None


def operator_identity() -> str:
    """Best-effort author identity stamped on journal rows and run records.

    Resolution: ``git config user.name`` → ``$USER`` → ``"operator"``. Cached per
    process; never raises. The field is informational only — nothing requires it,
    so the solo-operator flow is unchanged and legacy rows without it stay valid
    (aggregations count them as ``unknown``).
    """
    global _operator_identity_cache
    if _operator_identity_cache is not None:
        return _operator_identity_cache
    name = ""
    try:
        completed = subprocess.run(
            ["git", "config", "user.name"],
            text=True,
            capture_output=True,
            check=False,
        )
        name = (completed.stdout or "").strip()
    except OSError:
        name = ""
    if not name:
        name = os.environ.get("USER", "").strip()
    _operator_identity_cache = name or "operator"
    return _operator_identity_cache

def enforce_risk_confirm(
    task: Task,
    policy: dict[str, Any],
    confirm_risk: bool,
    *,
    risk_ack: str | None = None,
    root: Path | None = None,
    state: dict[str, Any] | None = None,
) -> None:
    gates = risk_gates(task, policy)
    if not gates:
        return
    # a lightweight --risk-ack clears ONLY risk-keyword gates (a
    # false-positive keyword ack), logging the reason to the decision journal.
    # It never clears the P0/P1 high-priority approval gate — that still needs
    # --confirm-risk.
    keyword_gates = [g for g in gates if g.startswith("risk-keyword:")]
    blocking = gates
    if risk_ack and keyword_gates:
        if root is not None:
            maybe_auto_log_anomaly(
                root,
                policy,
                phase="assign",
                choice="risk_ack",
                task_ids=[task.id],
                state=state,
                signals={"risk_gates": keyword_gates},
                reason=f"risk-ack: {risk_ack}",
            )
        blocking = [g for g in gates if not g.startswith("risk-keyword:")]
    if not blocking:
        return
    if confirm_risk:
        return
    die(f"risk gates require --confirm-risk: {', '.join(blocking)}")

def new_decision_entry(
    *,
    phase: str,
    choice: str,
    task_ids: list[str],
    run_ids: list[str],
    signals: dict[str, Any] | None = None,
    reason: str = "",
    auto: bool = False,
) -> dict[str, Any]:
    payload = dict(signals or {})
    if auto:
        payload["auto"] = True
    return {
        "schema_version": 1,
        "id": f"dec-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}",
        "at": now(),
        # Optional authorship: who wrote this row. Legacy rows
        # without it aggregate as "unknown"; no schema bump (additive field).
        "operator": operator_identity(),
        "phase": phase,
        "choice": choice,
        "reason": reason.strip(),
        "signals": payload,
        "task_ids": task_ids,
        "run_ids": run_ids,
        "result": "pending",
        "reflection": "",
        "reflected_at": None,
    }


def maybe_auto_log_anomaly(
    root: Path,
    policy: dict[str, Any],
    *,
    phase: str,
    choice: str,
    task_ids: list[str],
    run_ids: list[str] | None = None,
    state: dict[str, Any] | None = None,
    signals: dict[str, Any] | None = None,
    reason: str = "",
) -> dict[str, Any] | None:
    if not auto_log_anomalies_enabled(policy):
        return None
    if state is None:
        state = load_state(root)
    resolved_run_ids = (
        list(run_ids)
        if run_ids is not None
        else resolve_decision_run_ids(state, task_ids)
    )
    entry = new_decision_entry(
        phase=phase,
        choice=choice,
        task_ids=task_ids,
        run_ids=resolved_run_ids,
        signals=signals,
        reason=reason,
        auto=True,
    )
    if choice == QUOTA_BLIND_DISPATCH_CHOICE:
        payload = entry.get("signals")
        if isinstance(payload, dict):
            payload.setdefault("wave", decision_wave_key(state))
            payload.setdefault("count", 1)
        collapsed = collapse_repeat_quota_blind_dispatch(root, entry)
        if collapsed is not None:
            return collapsed
    return append_decision(root, entry)


def auto_log_run_start_anomalies(
    root: Path,
    policy: dict[str, Any],
    state: dict[str, Any],
    task: Task,
    run_id: str,
    backend_name: str,
    *,
    confirm_risk: bool,
) -> None:
    task_ids = [task.id]
    run_ids = [run_id]
    prior = prior_run_count_for_task(state, task.id, exclude_run_id=run_id)
    if prior >= 1:
        maybe_auto_log_anomaly(
            root,
            policy,
            phase="delivery",
            choice="retry_run",
            task_ids=task_ids,
            run_ids=run_ids,
            state=state,
            signals={"prior_run_count": prior, "task_id": task.id},
            reason=f"retry run for {task.id} (prior runs: {prior})",
        )
    if confirm_risk and risk_gates(task, policy):
        maybe_auto_log_anomaly(
            root,
            policy,
            phase="assign",
            choice="confirm_risk",
            task_ids=task_ids,
            run_ids=run_ids,
            state=state,
            signals={"risk_gates": risk_gates(task, policy), "backend": backend_name},
            reason="run started with --confirm-risk",
        )
    if is_limit_fallback_backend(task, policy, backend_name):
        maybe_auto_log_anomaly(
            root,
            policy,
            phase="delivery",
            choice="limit_fallback",
            task_ids=task_ids,
            run_ids=run_ids,
            state=state,
            signals={
                "backend": backend_name,
                "primaries": primary_backend_names(task, policy),
                "limit_fallback_order": list(
                    policy.get("routing", {}).get(
                        "limit_fallback_order", ["cursor_auto"]
                    )
                ),
            },
            reason=f"limit/fallback backend {backend_name}",
        )


def auto_log_limit_fallback_switch(
    root: Path,
    policy: dict[str, Any],
    state: dict[str, Any],
    task: Task,
    run_id: str,
    *,
    from_backend: str,
    to_backend: str,
    limit_detected: bool,
) -> None:
    if not is_limit_fallback_backend(task, policy, to_backend):
        return
    maybe_auto_log_anomaly(
        root,
        policy,
        phase="delivery",
        choice="limit_fallback",
        task_ids=[task.id],
        run_ids=[run_id],
        state=state,
        signals={
            "from_backend": from_backend,
            "to_backend": to_backend,
            "limit_detected": limit_detected,
            "backend": to_backend,
        },
        reason=f"limit fallback {from_backend} -> {to_backend}",
    )


def auto_log_credential_dead_fallback(
    root: Path,
    policy: dict[str, Any],
    state: dict[str, Any],
    task: Task,
    run_id: str,
    *,
    from_backend: str,
    to_backend: str,
    reason: str,
) -> None:
    """Record a fall-through caused by an unauthenticated backend.

    Unlike the limit fallback this is not gated on the receiving backend being a
    configured limit fallback: the chain moved because a backend can never work
    on this host, and retro needs that visible whichever backend caught the work.
    ``to_backend`` is empty when the chain was exhausted.
    """
    maybe_auto_log_anomaly(
        root,
        policy,
        phase="delivery",
        choice="credential_dead_fallback",
        task_ids=[task.id],
        run_ids=[run_id],
        state=state,
        signals={
            "from_backend": from_backend,
            "to_backend": to_backend,
            "credential_dead": True,
            "backend": to_backend or from_backend,
        },
        reason=(
            f"credential-dead fallback {from_backend} -> {to_backend or 'none'}: {reason}"
        ),
    )


def apply_ingest_stub(root: Path, stub: dict[str, Any]) -> dict[str, Any]:
    entry = new_decision_entry(
        phase=str(stub["phase"]),
        choice=str(stub["choice"]),
        task_ids=list(stub.get("task_ids") or []),
        run_ids=list(stub.get("run_ids") or []),
        signals=dict(stub.get("signals") or {}),
        reason=str(stub.get("reason") or ""),
        auto=True,
    )
    entry["at"] = str(stub.get("at") or entry["at"])
    reflection = str(stub.get("reflection") or "").strip()
    if reflection:
        entry["reflection"] = reflection
    return append_decision(root, entry)
