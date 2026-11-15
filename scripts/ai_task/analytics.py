"""Project analytics report generator (`ai-task report` dashboard).

python scripts/analytics.py --repo /path/to/project
    python scripts/analytics.py --repo . --output /tmp/out/report.html
    python scripts/analytics.py --repo . --since 7d
    ai-task report                         # via ai-task subcommand
    ai-task report --since 7d             # filter runs to last 7 days
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html import escape as _escape_html
from pathlib import Path
from types import ModuleType

from ai_task._shared import die
from ai_task.backlog import (
    Task,
    archive_task_files,
    parse_backlog_blocks,
    parse_task_files,
)


def networkx_available() -> bool:
    """True when the optional analytics deps (networkx) are importable.
    """
    return importlib.util.find_spec("networkx") is not None


class _LazyModule:
    """Import-on-first-use proxy for an optional analytics dependency.

    importing ``ai_task.analytics`` must work without networkx /
    numpy / plotly, so the heavy deps resolve on first attribute access
    inside the chart/DAG builders and exit with an actionable install hint
    when missing. ``ai-task report`` auto-installs the deps before invoking
    this module, so operators normally never see the error.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._module: ModuleType | None = None

    def __getattr__(self, attr: str) -> object:
        if self._module is None:
            try:
                # Semgrep non-literal-import is a false positive: _name comes only from the literal
                # module names of the _LazyModule instances below (networkx, numpy, plotly), never from input.
                # nosemgrep: non-literal-import
                self._module = importlib.import_module(self._name)
            except ModuleNotFoundError:
                die(
                    "install networkx for analytics: optional dependency "
                    f"'{self._name}' is missing; run `pip install -r "
                    "requirements-analytics.txt` (or `ai-task report`, "
                    "which auto-installs the analytics deps)"
                )
        return getattr(self._module, attr)


nx = _LazyModule("networkx")
np = _LazyModule("numpy")
go = _LazyModule("plotly.graph_objects")

# `c` is mapped explicitly. The `.get(..., "open")` fallback
# below would otherwise report dropped work as still open, which is the
# reporting lie the marker was added to remove.
STATUS_MAP = {"x": "done", "~": "deferred", " ": "open", "c": "canceled"}
SIZE_WEIGHTS = {"S": 2, "M": 3, "L": 5, "": 3}
SIZE_ORDER = ["S", "M", "L"]
PRIO_ORDER = ["P0", "P1", "P2", "P3"]

# Recurrence / sibling-rate defaults — mirror ai-task.py and policy [analytics].
# Overridden per repo by .ai-task/policies/default.toml when present.
SIBLING_MARKERS_DEFAULT = ("sibling of", "regression of", "root cause of", "re-drift")
SIBLING_WARN_RATE_DEFAULT = 0.5

# Rotated backlog archives (sdlc-backlog-rotate skill) — mirror ai-task.py
# DEFAULT_BACKLOG_ARCHIVE_GLOB and policy [analytics] archive_glob. The report
# and recurrence are AUDIT readers and merge these so delivered history
# survives rotation; delivery readers (plan / backlog-order /
# dor) schedule from the active BACKLOG.md only and never read the archive.
ARCHIVE_GLOB_DEFAULT = "backlog/archive/BACKLOG-*.md"

COLORS = {
    "done": "#10B981",
    "open": "#3B82F6",
    "deferred": "#D1D5DB",
    "canceled": "#9CA3AF",
    "claude": "#6366F1",
    "cursor_codex": "#F59E0B",
    "cursor_auto": "#94A3B8",
    "devin": "#14B8A6",
    "approve": "#10B981",
    "rework": "#EF4444",
    "neutral": "#CBD5E1",
}


# ---------------------------------------------------------------------------
# 1. Parse the backlog store
# ---------------------------------------------------------------------------
#
# The dashboard used to carry its own checkbox/field regexes here, and they
# desynced from the contract (field_re knew only Priority/Size/Depends
# on/Verify - it could not see Agent/Source/Incident). All block parsing now
# goes through ai_task.backlog.parse_backlog_blocks; this module only maps
# Task objects into the report's row shape and keeps the dashboard-only
# extras (milestone header, the "## Open / Deferred" section convention).

_MILESTONE_RE = re.compile(r"^# BACKLOG.*\((\w+)\)")
_DEFERRED_PHASE_RE = re.compile(r"^Open / Deferred", re.IGNORECASE)
_NUMBERED_PHASE_RE = re.compile(r"^Phase \d")


def _task_row(task: Task, milestone: str) -> dict:
    phase = task.phase or "Phase ?"
    row_milestone = milestone
    if _DEFERRED_PHASE_RE.match(phase):
        phase, row_milestone = "Deferred", "M2+"
    return {
        "id": task.id,
        "title": task.title,
        "status": STATUS_MAP.get(task.status, "open"),
        "phase": phase,
        "milestone": row_milestone,
        "priority": task.priority,
        "size": task.size,
        "depends_on": list(task.depends_on),
        "agent": task.agent,
        "source": task.source,
        "incident": task.incident,
    }


def parse_backlog(path: Path) -> dict[str, dict]:
    """One backlog file -> {task_id: row}, via the canonical block parser."""
    lines = path.read_text().splitlines()
    milestone = "M1"
    for line in lines:
        if mm := _MILESTONE_RE.match(line.strip()):
            milestone = mm.group(1)
            break
    return {
        task.id: _task_row(task, milestone)
        for task in parse_backlog_blocks(lines)
    }


def active_backlog_rows(repo_root: Path) -> dict[str, dict]:
    """Rows for the ACTIVE store: per-task files when present, else inline."""
    file_tasks = parse_task_files(repo_root)
    if file_tasks:
        return {task.id: _task_row(task, "M1") for task in file_tasks}
    return parse_backlog(repo_root / "BACKLOG.md")


def analytics_policy_section(repo_root: Path) -> dict:
    """The [analytics] section of .ai-task/policies/default.toml, or {}."""
    policy_path = repo_root / ".ai-task" / "policies" / "default.toml"
    if not policy_path.exists():
        return {}
    try:
        import tomllib

        section = tomllib.loads(policy_path.read_text()).get("analytics", {})
        return section if isinstance(section, dict) else {}
    except Exception:  # noqa: BLE001 - policy is optional for the dashboard
        return {}


def archive_glob_from_policy(section: dict) -> str:
    raw = section.get("archive_glob")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return ARCHIVE_GLOB_DEFAULT


def archive_backlog_paths(repo_root: Path, glob_pattern: str) -> list[Path]:
    """Rotated backlog archives matching the glob; [] when none (normal case)."""
    try:
        return sorted(p for p in repo_root.glob(glob_pattern) if p.is_file())
    except (OSError, ValueError):
        return []


def load_backlog(repo_root: Path) -> tuple[dict[str, dict], list[str]]:
    """Active BACKLOG.md merged with rotated archives (audit reader).

    Archive tasks are marked ``archived=True`` with milestone ``ARCH`` (and
    phase ``Archived`` when the flat archive sections carry no phase heading)
    so charts and tables can distinguish live scope from rotated history.
    De-duplicates by task id with the active file taking precedence. Archive
    read failures degrade gracefully to the readable files (active-only in
    the worst case); each failure is returned as a warning string. Returns
    ``(tasks, warnings)``.
    """
    warnings: list[str] = []
    merged: dict[str, dict] = {}
    section = analytics_policy_section(repo_root)
    glob_pattern = archive_glob_from_policy(section)
    archive_sources = list(archive_backlog_paths(repo_root, glob_pattern))
    # Rotated-out per-task files are archives too.
    archive_sources.extend(archive_task_files(repo_root))
    for archive_path in archive_sources:
        rel = archive_path.relative_to(repo_root).as_posix()
        try:
            archived_tasks = parse_backlog(archive_path)
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(
                f"backlog archive unreadable, report degraded to remaining "
                f"files: {rel} ({exc.__class__.__name__})"
            )
            continue
        for tid, t in archived_tasks.items():
            t["archived"] = True
            t["milestone"] = "ARCH"
            if not _NUMBERED_PHASE_RE.match(t["phase"]):
                # Flat archive sections ("## Archived from active ...") carry
                # no real phase; a rotated task file keeps its `## Phase N`.
                t["phase"] = "Archived"
            merged[tid] = t
    active = active_backlog_rows(repo_root)
    for tid, t in active.items():
        t["archived"] = False
        merged[tid] = t  # active store wins on id collision
    return merged, warnings


