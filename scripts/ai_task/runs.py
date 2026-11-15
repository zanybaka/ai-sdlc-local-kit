"""Runs domain for the ai-task CLI.

Boundary:
functions whose call chain reaches a name that tests monkeypatch on the
entrypoint module stay in scripts/ai-task.py. That pins the finalize/reap
orchestrators (notify_run_outcome -> _telegram_send/_notify_policy_for_root),
choose_backend_order (refresh_cooldowns -> probe_backend_recovery ->
backend_env -> _notify_suppress_implement_for_root), backend_env itself,
state.json I/O (fcntl/msvcrt/_LOCKLESS_PLATFORM_WARNED), the lease pair
(operator_identity cache), the waiting-quota lifecycle and the guard wrappers
that write journal rows (maybe_auto_log_anomaly -> operator_identity). This
module operates on state/run dicts passed in by the entrypoint and never
imports back into it.

Imports stdlib plus the already-extracted sibling domains (_shared, backlog,
policy, scheduling) only.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import tomllib

from ai_task._shared import app_path, die, now, pid_alive
from ai_task.backlog import TASK_RE, Task, risk_gates
from ai_task.policy import (
    AUTH_WORDS,
    CLAUDE_SANDBOX_ALLOWED_DOMAINS,
    CLAUDE_SANDBOX_CACHE_ENV,
    CLAUDE_SANDBOX_STACKS_APPLIED_KEY,
    CODEX_WORKER_SANDBOX_KEY,
    DEFAULT_AUTH_FIX_HINTS,
    LIMIT_WORDS,
    sandbox_stack_extra,
)
from ai_task.scheduling import (
    broad_scope_words_present,
    predict_task_files,
    task_block_body,
)

# the run --wait supervision loop polls the child process / log mtimes
# every `poll_interval` seconds. 2s in production; a test/tuning knob lets the CLI
# suite poll fast (e.g. 0.01) so --wait tests no longer pay the 2s-per-poll floor.
POLL_INTERVAL_ENV = "AI_TASK_POLL_INTERVAL_SECONDS"
DEFAULT_POLL_INTERVAL_SECONDS = 2.0


BLOCKED_WORDS = (
    "workspace trust required",
    "waiting for approval",
    "waiting for your approval",
    "approve this",
    "permission denied",
    "do you trust",
    "press enter to continue",
    "(y/n)",
    "waiting for user",
)

# Backlog `Agent:` field → backend preference order. `auto` uses policy routing.
AGENT_BACKEND_ORDER: dict[str, list[str]] = {
    "claude": ["claude"],
    "cursor": ["cursor_codex", "cursor_auto"],
    "codex": ["codex"],
    "cursor_codex": ["cursor_codex"],
    "cursor_auto": ["cursor_auto"],
    "devin": ["devin"],
    "human": [],
}

# Cursor API pool resets on monthly billing cycle; do not auto-clear cooldown on timer.
CURSOR_COOLDOWN_BACKENDS = frozenset({"cursor_codex", "cursor_auto"})
DEFAULT_AUTO_BACKEND_ORDER = ["claude"]
# Grace before a `running` run with no recorded pid is treated as orphaned:
# a just-launched run persists status="running" a few ms before
# its backend pid is captured, so do not reap pid-less runs younger than this.
ORPHAN_PIDLESS_GRACE_SECONDS = 60


DURATION_RE = re.compile(r"^(\d+)\s*([dhms])$", re.IGNORECASE)


def parse_duration_spec(text: str) -> dt.timedelta:
    normalized = text.strip().lower().replace(" ", "")
    match = DURATION_RE.fullmatch(normalized)
    if not match:
        die(f"invalid duration: {text} (use e.g. 7d, 24h, 30m)")
    amount = int(match.group(1))
    unit = match.group(2)
    seconds = {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
    return dt.timedelta(seconds=amount * seconds)


def parse_iso_timestamp(raw: str) -> dt.datetime:
    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def run_reference_time(run: dict[str, Any]) -> dt.datetime | None:
    for key in ("finished_at", "completed_at", "created_at"):
        raw = run.get(key)
        if isinstance(raw, str) and raw.strip():
            return parse_iso_timestamp(raw)
    return None


def run_sort_key(run: dict[str, Any]) -> dt.datetime:
    created = run.get("created_at")
    if isinstance(created, str) and created.strip():
        try:
            return parse_iso_timestamp(created)
        except (ValueError, TypeError):
            pass
    ref = run_reference_time(run)
    if ref is not None:
        return ref
    return dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def _supervision_poll_interval_seconds() -> float:
    """Seconds the run --wait supervision loop sleeps between polls.

    Reads ``AI_TASK_POLL_INTERVAL_SECONDS``. Falls back to the 2.0s
    default on a missing/blank/invalid value so production behavior is unchanged;
    negative values clamp to 0.0. This is a test/tuning knob — the CLI suite sets
    it to a small value so --wait tests don't pay the 2s-per-poll wall.
    """
    raw = os.environ.get(POLL_INTERVAL_ENV, "").strip()
    if not raw:
        return DEFAULT_POLL_INTERVAL_SECONDS
    try:
        interval = float(raw)
    except ValueError:
        return DEFAULT_POLL_INTERVAL_SECONDS
    if interval < 0:
        return 0.0
    return interval


def worktrees_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("worktrees_enabled", False))


def is_git_repository(root: Path) -> bool:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.returncode == 0
    except OSError:
        return False


def sanitize_git_branch_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._/-]+", "-", value).strip("./-")
    return cleaned or "task"


RUN_BRANCH_NAMESPACE = "ai-task/"


def planned_branch(task_id: str, run_id: str) -> str:
    """Branch name a run's worktree uses. Derivable from the run record alone."""
    short = run_id.split("-")[-1][:8]
    return f"{RUN_BRANCH_NAMESPACE}{sanitize_git_branch_component(task_id)}-{short}"


def planned_worktree(root: Path, task: Task, run_id: str) -> tuple[str, str]:
    branch = planned_branch(task.id, run_id)
    rel_path = f".ai-task/worktrees/{run_id}"
    return rel_path, branch


def run_branch_name(run: dict[str, Any]) -> str:
    """The run's branch: the recorded one, else derived from the record.

    A record whose `worktree_branch` was cleared (a removed worktree, a healed
    stale path) can still own a live ref, so the name has to survive the field.
    Only names in the `ai-task/` namespace are ever returned.
    """
    branch = str(run.get("worktree_branch", "") or "")
    if not branch:
        run_id = str(run.get("id", "") or "")
        task_id = str(run.get("task_id", "") or "")
        if run_id and task_id:
            branch = planned_branch(task_id, run_id)
    return branch if branch.startswith(RUN_BRANCH_NAMESPACE) else ""


def prepare_run_worktree(
    root: Path,
    config: dict[str, Any],
    task: Task,
    run_id: str,
) -> tuple[Path, str, str]:
    if not worktrees_enabled(config):
        return root.resolve(), "", ""
    if not is_git_repository(root):
        die("worktrees_enabled requires a git repository")
    rel_path, branch = planned_worktree(root, task, run_id)
    wt_path = (root / rel_path).resolve()
    if wt_path.exists():
        die(f"worktree path already exists: {rel_path}")
    wt_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(wt_path)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        die(f"git worktree add failed: {stderr}")
    copy_ignored_agents_md(root, wt_path)
    return wt_path, rel_path, branch


def copy_ignored_agents_md(root: Path, wt_path: Path) -> None:
    """Give a run's worktree the root AGENTS.md when git ignores it.

    A public repository keeps the canon AGENTS.md as a local copy listed in
    .gitignore, so `git worktree add` does not bring it and the run would work
    without the rules its packet tells it to follow. Only an ignored copy is
    copied: a tracked one is already in the worktree, and an untracked one that
    is not ignored could be committed by the run.
    """
    src = root / "AGENTS.md"
    dest = wt_path / "AGENTS.md"
    if not src.is_file() or dest.exists():
        return
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "AGENTS.md"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if ignored.returncode == 0:
        shutil.copyfile(src, dest)


def resolve_run_cwd(root: Path, run: dict[str, Any]) -> Path:
    rel = str(run.get("worktree_path", "") or "")
    if rel:
        return (root / rel).resolve()
    return root.resolve()


