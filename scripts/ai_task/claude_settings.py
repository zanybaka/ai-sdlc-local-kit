"""Canary for the settings JSON of the headless Claude worker.

In print mode Claude Code silently ignores a ``--settings`` file that fails
validation (``claude --help``). If a later Claude Code retypes or renames a key
of ``[backends.claude]`` settings, the whole JSON drops out of every worker run:
auto mode and ``--permission-prompts none`` stay in argv, while the write block,
the Bash sandbox and the cache env go, and runs keep passing.

The canary needs no model call. Two checks:

1. ``claude --settings <file> doctor`` lists invalid settings per file and key
   (checked on 2.1.322). The worker JSON is written to a file whose name the
   canary looks for, so an invalid user or project settings file is not blamed
   on the worker. A control file with ``sandbox.enabled = "yes"`` must be
   flagged in the same way; when it is not, the doctor output changed and the
   canary cannot tell.
2. Every key name of the JSON (outside ``env``, whose names are variables) is
   searched for in the installed Claude Code binary, or in its ``cli.js`` for
   an npm install. Settings validation lets unknown keys through, so a renamed
   key shows up only here: the old name disappears from the binary.

A pass is remembered per Claude Code version and settings hash in
``.ai-task/claude-settings-canary.json``, so ``ai-task run`` pays about two
seconds once per new CLI version, and ``quota doctor`` names the version the
canary last passed on. ``AI_TASK_CLAUDE_SETTINGS_CANARY=0`` skips it (the test
suite sets it so tests never run the real CLI).

What it cannot prove: a key still present in the binary and accepted by the
validator may have lost its effect. The live negative probe
``CanaryWorkerSettingsApplied`` in tests/test_vendor_contract.py covers that
with one cheap model call.
"""

from __future__ import annotations

import hashlib
import json
import mmap
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ai_task._shared import app_path, now
from ai_task.policy import claude_settings_from_argv
from ai_task.quota import parse_claude_cli_version

CLAUDE_SETTINGS_CANARY_ENV = "AI_TASK_CLAUDE_SETTINGS_CANARY"
CLAUDE_SETTINGS_CANARY_STATE_FILE = "claude-settings-canary.json"
CLAUDE_SETTINGS_CANARY_TIMEOUT_SECONDS = 30
# The control the doctor must flag: a boolean key given a string.
CLAUDE_SETTINGS_CANARY_CONTROL: dict[str, Any] = {"sandbox": {"enabled": "yes"}}
# Smaller files are wrappers (a shell or node launcher), not the CLI itself.
_MIN_BINARY_BYTES = 1_000_000


def claude_settings_key_paths(settings: dict[str, Any], prefix: str = "") -> list[str]:
    """Dotted paths of every key, without descending into ``env``."""
    paths: list[str] = []
    for key, value in settings.items():
        path = f"{prefix}{key}"
        paths.append(path)
        if isinstance(value, dict) and not (prefix == "" and key == "env"):
            paths.extend(claude_settings_key_paths(value, f"{path}."))
    return paths


