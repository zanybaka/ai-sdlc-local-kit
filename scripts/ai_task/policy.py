"""Policy domain for the ai-task CLI.

TOML policy machinery extracted verbatim from scripts/ai-task.py: policy file
reading (read_policy, read_config, load_toml), the bundled default policy
template (default_policy and the LIMIT_WORDS defaults baked into it), TOML
rendering (render_policy_toml and friends), and the template-wins merge plus
drift reporting behind `ai-task policy sync`.
"""

from __future__ import annotations

import ast
import copy
import datetime as dt
import json
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback.
    tomllib = None  # type: ignore[assignment]

from ai_task._shared import app_path, die

LIMIT_WORDS = (
    "rate limit",
    "usage limit",
    "too many requests",
    "429",
    "quota exceeded",
    "limit reached",
    "hit your limit",
    "reached your limit",
    "usage limit reached",
)


DEFAULT_LIMIT_PATTERNS = list(LIMIT_WORDS)


# Credential/auth failure signatures. Same shape as LIMIT_WORDS
# (substring match on the attempt's log tail, per-backend override via
# `auth_patterns`), but a different condition: the backend cannot work at all on
# this host until an operator authenticates it. Deliberately conservative — a
# match reclassifies a run away from "task failed", so a false positive hides a
# real failure. Bare status codes ("401") are excluded for that reason; the
# detector is additionally gated on a nonzero-exit attempt at every call site.
AUTH_WORDS = (
    "authentication required",
    "authentication failed",
    "not authenticated",
    "not logged in",
    "please log in",
    "please login",
    "agent login",
    "invalid api key",
    "expired credentials",
    "cursor_api_key",
    "your account is on hold",
)


DEFAULT_AUTH_PATTERNS = list(AUTH_WORDS)


# Operator-facing fix per backend command, used when a backend defines no
# `auth_fix` in policy. Keyed by the CLI command, not the backend name, so a
# repo that renames a backend table still gets the right instruction.
DEFAULT_AUTH_FIX_HINTS = {
    "cursor-agent": (
        "run `cursor-agent login` (or `agent login`) on this host, "
        "or set CURSOR_API_KEY"
    ),
    "claude": "run `claude login` on this host, or set ANTHROPIC_API_KEY",
    "codex": "run `codex login` on this host",
    "devin": "run `devin auth login` on this host",
}


POLICY_TOP_SECTION_ORDER = (
    "batch",
    "priority",
    "scenario",
    "executor",
    "review",
    "supervision",
    "cooldown",
    "cleanup",
    "quota",
    "verify",
    "parallel",
    "decisions",
    "scope_guard",
    "routing",
    "backends",
)


# Deliberate project choices that sync keeps even with --force: the host-inference
# opt-in, the executor mode and its ask rule and the
# Codex review pass opt-in.
POLICY_LOCAL_CHOICE_PATHS = frozenset(
    {
        "routing.default_source",
        "executor.default",
        "executor.ask_above_tasks",
        "executor.in_session_timeout_seconds",
        "review.codex.enabled",
    }
)


# Sections rendered via render_dict_table (they contain nested sub-tables, e.g.
# [quota.reservations]); render_simple_section would reject the nested dict.
POLICY_NESTED_TABLE_SECTIONS = frozenset({"quota", "review", "routing"})


POLICY_APPEND_LIST_KEYS = frozenset(
    {
        "limit_patterns",
        "auth_patterns",
        "blocked_patterns",
        "disabled_backends",
        "order",
        "high_priority",
        "commands",
        "extra_args",
        "args",
        "task_files",
    }
)


# Bundled template wins on policy sync when local differs (upgrade path). Other scalars: local wins.
POLICY_TEMPLATE_SCALAR_PATHS = frozenset(
    {
        "supervision.stall_timeout_seconds",
        "cooldown.default_seconds",
        "backends.claude.reasoning",
    }
)


# Retired bundled defaults: a local scalar still equal to one of them was never chosen by
# the project, so sync replaces it with the bundled value. Any other local value is the
# project's choice and stays (local wins, as for every scalar).
POLICY_RETIRED_SCALAR_DEFAULTS: dict[str, frozenset[Any]] = {
    # one report name, tasks/<ID>.md.
    "handoff.task_report_pattern": frozenset({"{task_id}-report.md"}),
}


def is_retired_policy_default(path: str, local: Any) -> bool:
    retired = POLICY_RETIRED_SCALAR_DEFAULTS.get(path)
    return retired is not None and isinstance(local, str) and local in retired


# Headless Claude permissions. Auto mode decides each tool call;
# --permission-prompts none (Claude Code 2.1.259) denies whatever would wait on a
# prompt; the --settings JSON adds permissions.denyInsteadOfPrompting (2.1.319, the
# same for subagents) and permissions.blockWritesOutsideWorkingDirectories (2.1.314,
# Write/Edit/NotebookEdit refuse paths outside the working directories).
#
# The Bash sandbox covers what the file-tool setting does not: a shell
# command writes only inside the worktree and the temp folder, and reaches only the
# domains below (default: GitHub and PyPI). strictAllowlist (2.1.219)
# denies any other host without a prompt, allowUnsandboxedCommands = false removes the
# per-command escape, failIfUnavailable (2.1.83) stops claude instead of running
# unsandboxed when the sandbox cannot start (Linux needs bubblewrap and socat).
# allowMachLookup opens macOS trustd, without which pip and gh fail TLS verification
# inside the sandbox (OSStatus -26276); Linux ignores it.
# The sandbox refuses the package caches in the home folder, so uv, pip and npm keep
# theirs under .ai-task/cache/ of the worktree: relative paths, so a command run from a
# subfolder still lands inside the worktree, and git ignores .ai-task/ at any depth.
CLAUDE_SANDBOX_CACHE_ENV: dict[str, str] = {
    "UV_CACHE_DIR": ".ai-task/cache/uv",
    "UV_TOOL_DIR": ".ai-task/cache/uv-tools",
    "UV_PYTHON_INSTALL_DIR": ".ai-task/cache/uv-python",
    "PIP_CACHE_DIR": ".ai-task/cache/pip",
    "npm_config_cache": ".ai-task/cache/npm",
}
CLAUDE_SANDBOX_ALLOWED_DOMAINS: tuple[str, ...] = (
    "github.com",
    "*.github.com",
    "*.githubusercontent.com",
    "pypi.org",
    "files.pythonhosted.org",
)
CLAUDE_HEADLESS_SETTINGS: dict[str, Any] = {
    "permissions": {
        "denyInsteadOfPrompting": True,
        "blockWritesOutsideWorkingDirectories": True,
    },
    "sandbox": {
        "enabled": True,
        "failIfUnavailable": True,
        "allowUnsandboxedCommands": False,
        "network": {
            "strictAllowlist": True,
            "allowedDomains": list(CLAUDE_SANDBOX_ALLOWED_DOMAINS),
            "allowMachLookup": ["com.apple.trustd.agent"],
        },
    },
    "env": dict(CLAUDE_SANDBOX_CACHE_ENV),
}
# Per-stack sandbox additions: node workers
# reach the npm registry, Xcode workers write DerivedData and the SwiftPM caches.
# read_policy merges the entries of the stacks it detects in the repository (or the
# stacks named by [backends.claude] sandbox_stacks) into the run argv; the policy file
# keeps the bundled list, so policy sync is unaffected.
CLAUDE_SANDBOX_STACK_EXTRAS: dict[str, dict[str, Any]] = {
    "node": {"network": {"allowedDomains": ["registry.npmjs.org"]}},
    "xcode": {
        "filesystem": {
            "allowWrite": [
                "~/Library/Developer/Xcode/DerivedData",
                "~/Library/Caches/org.swift.swiftpm",
                "~/Library/org.swift.swiftpm",
            ]
        }
    },
}
CLAUDE_SANDBOX_STACKS_KEY = "sandbox_stacks"
CLAUDE_SANDBOX_STACKS_APPLIED_KEY = "sandbox_stacks_applied"
# xcrun and xcodebuild also write the per-user temp and cache folders of macOS
# (getconf DARWIN_USER_TEMP_DIR / DARWIN_USER_CACHE_DIR, /var/folders/...), which are
# not the TMPDIR the sandbox opens; the paths differ per user, so they are read at launch.
CLAUDE_SANDBOX_DARWIN_USER_DIRS: tuple[str, ...] = ("DARWIN_USER_TEMP_DIR", "DARWIN_USER_CACHE_DIR")


