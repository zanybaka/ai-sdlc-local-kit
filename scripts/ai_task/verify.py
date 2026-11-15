"""Verify-profile domain for the ai-task CLI.

`[verify]` policy readers, verify-profile resolution (including the web-e2e
keyword heuristic), the pipefail-aware profile command runner, and the
verify report writer. The `verify` command shell stays in the entrypoint:
tests monkeypatch ``at.run_verify_commands`` / ``at.verify_profile_commands``,
so the shell must keep resolving those names through the entrypoint globals
(the functions themselves live here; no package-internal caller bypasses the
patch).
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ai_task._shared import die
from ai_task.backlog import Task, task_metadata

WEB_UI_VERIFY_KEYWORDS = (
    "web",
    "ui",
    "frontend",
    "front-end",
    "playwright",
    "e2e",
    "end-to-end",
    "browser",
    "streamlit",
    "gradio",
    "nicegui",
    "htmx",
    "react",
    "vue",
    "svelte",
    "dashboard",
    "landing page",
    "webpack",
    "vite",
    "next.js",
    "nextjs",
    "spa",
)


def task_context_suggests_web_e2e(task: Task | None) -> bool:
    if not task:
        return False
    text = task.block.lower()
    return any(keyword in text for keyword in WEB_UI_VERIFY_KEYWORDS)


def verify_settings(policy: dict[str, Any]) -> dict[str, Any]:
    raw = policy.get("verify", {})
    return raw if isinstance(raw, dict) else {}


def verify_profiles(policy: dict[str, Any]) -> dict[str, Any]:
    profiles = verify_settings(policy).get("profiles", {})
    return profiles if isinstance(profiles, dict) else {}


def task_verify_profile(task: Task | None) -> str:
    if not task:
        return ""
    block_lines = task.block.splitlines()
    return task_metadata(block_lines, "Verify").strip().lower()


def resolve_verify_profile(
    policy: dict[str, Any],
    *,
    task: Task | None,
    run_record: dict[str, Any] | None,
    cli_profile: str | None,
) -> tuple[str, str]:
    """Return (profile_name, resolution_source)."""
    settings = verify_settings(policy)
    profiles = verify_profiles(policy)
    if cli_profile:
        name = cli_profile.strip().lower()
        source = "cli"
    elif run_record and str(run_record.get("verify_profile", "") or "").strip():
        name = str(run_record["verify_profile"]).strip().lower()
        source = "run"
    elif task_verify_profile(task):
        name = task_verify_profile(task)
        source = "task_verify"
    elif (
        task
        and task_context_suggests_web_e2e(task)
        and "web-e2e" in profiles
        and not task_verify_profile(task)
    ):
        name = "web-e2e"
        source = "task_context"
    else:
        name = str(settings.get("default_profile", "none") or "none").strip().lower()
        source = "policy_default"
    if name not in profiles:
        known = ", ".join(sorted(profiles)) or "(none)"
        die(f"unknown verify profile: {name} (known: {known})")
    return name, source


def verify_profile_commands(policy: dict[str, Any], profile_name: str) -> list[str]:
    profile = verify_profiles(policy).get(profile_name, {})
    if not isinstance(profile, dict):
        die(f"invalid verify profile config: {profile_name}")
    commands = profile.get("commands", [])
    if not isinstance(commands, list):
        die(f"verify profile {profile_name} commands must be a list")
    return [str(cmd).strip() for cmd in commands if str(cmd).strip()]


def pipefail_shell() -> str | None:
    """Locate a POSIX shell that supports ``set -o pipefail`` for verify steps.
    """
    if os.name == "nt":
        return None
    for name in ("bash", "zsh"):
        path = shutil.which(name)
        if path:
            return path
    return None


# Shell names whose `-c <command>` argument starts a NEW shell without pipefail.
NESTED_PIPE_WRAPPER_SHELLS = frozenset({"bash", "sh", "zsh"})
# A single `|` (pipe or `|&`), not `||` (logical or).
_SINGLE_PIPE_RE = re.compile(r"(?<!\|)\|(?!\|)")
# Short-option cluster containing `c` (`-c`, `-lc`, `-ec`, ...), not long options.
_DASH_C_CLUSTER_RE = re.compile(r"-[A-Za-z]*c[A-Za-z]*")


def nested_shell_pipe_command(command: str) -> str | None:
    """Return the inner command when ``command`` nests a pipe in a sub-shell.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    for index, token in enumerate(tokens):
        if token.rsplit("/", 1)[-1] not in NESTED_PIPE_WRAPPER_SHELLS:
            continue
        rest = tokens[index + 1 :]
        inner: str | None = None
        pos = 0
        while pos < len(rest):
            arg = rest[pos]
            if _DASH_C_CLUSTER_RE.fullmatch(arg):
                if pos + 1 < len(rest):
                    inner = rest[pos + 1]
                break
            if arg in ("-o", "+o"):
                pos += 2  # skip the option name consumed by -o/+o
                continue
            if arg.startswith("-") and len(arg) > 1:
                pos += 1  # other option flag
                continue
            break  # operand before -c: a script-file invocation, not a wrapper
        if not inner or "pipefail" in inner:
            continue
        if _SINGLE_PIPE_RE.search(inner):
            return inner
    return None