def _scan_backlog_blocks(path: Path) -> dict[str, tuple[str, str]]:
    """One backlog file → ordered {task_id: (status_char, block_text_lower)}.

    Canonical block parser; the old private checkbox regex is
    gone.
    """
    return {
        task.id: (task.status, task.block.lower())
        for task in parse_backlog_blocks(path.read_text().splitlines())
    }


def _active_store_blocks(path: Path) -> dict[str, tuple[str, str]]:
    """Blocks of the ACTIVE store rooted at an active-backlog path.

    When the repo that owns ``path`` keeps per-task files, the
    root backlog file is a generated index with no parseable blocks, so the
    store directory is read instead.
    """
    file_tasks = parse_task_files(path.parent)
    if file_tasks:
        return {
            task.id: (task.status, task.block.lower()) for task in file_tasks
        }
    return _scan_backlog_blocks(path)


def backlog_recurrence(
    path: Path,
    *,
    markers: tuple[str, ...] = SIBLING_MARKERS_DEFAULT,
    threshold: float = SIBLING_WARN_RATE_DEFAULT,
    archive_paths: list[Path] | None = None,
) -> dict:
    """Sibling/regression recurrence over delivered (- [x]) backlog tasks.

    Mirrors ai-task.py ``recurrence_metrics`` so the dashboard surfaces the same
    signal without an extra subprocess. Scans full task blocks (title + context
    + DoD), not just titles, since markers usually live in Task Context.

    ``archive_paths`` merges rotated backlog archives so the
    delivered population survives sdlc-backlog-rotate; ids are de-duplicated with
    the active file taking precedence, and unreadable archive files degrade
    gracefully to the readable subset with a warning recorded in
    ``archive_warnings``.
    """
    markers_l = [m.lower() for m in markers]
    result: dict = {
        "available": False,
        "delivered_count": 0,
        "recurrence_count": 0,
        "sibling_rate": None,
        "threshold": threshold,
        "sibling_task_ids": [],
        "archive_files": [],
        "archive_warnings": [],
    }
    if not path.exists():
        return result
    merged: dict[str, tuple[str, str]] = {}
    archive_files: list[str] = []
    archive_warnings: list[str] = []
    for archive_path in archive_paths or []:
        try:
            merged.update(_scan_backlog_blocks(archive_path))
        except (OSError, UnicodeDecodeError) as exc:
            archive_warnings.append(
                f"backlog archive unreadable, recurrence degraded to remaining "
                f"files: {archive_path.name} ({exc.__class__.__name__})"
            )
            continue
        archive_files.append(str(archive_path))
    merged.update(_active_store_blocks(path))  # active store wins on id collision
    delivered_ids = [tid for tid, (status, _) in merged.items() if status == "x"]
    matched_ids = [
        tid
        for tid in delivered_ids
        if any(m in merged[tid][1] for m in markers_l)
    ]
    delivered = len(delivered_ids)
    rate = round(len(matched_ids) / delivered, 4) if delivered else None
    result.update(
        available=True,
        delivered_count=delivered,
        recurrence_count=len(matched_ids),
        sibling_rate=rate,
        sibling_task_ids=matched_ids,
        archive_files=archive_files,
        archive_warnings=archive_warnings,
    )
    return result


def load_recurrence(repo_root: Path) -> dict:
    """Compute recurrence using policy [analytics] overrides when present.

    Audit reader: merges rotated backlog archives ([analytics] archive_glob,
    default ``backlog/archive/BACKLOG-*.md``) with the active backlog.
    """
    markers: tuple[str, ...] = SIBLING_MARKERS_DEFAULT
    threshold = SIBLING_WARN_RATE_DEFAULT
    backlog_rel = "BACKLOG.md"
    section = analytics_policy_section(repo_root)
    raw = section.get("recurrence_markers")
    if isinstance(raw, list) and any(str(x).strip() for x in raw):
        markers = tuple(str(x).strip() for x in raw if str(x).strip())
    warn = section.get("recurrence_warn_rate")
    if isinstance(warn, (int, float)):
        threshold = float(warn)
    rel = section.get("recurrence_backlog")
    if isinstance(rel, str) and rel.strip():
        backlog_rel = rel.strip()
    archive_paths = archive_backlog_paths(
        repo_root, archive_glob_from_policy(section)
    )
    # Rotated-out per-task files are archives too.
    archive_paths.extend(archive_task_files(repo_root))
    return backlog_recurrence(
        repo_root / backlog_rel,
        markers=markers,
        threshold=threshold,
        archive_paths=archive_paths,
    )


# ---------------------------------------------------------------------------
# 2. DAG + critical path
# ---------------------------------------------------------------------------


def build_dag(tasks: dict) -> nx.DiGraph:
    G = nx.DiGraph()
    for tid, t in tasks.items():
        G.add_node(tid, **t, weight=SIZE_WEIGHTS.get(t["size"], 3))
    for tid, t in tasks.items():
        for dep in t["depends_on"]:
            if dep in tasks:
                G.add_edge(dep, tid)
    return G


def critical_path(G: nx.DiGraph, tasks: dict) -> list[str]:
    open_nodes = {n for n, d in tasks.items() if d["status"] == "open"}
    sub = G.subgraph(open_nodes).copy()
    if not nx.is_directed_acyclic_graph(sub):
        return []
    try:
        return nx.dag_longest_path(sub, weight="weight")
    except Exception:  # noqa: BLE001 - degrade to no critical path
        return []


# ---------------------------------------------------------------------------
# 3. Load run data
# ---------------------------------------------------------------------------


