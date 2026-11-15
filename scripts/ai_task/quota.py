"""Quota domain for the ai-task CLI.

Claude subscription quota supervision extracted verbatim from
scripts/ai-task.py: the rolling-window model (QuotaWindow, aliases,
statusLine snapshot parsing), the [quota] policy readers with their
pessimistic reservation defaults ([quota.reservations], S=5/M=8/L=10,
unknown=5), snapshot freshness + quota_status assembly, refresh-source
command mapping and live-output parsing, auto-resume derivation (resume
time from a fresh snapshot or a backend limit message, retry budget and
the wall-clock cap), admission-control arithmetic (reservation pruning,
reserved totals, budget, the dry reservation_decision), telemetry sample
building/appending/summaries, reservation calibration (percentiles,
recommendations, the [quota.reservations] patch), quota-aware fallback
routing, and the repo-agnostic statusLine settings snippet.

Imports stdlib plus the already-extracted sibling domains (_shared,
backlog, policy, runs, state) only. The quota -> state edge is acyclic
because state.py imports nothing above _shared.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import zoneinfo
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from ai_task._shared import app_path, die, now, pid_alive
from ai_task.backlog import Task, risk_gates
from ai_task.policy import (
    CLAUDE_QUOTA_POOL,
    backend_quota_pool,
    default_policy,
    loads_policy_toml,
    read_config,
)
from ai_task.policy_edit import edit_policy_text
from ai_task.runs import backend_available, backend_cooled_down, parse_iso8601
from ai_task.state import (
    StateLockTimeoutError,
    _read_state_unlocked,
    _state_lock,
    _write_json_atomic,
    state_path,
)

# --- Claude quota source layer ------------------------------------
# Best-effort: reads Claude Code subscription quota snapshots (five_hour /
# seven_day windows) to reserve a small budget and report a stop line. The
# preferred source is a statusLine snapshot file written by an external helper;
# headless refresh can also use Claude Code OAuth credentials or explicit
# operator-named adapters. With no source (or a stale one) this layer is inert:
# limit-pattern detection and [cooldown] continue unchanged and status reports
# quota as unavailable. Supervision is runtime routing only — it never plans or
# reasons about the work itself.

# Canonical rolling-window keys. Snapshots may use either the canonical key or a
# friendly alias; both normalize to the canonical name.
QUOTA_WINDOW_KEYS: tuple[str, ...] = ("five_hour", "seven_day")


QUOTA_WINDOW_ALIASES: dict[str, str] = {
    "five_hour": "five_hour",
    "5h": "five_hour",
    "five_hourly": "five_hour",
    "hourly": "five_hour",
    "rolling_5h": "five_hour",
    "seven_day": "seven_day",
    "7d": "seven_day",
    "weekly": "seven_day",
    "week": "seven_day",
    "rolling_7d": "seven_day",
}


QUOTA_RESERVATION_SIZE_KEYS: dict[str, str] = {
    "s": "s_percentage",
    "m": "m_percentage",
    "l": "l_percentage",
}


@dataclass(frozen=True)
class QuotaWindow:
    """One rolling quota window parsed from a snapshot."""

    name: str
    used_percentage: float
    resets_at: str | None = None
    captured_at: str | None = None

    def remaining_percentage(self) -> float:
        return max(0.0, 100.0 - self.used_percentage)

    def stop_line_percentage(self, reserve_percentage: float) -> float:
        """Used % at which routine dispatch must stop (== 100 - reserve)."""
        return max(0.0, 100.0 - max(0.0, reserve_percentage))

    def remaining_before_stop(self, reserve_percentage: float) -> float:
        """Headroom (percent) before the reserve stop line; 0 once at/over it."""
        return max(
            0.0, self.stop_line_percentage(reserve_percentage) - self.used_percentage
        )

    def at_or_over_stop(self, reserve_percentage: float) -> bool:
        return self.used_percentage >= self.stop_line_percentage(reserve_percentage)


def quota_config(policy: dict[str, Any]) -> dict[str, Any]:
    cfg = policy.get("quota", {})
    return cfg if isinstance(cfg, dict) else {}


def quota_enabled(policy: dict[str, Any]) -> bool:
    return bool(quota_config(policy).get("enabled", False))


def quota_reserve_percentage(policy: dict[str, Any]) -> float:
    return _as_float(quota_config(policy).get("reserve_percentage", 5), 5.0)


def quota_near_limit_threshold(policy: dict[str, Any]) -> float:
    return _as_float(
        quota_config(policy).get("near_limit_start_threshold_percentage", 85), 85.0
    )


def quota_resume_margin_seconds(policy: dict[str, Any]) -> int:
    return int(_as_float(quota_config(policy).get("resume_margin_seconds", 60), 60.0))


def quota_max_snapshot_age_seconds(policy: dict[str, Any]) -> int:
    return int(
        _as_float(quota_config(policy).get("max_snapshot_age_seconds", 900), 900.0)
    )


def quota_refresh_enabled(policy: dict[str, Any]) -> bool:
    return bool(quota_config(policy).get("refresh_enabled", True))


def quota_refresh_on_dispatch(policy: dict[str, Any]) -> bool:
    return bool(quota_config(policy).get("refresh_on_dispatch", True))


def quota_refresh_at_finalize(policy: dict[str, Any]) -> bool:
    """Refresh the quota source at detached finalize before the post snapshot.
    """
    return bool(quota_config(policy).get("refresh_at_finalize", False))


def quota_refresh_timeout_seconds(policy: dict[str, Any]) -> float:
    return max(
        1.0,
        _as_float(quota_config(policy).get("refresh_timeout_seconds", 10), 10.0),
    )


def quota_refresh_sources(policy: dict[str, Any]) -> list[str]:
    cfg = quota_config(policy)
    raw = cfg.get("refresh_sources")
    if raw is None:
        raw = cfg.get("sources")
    if not isinstance(raw, list):
        raw = ["claude_oauth", "ccquota"]
    sources = [str(item).strip() for item in raw if str(item).strip()]
    if sources == ["ccusage", "ccquota"]:
        return ["claude_oauth", "ccquota", "ccusage"]
    return sources


def _as_float(value: Any, default: float) -> float:
    try:
        if isinstance(value, bool):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def quota_reservation_percentage(policy: dict[str, Any], size: str | None) -> float:
    """Pessimistic reservation percent for a backlog Size:.

    Unrecognized or missing sizes use unknown_percentage. Estimates only.
    """
    reservations = quota_config(policy).get("reservations", {})
    if not isinstance(reservations, dict):
        reservations = {}
    unknown = _as_float(reservations.get("unknown_percentage", 5), 5.0)
    normalized = (size or "").strip().lower()
    key = QUOTA_RESERVATION_SIZE_KEYS.get(normalized)
    if key is None:
        return unknown
    return _as_float(reservations.get(key, unknown), unknown)


def quota_snapshot_path(root: Path, policy: dict[str, Any]) -> Path:
    raw = str(quota_config(policy).get("snapshot_path", ".ai-task/quota-snapshot.json"))
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    return root / candidate


def quota_refresh_state_path(root: Path) -> Path:
    return app_path(root) / "quota-refresh.json"


def read_quota_refresh_state(root: Path) -> dict[str, Any] | None:
    path = quota_refresh_state_path(root)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _normalize_window_name(raw: str) -> str | None:
    return QUOTA_WINDOW_ALIASES.get(raw.strip().lower())


def _window_field(entry: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in entry and entry[name] is not None:
            return entry[name]
    return None


def parse_statusline_snapshot(
    data: dict[str, Any],
) -> tuple[dict[str, QuotaWindow], list[str]]:
    """Parse a statusLine snapshot dict into windows keyed by canonical name.

    Accepts both shapes:
      {"windows": {"five_hour": {used_percentage, resets_at, captured_at}, ...}}
      {"five_hour": {...}, "seven_day": {...}}
    A top-level ``captured_at`` is inherited by windows that omit their own.
    Returns (windows, warnings); malformed windows are skipped, not fatal.
    """
    windows: dict[str, QuotaWindow] = {}
    warnings: list[str] = []
    if not isinstance(data, dict):
        return windows, ["snapshot is not a JSON object"]
    top_captured = data.get("captured_at")
    raw_windows = data.get("windows")
    if not isinstance(raw_windows, dict):
        raw_windows = {
            key: value
            for key, value in data.items()
            if _normalize_window_name(str(key)) is not None and isinstance(value, dict)
        }
    for raw_name, raw_entry in raw_windows.items():
        canonical = _normalize_window_name(str(raw_name))
        if canonical is None:
            continue
        if not isinstance(raw_entry, dict):
            warnings.append(f"window {raw_name} is not an object")
            continue
        used_raw = _window_field(
            raw_entry, "used_percentage", "used_pct", "used", "percent_used"
        )
        if used_raw is None:
            warnings.append(f"window {raw_name} missing used_percentage")
            continue
        try:
            used = float(used_raw)
        except (TypeError, ValueError):
            warnings.append(f"window {raw_name} used_percentage not numeric")
            continue
        used = max(0.0, min(100.0, used))
        resets_at = _window_field(raw_entry, "resets_at", "reset_at", "resets")
        captured_at = (
            _window_field(raw_entry, "captured_at", "as_of", "timestamp")
            or top_captured
        )
        windows[canonical] = QuotaWindow(
            name=canonical,
            used_percentage=used,
            resets_at=str(resets_at) if resets_at is not None else None,
            captured_at=str(captured_at) if captured_at is not None else None,
        )
    return windows, warnings


def _snapshot_age_seconds(
    windows: dict[str, QuotaWindow], raw_captured_at: Any
) -> float | None:
    """Seconds since the freshest captured_at across the snapshot, or None."""
    candidates: list[str] = []
    if isinstance(raw_captured_at, str) and raw_captured_at.strip():
        candidates.append(raw_captured_at)
    for window in windows.values():
        if window.captured_at:
            candidates.append(window.captured_at)
    newest: dt.datetime | None = None
    for candidate in candidates:
        parsed = parse_iso8601(candidate)
        if parsed is None:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        if newest is None or parsed > newest:
            newest = parsed
    if newest is None:
        return None
    return (dt.datetime.now(dt.timezone.utc) - newest).total_seconds()


def load_quota_snapshot(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    """Read the statusLine snapshot file (preferred source). No network access.

    Returns a normalized result dict; ``available`` is True only when at least one
    valid window parsed and the snapshot is fresh enough per max_snapshot_age_seconds.
    """
    path = quota_snapshot_path(root, policy)
    result: dict[str, Any] = {
        "source": "statusLine",
        "source_path": str(path),
        "available": False,
        "windows": {},
        "warnings": [],
        "age_seconds": None,
        "stale": False,
        "reason": None,
    }
    if not path.exists():
        result["reason"] = "snapshot file not found"
        return result
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result["reason"] = f"snapshot unreadable: {exc.__class__.__name__}"
        return result
    windows, warnings = parse_statusline_snapshot(raw)
    result["warnings"] = warnings
    if not windows:
        result["reason"] = "no valid quota windows in snapshot"
        return result
    age = _snapshot_age_seconds(
        windows, raw.get("captured_at") if isinstance(raw, dict) else None
    )
    result["age_seconds"] = age
    max_age = quota_max_snapshot_age_seconds(policy)
    if max_age > 0 and age is not None and age > max_age:
        result["stale"] = True
        result["reason"] = f"snapshot stale (age {int(age)}s > {max_age}s)"
        result["windows"] = windows
        return result
    result["available"] = True
    result["windows"] = windows
    return result


def quota_status(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    """Assemble the quota status payload without contacting nonconfigured services.

    Always returns a dict; ``available`` is False (with ``reason``) when quota is
    disabled or no fresh source exists, so callers degrade to limit/cooldown logic.
    """
    cfg = quota_config(policy)
    reserve = quota_reserve_percentage(policy)
    near_limit_threshold = quota_near_limit_threshold(policy)
    payload: dict[str, Any] = {
        "enabled": quota_enabled(policy),
        "available": False,
        "reserve_percentage": reserve,
        "stop_line_percentage": max(0.0, 100.0 - reserve),
        "near_limit_start_threshold_percentage": near_limit_threshold,
        "resume_margin_seconds": quota_resume_margin_seconds(policy),
        "source": None,
        "source_path": None,
        "source_fresh": False,
        "age_seconds": None,
        "windows": [],
        "near_limit": False,
        "at_or_over_stop": False,
        "warnings": [],
        "reason": None,
    }
    if not payload["enabled"]:
        payload["reason"] = "quota supervision disabled in policy"
        return payload
    snapshot = load_quota_snapshot(root, policy)
    payload["source"] = snapshot.get("source")
    payload["source_path"] = snapshot.get("source_path")
    payload["age_seconds"] = snapshot.get("age_seconds")
    payload["warnings"] = list(snapshot.get("warnings", []))
    windows: dict[str, QuotaWindow] = snapshot.get("windows", {})  # type: ignore[assignment]
    if not snapshot.get("available"):
        # Honor the configured snapshot source only; headless refresh sources are
        # never invoked from read-only status. Note opt-in fallback names for the
        # operator without running them.
        configured_sources = cfg.get("sources")
        if isinstance(configured_sources, list) and configured_sources:
            payload["configured_fallback_sources"] = [
                str(item) for item in configured_sources
            ]
        payload["reason"] = snapshot.get("reason") or "no fresh quota source"
        refresh_state = read_quota_refresh_state(root)
        if (
            isinstance(refresh_state, dict)
            and refresh_state.get("refreshed") is False
            and refresh_state.get("reason")
        ):
            payload["headless_refresh"] = {
                "available": False,
                "reason": refresh_state.get("reason"),
                "at": refresh_state.get("at"),
            }
            payload["reason"] = (
                f"{payload['reason']}; headless refresh unavailable: "
                f"{refresh_state.get('reason')}"
            )
        # Surface parsed-but-stale windows for operator visibility.
        if windows:
            payload["windows"] = [
                _quota_window_view(window, reserve, near_limit_threshold)
                for window in _ordered_windows(windows)
            ]
        return payload
    payload["available"] = True
    payload["source_fresh"] = True
    window_views = [
        _quota_window_view(window, reserve, near_limit_threshold)
        for window in _ordered_windows(windows)
    ]
    payload["windows"] = window_views
    payload["near_limit"] = any(view["near_limit"] for view in window_views)
    payload["at_or_over_stop"] = any(view["at_or_over_stop"] for view in window_views)
    return payload


def _ordered_windows(windows: dict[str, QuotaWindow]) -> list[QuotaWindow]:
    ordered = [windows[key] for key in QUOTA_WINDOW_KEYS if key in windows]
    extras = [w for name, w in windows.items() if name not in QUOTA_WINDOW_KEYS]
    return ordered + extras


def _quota_window_view(
    window: QuotaWindow, reserve: float, near_limit_threshold: float
) -> dict[str, Any]:
    return {
        "window": window.name,
        "used_percentage": round(window.used_percentage, 3),
        "remaining_percentage": round(window.remaining_percentage(), 3),
        "stop_line_percentage": round(window.stop_line_percentage(reserve), 3),
        "remaining_before_stop": round(window.remaining_before_stop(reserve), 3),
        "near_limit": window.used_percentage >= near_limit_threshold,
        "at_or_over_stop": window.at_or_over_stop(reserve),
        "resets_at": window.resets_at,
        "captured_at": window.captured_at,
    }


QUOTA_REFRESH_KNOWN_COMMANDS: dict[str, list[str]] = {
    "claude_oauth": ["builtin:claude-oauth-usage"],
    "ccusage": ["npx", "-y", "ccusage", "blocks", "--json", "--active", "--offline"],
    "ccquota": ["ccquota", "--json"],
}


def quota_refresh_source_command(source: str) -> list[str] | None:
    source = source.strip()
    if not source:
        return None
    known = QUOTA_REFRESH_KNOWN_COMMANDS.get(source)
    if known is not None:
        return list(known)
    parts = shlex.split(source)
    return parts or None


def _first_mapping_value(data: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return None


def _coerce_usage_percentage(raw: Any) -> float | None:
    if isinstance(raw, dict):
        raw = _first_mapping_value(
            raw,
            (
                "used_percentage",
                "used_pct",
                "used",
                "percent_used",
                "percentage",
                "percent",
                "utilization",
            ),
        )
    try:
        if raw is None or isinstance(raw, bool):
            return None
        return max(0.0, min(100.0, float(raw)))
    except (TypeError, ValueError):
        return None


def _coerce_reset_value(raw: Any, top_level: Any = None) -> str | None:
    if isinstance(raw, dict):
        raw = _first_mapping_value(
            raw,
            ("resets_at", "reset_at", "resetAt", "resets", "reset"),
        )
    elif top_level is not None:
        raw = top_level
    if raw is None:
        raw = top_level
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _known_usage_window(
    data: dict[str, Any],
    value_names: tuple[str, ...],
    reset_names: tuple[str, ...],
    *,
    name: str,
    captured_at: str,
) -> QuotaWindow | None:
    raw = _first_mapping_value(data, value_names)
    if raw is None:
        return None
    used = _coerce_usage_percentage(raw)
    if used is None:
        return None
    reset = _coerce_reset_value(raw, _first_mapping_value(data, reset_names))
    return QuotaWindow(
        name=name,
        used_percentage=used,
        resets_at=reset,
        captured_at=captured_at,
    )


def parse_known_quota_usage_windows(data: dict[str, Any]) -> dict[str, QuotaWindow]:
    """Parse common Claude quota CLI/API JSON shapes.

    Handles cc-quota / OAuth-style camelCase fields and cclimits ccquota JSON.
    """
    captured_at = now()
    windows: dict[str, QuotaWindow] = {}
    five = _known_usage_window(
        data,
        (
            "fiveHour",
            "five_hour",
            "fiveHourUsage",
            "five_hour_usage",
            "currentsession",
            "currentSession",
        ),
        ("fiveHourResetAt", "five_hour_reset_at", "fiveHourReset", "five_hour_reset"),
        name="five_hour",
        captured_at=captured_at,
    )
    if five is not None:
        windows["five_hour"] = five
    seven = _known_usage_window(
        data,
        (
            "sevenDay",
            "seven_day",
            "sevenDayAll",
            "sevenDayAllModels",
            "seven_day_all_models",
            "currentweekallmodels",
            "currentWeekAllModels",
        ),
        ("sevenDayResetAt", "seven_day_reset_at", "sevenDayReset", "seven_day_reset"),
        name="seven_day",
        captured_at=captured_at,
    )
    if seven is not None:
        windows["seven_day"] = seven
    return windows


def quota_snapshot_payload_from_windows(
    windows: dict[str, QuotaWindow],
) -> dict[str, Any]:
    captured_at = now()
    return {
        "captured_at": captured_at,
        "windows": {
            name: {
                "used_percentage": window.used_percentage,
                "captured_at": window.captured_at or captured_at,
                **({"resets_at": window.resets_at} if window.resets_at else {}),
            }
            for name, window in _sorted_window_items(windows)
        },
    }


def _sorted_window_items(
    windows: dict[str, QuotaWindow],
) -> list[tuple[str, QuotaWindow]]:
    ordered_names = list(QUOTA_WINDOW_KEYS)
    extra_names = sorted(name for name in windows if name not in QUOTA_WINDOW_KEYS)
    return [
        (name, windows[name]) for name in ordered_names + extra_names if name in windows
    ]


def _find_quota_windows_in_json(data: Any) -> tuple[dict[str, QuotaWindow], list[str]]:
    if isinstance(data, dict):
        known_windows = parse_known_quota_usage_windows(data)
        if known_windows:
            return known_windows, []
        windows, warnings = parse_statusline_snapshot(data)
        if windows:
            return windows, warnings
        for key in ("data", "result", "quota", "usage", "limits", "rate_limits"):
            if key not in data:
                continue
            nested_windows, nested_warnings = _find_quota_windows_in_json(data[key])
            if nested_windows:
                return nested_windows, nested_warnings
    if isinstance(data, list):
        for item in data:
            windows, warnings = _find_quota_windows_in_json(item)
            if windows:
                return windows, warnings
    return {}, ["no valid quota windows in live-source output"]


def parse_quota_refresh_output(text: str) -> tuple[dict[str, Any], list[str]]:
    raw = json.loads(text)
    windows, warnings = _find_quota_windows_in_json(raw)
    if not windows:
        raise ValueError("no valid quota windows in live-source output")
    return quota_snapshot_payload_from_windows(windows), warnings


def compact_quota_status(status: dict[str, Any]) -> dict[str, Any]:
    """A compact quota object for `status --json`, including unavailable reasons."""
    return {
        "enabled": status.get("enabled", False),
        "available": status.get("available", False),
        "source": status.get("source"),
        "source_fresh": status.get("source_fresh", False),
        "age_seconds": status.get("age_seconds"),
        "reason": status.get("reason"),
        "reserve_percentage": status.get("reserve_percentage"),
        "stop_line_percentage": status.get("stop_line_percentage"),
        "near_limit": status.get("near_limit", False),
        "at_or_over_stop": status.get("at_or_over_stop", False),
        "windows": [
            {
                "window": view.get("window"),
                "used_percentage": view.get("used_percentage"),
                "remaining_before_stop": view.get("remaining_before_stop"),
                "resets_at": view.get("resets_at"),
            }
            for view in status.get("windows", [])
        ],
    }


def quota_status_warnings(status: dict[str, Any]) -> list[str]:
    """Human warning lines for plain `status` near/over the configured threshold."""
    if not status.get("available"):
        if status.get("enabled"):
            reason = status.get("reason") or "no fresh quota source"
            return [
                (
                    "- quota source unavailable: "
                    f"{reason}; Claude quota admission control is inactive"
                )
            ]
        return []
    lines: list[str] = []
    for view in status.get("windows", []):
        if view.get("at_or_over_stop"):
            resets = view.get("resets_at") or "?"
            lines.append(
                f"- quota {view.get('window')}: used {view.get('used_percentage')}% "
                f"at/over reserve stop line {view.get('stop_line_percentage')}% "
                f"(resets {resets})"
            )
        elif view.get("near_limit"):
            threshold = status.get("near_limit_start_threshold_percentage")
            lines.append(
                f"- quota {view.get('window')}: used {view.get('used_percentage')}% "
                f"near limit (threshold {threshold}%); "
                f"{view.get('remaining_before_stop')}% left before reserve stop"
            )
    return lines


# --- Claude quota auto-resume after reset -------------------------
# When Claude is blocked by a quota reservation or a real limit message, the run is
# a recoverable *wait* state (``waiting_quota``), not failed work. The resume time
# is the LATEST reset among windows at/over the stop line — all blocked windows
# must clear before a probe can succeed — or, for repos with no fresh
# quota snapshot, parsed from the backend limit message; in both cases
# ``resume_margin_seconds`` is added so the window is treated as usable only after
# it has actually rolled over. ``wait-runs --resume-on-quota`` waits past that
# time, re-derives the resume time from a fresh snapshot on each wake (a
# still-blocked window re-arms WITHOUT consuming budget, bounded by the
# ``resume_max_wait_seconds`` wall-clock cap), probes Claude recovery, and
# re-launches the SAME packet in the SAME worktree (reusing the existing lease) up
# to a bounded retry budget so it can never wake/retry forever if Claude stays
# limited.


# --- Claude quota auto-resume after reset -------------------------
# When Claude is blocked by a quota reservation or a real limit message, the run is
# a recoverable *wait* state (``waiting_quota``), not failed work. The resume time
# is the LATEST reset among windows at/over the stop line — all blocked windows
# must clear before a probe can succeed — or, for repos with no fresh
# quota snapshot, parsed from the backend limit message; in both cases
# ``resume_margin_seconds`` is added so the window is treated as usable only after
# it has actually rolled over. ``wait-runs --resume-on-quota`` waits past that
# time, re-derives the resume time from a fresh snapshot on each wake (a
# still-blocked window re-arms WITHOUT consuming budget, bounded by the
# ``resume_max_wait_seconds`` wall-clock cap), probes Claude recovery, and
# re-launches the SAME packet in the SAME worktree (reusing the existing lease) up
# to a bounded retry budget so it can never wake/retry forever if Claude stays
# limited.

# Default cap on auto-resume attempts after the first quota pause, so a window that
# resets while Claude is still limited cannot drive an infinite wake/retry loop.
DEFAULT_QUOTA_RESUME_MAX_ATTEMPTS = 3


# Hard wall-clock cap on budget-free re-arming, measured from the
# first quota pause (``first_paused_at`` on the run record). Default 8 days covers
# a full seven_day window reset; past the cap the auto-resume budget is closed
# (attempts_remaining -> 0) and the run stays waiting_quota for the operator.
DEFAULT_QUOTA_RESUME_MAX_WAIT_SECONDS = 8 * 24 * 3600  # 691200


# Parse a reset hint out of a real limit message, e.g. "try again in 2h 30m",
# "retry after 45 minutes", "resets in 90s". Best-effort; absent → no resume time
# from text and the run degrades to the existing cooldown behavior.
_LIMIT_RESET_RE = re.compile(
    r"(?:try again|retry|resets?|available again|come back)"
    r"[^0-9]{0,20}?"
    r"(?P<hours>\d+)\s*(?:h|hour|hours|hr|hrs)?"
    r"(?:[^0-9]{0,4}(?P<minutes>\d+)\s*(?:m|min|mins|minute|minutes))?"
    r"(?:[^0-9]{0,4}(?P<seconds>\d+)\s*(?:s|sec|secs|second|seconds))?",
    re.IGNORECASE,
)


# A bare single unit, e.g. "try again in 45 minutes" / "retry in 30s".
_LIMIT_RESET_SINGLE_RE = re.compile(
    r"(?:try again|retry|resets?|available again|come back)"
    r"[^0-9]{0,20}?"
    r"(?P<amount>\d+)\s*(?P<unit>h|hr|hrs|hour|hours|m|min|mins|minute|minutes|s|sec|secs|second|seconds)\b",
    re.IGNORECASE,
)


# Absolute wall-clock reset, the current real limit format, e.g. "You've hit your
# session limit · resets 4:50am (Europe/Berlin)" or "resets at 22:00". Requires
# minutes or am/pm so a bare "resets 5" stays ambiguous; the optional
# parenthesized zone must look like an IANA name (unknown zones fall back to UTC).
_LIMIT_RESET_CLOCK_RE = re.compile(
    r"(?:try again|retry|resets?|available again|come back)"
    r"[^0-9]{0,20}?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?(?:\s*(?P<ampm>am|pm)\b)?"
    r"(?:[^0-9(]{0,10}\((?P<zone>[A-Za-z_]+/[A-Za-z_+-]+)\))?",
    re.IGNORECASE,
)


def quota_resume_max_attempts(policy: dict[str, Any]) -> int:
    """Bounded auto-resume retry budget; 0 disables auto-resume (always >= 0)."""
    raw = quota_config(policy).get(
        "resume_max_attempts", DEFAULT_QUOTA_RESUME_MAX_ATTEMPTS
    )
    return max(0, int(_as_float(raw, float(DEFAULT_QUOTA_RESUME_MAX_ATTEMPTS))))


def quota_resume_max_wait_seconds(policy: dict[str, Any]) -> int:
    """Wall-clock cap on budget-free re-arming; 0 disables the cap (always >= 0)."""
    raw = quota_config(policy).get(
        "resume_max_wait_seconds", DEFAULT_QUOTA_RESUME_MAX_WAIT_SECONDS
    )
    return max(0, int(_as_float(raw, float(DEFAULT_QUOTA_RESUME_MAX_WAIT_SECONDS))))


def quota_resume_wait_cap_exceeded(
    run: dict[str, Any],
    policy: dict[str, Any],
    *,
    now_dt: dt.datetime | None = None,
) -> bool:
    """Whether the run has waited on quota past the hard wall-clock cap.

    Measured from ``first_paused_at`` (recorded at the first quota pause); a run
    with no recorded first pause is never capped here — the caller records the
    timestamp before re-arming so the clock starts on the first wake at latest.
    """
    cap = quota_resume_max_wait_seconds(policy)
    if cap <= 0:
        return False
    first = parse_iso8601(str(run.get("first_paused_at") or ""))
    if first is None:
        return False
    if first.tzinfo is None:
        first = first.replace(tzinfo=dt.timezone.utc)
    current = now_dt or dt.datetime.now(dt.timezone.utc)
    return (current - first).total_seconds() > cap


def _apply_resume_margin(reset: dt.datetime, margin_seconds: int) -> str:
    """ISO8601 of ``reset`` plus the configured margin (never before reset)."""
    when = reset + dt.timedelta(seconds=max(0, margin_seconds))
    return when.replace(microsecond=0).isoformat()


def quota_resume_after_from_status(
    status: dict[str, Any], policy: dict[str, Any]
) -> tuple[str | None, str | None]:
    """Safe resume time + window name from a fresh quota snapshot.

    Picks the LATEST ``resets_at`` among windows at/over the reserve stop line —
    every blocked window must clear before a resume can succeed —
    and adds ``resume_margin_seconds``. Returns (resume_after_iso, window_name);
    both None when no fresh source, no at-or-over-stop window, or no parseable
    reset time.
    """
    if not status.get("available"):
        return None, None
    margin = quota_resume_margin_seconds(policy)
    best: dt.datetime | None = None
    best_window: str | None = None
    for view in status.get("windows", []):
        if not view.get("at_or_over_stop"):
            continue
        reset = parse_iso8601(str(view.get("resets_at") or "")) or None
        if reset is None:
            continue
        if reset.tzinfo is None:
            reset = reset.replace(tzinfo=dt.timezone.utc)
        if best is None or reset > best:
            best = reset
            best_window = str(view.get("window"))
    if best is None:
        return None, None
    return _apply_resume_margin(best, margin), best_window


def parse_limit_reset_after(
    log_text: str, policy: dt.datetime | dict[str, Any], *, margin_seconds: int = 0
) -> str | None:
    """Resume time parsed from a backend limit message, or None.

    The reset hint in the text is either a *duration from now* ("try again in 2h"),
    added to the current time, or an *absolute wall-clock time* ("resets 4:50am
    (Europe/Berlin)"), resolved to its next occurrence in the stated zone (UTC when
    the zone is missing or unknown). Both get ``resume_margin_seconds`` so repos
    with no quota snapshot still get a concrete ``resume_after``. Accepts either a
    policy dict (to read the margin) or, for testing, an explicit "now" datetime +
    margin_seconds. Durations take precedence over clock times.
    """
    if isinstance(policy, dict):
        margin = quota_resume_margin_seconds(policy)
        base = dt.datetime.now(dt.timezone.utc)
    else:
        margin = max(0, margin_seconds)
        base = policy
    if not log_text:
        return None
    delta = _parse_limit_reset_delta(log_text)
    if delta is not None:
        return _apply_resume_margin(base + delta, margin)
    reset = _parse_limit_reset_clock(log_text, base)
    if reset is None:
        return None
    return _apply_resume_margin(reset, margin)


def _parse_limit_reset_delta(log_text: str) -> dt.timedelta | None:
    match = _LIMIT_RESET_RE.search(log_text)
    if match and (match.group("minutes") or match.group("seconds")):
        hours = int(match.group("hours") or 0)
        minutes = int(match.group("minutes") or 0)
        seconds = int(match.group("seconds") or 0)
        total = hours * 3600 + minutes * 60 + seconds
        if total > 0:
            return dt.timedelta(seconds=total)
    single = _LIMIT_RESET_SINGLE_RE.search(log_text)
    if single:
        amount = int(single.group("amount"))
        unit = single.group("unit").lower()
        if unit.startswith("h"):
            factor = 3600
        elif unit.startswith("m"):
            factor = 60
        else:
            factor = 1
        if amount > 0:
            return dt.timedelta(seconds=amount * factor)
    return None


def _parse_limit_reset_clock(log_text: str, base: dt.datetime) -> dt.datetime | None:
    """Next UTC occurrence of an absolute wall-clock reset hint, or None.

    A bare hour with no minutes and no am/pm ("resets 5") is too ambiguous to
    schedule. Unknown or malformed timezone names degrade to UTC rather than
    dropping the hint entirely.
    """
    match = _LIMIT_RESET_CLOCK_RE.search(log_text)
    if match is None:
        return None
    minute_raw = match.group("minute")
    ampm = (match.group("ampm") or "").lower()
    if minute_raw is None and not ampm:
        return None
    hour = int(match.group("hour"))
    minute = int(minute_raw or 0)
    if minute > 59:
        return None
    if ampm:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    elif hour > 23:
        return None
    tz: dt.tzinfo = dt.timezone.utc
    zone = match.group("zone")
    if zone:
        try:
            tz = zoneinfo.ZoneInfo(zone)
        except (KeyError, ValueError, OSError):
            tz = dt.timezone.utc
    if base.tzinfo is None:
        base = base.replace(tzinfo=dt.timezone.utc)
    local_now = base.astimezone(tz)
    reset = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if reset <= local_now:
        reset += dt.timedelta(days=1)
    return reset.astimezone(dt.timezone.utc)


def resume_after_is_due(resume_after: str | None) -> bool:
    """Whether the recorded resume time has passed (None → treat as due)."""
    if not resume_after:
        return True
    parsed = parse_iso8601(resume_after)
    if parsed is None:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc) >= parsed


# --- Claude quota admission control -------------------------------
# Reservations make parallel Claude dispatch budget-aware. Before a Claude-backed
# run starts we reserve a pessimistic upper-bound percentage (by task Size:) under
# the shared state lock, so concurrent `ai-task run` processes cannot consume the
# same remaining budget. The effective budget is the *minimum* room before the
# reserve stop line across fresh windows, after subtracting already-active
# reservations. Reservations are estimates, not exact cost prediction; they are
# released on success, failure, stop, and never taken on a dry-run.


# --- Claude quota admission control -------------------------------
# Reservations make parallel Claude dispatch budget-aware. Before a Claude-backed
# run starts we reserve a pessimistic upper-bound percentage (by task Size:) under
# the shared state lock, so concurrent `ai-task run` processes cannot consume the
# same remaining budget. The effective budget is the *minimum* room before the
# reserve stop line across fresh windows, after subtracting already-active
# reservations. Reservations are estimates, not exact cost prediction; they are
# released on success, failure, stop, and never taken on a dry-run.

# A backend is gated when its quota_pool is claude: the backend named
# claude by default, any other one only by declaring it. cursor_*, codex and devin
# bill separate pools and are never gated by these reservations.
def is_quota_gated_backend(name: str, policy: dict[str, Any]) -> bool:
    return backend_quota_pool(name, policy) == CLAUDE_QUOTA_POOL


def prune_stale_quota_reservations(state: dict[str, Any]) -> None:
    """Drop reservations whose run is gone or no longer holding budget.

    A reservation is live only while its run is still queued/running/paused (and,
    once a pid is known, that pid is alive). Mirrors prune_stale_leases so a killed
    supervisor or reaped backend frees the budget it had reserved.
    """
    reservations = state.setdefault("quota_reservations", {})
    runs = state.get("runs", {})
    for run_id, reservation in list(reservations.items()):
        if not isinstance(reservation, dict):
            reservations.pop(run_id, None)
            continue
        run = runs.get(run_id, {})
        if not run:
            # No run record yet (just acquired) — keep; or run pruned — drop.
            if reservation.get("detached"):
                continue
            reservations.pop(run_id, None)
            continue
        if run.get("status") in {"queued", "running", "paused"}:
            pid = run.get("pid")
            if pid is None or (isinstance(pid, int) and pid_alive(pid)):
                continue
        reservations.pop(run_id, None)


def active_quota_reservations(state: dict[str, Any]) -> list[dict[str, Any]]:
    prune_stale_quota_reservations(state)
    return [
        reservation
        for reservation in state.get("quota_reservations", {}).values()
        if isinstance(reservation, dict)
    ]


def quota_reserved_total(state: dict[str, Any]) -> float:
    """Sum of active reservation percentages currently held against the budget."""
    return sum(
        _as_float(reservation.get("percentage", 0), 0.0)
        for reservation in active_quota_reservations(state)
    )


def quota_available_budget(
    status: dict[str, Any], state: dict[str, Any]
) -> float | None:
    """Effective free budget = min over fresh windows of room before the stop line,
    after subtracting already-active reservations. None when quota is unavailable.

    available = min((100 - reserve) - used) - sum(active reservations)
    """
    if not status.get("available"):
        return None
    windows = status.get("windows", [])
    if not windows:
        return None
    reserved = quota_reserved_total(state)
    per_window = [
        _as_float(view.get("remaining_before_stop", 0), 0.0) - reserved
        for view in windows
    ]
    return min(per_window)


def reservation_decision(
    task: Task,
    policy: dict[str, Any],
    status: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    """Compute (without mutating state) whether a Claude reservation would fit.

    Returns the routing-facing view: required percent, available budget, whether it
    fits, and a blocked reason when it does not. ``quota_available`` is None when no
    fresh quota source exists, in which case admission control is inert (fits=True)
    and dispatch degrades to limit-pattern/cooldown behavior.
    """
    required = quota_reservation_percentage(policy, task.size)
    if not status.get("available"):
        return {
            "required": round(required, 3),
            "available": None,
            "fits": True,
            "blocked_reason": None,
        }
    available = quota_available_budget(status, state)
    fits = available is not None and required <= available
    blocked_reason: str | None = None
    if not fits:
        if status.get("at_or_over_stop"):
            blocked_reason = "at_or_over_stop_line"
        else:
            blocked_reason = "insufficient_budget"
    return {
        "required": round(required, 3),
        "available": None if available is None else round(available, 3),
        "fits": fits,
        "blocked_reason": blocked_reason,
    }


def release_quota_reservation(state: dict[str, Any], run_id: str) -> None:
    """Release a run's quota reservation in-memory (persisted by save_state merge)."""
    state.get("quota_reservations", {}).pop(run_id, None)


