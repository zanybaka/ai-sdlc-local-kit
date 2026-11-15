"""Scheduling domain for the ai-task CLI.

Standalone by design: imports only the stdlib, ai_task._shared, and Task
from ai_task.backlog - no subprocess, no state.json, no run/quota imports.
State reaches eligible_tasks/prune_stale_leases as a plain dict argument
(the caller loads and saves it), policy reaches every function as a plain
dict, and predict_task_files receives tracked files and git history as
arguments - the git-running providers (git_tracked_files,
git_recent_commit_files, enrich_signals_with_predictions) stay in the
entrypoint. If a future mover function drags in run lifecycle or journal
helpers (acquire_task_lease does - it stamps operator identity and
timestamps for state.json), that is a sign it belongs to a later Phase 35
slice, not here.
"""

from __future__ import annotations

import re
import sys
from typing import Any

from ai_task._shared import pid_alive
from ai_task.backlog import Task


def priority_rank(policy: dict[str, Any], priority: str) -> int:
    order = policy.get("priority", {}).get("order", ["P0", "P1", "P2", "P3"])
    try:
        return list(order).index(priority)
    except ValueError:
        return len(order)

def prune_stale_leases(state: dict[str, Any]) -> None:
    leases = state.setdefault("leases", {})
    for task_id, lease in list(leases.items()):
        run_id = str(lease.get("run_id", ""))
        run = state.get("runs", {}).get(run_id, {})
        if not run:
            continue
        # A waiting_quota run still owns its task: it is a recoverable wait whose
        # packet/worktree will be re-launched after reset, so its lease must survive
        # so resume reuses it instead of acquiring a duplicate lease.
        if run.get("status") == "waiting_quota":
            continue
        if run.get("status") in {"running", "paused"}:
            # An in-session run has no pid while the teamlead's subagent works;
            # it holds the task until worker-done or the timeout reaps it.
            if run.get("in_session"):
                continue
            pid = run.get("pid")
            if isinstance(pid, int) and pid_alive(pid):
                continue
        leases.pop(task_id, None)

def task_lease_message(
    state: dict[str, Any], task_id: str, take_lease: bool
) -> str | None:
    if take_lease:
        return None
    prune_stale_leases(state)
    lease = state.get("leases", {}).get(task_id)
    if not lease:
        return None
    holder = lease.get("run_id", "?")
    # Legacy lease rows carry no operator; name them "unknown"
    # so a same-machine collision is legible without crashing on old state.json.
    operator = lease.get("operator") or "unknown"
    return (
        f"task {task_id} is leased by run {holder}, operator {operator} "
        "(use --take-lease to override)"
    )

# Autonomous/headless selection lever. Bulk dispatch — `plan --bulk`,
# `parallel-plan`, the default `run` with no explicit id, and `backlog-order
# --autonomous` — must never pick a task that by definition needs the owner, or a
# headless runner spends a run on work it cannot deliver. This is the single
# chokepoint so the same gate can later also defer review-gated tasks: extend the
# reason function, not every call site. An explicit `ai-task run <id>` bypasses this
# gate (the operator addressed the task by name); an owner-only task then still meets
# the existing coordination-only refusal in choose_backend_order/run.
AUTONOMOUS_OWNER_ONLY_AGENTS = frozenset({"human"})


def autonomous_skip_reason(task: Task) -> str | None:
    """Why `task` is ineligible for autonomous/headless selection, or None if eligible."""
    if (task.agent or "auto").strip().lower() in AUTONOMOUS_OWNER_ONLY_AGENTS:
        return "owner-only (Agent: human)"
    return None


def owner_only_open_tasks(tasks: list[Task]) -> list[Task]:
    """Open tasks an autonomous run would skip (owner-only), in file order."""
    return [
        task
        for task in tasks
        if task.is_open and autonomous_skip_reason(task) is not None
    ]


def format_owner_only_remaining(tasks: list[Task]) -> str | None:
    """One-line 'owner-only remaining' note for autonomous commands, or None."""
    owner_only = owner_only_open_tasks(tasks)
    if not owner_only:
        return None
    ids = ", ".join(task.id for task in owner_only)
    return (
        f"owner-only remaining (skipped by autonomous selection; "
        f"run by explicit id to address): {ids}"
    )