def darwin_user_dirs() -> list[str]:
    """The per-user temp and cache folders of macOS; [] elsewhere or when getconf fails."""
    if not sys.platform.startswith("darwin"):
        return []
    import subprocess

    found: list[str] = []
    for name in CLAUDE_SANDBOX_DARWIN_USER_DIRS:
        try:
            proc = subprocess.run(
                ["getconf", name], check=False, capture_output=True, text=True, timeout=5
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        value = proc.stdout.strip().rstrip("/")
        if proc.returncode == 0 and value.startswith("/"):
            found.append(value)
    return found


def sandbox_stack_extra(stack: str) -> dict[str, Any]:
    """CLAUDE_SANDBOX_STACK_EXTRAS[stack] plus what is read at launch (xcode: macOS user dirs)."""
    extra = json.loads(json.dumps(CLAUDE_SANDBOX_STACK_EXTRAS.get(stack, {})))
    if stack == "xcode":
        dirs = darwin_user_dirs()
        if dirs:
            extra.setdefault("filesystem", {}).setdefault("allowWrite", []).extend(dirs)
    return extra


def detect_sandbox_stacks(root: Path) -> set[str]:
    """Stacks of CLAUDE_SANDBOX_STACK_EXTRAS found by cheap markers at the root and one level below."""
    stacks: set[str] = set()

    def visible(path: Path) -> bool:
        return not any(
            part.startswith(".") or part == "node_modules"
            for part in path.relative_to(root).parts[:-1]
        )

    if (root / "package.json").is_file() or any(
        candidate.is_file() and visible(candidate) for candidate in root.glob("*/package.json")
    ):
        stacks.add("node")
    xcode = [*root.glob("*.xcodeproj"), *root.glob("*.xcworkspace"), *root.glob("*/*.xcodeproj")]
    if (root / "Package.swift").is_file() or any(visible(item) for item in xcode):
        stacks.add("xcode")
    return stacks


def _merge_sandbox_extra(target: dict[str, Any], extra: dict[str, Any]) -> None:
    for key, value in extra.items():
        current = target.get(key)
        if isinstance(value, dict):
            if not isinstance(current, dict):
                current = target[key] = {}
            _merge_sandbox_extra(current, value)
        elif isinstance(value, list):
            items = list(current) if isinstance(current, list) else []
            items.extend(item for item in value if item not in items)
            target[key] = items
        else:
            target[key] = value


def apply_claude_sandbox_stacks(policy: dict[str, Any], root: Path | None) -> dict[str, Any]:
    """Add the per-stack sandbox entries to every claude backend whose settings sandbox Bash.

    ``sandbox_stacks`` in the backend table replaces detection (an empty list turns the
    additions off); unknown names are ignored. The stacks used are recorded under
    ``sandbox_stacks_applied`` so status and doctor can show them.
    """
    backends = policy.get("backends", {})
    if not isinstance(backends, dict):
        return policy
    detected: set[str] | None = None
    for config in backends.values():
        if not isinstance(config, dict) or Path(str(config.get("command", ""))).name != "claude":
            continue
        extra_args = [str(item) for item in config.get("extra_args", []) or []]
        if "--settings" not in extra_args[:-1]:
            continue
        index = extra_args.index("--settings") + 1
        settings = claude_settings_from_argv(extra_args)
        sandbox = settings.get("sandbox")
        if not isinstance(sandbox, dict) or not sandbox.get("enabled"):
            continue
        chosen = config.get(CLAUDE_SANDBOX_STACKS_KEY)
        if isinstance(chosen, list):
            stacks = {str(item) for item in chosen}
        else:
            if detected is None:
                detected = detect_sandbox_stacks(root) if root is not None else set()
            stacks = detected
        applied = sorted(stack for stack in stacks if stack in CLAUDE_SANDBOX_STACK_EXTRAS)
        for stack in applied:
            _merge_sandbox_extra(sandbox, sandbox_stack_extra(stack))
        if applied:
            extra_args[index] = json.dumps(settings, separators=(",", ":"))
            config["extra_args"] = extra_args
        config[CLAUDE_SANDBOX_STACKS_APPLIED_KEY] = applied
    return policy


# The Codex worker sandbox. [backends.codex] runs workspace-write, which
# refuses the package caches and DerivedData in the home folder and has no network.
# With worker_sandbox = true, backend_command adds the same owner decisions as the
# Claude worker: caches under .ai-task/cache/ of the run directory, network only to
# CLAUDE_SANDBOX_ALLOWED_DOMAINS through the managed proxy of Codex, and the
# CLAUDE_SANDBOX_STACK_EXTRAS entries of the stacks found here (npm registry for node,
# DerivedData and the SwiftPM caches for Xcode) as domains and writable roots.
CODEX_WORKER_SANDBOX_KEY = "worker_sandbox"


def apply_codex_sandbox_stacks(policy: dict[str, Any], root: Path | None) -> dict[str, Any]:
    """Record the sandbox stacks of every codex backend with ``worker_sandbox``.

    Same rules as the claude backend: ``sandbox_stacks`` replaces detection, unknown
    names are ignored, and the result lands under ``sandbox_stacks_applied``, which
    backend_command reads at launch.
    """
    backends = policy.get("backends", {})
    if not isinstance(backends, dict):
        return policy
    detected: set[str] | None = None
    for config in backends.values():
        if not isinstance(config, dict) or Path(str(config.get("command", ""))).name != "codex":
            continue
        if not config.get(CODEX_WORKER_SANDBOX_KEY):
            continue
        chosen = config.get(CLAUDE_SANDBOX_STACKS_KEY)
        if isinstance(chosen, list):
            stacks = {str(item) for item in chosen}
        else:
            if detected is None:
                detected = detect_sandbox_stacks(root) if root is not None else set()
            stacks = detected
        config[CLAUDE_SANDBOX_STACKS_APPLIED_KEY] = sorted(
            stack for stack in stacks if stack in CLAUDE_SANDBOX_STACK_EXTRAS
        )
    return policy


# Linux binaries the Claude Code sandbox needs; quota doctor checks them on Linux.
CLAUDE_SANDBOX_LINUX_BINARIES: tuple[str, ...] = ("bwrap", "socat")
CLAUDE_HEADLESS_PERMISSION_ARGS: tuple[str, ...] = (
    "--permission-mode",
    "auto",
    "--permission-prompts",
    "none",
    "--settings",
    json.dumps(CLAUDE_HEADLESS_SETTINGS, separators=(",", ":")),
)
# The oldest Claude Code that knows every flag and key above (denyInsteadOfPrompting).
CLAUDE_HEADLESS_PERMISSIONS_MIN_VERSION: tuple[int, int, int] = (2, 1, 319)
CLAUDE_RETIRED_SKIP_PERMISSIONS_FLAG = "--dangerously-skip-permissions"


# Retired bundled list defaults. Lists under backends.*.args/extra_args are recipe lists
# (a local list that differs from bundled is kept whole), so without this table a policy
# that still carries an old template value would keep it forever. A local list equal to
# a retired value was never chosen by the project, and sync replaces it with the bundled
# list; any other local list stays the project's override.
POLICY_RETIRED_LIST_DEFAULTS: dict[str, tuple[tuple[str, ...], ...]] = {
    "backends.claude.extra_args": (
        # The bypass flag gives way to auto mode with no prompts.
        (CLAUDE_RETIRED_SKIP_PERMISSIONS_FLAG,),
        # The first no-prompt list, before the Bash sandbox.
        (
            "--permission-mode",
            "auto",
            "--permission-prompts",
            "none",
            "--settings",
            (
                '{"permissions":{"denyInsteadOfPrompting":true,'
                '"blockWritesOutsideWorkingDirectories":true}}'
            ),
        ),
        # The sandbox list before the caches moved into the worktree.
        (
            "--permission-mode",
            "auto",
            "--permission-prompts",
            "none",
            "--settings",
            '{"permissions":{"denyInsteadOfPrompting":true,"blockWritesOutsideWorkingDirectories":true},"sandbox":{"enabled":true,"failIfUnavailable":true,"allowUnsandboxedCommands":false,"network":{"strictAllowlist":true,"allowedDomains":["github.com","*.github.com","*.githubusercontent.com","pypi.org","files.pythonhosted.org"],"allowMachLookup":["com.apple.trustd.agent"]}}}',
        ),
    ),
    "backends.codex.args": (
        (),
        (
            "exec", "--model", "gpt-6.1-sol", "--json", "--color", "never",
            "--sandbox", "workspace-write", "-c", 'approval_policy="never"',
            "-c", 'model_reasoning_effort="high"', "--ephemeral",
        ),
        (
            "exec", "--model", "gpt-6.1-sol", "--json", "--color", "never",
            "--sandbox", "workspace-write", "-c", 'approval_policy="never"',
            "-c", 'model_reasoning_effort="high"', "-c", "project_doc_max_bytes=262144",
            "--ephemeral",
        ),
    ),
}


def is_retired_policy_list_default(path: str, local: Any) -> bool:
    retired = POLICY_RETIRED_LIST_DEFAULTS.get(path)
    if retired is None or not isinstance(local, list):
        return False
    return tuple(str(item) for item in local) in retired


def claude_settings_from_argv(argv: list[str]) -> dict[str, Any]:
    """The inline JSON of ``--settings`` in a claude argv; {} for a file path or none."""
    for index, item in enumerate(argv[:-1]):
        if item == "--settings":
            try:
                data = json.loads(argv[index + 1])
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}
    return {}