def claude_settings_hash(settings: dict[str, Any]) -> str:
    text = json.dumps(settings, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def parse_doctor_invalid_settings(output: str, file_name: str) -> list[str]:
    """``key: message`` for each invalid-setting line of ``claude doctor`` naming the file."""
    found: list[str] = []
    for line in output.splitlines():
        if file_name not in line:
            continue
        _, _, rest = line.partition(file_name)
        rest = rest.lstrip(" ›>:").strip()
        found.append(rest or line.strip())
    return found


def claude_binary_path(command: str, path_env: str | None) -> Path | None:
    """Real file behind the claude command (npm: cli.js, native: the versioned binary)."""
    found = shutil.which(command, path=path_env)
    if found is None:
        return None
    return Path(os.path.realpath(found))


def missing_key_names(binary: Path, key_paths: list[str]) -> list[str] | None:
    """Key paths whose last name is absent from the binary; None when it cannot be read."""
    try:
        if binary.stat().st_size < _MIN_BINARY_BYTES:
            return None
        with binary.open("rb") as handle, mmap.mmap(
            handle.fileno(), 0, access=mmap.ACCESS_READ
        ) as data:
            return [
                path
                for path in key_paths
                if data.find(path.rsplit(".", 1)[-1].encode("utf-8")) < 0
            ]
    except (OSError, ValueError):
        return None


def canary_state_path(root: Path) -> Path:
    return app_path(root) / CLAUDE_SETTINGS_CANARY_STATE_FILE


def read_canary_state(root: Path) -> dict[str, Any]:
    try:
        data = json.loads(canary_state_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_canary_state(root: Path, state: dict[str, Any]) -> None:
    path = canary_state_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _last_pass_note(last: dict[str, Any]) -> str:
    if not last:
        return "it has not passed on this host yet"
    return f"it last passed on Claude Code {last.get('cli_version')} at {last.get('at')}"


def claude_settings_canary(
    backend: dict[str, Any],
    root: Path,
    *,
    use_cache: bool = True,
    timeout: int = CLAUDE_SETTINGS_CANARY_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Check that the local Claude Code accepts the backend's inline settings JSON.

    ``ok`` is False on a definitive finding (``invalid`` or ``unknown_keys``) and
    when the canary cannot tell (``undetermined``: the doctor flags no control,
    or it fails to run). ``checked`` is False when there is nothing to check or
    the check is skipped. Never raises.
    """
    argv = [str(item) for item in backend.get("args", []) or []]
    argv += [str(item) for item in backend.get("extra_args", []) or []]
    settings = claude_settings_from_argv(argv)
    state = read_canary_state(root)
    last = state.get("last_pass") if isinstance(state.get("last_pass"), dict) else {}
    report: dict[str, Any] = {
        "checked": False,
        "ok": True,
        "cached": False,
        "undetermined": False,
        "cli_version": None,
        "invalid": [],
        "unknown_keys": [],
        "last_passed_version": last.get("cli_version"),
        "last_passed_at": last.get("at"),
        "why": "",
    }
    if not settings:
        report["why"] = "no inline --settings JSON in the claude argv, nothing to check"
        return report
    if os.environ.get(CLAUDE_SETTINGS_CANARY_ENV, "").strip() == "0":
        report["why"] = f"settings canary skipped ({CLAUDE_SETTINGS_CANARY_ENV}=0)"
        return report
    command = str(backend.get("command") or "claude")
    env = dict(os.environ)
    extra_env = backend.get("env", {})
    if isinstance(extra_env, dict):
        env.update({str(key): str(value) for key, value in extra_env.items()})
    binary = claude_binary_path(command, env.get("PATH"))
    if binary is None:
        report["why"] = f"settings canary not run: `{command}` not found on PATH"
        return report

    def _run(args: list[str]) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                [command, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                stdin=subprocess.DEVNULL,
                cwd=scratch,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    digest = claude_settings_hash(settings)
    with tempfile.TemporaryDirectory(prefix="ai-task-settings-canary-") as scratch:
        version_proc = _run(["--version"])
        version = parse_claude_cli_version(version_proc.stdout if version_proc else None)
        found = ".".join(str(part) for part in version) if version else None
        report["cli_version"] = found
        if (
            use_cache
            and found is not None
            and last.get("cli_version") == found
            and last.get("settings_hash") == digest
        ):
            report.update(checked=True, cached=True)
            report["why"] = (
                f"Claude Code {found} accepted this settings JSON at {last.get('at')} "
                "(cached pass)"
            )
            return report
        report["checked"] = True
        worker_file = Path(scratch) / f"ai-task-worker-settings-{digest}.json"
        control_file = Path(scratch) / "ai-task-control-settings.json"
        worker_file.write_text(json.dumps(settings), encoding="utf-8")
        control_file.write_text(json.dumps(CLAUDE_SETTINGS_CANARY_CONTROL), encoding="utf-8")
        control = _run(["--settings", str(control_file), "doctor"])
        worker = _run(["--settings", str(worker_file), "doctor"])

    version_note = f"Claude Code {found or 'of unknown version'}"
    control_flagged = control is not None and bool(
        parse_doctor_invalid_settings(control.stdout + control.stderr, control_file.name)
    )
    if worker is not None:
        report["invalid"] = parse_doctor_invalid_settings(
            worker.stdout + worker.stderr, worker_file.name
        )
    missing = missing_key_names(binary, claude_settings_key_paths(settings))
    report["unknown_keys"] = missing or []
    findings: list[str] = []
    if report["invalid"]:
        findings.append(
            "`claude doctor` reports invalid keys, so print mode drops the whole JSON: "
            + "; ".join(report["invalid"])
        )
    if report["unknown_keys"]:
        findings.append(
            "key names absent from the Claude Code binary, renamed or removed: "
            + ", ".join(report["unknown_keys"])
        )
    if findings:
        report["ok"] = False
        report["why"] = (
            f"{version_note} would run the worker without its settings JSON (write "
            "block, Bash sandbox, cache env): "
            + " | ".join(findings)
            + f"; {_last_pass_note(last)}. Update CLAUDE_HEADLESS_SETTINGS "
            "and repeat the negative probe (docs/vendor-contract.md)"
        )
        return report
    if worker is None or not control_flagged:
        report["ok"] = False
        report["undetermined"] = True
        cause = (
            "`claude --settings <file> doctor` did not run"
            if worker is None or control is None
            else "`claude doctor` no longer reports a known-invalid control settings file"
        )
        report["why"] = (
            f"settings canary cannot tell on {version_note}: {cause}; "
            f"{_last_pass_note(last)}. Repeat the negative probe "
            "(docs/vendor-contract.md)"
        )
        return report
    keys_note = (
        f"{len(claude_settings_key_paths(settings))} key names found in the binary"
        if missing is not None
        else f"key names not searched, {binary.name} is a wrapper"
    )
    report["why"] = (
        f"{version_note} accepts the worker settings JSON: `claude doctor` flags "
        f"no key, {keys_note}"
    )
    if found is not None:
        report["last_passed_version"] = found
        report["last_passed_at"] = now()
        state["last_pass"] = {
            "cli_version": found,
            "settings_hash": digest,
            "at": report["last_passed_at"],
        }
        _write_canary_state(root, state)
    return report


def claude_settings_launch_block(backend: dict[str, Any], root: Path) -> str | None:
    """Reason to refuse a claude launch, or None.

    Refuses only on a definitive finding: the worker would run without its
    settings JSON. A canary that cannot tell warns on stderr and lets the run
    go, because a changed doctor output must not stop every wave; quota doctor
    fails on it instead.
    """
    report = claude_settings_canary(backend, root)
    if report["ok"] or not report["checked"]:
        return None
    if report["undetermined"]:
        print(f"warning: {report['why']}", file=sys.stderr)
        return None
    return str(report["why"])