def remove_run_worktree(
    root: Path, run: dict[str, Any], *, force: bool = False
) -> str | None:
    rel = str(run.get("worktree_path", "") or "")
    if not rel:
        return None
    wt_path = root / rel
    if not wt_path.exists():
        run.pop("worktree_path", None)
        run.pop("worktree_branch", None)
        return None
    cmd = ["git", "worktree", "remove", str(wt_path)]
    if force:
        cmd.append("--force")
    completed = subprocess.run(
        cmd, cwd=root, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        return (
            completed.stderr or completed.stdout or "git worktree remove failed"
        ).strip()
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    run.pop("worktree_path", None)
    # `worktree_branch` deliberately survives here: the ref outlives the
    # worktree, and a name dropped from state is a ref nothing can find again.
    # `release_run_worktree` clears it once the ref is gone.
    return None


def worktree_dirty_paths(root: Path, run: dict[str, Any]) -> list[str]:
    """Uncommitted paths inside a run's worktree.

    Untracked files count as dirty: per the run release contract the teamlead
    commits, not the implement run, so work that never reached a commit is the
    norm rather than an anomaly, and it is exactly what a sweep must not
    discard. Ignored entries are excluded — `.ai-task/` lives inside the
    worktree and is not work. Returns an empty list when the run owns no
    worktree, the directory is gone, or git cannot read it: absence of evidence
    is not treated as dirt, and the commits-ahead guard still applies.
    """
    rel = str(run.get("worktree_path", "") or "")
    if not rel:
        return []
    wt_path = root / rel
    if not wt_path.is_dir():
        return []
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=wt_path,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return []
    dirty: set[str] = set()
    for line in (completed.stdout or "").splitlines():
        if len(line) < 4:
            continue
        if line[:2] == "!!":
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        if path:
            dirty.add(path)
    return sorted(dirty)


def git_text(cwd: Path, *args: str) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (completed.stdout or completed.stderr or "").strip()
    return completed.returncode, output


def current_git_branch(cwd: Path) -> str | None:
    code, output = git_text(cwd, "symbolic-ref", "--short", "HEAD")
    return output if code == 0 and output and output != "HEAD" else None


def cleanup_default_branch(root: Path) -> str | None:
    branch = current_git_branch(root)
    if branch:
        return branch
    code, output = git_text(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    return output if code == 0 and output else None


def cleanup_worktree_branch(root: Path, run: dict[str, Any]) -> str | None:
    branch = str(run.get("worktree_branch", "") or "")
    if branch:
        return branch
    rel = str(run.get("worktree_path", "") or "")
    if not rel:
        return None
    return current_git_branch(root / rel)


def cleanup_branch_ahead_count(
    root: Path, run: dict[str, Any]
) -> tuple[int | None, str, str, str]:
    base = cleanup_default_branch(root) or ""
    branch = cleanup_worktree_branch(root, run) or ""
    if not base:
        return None, base, branch, "default branch could not be determined"
    if not branch:
        return None, base, branch, "worktree branch could not be determined"
    code, output = git_text(root, "rev-list", "--count", f"{base}..{branch}")
    if code != 0:
        return None, base, branch, output or "git rev-list failed"
    try:
        return int(output), base, branch, ""
    except ValueError:
        return None, base, branch, f"unexpected git rev-list output: {output}"


def worktree_keep_reason(
    root: Path, run: dict[str, Any], *, force: bool = False
) -> str | None:
    """Why a run's worktree must survive a sweep, or None when it is disposable.

    Two independent questions, both of which have to come back clean:
    does the working tree hold uncommitted work, and does the
    branch hold commits the base does not have. Every status that can own a
    worktree is asked - a `done` run is not exempt, since the release contract
    leaves its work uncommitted just as often. `force` answers None for both,
    which is the single documented override.
    """
    if force:
        return None
    dirty = worktree_dirty_paths(root, run)
    if dirty:
        shown = ", ".join(dirty[:5])
        if len(dirty) > 5:
            shown += f" (+{len(dirty) - 5} more)"
        rel = str(run.get("worktree_path", "") or "")
        return (
            f"uncommitted changes in {rel}: {shown}; "
            "commit or move the work, or pass --force to discard it"
        )
    ahead, base, branch, reason = cleanup_branch_ahead_count(root, run)
    if ahead is None:
        return (
            f"cannot verify commits ahead of the default branch ({reason}); "
            "pass --force to remove"
        )
    if ahead > 0:
        return (
            f"branch {branch} is {ahead} commit(s) ahead of {base}; "
            "run verdict/complete first or pass --force to remove"
        )
    return None


def git_branch_exists(root: Path, branch: str) -> bool:
    if not branch:
        return False
    code, _ = git_text(root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    return code == 0


def delete_git_branch(root: Path, branch: str, *, force: bool = False) -> str | None:
    code, output = git_text(root, "branch", "-D" if force else "-d", branch)
    return None if code == 0 else (output or "git branch delete failed")


def release_run_worktree(
    root: Path, run: dict[str, Any], *, force: bool = False
) -> dict[str, str]:
    """Remove a run's worktree and, when it is safe, its branch.

    The worktree removal itself always passes git's `--force`, because callers
    gate that decision upstream with `worktree_keep_reason`. The `force`
    argument here is the operator's `--force`: it decides whether a branch with
    commits the base does not have is deleted anyway.

    Returns `error`, `branch`, `branch_deleted` and `branch_kept` (the reason,
    when the ref survives). Commits ahead are counted before the removal, since
    resolving an unrecorded branch name needs the worktree.
    """
    branch = str(cleanup_worktree_branch(root, run) or "")
    ahead, base, _branch, reason = cleanup_branch_ahead_count(root, run)
    result = {"error": "", "branch": branch, "branch_deleted": "", "branch_kept": ""}
    error = remove_run_worktree(root, run, force=True)
    if error:
        result["error"] = error
        return result
    if not branch:
        run.pop("worktree_branch", None)
        return result
    if not branch.startswith(RUN_BRANCH_NAMESPACE):
        # Refs this tool did not create are never candidates for deletion.
        run["worktree_branch"] = branch
        return result
    if not git_branch_exists(root, branch):
        run.pop("worktree_branch", None)
        return result
    # Kept branches are written back: when the worktree was already gone,
    # `remove_run_worktree` took its missing-path branch and cleared the field.
    if not force and (ahead is None or ahead > 0):
        result["branch_kept"] = (
            f"cannot verify commits ahead ({reason})"
            if ahead is None
            else f"{ahead} commit(s) ahead of {base}"
        )
        run["worktree_branch"] = branch
        return result
    delete_error = delete_git_branch(root, branch, force=force)
    if delete_error:
        result["branch_kept"] = delete_error
        run["worktree_branch"] = branch
        return result
    result["branch_deleted"] = branch
    run.pop("worktree_branch", None)
    return result


def cooldown_config(policy: dict[str, Any]) -> dict[str, Any]:
    return policy.get("cooldown", {})


def cooldown_active(info: dict[str, Any]) -> bool:
    until = info.get("cooldown_until")
    if not until:
        return True
    expires = parse_iso8601(str(until))
    if expires is None:
        return True
    return dt.datetime.now(dt.timezone.utc) < expires


def backend_cooled_down(name: str, info: dict[str, Any] | None) -> bool:
    """Whether routing should skip this backend. Cursor backends stay blocked until manual clear."""
    if not info:
        return False
    if name in CURSOR_COOLDOWN_BACKENDS:
        return True
    return cooldown_active(info)


def set_backend_cooldown(
    state: dict[str, Any],
    name: str,
    policy: dict[str, Any],
    reason: str,
    run_id: str | None = None,
    *,
    from_active_attempt: bool = False,
) -> None:
    if not name:
        return
    seconds = int(cooldown_config(policy).get("default_seconds", 1800) or 1800)
    until = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds)).replace(
        microsecond=0
    )
    until_iso = until.isoformat()
    cooldowns = state.setdefault("backend_cooldowns", {})
    existing = cooldowns.get(name)
    if existing and cooldown_active(existing):
        existing_expiry = parse_iso8601(str(existing.get("cooldown_until")))
        if existing_expiry is not None and until <= existing_expiry:
            return
        if not from_active_attempt:
            return
    cooldowns[name] = {
        "reason": reason,
        "checked_at": now(),
        "cooldown_until": until_iso,
        "run_id": run_id,
    }


def clear_backend_cooldown(state: dict[str, Any], name: str) -> None:
    state.get("backend_cooldowns", {}).pop(name, None)


def run_elapsed_seconds(run: dict[str, Any]) -> float | None:
    """Wall-clock seconds from started_at/created_at to finished_at (or now)."""
    started = parse_iso8601(str(run.get("started_at") or run.get("created_at") or ""))
    if started is None:
        return None
    finished = parse_iso8601(str(run.get("finished_at") or "")) or dt.datetime.now(
        dt.timezone.utc
    )
    return max(0.0, (finished - started).total_seconds())


def agent_preferred_backends(task: Task, policy: dict[str, Any]) -> list[str] | None:
    """None = use default auto routing; [] = human/manual only."""
    agent = (task.agent or "auto").strip().lower()
    if not agent or agent == "auto":
        return None
    routing = policy.get("routing", {})
    agent_map = routing.get("agent_map")
    if isinstance(agent_map, dict) and agent in agent_map:
        value = agent_map[agent]
        if isinstance(value, list):
            return [str(name) for name in value]
        return [str(value)]
    if agent == "codex" and "default_source" not in routing:
        return ["cursor_codex"]
    if agent in AGENT_BACKEND_ORDER:
        return list(AGENT_BACKEND_ORDER[agent])
    die(
        f"unknown Agent: {agent} on task {task.id} (use auto, claude, cursor, codex, devin, or human)"
    )
    return None  # unreachable


TEAMLEAD_MARKERS = ("CODEX_THREAD_ID", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def teamlead_host() -> tuple[str | None, str]:
    """markers are hints, not authentication or permission evidence."""
    worker = os.environ.get("AI_TASK_WORKER_BACKEND")
    if worker:
        return (worker if worker in {"claude", "codex"} else None), "worker executor"
    codex = bool(os.environ.get("CODEX_THREAD_ID"))
    claude = bool(os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_ENTRYPOINT"))
    if codex and claude:
        return None, "conflicting teamlead markers; using policy order"
    if codex:
        return "codex", "Codex teamlead"
    if claude:
        return "claude", "Claude Code teamlead"
    return None, "unknown teamlead; using policy order"


def default_backend_order(task: Task, policy: dict[str, Any]) -> tuple[list[str], str]:
    routing = policy.get("routing", {})
    key = "simple_order" if task.size.upper() == "S" and not risk_gates(task, policy) else "default_order"
    order = list(routing.get(key, routing.get("default_order", DEFAULT_AUTO_BACKEND_ORDER)))
    if routing.get("default_source", "policy") != "host":
        return order, "project policy"
    # A custom order is itself an explicit project choice. Set default_source=policy
    # to deliberately keep the bundled [claude] order even from a Codex session.
    if order != DEFAULT_AUTO_BACKEND_ORDER:
        return order, "project routing order"
    host, reason = teamlead_host()
    return ([host] if host else order), reason


def primary_backend_names(task: Task, policy: dict[str, Any]) -> list[str]:
    routing = policy.get("routing", {})
    backends = policy.get("backends", {})
    disabled = set(routing.get("disabled_backends", []))
    preferred = agent_preferred_backends(task, policy)
    if preferred is not None:
        base = preferred
    else:
        base, _ = default_backend_order(task, policy)
    return [
        name
        for name in base
        if name not in disabled and backends.get(name, {}).get("enabled", False)
    ]


def is_in_session_backend(backend: dict[str, Any]) -> bool:
    """the teamlead's own subagent executes the run; ai-task launches nothing."""
    return bool(backend.get("in_session", False))


def backend_available(backend: dict[str, Any]) -> bool:
    if is_in_session_backend(backend):
        return True
    return bool(shutil.which(str(backend.get("command", ""))))


def supervision_config(policy: dict[str, Any]) -> dict[str, Any]:
    return policy.get("supervision", {})


EXECUTOR_MODES = ("headless", "in_session")
DEFAULT_EXECUTOR_ASK_ABOVE_TASKS = 3
DEFAULT_IN_SESSION_TIMEOUT_SECONDS = 7200


def executor_config(policy: dict[str, Any]) -> dict[str, Any]:
    config = policy.get("executor", {})
    return config if isinstance(config, dict) else {}


def in_session_timeout_seconds(policy: dict[str, Any] | None) -> int:
    """Seconds an in-session run may wait for worker-done before it is reaped (0 = never)."""
    value = executor_config(policy or {}).get(
        "in_session_timeout_seconds", DEFAULT_IN_SESSION_TIMEOUT_SECONDS
    )
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return DEFAULT_IN_SESSION_TIMEOUT_SECONDS


def in_session_backend_for_host(host: str | None) -> str | None:
    """The in-session backend matching the teamlead host, or None when unknown."""
    return f"{host}_subagent" if host in {"claude", "codex"} else None


def executor_choice(
    policy: dict[str, Any],
    *,
    tasks: int,
    waves: int,
    named: str | None = None,
    no_questions: bool = False,
    host: str | None = None,
) -> dict[str, Any]:
    """Which executor mode a batch uses and whether the teamlead must ask.

    A mode named in the owner's request wins and is never re-asked. Otherwise a
    batch of more than one wave or more than ``ask_above_tasks`` tasks asks, with
    the policy default as the recommended answer, unless an owner's intent forbids
    questions; a smaller batch takes the policy default silently.
    """
    config = executor_config(policy)
    default = str(config.get("default", "headless") or "headless")
    if default not in EXECUTOR_MODES:
        default = "headless"
    try:
        threshold = int(config.get("ask_above_tasks", DEFAULT_EXECUTOR_ASK_ABOVE_TASKS))
    except (TypeError, ValueError):
        threshold = DEFAULT_EXECUTOR_ASK_ABOVE_TASKS
    large = waves > 1 or tasks > threshold
    if named:
        mode, source, ask = named, "request", False
    elif no_questions:
        mode, source, ask = default, "intent", False
    elif large:
        mode, source, ask = default, "answer", True
    else:
        mode, source, ask = default, "policy", False
    backend = in_session_backend_for_host(host) if mode == "in_session" else None
    if ask:
        reason = (
            f"batch of {tasks} task(s) in {waves} wave(s) exceeds one wave or "
            f"{threshold} task(s); ask with {default} recommended"
        )
    elif source == "request":
        reason = "mode named in the request"
    elif source == "intent":
        reason = "intent forbids questions; policy default taken and reported"
    else:
        reason = f"batch within one wave and {threshold} task(s); policy default"
    return {
        "mode": mode,
        "recommended": default,
        "source": source,
        "ask": ask,
        "large_batch": large,
        "ask_above_tasks": threshold,
        "tasks": tasks,
        "waves": waves,
        "in_session_backend": backend,
        "reason": reason,
    }


# The worker-done contract: what a worker reports when
# it ends. An in-session worker reports through `ai-task worker-done --outcome
# --final-text --note`; a headless Codex worker returns the same three fields as
# its final message, held to this schema by `codex exec --output-schema`.
WORKER_OUTCOMES = ("success", "failure", "limited")
WORKER_REPORT_SCHEMA_FILE = "worker-done.schema.json"
WORKER_REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["outcome", "final_answer", "note"],
    "properties": {
        "outcome": {
            "type": "string",
            "enum": list(WORKER_OUTCOMES),
            "description": (
                "success: the task is done and its checks pass. failure: the task "
                "is not done, for any reason, a refused or failing command included. "
                "limited: only when the model service itself stopped you with a "
                "usage or rate limit."
            ),
        },
        "final_answer": {
            "type": "string",
            "description": (
                "Markdown report for the reviewer: what changed, which checks ran "
                "and their result, what is left."
            ),
        },
        "note": {
            "type": "string",
            "description": "One short line with the cause of a failure or a limit; empty on success.",
        },
    },
}


def write_worker_report_schema(output_dir: Path) -> Path:
    """Write the worker-done schema next to the run's final answer."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / WORKER_REPORT_SCHEMA_FILE
    text = json.dumps(WORKER_REPORT_SCHEMA, indent=2) + "\n"
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def codex_home_hook_trust_args(home: Path | None = None) -> list[str]:
    """`-c hooks.state={...}` with the saved trust of `$CODEX_HOME/hooks.json`.

    The worker runs with --ignore-user-config, so Codex loads `$CODEX_HOME/hooks.json`
    but not the trust that `scripts/register-codex-hooks.py` saved in config.toml,
    and skips the hooks as untrusted. Codex reads hooks.state from the -c layer
    too (codex-rs/hooks/src/config_rules.rs), so the worker gets the trust of the
    home hooks file and nothing else of the personal config: no trust for hooks a
    project carries in its own .codex folder, no model, MCP servers or notify.
    No file, no entries, or a broken config: [] and Codex skips the hooks.
    """
    home = home or codex_home()
    try:
        data = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return []
    state = data.get("hooks", {}).get("state", {})
    if not isinstance(state, dict):
        return []
    prefixes = {f"{home / 'hooks.json'}:", f"{home.resolve() / 'hooks.json'}:"}
    entries = []
    for key in sorted(state):
        value = state[key]
        if not isinstance(value, dict) or not any(key.startswith(p) for p in prefixes):
            continue
        fields = []
        if isinstance(value.get("trusted_hash"), str):
            fields.append(f"trusted_hash={json.dumps(value['trusted_hash'])}")
        if isinstance(value.get("enabled"), bool):
            fields.append(f"enabled={'true' if value['enabled'] else 'false'}")
        if fields:
            entries.append(f"{json.dumps(key)}={{{', '.join(fields)}}}")
    if not entries:
        return []
    return ["-c", "hooks.state={" + ", ".join(entries) + "}"]


def codex_project_trust_args(run_cwd: Path) -> list[str]:
    """`-c projects={...}` marking the run directory trusted.

    A Codex worker in workspace-write finds no trust entry for its directory and
    writes `[projects."<repository root>"] trust_level = "trusted"` into the
    personal config.toml, --ignore-user-config or not (thread_processor.rs). Codex
    looks the project up in the merged map, the -c layer included, by the working
    directory first, so this entry gives the same trust without the write.
    """
    key = json.dumps(str(run_cwd.resolve()))
    return ["-c", f'projects={{{key}={{trust_level="trusted"}}}}']


def codex_sandbox_args(run_cwd: Path, stacks: list[str]) -> list[str]:
    """`-c` arguments that fit the workspace-write sandbox to the stacks.

    workspace-write refuses the caches under the home folder (uv, pip, npm,
    DerivedData) and has no network. The worker gets what the Claude worker has:
    caches under `.ai-task/cache/` of the run directory, absolute because Codex
    knows no working directory for an environment value; network only to the
    allowed domains, through the managed proxy that Codex starts when
    `features.network_proxy` carries a domain list and the sandbox allows network
    (codex-rs/core/src/config/network_config.rs); and the writable folders of the
    stacks, with `~` expanded, since Codex takes absolute roots only.
    """
    base = run_cwd.resolve()
    domains = list(CLAUDE_SANDBOX_ALLOWED_DOMAINS)
    roots: list[str] = []
    for stack in stacks:
        extra = sandbox_stack_extra(stack)
        for domain in extra.get("network", {}).get("allowedDomains", []):
            if domain not in domains:
                domains.append(domain)
        for path in extra.get("filesystem", {}).get("allowWrite", []):
            resolved = str(Path(path).expanduser())
            if resolved not in roots:
                roots.append(resolved)
    env = ", ".join(
        f"{name}={json.dumps(str(base / rel))}" for name, rel in CLAUDE_SANDBOX_CACHE_ENV.items()
    )
    allow = ", ".join(f"{json.dumps(domain)}=\"allow\"" for domain in domains)
    args = [
        "-c", "sandbox_workspace_write.network_access=true",
        "-c", f"features.network_proxy={{enabled=true, mode=\"full\", domains={{{allow}}}}}",
        "-c", f"shell_environment_policy.set={{{env}}}",
    ]
    if roots:
        listed = ", ".join(json.dumps(root) for root in roots)
        args.extend(["-c", f"sandbox_workspace_write.writable_roots=[{listed}]"])
    return args


def backend_command(
    backend: dict[str, Any],
    prompt: str,
    *,
    workspace: Path | None = None,
    output_dir: Path | None = None,
    run_cwd: Path | None = None,
) -> list[str]:
    command = str(backend.get("command", ""))
    args = [str(arg) for arg in backend.get("args", [])]
    args.extend(str(arg) for arg in backend.get("extra_args", []))
    prompt_arg = str(backend.get("prompt_arg", ""))
    result = [command]
    if workspace is not None and command == "cursor-agent":
        result.extend(["--workspace", str(workspace)])
    result.extend(args)
    if backend.get("hook_trust_from_home"):
        result.extend(codex_home_hook_trust_args())
    if run_cwd is not None and backend.get("trust_run_directory"):
        result.extend(codex_project_trust_args(run_cwd))
    if run_cwd is not None and backend.get(CODEX_WORKER_SANDBOX_KEY):
        stacks = backend.get(CLAUDE_SANDBOX_STACKS_APPLIED_KEY)
        result.extend(codex_sandbox_args(run_cwd, list(stacks) if isinstance(stacks, list) else []))
    if output_dir is not None and backend.get("output_schema_arg"):
        schema = write_worker_report_schema(output_dir)
        result.extend([str(backend["output_schema_arg"]), str(schema)])
    if output_dir is not None and backend.get("output_last_message_arg"):
        result.extend([str(backend["output_last_message_arg"]), str(output_dir / "final.md")])
    if prompt_arg:
        result.extend([prompt_arg, prompt])
    elif not backend.get("stdin_prompt", True):
        result.append(prompt)
    return result


def backend_input(backend: dict[str, Any], prompt: str) -> str | None:
    if backend.get("stdin_prompt", True):
        return prompt
    return None


def run_age_seconds(run: dict[str, Any]) -> float | None:
    started = parse_iso8601(str(run.get("started_at") or run.get("created_at")))
    if started is None:
        return None
    return (dt.datetime.now(dt.timezone.utc) - started).total_seconds()



SCOPE_SNAPSHOT_DIR = "scope-pre"
SCOPE_GUARD_MAX_EDITS = 200
SCOPE_ACK_CHOICE = "scope_ack"

SCOPE_SENSITIVE_FILES = (".gitmodules", ".ai-task/config.toml")
SCOPE_SENSITIVE_GLOBS = (".ai-task/policies/*.toml",)
SENSITIVE_EDITS_CHOICE = "sensitive_file_edits"


def scope_guard_config(policy: dict[str, Any]) -> dict[str, Any]:
    section = policy.get("scope_guard", {})
    return section if isinstance(section, dict) else {}


def scope_guard_enabled(policy: dict[str, Any]) -> bool:
    return bool(scope_guard_config(policy).get("enabled", True))


def scope_guard_mode(policy: dict[str, Any]) -> str:
    mode = str(scope_guard_config(policy).get("mode", "warn")).strip().lower()
    return mode if mode in {"warn", "require_ack"} else "warn"


def scope_guard_task_files(policy: dict[str, Any]) -> list[str]:
    raw = scope_guard_config(policy).get("task_files", ["BACKLOG.md"])
    if not isinstance(raw, list):
        return ["BACKLOG.md"]
    files: list[str] = []
    for item in raw:
        rel = str(item).strip()
        if not rel:
            continue
        path = Path(rel)
        # Policy is operator-owned, but keep snapshots inside the working tree.
        if path.is_absolute() or ".." in path.parts:
            continue
        files.append(rel)
    return files


def sensitive_file_hashes(
    run_cwd: Path,
    files: tuple[str, ...] = SCOPE_SENSITIVE_FILES,
    globs: tuple[str, ...] = SCOPE_SENSITIVE_GLOBS,
) -> dict[str, str]:
    """SHA-256 per existing sensitive control file, keyed by relative path."""
    paths: list[Path] = [run_cwd / rel for rel in files]
    for pattern in globs:
        paths.extend(sorted(run_cwd.glob(pattern)))
    hashes: dict[str, str] = {}
    for path in paths:
        try:
            if not path.is_file():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        hashes[path.relative_to(run_cwd).as_posix()] = digest
    return hashes


def capture_scope_snapshot(
    run_dir: Path, run_cwd: Path, policy: dict[str, Any]
) -> dict[str, Any]:
    """Copy configured task files into run_dir/scope-pre as the pre-run state.

    Returns the guard manifest stored on the run record: the files configured at
    launch plus the subset that existed and was snapshotted, and the sensitive
    control-file hashes. Best-effort — a copy failure skips that
    file rather than failing the launch.
    """
    if not scope_guard_enabled(policy):
        return {"files": [], "captured": []}
    files = scope_guard_task_files(policy)
    captured: list[str] = []
    for rel in files:
        src = run_cwd / rel
        try:
            if not src.is_file():
                continue
            dest = run_dir / SCOPE_SNAPSHOT_DIR / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            captured.append(rel)
        except OSError:
            continue
    return {
        "files": files,
        "captured": captured,
        "sensitive": sensitive_file_hashes(run_cwd),
    }


def _split_backlog_scope_segments(
    lines: list[str],
) -> tuple[dict[str, str], list[str]]:
    """Split task-file lines into {task_id: block_text} plus non-task lines.

    Same block boundaries as parse_backlog_blocks: a task block runs from its
    checkbox line until the next checkbox line or `## ` section heading. Blank
    lines outside blocks are dropped so whitespace reflow never flags.

    Generated-index awareness: a one-liner index entry
    (``- [x] [ID](backlog/tasks/ID.md) Title``) counts as that task's
    single-line block, so the run's own checkbox flip in the regenerated
    BACKLOG.md stays in scope while a foreign entry change still flags. The
    generated marker line (content hash changes on every regeneration) is
    ignored entirely.
    """
    from ai_task.backlog_store import INDEX_TASK_LINE_RE, is_marker_line

    blocks: dict[str, str] = {}
    other: list[str] = []
    current_id: str | None = None
    current: list[str] = []

    def flush() -> None:
        nonlocal current_id, current
        if current_id is not None:
            blocks[current_id] = "\n".join(current).strip()
        current_id = None
        current = []

    for line in lines:
        match = TASK_RE.match(line)
        if match:
            flush()
            current_id = match.group("id")
            current = [line]
            continue
        index_match = INDEX_TASK_LINE_RE.match(line)
        if index_match:
            flush()
            blocks[index_match.group("id")] = line.rstrip()
            continue
        if is_marker_line(line):
            flush()
            continue
        if line.startswith("## "):
            flush()
            other.append(line.rstrip())
            continue
        if current_id is not None:
            current.append(line)
        elif line.strip():
            other.append(line.rstrip())
    flush()
    return blocks, other


def _clip_scope_detail(text: str, limit: int = 160) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _line_count_map(lines: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in lines:
        counts[line] = counts.get(line, 0) + 1
    return counts


def backlog_out_of_scope_edits(
    pre_text: str, post_text: str, task_id: str, *, path: str = "BACKLOG.md"
) -> list[dict[str, Any]]:
    """Edits outside the run's own task block between two task-file versions.

    In scope (never flagged): any change confined to the `task_id` block — the
    checkbox flip, DOD notes, the block's own lines. Flagged: foreign task
    blocks added/modified/removed, `## ` sections added/removed, and any other
    non-task content change (preamble text). A file with no task blocks (a
    non-backlog task file) therefore flags every changed line.
    """
    if pre_text == post_text:
        return []
    pre_blocks, pre_other = _split_backlog_scope_segments(pre_text.splitlines())
    post_blocks, post_other = _split_backlog_scope_segments(post_text.splitlines())
    edits: list[dict[str, Any]] = []

    def add(kind: str, *, tid: str | None = None, detail: str = "") -> None:
        entry: dict[str, Any] = {"path": path, "kind": kind}
        if tid:
            entry["task_id"] = tid
        if detail:
            entry["detail"] = _clip_scope_detail(detail)
        edits.append(entry)

    def first_line(block: str) -> str:
        return block.splitlines()[0] if block else ""

    for tid, block in post_blocks.items():
        if tid == task_id:
            continue
        pre_block = pre_blocks.get(tid)
        if pre_block is None:
            add("task_added", tid=tid, detail=first_line(block))
        elif pre_block != block:
            add("task_modified", tid=tid, detail=first_line(block))
    for tid, block in pre_blocks.items():
        if tid != task_id and tid not in post_blocks:
            add("task_removed", tid=tid, detail=first_line(block))
    pre_counts = _line_count_map(pre_other)
    post_counts = _line_count_map(post_other)
    for line, count in post_counts.items():
        if count > pre_counts.get(line, 0):
            add(
                "section_added" if line.startswith("## ") else "content_added",
                detail=line,
            )
    for line, count in pre_counts.items():
        if count > post_counts.get(line, 0):
            add(
                "section_removed" if line.startswith("## ") else "content_removed",
                detail=line,
            )
    return edits


def sensitive_file_edits_between(
    pre_hashes: dict[str, Any], post_hashes: dict[str, str]
) -> list[dict[str, Any]]:
    """Changed/added/removed sensitive control files between launch and finalize."""
    edits: list[dict[str, Any]] = []
    for rel, digest in post_hashes.items():
        pre = pre_hashes.get(rel)
        if pre is None:
            edits.append({"path": rel, "kind": "file_added"})
        elif str(pre) != digest:
            edits.append({"path": rel, "kind": "file_modified"})
    for rel in pre_hashes:
        if rel not in post_hashes:
            edits.append({"path": rel, "kind": "file_removed"})
    return sorted(edits, key=lambda edit: str(edit["path"]))


# Persistent policy-hash baseline. The in-run
# sensitive watch above only sees edits between launch and finalize; a policy
# edited *between* runs (merged PR, manual agent session) is loaded silently at
# the next run/verify with nothing to diff against. The baseline at
# .ai-task/policy-hashes.json closes that window: written on `init` and
# `policy sync` (the operator's review point), checked at `run` / `verify` /
# `plan --bulk` entry. A mismatch warns loudly naming the drifted files and
# auto-logs a `policy_baseline_drift` decision row (deduped while the drift
# fingerprint is unchanged), but never blocks. Residual: policy stays
# operator-owned — this catches agent/PR drift between syncs, not a malicious
# operator, who can rewrite the baseline file too.
POLICY_BASELINE_FILE = "policy-hashes.json"
POLICY_BASELINE_FILES = (".ai-task/config.toml",)
POLICY_BASELINE_GLOBS = (".ai-task/policies/*.toml",)
POLICY_DRIFT_CHOICE = "policy_baseline_drift"


def policy_baseline_path(root: Path) -> Path:
    return app_path(root) / POLICY_BASELINE_FILE


def policy_baseline_hashes(root: Path) -> dict[str, str]:
    """Hashes of the config-as-code files loaded at run/verify/refresh."""
    return sensitive_file_hashes(
        root, files=POLICY_BASELINE_FILES, globs=POLICY_BASELINE_GLOBS
    )


def read_policy_baseline(root: Path) -> dict[str, str] | None:
    """Stored baseline hashes, or None when absent/unreadable (legacy repo)."""
    try:
        payload = json.loads(policy_baseline_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    hashes = payload.get("hashes") if isinstance(payload, dict) else None
    if not isinstance(hashes, dict):
        return None
    return {str(rel): str(digest) for rel, digest in hashes.items()}


def write_policy_baseline(root: Path) -> dict[str, str]:
    """Record current policy/config hashes as the reviewed baseline."""
    hashes = policy_baseline_hashes(root)
    payload = {"updated_at": now(), "hashes": hashes}
    path = policy_baseline_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass  # best-effort: the check degrades to the missing-baseline notice
    return hashes


def main_tree_tracked_dirty(root: Path) -> set[str]:
    """Tracked-dirty paths on the MAIN working tree via `git status --porcelain`.

    Excludes untracked (`??`) and ignored (`!!`) entries; for a rename
    (`old -> new`) the new path is returned. Uses subprocess directly rather
    than the `git_text` helper, whose `.strip()` on the whole output eats the
    leading space of the first porcelain line (` M f` -> `M f`) and corrupts the
    two-column XY status code.
    """
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return set()
    dirty: set[str] = set()
    for line in (completed.stdout or "").splitlines():
        if len(line) < 4:
            continue
        if line[:2] in ("??", "!!"):
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        if path:
            dirty.add(path)
    return dirty


def read_detached_exit_status(root: Path, run: dict[str, Any]) -> int | None:
    """Read a detached run's exit-status sidecar, if present.

    The POSIX detached launch wraps the backend in a shell that writes its exit
    code to this sidecar before exiting, so a gone pid guarantees the file is
    already flushed. Returns the integer exit code, or None when the run has no
    sidecar path, the file is missing/unreadable, or its contents are not an
    integer — a genuine kill/crash where the wrapper never got to write it, which
    keeps the needs_recovery fallback.
    """
    rel = run.get("exit_status_path")
    if not rel:
        return None
    path = Path(str(rel))
    path = path if path.is_absolute() else root / path
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def detect_limit(log_text: str, backend: dict[str, Any]) -> bool:
    patterns = [
        str(item).lower() for item in backend.get("limit_patterns", LIMIT_WORDS)
    ]
    lowered = log_text.lower()
    return any(pattern in lowered for pattern in patterns)


def detect_blocked(log_text: str, policy: dict[str, Any]) -> bool:
    patterns = [
        str(item).lower()
        for item in supervision_config(policy).get("blocked_patterns", BLOCKED_WORDS)
    ]
    lowered = log_text.lower()
    return any(pattern in lowered for pattern in patterns)


def detect_auth_failure(log_text: str, backend: dict[str, Any]) -> bool:
    """Whether this attempt's output says the backend is unauthenticated.

    Same shape as ``detect_limit`` (substring match, per-backend ``auth_patterns``
    override), different meaning: the backend cannot work on this host at all, so
    the attempt is an operator-configuration fault rather than a task failure.
    Callers gate this on a nonzero-exit attempt — a run that merely *mentions*
    authentication while succeeding is not credential-dead.
    """
    patterns = [str(item).lower() for item in backend.get("auth_patterns", AUTH_WORDS)]
    lowered = log_text.lower()
    return any(pattern in lowered for pattern in patterns)


def backend_auth_fix(backend: dict[str, Any]) -> str:
    """Operator instruction for re-authenticating a backend."""
    hint = str(backend.get("auth_fix", "") or "").strip()
    if hint:
        return hint
    command = str(backend.get("command", "") or "")
    return DEFAULT_AUTH_FIX_HINTS.get(
        command, f"authenticate the `{command or 'backend'}` CLI on this host"
    )


def auth_failure_reason(name: str, backend: dict[str, Any], log_text: str = "") -> str:
    """One actionable line: which backend, what happened, what to do."""
    excerpt = first_auth_error_line(log_text)
    detail = f" ({excerpt})" if excerpt else ""
    return (
        f"{name} is not authenticated on this host{detail}; "
        f"fix: {backend_auth_fix(backend)}"
    )


def first_auth_error_line(log_text: str, limit: int = 160) -> str:
    """First log line that matched an auth pattern, trimmed for operator output."""
    lowered_patterns = [str(item).lower() for item in AUTH_WORDS]
    for line in log_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if any(pattern in lowered for pattern in lowered_patterns):
            return stripped[:limit]
    return ""


def mark_backend_credential_dead(
    state: dict[str, Any],
    name: str,
    backend: dict[str, Any],
    reason: str,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """Remember that a backend is unusable until an operator authenticates it.

    Separate from ``backend_cooldowns`` on purpose: a cooldown is a
    timer that expires on its own, while a credential failure stays until someone
    logs in. Cleared by a successful attempt on the same backend, or by
    ``ai-task cooldown clear <backend> --force``.
    """
    if not name:
        return None
    entry = {
        "status": "credential_dead",
        "reason": reason,
        "fix": backend_auth_fix(backend),
        "detected_at": now(),
        "run_id": run_id,
    }
    state.setdefault("backend_credentials", {})[name] = entry
    return entry


def backend_credential_dead(state: dict[str, Any], name: str) -> dict[str, Any] | None:
    info = state.get("backend_credentials", {}).get(name)
    if isinstance(info, dict) and info.get("status") == "credential_dead":
        return info
    return None


def clear_backend_credentials(state: dict[str, Any], name: str) -> None:
    state.get("backend_credentials", {}).pop(name, None)


def collect_run_log_paths(run: dict[str, Any], root: Path) -> list[Path]:
    paths: list[Path] = []
    for key in ("stdout", "stderr"):
        rel = run.get(key)
        if rel:
            path = Path(str(rel))
            paths.append(path if path.is_absolute() else root / path)
    for attempt in run.get("attempts", []):
        for key in ("stdout", "stderr"):
            rel = attempt.get(key)
            if rel:
                path = Path(str(rel))
                paths.append(path if path.is_absolute() else root / path)
    run_dir = run.get("run_dir")
    if run_dir:
        base = root / str(run_dir)
        if base.is_dir():
            paths.extend(sorted(base.glob("*-stdout.log")))
            paths.extend(sorted(base.glob("*-stderr.log")))
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen or not path.exists():
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def read_run_logs(run: dict[str, Any], root: Path, tail_chars: int = 8000) -> str:
    text = ""
    for path in collect_run_log_paths(run, root):
        text += path.read_text(encoding="utf-8", errors="replace")[-tail_chars:]
    return text


def log_latest_mtime(paths: list[Path]) -> float | None:
    mtimes = [path.stat().st_mtime for path in paths if path.exists()]
    return max(mtimes) if mtimes else None


def parse_iso8601(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_idle_seconds(run: dict[str, Any], root: Path) -> int | None:
    """Seconds since last run log growth, or since start when no logs exist yet."""
    if run.get("status") not in {"running", "paused"}:
        return None
    now_ts = dt.datetime.now(dt.timezone.utc).timestamp()
    paths = collect_run_log_paths(run, root)
    last_mtime = log_latest_mtime(paths)
    if last_mtime is not None:
        return max(0, int(now_ts - last_mtime))
    started = parse_iso8601(str(run.get("started_at") or run.get("created_at")))
    if started is not None:
        return max(0, int(now_ts - started.timestamp()))
    return None


def format_run_activity_line(analysis: dict[str, Any], policy: dict[str, Any]) -> str:
    idle = analysis.get("idle_seconds")
    if idle is None:
        return "activity: no log files yet"
    stall_timeout = int(supervision_config(policy).get("stall_timeout_seconds", 0) or 0)
    minutes, seconds = divmod(int(idle), 60)
    silent = f"silent {minutes}m {seconds}s" if minutes else f"silent {seconds}s"
    signals = analysis.get("signals", [])
    if "stalled" in signals:
        threshold = (
            f" (stall threshold {stall_timeout // 60}m)" if stall_timeout else ""
        )
        return f"activity: {silent}{threshold} — stalled"
    if stall_timeout > 0 and idle < stall_timeout:
        return f"activity: {silent} (stall at {stall_timeout // 60}m)"
    return f"activity: {silent}"


def analyze_supervision(
    run: dict[str, Any],
    root: Path,
    policy: dict[str, Any],
    backends: dict[str, Any],
) -> dict[str, Any]:
    log_text = read_run_logs(run, root)
    backend = backends.get(str(run.get("backend", "")), {})
    signals: list[str] = []
    if log_text and detect_limit(log_text, backend):
        signals.append("limit")
    if log_text and detect_blocked(log_text, policy):
        signals.append("blocked_on_user")
    idle_seconds = compute_idle_seconds(run, root)
    sup = supervision_config(policy)
    stall_timeout = int(sup.get("stall_timeout_seconds", 0) or 0)
    # A live backend pid means the run is working even when its logs are silent
    # (backends launch with --print and emit nothing until a clean exit), so log
    # silence alone must never raise `stalled`. Only flag `stalled`
    # when there is no log growth AND liveness cannot be confirmed (pid absent or
    # already dead) — a genuinely stuck/abandoned process, not quiet progress.
    alive = pid_alive(run.get("pid"))
    if (
        stall_timeout > 0
        and run.get("status") in {"running", "paused"}
        and idle_seconds is not None
        and alive is not True
    ):
        started = parse_iso8601(str(run.get("started_at") or run.get("created_at")))
        if started is not None:
            run_seconds = (dt.datetime.now(dt.timezone.utc) - started).total_seconds()
            if idle_seconds >= stall_timeout and run_seconds >= stall_timeout:
                signals.append("stalled")
    return {
        "signals": signals,
        "log_bytes": len(log_text),
        "idle_seconds": idle_seconds,
    }


def apply_supervision(
    run: dict[str, Any],
    root: Path,
    policy: dict[str, Any],
    backends: dict[str, Any],
) -> dict[str, Any]:
    analysis = analyze_supervision(run, root, policy, backends)
    run["supervision"] = analysis
    signals = analysis.get("signals", [])
    if "limit" in signals:
        run["status_note"] = "limit detected in logs"
    elif "blocked_on_user" in signals:
        run["status_note"] = "blocked_on_user pattern in logs"
    elif "stalled" in signals:
        run["status_note"] = "stalled: no log growth within stall_timeout_seconds"
    return analysis


def wait_subprocess_with_supervision(
    command: list[str],
    *,
    cwd: Path,
    prompt_input: str | None,
    stdout_path: Path,
    stderr_path: Path,
    policy: dict[str, Any],
    stall_timeout: int,
    auto_stop: bool,
    env: dict[str, str] | None = None,
    on_start: Callable[[int], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    with (
        stdout_path.open("w", encoding="utf-8") as stdout,
        stderr_path.open("w", encoding="utf-8") as stderr,
    ):
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE if prompt_input is not None else None,
            stdout=stdout,
            stderr=stderr,
            text=True,
            env=env,
        )
        if on_start is not None:
            on_start(process.pid)
        if prompt_input is not None and process.stdin is not None:
            process.stdin.write(prompt_input)
            process.stdin.close()
        poll_interval = _supervision_poll_interval_seconds()
        last_mtime: float | None = None
        last_growth = dt.datetime.now(dt.timezone.utc)
        while True:
            returncode = process.poll()
            if returncode is not None:
                return subprocess.CompletedProcess(command, returncode)
            if stall_timeout > 0:
                mtimes = [stdout_path.stat().st_mtime, stderr_path.stat().st_mtime]
                current = max(mtimes)
                if last_mtime is None or current > last_mtime:
                    last_mtime = current
                    last_growth = dt.datetime.now(dt.timezone.utc)
                elif (
                    dt.datetime.now(dt.timezone.utc) - last_growth
                ).total_seconds() >= stall_timeout:
                    if auto_stop:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                    return subprocess.CompletedProcess(command, 124)
            time.sleep(poll_interval)


def run_attempt_capturing_pid(
    command: list[str],
    *,
    cwd: Path,
    prompt_input: str | None,
    stdout_path: Path,
    stderr_path: Path,
    env: dict[str, str] | None = None,
    on_start: Callable[[int], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a waited backend attempt synchronously while exposing its child pid.

    Mirrors the old ``subprocess.run`` non-stall path but uses ``Popen`` so the
    backend pid can be persisted at launch; the call still blocks
    until the process exits, so behaviour is otherwise unchanged.
    """
    with (
        stdout_path.open("w", encoding="utf-8") as stdout,
        stderr_path.open("w", encoding="utf-8") as stderr,
    ):
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE if prompt_input is not None else None,
            stdout=stdout,
            stderr=stderr,
            text=True,
            env=env,
        )
        if on_start is not None:
            on_start(process.pid)
        if prompt_input is not None and process.stdin is not None:
            process.stdin.write(prompt_input)
            process.stdin.close()
        returncode = process.wait()
    return subprocess.CompletedProcess(command, returncode)


# Run statuses that ``wait-runs`` keeps polling on. ``waiting_quota`` is an active
# *wait* state: with --resume-on-quota the run is still in flight and
# will be re-launched after the window resets; without it the caller still waits.
def quota_resume_attempts_used(run: dict[str, Any]) -> int:
    return int(run.get("resume_attempts", 0) or 0)


def build_resume_receipt(
    run: dict[str, Any],
    task: Task,
    *,
    reason: str,
    resume_after: str | None,
    quota_window: str | None,
    attempts_remaining: int,
    files_changed: bool,
    diff_summary: str,
) -> dict[str, Any]:
    """Compact, human-auditable record of why a paused run may be re-tried.

    Captures what task was in flight, why it paused, whether files changed in the
    worktree, how many auto-resume attempts remain, and the justification for
    another Claude attempt — written into the run record so the decision is visible
    in ``status --json`` and the run log before any re-launch.
    """
    justification = (
        "same packet + worktree, lease retained; quota/limit is a transient wait, "
        f"not a code defect; {attempts_remaining} auto-resume attempt(s) remain"
    )
    if attempts_remaining <= 0:
        justification = (
            "auto-resume budget exhausted; leaving waiting_quota for operator review "
            "(raise resume_max_attempts, wait, or allow a non-Claude fallback)"
        )
    return {
        "recorded_at": now(),
        "task_id": task.id,
        "task_title": task.title,
        "reason": reason,
        "paused_status": run.get("status"),
        "resume_after": resume_after,
        "quota_window": quota_window,
        "attempts_remaining": max(0, attempts_remaining),
        "files_changed": files_changed,
        "diff_summary_head": (
            diff_summary.splitlines()[0] if diff_summary else "(no diff)"
        ),
        "justification": justification,
    }


def append_run_log_note(root: Path, run: dict[str, Any], message: str) -> None:
    """Append a one-line operational note to the run's stdout log (best-effort)."""
    rel = run.get("stdout")
    if not rel:
        return
    path = Path(str(rel))
    target = path if path.is_absolute() else root / path
    try:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"\n[ai-task {now()}] {message}\n")
    except OSError:
        pass