def claude_permission_mode_report(
    backend: dict[str, Any],
    version: tuple[int, int, int] | None,
    *,
    platform: str | None = None,
    which: Any = None,
) -> dict[str, Any]:
    """How the claude backend answers permission checks, for quota doctor.

    ``ok`` is False when the policy asks for the no-prompt mode and the local
    Claude Code is too old to know it (a run stops on an unknown option), or when
    its settings turn on the Bash sandbox on Linux without bubblewrap or socat
    (failIfUnavailable stops every run). The retired bypass flag and a custom argv
    are reported and pass, they are the project's choice.
    """
    argv = [str(item) for item in backend.get("args", []) or []]
    argv += [str(item) for item in backend.get("extra_args", []) or []]
    found = ".".join(str(part) for part in version) if version else None
    need = ".".join(str(part) for part in CLAUDE_HEADLESS_PERMISSIONS_MIN_VERSION)
    report: dict[str, Any] = {
        "mode": "custom",
        "ok": True,
        "cli_version": found,
        "min_version": need,
        "why": "",
    }
    bypass = CLAUDE_RETIRED_SKIP_PERMISSIONS_FLAG in argv or any(
        argv[i] == "--permission-mode" and argv[i + 1] == "bypassPermissions"
        for i in range(len(argv) - 1)
    )
    if "--permission-prompts" in argv:
        report["mode"] = "auto-no-prompts"
        if version is None:
            report["why"] = (
                "auto mode, anything that would prompt is denied; Claude Code "
                f"version unknown, this mode needs {need} or newer"
            )
        elif version < CLAUDE_HEADLESS_PERMISSIONS_MIN_VERSION:
            report["ok"] = False
            report["why"] = (
                f"Claude Code {found} is older than {need}: the no-prompt mode "
                "(--permission-prompts none, permissions.denyInsteadOfPrompting) "
                "is not available here and claude runs stop; update claude on "
                "this host"
            )
        else:
            report["why"] = (
                "auto mode, anything that would prompt is denied, Write and Edit "
                f"outside the worktree are refused (Claude Code {found})"
            )
        sandbox = claude_settings_from_argv(argv).get("sandbox")
        sandbox = sandbox if isinstance(sandbox, dict) else {}
        report["sandbox"] = bool(sandbox.get("enabled"))
        if report["sandbox"]:
            network = sandbox.get("network")
            domains = network.get("allowedDomains") if isinstance(network, dict) else None
            count = len(domains) if isinstance(domains, list) else 0
            report["why"] += f"; Bash runs in the sandbox, network to {count} allowed domain(s)"
            stacks = backend.get(CLAUDE_SANDBOX_STACKS_APPLIED_KEY)
            if isinstance(stacks, list):
                report["sandbox_stacks"] = list(stacks)
                if stacks:
                    joined = ", ".join(stacks)
                    report["why"] += f", stack additions: {joined}"
            host = platform if platform is not None else sys.platform
            if host.startswith("linux"):
                if which is None:
                    import shutil

                    which = shutil.which
                missing = [name for name in CLAUDE_SANDBOX_LINUX_BINARIES if which(name) is None]
                if missing:
                    report["ok"] = False
                    report["why"] = (
                        "the Bash sandbox is on but "
                        + ", ".join(missing)
                        + " is missing on this Linux host: failIfUnavailable stops "
                        "every claude run; install bubblewrap and socat"
                    )
    elif bypass:
        report["mode"] = "bypass"
        report["why"] = (
            "bypass: every tool call is approved (--dangerously-skip-permissions); "
            "the bundled policy uses auto mode with no prompts, "
            "and `ai-task policy sync` replaces the old bundled value"
        )
        if version is not None and version < CLAUDE_HEADLESS_PERMISSIONS_MIN_VERSION:
            report["why"] += f"; Claude Code {found} needs {need} for that mode"
    else:
        report["why"] = "custom argv: neither the no-prompt mode nor the bypass flag"
    return report


# Replace Claude argv from the template; routing lists stay project-owned.
POLICY_TEMPLATE_LIST_PATHS = frozenset(
    {
        "backends.claude.args",
    }
)


# Recipe lists: order and composition are the meaning, so sync treats
# the whole list as one value. A local list that differs from bundled is an override:
# sync never appends into it and --force never replaces it; both report it as kept.
# To take the bundled recipe, delete the key (or the profile table) and run sync.
# POLICY_TEMPLATE_LIST_PATHS wins over this rule (backends.claude.args stays template-wins).
POLICY_RECIPE_LIST_NOTE = (
    "recipe list: local override kept whole (sync never appends or replaces it; "
    "delete the key to take the bundled one)"
)


def is_policy_recipe_list_path(path: str) -> bool:
    if path in {
        "routing.default_order", "routing.simple_order", "routing.limit_fallback_order",
        "routing.disabled_backends",
    }:
        return True
    if path in POLICY_TEMPLATE_LIST_PATHS:
        return False
    parts = path.split(".")
    if len(parts) == 4 and parts[:2] == ["verify", "profiles"]:
        return parts[3] == "commands"
    if len(parts) == 3 and parts[0] == "backends":
        return parts[2] in ("args", "extra_args")
    return False


# Model override. backends.claude.args is template-wins, so a repository
# that keeps another model by owner decision sets model_override in the backend table
# instead of editing args, with model_override_reason and model_override_since:
#   [backends.claude]
#   model_override = "opus"
#   model_override_reason = "owner moved coding runs to Opus"
#   model_override_since = 2026-10-22
# read_policy builds the run argv from the bundled args with only the --model value
# replaced, so effort, --print and flags the template adds later keep coming from the
# template. These keys exist only locally, so sync keeps them in both modes, --force
# included. Sync writes model_override_bundled itself: the bundled model it last
# checked the override against, so a template model change is warned about instead of
# going stale. Deleting model_override returns the bundled model; the other
# model_override_* keys are then ignored.
MODEL_OVERRIDE_KEY = "model_override"
MODEL_OVERRIDE_REASON_KEY = "model_override_reason"
MODEL_OVERRIDE_SINCE_KEY = "model_override_since"
MODEL_OVERRIDE_BUNDLED_KEY = "model_override_bundled"
MODEL_OVERRIDE_KEYS = frozenset(
    {
        MODEL_OVERRIDE_KEY,
        MODEL_OVERRIDE_REASON_KEY,
        MODEL_OVERRIDE_SINCE_KEY,
        MODEL_OVERRIDE_BUNDLED_KEY,
    }
)


def model_override_since_text(value: Any) -> str | None:
    """ISO date of model_override_since (a TOML date or a YYYY-MM-DD string)."""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip()).isoformat()
        except ValueError:
            return None
    return None


def model_override_errors(policy: dict[str, Any]) -> list[str]:
    """One line per backend whose model_override is incomplete, naming the missing field."""
    errors: list[str] = []
    backends = policy.get("backends", {})
    if not isinstance(backends, dict):
        return errors
    for name, config in backends.items():
        if not isinstance(config, dict) or MODEL_OVERRIDE_KEY not in config:
            continue
        prefix = f"[backends.{name}] {MODEL_OVERRIDE_KEY}"
        model = config[MODEL_OVERRIDE_KEY]
        if not isinstance(model, str) or not model.strip():
            errors.append(f'{prefix} must name a model, for example "opus"')
        reason = config.get(MODEL_OVERRIDE_REASON_KEY)
        if not isinstance(reason, str) or not reason.strip():
            errors.append(
                f"{prefix} needs {MODEL_OVERRIDE_REASON_KEY}: why this repository "
                "keeps its own model"
            )
        since = config.get(MODEL_OVERRIDE_SINCE_KEY)
        if since is None or since == "":
            errors.append(
                f"{prefix} needs {MODEL_OVERRIDE_SINCE_KEY}: the date it was set, "
                "for example 2026-10-22"
            )
        elif model_override_since_text(since) is None:
            errors.append(
                f"{prefix}: {MODEL_OVERRIDE_SINCE_KEY} = {since!r} is not a date "
                "(YYYY-MM-DD)"
            )
    return errors


def args_model(args: Any) -> str | None:
    """The value after --model (or of --model=...) in a backend args list."""
    if not isinstance(args, list):
        return None
    items = [str(arg) for arg in args]
    for index, arg in enumerate(items):
        if arg == "--model" and index + 1 < len(items):
            return items[index + 1]
        if arg.startswith("--model="):
            return arg.split("=", 1)[1]
    return None


def args_with_model(args: Any, model: str) -> list[str]:
    """args with the --model value replaced; --model is prepended when args name none."""
    items = [str(arg) for arg in args] if isinstance(args, list) else []
    for index, arg in enumerate(items):
        if arg == "--model" and index + 1 < len(items):
            items[index + 1] = model
            return items
        if arg.startswith("--model="):
            items[index] = f"--model={model}"
            return items
    return ["--model", model, *items]


def apply_model_overrides(policy: dict[str, Any]) -> dict[str, Any]:
    """Rewrite in place the args of every backend with a model_override (run argv)."""
    backends = policy.get("backends", {})
    if not isinstance(backends, dict):
        return policy
    for config in backends.values():
        if isinstance(config, dict) and config.get(MODEL_OVERRIDE_KEY):
            config["args"] = args_with_model(
                config.get("args", []), str(config[MODEL_OVERRIDE_KEY])
            )
    return policy