def quota_reservations_view(state: dict[str, Any]) -> dict[str, Any]:
    """Active reservations for `status --json` (visible admission-control state)."""
    return {
        run_id: dict(reservation)
        for run_id, reservation in state.get("quota_reservations", {}).items()
        if isinstance(reservation, dict)
    }


# --- Claude quota telemetry ---------------------------------------
# Best-effort structured samples so the hand-picked [quota.reservations] percentages
# can later be replaced by observed p80/p95 deltas. For every Claude
# run we append one JSON line capturing the pre/post quota snapshot, the reservation,
# task id + Size:, backend/model, elapsed, exit status, retry/limit signals, and a
# cheap changed-file/diffstat summary. Telemetry is NEVER required for delivery: a
# missing quota source or unavailable diffstat degrades the sample to partial, and a
# write failure is swallowed so it can never break or fail a run. Samples carry a
# schema_version and contain NO secrets and NO absolute transcript content — paths
# are redacted to repo-relative form before they are written.
QUOTA_TELEMETRY_SCHEMA = 1


QUOTA_TELEMETRY_FILENAME = "quota-telemetry.jsonl"


QUOTA_TELEMETRY_DEFAULT_PATH = f".ai-task/{QUOTA_TELEMETRY_FILENAME}"


# Diffstat is a cheap summary, not a transcript; cap it so a huge wave cannot bloat
# the telemetry file or smuggle large blobs of changed content into a sample.
QUOTA_TELEMETRY_DIFFSTAT_MAX_CHARS = 4000