def warn_nested_shell_pipes(
    settings: dict[str, Any], profile_name: str, commands: list[str]
) -> None:
    """Flag profile commands whose pipes hide inside a nested shell wrapper.

    Policy knob ``[verify] nested_shell_pipe``: ``"warn"`` (default) prints a
    warning per offending command; ``"fail"`` additionally refuses to run the
    profile.
    """
    flagged = [
        (command, inner)
        for command in commands
        if (inner := nested_shell_pipe_command(command)) is not None
    ]
    if not flagged:
        return
    for command, inner in flagged:
        print(
            f"warning: verify profile {profile_name}: nested shell wrapper hides "
            f"a pipe from pipefail: {command}\n"
            f"  the inner shell runs `{inner}` without pipefail, so a failing "
            "inner pipe stage cannot fail this step; de-nest the command (write "
            "it flat, e.g. `cd web && npm run build 2>&1 | tail -5`) or start "
            "the inner command with `set -o pipefail;`",
            file=sys.stderr,
        )
    mode = str(settings.get("nested_shell_pipe", "warn") or "warn").strip().lower()
    if mode == "fail":
        die(
            f"verify profile {profile_name} nests pipes inside shell wrappers; "
            'refusing to run (nested_shell_pipe = "fail" in [verify])'
        )


def run_verify_commands(
    commands: list[str], *, cwd: Path, dry_run: bool
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    shell_exe = pipefail_shell()
    for command in commands:
        if dry_run:
            results.append({"command": command, "exit_code": 0, "dry_run": True})
            continue
        if shell_exe:
            # Pipefail contract: a failing stage of any pipe written in the
            # profile command itself fails the step. Pipes nested
            # inside a `bash -c`/`sh -c`/`zsh -c` wrapper run in an inner shell
            # WITHOUT pipefail and are NOT covered — warn_nested_shell_pipes
            # flags that shape before execution.
            completed = subprocess.run(
                [shell_exe, "-o", "pipefail", "-c", command],
                cwd=cwd,
                text=True,
                capture_output=True,
                check=False,
            )
        else:
            completed = subprocess.run(
                command,
                cwd=cwd,
                # Semgrep subprocess-shell-true is accepted: verify commands are shell strings
                # by contract, written by the repository owner in its own ai-task profile; this is the fallback when
                # no pipefail shell is found.
                # nosemgrep: subprocess-shell-true
                shell=True,
                text=True,
                capture_output=True,
                check=False,
            )
        results.append(
            {
                "command": command,
                "exit_code": completed.returncode,
                "pipefail": bool(shell_exe),
                "stdout_tail": (completed.stdout or "")[-2000:],
                "stderr_tail": (completed.stderr or "")[-2000:],
            }
        )
    return results


def write_verify_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# ai-task verify report",
        "",
        f"Profile: {payload.get('profile')}",
        f"Resolution: {payload.get('resolution', 'unknown')}",
        f"Status: {payload.get('status')}",
        f"Cwd: {payload.get('cwd')}",
        f"Generated: {payload.get('generated_at')}",
        "",
    ]
    for item in payload.get("results", []):
        lines.append(f"## `{item.get('command')}`")
        lines.append(f"exit_code: {item.get('exit_code')}")
        if item.get("stdout_tail"):
            lines.append("```text")
            lines.append(str(item.get("stdout_tail")).rstrip())
            lines.append("```")
        if item.get("stderr_tail"):
            lines.append("stderr:")
            lines.append("```text")
            lines.append(str(item.get("stderr_tail")).rstrip())
            lines.append("```")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