@dataclass(frozen=True)
class ModelOverrideSync:
    drifts: list[PolicyDriftEntry]
    changes: list[str]
    warnings: list[str]


def sync_model_overrides(
    template: dict[str, Any],
    local: dict[str, Any],
    merged: dict[str, Any],
) -> ModelOverrideSync:
    """Report each model_override on sync and record the bundled model it was checked
    against in merged (model_override_bundled). Warn when that bundled model changed."""
    drifts: list[PolicyDriftEntry] = []
    changes: list[str] = []
    warnings: list[str] = []
    local_backends = local.get("backends", {})
    if not isinstance(local_backends, dict):
        return ModelOverrideSync(drifts, changes, warnings)
    template_backends = template.get("backends", {})
    for name, config in local_backends.items():
        if not isinstance(config, dict) or not config.get(MODEL_OVERRIDE_KEY):
            continue
        override = str(config[MODEL_OVERRIDE_KEY])
        since = model_override_since_text(config.get(MODEL_OVERRIDE_SINCE_KEY))
        reason = str(config.get(MODEL_OVERRIDE_REASON_KEY, ""))
        bundled_backend = (
            template_backends.get(name, {})
            if isinstance(template_backends, dict)
            else {}
        )
        bundled = args_model(
            bundled_backend.get("args") if isinstance(bundled_backend, dict) else None
        )
        path = f"backends.{name}.{MODEL_OVERRIDE_KEY}"
        drifts.append(
            PolicyDriftEntry(
                path=path,
                local=override,
                bundled=bundled or "",
                note=(
                    f"local model {override} since {since} ({reason}), "
                    f"bundled {bundled or 'none'}"
                ),
            )
        )
        if bundled is None:
            continue
        recorded = config.get(MODEL_OVERRIDE_BUNDLED_KEY)
        if recorded == bundled:
            continue
        record_path = f"backends.{name}.{MODEL_OVERRIDE_BUNDLED_KEY}"
        if recorded is None:
            changes.append(f"add {record_path}")
        else:
            warnings.append(
                f"the bundled template changed the {name} model from {recorded} to "
                f"{bundled}, while this repository keeps {MODEL_OVERRIDE_KEY} = "
                f"{override} (since {since}: {reason}). Check that the override still "
                f"holds, or delete {MODEL_OVERRIDE_KEY} to run on {bundled}."
            )
            changes.append(f"update {record_path}: {recorded!r} -> {bundled!r}")
        merged_backend = merged.get("backends", {}).get(name)
        if isinstance(merged_backend, dict):
            merged_backend[MODEL_OVERRIDE_BUNDLED_KEY] = bundled
    return ModelOverrideSync(drifts, changes, warnings)


POLICY_SYNC_UPDATE_RE = re.compile(r"^update (.+): (.+) -> (.+)$")


POLICY_SYNC_APPEND_RE = re.compile(r"^append (.+): (.+)$")


POLICY_SYNC_ADD_RE = re.compile(r"^add (.+)$")


def load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if tomllib is None:
        die("Python 3.11+ is required to read TOML policies")
    with path.open("rb") as f:
        return tomllib.load(f)


def loads_policy_toml(text: str) -> dict[str, Any]:
    if tomllib is None:
        die("Python 3.11+ is required to read TOML policies")
    return tomllib.loads(text)


def bundled_template_policy(default_verify_profile: str = "none") -> dict[str, Any]:
    return loads_policy_toml(
        default_policy(default_verify_profile=default_verify_profile)
    )


def format_toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def format_toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        return format_toml_string(value)
    if isinstance(value, (dt.date, dt.time)):
        # A bare TOML date such as model_override_since = 2026-10-22.
        return value.isoformat()
    die(f"unsupported policy scalar type: {type(value)!r}")
    return ""


def format_toml_array(values: list[Any]) -> str:
    if not values:
        return "[]"
    if all(isinstance(item, str) for item in values):
        lines = ["["]
        for item in values:
            lines.append(f"  {format_toml_string(item)},")
        lines.append("]")
        return "\n".join(lines)
    return json.dumps(values)


def render_dict_table(table_path: str, data: dict[str, Any]) -> list[str]:
    lines = [f"[{table_path}]", ""]
    subtables: list[tuple[str, dict[str, Any]]] = []
    for key, value in data.items():
        if isinstance(value, dict):
            subtables.append((f"{table_path}.{key}", value))
        elif isinstance(value, list):
            formatted = format_toml_array(value)
            if "\n" in formatted:
                lines.append(f"{key} = {formatted}")
            else:
                lines.append(f"{key} = {formatted}")
        else:
            lines.append(f"{key} = {format_toml_scalar(value)}")
    lines.append("")
    for subpath, subdata in subtables:
        lines.extend(render_dict_table(subpath, subdata))
    return lines


def render_simple_section(name: str, data: dict[str, Any]) -> list[str]:
    lines = [f"[{name}]", ""]
    for key, value in data.items():
        if isinstance(value, list):
            formatted = format_toml_array(value)
            if "\n" in formatted:
                lines.append(f"{key} = {formatted}")
            else:
                lines.append(f"{key} = {formatted}")
        elif isinstance(value, dict):
            die(f"unexpected nested dict in simple section {name}.{key}")
        else:
            lines.append(f"{key} = {format_toml_scalar(value)}")
    lines.append("")
    return lines


def render_verify_section(verify: dict[str, Any]) -> list[str]:
    lines = ["[verify]", ""]
    profiles = verify.get("profiles", {})
    for key, value in verify.items():
        if key == "profiles":
            continue
        lines.append(f"{key} = {format_toml_scalar(value)}")
    lines.append("")
    for name, profile in profiles.items():
        lines.extend(render_dict_table(f"verify.profiles.{name}", profile))
    return lines