def load_runs(repo_root: Path) -> tuple[list[dict], dict]:
    result = subprocess.run(
        ["ai-task", "--repo", str(repo_root), "status", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    data = __import__("json").loads(result.stdout)
    return data.get("runs", []), data


def parse_dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def run_duration_s(r: dict) -> float | None:
    c, f = parse_dt(r.get("created_at")), parse_dt(r.get("finished_at"))
    if c and f:
        return max(0.0, (f - c).total_seconds())
    return None


def enrich_runs(runs: list[dict], tasks: dict) -> list[dict]:
    """Add phase/priority/size/duration_s to each run from backlog."""
    for r in runs:
        t = tasks.get(r.get("task_id"), {})
        r["phase"] = t.get("phase", "?")
        r["priority"] = t.get("priority", "?")
        r["size"] = t.get("size", "?")
        r["milestone"] = t.get("milestone", "?")
        r["duration_s"] = run_duration_s(r)
    return runs


_DURATION_RE = re.compile(r"^(\d+)(d|h|m|s)$")


def _run_reference_time(run: dict) -> datetime | None:
    """Return reference time for a run: finished_at → completed_at → created_at."""
    for key in ("finished_at", "completed_at", "created_at"):
        raw = run.get(key)
        if isinstance(raw, str) and raw.strip():
            try:
                val = raw.strip()
                if val.endswith("Z"):
                    val = val[:-1] + "+00:00"
                parsed = datetime.fromisoformat(val)
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except (ValueError, TypeError):
                pass
    return None


def parse_since_spec(spec: str) -> datetime:
    """Parse --since SPEC into a UTC-aware cutoff datetime.

    Accepted forms:
    - Relative duration:  ``7d``, ``24h``, ``30m``, ``60s``
      Interpreted as *now minus duration* (UTC).
    - Date only:          ``YYYY-MM-DD``
      Interpreted as start of that calendar day in UTC (i.e. 00:00:00 UTC).
    - Absolute datetime:  ISO-8601 with optional timezone, e.g.
      ``2026-05-27T14:30:00+03:00`` or ``2026-05-27T14:30:00Z``.
      Naive datetime (no tz) is treated as UTC.
    """
    s = spec.strip()

    # Relative duration (e.g. 7d, 24h)
    m = _DURATION_RE.fullmatch(s.lower())
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        seconds = {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
        return datetime.now(tz=timezone.utc) - timedelta(seconds=amount * seconds)

    # Date only: YYYY-MM-DD
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

    # Absolute ISO-8601 datetime
    val = s
    if val.endswith("Z"):
        val = val[:-1] + "+00:00"
    parsed = datetime.fromisoformat(val)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def filter_runs_since(runs: list[dict], cutoff: datetime) -> list[dict]:
    """Return only runs whose reference time is >= cutoff."""
    result = []
    for r in runs:
        ref = _run_reference_time(r)
        if ref is not None and ref >= cutoff:
            result.append(r)
        elif ref is None:
            # No timestamp at all — include to avoid silently dropping live runs
            result.append(r)
    return result


def filter_runs_last(runs: list[dict], n: int) -> list[dict]:
    """Return the N most recent runs sorted by (created_at, run_sort_key).

    Runs without a ``created_at`` timestamp are placed last (treated as oldest)
    so they do not crowd out timestamped runs.  If N >= len(runs) all runs are
    returned (preserving order).
    """

    def _sort_key(r: dict) -> tuple:
        raw = r.get("created_at") or ""
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            ts = (
                datetime.fromisoformat(raw).astimezone(timezone.utc).isoformat()
                if raw
                else ""
            )
        except (ValueError, TypeError):
            ts = ""
        sort_key = str(r.get("run_sort_key") or "")
        return (ts, sort_key)

    sorted_runs = sorted(runs, key=_sort_key, reverse=True)
    return sorted_runs[:n]


def filter_runs(
    runs: list[dict],
    *,
    since: datetime | None = None,
    last: int | None = None,
) -> list[dict]:
    """Unified run filter.  Exactly one of ``since`` or ``last`` may be set.

    Raises ``ValueError`` if both are provided.
    """
    if since is not None and last is not None:
        raise ValueError("--since and --last are mutually exclusive; use only one.")
    if since is not None:
        return filter_runs_since(runs, since)
    if last is not None:
        return filter_runs_last(runs, last)
    return list(runs)


# ---------------------------------------------------------------------------
# 4. Helper
# ---------------------------------------------------------------------------


def _phase_num(p: str) -> int:
    m = re.search(r"\d+", p)
    return int(m.group()) if m else 999


def _short_phase(p: str) -> str:
    return re.sub(r"Phase (\d+).*", r"Ph \1", p)


def _box(
    data_by_key: dict[str, list[float]],
    title: str,
    xlabel: str,
    ordered_keys: list[str] | None = None,
    color: str = "#6366F1",
    height: int = 340,
) -> go.Figure:
    keys = ordered_keys or sorted(data_by_key)
    keys = [k for k in keys if data_by_key.get(k)]
    fig = go.Figure()
    for k in keys:
        fig.add_trace(
            go.Box(
                y=data_by_key[k],
                name=k,
                marker_color=color,
                boxmean="sd",
                jitter=0.3,
                pointpos=-1.8,
            )
        )
    fig.update_layout(
        title=title,
        yaxis_title="Duration (min)",
        xaxis_title=xlabel,
        template="plotly_white",
        height=height,
        showlegend=False,
    )
    return fig


# ---------------------------------------------------------------------------
# 5. Chart functions
# ---------------------------------------------------------------------------

# ── Burndown ──────────────────────────────────────────────────────────────


def chart_burndown(runs: list[dict], tasks: dict) -> go.Figure:
    events = sorted(
        parsed
        for r in runs
        if r.get("status") == "done" and r.get("finished_at")
        if (parsed := parse_dt(r["finished_at"])) is not None
    )
    xs = events
    ys = list(range(1, len(xs) + 1))

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines+markers",
            name="Done (cumulative)",
            line={"color": COLORS["done"], "width": 2},
            marker={"size": 4},
        )
    )

    if len(xs) >= 2:
        t0 = xs[0].timestamp()
        xnum = [(x.timestamp() - t0) / 3600 for x in xs]
        c = np.polyfit(xnum, ys, 1)
        xext = [*xnum, xnum[-1] + 8]
        yext = [c[0] * x + c[1] for x in xext]
        xext_dt = [datetime.fromtimestamp(t0 + h * 3600, tz=timezone.utc) for h in xext]
        fig.add_trace(
            go.Scatter(
                x=xext_dt,
                y=yext,
                mode="lines",
                name="Trend",
                line={"color": "#F59E0B", "width": 2, "dash": "dash"},
            )
        )

    # Canceled work is dropped scope, not a burndown target.
    total = sum(
        1 for t in tasks.values() if t["status"] not in ("deferred", "canceled")
    )
    fig.add_hline(
        y=total,
        line_dash="dot",
        line_color="#10B981",
        annotation_text=f"Total non-deferred: {total}",
    )
    fig.update_layout(
        title="Burndown — cumulative done tasks",
        xaxis_title="Time (UTC)",
        yaxis_title="Tasks done",
        template="plotly_white",
        height=380,
    )
    return fig


# ── Velocity ──────────────────────────────────────────────────────────────


def chart_velocity(runs: list[dict]) -> go.Figure:
    buckets: Counter = Counter()
    for r in runs:
        if r.get("status") == "done" and r.get("finished_at"):
            dt = parse_dt(r["finished_at"])
            if dt is None:
                continue
            b = dt.replace(minute=0, second=0, microsecond=0, hour=(dt.hour // 2) * 2)
            buckets[b] += 1
    xs = sorted(buckets)
    fig = go.Figure(go.Bar(x=xs, y=[buckets[x] for x in xs], marker_color="#6366F1"))
    fig.update_layout(
        title="Velocity — tasks completed per 2-hour window",
        xaxis_title="Time (UTC)",
        yaxis_title="Tasks",
        template="plotly_white",
        height=320,
    )
    return fig


# ── Gantt ─────────────────────────────────────────────────────────────────


def chart_gantt(runs: list[dict]) -> go.Figure:
    done = [
        r
        for r in runs
        if r.get("status") == "done" and r.get("created_at") and r.get("finished_at")
    ]
    done.sort(key=lambda r: r["created_at"])

    backend_color = {
        "claude": COLORS["claude"],
        "cursor_codex": COLORS["cursor_codex"],
        "cursor_auto": COLORS["cursor_auto"],
        "devin": COLORS["devin"],
    }
    seen_backends: set[str] = set()

    fig = go.Figure()
    for i, r in enumerate(done):
        c = parse_dt(r["created_at"])
        f = parse_dt(r["finished_at"])
        if c is None or f is None:
            continue
        be = r.get("backend", "?")
        col = backend_color.get(be, "#CBD5E1")
        show_legend = be not in seen_backends
        seen_backends.add(be)
        fig.add_trace(
            go.Scatter(
                x=[c, f, f, c, c],
                y=[i - 0.4, i - 0.4, i + 0.4, i + 0.4, i - 0.4],
                fill="toself",
                mode="lines",
                fillcolor=col,
                line={"color": col, "width": 0.5},
                name=be,
                legendgroup=be,
                showlegend=show_legend,
                hovertemplate=(
                    f"<b>{r['task_id']}</b><br>"
                    f"{(r.get('task_title') or '')[:40]}<br>"
                    f"Backend: {be}<br>"
                    f"Start: {c.strftime('%H:%M')}<br>"
                    f"End:   {f.strftime('%H:%M')}<br>"
                    f"Dur:   {(f - c).total_seconds() / 60:.1f} min"
                    "<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        title="Gantt — all completed runs",
        xaxis_title="Time (UTC)",
        yaxis={
            "tickvals": list(range(len(done))),
            "ticktext": [r["task_id"] for r in done],
            "autorange": "reversed",
        },
        template="plotly_white",
        height=max(400, len(done) * 14),
        legend={"orientation": "h", "y": 1.02},
    )
    return fig


# ── Hour×Day heatmap ──────────────────────────────────────────────────────


def chart_heatmap(runs: list[dict]) -> go.Figure:
    grid: dict[tuple[int, int], int] = defaultdict(int)  # (weekday, hour) → count
    for r in runs:
        if r.get("status") == "done" and r.get("finished_at"):
            dt = parse_dt(r["finished_at"])
            if dt is None:
                continue
            grid[(dt.weekday(), dt.hour)] += 1

    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    hours = list(range(24))
    z = [[grid.get((d, h), 0) for h in hours] for d in range(7)]

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=[f"{h:02d}:00" for h in hours],
            y=days,
            colorscale="Blues",
            showscale=True,
            hovertemplate="Day: %{y}<br>Hour: %{x}<br>Runs: %{z}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Heatmap — completed runs by day & hour (UTC)",
        xaxis_title="Hour (UTC)",
        template="plotly_white",
        height=320,
    )
    return fig


# ── Duration histogram ────────────────────────────────────────────────────


def chart_duration_hist(runs: list[dict]) -> go.Figure:
    durs = [
        r["duration_s"] / 60
        for r in runs
        if r.get("status") == "done" and r.get("duration_s") is not None
    ]
    fig = go.Figure(
        go.Histogram(
            x=durs,
            nbinsx=30,
            marker_color="#6366F1",
            hovertemplate="~%{x:.1f} min — %{y} runs<extra></extra>",
        )
    )
    if durs:
        med = float(np.median(durs))
        p95 = float(np.percentile(durs, 95))
        fig.add_vline(
            x=med,
            line_dash="dash",
            line_color="#10B981",
            annotation_text=f"Median {med:.1f}m",
        )
        fig.add_vline(
            x=p95,
            line_dash="dot",
            line_color="#EF4444",
            annotation_text=f"p95 {p95:.1f}m",
        )
    fig.update_layout(
        title="Duration distribution (done runs)",
        xaxis_title="Duration (min)",
        yaxis_title="Count",
        template="plotly_white",
        height=320,
    )
    return fig


# ── Duration trend ────────────────────────────────────────────────────────


def chart_duration_trend(runs: list[dict]) -> go.Figure:
    pts = sorted(
        [
            (parsed, r["duration_s"] / 60)
            for r in runs
            if r.get("status") == "done"
            and r.get("finished_at")
            and r.get("duration_s")
            if (parsed := parse_dt(r["finished_at"])) is not None
        ],
        key=lambda x: x[0],
    )
    if not pts:
        return go.Figure()
    xs, ys = zip(*pts, strict=True)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="markers",
            name="Run duration",
            marker={"color": "#6366F1", "size": 5, "opacity": 0.6},
        )
    )
    # Rolling average (window=5)
    ys_arr = np.array(ys, dtype=float)
    w = min(5, len(ys_arr))
    roll = np.convolve(ys_arr, np.ones(w) / w, mode="valid")
    fig.add_trace(
        go.Scatter(
            x=list(xs[w - 1 :]),
            y=roll.tolist(),
            mode="lines",
            name=f"Rolling avg ({w})",
            line={"color": "#F59E0B", "width": 2},
        )
    )
    fig.update_layout(
        title="Duration trend over time — is the agent slowing down?",
        xaxis_title="Time (UTC)",
        yaxis_title="Duration (min)",
        template="plotly_white",
        height=340,
        legend={"orientation": "h", "y": 1.08},
    )
    return fig


# ── Concurrency ───────────────────────────────────────────────────────────


def chart_concurrency(runs: list[dict]) -> go.Figure:
    events: list[tuple[datetime, int]] = []
    for r in runs:
        c = parse_dt(r.get("created_at"))
        f = parse_dt(r.get("finished_at"))
        if c:
            events.append((c, +1))
        if f:
            events.append((f, -1))
    events.sort(key=lambda e: e[0])

    xs, ys, cur = [], [], 0
    for dt, delta in events:
        xs.append(dt)
        ys.append(cur)
        cur += delta
        xs.append(dt)
        ys.append(cur)

    fig = go.Figure(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines",
            fill="tozeroy",
            line={"color": "#6366F1", "width": 1.5},
            fillcolor="rgba(99,102,241,0.15)",
        )
    )
    fig.update_layout(
        title="Concurrency — simultaneous active runs",
        xaxis_title="Time (UTC)",
        yaxis_title="Parallel runs",
        template="plotly_white",
        height=300,
    )
    return fig


# ── Backend pie ───────────────────────────────────────────────────────────


def chart_backend_pie(runs: list[dict]) -> go.Figure:
    counts = Counter(r.get("backend", "?") for r in runs if r.get("status") == "done")
    labels, values = zip(*counts.most_common(), strict=True) if counts else ([], [])
    colors = [COLORS.get(b, "#CBD5E1") for b in labels]
    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            marker={"colors": colors},
            textinfo="label+percent+value",
            hole=0.35,
        )
    )
    fig.update_layout(
        title="Backend distribution (done runs)", template="plotly_white", height=340
    )
    return fig