def done_dependency_ids(
    tasks: list[Task], extra_done_ids: set[str] | None = None
) -> set[str]:
    """Ids that satisfy a `Depends on:`, for all three scheduling paths.

    Done active tasks plus `extra_done_ids` - work that left the active store.
    Rotation moves a closed task file to backlog/archive/tasks/, and the
    scheduler parses the active store only, so without those ids a dependency
    on archived work blocks its dependent forever. Callers that
    have the repo root pass archived_done_ids(root) from ai_task.backlog; this
    module stays free of filesystem reads, the same way state and policy
    arrive as plain arguments. An id nobody has filed is in neither set, so a
    typo still blocks and is still reported.
    """
    return {task.id for task in tasks if task.status == "x"} | set(
        extra_done_ids or ()
    )


def eligible_tasks(
    tasks: list[Task],
    state: dict[str, Any],
    policy: dict[str, Any],
    *,
    respect_leases: bool = True,
    autonomous: bool = False,
    extra_done_ids: set[str] | None = None,
) -> list[Task]:
    prune_stale_leases(state)
    done_ids = done_dependency_ids(tasks, extra_done_ids)
    active_ids = {
        run.get("task_id")
        for run in state.get("runs", {}).values()
        if run.get("status")
        in {"running", "paused", "needs_review", "fixing", "waiting_quota"}
    }
    selected: list[Task] = []
    for task in tasks:
        if not task.is_open or task.id in active_ids:
            continue
        if autonomous and autonomous_skip_reason(task) is not None:
            continue
        if respect_leases and task_lease_message(state, task.id, False):
            continue
        if any(dep not in done_ids for dep in task.depends_on):
            continue
        selected.append(task)
    return sorted(
        selected, key=lambda task: (priority_rank(policy, task.priority), task.index)
    )

def open_tasks_execution_order(
    tasks: list[Task],
    policy: dict[str, Any],
    *,
    extra_done_ids: set[str] | None = None,
) -> list[Task]:
    """Topological order of open tasks: deps before dependents; tie-break priority then file index."""
    done_ids = done_dependency_ids(tasks, extra_done_ids)
    open_tasks = [task for task in tasks if task.is_open]
    ordered: list[Task] = []
    remaining = list(open_tasks)
    while remaining:
        ready = [
            task
            for task in remaining
            if all(dep in done_ids for dep in task.depends_on)
        ]
        if not ready:
            print(
                "warning: cannot resolve dependency order for remaining open tasks; "
                "using file order for the rest",
                file=sys.stderr,
            )
            ready = sorted(remaining, key=lambda task: task.index)
        ready.sort(key=lambda task: (priority_rank(policy, task.priority), task.index))
        for task in ready:
            ordered.append(task)
            done_ids.add(task.id)
        remaining = [task for task in remaining if task.id not in {t.id for t in ready}]
    return ordered