def quota_telemetry_path(root: Path, policy: dict[str, Any]) -> Path:
    """Telemetry JSONL location from `[quota] telemetry_path`.

    Mirrors quota_snapshot_path semantics: a relative path resolves under the repo
    root (per-repo isolation, the default), while an absolute path (after ``~``
    expansion) is honored as-is. Pointing several repos at one shared absolute file
    pools their samples so `quota calibrate` can reach its sample minimum across
    repos; each sample's ``repo_id`` keeps merged data attributable.
    """
    raw = str(quota_config(policy).get("telemetry_path", QUOTA_TELEMETRY_DEFAULT_PATH))
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    return root / candidate


def quota_telemetry_repo_id(root: Path) -> str:
    """Stable repo identifier carried by every telemetry sample.

    Prefers ``project_id`` from `.ai-task/config.toml`, falling back to the repo
    directory name, so samples pooled into one shared telemetry file stay
    attributable to their source repo. Best-effort: never raises.
    """
    try:
        raw = str(read_config(root).get("project_id") or "").strip()
    except (OSError, ValueError):
        raw = ""
    return raw or root.name or "project"


def _redact_abs_paths(text: str, root: Path) -> str:
    """Strip absolute paths so a sample never carries machine-specific or transcript
    content. The repo root and the user's home are rewritten to stable placeholders;
    any remaining POSIX/Windows absolute path token is reduced to its basename.
    """
    if not text:
        return text
    redacted = text
    for needle, replacement in (
        (str(root.resolve()), "<repo>"),
        (str(root), "<repo>"),
        (str(Path.home()), "<home>"),
    ):
        if needle and needle not in ("", "/"):
            redacted = redacted.replace(needle, replacement)
    # Reduce any leftover *absolute* path tokens (e.g. a worktree under /tmp, a
    # Windows drive path) to their basename so no absolute filesystem location or
    # transcript path survives. The token must begin at a boundary (start of line or
    # whitespace) so repo-relative paths like ``.ai-task/quota-snapshot.json`` — which
    # are already safe — are left intact rather than mangled mid-string.
    redacted = re.sub(
        r"(?m)(?<![^\s])(?:[A-Za-z]:\\|/)[^\s,;:'\"]+",
        lambda m: re.split(r"[\\/]", m.group(0).rstrip("/\\"))[-1] or m.group(0),
        redacted,
    )
    return redacted