# ── Duration by backend (box) ─────────────────────────────────────────────


def chart_duration_by_backend(runs: list[dict]) -> go.Figure:
    data: dict[str, list[float]] = defaultdict(list)
    for r in runs:
        if r.get("status") == "done" and r.get("duration_s") is not None:
            data[r.get("backend", "?")].append(r["duration_s"] / 60)
    return _box(data, "Duration by backend", "Backend")


# ── Backend over time ─────────────────────────────────────────────────────


def chart_backend_over_time(runs: list[dict]) -> go.Figure:
    buckets: dict[tuple, int] = defaultdict(int)
    for r in runs:
        if r.get("status") == "done" and r.get("finished_at"):
            dt = parse_dt(r["finished_at"])
            if dt is None:
                continue
            b = dt.replace(minute=0, second=0, microsecond=0, hour=(dt.hour // 2) * 2)
            buckets[(b, r.get("backend", "?"))] += 1

    all_times = sorted({k[0] for k in buckets})
    all_backends = sorted({k[1] for k in buckets})
    fig = go.Figure()
    for be in all_backends:
        fig.add_trace(
            go.Bar(
                x=all_times,
                y=[buckets.get((t, be), 0) for t in all_times],
                name=be,
                marker_color=COLORS.get(be, "#CBD5E1"),
            )
        )
    fig.update_layout(
        barmode="stack",
        title="Backend mix over time (2h buckets)",
        xaxis_title="Time (UTC)",
        yaxis_title="Runs",
        template="plotly_white",
        height=320,
        legend={"orientation": "h", "y": 1.08},
    )
    return fig


# ── Verdict by phase ──────────────────────────────────────────────────────


def chart_verdict_by_phase(runs: list[dict]) -> go.Figure:
    data: dict[str, Counter] = defaultdict(Counter)
    for r in runs:
        if r.get("verdict") and r.get("phase") and r["phase"] != "?":
            data[r["phase"]][r["verdict"]] += 1

    phases = sorted(data, key=_phase_num)
    short = [_short_phase(p) for p in phases]
    verdicts = ["approve", "rework", "defer", "split", "escalate"]
    vc = {v: COLORS.get(v, "#CBD5E1") for v in verdicts}

    fig = go.Figure()
    for v in verdicts:
        vals = [data[p].get(v, 0) for p in phases]
        if any(vals):
            fig.add_trace(
                go.Bar(
                    name=v,
                    x=short,
                    y=vals,
                    marker_color=vc[v],
                    customdata=phases,
                    hovertemplate="%{customdata}<br>" + v + ": %{y}<extra></extra>",
                )
            )
    fig.update_layout(
        barmode="stack",
        title="Verdict breakdown by phase",
        xaxis_title="Phase",
        yaxis_title="Runs",
        template="plotly_white",
        height=360,
        legend={"orientation": "h", "y": 1.08},
    )
    return fig


# ── Verify pass rate by phase ─────────────────────────────────────────────


def chart_verify_by_phase(runs: list[dict]) -> go.Figure:
    totals: Counter = Counter()
    passed: Counter = Counter()
    for r in runs:
        if r.get("verify_status") and r.get("phase") and r["phase"] != "?":
            totals[r["phase"]] += 1
            if r["verify_status"] == "passed":
                passed[r["phase"]] += 1

    phases = sorted(totals, key=_phase_num)
    short = [_short_phase(p) for p in phases]
    rates = [round(passed[p] / totals[p] * 100, 1) if totals[p] else 0 for p in phases]

    fig = go.Figure(
        go.Bar(
            x=short,
            y=rates,
            marker_color="#10B981",
            customdata=phases,
            hovertemplate="%{customdata}<br>Pass rate: %{y}%<extra></extra>",
        )
    )
    fig.add_hline(y=100, line_dash="dot", line_color="#D1D5DB")
    fig.update_layout(
        title="Verify pass rate by phase (%)",
        xaxis_title="Phase",
        yaxis_title="Pass rate (%)",
        yaxis={"range": [0, 105]},
        template="plotly_white",
        height=320,
    )
    return fig


# ── Review gates ──────────────────────────────────────────────────────────


def chart_review_gates(runs: list[dict]) -> go.Figure:
    gate_counts: Counter = Counter()
    for r in runs:
        for g in r.get("review_gates") or []:
            gate_counts[g] += 1
    if not gate_counts:
        fig = go.Figure()
        fig.add_annotation(
            text="No review gates triggered",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 14},
        )
        return fig
    labels, vals = zip(*gate_counts.most_common(), strict=True)
    fig = go.Figure(go.Bar(x=labels, y=vals, marker_color="#F59E0B"))
    fig.update_layout(
        title="Review gates triggered (frequency)",
        xaxis_title="Gate",
        yaxis_title="Count",
        template="plotly_white",
        height=300,
    )
    return fig


# ── Duration by size ──────────────────────────────────────────────────────


def chart_duration_by_size(runs: list[dict]) -> go.Figure:
    data: dict[str, list[float]] = defaultdict(list)
    for r in runs:
        if (
            r.get("status") == "done"
            and r.get("duration_s") is not None
            and r["size"] != "?"
        ):
            data[r["size"]].append(r["duration_s"] / 60)
    return _box(
        data, "Duration by task size", "Size", ordered_keys=SIZE_ORDER, color="#6366F1"
    )


# ── Duration by phase ─────────────────────────────────────────────────────


def chart_duration_by_phase(runs: list[dict]) -> go.Figure:
    data: dict[str, list[float]] = defaultdict(list)
    for r in runs:
        if (
            r.get("status") == "done"
            and r.get("duration_s") is not None
            and r["phase"] != "?"
        ):
            data[r["phase"]].append(r["duration_s"] / 60)
    ordered = sorted(data, key=_phase_num)
    short = {p: _short_phase(p) for p in ordered}
    data_short = {short[p]: data[p] for p in ordered}
    return _box(
        data_short,
        "Duration by phase",
        "Phase",
        ordered_keys=list(data_short),
        color="#3B82F6",
        height=400,
    )


# ── Duration by priority ──────────────────────────────────────────────────


def chart_duration_by_priority(runs: list[dict]) -> go.Figure:
    data: dict[str, list[float]] = defaultdict(list)
    for r in runs:
        if (
            r.get("status") == "done"
            and r.get("duration_s") is not None
            and r["priority"] != "?"
        ):
            data[r["priority"]].append(r["duration_s"] / 60)
    return _box(
        data,
        "Duration by priority",
        "Priority",
        ordered_keys=PRIO_ORDER,
        color="#F59E0B",
    )


# ── Phase completion timeline ─────────────────────────────────────────────


def chart_phase_completion(runs: list[dict]) -> go.Figure:
    """When was the last task in each phase completed?"""
    last_finished: dict[str, datetime] = {}
    for r in runs:
        if r.get("status") == "done" and r.get("finished_at") and r["phase"] != "?":
            dt = parse_dt(r["finished_at"])
            if dt is None:
                continue
            p = r["phase"]
            if p not in last_finished or dt > last_finished[p]:
                last_finished[p] = dt

    phases = sorted(last_finished, key=_phase_num)
    xs = [last_finished[p] for p in phases]
    short = [_short_phase(p) for p in phases]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=short,
            mode="markers+lines",
            marker={"size": 10, "color": COLORS["done"]},
            line={"color": "#D1D5DB", "dash": "dot"},
            customdata=phases,
            hovertemplate="%{customdata}<br>Completed: %{x}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Phase completion timeline — when was last task in each phase done?",
        xaxis_title="Time (UTC)",
        yaxis_title="Phase",
        template="plotly_white",
        height=420,
        yaxis={"autorange": "reversed"},
    )
    return fig