def blocked_by_dependencies(
    tasks: list[Task],
    state: dict[str, Any],
    *,
    extra_done_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    done_ids = done_dependency_ids(tasks, extra_done_ids)
    blocked: list[dict[str, Any]] = []
    for task in tasks:
        if not task.is_open:
            continue
        missing = [dep for dep in task.depends_on if dep not in done_ids]
        if missing:
            blocked.append({"id": task.id, "title": task.title, "waiting_for": missing})
    return blocked

def dependency_cycles(tasks: list[Task]) -> list[str]:
    """Detect circular Depends on chains (detect-only; returns human-readable cycle paths)."""
    known = {task.id for task in tasks}
    graph = {
        task.id: [dep for dep in task.depends_on if dep in known] for task in tasks
    }
    cycles: list[str] = []
    visited: set[str] = set()
    on_path: list[str] = []
    index_on_path: dict[str, int] = {}

    def visit(node: str) -> None:
        if node in index_on_path:
            start = index_on_path[node]
            loop = [*on_path[start:], node]
            cycles.append(" -> ".join(loop))
            return
        if node in visited:
            return
        visited.add(node)
        index_on_path[node] = len(on_path)
        on_path.append(node)
        for dep in graph.get(node, []):
            visit(dep)
        on_path.pop()
        index_on_path.pop(node, None)

    for task in tasks:
        visit(task.id)
    return list(dict.fromkeys(cycles))

def warn_dependency_cycles(tasks: list[Task]) -> None:
    for cycle in dependency_cycles(tasks):
        print(f"warning: dependency cycle detected: {cycle}", file=sys.stderr)

PATH_TOKEN_RE = re.compile(
    r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.*-]+|\b[A-Za-z0-9_.-]+\.(?:py|ts|tsx|js|jsx|cs|go|md|json|toml|yml|yaml|qml)\b",
    re.IGNORECASE,
)
BROAD_SCOPE_WORDS = (
    "whole repo",
    "entire repo",
    "entire codebase",
    "all files",
    "whole codebase",
)
LAYER_HINTS: dict[str, tuple[str, ...]] = {
    "frontend": (
        "frontend",
        "ui",
        "qml",
        "react",
        "vue",
        "svelte",
        "tsx",
        "jsx",
        "widget",
    ),
    "backend": ("backend", "api", "server", "service", "grpc", "rest"),
    "infra": ("ci", "docker", "workflow", "terraform", "deploy", "pipeline"),
    "tests": ("tests/", "test_", "pytest", "jest", "vitest"),
}


def extract_path_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in PATH_TOKEN_RE.finditer(text):
        token = match.group(0).strip().lower().replace("\\", "/")
        if token in {"agents.md", "backlog.md", "changelog.md"}:
            continue
        tokens.add(token)
    return tokens

# Collision-aware file prediction. CamelCase identifiers in task
# text (CommandCard, RoleCrossCut) usually name components whose files the task
# will touch even when no explicit path is written.
COMPONENT_HINT_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*[a-z][A-Z][A-Za-z0-9]*\b")
COMPONENT_HINT_MIN_LEN = 5
COMPONENT_HINT_STOPWORDS = frozenset(
    {
        "bitbucket",
        "camelcase",
        "changelog",
        "graphql",
        "javascript",
        "github",
        "gitlab",
        "macbook",
        "mongodb",
        "postgresql",
        "powershell",
        "pyproject",
        "pytest",
        "techspec",
        "typescript",
        "websocket",
    }
)
MAX_PREDICTED_FILES = 64
MAX_EXACT_PACKING_TASKS = 16

def task_block_body(task: Task) -> str:
    return "\n".join(task.block.splitlines()[1:])


def extract_component_hints(text: str) -> set[str]:
    """CamelCase component names mentioned in task text (e.g. CommandCard)."""
    hints: set[str] = set()
    for match in COMPONENT_HINT_RE.finditer(text):
        word = match.group(0)
        if len(word) < COMPONENT_HINT_MIN_LEN:
            continue
        if word.lower() in COMPONENT_HINT_STOPWORDS:
            continue
        hints.add(word)
    return hints