# Statuses ``wait-runs`` keeps polling. ``waiting_quota`` is an active *wait* state:
# the run paused on quota/limit and (with --resume-on-quota) will be
# re-launched after the window resets — so wait-runs keeps waiting rather than
# treating it as inactive/failed.
ACTIVE_WAIT_RUN_STATUSES = frozenset({"running", "paused", "waiting_quota"})


def wait_run_row(run: dict[str, Any]) -> dict[str, Any]:
    row = {
        "id": run.get("id"),
        "task_id": run.get("task_id"),
        "status": run.get("status"),
        "signals": list(run.get("signals", [])),
        "status_note": run.get("status_note"),
    }
    if run.get("status") == "waiting_quota":
        row["resume_after"] = run.get("resume_after")
        row["quota_window"] = run.get("quota_window")
        row["resume_attempts_remaining"] = run.get("resume_attempts_remaining")
    if run.get("worktree_path"):
        row["worktree_path"] = run.get("worktree_path")
    return row


def wait_run_rows(
    snapshot: dict[str, Any], run_ids: list[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    by_id = {
        str(run.get("id")): run
        for run in snapshot.get("runs", [])
        if run.get("id") is not None
    }
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for run_id in run_ids:
        run = by_id.get(run_id)
        if run is None:
            missing.append(run_id)
            continue
        rows.append(wait_run_row(run))
    return rows, missing


def emit_wait_runs_json(
    *, ok: bool, rows: list[dict[str, Any]], missing: list[str], timeout: bool
) -> None:
    print(
        json.dumps(
            {
                "ok": ok,
                "runs": rows,
                "missing": missing,
                "timeout": timeout,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def print_wait_run_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        signals = row.get("signals", [])
        signal_text = ",".join(signals) if signals else "-"
        parts = [
            str(row.get("id")),
            f"task_id={row.get('task_id')}",
            f"status={row.get('status')}",
            f"signals={signal_text}",
            f"status_note={row.get('status_note') or '-'}",
        ]
        if row.get("worktree_path"):
            parts.append(f"worktree_path={row.get('worktree_path')}")
        print("  ".join(parts))


def _waiting_quota_task(state: dict[str, Any], run: dict[str, Any]) -> Task:
    """A minimal Task for receipt-building from a run record (id/title only)."""
    return Task(
        id=str(run.get("task_id", "")),
        title=str(run.get("task_title", "")),
        status=" ",
        phase="",
        index=0,
        block="",
        priority="",
        size="",
        depends_on=(),
        agent="",
    )


GIT_HISTORY_COMMITS = 200


def git_tracked_files(root: Path) -> list[str]:
    """Tracked file paths for hint-to-file mapping; empty outside git repos."""
    code, output = git_text(root, "ls-files")
    if code != 0 or not output:
        return []
    return [
        line.strip().replace("\\", "/") for line in output.splitlines() if line.strip()
    ]


def git_recent_commit_files(
    root: Path, limit: int = GIT_HISTORY_COMMITS
) -> list[tuple[str, list[str]]]:
    """Recent history as (subject, changed files); empty outside git repos."""
    code, output = git_text(
        root, "log", f"-{limit}", "--no-merges", "--name-only", "--format=%x1e%s"
    )
    if code != 0 or not output:
        return []
    commits: list[tuple[str, list[str]]] = []
    for chunk in output.split("\x1e"):
        lines = [line.strip() for line in chunk.strip().splitlines()]
        if not lines or not lines[0]:
            continue
        commits.append((lines[0], [line for line in lines[1:] if line]))
    return commits


def enrich_signals_with_predictions(
    root: Path,
    tasks: list[Task],
    signals: dict[str, dict[str, Any]],
) -> None:
    """Attach predicted touched-file sets to scope signals.

    When a task has no explicit path tokens but predictions found concrete
    targets (component hints, git history), the task is no longer treated as
    broad-scope: the old planner serialized exactly these tasks.
    """
    tracked = git_tracked_files(root)
    history = git_recent_commit_files(root)
    for task in tasks:
        sig = signals[task.id]
        body = task_block_body(task)
        prediction = predict_task_files(body, tracked_files=tracked, history=history)
        sig["predicted_files"] = prediction["predicted_files"]
        sig["file_prediction"] = prediction["sources"]
        sig["component_hints"] = prediction["component_hints"]
        if (
            sig.get("scope_broad")
            and prediction["predicted_files"]
            and not broad_scope_words_present(body)
        ):
            sig["scope_broad"] = False
            sig["scope_inferred"] = "predicted files narrow the scope"


def find_run(state: dict[str, Any], run_id: str) -> dict[str, Any]:
    runs = state.get("runs", {})
    if run_id not in runs:
        die(f"run not found: {run_id}")
    return runs[run_id]


def collect_git_diff_summary(cwd: Path) -> str:
    """Working tree, staged, and untracked paths (untracked are omitted by plain git diff)."""
    sections: list[str] = []
    for label, cmd in (
        ("Working tree", ["git", "diff", "--stat"]),
        ("Staged", ["git", "diff", "--cached", "--stat"]),
    ):
        completed = subprocess.run(
            cmd, cwd=cwd, text=True, capture_output=True, check=False
        )
        body = (completed.stdout or "").strip()
        if body:
            sections.append(f"{label}:\n{body}")
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    other = (untracked.stdout or "").strip()
    if other:
        sections.append("Untracked:\n" + other)
    return "\n\n".join(sections) if sections else "(no diff)"


# --- Phase timing + prune helpers ---


# Orchestration phases that have a CLI entry point and run AFTER the implement
# run against an existing run record. The run's own wall-clock is
# the implement phase; these are the overhead on top of it.
ORCHESTRATION_PHASES = ("verify", "review", "verdict")


def record_phase_timing(run: dict[str, Any], phase: str, started: str) -> None:
    """Accumulate per-phase timing onto ``run["phase_timing"][phase]``.

    Each phase command (verify/review/verdict) runs AFTER the implement run, so
    its elapsed wall-clock is pure orchestration overhead. ``started`` is the
    ISO stamp captured when the command began; the finish stamp is ``now()``.

    Repeats (a rework loop re-runs verify/review) ACCUMULATE: ``elapsed_seconds``
    sums across invocations and ``runs`` counts them, so a task that needed three
    review rounds shows its true total orchestration cost rather than the last
    round only. ``first_started_at`` / ``last_finished_at`` bracket the span.
    Additive: legacy runs without ``phase_timing`` simply gain the dict.
    """
    finished = now()
    start_dt = parse_iso8601(started)
    finish_dt = parse_iso8601(finished)
    elapsed = (
        max(0.0, (finish_dt - start_dt).total_seconds())
        if start_dt is not None and finish_dt is not None
        else 0.0
    )
    timing = run.setdefault("phase_timing", {})
    if not isinstance(timing, dict):
        timing = {}
        run["phase_timing"] = timing
    cell = timing.get(phase)
    if not isinstance(cell, dict):
        cell = {"elapsed_seconds": 0.0, "runs": 0, "first_started_at": started}
        timing[phase] = cell
    cell["elapsed_seconds"] = round(
        float(cell.get("elapsed_seconds", 0.0)) + elapsed, 3
    )
    cell["runs"] = int(cell.get("runs", 0)) + 1
    cell.setdefault("first_started_at", started)
    cell["last_finished_at"] = finished


def phase_overhead_components(
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Sum implement + per-phase orchestration elapsed across ``runs``.

    Returns ``{"implement_seconds", "phases": {phase: {seconds, runs_present}},
    "any_timing": bool}``. ``implement_seconds`` is the summed run wall-clock
    (the implement phase). Each orchestration phase carries its summed elapsed
    and how many runs in the window recorded that phase — so a phase that never
    ran (or predates the field) is distinguishable from one measured as 0.
    """
    implement = 0.0
    phases: dict[str, dict[str, Any]] = {
        phase: {"seconds": 0.0, "runs_present": 0} for phase in ORCHESTRATION_PHASES
    }
    any_timing = False
    for run in runs:
        if not isinstance(run, dict):
            continue
        elapsed = run_elapsed_seconds(run)
        if elapsed is not None:
            implement += elapsed
        timing = run.get("phase_timing")
        if not isinstance(timing, dict):
            continue
        for phase in ORCHESTRATION_PHASES:
            cell = timing.get(phase)
            if not isinstance(cell, dict):
                continue
            seconds = cell.get("elapsed_seconds")
            if not isinstance(seconds, (int, float)):
                continue
            phases[phase]["seconds"] += float(seconds)
            phases[phase]["runs_present"] += 1
            any_timing = True
    return {
        "implement_seconds": round(implement, 3),
        "phases": phases,
        "any_timing": any_timing,
    }


def overhead_ratio_cell(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Scorecard/trend ``overhead_ratio`` cell from phase stamps.

    ratio = (summed verify+review+verdict elapsed) / (summed implement elapsed),
    over runs in the window that carry phase timing. Returns a measured cell with
    the ratio + per-component seconds, marking any orchestration phase that never
    recorded timing as ``unmeasured`` (the ratio is then ``partial``). A window
    where no run has phase timing degrades to the legacy ``{"unmeasured": reason}``
    so fully-legacy windows read exactly as before — never a wrong number.
    """
    comp = phase_overhead_components(runs)
    if not comp["any_timing"]:
        return {
            "unmeasured": "no phase timing (verify/review/verdict elapsed not recorded)"
        }
    implement = float(comp["implement_seconds"])
    components: dict[str, Any] = {}
    orchestration = 0.0
    partial = False
    for phase in ORCHESTRATION_PHASES:
        cell = comp["phases"][phase]
        if cell["runs_present"] == 0:
            components[phase] = {"unmeasured": "phase never timed in window"}
            partial = True
            continue
        seconds = round(float(cell["seconds"]), 3)
        components[phase] = {"seconds": seconds, "runs_present": cell["runs_present"]}
        orchestration += float(cell["seconds"])
    result: dict[str, Any] = {
        "implement_seconds": round(implement, 3),
        "orchestration_seconds": round(orchestration, 3),
        "components": components,
        "partial": partial,
    }
    if implement <= 0:
        result["ratio"] = None
        result["unmeasured"] = "no implement elapsed (run wall-clock missing)"
    else:
        result["ratio"] = round(orchestration / implement, 4)
    return result


PRUNE_STATUSES = frozenset({"done", "dry_run"})


def clear_leases_for_run(state: dict[str, Any], run_id: str) -> None:
    leases = state.setdefault("leases", {})
    for task_id, lease in list(leases.items()):
        if str(lease.get("run_id", "")) == run_id:
            leases.pop(task_id, None)


def remove_run_artifacts(
    root: Path, state: dict[str, Any], run_id: str
) -> dict[str, Any] | None:
    run = state.get("runs", {}).pop(run_id, None)
    if not run:
        return None
    clear_leases_for_run(state, run_id)
    run_dir_rel = str(run.get("run_dir", "") or "")
    if run_dir_rel:
        run_dir = (root / run_dir_rel).resolve()
        if run_dir.is_dir():
            shutil.rmtree(run_dir)
    return run


def heal_stale_worktree_record(root: Path, run: dict[str, Any]) -> bool:
    """Clear worktree fields when the directory they name is gone.

    Returns True when the record was healed. The clearing itself is delegated
    to `remove_run_worktree`, whose missing-path branch already does exactly
    this - but only after the existence check here, because that function
    removes a worktree that IS there. Nothing else clears the field, so a
    worktree removed by any route the tool did not take (an operator's own
    `git worktree remove`, a deleted checkout, a moved repo) leaves a record
    that `select_prune_run_ids` refuses forever.
    """
    rel = str(run.get("worktree_path", "") or "")
    if not rel or (root / rel).exists():
        return False
    remove_run_worktree(root, run)
    return True


def select_prune_run_ids(
    state: dict[str, Any],
    *,
    root: Path,
    run_id: str | None,
    older_than: dt.timedelta | None,
    keep_last: int | None,
    include_failed: bool,
) -> tuple[list[str], list[str], list[str]]:
    """Ids to prune, ids skipped for a live worktree, ids whose record healed."""
    statuses = set(PRUNE_STATUSES)
    if include_failed:
        statuses.add("failed")
    runs = state.get("runs", {})
    eligible = [rid for rid, run in runs.items() if run.get("status") in statuses]
    # Heal before filtering, so the worktree question below is about a real
    # directory rather than a leftover field. Scoped to prunable statuses:
    # a live run's cwd must not be re-pointed underneath it.
    healed = [rid for rid in eligible if heal_stale_worktree_record(root, runs[rid])]
    skipped_worktrees: list[str] = []
    if run_id:
        if run_id not in runs:
            die(f"run not found: {run_id}")
        if runs[run_id].get("status") not in statuses:
            die(
                f"run {run_id} has status {runs[run_id].get('status')}; "
                f"prune only supports {sorted(statuses)}"
            )
        eligible = [run_id]
    if older_than is not None:
        cutoff = dt.datetime.now(dt.timezone.utc) - older_than
        eligible = [
            rid
            for rid in eligible
            if (ref := run_reference_time(runs[rid])) is not None and ref < cutoff
        ]
    if keep_last is not None:
        if keep_last < 0:
            die("--keep-last must be zero or positive")
        if keep_last > 0:
            by_task: dict[str, list[tuple[dt.datetime, str]]] = {}
            min_time = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
            for rid in eligible:
                task_id = str(runs[rid].get("task_id", ""))
                ref = run_reference_time(runs[rid]) or min_time
                by_task.setdefault(task_id, []).append((ref, rid))
            keep_ids: set[str] = set()
            for items in by_task.values():
                items.sort(key=lambda item: item[0], reverse=True)
                for _, rid in items[:keep_last]:
                    keep_ids.add(rid)
            eligible = [rid for rid in eligible if rid not in keep_ids]
    for rid in list(eligible):
        if runs[rid].get("worktree_path"):
            skipped_worktrees.append(rid)
    eligible = [rid for rid in eligible if rid not in skipped_worktrees]
    return sorted(eligible), sorted(skipped_worktrees), sorted(healed)


def prune_old_cleanup_reports(
    root: Path, *, older_than: dt.timedelta, dry_run: bool
) -> list[str]:
    cleanup_dir = app_path(root) / "cleanup"
    if not cleanup_dir.is_dir():
        return []
    cutoff = dt.datetime.now(dt.timezone.utc) - older_than
    removed: list[str] = []
    for path in sorted(cleanup_dir.glob("cleanup-*.json")):
        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
        if mtime >= cutoff:
            continue
        rel = str(path.relative_to(root))
        if not dry_run:
            path.unlink(missing_ok=True)
        removed.append(rel)
    return removed