# ── Phase breakdown (existing, now per-milestone) ─────────────────────────


def _phase_bar(tasks_subset: dict, title: str) -> go.Figure:
    groups: dict[str, Counter] = defaultdict(Counter)
    for t in tasks_subset.values():
        groups[t["phase"]][t["status"]] += 1
    phases = sorted(groups, key=_phase_num)
    short = [_short_phase(p) for p in phases]

    fig = go.Figure()
    for status, col in [
        ("done", COLORS["done"]),
        ("open", COLORS["open"]),
        ("deferred", COLORS["deferred"]),
        ("canceled", COLORS["canceled"]),
    ]:
        fig.add_trace(
            go.Bar(
                name=status.capitalize(),
                x=short,
                y=[groups[p][status] for p in phases],
                marker_color=col,
                customdata=phases,
                hovertemplate="%{customdata}<br>" + status + ": %{y}<extra></extra>",
            )
        )
    fig.update_layout(
        barmode="stack",
        title=title,
        xaxis_title="Phase",
        yaxis_title="Tasks",
        template="plotly_white",
        height=360,
        legend={"orientation": "h", "y": 1.1},
    )
    return fig


def chart_phase_breakdown(tasks: dict) -> tuple[go.Figure, go.Figure, go.Figure]:
    # Archived (rotated) tasks are history, not live scope: they appear in the
    # all-milestones chart under their "Archived" phase / ARCH milestone but
    # are excluded from the live M1 / M2+ splits.
    live = {k: v for k, v in tasks.items() if not v.get("archived")}
    m1 = {k: v for k, v in live.items() if v["milestone"] == "M1"}
    m2 = {k: v for k, v in live.items() if v["milestone"] != "M1"}
    return (
        _phase_bar(tasks, "All milestones — task status by phase (incl. archived)"),
        _phase_bar(m1, "M1 — task status by phase (Phases 0–15)"),
        _phase_bar(m2, "M2+ — deferred / future scope"),
    )


# ── Critical path ─────────────────────────────────────────────────────────


def chart_critical_path(cp: list[str], tasks: dict) -> go.Figure:
    if not cp:
        fig = go.Figure()
        fig.add_annotation(
            text="No open critical path",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        return fig
    n = len(cp)
    prio_color = {"P0": "#EF4444", "P1": "#F59E0B", "P2": "#3B82F6", "P3": "#9CA3AF"}
    colors = [prio_color.get(tasks[t]["priority"], "#9CA3AF") for t in cp]
    fig = go.Figure()
    for i in range(n - 1):
        fig.add_annotation(
            x=i + 1 - 0.15,
            y=0,
            ax=i + 0.15,
            ay=0,
            xref="x",
            yref="y",
            axref="x",
            ayref="y",
            showarrow=True,
            arrowhead=2,
            arrowcolor="#9CA3AF",
            arrowsize=1.2,
        )
    fig.add_trace(
        go.Scatter(
            x=list(range(n)),
            y=[0] * n,
            mode="markers+text",
            marker={"size": 32, "color": colors, "line": {"width": 2, "color": "white"}},
            text=cp,
            textposition="top center",
            customdata=[
                [tasks[t]["title"], tasks[t]["priority"], tasks[t]["size"]] for t in cp
            ],
            hovertemplate="<b>%{text}</b><br>%{customdata[0]}<br>P: %{customdata[1]} | Size: %{customdata[2]}<extra></extra>",
        )
    )
    w = sum(SIZE_WEIGHTS.get(tasks[t]["size"], 3) for t in cp)
    fig.update_layout(
        title=f"Critical path ({n} tasks · ~{w * 8.7 / 60:.1f}h at median pace)",
        template="plotly_white",
        height=260,
        showlegend=False,
        xaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
        yaxis={
            "showgrid": False, "zeroline": False, "showticklabels": False, "range": [-0.5, 0.8]
        },
    )
    return fig


# ── Dependency graph ──────────────────────────────────────────────────────


def chart_dep_graph(tasks: dict, G: nx.DiGraph) -> go.Figure:
    open_ids = {n for n, d in tasks.items() if d["status"] == "open"}
    ctx = set(open_ids)
    for n in open_ids:
        ctx.update(G.predecessors(n))
    sub = G.subgraph(ctx)

    try:
        pos = nx.nx_agraph.graphviz_layout(sub, prog="dot")
    except Exception:  # noqa: BLE001 - graphviz is optional, spring fallback
        pos = nx.spring_layout(sub, seed=42, k=2.5)

    grp_color = {
        "MODE": "#3B82F6",
        "TEST": "#10B981",
        "QA": "#8B5CF6",
        "PERF": "#F59E0B",
        "SEC": "#EF4444",
        "UX": "#EC4899",
        "A11Y": "#06B6D4",
        "VIS": "#84CC16",
        "LAYOUT": "#F97316",
        "PYBASE": "#6366F1",
        "PYMODES": "#14B8A6",
        "SCHEMA": "#A78BFA",
        "WEBBASE": "#FB923C",
        "INFRA": "#94A3B8",
    }
    ex, ey = [], []
    for u, v in sub.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        ex += [x0, x1, None]
        ey += [y0, y1, None]

    nodes = list(sub.nodes())
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=ex,
            y=ey,
            mode="lines",
            line={"width": 1, "color": "#E2E8F0"},
            hoverinfo="none",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[pos[n][0] for n in nodes],
            y=[pos[n][1] for n in nodes],
            mode="markers+text",
            marker={
                "size": [20 if tasks[n]["status"] == "open" else 12 for n in nodes],
                "color": [grp_color.get(n.split("-")[0], "#CBD5E1") for n in nodes],
                "symbol": [
                    "circle" if tasks[n]["status"] == "open" else "circle-open"
                    for n in nodes
                ],
                "line": {"width": 1.5, "color": "white"},
            },
            text=nodes,
            textposition="top center",
            hovertext=[f"{n}<br>{tasks[n]['title'][:40]}" for n in nodes],
            hoverinfo="text",
        )
    )
    fig.update_layout(
        title="Dependency graph — open tasks (hollow = done context)",
        template="plotly_white",
        height=600,
        showlegend=False,
        xaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
        yaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
    )
    return fig