def predict_task_files(
    task_text: str,
    *,
    tracked_files: list[str] | None = None,
    history: list[tuple[str, list[str]]] | None = None,
) -> dict[str, Any]:
    """Predict the file set a task will touch.

    Sources, in confidence order:
    - explicit path tokens in the task text (bare names expand to tracked paths);
    - CamelCase component hints mapped to tracked files (or kept as abstract
      ``component:<name>`` markers when the repo has no matching file);
    - files changed by recent commits about the same components.
    All entries are normalized to lowercase forward-slash paths.
    """
    tracked = [item.replace("\\", "/") for item in (tracked_files or [])]
    tokens = extract_path_tokens(task_text)
    hints = extract_component_hints(task_text)
    from_tokens: set[str] = set()
    from_hints: set[str] = set()
    from_history: set[str] = set()

    for token in tokens:
        matches = [
            item.lower()
            for item in tracked
            if item.lower() == token or item.lower().endswith("/" + token)
        ]
        from_tokens.update(matches or [token])

    for hint in hints:
        needle = hint.lower()
        matches = [
            item.lower()
            for item in tracked
            if needle in item.rsplit("/", 1)[-1].lower()
        ]
        from_hints.update(matches or [f"component:{needle}"])

    needles = {hint.lower() for hint in hints}
    needles.update(
        token.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower() for token in tokens
    )
    needles = {needle for needle in needles if len(needle) >= 4}
    for subject, files in history or []:
        subject_lower = subject.lower()
        if not any(needle in subject_lower for needle in needles):
            continue
        for path in files:
            normalized = path.replace("\\", "/").lower()
            if any(needle in normalized.rsplit("/", 1)[-1] for needle in needles):
                from_history.add(normalized)

    predicted = sorted(from_tokens | from_hints | from_history)
    return {
        "predicted_files": predicted[:MAX_PREDICTED_FILES],
        "sources": {
            "path_tokens": sorted(from_tokens),
            "component_hints": sorted(from_hints),
            "git_history": sorted(from_history),
        },
        "component_hints": sorted(hints),
    }


def broad_scope_words_present(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in BROAD_SCOPE_WORDS)


def task_scope_signals(task: Task) -> dict[str, Any]:
    body = task_block_body(task)
    tokens = extract_path_tokens(body)
    lowered = body.lower()
    broad = not tokens or any(word in lowered for word in BROAD_SCOPE_WORDS)
    layers: list[str] = []
    for layer, hints in LAYER_HINTS.items():
        if any(hint in lowered for hint in hints) or any(
            hint in " ".join(tokens) for hint in hints
        ):
            layers.append(layer)
    return {
        "task_id": task.id,
        "priority": task.priority,
        "size": task.size,
        "depends_on": list(task.depends_on),
        "path_tokens": sorted(tokens),
        "scope_broad": broad,
        "layers": layers or ["unknown"],
        "risk_gates": [],
    }


def parallel_policy(policy: dict[str, Any]) -> dict[str, Any]:
    raw = policy.get("parallel", {})
    return raw if isinstance(raw, dict) else {}


# W2 overlap-gate warn threshold — override in policy [parallel] overlap_warn_share.
PARALLEL_OVERLAP_WARN_SHARE_DEFAULT = 0.3


def parallel_overlap_warn_share(policy: dict[str, Any]) -> float:
    """W2 overlap-gate warn threshold: tasks on most-contended file / batch size.

    Read from policy ``[parallel] overlap_warn_share`` so a retro conclusion
    like "this repo needs 20%" has a durable per-repo home;
    local value wins on policy sync. Junk values fall back to the default,
    valid values are clamped to 0..1.
    """
    raw = parallel_policy(policy).get(
        "overlap_warn_share", PARALLEL_OVERLAP_WARN_SHARE_DEFAULT
    )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return PARALLEL_OVERLAP_WARN_SHARE_DEFAULT
    return min(max(value, 0.0), 1.0)


def tasks_block_parallel(task_a: Task, task_b: Task) -> bool:
    return task_b.id in task_a.depends_on or task_a.id in task_b.depends_on


def _file_like(entry: str) -> bool:
    last = entry.rsplit("/", 1)[-1]
    return "." in last and not last.startswith("*")