def telemetry_quota_snapshot(status: dict[str, Any]) -> dict[str, Any]:
    """A minimal, secret-free quota view for a telemetry sample.

    Carries only window usage (enough to estimate an observed delta) and freshness;
    never the source file path. ``available: False`` (with a reason) when no fresh
    source exists so the sample degrades to partial instead of being dropped.
    """
    if not status.get("available"):
        return {
            "available": False,
            "reason": status.get("reason") or "no fresh quota source",
        }
    return {
        "available": True,
        "source": status.get("source"),
        "age_seconds": status.get("age_seconds"),
        "windows": [
            {
                "window": view.get("window"),
                "used_percentage": view.get("used_percentage"),
                "remaining_before_stop": view.get("remaining_before_stop"),
            }
            for view in status.get("windows", [])
        ],
    }


def _backend_arg_value(backend: dict[str, Any], flag: str) -> str | None:
    args = [str(arg) for arg in backend.get("args", [])]
    for index, arg in enumerate(args):
        if arg == flag and index + 1 < len(args):
            return args[index + 1]
    return None


def backend_model_label(backend: dict[str, Any]) -> str | None:
    """Best-effort model name from a backend's args (token after ``--model``)."""
    return _backend_arg_value(backend, "--model")


def backend_model_info(backend: dict[str, Any]) -> dict[str, str | None]:
    """Model and effort a backend runs with, for the run record.

    Read from the backend's own args (``--model`` / ``--effort``), so it names
    what the launch command actually passed; ``None`` where the backend leaves
    the choice to the CLI's default.
    """
    effort = _backend_arg_value(backend, "--effort")
    if effort is None and Path(str(backend.get("command", ""))).name == "codex":
        args = [str(arg) for arg in backend.get("args", [])]
        for index, arg in enumerate(args[:-1]):
            if arg in {"-c", "--config"} and args[index + 1].startswith("model_reasoning_effort="):
                effort = args[index + 1].split("=", 1)[1].strip('"\'')
    return {
        "model": backend_model_label(backend),
        "effort": effort,
    }