# ---------------------------------------------------------------------------
# 6. Assemble HTML
# ---------------------------------------------------------------------------

CSS = """
:root {
  /* ── Spacing scale (0.25rem base) ── */
  --sp-1: 0.25rem;  --sp-2: 0.5rem;   --sp-3: 0.75rem;
  --sp-4: 1rem;     --sp-5: 1.25rem;  --sp-6: 1.5rem;
  --sp-8: 2rem;     --sp-10: 2.5rem;  --sp-12: 3rem;

  /* ── Type scale (ratio 1.125) ── */
  --text-xs:   0.75rem;   /* 12px */
  --text-sm:   0.8125rem; /* 13px */
  --text-base: 0.9375rem; /* 15px */
  --text-lg:   1.0625rem; /* 17px */
  --text-xl:   1.1875rem; /* 19px */
  --text-2xl:  1.5rem;    /* 24px */

  /* ── OKLCH color tokens (restrained: tinted slate + indigo accent) ── */
  --bg:        oklch(98%  0.005 260);   /* near-white with indigo tint   */
  --bg-panel:  oklch(100% 0.003 260);   /* sidebar / panel               */
  --bg-card:   oklch(100% 0.003 260);
  --bg-subtle: oklch(96%  0.007 260);   /* code blocks, hover            */

  --border:    oklch(91%  0.008 260);
  --border-md: oklch(86%  0.010 260);

  --text-1:    oklch(16%  0.012 260);   /* headings         — ~18:1 on white */
  --text-2:    oklch(34%  0.010 260);   /* body             — ~10:1 on white */
  --text-3:    oklch(40%  0.009 260);   /* muted / labels   —  6.4:1 on white (≥4.5 ✓) */

  --accent:    oklch(42%  0.22  262);   /* indigo           —  6.0:1 on white (≥4.5 ✓) */
  --accent-bg: oklch(97%  0.014 262);   /* very light tint  — background only */

  --green:     oklch(46%  0.18  152);   /* emerald          —  5.5:1 on white (≥4.5 ✓) */
  --amber:     oklch(48%  0.16   75);   /* amber            —  5.0:1 on white (≥4.5 ✓) */
  --red:       oklch(44%  0.22   25);   /* red              —  6.2:1 on white (≥4.5 ✓) */

  /* ── Elevation ── */
  --shadow-sm: 0 1px 2px oklch(0% 0 0 / 0.05), 0 1px 4px oklch(0% 0 0 / 0.04);
  --shadow-md: 0 2px 6px oklch(0% 0 0 / 0.07), 0 1px 2px oklch(0% 0 0 / 0.04);

  /* ── Layout ── */
  --sidebar-w: 200px;
  --content-max: 960px;
  --radius: 6px;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html { font-size: 16px; -webkit-font-smoothing: antialiased; }

body {
  font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  background: var(--bg);
  color: var(--text-2);
  line-height: 1.5;
  display: flex;
  min-height: 100vh;
}

/* ── Sidebar nav ── */
.sidebar {
  width: var(--sidebar-w);
  min-width: var(--sidebar-w);
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  padding: var(--sp-6) 0 var(--sp-8);
  display: flex;
  flex-direction: column;
  gap: 0;
}

.sidebar-logo {
  padding: 0 var(--sp-4) var(--sp-4);
  border-bottom: 1px solid var(--border);
  margin-bottom: var(--sp-2);
}

.sidebar-logo-name {
  font-size: var(--text-sm);
  font-weight: 700;
  color: var(--accent);
  letter-spacing: -0.02em;
  display: block;
}

.sidebar-logo span {
  font-weight: 400;
  color: var(--text-3);
  font-size: var(--text-xs);
  display: block;
  margin-top: var(--sp-1);
}

.nav-item {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  padding: 6px var(--sp-4);
  font-size: var(--text-sm);
  color: var(--text-3);
  text-decoration: none;
  transition: color 120ms ease, background 120ms ease;
  cursor: pointer;
  line-height: 1.4;
}
.nav-item:hover { color: var(--text-1); background: var(--bg-subtle); }
.nav-item.active { color: var(--accent); font-weight: 500; }

.nav-num {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-3);
  letter-spacing: 0.04em;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
  width: 1.6em;
}
.nav-item.active .nav-num { color: var(--accent); }

/* ── Main content ── */
.main {
  flex: 1;
  min-width: 0;
  padding: var(--sp-8) var(--sp-8) var(--sp-12);
}

.page-header {
  margin-bottom: var(--sp-8);
  padding-bottom: var(--sp-5);
  border-bottom: 1px solid var(--border);
}

.page-header-left {
  /* single column layout */
}

.page-title {
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--text-1);
  letter-spacing: -0.03em;
  line-height: 1.1;
}

.page-meta {
  font-size: var(--text-xs);
  color: var(--text-3);
  margin-top: var(--sp-2);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.01em;
}


/* ── Progress bar ── */
.progress-wrap {
  margin: var(--sp-3) 0 0;
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.progress-bar {
  flex: 1;
  height: 3px;
  background: var(--border);
  border-radius: 999px;
  overflow: hidden;
  max-width: 200px;
}
.progress-fill {
  height: 100%;
  background: var(--green);
  border-radius: 999px;
  transition: width 600ms ease;
}
.progress-label {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--text-3);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

/* ── Stat bar (horizontal, no grid) ── */
.stat-bar {
  display: flex;
  align-items: stretch;
  margin-bottom: var(--sp-8);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--bg-card);
  box-shadow: var(--shadow-sm);
}

.stat-cluster {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0;
  flex: 1;
  padding: var(--sp-1) 0;
}
.stat-cluster + .stat-cluster {
  border-left: 2px solid var(--border-md);
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: var(--sp-2) var(--sp-4);
  min-width: 0;
}
.stat-item + .stat-item {
  border-left: 1px solid var(--border);
}

.si-val {
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--text-1);
  letter-spacing: -0.03em;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.si-lbl {
  font-size: 10px;
  font-weight: 500;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  white-space: nowrap;
  margin-top: 2px;
}
.si-val.green  { color: var(--green);  }
.si-val.amber  { color: var(--amber);  }
.si-val.accent { color: var(--accent); }
.si-val.red    { color: var(--red);    }

/* ── Section header ── */
.section-anchor { scroll-margin-top: var(--sp-6); }

.section-hd {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
  margin: var(--sp-10) 0 var(--sp-5);
  padding-bottom: var(--sp-3);
  border-bottom: 1px solid var(--border);
}

.section-num {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--accent);
  letter-spacing: 0.06em;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.section-hd h2 {
  font-size: 1.125rem;
  font-weight: 700;
  color: var(--text-1);
  letter-spacing: -0.02em;
}

/* ── Chart block ── */
.chart-block {
  margin-bottom: var(--sp-6);
}

.chart-label {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: var(--sp-2);
}

/* ── Code / monospace box ── */
.cp-box {
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--sp-3) var(--sp-4);
  font-family: "SF Mono", "Fira Code", ui-monospace, monospace;
  font-size: var(--text-xs);
  color: var(--text-2);
  word-break: break-word;
  line-height: 1.9;
  margin-bottom: var(--sp-4);
}

/* ── Archive warning banner ── */
.warn-banner {
  background: var(--accent-bg);
  border: 1px solid var(--amber);
  border-left: 4px solid var(--amber);
  border-radius: var(--radius);
  color: var(--text-1);
  font-size: var(--text-sm);
  padding: var(--sp-3) var(--sp-4);
  margin-bottom: var(--sp-6);
}
.warn-banner ul { margin: var(--sp-1) 0 0 var(--sp-5); }

/* ── Footer ── */
footer {
  font-size: var(--text-xs);
  color: var(--text-3);
  text-align: center;
  margin-top: var(--sp-12);
  padding-top: var(--sp-6);
  border-top: 1px solid var(--border);
}

/* ── Focus & reduced motion ── */
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 3px; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition-duration: 0ms !important; } }
@media (prefers-color-scheme: dark) {
  :root {
    --bg:        oklch(14%  0.01  260);
    --bg-panel:  oklch(17%  0.01  260);
    --bg-card:   oklch(17%  0.01  260);
    --bg-subtle: oklch(20%  0.01  260);
    --border:    oklch(26%  0.012 260);
    --border-md: oklch(32%  0.014 260);
    --text-1:    oklch(96%  0.005 260);
    --text-2:    oklch(80%  0.007 260);
    --text-3:    oklch(60%  0.008 260);
    --accent:    oklch(70%  0.18  262);
    --accent-bg: oklch(22%  0.03  262);
  }
}
"""