def predicted_files_collision(
    files_a: set[str], files_b: set[str]
) -> tuple[str, list[str]] | None:
    """Why two predicted file sets collide, or None when they are disjoint.
    """
    if not files_a or not files_b:
        return "unknown scope (no predicted files for at least one task)", []
    shared = sorted(files_a & files_b)
    if shared:
        listed = ", ".join(shared[:4])
        more = f" (+{len(shared) - 4} more)" if len(shared) > 4 else ""
        return f"shared predicted files: {listed}{more}", shared
    # A bare file name (no directory) claims that name anywhere in the tree.
    for bare_side, full_side in ((files_a, files_b), (files_b, files_a)):
        bare = {e for e in bare_side if "/" not in e and ":" not in e and _file_like(e)}
        for name in sorted(bare):
            hits = sorted(f for f in full_side if f.rsplit("/", 1)[-1] == name)
            if hits:
                return f"shared predicted file name: {name} ({hits[0]})", [
                    name,
                    *hits[:3],
                ]
    # An extensionless path entry claims the whole directory subtree.
    for claim_side, file_side in ((files_a, files_b), (files_b, files_a)):
        claims = {
            e.rstrip("*").rstrip("/")
            for e in claim_side
            if "/" in e and not _file_like(e)
        }
        for claim in sorted(claims):
            hits = sorted(
                f for f in file_side if f == claim or f.startswith(claim + "/")
            )
            if hits:
                return f"directory claim {claim}/ overlaps {hits[0]}", [
                    claim,
                    *hits[:3],
                ]
    return None


def pair_predicted_files(sig: dict[str, Any]) -> set[str]:
    predicted = sig.get("predicted_files")
    if predicted:
        return set(predicted)
    return set(sig.get("path_tokens", []))