def model_info_text(info: dict[str, Any]) -> str:
    """``sonnet, effort high`` / ``sonnet`` / ``""`` when no model is known."""
    model = info.get("model")
    if not model:
        return ""
    effort = info.get("effort")
    return f"{model}, effort {effort}" if effort else str(model)


IN_SESSION_SUFFIX = "_subagent"
_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def in_session_model_request(policy: dict[str, Any], backend_name: str) -> dict[str, Any]:
    """Model and effort an in-session run asks its subagent for.

    ``claude_subagent`` takes them from ``[backends.claude]`` and
    ``codex_subagent`` from ``[backends.codex]``, after ``model_override``, so the
    subagent runs on what the headless worker of the same vendor would.
    """
    source = backend_name.removesuffix(IN_SESSION_SUFFIX)
    backend = policy.get("backends", {}).get(source)
    if source == backend_name or not isinstance(backend, dict):
        return {"requested_model": None, "requested_effort": None, "requested_from": None}
    info = backend_model_info(backend)
    return {
        "requested_model": info["model"],
        "requested_effort": info["effort"],
        "requested_from": f"backends.{source}",
    }


def claude_config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def subagent_transcript_path(agent_id: str) -> Path | None:
    """The Claude Code transcript of one subagent, found by the agent id the Agent tool returns.

    Claude Code writes it as ``projects/<project>/<session>/subagents/agent-<id>.jsonl``
    under its config directory. The layout is not a published contract, so a miss
    returns ``None`` and the caller falls back to the reported or requested values.
    """
    if not _AGENT_ID_RE.match(agent_id):
        return None
    matches = sorted(claude_config_dir().glob(f"projects/*/*/subagents/agent-{agent_id}.jsonl"))
    return matches[-1] if matches else None


def subagent_transcript_model(path: Path) -> dict[str, Any] | None:
    """Model and effort the API served a subagent, read from its transcript.

    Each assistant line carries ``message.model`` (the model that answered) and
    ``effort``. Synthetic lines and API error lines are skipped. ``None`` when no
    answered line exists.
    """
    models: list[str] = []
    efforts: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        if entry.get("isApiErrorMessage"):
            continue
        message = entry.get("message")
        model = message.get("model") if isinstance(message, dict) else None
        if not isinstance(model, str) or not model or model.startswith("<"):
            continue
        models.append(model)
        effort = entry.get("effort")
        if isinstance(effort, str) and effort:
            efforts.append(effort)
    if not models:
        return None
    return {
        "model": models[-1],
        "effort": efforts[-1] if efforts else None,
        "models_seen": sorted(set(models)),
    }


def model_matches_request(served: str | None, requested: str | None) -> bool:
    """``claude-sonnet-5-5`` serves the alias ``sonnet``; an empty request matches anything."""
    if not requested:
        return True
    if not served:
        return False
    served_l, requested_l = served.lower(), requested.lower()
    return served_l == requested_l or requested_l in served_l.split("-")


