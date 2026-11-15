"""Telegram finalize notifications for the ai-task CLI.

The per-task Stop hook (hooks/telegram-notify.py) fires from INSIDE the
headless ``claude -p`` when the model stops - BEFORE verify and verdict are
computed - so it can only report "implementation done". ai-task IS the
finalizer, so it sends the authoritative OUTCOME ping (verify result, verdict,
changed files) when a run's verdict is recorded, reusing the same Claude Code
Telegram channel credentials.

Everything here is best-effort and config-gated: a missing channel .env, a
urllib error, or ``[notify] enabled = false`` silently no-ops - a notification
must never affect a run. ``AI_TASK_NOTIFY_DISABLED=1`` short-circuits the
sender outright; the test harness sets it (tests/__init__.py and
tests/conftest.py) so a suite run never POSTs.

Imports ``policy``, ``state`` and ``runs`` (git helpers for the committed-diff
fallback). ``backend_env`` deliberately does NOT live here even though it
consults ``_notify_suppress_implement_for_root``: notify already imports runs,
so hosting backend_env would close a cycle. It lands in lifecycle.py.
Nothing in the package imports this module except the entrypoint.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib import request as urlrequest

from ai_task._shared import app_path, now
from ai_task.policy import load_toml, read_config
from ai_task.runs import cleanup_branch_ahead_count, git_text

_TELEGRAM_DIR = Path.home() / ".claude" / "channels" / "telegram"


def _notify_config(policy: dict[str, Any]) -> dict[str, Any]:
    section = policy.get("notify", {})
    return section if isinstance(section, dict) else {}


def _notify_runs_enabled(policy: dict[str, Any]) -> bool:
    return bool(_notify_config(policy).get("enabled", True))


def _read_policy_safe(root: Path) -> dict[str, Any]:
    """Policy dict for `root`, or {} — NEVER dies.

    `read_policy`/`read_config`/`die` raise `SystemExit` (which an `except
    Exception` does NOT catch) when the repo is not an initialized ai-task repo.
    The notify path runs from `backend_env`, whose cwd may be any repo (e.g. the
    profile repo with no `.ai-task`), so it must read defensively. We resolve the
    configured policy name via `read_config(root)["default_policy"]`
    and load `policies/<name>.toml` so an operator with a non-`default` policy
    still gets the right [notify] section; `load_toml` returns {} for a missing
    file. Catch BOTH `Exception` AND `SystemExit` so a non-initialized repo can
    never abort the caller.
    """
    try:
        name = str(read_config(root).get("default_policy", "default")) or "default"
        pol = load_toml(app_path(root) / "policies" / f"{name}.toml")
        return pol if isinstance(pol, dict) else {}
    except (Exception, SystemExit):
        return {}


def _notify_policy_for_root(root: Path) -> dict[str, Any]:
    # Read fresh each call (backend_env runs only a handful of times per wave —
    # the file read is cheap and avoids any shared-mutable cache state).
    return _notify_config(_read_policy_safe(root))


def _notify_suppress_implement_for_root(root: Path) -> bool:
    cfg = _notify_policy_for_root(root)
    # Suppress the Stop-hook implement ping only when notifications are on AND the
    # operator turned the implement ping off (default: keep both pings).
    return bool(cfg.get("enabled", True)) and not bool(cfg.get("implement_ping", True))


def _telegram_send(text: str) -> bool:
    """Best-effort Telegram push reusing the Claude Code channel creds.

    Returns True if a send was attempted, False if creds are absent/unreadable.
    Never raises — a notification must never break a run.
    """
    # Hard kill-switch (set by the test harness): the CLI tests run real
    # `verdict` commands on temp repos, which would otherwise POST fixture pings
    # to the operator's real channel.
    if os.environ.get("AI_TASK_NOTIFY_DISABLED"):
        return False
    try:
        env_file = _TELEGRAM_DIR / ".env"
        access_file = _TELEGRAM_DIR / "access.json"
        token = None
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip()
        chat_id = None
        if access_file.is_file():
            allow = json.loads(access_file.read_text(encoding="utf-8")).get(
                "allowFrom", []
            )
            if allow:
                chat_id = str(allow[0])
        if not token or not chat_id:
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps(
            {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        ).encode()
        req = urlrequest.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        # Bounded timeout: this send is synchronous in verdict_cmd, so a slow
        # Telegram endpoint must not stall the finalize step for long.
        # Semgrep dynamic-urllib is a false positive: the URL is built from the literal https base and nothing else, file:// cannot get here.
        # nosemgrep: dynamic-urllib-use-detected
        urlrequest.urlopen(req, timeout=5)  # noqa: S310 - literal https Telegram API URL.
        return True
    except Exception:
        return False


def _notify_wave(state: dict[str, Any], task_id: str = "") -> tuple[int, int] | None:
    batch = state.get("last_batch")
    if not isinstance(batch, list) or not batch:
        return None
    # Only report wave progress when THIS task belongs to the current batch —
    # otherwise `last_batch` is from an earlier wave and the counts are stale
    # (e.g. would read "N/N готово · 0 в работе" for an unrelated run).
    if task_id and task_id not in batch:
        return None
    leases = state.get("leases")
    leased = set(leases) if isinstance(leases, dict) else set()
    in_flight = sum(1 for t in batch if t in leased)
    return in_flight, len(batch)


def _notify_quota(root: Path) -> str | None:
    snap = root / ".ai-task" / "quota-snapshot.json"
    if not snap.is_file():
        return None
    try:
        data = json.loads(snap.read_text(encoding="utf-8"))
        fh = data.get("windows", {}).get("five_hour", {})
        used = fh.get("used_percentage")
        if used is None:
            return None
        cap = fh.get("captured_at") or data.get("captured_at")
        tag = ""
        if cap:
            try:
                ts = dt.datetime.fromisoformat(str(cap).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=dt.timezone.utc)
                tag = f" (обн. {ts.astimezone().strftime('%H:%M')})"
            except Exception:
                tag = ""
        return f"5h: {100 - float(used):.0f}% ост.{tag}"
    except Exception:
        return None


def _diffstat_names(text: str) -> list[str]:
    names: list[str] = []
    for line in text.splitlines():
        m = re.match(r"\s*([^\s|]+)\s+\|\s+\d+", line)
        if m:
            names.append(m.group(1))
    return names


def _notify_committed_diff_names(root: Path | None, run_record: dict[str, Any]) -> list[str]:
    """Changed files from the run's committed diff (`<base>..<branch>`), best-effort.

    `uncommitted_changes` is empty at verdict time for a run that already
    committed, so derive the file list from the run's git commit
    range instead. The worktree branch (`ai-task/<TASK>-<hash>`) and its base
    branch are both visible from `root` (worktrees share the object store), so a
    single `git -C <root> diff --stat <base>..<branch>` yields the run's changed
    files. Any git error → [] (no line).
    """
    if root is None:
        return []
    try:
        _count, base, branch, err = cleanup_branch_ahead_count(root, run_record)
        if err or not base or not branch:
            return []
        code, output = git_text(root, "diff", "--stat", f"{base}..{branch}")
        if code != 0:
            return []
        return _diffstat_names(output)
    except Exception:
        return []


def _notify_changed_files(run_record: dict[str, Any], root: Path | None = None) -> str:
    names = _diffstat_names(str(run_record.get("uncommitted_changes") or ""))
    if not names:
        # Fall back to the run's committed diff: a run that already committed has
        # an empty `uncommitted_changes` at verdict time.
        names = _notify_committed_diff_names(root, run_record)
    if not names:
        return ""
    shown = ", ".join(names[:3])
    if len(names) > 3:
        shown += f" (+{len(names) - 3})"
    return shown


def _notify_outcome_label(verdict: str, status: str) -> tuple[str, str]:
    if verdict == "approve":
        return "✅", "approved"
    if verdict in {"rework", "split", "escalate"}:
        return "❌", verdict
    if verdict == "defer":
        return "⏸", "defer"
    if status == "backend_unusable":
        # Operator-configuration fault, not a task outcome: neither
        # ❌ (the task did not fail) nor ✅ (nothing shipped).
        return "🔌", "backend unusable — fix credentials"
    if status in {"failed", "needs_recovery", "stopped"}:
        return "❌", status
    return "✅", status or verdict or "готово"


def _notify_outcome_message(
    root: Path, state: dict[str, Any], run_record: dict[str, Any]
) -> str:
    # parse_mode=HTML: every data-derived value must be escaped, or a title
    # containing <, >, or & makes Telegram reject the message (silent no-op).
    task_id_raw = str(run_record.get("task_id") or "")
    project = html.escape(root.name or "?")
    task_id = html.escape(task_id_raw or "?")
    title = str(run_record.get("task_title") or "")
    verdict = str(run_record.get("verdict") or "").strip().lower()
    status = str(run_record.get("status") or "").strip().lower()
    emoji, outcome = _notify_outcome_label(verdict, status)

    parts = [f"{emoji} <b>{project}</b> · {task_id} — {html.escape(outcome)}"]
    if title:
        shown = title[:80] + "…" if len(title) > 80 else title
        parts.append(f"<i>«{html.escape(shown)}»</i>")

    line: list[str] = []
    vstatus = str(run_record.get("verify_status") or "").strip().lower()
    if vstatus:
        vmark = {"passed": "✅", "failed": "❌", "skipped": "—"}.get(
            vstatus, html.escape(vstatus)
        )
        vp = run_record.get("verify_profile")
        line.append(f"verify {vmark}" + (f" {html.escape(str(vp))}" if vp else ""))
    if verdict:
        line.append(f"вердикт: {html.escape(verdict)}")
    if line:
        parts.append(" · ".join(line))

    changed = _notify_changed_files(run_record, root)
    if changed:
        parts.append(f"изменено: {html.escape(changed)}")

    oos = run_record.get("out_of_scope_edits")
    if isinstance(oos, list) and oos:
        parts.append(f"⚠ out-of-scope: {len(oos)} правк(и) вне задачи")

    wave = _notify_wave(state, task_id_raw)
    if wave:
        in_flight, total = wave
        done = max(0, total - in_flight)
        parts.append(f"волна: {done}/{total} готово · {in_flight} в работе")

    quota = _notify_quota(root)
    if quota:
        parts.append(f"◈ {quota}")
    return "\n\n".join(parts)


def notify_run_outcome(
    root: Path, state: dict[str, Any], run_record: dict[str, Any]
) -> None:
    """Send the ai-task finalize outcome ping (best-effort, config-gated).

    Dedupe: a run pings AT MOST ONCE for its outcome. A terminal
    failure (`failed`/`needs_recovery`/`stopped`) pings here from its finalize
    path, and a run that proceeds to a verdict pings here from `verdict_cmd`;
    `run_record["outcome_notified"]` (stamped when a send is attempted) prevents
    the two from double-sending. The caller persists the flag via its own
    `save_state` so a later verdict on the same run sees it. Best-effort
    throughout — a notification must never affect a run.
    """
    try:
        if run_record.get("outcome_notified"):
            return
        if not _notify_runs_enabled(_read_policy_safe(root)):
            return
        # Stamp before sending so a slow/failed POST cannot cause a re-send on a
        # later finalize path for the same run.
        run_record["outcome_notified"] = now()
        _telegram_send(_notify_outcome_message(root, state, run_record))
    except Exception:  # noqa: S110 - outcome notification is best-effort and must not fail finalize.
        pass