def can_parallel_pair(
    sig_a: dict[str, Any],
    sig_b: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[bool, list[str]]:
    reasons_against: list[str] = []
    par = parallel_policy(policy)
    if (sig_a["scope_broad"] or sig_b["scope_broad"]) and par.get(
        "sequential_on_broad_scope", True
    ):
        reasons_against.append("broad scope on at least one task")
    if (sig_a["priority"] == "P0" or sig_b["priority"] == "P0") and par.get(
        "sequential_on_any_p0_risk", True
    ):
        reasons_against.append("P0 task in pair")
    collision = predicted_files_collision(
        pair_predicted_files(sig_a), pair_predicted_files(sig_b)
    )
    if collision is not None:
        reasons_against.append(collision[0])
    elif not par.get("allow_cross_layer", True) and sig_a["layers"] != sig_b["layers"]:
        reasons_against.append("cross-layer disabled by policy")
    if not par.get("allow_mixed_size", True) and sig_a["size"] != sig_b["size"]:
        reasons_against.append("mixed size disabled by policy")
    if reasons_against:
        return False, reasons_against
    return True, ["disjoint predicted files or policy allows cross-layer"]


def build_collision_edges(
    tasks: list[Task],
    signals: dict[str, dict[str, Any]],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Conflict graph over the batch: one edge per pair that must not share a wave."""
    edges: list[dict[str, Any]] = []
    for pos, task_a in enumerate(tasks):
        for task_b in tasks[pos + 1 :]:
            if tasks_block_parallel(task_a, task_b):
                edges.append(
                    {
                        "tasks": [task_a.id, task_b.id],
                        "reason": "in-batch dependency",
                        "shared_files": [],
                    }
                )
                continue
            pair_ok, reasons = can_parallel_pair(
                signals[task_a.id], signals[task_b.id], policy
            )
            if pair_ok:
                continue
            shared = sorted(
                pair_predicted_files(signals[task_a.id])
                & pair_predicted_files(signals[task_b.id])
            )
            edges.append(
                {
                    "tasks": [task_a.id, task_b.id],
                    "reason": "; ".join(reasons),
                    "shared_files": shared,
                }
            )
    return edges


def max_disjoint_subset(
    candidates: list[str],
    conflicts: set[frozenset[str]],
    cap: int,
) -> list[str]:
    """Largest pairwise-disjoint subset of candidates, capped at cap.

    Exact search (with pruning) up to MAX_EXACT_PACKING_TASKS candidates;
    greedy first-fit beyond that. Ties prefer earlier candidates so backlog
    priority order is respected.
    """
    if cap <= 1 or len(candidates) == 1:
        return candidates[:1]
    if len(candidates) > MAX_EXACT_PACKING_TASKS:
        chosen: list[str] = []
        for candidate in candidates:
            if len(chosen) >= cap:
                break
            if all(frozenset((candidate, c)) not in conflicts for c in chosen):
                chosen.append(candidate)
        return chosen
    best: list[str] = []

    def search(idx: int, chosen: list[str]) -> None:
        nonlocal best
        if len(chosen) > len(best):
            best = list(chosen)
        if len(best) >= cap or len(chosen) >= cap or idx >= len(candidates):
            return
        if len(chosen) + (len(candidates) - idx) <= len(best):
            return
        candidate = candidates[idx]
        if all(frozenset((candidate, c)) not in conflicts for c in chosen):
            chosen.append(candidate)
            search(idx + 1, chosen)
            chosen.pop()
        search(idx + 1, chosen)

    search(0, [])
    return best


def pack_disjoint_waves(
    tasks: list[Task],
    conflicts: set[frozenset[str]],
    max_concurrent: int,
) -> tuple[list[list[str]], list[str]]:
    """Pack maximal disjoint waves under max_concurrent.

    Each wave is the largest set of dependency-ready tasks with no collision
    edge between any pair, so hot-file tasks spread across waves while
    independent tasks fill the remaining width instead of over-serializing.
    """
    order = {task.id: pos for pos, task in enumerate(tasks)}
    in_batch = {task.id for task in tasks}
    depends = {
        task.id: {dep for dep in task.depends_on if dep in in_batch} for task in tasks
    }
    waves: list[list[str]] = []
    notes: list[str] = []
    scheduled: set[str] = set()
    remaining = [task.id for task in tasks]
    while remaining:
        ready = [tid for tid in remaining if depends[tid] <= scheduled]
        if not ready:
            ready = [remaining[0]]
            notes.append(f"dependency cycle fallback: scheduling {remaining[0]} alone")
        wave = max_disjoint_subset(ready, conflicts, max_concurrent) or [ready[0]]
        wave.sort(key=order.__getitem__)
        if len(wave) == 1 and len(ready) > 1:
            notes.append(
                f"serial wave for {wave[0]} (collision edges block pairing "
                "with every other ready task)"
            )
        waves.append(wave)
        scheduled.update(wave)
        remaining = [tid for tid in remaining if tid not in scheduled]
    if len(tasks) > 1:
        widths = "/".join(str(len(wave)) for wave in waves)
        notes.append(
            f"wave packing: widths {widths} under max_concurrent {max_concurrent}"
        )
    return waves, notes


def build_parallel_waves(
    tasks: list[Task],
    signals: dict[str, dict[str, Any]],
    policy: dict[str, Any],
) -> tuple[list[list[str]], list[str], list[dict[str, Any]]]:
    par = parallel_policy(policy)
    max_concurrent = int(par.get("max_concurrent", 3))
    edges = build_collision_edges(tasks, signals, policy)
    conflicts = {frozenset(edge["tasks"]) for edge in edges}
    waves, notes = pack_disjoint_waves(tasks, conflicts, max_concurrent)
    return waves, notes, edges


# --- Wave batch sizing ---


def resolve_wave_batch_size(
    *,
    explicit_batch: int | None,
    auto_batch: bool,
    policy: dict[str, Any],
    eligible_count: int,
) -> tuple[int, str]:
    batch_cfg = policy.get("batch", {})
    default_size = int(batch_cfg.get("default_size", 1))
    max_size = int(batch_cfg.get("max_size", default_size))
    auto_target = int(batch_cfg.get("auto_target", max_size))
    if explicit_batch is not None:
        mode = "explicit"
        requested = explicit_batch
    elif auto_batch:
        mode = "auto"
        requested = auto_target
    else:
        mode = "default"
        requested = default_size
    requested = max(0, requested)
    max_size = max(0, max_size)
    capped = min(requested, max_size)
    resolved = min(capped, max(0, eligible_count))
    if eligible_count <= 0:
        reasoning = "eligible_none"
    elif eligible_count < capped:
        reasoning = f"eligible_only_{eligible_count}"
    elif resolved < requested and resolved == max_size and max_size < requested:
        reasoning = "max_size_cap"
    elif mode == "auto" and eligible_count > requested:
        reasoning = "auto_target_cap"
    else:
        reasoning = {
            "explicit": "explicit_batch",
            "auto": "auto_target",
            "default": "default_size",
        }[mode]
    return resolved, reasoning