def build_quota_telemetry_sample(
    *,
    root: Path,
    run_id: str,
    task: Task,
    backend: str,
    backend_config: dict[str, Any],
    reservation_percentage: float | None,
    quota_reserved: bool,
    pre_quota: dict[str, Any] | None,
    post_quota: dict[str, Any] | None,
    elapsed_seconds: float | None,
    exit_status: str,
    exit_code: Any,
    limited: bool,
    stalled: bool,
    blocked_reason: str | None,
    attempts: int,
    sample_kind: str,
    diffstat: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assemble one telemetry sample.

    ``sample_kind`` is ``single`` or ``parallel``. A parallel sample is flagged
    ``confidence: low`` because per-run quota attribution is not reliable inside a
    wave (no per-run usage metadata). A sample missing its pre or post quota
    snapshot is ``partial`` so the calibrator can exclude it from
    high-confidence delta estimates. ``repo_id`` attributes the
    sample to its source repo when several repos pool telemetry into one shared
    file; it is an additive optional field, so ``schema_version`` stays 1 —
    readers tolerate its absence in older samples.
    """
    has_pre = bool(pre_quota and pre_quota.get("available"))
    has_post = bool(post_quota and post_quota.get("available"))
    partial = not (has_pre and has_post)
    confidence = "high"
    if sample_kind == "parallel" or partial:
        confidence = "low"
    sample: dict[str, Any] = {
        "schema_version": QUOTA_TELEMETRY_SCHEMA,
        "recorded_at": now(),
        "repo_id": quota_telemetry_repo_id(root),
        "run_id": run_id,
        "task_id": task.id,
        "size": task.size or None,
        "backend": backend,
        "model": backend_model_label(backend_config),
        "reservation_percentage": (
            None if reservation_percentage is None else round(reservation_percentage, 3)
        ),
        "quota_reserved": bool(quota_reserved),
        "pre_quota": pre_quota if pre_quota is not None else {"available": False},
        "post_quota": post_quota if post_quota is not None else {"available": False},
        "elapsed_seconds": (
            None if elapsed_seconds is None else round(elapsed_seconds, 3)
        ),
        "exit_status": exit_status,
        "exit_code": exit_code,
        "limited": bool(limited),
        "stalled": bool(stalled),
        "blocked_reason": blocked_reason,
        "attempts": attempts,
        "sample_kind": sample_kind,
        "confidence": confidence,
        "partial": partial,
    }
    if diffstat is not None:
        sample["diffstat"] = diffstat
    return sample


def append_quota_telemetry_sample(
    root: Path, policy: dict[str, Any], sample: dict[str, Any]
) -> bool:
    """Append one sample to the telemetry JSONL. Best-effort: never raises.
    """
    try:
        path = quota_telemetry_path(root, policy)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(sample, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return True
    except (OSError, TypeError, ValueError):
        return False


def other_active_quota_run(
    state: dict[str, Any], run_id: str, policy: dict[str, Any]
) -> bool:
    """True when another run is concurrently using the Claude quota at launch.

    Used to tag a telemetry sample as part of a parallel wave (low confidence): a
    peer run is concurrent when it holds a quota reservation, or is running/paused on
    a quota-gated backend. Without per-run usage metadata we cannot attribute spend
    inside a wave, so any concurrency forces ``sample_kind: parallel``.
    """
    for other_id in state.get("quota_reservations", {}):
        if other_id != run_id:
            return True
    for other_id, other_run in state.get("runs", {}).items():
        if other_id == run_id or not isinstance(other_run, dict):
            continue
        if other_run.get("status") in {"running", "paused"} and is_quota_gated_backend(
            str(other_run.get("backend", "")), policy
        ):
            return True
    return False


def quota_telemetry_summary(
    root: Path, policy: dict[str, Any], *, recent_limit: int = 50
) -> dict[str, Any]:
    """Recent telemetry count + last-sample time for status surfaces.

    Reads only the tail of the JSONL (best-effort, never raises): reports the total
    sample count, the most recent ``recorded_at``, and how many of the recent
    samples were high vs low confidence so an operator can see whether usable
    calibration data is accumulating.
    """
    summary: dict[str, Any] = {
        "available": False,
        "count": 0,
        "last_sample_at": None,
        "recent_high_confidence": 0,
        "recent_low_confidence": 0,
    }
    path = quota_telemetry_path(root, policy)
    try:
        if not path.exists():
            return summary
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except OSError:
        return summary
    if not lines:
        return summary
    summary["available"] = True
    summary["count"] = len(lines)
    recent: list[dict[str, Any]] = []
    for line in lines[-recent_limit:]:
        try:
            parsed = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            recent.append(parsed)
    for parsed in recent:
        if parsed.get("confidence") == "low":
            summary["recent_low_confidence"] += 1
        else:
            summary["recent_high_confidence"] += 1
    last_at: str | None = None
    for parsed in recent:
        stamp = parsed.get("recorded_at")
        if isinstance(stamp, str) and stamp.strip():
            last_at = stamp
    summary["last_sample_at"] = last_at
    return summary


QUOTA_CALIBRATION_MIN_SAMPLES = 100


# Dry-run (report-only) may surface a recommendation from far fewer samples so an
# operator can watch the estimate form; this per-size floor only gates whether a
# size gets a recommendation at all, never an apply.
QUOTA_CALIBRATION_DRY_RUN_MIN_PER_SIZE = 10


# Conservative floor: never recommend a reservation below this percent, so a few
# tiny-delta samples cannot drive the reserved budget to ~0 and overbook the window.
QUOTA_CALIBRATION_FLOOR_PERCENTAGE = 3.0


# The size keys we recommend for, in the order shown in output / patch.
QUOTA_CALIBRATION_SIZE_ORDER: tuple[tuple[str, str], ...] = (
    ("S", "s_percentage"),
    ("M", "m_percentage"),
    ("L", "l_percentage"),
    ("unknown", "unknown_percentage"),
)


def quota_calibration_min_samples(policy: dict[str, Any]) -> int:
    """Minimum high-confidence samples required before `calibrate --apply` is allowed.

    Configurable via `[quota] calibration_min_samples`; defaults to 100. Values below
    1 are clamped to 1 so apply always requires at least one observation.
    """
    raw = quota_config(policy).get(
        "calibration_min_samples", QUOTA_CALIBRATION_MIN_SAMPLES
    )
    return max(1, int(_as_float(raw, float(QUOTA_CALIBRATION_MIN_SAMPLES))))


def quota_calibration_floor(policy: dict[str, Any]) -> float:
    """Minimum recommendable reservation percent (never recommend below this)."""
    raw = quota_config(policy).get(
        "calibration_floor_percentage", QUOTA_CALIBRATION_FLOOR_PERCENTAGE
    )
    return max(0.0, _as_float(raw, QUOTA_CALIBRATION_FLOOR_PERCENTAGE))


def read_quota_telemetry_samples(
    root: Path, policy: dict[str, Any]
) -> list[dict[str, Any]]:
    """Parse every telemetry sample from the JSONL (best-effort, never raises).

    Skips blank and corrupt lines and non-dict objects. Returns [] when the file is
    absent or unreadable so calibration degrades to an insufficient-sample report.
    """
    path = quota_telemetry_path(root, policy)
    try:
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    samples: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            samples.append(parsed)
    return samples


def percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolation percentile (``pct`` in 0..100). None for an empty list.

    Matches the common "linear interpolation between closest ranks" method: the
    p50 of a single value is that value, and p95 of a tight cluster sits near the
    top of the observed range rather than overshooting it.
    """
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    clamped = min(100.0, max(0.0, pct))
    rank = (clamped / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


def sample_observed_delta(sample: dict[str, Any]) -> float | None:
    """Observed quota spend (percentage points) attributable to one sample.

    Uses the largest non-negative ``used_percentage`` increase across the windows
    present in both the pre- and post-quota snapshots (the tightest window binds the
    reservation, so the largest window delta is the right per-task cost signal).
    Returns None when either snapshot is unavailable or no window can be matched —
    such a sample carries no usable delta and is excluded from estimates.
    """
    pre = sample.get("pre_quota")
    post = sample.get("post_quota")
    if not isinstance(pre, dict) or not isinstance(post, dict):
        return None
    if not pre.get("available") or not post.get("available"):
        return None
    pre_used: dict[str, float] = {}
    for view in pre.get("windows", []) or []:
        if isinstance(view, dict) and view.get("window") is not None:
            pre_used[str(view.get("window"))] = _as_float(
                view.get("used_percentage"), 0.0
            )
    best: float | None = None
    for view in post.get("windows", []) or []:
        if not isinstance(view, dict):
            continue
        name = view.get("window")
        if name is None or str(name) not in pre_used:
            continue
        delta = _as_float(view.get("used_percentage"), 0.0) - pre_used[str(name)]
        if delta < 0:
            # A window reset between pre and post (used dropped); not a usable
            # per-task delta for that window.
            continue
        if best is None or delta > best:
            best = delta
    return best


def sample_size_key(sample: dict[str, Any]) -> str:
    """Normalize a sample's ``size`` to one of S / M / L / unknown."""
    normalized = str(sample.get("size") or "").strip().lower()
    if normalized in QUOTA_RESERVATION_SIZE_KEYS:
        return normalized.upper()
    return "unknown"


def is_high_confidence_sample(sample: dict[str, Any]) -> bool:
    """True for a single-run, non-partial sample with a usable observed delta.

    These are the only samples calibration trusts for per-task recommendations:
    parallel/wave samples (``confidence: low``) and partial samples have no reliable
    per-task attribution and are excluded by default.
    """
    if sample.get("confidence") == "low":
        return False
    if sample.get("partial"):
        return False
    return sample_observed_delta(sample) is not None


def _round_opt(value: float | None, digits: int = 3) -> float | None:
    """Round a percentile value, passing None through unchanged."""
    return None if value is None else round(value, digits)


def _percentile_block(deltas: list[float]) -> dict[str, Any]:
    """p50/p80/p95 + count/min/max for a list of observed deltas."""
    return {
        "count": len(deltas),
        "p50": _round_opt(percentile(deltas, 50)),
        "p80": _round_opt(percentile(deltas, 80)),
        "p95": _round_opt(percentile(deltas, 95)),
        "min": _round_opt(min(deltas)) if deltas else None,
        "max": _round_opt(max(deltas)) if deltas else None,
    }


def recommend_reservation_percentage(deltas: list[float], floor: float) -> float | None:
    """Conservative reservation: p95 rounded UP to a whole percent, with a floor.

    Returns None when there are no observed deltas. Rounding up (ceil) keeps the
    recommendation a pessimistic upper bound; the floor prevents a near-zero result.
    """
    p95 = percentile(deltas, 95)
    if p95 is None:
        return None
    return float(max(math.ceil(p95), math.ceil(floor)))


def aggregate_quota_calibration(
    root: Path,
    policy: dict[str, Any],
    *,
    include_low_confidence: bool = False,
) -> dict[str, Any]:
    """Build the full calibration view from telemetry (no policy writes).

    Splits samples into high-confidence (single-run, non-partial, with a usable
    delta) and low-confidence (parallel/partial) buckets. By default only the
    high-confidence bucket feeds percentiles and recommendations; low-confidence
    samples are reported in the confidence buckets but excluded from the math.
    """
    samples = read_quota_telemetry_samples(root, policy)
    floor = quota_calibration_floor(policy)
    high: list[dict[str, Any]] = []
    low_confidence = 0
    no_delta = 0
    for sample in samples:
        if is_high_confidence_sample(sample):
            high.append(sample)
        elif sample.get("confidence") == "low" or sample.get("partial"):
            low_confidence += 1
        else:
            # Single-run but no matchable pre/post window delta.
            no_delta += 1
    used_samples = list(high)
    if include_low_confidence:
        # Opt-in: also fold low-confidence samples that still expose a delta. This is
        # documented as less trustworthy and never the default.
        for sample in samples:
            if sample in high:
                continue
            if sample_observed_delta(sample) is not None:
                used_samples.append(sample)

    by_size_deltas: dict[str, list[float]] = {
        key: [] for key, _ in QUOTA_CALIBRATION_SIZE_ORDER
    }
    by_model_deltas: dict[str, list[float]] = {}
    for sample in used_samples:
        delta = sample_observed_delta(sample)
        if delta is None:
            continue
        by_size_deltas.setdefault(sample_size_key(sample), []).append(delta)
        model_key = "/".join(
            part
            for part in (
                str(sample.get("backend") or "?"),
                str(sample.get("model") or "?"),
            )
        )
        by_model_deltas.setdefault(model_key, []).append(delta)

    reservations = quota_config(policy).get("reservations", {})
    if not isinstance(reservations, dict):
        reservations = {}
    unknown_current = _as_float(reservations.get("unknown_percentage", 5), 5.0)

    by_size: dict[str, Any] = {}
    recommendations: dict[str, Any] = {}
    for label, policy_key in QUOTA_CALIBRATION_SIZE_ORDER:
        deltas = by_size_deltas.get(label, [])
        block = _percentile_block(deltas)
        if label == "unknown":
            current = unknown_current
        else:
            current = _as_float(
                reservations.get(policy_key, unknown_current), unknown_current
            )
        block["current_percentage"] = round(current, 3)
        recommended = recommend_reservation_percentage(deltas, floor)
        block["recommended_percentage"] = recommended
        block["policy_key"] = policy_key
        block["enough_for_recommendation"] = (
            recommended is not None
            and len(deltas) >= QUOTA_CALIBRATION_DRY_RUN_MIN_PER_SIZE
        )
        by_size[label] = block
        if recommended is not None:
            recommendations[policy_key] = recommended

    by_model: dict[str, Any] = {}
    for model_key, deltas in sorted(by_model_deltas.items()):
        by_model[model_key] = _percentile_block(deltas)

    min_samples = quota_calibration_min_samples(policy)
    high_count = len(high)
    return {
        "schema_version": QUOTA_TELEMETRY_SCHEMA,
        "total_samples": len(samples),
        "confidence_buckets": {
            "high_confidence": high_count,
            "low_confidence": low_confidence,
            "single_run_without_delta": no_delta,
        },
        "include_low_confidence": include_low_confidence,
        "used_sample_count": len(used_samples),
        "floor_percentage": round(floor, 3),
        "min_samples_for_apply": min_samples,
        "enough_for_apply": high_count >= min_samples,
        "by_size": by_size,
        "by_model": by_model,
        "recommendations": recommendations,
    }


def quota_calibration_patch(calibration: dict[str, Any]) -> dict[str, Any]:
    """The `[quota.reservations]` changes a recommendation would make.

    Includes every size that has at least one usable observed delta (so a
    recommendation exists) and whose recommended value differs from the current
    value. Empty dict means "no change". The per-size dry-run display floor only
    annotates the report ("low n"); the real apply guard is the total
    high-confidence sample minimum enforced by the caller (``enough_for_apply``).
    """
    patch: dict[str, Any] = {}
    by_size = calibration.get("by_size", {})
    for label, _ in QUOTA_CALIBRATION_SIZE_ORDER:
        block = by_size.get(label, {})
        recommended = block.get("recommended_percentage")
        current = block.get("current_percentage")
        policy_key = block.get("policy_key")
        if recommended is None or policy_key is None:
            continue
        if current is None or float(recommended) != float(current):
            patch[str(policy_key)] = {
                "from": current,
                "to": recommended,
                "size": label,
            }
    return patch


def apply_quota_calibration_patch(
    policy_path: Path, patch: dict[str, Any]
) -> tuple[Path, str | None]:
    """Apply a calibration patch to ``[quota.reservations]`` with a policy backup.

    Same backup-then-edit path `policy sync` uses: copies the policy to
    ``<name>.toml.bak`` (preserving mode), updates only the reservation keys in the
    patch, and writes them into the existing text with edit_policy_text, so comments
    and layout stay. Returns the backup path and, when the edit fell
    back to the full render, the reason. The caller is responsible for guarding the
    sample-count minimum.
    """
    text = policy_path.read_text(encoding="utf-8")
    local = loads_policy_toml(text)
    policy = copy.deepcopy(local)
    quota_section = policy.setdefault("quota", {})
    if not isinstance(quota_section, dict):
        quota_section = {}
        policy["quota"] = quota_section
    reservations = quota_section.setdefault("reservations", {})
    if not isinstance(reservations, dict):
        reservations = {}
        quota_section["reservations"] = reservations
    for policy_key, change in patch.items():
        to_value = change.get("to") if isinstance(change, dict) else change
        # Reservation percentages render cleanest as ints when whole.
        if isinstance(to_value, float) and to_value.is_integer():
            to_value = int(to_value)
        reservations[policy_key] = to_value
    backup_path = policy_path.with_suffix(".toml.bak")
    shutil.copy2(policy_path, backup_path)
    profile = str(local.get("verify", {}).get("default_profile", "none"))
    edited, fallback_reason = edit_policy_text(
        text, local, policy, default_policy(default_verify_profile=profile)
    )
    policy_path.write_text(edited, encoding="utf-8")
    return backup_path, fallback_reason


# --- end Claude quota source layer ----------------------------------------------


def quota_fallback_candidates(
    task: Task,
    policy: dict[str, Any],
    state: dict[str, Any],
    root: Path,
    *,
    confirm_risk: bool = False,
) -> list[str]:
    """Non-Claude backends eligible to run a Claude-quota-blocked task.

    Mirrors the limit-fallback rules in choose_backend_order (enabled, available,
    not disabled, not in cooldown, and honoring ask_before_weaker_fallback_for_risky_tasks)
    so quota-blocking reuses the same fallback policy as a rate limit — it does not
    invent a new fallback path. Quota-gated backends are excluded by definition.

    A wave-level backend pin suppresses quota fallback too: the
    pin's contract is "no substitution", so a quota-blocked pinned backend waits
    or fails instead of handing the task to another vendor.
    """
    if state.get("pinned_backend"):
        return []
    routing = policy.get("routing", {})
    backends = policy.get("backends", {})
    disabled = set(routing.get("disabled_backends", []))
    cooldowns = state.get("backend_cooldowns", {})
    candidates: list[str] = []
    for name in routing.get("limit_fallback_order", ["cursor_auto"]):
        if is_quota_gated_backend(name, policy):
            continue
        if name in disabled or not backends.get(name, {}).get("enabled", False):
            continue
        if name in cooldowns and backend_cooled_down(name, cooldowns[name]):
            continue
        if not backend_available(backends.get(name, {})):
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
        candidates.append(name)
    return candidates


def quota_statusline_global_command() -> str:
    # The dispatcher should be installed on PATH, for example ~/.local/bin.
    return "ai-task-quota-statusline-dispatch.py"


def quota_statusline_global_settings_snippet() -> str:
    command = quota_statusline_global_command()
    return json.dumps(
        {
            "statusLine": {
                "type": "command",
                "command": command,
            }
        },
        ensure_ascii=False,
        indent=2,
    )


def write_quota_refresh_state(root: Path, result: dict[str, Any]) -> None:
    try:
        _write_json_atomic(quota_refresh_state_path(root), result)
    except OSError:
        pass


CLAUDE_OAUTH_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_OAUTH_BETA_HEADER = "oauth-2025-04-20"
CLAUDE_OAUTH_TOKEN_ENV_KEYS = (
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_OAUTH_TOKEN",
)
CLAUDE_CREDENTIAL_PATHS = (
    Path("~/.claude/.credentials.json"),
    Path("~/.config/claude/.credentials.json"),
)
CLAUDE_KEYCHAIN_SERVICES = (
    "Claude Code-credentials",
    "Claude Code",
)
# ``AI_TASK_CLAUDE_OAUTH_USAGE=0`` turns the built-in claude_oauth
# quota source off: ai-task reads no stored Claude token and never calls the
# usage endpoint. The test suite sets it, so a test owns its quota snapshot and
# never sees the developer's live usage (at 95% and above every Claude dispatch
# of a test was refused as at_or_over_stop_line).
CLAUDE_OAUTH_USAGE_ENV = "AI_TASK_CLAUDE_OAUTH_USAGE"


def claude_oauth_usage_disabled() -> bool:
    return os.environ.get(CLAUDE_OAUTH_USAGE_ENV, "").strip() == "0"


def _extract_oauth_token(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("sk-ant-oat", "sk-ant-oauth")):
            return text
        return None
    if isinstance(value, dict):
        preferred = (
            "accessToken",
            "access_token",
            "oauthAccessToken",
            "oauth_access_token",
        )
        for key in preferred:
            token = _extract_oauth_token(value.get(key))
            if token:
                return token
        for key, nested in value.items():
            if "token" in str(key).lower():
                token = _extract_oauth_token(nested)
                if token:
                    return token
        for nested in value.values():
            token = _extract_oauth_token(nested)
            if token:
                return token
    if isinstance(value, list):
        for item in value:
            token = _extract_oauth_token(item)
            if token:
                return token
    return None


def _extract_oauth_token_from_text(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith(("sk-ant-oat", "sk-ant-oauth")):
        return stripped
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return _extract_oauth_token(parsed)


def load_claude_oauth_token() -> str | None:
    """Best-effort Claude Code OAuth token lookup without logging secret values."""
    if claude_oauth_usage_disabled():
        return None
    for key in CLAUDE_OAUTH_TOKEN_ENV_KEYS:
        token = _extract_oauth_token(os.environ.get(key))
        if token:
            return token
    for raw_path in CLAUDE_CREDENTIAL_PATHS:
        path = raw_path.expanduser()
        if not path.exists():
            continue
        try:
            token = _extract_oauth_token_from_text(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if token:
            return token
    if sys.platform == "darwin" and shutil.which("security") is not None:
        for service in CLAUDE_KEYCHAIN_SERVICES:
            try:
                completed = subprocess.run(
                    ["security", "find-generic-password", "-s", service, "-w"],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=3,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if completed.returncode != 0:
                continue
            token = _extract_oauth_token_from_text(completed.stdout)
            if token:
                return token
    return None


# Actionable reason for HTTP 401/403 from the OAuth usage endpoint: the cached
# token in credentials/keychain has expired and only the Claude Code app itself
# can mint a fresh one — no headless source can recover.
CLAUDE_OAUTH_UNAUTHORIZED_REASON = (
    "OAuth token expired/unauthorized — open Claude Code to refresh it"
)


class ClaudeOAuthUnauthorizedError(RuntimeError):
    """Usage endpoint rejected the cached OAuth token (HTTP 401/403)."""


def fetch_claude_oauth_usage_json(policy: dict[str, Any]) -> str:
    token = load_claude_oauth_token()
    if not token:
        if claude_oauth_usage_disabled():
            raise RuntimeError(f"Claude OAuth usage source off ({CLAUDE_OAUTH_USAGE_ENV}=0)")
        raise RuntimeError("Claude Code OAuth token not found")
    request = urlrequest.Request(
        CLAUDE_OAUTH_USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "anthropic-beta": CLAUDE_OAUTH_BETA_HEADER,
        },
        method="GET",
    )
    try:
        # Semgrep dynamic-urllib is a false positive: CLAUDE_OAUTH_USAGE_URL is a literal https constant.
        # nosemgrep: dynamic-urllib-use-detected
        with urlrequest.urlopen(  # noqa: S310 - literal https URL, user-authenticated Anthropic endpoint.
            request,
            timeout=quota_refresh_timeout_seconds(policy),
        ) as response:
            return response.read().decode("utf-8")
    except urlerror.HTTPError as exc:
        if exc.code in (401, 403):
            raise ClaudeOAuthUnauthorizedError(
                f"Claude OAuth usage endpoint returned HTTP {exc.code}: "
                f"{CLAUDE_OAUTH_UNAUTHORIZED_REASON}"
            ) from exc
        raise RuntimeError(
            f"Claude OAuth usage endpoint returned HTTP {exc.code}"
        ) from exc
    except urlerror.URLError as exc:
        reason = getattr(exc, "reason", exc.__class__.__name__)
        raise RuntimeError(
            f"Claude OAuth usage endpoint unreachable: {reason}"
        ) from exc


def run_quota_refresh_source(
    root: Path, policy: dict[str, Any], source: str
) -> dict[str, Any]:
    command = quota_refresh_source_command(source)
    result: dict[str, Any] = {
        "source": source,
        "command": command or [],
        "ok": False,
        "reason": None,
    }
    if not command:
        result["reason"] = "empty refresh command"
        return result
    if command[0] == "builtin:claude-oauth-usage":
        try:
            raw_output = fetch_claude_oauth_usage_json(policy)
            snapshot, warnings = parse_quota_refresh_output(raw_output)
        except ClaudeOAuthUnauthorizedError as exc:
            # Token stale (HTTP 401/403): only the Claude Code app can refresh
            # it. Flag structurally so doctor/probe need no string matching,
            # and let quota_refresh fall through to the next source.
            result["reason"] = str(exc)
            result["unauthorized"] = True
            return result
        except (RuntimeError, json.JSONDecodeError, ValueError) as exc:
            result["reason"] = str(exc)
            return result
        _write_json_atomic(quota_snapshot_path(root, policy), snapshot)
        result["ok"] = True
        result["snapshot_path"] = str(quota_snapshot_path(root, policy))
        result["warnings"] = warnings
        return result
    if shutil.which(command[0]) is None:
        result["reason"] = f"command not found: {command[0]}"
        return result
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=quota_refresh_timeout_seconds(policy),
        )
    except subprocess.TimeoutExpired:
        result["reason"] = f"command timed out: {' '.join(command)}"
        return result
    except OSError as exc:
        result["reason"] = f"command failed to start: {exc.__class__.__name__}"
        return result
    if completed.returncode != 0:
        stderr = completed.stderr.strip().splitlines()
        detail = stderr[0] if stderr else f"exit {completed.returncode}"
        result["reason"] = f"command exited {completed.returncode}: {detail}"
        return result
    if not completed.stdout.strip():
        result["reason"] = "command produced no JSON output"
        return result
    try:
        snapshot, warnings = parse_quota_refresh_output(completed.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        result["reason"] = f"unparseable live-source output: {exc}"
        return result
    _write_json_atomic(quota_snapshot_path(root, policy), snapshot)
    result["ok"] = True
    result["snapshot_path"] = str(quota_snapshot_path(root, policy))
    result["warnings"] = warnings
    return result


def quota_refresh(
    root: Path, policy: dict[str, Any], *, force: bool = False
) -> dict[str, Any]:
    """Try to refresh the quota snapshot from a headless live source.

    `quota status` stays read-only; this explicit path may shell out to configured
    live-source commands and atomically update `.ai-task/quota-snapshot.json`.
    """
    result: dict[str, Any] = {
        "refreshed": False,
        "available": False,
        "source": None,
        "snapshot_path": str(quota_snapshot_path(root, policy)),
        "attempts": [],
        "reason": None,
        "at": now(),
    }
    if not quota_enabled(policy):
        result["reason"] = "quota supervision disabled in policy"
        write_quota_refresh_state(root, result)
        return result
    if not quota_refresh_enabled(policy):
        result["reason"] = "headless quota refresh disabled in policy"
        write_quota_refresh_state(root, result)
        return result
    current = quota_status(root, policy)
    if current.get("available") and not force:
        result["available"] = True
        result["reason"] = "snapshot already fresh"
        result["status"] = compact_quota_status(current)
        write_quota_refresh_state(root, result)
        return result
    sources = quota_refresh_sources(policy)
    if not sources:
        result["reason"] = "no quota refresh sources configured"
        write_quota_refresh_state(root, result)
        return result
    for source in sources:
        attempt = run_quota_refresh_source(root, policy, source)
        result["attempts"].append(attempt)
        if not attempt.get("ok"):
            continue
        status = quota_status(root, policy)
        result["refreshed"] = True
        result["available"] = bool(status.get("available"))
        result["source"] = source
        result["status"] = compact_quota_status(status)
        result["reason"] = None if status.get("available") else status.get("reason")
        write_quota_refresh_state(root, result)
        return result
    reasons = [
        str(attempt.get("reason"))
        for attempt in result["attempts"]
        if attempt.get("reason")
    ]
    result["reason"] = "headless quota refresh unavailable" + (
        f": {'; '.join(reasons)}" if reasons else ""
    )
    if any(attempt.get("unauthorized") for attempt in result["attempts"]):
        result["unauthorized"] = True
    write_quota_refresh_state(root, result)
    return result


def try_acquire_quota_reservation(
    root: Path,
    policy: dict[str, Any],
    task: Task,
    run_id: str,
    backend: str,
) -> dict[str, Any]:
    """Atomically reserve quota for a Claude-backed run under the state lock.

    Re-reads the latest persisted reservations inside the lock, recomputes the
    dual-window budget, and only writes the reservation when it fits — so two
    concurrent `ai-task run` processes cannot both consume the same remaining
    budget. Returns a result dict with reserved/required/available/blocked_reason.

    When quota is disabled or no fresh source exists this is inert: it reserves
    nothing and reports ``reserved=False`` with ``available=None`` so the caller
    keeps the unchanged limit/cooldown dispatch path.
    """
    required = quota_reservation_percentage(policy, task.size)
    result: dict[str, Any] = {
        "reserved": False,
        "required": round(required, 3),
        "available": None,
        "blocked_reason": None,
        "backend": backend,
    }
    if not quota_enabled(policy) or not is_quota_gated_backend(backend, policy):
        return result
    status = quota_status(root, policy)
    if not status.get("available"):
        # Inert without a fresh source — admission control does not block dispatch.
        return result
    try:
        with _state_lock(root):
            latest = _read_state_unlocked(root)
            available = quota_available_budget(status, latest)
            result["available"] = None if available is None else round(available, 3)
            if available is None or required > available:
                if status.get("at_or_over_stop"):
                    result["blocked_reason"] = "at_or_over_stop_line"
                else:
                    result["blocked_reason"] = "insufficient_budget"
                return result
            latest.setdefault("quota_reservations", {})[run_id] = {
                "run_id": run_id,
                "task_id": task.id,
                "size": task.size,
                "backend": backend,
                "percentage": round(required, 3),
                "created_at": now(),
            }
            latest["updated_at"] = now()
            _write_json_atomic(state_path(root), latest)
            result["reserved"] = True
            return result
    except StateLockTimeoutError as exc:
        die(str(exc))
    return result


# ---------------------------------------------------------------------------
# Headless Claude login expiry
# ---------------------------------------------------------------------------
#
# Claude Code 2.1.318 (2026-11-03) reports when a stored claude.ai sign-in
# ends: ``loginExpiresAt`` in ``claude auth status --json`` and
# ``credential_expires_at`` in the ``claude -p --output-format json`` result.
# A stale headless login is a known incident (``claude -p`` answers
# "account on hold" while the interactive session still works), so `quota
# doctor` and `quota probe` print the date and warn below
# ``[quota] login_expiry_warn_days``. Older Claude Code has no such field: the
# check reports CLAUDE_LOGIN_EXPIRY_UNKNOWN_OLD_CLI instead of failing.

CLAUDE_LOGIN_EXPIRY_MIN_VERSION: tuple[int, int, int] = (2, 1, 318)
CLAUDE_LOGIN_EXPIRY_UNKNOWN_OLD_CLI = "expiry unknown, Claude Code < 2.1.318"
CLAUDE_LOGIN_CHECK_ENV = "AI_TASK_CLAUDE_LOGIN_CHECK"
DEFAULT_LOGIN_EXPIRY_WARN_DAYS = 14.0
_CLAUDE_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def quota_login_expiry_warn_days(policy: dict[str, Any]) -> float:
    """Days before the sign-in ends at which doctor and probe start warning."""
    return max(
        0.0,
        _as_float(
            quota_config(policy).get(
                "login_expiry_warn_days", DEFAULT_LOGIN_EXPIRY_WARN_DAYS
            ),
            DEFAULT_LOGIN_EXPIRY_WARN_DAYS,
        ),
    )


def parse_claude_cli_version(text: str | None) -> tuple[int, int, int] | None:
    """``2.1.322 (Claude Code)`` -> (2, 1, 322); None when no version is found."""
    match = _CLAUDE_VERSION_RE.search(text or "")
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def parse_claude_login_payload(text: str | None) -> dict[str, Any]:
    """Read the sign-in fields from either Claude Code JSON output.

    Accepts ``claude auth status --json`` (``loggedIn``, ``loginExpiresAt``)
    and the ``claude -p --output-format json`` result (``credential_expires_at``;
    a not-logged-in run has ``is_error`` and a "Not logged in" result).
    ``field_present`` tells a CLI that knows the field but has no date (null)
    from a CLI that predates it.
    """
    out: dict[str, Any] = {
        "source": None,
        "logged_in": None,
        "expires_at": None,
        "field_present": False,
    }
    try:
        data = json.loads(text or "")
    except json.JSONDecodeError:
        return out
    if not isinstance(data, dict):
        return out
    if "loggedIn" in data or "loginExpiresAt" in data:
        out["source"] = "auth_status"
        if isinstance(data.get("loggedIn"), bool):
            out["logged_in"] = data["loggedIn"]
        out["field_present"] = "loginExpiresAt" in data
        value = data.get("loginExpiresAt")
    elif data.get("type") == "result":
        out["source"] = "print_result"
        result_text = str(data.get("result") or "")
        if data.get("is_error") and "not logged in" in result_text.lower():
            out["logged_in"] = False
        out["field_present"] = "credential_expires_at" in data
        value = data.get("credential_expires_at")
    else:
        return out
    if isinstance(value, str) and value.strip():
        out["expires_at"] = value.strip()
    return out


def assess_claude_login_expiry(
    parsed: dict[str, Any],
    *,
    version: tuple[int, int, int] | None,
    warn_days: float,
    now_dt: dt.datetime | None = None,
) -> dict[str, Any]:
    """Turn parsed sign-in fields into the report doctor and probe print.

    ``ok`` is False only when the operator has to act: not logged in, already
    expired, or fewer than ``warn_days`` left. An unknown expiry (old CLI, API
    key auth, unreadable output) is informational and stays ``ok``.
    """
    report: dict[str, Any] = {
        "known": False,
        "ok": True,
        "warn": False,
        "logged_in": parsed.get("logged_in"),
        "expires_at": None,
        "days_left": None,
        "threshold_days": warn_days,
        "cli_version": ".".join(str(part) for part in version) if version else None,
        "source": parsed.get("source"),
        "reason": None,
    }
    if parsed.get("logged_in") is False:
        report.update(
            ok=False,
            warn=True,
            reason=(
                "claude is not logged in on this host: headless runs here stop "
                "with 'Not logged in'; run `claude auth login` as the user the "
                "workers run as"
            ),
        )
        return report
    expires_raw = parsed.get("expires_at")
    if not expires_raw:
        old_cli = (version is not None and version < CLAUDE_LOGIN_EXPIRY_MIN_VERSION) or (
            parsed.get("source") is not None and not parsed.get("field_present")
        )
        if old_cli:
            reason = CLAUDE_LOGIN_EXPIRY_UNKNOWN_OLD_CLI
            if report["cli_version"]:
                reason += f" (found {report['cli_version']})"
        elif parsed.get("source") is None:
            reason = "expiry unknown: claude printed no readable sign-in status"
        else:
            reason = (
                "expiry unknown: no stored claude.ai sign-in with an end date "
                "(API key or another auth method)"
            )
        report["reason"] = reason
        return report
    expires = parse_iso8601(expires_raw)
    if expires is None:
        report["reason"] = f"expiry unknown: unreadable date {expires_raw!r}"
        return report
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=dt.timezone.utc)
    current = now_dt or dt.datetime.now(dt.timezone.utc)
    days_left = (expires - current).total_seconds() / 86400.0
    report["known"] = True
    report["expires_at"] = expires.astimezone(dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    report["days_left"] = round(days_left, 1)
    if days_left <= 0:
        report.update(
            ok=False,
            warn=True,
            reason=(
                "claude.ai sign-in has expired: headless runs on this host fail "
                "until `claude auth login`"
            ),
        )
    elif days_left < warn_days:
        report.update(
            ok=False,
            warn=True,
            reason=(
                f"claude.ai sign-in ends in {days_left:.1f} days, below the "
                f"{warn_days:g}-day threshold: run `claude auth login` on this "
                "host before it lapses"
            ),
        )
    return report


def _claude_login_command(policy: dict[str, Any]) -> tuple[str, dict[str, str]]:
    backend = policy.get("backends", {}).get("claude", {})
    if not isinstance(backend, dict):
        backend = {}
    command = str(backend.get("command") or "claude")
    extra = backend.get("env", {})
    env = dict(os.environ)
    if isinstance(extra, dict):
        env.update({str(key): str(value) for key, value in extra.items()})
    return command, env


def claude_login_expiry(policy: dict[str, Any]) -> dict[str, Any]:
    """Ask the local ``claude`` when its stored sign-in ends (read-only).

    Runs ``claude --version`` and, on 2.1.318 or newer, ``claude auth status
    --json`` with the claude backend's command and env, so a worker's
    CLAUDE_CONFIG_DIR is honored. Never raises: a missing binary, an old CLI
    or a timeout come back as an unknown expiry with a reason.
    ``AI_TASK_CLAUDE_LOGIN_CHECK=0`` skips the check (the test suite sets it so
    tests never touch the developer's real login).
    """
    warn_days = quota_login_expiry_warn_days(policy)
    if os.environ.get(CLAUDE_LOGIN_CHECK_ENV, "").strip() == "0":
        report = assess_claude_login_expiry({}, version=None, warn_days=warn_days)
        report["reason"] = f"login check skipped ({CLAUDE_LOGIN_CHECK_ENV}=0)"
        return report
    command, env = _claude_login_command(policy)
    timeout = quota_refresh_timeout_seconds(policy)
    if shutil.which(command, path=env.get("PATH")) is None:
        report = assess_claude_login_expiry({}, version=None, warn_days=warn_days)
        report["reason"] = f"expiry unknown: `{command}` not found on PATH"
        return report

    def _run(args: list[str]) -> str | None:
        try:
            proc = subprocess.run(
                [command, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        # `claude auth status` exits 1 when not logged in but still prints JSON.
        return proc.stdout

    version = parse_claude_cli_version(_run(["--version"]))
    if version is not None and version < CLAUDE_LOGIN_EXPIRY_MIN_VERSION:
        return assess_claude_login_expiry({}, version=version, warn_days=warn_days)
    parsed = parse_claude_login_payload(_run(["auth", "status", "--json"]))
    return assess_claude_login_expiry(parsed, version=version, warn_days=warn_days)


def claude_login_expiry_line(report: dict[str, Any]) -> str:
    """One human line for doctor and probe output."""
    if report.get("known") and report.get("ok"):
        return (
            f"claude.ai sign-in ends {report.get('expires_at')} "
            f"({report.get('days_left')} days left; warning starts at "
            f"{report.get('threshold_days'):g} days)"
        )
    if report.get("known"):
        return f"{report.get('reason')} (ends {report.get('expires_at')})"
    return str(report.get("reason") or "expiry unknown")