def render_backends_section(backends: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for name, backend in backends.items():
        lines.extend(render_dict_table(f"backends.{name}", backend))
    return lines


def render_policy_toml(data: dict[str, Any]) -> str:
    lines = ["# ai-task backend and orchestration policy", ""]
    ordered = list(POLICY_TOP_SECTION_ORDER) + [
        key for key in data if key not in POLICY_TOP_SECTION_ORDER
    ]
    seen: set[str] = set()
    for section in ordered:
        if section not in data or section in seen:
            continue
        seen.add(section)
        payload = data[section]
        if section == "verify":
            lines.extend(render_verify_section(payload))
        elif section == "backends":
            lines.extend(render_backends_section(payload))
        elif section in POLICY_NESTED_TABLE_SECTIONS and isinstance(payload, dict):
            lines.extend(render_dict_table(section, payload))
        elif isinstance(payload, dict):
            lines.extend(render_simple_section(section, payload))
        else:
            die(f"unsupported policy section type: {section}")
    return "\n".join(lines).rstrip() + "\n"


def merge_policy_nodes(
    template: Any,
    local: Any,
    *,
    path: str,
    force: bool = False,
) -> tuple[Any, list[str]]:
    if path in POLICY_LOCAL_CHOICE_PATHS and local is not None:
        return local, []
    if isinstance(template, dict) and isinstance(local, dict):
        return merge_policy_dicts(template, local, path=path, force=force)
    if isinstance(template, dict):
        return json.loads(json.dumps(template)), [f"add {path}"]
    if isinstance(template, list) and isinstance(local, list):
        if is_retired_policy_list_default(path, local) and local != template:
            return list(template), [f"update {path}: {local!r} -> {template!r}"]
        if is_policy_recipe_list_path(path):
            return list(local), []
        if force or path in POLICY_TEMPLATE_LIST_PATHS:
            if local != template:
                return list(template), [f"update {path}: {local!r} -> {template!r}"]
            return list(local), []
        list_key = path.rsplit(".", 1)[-1]
        if list_key in POLICY_APPEND_LIST_KEYS:
            merged = list(local)
            changes: list[str] = []
            for item in template:
                if item not in merged:
                    merged.append(item)
                    changes.append(f"append {path}: {item!r}")
            return merged, changes
        if local != template:
            return list(template), [f"update {path}: {local!r} -> {template!r}"]
        return list(local), []
    if force or path in POLICY_TEMPLATE_SCALAR_PATHS or is_retired_policy_default(
        path, local
    ):
        if local != template:
            return template, [f"update {path}: {local!r} -> {template!r}"]
        return local, []
    if local is not None:
        return local, []
    return template, [f"add {path}"]


def merge_policy_dicts(
    template: dict[str, Any],
    local: dict[str, Any],
    *,
    path: str = "",
    force: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    result: dict[str, Any] = {}
    changes: list[str] = []
    # upgrading an existing policy must not change its chosen vendor.
    # New repositories get host inference; existing ones opt in explicitly.
    if path == "routing" and "default_source" in template and "default_source" not in local:
        local = {
            **local, "default_source": "policy",
            "agent_map": {"codex": ["cursor_codex"], **local.get("agent_map", {})},
        }
        changes.append('add routing.default_source: "policy" (preserve existing routing)')
        changes.append("add routing.agent_map.codex: preserve legacy Cursor alias")
    keys = list(local.keys())
    for key in template:
        if key not in keys:
            keys.append(key)
    for key in keys:
        sub_path = f"{path}.{key}" if path else key
        if key not in template:
            # deepcopy, not a JSON round trip: local-only keys may hold TOML dates.
            result[key] = copy.deepcopy(local[key])
            continue
        if key not in local:
            result[key] = json.loads(json.dumps(template[key]))
            changes.append(f"add {sub_path}")
            continue
        merged, sub_changes = merge_policy_nodes(
            template[key], local[key], path=sub_path, force=force
        )
        result[key] = merged
        changes.extend(sub_changes)
    return result, changes


@dataclass(frozen=True)
class PolicyDriftEntry:
    path: str
    local: Any
    bundled: Any
    note: str = ""


def format_policy_display_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False) if value else "[]"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return repr(value)


def _parse_sync_repr(value: str) -> Any:
    try:
        return ast.literal_eval(value.strip())
    except (SyntaxError, ValueError):
        return value.strip()


def collect_policy_drift(
    template: Any,
    local: Any,
    *,
    path: str = "",
    force: bool = False,
) -> list[PolicyDriftEntry]:
    """Paths where local differs from bundled template but merge keeps local (informational).

    With force, only what --force still keeps: local-only keys and overridden recipe lists.
    """
    if force:
        return collect_local_only_policy_entries(
            local, template, path=path
        ) + collect_recipe_overrides(template, local, path=path)
    drifts: list[PolicyDriftEntry] = []
    if isinstance(template, dict) and isinstance(local, dict):
        for key in template:
            if key not in local:
                continue
            sub_path = f"{path}.{key}" if path else key
            drifts.extend(
                collect_policy_drift(template[key], local[key], path=sub_path)
            )
        return drifts
    if isinstance(template, list) and isinstance(local, list):
        if path in POLICY_TEMPLATE_LIST_PATHS or is_retired_policy_list_default(path, local):
            return drifts
        if is_policy_recipe_list_path(path):
            return collect_recipe_overrides(template, local, path=path)
        list_key = path.rsplit(".", 1)[-1]
        if list_key in POLICY_APPEND_LIST_KEYS:
            extra = [item for item in local if item not in template]
            if extra:
                drifts.append(
                    PolicyDriftEntry(
                        path=path,
                        local=local,
                        bundled=template,
                        note="local has extra items; sync only appends missing bundled entries",
                    )
                )
            return drifts
        if local != template:
            drifts.append(PolicyDriftEntry(path=path, local=local, bundled=template))
        return drifts
    if path in POLICY_TEMPLATE_SCALAR_PATHS or is_retired_policy_default(path, local):
        return drifts
    if local != template:
        drifts.append(PolicyDriftEntry(path=path, local=local, bundled=template))
    return drifts


def collect_recipe_overrides(
    template: Any,
    local: Any,
    *,
    path: str = "",
) -> list[PolicyDriftEntry]:
    """Recipe lists where local differs from bundled (kept by sync, with or without --force)."""
    if isinstance(template, dict) and isinstance(local, dict):
        drifts: list[PolicyDriftEntry] = []
        for key in template:
            if key in local:
                sub_path = f"{path}.{key}" if path else key
                drifts.extend(
                    collect_recipe_overrides(template[key], local[key], path=sub_path)
                )
        return drifts
    if (
        isinstance(template, list)
        and isinstance(local, list)
        and is_policy_recipe_list_path(path)
        and not is_retired_policy_list_default(path, local)
        and local != template
    ):
        return [
            PolicyDriftEntry(
                path=path, local=local, bundled=template, note=POLICY_RECIPE_LIST_NOTE
            )
        ]
    return []


def collect_local_only_policy_entries(
    local: Any,
    template: Any,
    *,
    path: str = "",
) -> list[PolicyDriftEntry]:
    """Local keys absent from bundled template (--force sync keeps these)."""
    drifts: list[PolicyDriftEntry] = []
    if isinstance(local, dict) and isinstance(template, dict):
        for key in local:
            sub_path = f"{path}.{key}" if path else key
            if key in MODEL_OVERRIDE_KEYS and path.startswith("backends."):
                continue  # reported as one line by sync_model_overrides
            if key not in template:
                drifts.append(
                    PolicyDriftEntry(
                        path=sub_path,
                        local=local[key],
                        bundled="",
                        note="local-only; not in bundled template (kept on --force sync)",
                    )
                )
            else:
                drifts.extend(
                    collect_local_only_policy_entries(
                        local[key], template[key], path=sub_path
                    )
                )
        return drifts
    return drifts


def policy_sync_color(text: str, *, kind: str) -> str:
    if not sys.stdout.isatty():
        return text
    if kind == "apply":
        return f"\033[32m{text}\033[0m"
    if kind == "drift":
        return f"\033[33m{text}\033[0m"
    return text


def print_policy_value_pair(
    path: str,
    local: Any,
    bundled: Any,
    *,
    kind: str,
    note: str = "",
    bundled_suffix: str = "",
) -> None:
    print(policy_sync_color(f"  {path}", kind=kind))
    print(
        policy_sync_color(
            f"    local:   {format_policy_display_value(local)}", kind=kind
        )
    )
    bundled_line = format_policy_display_value(bundled)
    if bundled_suffix:
        bundled_line = f"{bundled_line}  {bundled_suffix}"
    print(policy_sync_color(f"    bundled: {bundled_line}", kind=kind))
    if note:
        print(policy_sync_color(f"    note:    {note}", kind=kind))
    print()


def print_policy_sync_change(change: str) -> None:
    update = POLICY_SYNC_UPDATE_RE.match(change)
    if update:
        path, local_raw, bundled_raw = update.groups()
        print_policy_value_pair(
            path,
            _parse_sync_repr(local_raw),
            _parse_sync_repr(bundled_raw),
            kind="apply",
            bundled_suffix="(will apply)",
        )
        return
    append = POLICY_SYNC_APPEND_RE.match(change)
    if append:
        path, item_raw = append.groups()
        print(policy_sync_color(f"  {path}", kind="apply"))
        print(
            policy_sync_color(
                f"    bundled adds: {_parse_sync_repr(item_raw)!r}  (will append)",
                kind="apply",
            )
        )
        print()
        return
    add = POLICY_SYNC_ADD_RE.match(change)
    if add:
        print(policy_sync_color(f"  + {add.group(1)}", kind="apply"))
        print()
        return
    print(policy_sync_color(f"- {change}", kind="apply"))


def print_policy_sync_report(
    *,
    policy_path: Path,
    changes: list[str],
    drifts: list[PolicyDriftEntry],
    dry_run: bool,
    force: bool = False,
    warnings: list[str] | None = None,
) -> None:
    mode = " (force)" if force else ""
    if changes:
        verb = "Would apply" if dry_run else "Applied"
        print(f"{verb} {len(changes)} bundled change(s) to {policy_path}{mode}:")
        print()
        for change in changes:
            print_policy_sync_change(change)
    elif dry_run:
        print("Policy already in sync (no bundled updates to apply).")
    else:
        print("Policy already in sync.")
    if drifts:
        heading = (
            "Kept on force sync (local-only keys and overridden recipe lists):"
            if force
            else "Local differs from bundled (kept as-is, not synced):"
        )
        print(heading)
        print()
        for entry in drifts:
            if entry.path.endswith(f".{MODEL_OVERRIDE_KEY}"):
                print(policy_sync_color(f"  {entry.path}", kind="drift"))
                print(policy_sync_color(f"    {entry.note}", kind="drift"))
                print()
                continue
            if entry.bundled == "" and entry.note:
                print(policy_sync_color(f"  {entry.path}", kind="drift"))
                print(
                    policy_sync_color(
                        f"    local: {format_policy_display_value(entry.local)}",
                        kind="drift",
                    )
                )
                print(policy_sync_color(f"    note:  {entry.note}", kind="drift"))
                print()
                continue
            print_policy_value_pair(
                entry.path,
                entry.local,
                entry.bundled,
                kind="drift",
                note=entry.note,
            )
    for warning in warnings or []:
        print(policy_sync_color(f"Warning: {warning}", kind="drift"))
        print()


def _policy_limit_patterns_toml() -> str:
    return format_toml_array(DEFAULT_LIMIT_PATTERNS)


def _policy_auth_patterns_toml() -> str:
    return format_toml_array(DEFAULT_AUTH_PATTERNS)


def default_policy(*, default_verify_profile: str = "none") -> str:
    profile = default_verify_profile.strip() or "none"
    limit_patterns = _policy_limit_patterns_toml()
    auth_patterns = _policy_auth_patterns_toml()
    claude_extra_args = format_toml_array(CLAUDE_HEADLESS_PERMISSION_ARGS)
    return f"""# ai-task backend and orchestration policy

[batch]
default_size = 1
max_size = 5
auto_target = 5

[priority]
default = "P2"
order = ["P0", "P1", "P2", "P3"]

[scenario]
# Delivery scenario handshake. When `default` names a
# valid scenario id (wave_full, wave_monolithic, wave_monolithic_sequential,
# single_next, isolated_worktree_batch), `scenario check` passes without a fresh
# delivery_scenario:* decision — teamlead announces the default and proceeds
# instead of running the full picker. Empty = unset (picker required). A fresh
# explicit delivery_scenario:* decision always wins over the default.
default = ""
# Days before a delivery_scenario:* decision is considered stale (CLI
# --max-stale-days overrides per call).
stale_days = 7

[executor]
# How teamlead waves execute tasks. "headless" launches CLI
# worker processes (claude -p, codex exec). "in_session" runs every task in a fresh
# subagent of the teamlead's own session through the claude_subagent or
# codex_subagent backend, so delivery does not depend on the headless CLI token.
# Before a batch of more than one wave or more than ask_above_tasks tasks the
# teamlead asks which mode to use, offering `default` as the recommended answer,
# unless the request names the mode. `ai-task executor` applies this rule.
default = "headless"
ask_above_tasks = 3
# An in-session run that no `worker-done` reports within this many seconds is
# reaped to needs_recovery (0 = never).
in_session_timeout_seconds = 7200

[review]
high_priority = ["P0", "P1"]
require_for_risk_keywords = true
require_for_broad_diffs = true
broad_diff_file_threshold = 8
ask_before_weaker_fallback_for_risky_tasks = true

[review.codex]
# Second review vendor. When enabled, `ai-task review` also runs
# `codex exec review` on the run diff and writes its findings into the run
# review-findings.md with Source: codex; the teamlead still records the verdict.
# The command reuses the [backends.codex] argv recipe (no personal config, the
# same instruction budget and trust) whether or not that backend runs tasks, and
# swaps its sandbox for this one. Off by default: a pass spends Codex quota.
enabled = false
sandbox = "read-only"
timeout_seconds = 1200

[notify]
# Telegram finalize notifications. When enabled AND the Claude Code
# Telegram channel is configured (~/.claude/channels/telegram/.env), ai-task
# sends an OUTCOME ping (verify result + verdict + changed files + wave) when a
# run's verdict is recorded — the per-task Stop hook fires before verify/verdict
# exist and cannot. `implement_ping` keeps the per-task implement-done Stop ping
# (the 🔨 ping from hooks/telegram-notify.py): set it false to receive ONLY the
# outcome ping (ai-task then signals the child hook to stand down). No-ops
# silently when creds are absent, enabled = false, or env AI_TASK_NOTIFY_DISABLED
# is set (the test harness sets it so a test run never POSTs fixture pings).
enabled = true
implement_ping = true

[supervision]
# Log-silence threshold for the `stalled` signal (0 = disabled). `stalled` fires
# only when there is no log growth for this long AND the backend pid is not alive
# (or was never recorded); a silent-but-alive run (the normal --print case) is not
# stalled. Default 1800 (30m): tune per repo (very long quiet runs may need 3600+).
stall_timeout_seconds = 1800
# auto_stop_on_stall terminates waited runs after stall_timeout_seconds of no log
# growth; it keys on log growth, not pid, so leave false for silent --print backends.
auto_stop_on_stall = false
blocked_patterns = [
    "workspace trust required",
    "waiting for approval",
    "waiting for your approval",
    "approve this",
    "do you trust",
    "press enter to continue",
    "permission denied",
]

[cooldown]
# After a rate limit, skip that backend until cooldown_until, then probe before reuse.
default_seconds = 1800
probe_enabled = true
probe_timeout_seconds = 90

[cleanup]
# Remove a run's worktree (and its merged branch) when `complete` succeeds.
# Once a run is complete its work is merged, so the worktree is
# disposable and the safe moment to prune is known without asking the operator
# to judge anything. Guarded exactly like `cleanup --remove-worktrees`: a dirty
# working tree or a branch with commits ahead is KEPT and reported, never
# force-removed. Set false to keep every worktree for post-hoc inspection and
# sweep them yourself; `complete --remove-worktree` still removes one on demand.
remove_worktree_on_complete = true

[quota]
# Best-effort Claude subscription quota supervision. Reads quota
# snapshots (five_hour / seven_day windows) to reserve a small budget for control
# turns and plan recovery. If no quota source is configured/fresh, this is inert:
# limit-pattern detection and [cooldown] keep working and status reports quota as
# unavailable. Quota supervision is runtime routing, not a second agent brain.
enabled = true
# Headroom (percent of the window) never spent by routine dispatch — the stop line
# is at used == (100 - reserve_percentage).
reserve_percentage = 5
# Warn (plain status) and treat the window as "near limit" at/above this used %.
near_limit_start_threshold_percentage = 85
# After a window resets, wait this many extra seconds before treating it as usable.
resume_margin_seconds = 60
# Bounded auto-resume retry budget for `wait-runs --resume-on-quota`.
# After a quota/limit pause, the same packet is re-launched at most this many times;
# if Claude is still limited after each reset the run is left waiting_quota and the
# budget is exhausted instead of waking/retrying forever. 0 disables auto-resume.
resume_max_attempts = 3
# The resume target is the LATEST reset among windows at/over the stop line (all
# blocked windows must clear). On each wake the resume time is re-derived from a
# fresh snapshot; a still-blocked window re-arms the wait WITHOUT consuming a
# retry attempt, bounded by this hard wall-clock cap measured from the first
# quota pause. Default 8 days covers a full seven_day window reset;
# past the cap auto-resume stops (budget closed) and the run stays waiting_quota
# for the operator. 0 disables the cap.
resume_max_wait_seconds = 691200
# A snapshot older than this is treated as stale (source unavailable) so routing
# falls back to limit-pattern/cooldown behavior. 0 disables the freshness gate.
max_snapshot_age_seconds = 900
# Headless refresh complements the interactive statusLine source: dispatch checks
# freshness and, when stale/missing, tries configured live-source commands before
# quota admission control decides whether Claude may launch.
refresh_enabled = true
refresh_on_dispatch = true
refresh_timeout_seconds = 10
refresh_sources = ["claude_oauth", "ccquota"]
# `quota doctor` and `quota probe` print when the headless claude.ai sign-in ends
# on Claude Code 2.1.318 or newer, and fail the login check this
# many days before it does. Claude Code itself warns on stderr only 10 days ahead and only
# in text output; two weeks leaves the owner a weekend to log the workers in again.
login_expiry_warn_days = 14
# Refresh the quota source when a DETACHED run finalizes, before its completion
# telemetry takes the post snapshot. Off by default: it costs one
# live-source call per finished run. It never blocks work (the run is already
# over) — turn it on for a calibration window so detached waves produce
# high-confidence quota deltas instead of `partial` samples with a stale post
# snapshot. Foreground runs are unaffected; their post snapshot is taken inline.
refresh_at_finalize = false
# Minimum high-confidence telemetry samples before `quota calibrate --apply` will
# rewrite [quota.reservations]. Calibration is advisory: `quota stats`
# and `calibrate --dry-run` work with any amount of data, but applying is refused
# below this floor so one unusual batch cannot move the reserved budget.
calibration_min_samples = 100
# Never recommend a reservation below this percent, so a few tiny-delta samples
# cannot drive the reserved budget toward zero and overbook the window.
calibration_floor_percentage = 3
# Snapshot file written by the statusLine helper, relative to the repo root (under
# the gitignored .ai-task/). Absolute paths are honored as-is. See docs/ai-task.md.
snapshot_path = ".ai-task/quota-snapshot.json"
# Telemetry JSONL appended per Claude run. Relative paths resolve
# under the repo root (per-repo isolation, the default); an absolute path (~
# expanded) is honored as-is so several repos can pool samples into one shared
# file and `quota calibrate` can reach its sample minimum across repos.
# Each sample carries repo_id so merged data stays attributable.
telemetry_path = ".ai-task/quota-telemetry.jsonl"

[quota.reservations]
# Pessimistic per-task upper-bound reservations by backlog Size: (percent of the
# tightest window). unknown_percentage covers missing/unrecognized Size. These are
# estimates, not exact cost prediction; later telemetry can recommend new values.
s_percentage = 5
m_percentage = 8
l_percentage = 10
unknown_percentage = 5

[verify]
# Gates before AI review. Commands are stack-specific (ruff/pytest = Python only). See docs/ai-task-verify.md.
# Pipefail contract: commands run via bash/zsh `-o pipefail`, so a failing stage of a
# pipe written in the profile command itself fails the step (`npm run build 2>&1 | tail -5`
# cannot mask a build failure). Caveat: pipefail does NOT reach pipes nested inside a
# shell wrapper — `bash -c 'cd web && npm run build 2>&1 | tail -5'` starts an inner
# shell without pipefail, and the inner pipe masks failures again.
# Convention: keep profile commands flat (`cd web && npm run build 2>&1 | tail -5`);
# if a wrapper is unavoidable, start the inner command with `set -o pipefail;`.
# verify flags nested `bash -c`/`sh -c`/`zsh -c` wrappers that contain a pipe:
# nested_shell_pipe = "warn" prints a warning; "fail" refuses to run the profile.
enabled = true
default_profile = "{profile}"
require_before_review = true
allow_skip = false
nested_shell_pipe = "warn"

[verify.profiles.python-full]
description = "Python: lint + tests"
commands = ["ruff check .", "pytest -q"]

[verify.profiles.python-quick]
description = "Python: lint only"
commands = ["ruff check ."]

[verify.profiles.node-full]
description = "Node/TS: lint + tests (adjust scripts to your package.json)"
commands = ["npm run lint", "npm test"]

[verify.profiles.node-quick]
description = "Node/TS: lint only"
commands = ["npm run lint"]

[verify.profiles.dotnet-full]
description = ".NET: build + test (run from repo or solution directory)"
commands = ["dotnet build --no-restore", "dotnet test --no-build"]

[verify.profiles.dotnet-quick]
description = ".NET: build only"
commands = ["dotnet build --no-restore"]

[verify.profiles.go-full]
description = "Go: vet + test (module root)"
commands = ["go vet ./...", "go test ./..."]

[verify.profiles.go-quick]
description = "Go: vet only"
commands = ["go vet ./..."]

[verify.profiles.web-e2e]
description = "Web/UI: Playwright E2E (edit commands to match package.json)"
commands = ["npx playwright test"]

[verify.profiles.web-e2e-quick]
description = "Web/UI: smoke E2E when a script exists"
commands = ["npm run test:e2e"]

[verify.profiles.docker-build]
description = "Containers: image builds (uncomment hadolint when installed)"
commands = ["docker build -q ."]
# commands = ["hadolint Dockerfile", "docker build -q ."]

[verify.profiles.compose-config]
description = "Containers: compose file validates"
commands = ["docker compose config -q"]

[verify.profiles.terraform-validate]
description = "IaC: terraform fmt + validate (run in the module directory)"
commands = ["terraform fmt -check", "terraform validate"]

[verify.profiles.helm-lint]
description = "Helm: chart lints (run in the chart directory; uncomment kube-score when installed)"
commands = ["helm lint ."]
# commands = ["helm lint .", "helm template . | kube-score score -"]

# mixed python+node repo: copy and edit
# [verify.profiles.fullstack-example]
# description = "Composite: python backend lint + node frontend lint"
# commands = ["ruff check .", "cd web && npm run lint"]

# Short aliases for Python-only repos (same commands as python-*)
[verify.profiles.full]
description = "Alias of python-full"
commands = ["ruff check .", "pytest -q"]

[verify.profiles.quick]
description = "Alias of python-quick"
commands = ["ruff check ."]

[verify.profiles.none]
description = "No commands (explicit opt-out; verify passes with empty report)"
commands = []

[parallel]
# Inter-task parallelism (ai-task parallel-plan). Intra-task: vendor subagents in packet.
enabled = true
max_concurrent = 3
require_worktrees = true
auto_dispatch = true
allow_cross_layer = true
allow_mixed_size = true
sequential_on_any_p0_risk = true
sequential_on_broad_scope = true
# W2 overlap-gate warn threshold (teamlead skill): tasks touching the
# most-contended predicted file ÷ batch size. Calibrate per repo from
# parallelism-ROI reflections (retro); local value wins on policy sync.
overlap_warn_share = 0.3

[decisions]
# Append anomaly stubs to decisions.jsonl (verify fail, retry, limit fallback, verdict rework, --confirm-risk).
auto_log_anomalies = true

[scope_guard]
# Out-of-scope backlog edit guard. `run` snapshots the task files
# below at launch (run dir scope-pre/); finalize diffs them against the run
# working tree and records every edit outside the run's OWN task block (foreign
# task blocks edited/removed, new tasks or sections appended, preamble changes)
# as out_of_scope_edits on the run — surfaced by status --json and plain-status
# operator alerts. mode = "warn" only reports; mode = "require_ack" additionally
# blocks `verdict approve` / `complete` until the operator reverts the edits or
# logs an acknowledgment decision row:
#   ai-task decision log --phase verdict --choice scope_ack \
#     --task-ids <TASK-ID> --run-ids <run-id> --reason "why the edits stay"
# Launch also hashes the sensitive control files (.gitmodules,
# .ai-task/config.toml, .ai-task/policies/*.toml); finalize flags changes as
# sensitive_file_edits — informational in both modes.
# Posture: warn is the solo-operator default; set mode = "require_ack" when
# backlog text can come from someone other than the operator (second operator,
# shared BACKLOG.md) — see docs/ai-task.md «Untrusted backlog input».
enabled = true
mode = "warn"
# Task files to snapshot and diff, relative to the run working tree.
task_files = ["BACKLOG.md"]

[handoff]
# Per-task report, written on demand: only when there is something to keep
# beyond the Progress line, CHANGELOG and the commit. Relative to repo root; {{task_id}}
# is substituted. `complete --require-report` fails closed when it is absent.
task_report_dir = "tasks"
task_report_pattern = "{{task_id}}.md"

[routing]
# Backlog Agent: (auto|claude|cursor|codex|devin|human) — see docs/ai-task.md. Optional agent_map in TOML.
# Agent: auto uses host inference after explicit choices. No silent model switching: a limited or quota-blocked
# run waits (waiting_quota) or reports instead of moving the task to another vendor.
# Fallback is opt-in — set limit_fallback_order = ["cursor_auto"] to re-enable it.
# Pick a backend explicitly per run with --backend; cursor_codex stays opt-in
# (Agent: cursor or --backend). Pin one backend for a whole wave with
# `ai-task pin <name>` (lives in state.json, overrides Agent:, kills fallback).
default_order = ["claude"]
simple_order = ["claude"]
limit_fallback_order = []
# host: infer Claude/Codex only when the task and project have no explicit choice.
# policy: always use the orders above. Existing policies keep policy mode on sync.
default_source = "host"
disabled_backends = []

[backends.claude]
enabled = true
command = "claude"
# Draws on the Claude subscription quota. A second backend that runs
# claude (a cheaper tier) must declare quota_pool too, or the policy is refused.
quota_pool = "claude"
# Coding agents run on Sonnet at high effort (default, for speed and
# spend); review and verdict stay with the teamlead session. max effort is Opus-only in
# Claude Code. Do not use opus[1m] (1M). policy sync resets args to this template; a
# repository that keeps another model sets model_override with model_override_reason
# and model_override_since instead (docs/ai-task.md, Policy sync).
args = ["--model", "sonnet", "--effort", "high", "--print"]
# Permissions: auto mode decides each tool call, and whatever
# would wait on a prompt is denied (--permission-prompts none, 2.1.259). --settings
# adds denyInsteadOfPrompting (2.1.319: the same for subagents) and
# blockWritesOutsideWorkingDirectories (2.1.314: Write, Edit and NotebookEdit refuse
# paths outside the worktree). Needs Claude Code >= 2.1.319; quota doctor says so on
# an older one. The settings travel in argv, not in the worktree's .claude/settings.json:
# the agent can edit that file, and since 2.1.257 it cannot set the mode anyway.
# policy sync replaces the retired ["--dangerously-skip-permissions"] with this list.
extra_args = {claude_extra_args}
stdin_prompt = false
prompt_arg = ""
probe_prompt = "Reply with exactly OK."
reasoning = "high"
workload = "substantial"
limit_patterns = {limit_patterns}
# Credential-dead detection: substrings that mean this backend is
# unauthenticated on THIS host, not that the task failed. A matching attempt does
# not consume the task's failure budget — the backend is marked unusable (with
# `auth_fix` as the operator instruction) and routing falls through to the next
# backend in the chain. Append-only on `policy sync`.
auth_patterns = {auth_patterns}
auth_fix = "resolve any account access restriction, or run `claude login` on this host, or set ANTHROPIC_API_KEY"

[backends.claude.env]
CLAUDE_CODE_DISABLE_1M_CONTEXT = "1"

[backends.cursor_codex]
enabled = true
command = "cursor-agent"
# Pin Codex 5.3 high (latest Codex generation in cursor-agent --list-models; no 5.4+ yet).
args = ["--model", "gpt-5.3-codex-high", "--print", "--trust", "--yolo"]
stdin_prompt = false
prompt_arg = ""
reasoning = "high"
workload = "opt-in-codex"
limit_patterns = {limit_patterns}
auth_patterns = {auth_patterns}
auth_fix = "run `cursor-agent login` (or `agent login`) on this host, or set CURSOR_API_KEY"

[backends.cursor_auto]
enabled = true
command = "cursor-agent"
args = ["--model", "auto", "--print", "--trust", "--yolo"]
stdin_prompt = false
prompt_arg = ""
reasoning = "auto"
workload = "limit-fallback-only"
limit_patterns = {limit_patterns}
auth_patterns = {auth_patterns}
auth_fix = "run `cursor-agent login` (or `agent login`) on this host, or set CURSOR_API_KEY"

[backends.codex]
enabled = true
command = "codex"
quota_pool = "none"
# Needs codex-cli >= 0.131.0, the first release with every flag here (as
# read in the Codex tags: --ephemeral 0.99, --ignore-user-config 0.122, hooks.state
# from -c 0.128, --strict-config and hooks.json beside the user config 0.131);
# checked live with codex exec --help and a worker run on 0.167.1.
# Sandbox writes stay inside the workspace; approval_policy=never makes denied
# operations fail instead of prompting. --ignore-user-config: the personal
# ~/.codex/config.toml (model, effort, MCP servers, plugins, notify, project trust)
# does not change a run; auth still comes from CODEX_HOME. --strict-config stops
# a run on an unknown key in -c or in a project's .codex/config.toml.
# project_doc_max_bytes: Codex loads AGENTS.override.md instead of AGENTS.md and
# cuts project instructions at 32768 bytes by default; 262144 fits the largest
# canon plus override with room to grow (docs/ai-task.md, Native Codex CLI).
args = ["exec", "--model", "gpt-6.1-sol", "--json", "--color", "never", "--sandbox", "workspace-write", "--ignore-user-config", "--strict-config", "-c", 'approval_policy="never"', "-c", 'model_reasoning_effort="high"', "-c", "project_doc_max_bytes=262144", "--ephemeral"]
stdin_prompt = true
prompt_arg = ""
# The hooks of $CODEX_HOME/hooks.json need the trust saved in the
# config the worker ignores; ai-task passes those trust entries, and only those,
# as one -c hooks.state argument.
hook_trust_from_home = true
# Codex writes trust for the repository into the personal config.toml when a
# workspace-write run has none, even with --ignore-user-config; ai-task passes
# trust for the run directory as -c projects so the run leaves that file alone.
trust_run_directory = true
# Shell commands keep uv, pip and npm caches under .ai-task/cache/ of the run
# directory and reach only the GitHub and PyPI domains of the Claude worker (npm
# registry for node, DerivedData and SwiftPM caches writable for Xcode): ai-task
# adds sandbox_workspace_write, features.network_proxy and
# shell_environment_policy as -c arguments at launch. sandbox_stacks = [...]
# replaces stack detection, an empty list turns the stack additions off.
worker_sandbox = true
# The final message is the worker-done report (outcome, final_answer, note),
# held to a JSON schema that ai-task writes into the run directory.
output_schema_arg = "--output-schema"
output_last_message_arg = "--output-last-message"
reasoning = "high"
workload = "substantial"
limit_patterns = {limit_patterns}
auth_patterns = {auth_patterns}
auth_fix = "run `codex login` on this host"

[backends.claude_subagent]
# In-session executor: a fresh Claude Code subagent of the teamlead's
# session does the work. ai-task records the run and launches nothing; the
# teamlead reports the outcome with `ai-task worker-done`. Draws on the Claude
# subscription quota like the claude backend. Opt-in only: --backend or pin.
enabled = true
in_session = true
command = ""
quota_pool = "claude"
reasoning = "host session"
workload = "opt-in"

[backends.codex_subagent]
# In-session executor for a Codex teamlead. Bills the Codex pool,
# never Claude reservations. Opt-in only: --backend or pin.
enabled = true
in_session = true
command = ""
quota_pool = "none"
reasoning = "host session"
workload = "opt-in"

[backends.devin]
# Devin CLI. Opt-in only — Agent: devin or `run --backend devin`;
# never in default auto routing. `swe` resolves to the latest SWE model.
# `-p` is headless print mode; bypass approves every action, like the retired claude --dangerously-skip-permissions
# / cursor --yolo (org-level team settings can still deny).
# --respect-workspace-trust false is required for -p in an untrusted directory —
# headless mode cannot show the trust prompt. Devin bills per ACU; cooldown clears
# on timer (not the sticky Cursor API-pool rule).
enabled = true
command = "devin"
args = [
    "--model", "swe",
    "--permission-mode", "bypass",
    "--respect-workspace-trust", "false",
]
prompt_arg = "-p"
stdin_prompt = false
reasoning = "unset"
workload = "opt-in"
limit_patterns = {limit_patterns}
auth_patterns = {auth_patterns}
auth_fix = "run `devin auth login` on this host"

[analytics]
# Recurrence / sibling-rate signal in `decision analytics`, factual reports,
# and the `ai-task report` dashboard. Counts delivered (- [x]) backlog tasks
# whose block matches a marker below — fixes that re-patch a sibling/regression
# of earlier work instead of generalizing. Complements rework_rate.
# recurrence_warn_rate: warn when the sibling rate >= this fraction (0 disables).
recurrence_warn_rate = 0.5
recurrence_markers = ["sibling of", "regression of", "root cause of", "re-drift"]
# recurrence_backlog = "BACKLOG.md"  # source backlog path, relative to repo root
# Rotated backlog archives (sdlc-backlog-rotate skill) merged by AUDIT readers only
# (recurrence + `ai-task report`); delivery readers (plan/backlog-order/dor)
# stay active-only. Active BACKLOG.md wins on id collision.
# archive_glob = "backlog/archive/BACKLOG-*.md"

[slo]
# Delivery health SLO gates — violations surface in `decision analytics` output.
# Thresholds are fractions (0.0–1.0) or integer counts; 0 disables a gate.
# max_rework_rate = 0.5
# max_implicit_retry_rate = 0.5
# max_runs_without_verdict = 5
# max_failed_runs = 3
"""


def cleanup_config(policy: dict[str, Any]) -> dict[str, Any]:
    return policy.get("cleanup", {})


def remove_worktree_on_complete(policy: dict[str, Any]) -> bool:
    """Does a successful `complete` prune the run's worktree?

    Defaults to True for policies written before the knob existed, so the
    behaviour is on everywhere and the opt-out is an explicit local `false`
    (which `policy sync` preserves - the key is not a template-wins scalar).
    """
    return bool(cleanup_config(policy).get("remove_worktree_on_complete", True))


def read_config(root: Path) -> dict[str, Any]:
    return load_toml(app_path(root) / "config.toml")


# Quota pools. A backend draws on the Claude subscription quota, and so
# takes a quota reservation and stops at the reserve line, when its table declares
# quota_pool = "claude". The backend named claude defaults to that pool, so a local
# policy written before the field keeps its supervision. Any other backend whose
# command runs claude must declare a pool ("claude", or "none" when it bills a
# separate pool such as an API key), or the policy is refused at load: guessing from
# the command alone is defeated by a wrapper or another path to the binary.
CLAUDE_QUOTA_POOL = "claude"
NO_QUOTA_POOL = "none"
QUOTA_POOLS = frozenset({CLAUDE_QUOTA_POOL, NO_QUOTA_POOL})


def backend_quota_pool(name: str, policy: dict[str, Any]) -> str:
    """Quota pool a backend draws on: CLAUDE_QUOTA_POOL or NO_QUOTA_POOL."""
    config = policy.get("backends", {}).get(name)
    if isinstance(config, dict) and "quota_pool" in config:
        return str(config["quota_pool"])
    return CLAUDE_QUOTA_POOL if name == "claude" else NO_QUOTA_POOL


def _command_runs_claude(command: Any) -> bool:
    if not isinstance(command, str) or not command.strip():
        return False
    try:
        first = shlex.split(command)[0]
    except (ValueError, IndexError):
        first = command.split()[0]
    return Path(first).name == "claude"


def quota_pool_errors(policy: dict[str, Any]) -> list[str]:
    """One line per backend table whose quota pool is unknown or missing."""
    errors: list[str] = []
    backends = policy.get("backends", {})
    if not isinstance(backends, dict):
        return errors
    for name, config in backends.items():
        if not isinstance(config, dict):
            continue
        if "quota_pool" in config:
            pool = config["quota_pool"]
            if pool not in QUOTA_POOLS:
                errors.append(
                    f"[backends.{name}] quota_pool = {pool!r} is not a known pool; "
                    f'use "{CLAUDE_QUOTA_POOL}" or "{NO_QUOTA_POOL}"'
                )
        elif name != "claude" and _command_runs_claude(config.get("command")):
            errors.append(
                f"[backends.{name}] runs claude but declares no quota_pool, so it would "
                f'escape quota supervision; add quota_pool = "{CLAUDE_QUOTA_POOL}" '
                f'(or "{NO_QUOTA_POOL}" if it bills a separate pool, e.g. an API key)'
            )
    return errors


def read_policy(root: Path, policy_name: str | None = None) -> dict[str, Any]:
    config = read_config(root)
    selected = policy_name or str(config.get("default_policy", "default"))
    policy = load_toml(app_path(root) / "policies" / f"{selected}.toml")
    if not policy:
        die(f"policy not found: {selected}")
    errors = quota_pool_errors(policy) + model_override_errors(policy)
    if policy.get("routing", {}).get("default_source", "policy") not in ("host", "policy"):
        errors.append('[routing] default_source must be "host" or "policy"')
    codex = policy.get("backends", {}).get("codex", {})
    if (
        codex.get("enabled") and Path(str(codex.get("command", ""))).name == "codex"
        and "exec" not in codex.get("args", [])
    ):
        errors.append('[backends.codex] requires "exec" in args; replace the legacy placeholder before enabling it')
    if errors:
        die(f"policy {selected}: " + "\n  ".join(errors))
    policy = apply_claude_sandbox_stacks(apply_model_overrides(policy), root)
    return apply_codex_sandbox_stacks(policy, root)
