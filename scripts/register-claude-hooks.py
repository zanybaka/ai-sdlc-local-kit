#!/usr/bin/env python3
"""Register the Claude Code hooks of this repository in the user settings.

The link scripts (scripts/link-symbolic-folders.sh and .ps1) make the hooks
available as ~/.claude/hooks. This script, which both of them call, adds the
hook entries to ~/.claude/settings.json so the hooks actually run.

It merges, it never replaces: every key, event, matcher group and hook the
user already has stays where it is. A hook of this repository that is already
registered (its file name appears in a command of the same event) keeps its
command and any extra keys such as statusMessage; only the keys this script
owns, timeout and onFailure, are set to the values below. A second run with
nothing new changes nothing and does not rewrite the file.

A hook is registered only when its file is in the hooks folder, and the
Telegram hook only when its config exists. The project Stop hook of this
repository lives in the committed .claude/settings.json and is never copied
into user settings.

Usage:
    python3 scripts/register-claude-hooks.py            # merge and write
    python3 scripts/register-claude-hooks.py --dry-run  # print the diff only

Exit codes: 0 done or nothing to do, 2 the settings file cannot be merged
(invalid JSON or an unexpected shape); the file is then left untouched.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class HookSpec:
    event: str
    script: str
    matcher: str | None = None
    timeout: int | None = None
    on_failure: str | None = None
    # Paths relative to the Claude folder that must all exist for the hook to be registered.
    needs: tuple[str, ...] = field(default_factory=tuple)


TELEGRAM_CONFIG = ("channels/telegram/.env", "channels/telegram/access.json")

HOOKS: tuple[HookSpec, ...] = (
    # Fail open on purpose: this hook runs before every Bash call of every
    # session, so with onFailure "block" a hook that cannot start (python3
    # missing, a syntax error after a bad pull) would refuse every shell
    # command. A missed polling refusal costs API calls; a blocked shell stops
    # all work.
    HookSpec(
        event="PreToolUse",
        matcher="Bash",
        script="no-expensive-ci-polling.py",
        timeout=10,
        on_failure="continue",
    ),
    # Fail closed: a lint gate that crashes or times out must not let the
    # turn end as if the lint passed. The hook itself still approves on its
    # own handled errors (no transcript, no git), so only a hook that cannot
    # start, times out or exits with an unexpected code blocks the stop.
    # The timeout covers its five linter calls of up to 120 seconds each.
    HookSpec(
        event="Stop",
        script="lint-gate.py",
        timeout=660,
        on_failure="block",
    ),
    HookSpec(
        event="Stop",
        script="telegram-notify.py",
        timeout=30,
        needs=TELEGRAM_CONFIG,
    ),
    HookSpec(
        event="Notification",
        script="telegram-notify.py",
        timeout=30,
        needs=TELEGRAM_CONFIG,
    ),
)

OWNED_KEYS = ("timeout", "onFailure")


class SettingsError(Exception):
    """The settings file cannot be merged safely."""


def hook_command(python: str, hooks_ref: str, script: str) -> str:
    return f'{python} "{hooks_ref}/{script}"'


def _groups(hooks: dict, event: str) -> list:
    groups = hooks.setdefault(event, [])
    if not isinstance(groups, list):
        raise SettingsError(f"hooks.{event} is not a list")
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
            raise SettingsError(f"hooks.{event} has an entry without a hooks list")
    return groups


def _find_existing(groups: list, script: str) -> dict | None:
    for group in groups:
        for hook in group.get("hooks", []):
            if isinstance(hook, dict) and script in str(hook.get("command", "")):
                return hook
    return None


def _target_group(groups: list, matcher: str | None) -> dict:
    for group in groups:
        current = group.get("matcher")
        if matcher is None and current in (None, "", "*"):
            return group
        if matcher is not None and current == matcher:
            return group
    group: dict = (
        {"matcher": matcher, "hooks": []} if matcher is not None else {"hooks": []}
    )
    groups.append(group)
    return group


def merge(
    settings: dict,
    *,
    claude_dir: Path,
    hooks_dir: Path,
    hooks_ref: str,
    python: str,
    specs: tuple[HookSpec, ...] = HOOKS,
) -> tuple[dict, list[str]]:
    """Return merged settings and one human-readable line per decision."""
    if not isinstance(settings, dict):
        raise SettingsError("the settings file is not a JSON object")
    result = copy.deepcopy(settings)
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SettingsError("hooks is not an object")
    notes: list[str] = []
    for spec in specs:
        label = f"{spec.event} {spec.script}"
        if not (hooks_dir / spec.script).is_file():
            notes.append(f"skip {label}: no {hooks_dir / spec.script}")
            continue
        missing = [rel for rel in spec.needs if not (claude_dir / rel).is_file()]
        groups = _groups(hooks, spec.event)
        existing = _find_existing(groups, spec.script)
        if missing:
            if existing is None:
                notes.append(f"skip {label}: no {', '.join(missing)}")
            else:
                notes.append(f"keep {label}: registered by you, its config is missing")
            continue
        wanted = {"timeout": spec.timeout, "onFailure": spec.on_failure}
        if existing is None:
            entry: dict = {
                "type": "command",
                "command": hook_command(python, hooks_ref, spec.script),
            }
            entry.update({k: v for k, v in wanted.items() if v is not None})
            _target_group(groups, spec.matcher)["hooks"].append(entry)
            notes.append(f"add {label}")
            continue
        changed = [
            key
            for key in OWNED_KEYS
            if wanted[key] is not None and existing.get(key) != wanted[key]
        ]
        for key in changed:
            existing[key] = wanted[key]
        notes.append(
            f"update {label}: {', '.join(changed)}" if changed else f"ok {label}"
        )
    # Drop event lists this run created but left empty (every hook skipped).
    for event in [
        e
        for e, groups in hooks.items()
        if groups == [] and e not in settings.get("hooks", {})
    ]:
        del hooks[event]
    if not hooks and "hooks" not in settings:
        del result["hooks"]
    return result, notes


def render(settings: dict) -> str:
    return json.dumps(settings, indent=2, ensure_ascii=False) + "\n"


def write_atomic(path: Path, text: str) -> None:
    target = path.resolve() if path.is_symlink() else path
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings.", suffix=".json", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claude-dir", type=Path, help="default: ~/.claude")
    parser.add_argument(
        "--python", default="python3", help="interpreter named in hook commands"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the diff, write nothing"
    )
    args = parser.parse_args(argv)

    home_claude = Path.home() / ".claude"
    claude_dir = args.claude_dir or home_claude
    hooks_dir = claude_dir / "hooks"
    # $HOME expands in the shells Claude Code runs hooks with (bash, zsh, PowerShell).
    hooks_ref = (
        "$HOME/.claude/hooks" if claude_dir == home_claude else hooks_dir.as_posix()
    )
    settings_path = claude_dir / "settings.json"

    old_text = (
        settings_path.read_text(encoding="utf-8") if settings_path.exists() else ""
    )
    try:
        old = json.loads(old_text) if old_text.strip() else {}
        new, notes = merge(
            old,
            claude_dir=claude_dir,
            hooks_dir=hooks_dir,
            hooks_ref=hooks_ref,
            python=args.python,
        )
    except (ValueError, SettingsError) as exc:
        print(f"Hooks: {settings_path} left untouched: {exc}", file=sys.stderr)
        return 2

    for note in notes:
        print(f"Hooks: {note}")
    if new == old:
        print(f"Hooks: {settings_path} is up to date")
        return 0
    new_text = render(new)
    if args.dry_run:
        sys.stdout.writelines(
            difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"{settings_path} (now)",
                tofile=f"{settings_path} (after)",
            )
        )
        return 0
    if settings_path.exists():
        backup = settings_path.with_name(
            f"settings.json.bak.{time.strftime('%Y%m%d_%H%M%S')}"
        )
        backup.write_text(old_text, encoding="utf-8")
        print(f"Hooks: backup {backup}")
    write_atomic(settings_path, new_text)
    print(f"Hooks: wrote {settings_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
