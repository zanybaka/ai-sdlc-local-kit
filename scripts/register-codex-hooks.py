#!/usr/bin/env python3
"""Register the Codex hooks of this repository and trust them.

The link scripts call this right after scripts/register-claude-hooks.py, in
the same step. It does two things.

1. It merges the hook entries into ~/.codex/hooks.json (or $CODEX_HOME), the
   same way the Claude registrar merges ~/.claude/settings.json: every event,
   group and hook the user has stays, a hook of ours that is already there
   (its file name in a command of the same event) keeps its command, and only
   timeout is set. The merge code is the Claude registrar's own `merge`.
2. Codex runs a hook from hooks.json only after the user trusted it: the
   trusted hash of the declaration is stored under hooks.state in
   config.toml. This script asks Codex itself for the key and hash of each of
   our hooks (`codex app-server`, method hooks/list) and writes the trust
   through Codex's own config writer (config/batchWrite, upsert into
   hooks.state), so the hash format stays Codex's business and config.toml
   keeps its comments and layout. Only hooks from our hooks.json whose
   command names one of our scripts are trusted; a hook the user disabled
   stays disabled. Without the `codex` binary the hooks are registered and a
   note says they are not trusted yet.

Why not --dangerously-bypass-hook-trust for the worker: that flag runs every
enabled hook without trust, including a hooks.json or [hooks] that a project
being worked on carries in its own .codex folder, so an untrusted repository
would run its commands in the worker. A saved trust covers only these hooks.
The trust is keyed by position (hooks.json:<event>:<group>:<handler>) and
hashed over the declaration, not over the script file: a git pull of a hook
script keeps it trusted, while a new group in front of ours or a changed
command needs this script to run again.

Usage:
    python3 scripts/register-codex-hooks.py            # merge, write, trust
    python3 scripts/register-codex-hooks.py --dry-run  # print the diff only

Exit codes: 0 done or nothing to do (also when Codex is not installed),
2 hooks.json cannot be merged (left untouched), 3 Codex refused or did not
answer the trust request (hooks.json is written, the hooks stay untrusted).
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "register_claude_hooks", Path(__file__).with_name("register-claude-hooks.py")
)
assert _spec is not None and _spec.loader is not None
claude = importlib.util.module_from_spec(_spec)
sys.modules["register_claude_hooks"] = claude
_spec.loader.exec_module(claude)

HookSpec = claude.HookSpec

HOOKS: tuple[HookSpec, ...] = (
    # Same hook and input as under Claude Code: Codex sends its shell calls as
    # tool_name "Bash" with tool_input.command. Codex has no onFailure: a hook
    # that cannot start is reported and the command goes ahead (fail open,
    # as chosen for Claude).
    HookSpec(
        event="PreToolUse",
        matcher="^Bash$",
        script="no-expensive-ci-polling.py",
        timeout=10,
    ),
    # The lint gate's Codex adapter: records the files of each apply_patch,
    # because a `codex exec --ephemeral` worker gets no transcript.
    HookSpec(
        event="PostToolUse",
        matcher="^apply_patch$",
        script="lint-gate.py",
        timeout=30,
    ),
    # Codex has no onFailure either: a lint gate that cannot start lets the
    # turn end with a hook failure shown, it does not block.
    HookSpec(event="Stop", script="lint-gate.py", timeout=660),
)

# hooks/list names events in camelCase.
EVENT_IDS = {"PreToolUse": "preToolUse", "PostToolUse": "postToolUse", "Stop": "stop"}
TRUSTABLE = ("untrusted", "modified")
RPC_TIMEOUT = 60  # seconds for the whole app-server conversation


class TrustError(Exception):
    """Codex did not answer or refused the trust request."""


class AppServer:
    """Minimal JSON-RPC client of `codex app-server` over stdio."""

    def __init__(self, codex: str, codex_home: Path) -> None:
        env = dict(os.environ, CODEX_HOME=str(codex_home))
        try:
            self.proc = subprocess.Popen(
                [codex, "app-server"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                env=env,
            )
        except OSError as exc:
            raise TrustError(f"cannot start {codex} app-server: {exc}") from exc
        self.deadline = time.monotonic() + RPC_TIMEOUT
        self.lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.next_id = 0

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _send(self, message: dict) -> None:
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
            self.proc.stdin.flush()
        except OSError as exc:
            raise TrustError(f"codex app-server closed its input: {exc}") from exc

    def call(self, method: str, params: dict) -> dict:
        self.next_id += 1
        wanted = self.next_id
        self._send({"id": wanted, "method": method, "params": params})
        while True:
            left = self.deadline - time.monotonic()
            if left <= 0:
                raise TrustError(f"codex app-server did not answer {method} in time")
            try:
                line = self.lines.get(timeout=left)
            except queue.Empty:
                continue
            if line is None:
                raise TrustError(f"codex app-server exited before answering {method}")
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict) or message.get("id") != wanted:
                continue
            if "error" in message:
                raise TrustError(f"{method}: {message['error']}")
            result = message.get("result")
            return result if isinstance(result, dict) else {}

    def notify(self, method: str) -> None:
        self._send({"method": method})

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()


def our_untrusted(
    entries: list, hooks_path: Path, specs: tuple[HookSpec, ...]
) -> tuple[dict[str, str], list[str]]:
    """Pick our hooks from a hooks/list answer: {key: hash} to trust, notes."""
    wanted = {(EVENT_IDS[s.event], s.script) for s in specs}
    source = str(hooks_path.resolve())
    trust: dict[str, str] = {}
    notes: list[str] = []
    for entry in entries:
        for hook in entry.get("hooks", []) if isinstance(entry, dict) else []:
            if not isinstance(hook, dict) or hook.get("handlerType") != "command":
                continue
            try:
                if str(Path(str(hook.get("sourcePath", ""))).resolve()) != source:
                    continue
            except OSError:
                continue
            command = str(hook.get("command", ""))
            script = next(
                (s for e, s in wanted if e == hook.get("eventName") and s in command),
                None,
            )
            if script is None:
                continue
            label = f"{hook.get('eventName')} {script}"
            status = hook.get("trustStatus")
            if not hook.get("enabled", True):
                notes.append(f"keep {label}: disabled by you")
            elif status in TRUSTABLE and hook.get("key") and hook.get("currentHash"):
                trust[str(hook["key"])] = str(hook["currentHash"])
                notes.append(f"trust {label}: was {status}")
            else:
                notes.append(f"ok {label}: {status}")
    return trust, notes


def trust_hooks(
    codex: str, codex_home: Path, hooks_path: Path, specs: tuple[HookSpec, ...]
) -> list[str]:
    server = AppServer(codex, codex_home)
    try:
        server.call(
            "initialize",
            {"clientInfo": {"name": "register-codex-hooks", "title": None, "version": "1"}},
        )
        server.notify("initialized")
        listed = server.call("hooks/list", {"cwds": [str(codex_home)]})
        trust, notes = our_untrusted(listed.get("data", []), hooks_path, specs)
        if trust:
            server.call(
                "config/batchWrite",
                {
                    "edits": [
                        {
                            "keyPath": "hooks.state",
                            "value": {k: {"trusted_hash": h} for k, h in trust.items()},
                            "mergeStrategy": "upsert",
                        }
                    ]
                },
            )
            listed = server.call("hooks/list", {"cwds": [str(codex_home)]})
            left, _ = our_untrusted(listed.get("data", []), hooks_path, specs)
            if left:
                raise TrustError(f"still untrusted after the write: {', '.join(left)}")
        return notes
    finally:
        server.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--codex-home", type=Path, help="default: $CODEX_HOME or ~/.codex")
    parser.add_argument("--hooks-dir", type=Path, help="default: ~/.claude/hooks")
    parser.add_argument("--python", default="python3", help="interpreter named in hook commands")
    parser.add_argument("--codex", default="codex", help="Codex binary used to trust the hooks")
    parser.add_argument("--dry-run", action="store_true", help="print the diff, write nothing")
    args = parser.parse_args(argv)

    codex_home = args.codex_home or Path(
        os.environ.get("CODEX_HOME") or Path.home() / ".codex"
    )
    default_hooks = Path.home() / ".claude" / "hooks"
    hooks_dir = (args.hooks_dir or default_hooks).expanduser().absolute()
    # Codex runs a hook command through `$SHELL -lc` on Unix, so $HOME expands;
    # on Windows the absolute path is safer than a shell variable.
    hooks_ref = (
        "$HOME/.claude/hooks"
        if hooks_dir == default_hooks and os.name != "nt"
        else hooks_dir.as_posix()
    )
    hooks_path = codex_home / "hooks.json"

    old_text = hooks_path.read_text(encoding="utf-8") if hooks_path.exists() else ""
    try:
        old = json.loads(old_text) if old_text.strip() else {}
        new, notes = claude.merge(
            old,
            claude_dir=codex_home,
            hooks_dir=hooks_dir,
            hooks_ref=hooks_ref,
            python=args.python,
            specs=HOOKS,
        )
    except (ValueError, claude.SettingsError) as exc:
        print(f"Codex hooks: {hooks_path} left untouched: {exc}", file=sys.stderr)
        return 2

    for note in notes:
        print(f"Codex hooks: {note}")
    if new == old:
        print(f"Codex hooks: {hooks_path} is up to date")
    elif args.dry_run:
        sys.stdout.writelines(
            difflib.unified_diff(
                old_text.splitlines(keepends=True),
                claude.render(new).splitlines(keepends=True),
                fromfile=f"{hooks_path} (now)",
                tofile=f"{hooks_path} (after)",
            )
        )
    else:
        if hooks_path.exists():
            backup = hooks_path.with_name(f"hooks.json.bak.{time.strftime('%Y%m%d_%H%M%S')}")
            backup.write_text(old_text, encoding="utf-8")
            print(f"Codex hooks: backup {backup}")
        claude.write_atomic(hooks_path, claude.render(new))
        print(f"Codex hooks: wrote {hooks_path}")

    if args.dry_run:
        print("Codex hooks: dry run, trust is not asked for")
        return 0
    if not new.get("hooks"):
        return 0
    codex = shutil.which(args.codex)
    if codex is None:
        print(
            f"Codex hooks: {args.codex} not found; the hooks are registered but not "
            "trusted, run this script again after installing Codex"
        )
        return 0
    try:
        for note in trust_hooks(codex, codex_home, hooks_path, HOOKS):
            print(f"Codex hooks: {note}")
    except TrustError as exc:
        print(f"Codex hooks: not trusted: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