SECTIONS = [
    ("progress", "Progress & pace"),
    ("timeline", "Timeline"),
    ("duration", "Duration"),
    ("backend", "Backend / CLI"),
    ("quality", "Quality"),
    ("backlog", "Backlog by phase"),
    ("graph", "Graph & critical path"),
]


def sec_hd(sid: str, num: int, title: str) -> str:
    return (
        f'<div class="section-anchor" id="{sid}"></div>'
        f'<div class="section-hd">'
        f'<span class="section-num">{num:02d}</span>'
        f"<h2>{title}</h2>"
        f"</div>"
    )


def chart_block(label: str, body: str) -> str:
    return (
        f'<div class="chart-block"><div class="chart-label">{label}</div>{body}</div>'
    )


def build_report(
    tasks: dict,
    runs: list[dict],
    cp: list[str],
    since_label: str = "",
    subtitle: str = "",
    recurrence: dict | None = None,
    archive_warnings: list[str] | None = None,
) -> str:
    G = build_dag(tasks)  # DAG is deterministic from tasks; no need for a global
    done = sum(1 for t in tasks.values() if t["status"] == "done")
    open_ = sum(1 for t in tasks.values() if t["status"] == "open")
    deferred = sum(1 for t in tasks.values() if t["status"] == "deferred")
    canceled = sum(1 for t in tasks.values() if t["status"] == "canceled")
    archived = sum(1 for t in tasks.values() if t.get("archived"))
    total = done + open_
    pct = round(done / total * 100) if total else 0

    first_run = min(
        (
            parsed
            for r in runs
            if r.get("created_at")
            if (parsed := parse_dt(r["created_at"])) is not None
        ),
        default=None,
    )
    last_run = max(
        (
            parsed
            for r in runs
            if r.get("finished_at")
            if (parsed := parse_dt(r["finished_at"])) is not None
        ),
        default=None,
    )
    elapsed_h = (
        (last_run - first_run).total_seconds() / 3600 if first_run and last_run else 0
    )
    pace = done / elapsed_h if elapsed_h else 0
    eta_h = open_ / pace if pace else 0

    done_runs = [r for r in runs if r.get("status") == "done"]
    durs = [r["duration_s"] for r in done_runs if r.get("duration_s")]
    median_min = float(np.median(durs)) / 60 if durs else 0
    approved = sum(1 for r in runs if r.get("verdict") == "approve")
    rework = sum(1 for r in runs if r.get("verdict") == "rework")
    verify_pass = sum(1 for r in runs if r.get("verify_status") == "passed")

    sibling_stat = ""
    if (
        isinstance(recurrence, dict)
        and recurrence.get("available")
        and recurrence.get("delivered_count")
    ):
        sib_rate = recurrence.get("sibling_rate") or 0
        sib_thr = recurrence.get("threshold") or SIBLING_WARN_RATE_DEFAULT
        sib_pct = round(sib_rate * 100)
        sib_cls = "red" if sib_rate >= sib_thr else "green"
        sib_n = recurrence.get("recurrence_count", 0)
        sib_tot = recurrence.get("delivered_count", 0)
        sibling_stat = (
            '<div class="stat-item" '
            f'title="{sib_n} of {sib_tot} delivered tasks are siblings/regressions '
            f'(warn ≥ {round(sib_thr * 100)}%)">'
            f'<span class="si-val {sib_cls}">{sib_pct}%</span>'
            '<span class="si-lbl">Sibling rate</span>'
            "</div>"
        )

    def H(fig: go.Figure) -> str:
        return fig.to_html(full_html=False, include_plotlyjs=False)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cp_ids = " → ".join(cp) if cp else "n/a"
    w = sum(SIZE_WEIGHTS.get(tasks[t]["size"], 3) for t in cp)
    _active_subtitle = subtitle or since_label
    window_html = (
        f'<p class="page-meta" style="color:var(--accent)">{_active_subtitle} · {len(runs)} runs</p>'
        if _active_subtitle
        else ""
    )

    # Rotated-history marker + degradation banner.
    archived_stat = (
        '<div class="stat-item" '
        'title="Delivered history merged from rotated backlog archives '
        '(backlog/archive); not live scope">'
        f'<span class="si-val">{archived}</span>'
        '<span class="si-lbl">Archived</span>'
        "</div>"
        if archived
        else ""
    )
    # only rendered when there is dropped work, so a repo that has
    # never canceled anything keeps the tile row it had.
    canceled_stat = (
        '<div class="stat-item" '
        'title="Dropped work (`- [c]`): decided against, not delivered and not '
        'paused">'
        f'<span class="si-val">{canceled}</span>'
        '<span class="si-lbl">Canceled</span>'
        "</div>"
        if canceled
        else ""
    )
    warning_banner = ""
    if archive_warnings:
        items = "".join(
            f"<li>{_escape_html(warning)}</li>" for warning in archive_warnings
        )
        warning_banner = (
            '<div class="warn-banner" role="alert">'
            "<strong>Backlog archive warning</strong> — delivered-history "
            "metrics degraded to the readable backlog files only:"
            f"<ul>{items}</ul></div>"
        )

    fig_burndown = chart_burndown(runs, tasks)
    fig_velocity = chart_velocity(runs)
    fig_gantt = chart_gantt(runs)
    fig_heatmap = chart_heatmap(runs)
    fig_dur_hist = chart_duration_hist(runs)
    fig_dur_trend = chart_duration_trend(runs)
    fig_concurrency = chart_concurrency(runs)
    fig_be_pie = chart_backend_pie(runs)
    fig_be_dur = chart_duration_by_backend(runs)
    fig_be_time = chart_backend_over_time(runs)
    fig_verdict_phase = chart_verdict_by_phase(runs)
    fig_verify_phase = chart_verify_by_phase(runs)
    fig_gates = chart_review_gates(runs)
    fig_dur_size = chart_duration_by_size(runs)
    fig_dur_phase = chart_duration_by_phase(runs)
    fig_dur_prio = chart_duration_by_priority(runs)
    fig_phase_comp = chart_phase_completion(runs)
    fig_cp = chart_critical_path(cp, tasks)
    fig_dep = chart_dep_graph(tasks, G)
    fig_ph_all, fig_ph_m1, fig_ph_m2 = chart_phase_breakdown(tasks)

    nav_items = "".join(
        f'<a class="nav-item" href="#{sid}" onclick="setActive(this)">'
        f'<span class="nav-num">{i + 1:02d}</span>{title}'
        f"</a>"
        for i, (sid, title) in enumerate(SECTIONS)
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Project Analytics — {now_str}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>{CSS}</style>
</head>
<body>

<nav class="sidebar" aria-label="Sections">
  <div class="sidebar-logo">
    <span class="sidebar-logo-name">Project Analytics</span>
    <span>{now_str}</span>
  </div>
  {nav_items}
</nav>

<main class="main">
  <header class="page-header">
    <div class="page-header-left">
      <h1 class="page-title">Project Analytics</h1>
      <p class="page-meta">Generated {now_str}</p>
      {window_html}
      <div class="progress-wrap" title="{done} done of {total} non-deferred">
        <div class="progress-bar"><div class="progress-fill" style="width:{
        pct
    }%"></div></div>
        <span class="progress-label">{done} / {total} tasks</span>
      </div>
    </div>
  </header>

  {warning_banner}

  <div class="stat-bar">
    <div class="stat-cluster">
      <div class="stat-item">
        <span class="si-val green">{done}</span>
        <span class="si-lbl">Done</span>
      </div>
      <div class="stat-item">
        <span class="si-val">{open_}</span>
        <span class="si-lbl">Open</span>
      </div>
      <div class="stat-item">
        <span class="si-val">{deferred}</span>
        <span class="si-lbl">Deferred</span>
      </div>
      {canceled_stat}
      {archived_stat}
      <div class="stat-item">
        <span class="si-val accent">{pct}%</span>
        <span class="si-lbl">Complete</span>
      </div>
    </div>
    <div class="stat-cluster">
      <div class="stat-item">
        <span class="si-val amber">{elapsed_h:.1f}h</span>
        <span class="si-lbl">Elapsed</span>
      </div>
      <div class="stat-item">
        <span class="si-val accent">{pace:.1f}/h</span>
        <span class="si-lbl">Pace</span>
      </div>
      <div class="stat-item">
        <span class="si-val amber">~{eta_h:.1f}h</span>
        <span class="si-lbl">ETA</span>
      </div>
      <div class="stat-item">
        <span class="si-val accent">{median_min:.1f}m</span>
        <span class="si-lbl">Median run</span>
      </div>
    </div>
    <div class="stat-cluster">
      <div class="stat-item">
        <span class="si-val green">{approved}</span>
        <span class="si-lbl">Approved</span>
      </div>
      <div class="stat-item">
        <span class="si-val {"red" if rework > 0 else "green"}">{rework}</span>
        <span class="si-lbl">Rework</span>
      </div>
      <div class="stat-item">
        <span class="si-val green">{verify_pass}</span>
        <span class="si-lbl">Verify</span>
      </div>
      <div class="stat-item">
        <span class="si-val {
        "green"
        if approved > 0
        and (approved / (approved + rework) if (approved + rework) else 1) >= 0.9
        else "amber"
    }">{
        round(approved / (approved + rework) * 100) if (approved + rework) else 0
    }%</span>
        <span class="si-lbl">Approve rate</span>
      </div>
      {sibling_stat}
    </div>
  </div>

  {sec_hd("progress", 1, "Progress & pace")}
  {chart_block("Burndown", H(fig_burndown))}
  {chart_block("Velocity — tasks per 2h window", H(fig_velocity))}
  {chart_block("Run concurrency", H(fig_concurrency))}

  {sec_hd("timeline", 2, "Timeline")}
  {chart_block("Gantt — all completed runs", H(fig_gantt))}
  {chart_block("Phase completion over time", H(fig_phase_comp))}
  {chart_block("Activity by day and hour (UTC)", H(fig_heatmap))}

  {sec_hd("duration", 3, "Duration")}
  {chart_block("Duration distribution", H(fig_dur_hist))}
  {chart_block("Duration trend — is the agent slowing down?", H(fig_dur_trend))}
  {chart_block("By task size", H(fig_dur_size))}
  {chart_block("By priority", H(fig_dur_prio))}
  {chart_block("By phase", H(fig_dur_phase))}

  {sec_hd("backend", 4, "Backend / CLI")}
  {chart_block("Backend distribution", H(fig_be_pie))}
  {chart_block("Duration by backend", H(fig_be_dur))}
  {chart_block("Backend mix over time", H(fig_be_time))}

  {sec_hd("quality", 5, "Quality")}
  {chart_block("Verdict breakdown by phase", H(fig_verdict_phase))}
  {chart_block("Verify pass rate by phase", H(fig_verify_phase))}
  {chart_block("Review gates — trigger frequency", H(fig_gates))}

  {sec_hd("backlog", 6, "Backlog by phase")}
  {chart_block("All milestones", H(fig_ph_all))}
  {chart_block("M1 — Phases 0–15", H(fig_ph_m1))}
  {chart_block("M2+ — deferred", H(fig_ph_m2))}

  {sec_hd("graph", 7, "Graph & critical path")}
  {
        chart_block(
            f"Critical path — {len(cp)} tasks · ~{w * 8.7 / 60:.1f}h",
            f'<div class="cp-box">{cp_ids}</div>' + H(fig_cp),
        )
    }
  {chart_block("Dependency graph (open tasks)", H(fig_dep))}

  <footer>Project analytics · ai-task · {now_str}</footer>
