#!/usr/bin/env python3
"""Claude Code statusLine helper for ai-task quota snapshots.

Claude Code calls the configured statusLine command with a JSON payload on stdin.
This helper extracts rolling quota windows from that payload and atomically writes
the repo-local `.ai-task/quota-snapshot.json` file consumed by `ai-task quota`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

APP_DIR = ".ai-task"
WINDOW_ALIASES: dict[str, str] = {
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
USED_KEYS = (
    "used_percentage",
    "used_pct",
    "percent_used",
    "used",
    "percentage",
    "percent",
)
USED_FRACTION_KEYS = ("used_fraction", "fraction_used")
REMAINING_KEYS = ("remaining_percentage", "remaining_pct", "remaining")
REMAINING_FRACTION_KEYS = ("remaining_fraction", "fraction_remaining")
RESET_KEYS = ("resets_at", "reset_at", "resets", "reset_time")
CAPTURED_KEYS = ("captured_at", "as_of", "timestamp", "current_time")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def normalize_window_name(raw: Any) -> str | None:
    return WINDOW_ALIASES.get(str(raw).strip().lower())


def as_percentage(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, number))


def as_fraction_percentage(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, number * 100.0))


def first_value(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def repo_root(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / APP_DIR).exists() or (candidate / ".git").exists():
            return candidate
    return current


def candidate_windows(data: dict[str, Any]) -> dict[str, Any]:
    for key in ("rate_limits", "rateLimits", "quota", "windows"):
        value = data.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            return {
                str(item.get("name") or item.get("window") or index): item
                for index, item in enumerate(value)
                if isinstance(item, dict)
            }
    return {
        key: value
        for key, value in data.items()
        if normalize_window_name(key) is not None and isinstance(value, dict)
    }


def normalize_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    captured_at = first_value(data, CAPTURED_KEYS) or now_iso()
    windows: dict[str, Any] = {}
    for raw_name, raw_entry in candidate_windows(data).items():
        canonical = normalize_window_name(raw_name)
        if canonical is None and isinstance(raw_entry, dict):
            canonical = normalize_window_name(raw_entry.get("name") or raw_entry.get("window"))
        if canonical is None or not isinstance(raw_entry, dict):
            continue
        used = as_percentage(first_value(raw_entry, USED_KEYS))
        if used is None:
            used = as_fraction_percentage(first_value(raw_entry, USED_FRACTION_KEYS))
        if used is None:
            remaining = as_percentage(first_value(raw_entry, REMAINING_KEYS))
            if remaining is None:
                remaining = as_fraction_percentage(
                    first_value(raw_entry, REMAINING_FRACTION_KEYS)
                )
            if remaining is not None:
                used = max(0.0, min(100.0, 100.0 - remaining))
        if used is None:
            continue
        reset = first_value(raw_entry, RESET_KEYS)
        window_captured = first_value(raw_entry, CAPTURED_KEYS) or captured_at
        windows[canonical] = {
            "used_percentage": used,
            "captured_at": str(window_captured),
        }
        if reset is not None:
            windows[canonical]["resets_at"] = str(reset)
    if not windows:
        raise ValueError("no quota windows found in statusLine input")
    return {"captured_at": str(captured_at), "windows": windows}


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        tmp_name = handle.name
    os.replace(tmp_name, path)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write .ai-task/quota-snapshot.json from Claude Code statusLine JSON"
    )
    parser.add_argument("--repo", help="Repository root. Defaults to cwd/git/.ai-task root.")
    parser.add_argument(
        "--output",
        help="Snapshot path. Defaults to <repo>/.ai-task/quota-snapshot.json.",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print normalized snapshot JSON instead of writing it.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        raw = json.loads(sys.stdin.read() or "{}")
        if not isinstance(raw, dict):
            # Raising into this function's own except is the design: the whole
            # body is guarded so a bad payload prints one line and exits 1
            # instead of breaking the status line.
            raise TypeError("statusLine input must be a JSON object")  # noqa: TRY301
        snapshot = normalize_snapshot(raw)
        if args.print:
            print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        explicit_repo = args.repo or os.environ.get("AI_TASK_REPO")
        root = (
            Path(explicit_repo).expanduser().resolve()
            if explicit_repo
            else repo_root(Path.cwd())
        )
        output = (
            Path(args.output).expanduser()
            if args.output
            else root / APP_DIR / "quota-snapshot.json"
        )
        if not output.is_absolute():
            output = root / output
        write_json_atomic(output, snapshot)
    except Exception as exc:
        print(f"ai-task quota statusLine helper: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