</main>

<script>
  function setActive(el) {{
    document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
    el.classList.add("active");
  }}
  // Highlight nav item on scroll
  const anchors = document.querySelectorAll(".section-anchor");
  const navLinks = document.querySelectorAll(".nav-item");
  const obs = new IntersectionObserver(entries => {{
    entries.forEach(e => {{
      if (e.isIntersecting) {{
        const id = e.target.id;
        navLinks.forEach(a => {{
          a.classList.toggle("active", a.getAttribute("href") === "#" + id);
        }});
      }}
    }});
  }}, {{ rootMargin: "-20% 0px -70% 0px" }});
  anchors.forEach(a => obs.observe(a));
</script>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="analytics",
        description="Generate an HTML analytics report for an ai-task project.",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        metavar="DIR",
        help="Repository root (where .ai-task/ and BACKLOG.md live). Default: cwd.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="FILE",
        help="Output HTML path. Default: <repo>/analytics/report.html.",
    )
    parser.add_argument(
        "--since",
        metavar="SPEC",
        default=None,
        help=(
            "Filter run-timeline sections to runs whose reference time "
            "(finished_at → completed_at → created_at) is >= the cutoff. "
            "SPEC accepts: (1) relative duration — e.g. ``7d``, ``24h``, ``30m``; "
            "(2) date only — ``YYYY-MM-DD`` (interpreted as 00:00:00 UTC on that day); "
            "(3) absolute ISO-8601 datetime — e.g. ``2026-05-20T14:00:00Z`` or "
            "``2026-05-20T14:00:00+03:00`` (naive datetime treated as UTC). "
            "Backlog task table is always full-repo (unaffected by this flag). "
            "Mutually exclusive with --last."
        ),
    )
    parser.add_argument(
        "--last",
        metavar="N",
        type=int,
        default=None,
        help=(
            "Keep only the N most recent runs (by created_at, tie-break run_sort_key). "
            "Use when you want «last five deliveries» instead of a calendar window. "
            "Mutually exclusive with --since."
        ),
    )
    args = parser.parse_args(argv)

    repo_root = args.repo.resolve()
    out: Path = (
        args.output.resolve()
        if args.output
        else repo_root / "analytics" / "report.html"
    )

    # Audit reader: active BACKLOG.md merged with rotated archives so delivered
    # history survives sdlc-backlog-rotate. Delivery readers (plan /
    # backlog-order / dor) stay active-only.
    tasks, archive_warnings = load_backlog(repo_root)
    for warning in archive_warnings:
        print(f"WARNING: {warning}")
    G = build_dag(tasks)
    cp = critical_path(G, tasks)
    runs, _ = load_runs(repo_root)
    enrich_runs(runs, tasks)

    if args.since and args.last is not None:
        print(
            "error: --since and --last are mutually exclusive. "
            "Use --since for a time window (e.g. 7d, 2026-05-20) "
            "or --last for the N most recent runs (e.g. --last 10).",
            file=__import__("sys").stderr,
        )
        return 1

    since_label = ""
    subtitle = ""
    if args.since:
        cutoff = parse_since_spec(args.since)
        total_runs = len(runs)
        runs = filter_runs_since(runs, cutoff)
        since_label = f"Runs since {cutoff.strftime('%Y-%m-%d %H:%M UTC')}"
        print(f"Window: {since_label} ({len(runs)} of {total_runs} runs)")
    elif args.last is not None:
        total_runs = len(runs)
        runs = filter_runs_last(runs, args.last)
        subtitle = f"Last {args.last} runs"
        if total_runs < args.last:
            print(
                f"Note: --last {args.last} requested but only {total_runs} runs available; "
                f"using all {total_runs}."
            )
        else:
            print(f"Window: {subtitle} ({len(runs)} of {total_runs} runs)")

    recurrence = load_recurrence(repo_root)

    all_archive_warnings = list(
        dict.fromkeys(archive_warnings + (recurrence.get("archive_warnings") or []))
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        build_report(
            tasks,
            runs,
            cp,
            since_label=since_label,
            subtitle=subtitle,
            recurrence=recurrence,
            archive_warnings=all_archive_warnings,
        )
    )
    sib_rate = recurrence.get("sibling_rate")
    sib_note = (
        f", sibling rate {round(sib_rate * 100)}%"
        if isinstance(sib_rate, (int, float))
        else ""
    )
    print(f"Report → {out}  ({len(runs)} runs, {len(cp)} cp tasks{sib_note})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
