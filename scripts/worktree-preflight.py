#!/usr/bin/env python3
"""Worktree apply preflight overlap analyzer.

Inspects changed file overlap across git worktrees, warns on high-conflict
zones, and recommends apply mode (immediate or deferred).

Usage:
    python scripts/worktree-preflight.py [--repo PATH] [--json]

Exit codes:
    0  No overlap or only low-risk overlap — deferred apply may be safe
    1  High-risk overlap detected — immediate apply recommended
    2  Error (not a git repo, worktrees not accessible, etc.)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HIGH_RISK_PATTERNS = [
    "BACKLOG.md",
    "CHANGELOG.md",
    re.compile(r"^docs/ai-task.*\.md$"),
    re.compile(r"^skills/ai-task-"),
    "scripts/ai-task.py",
    re.compile(r"^tests/"),
    re.compile(r"^scripts/ai-task"),
]

CONTROL_FILE_LABEL = "shared-control"


def is_high_risk(path: str) -> bool:
    for pat in HIGH_RISK_PATTERNS:
        if isinstance(pat, str):
            if path == pat or path.endswith("/" + pat):
                return True
        else:
            if pat.search(path):
                return True
    return False


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


def get_worktrees(repo: Path) -> list[dict]:
    """Return list of {path, branch, head, is_main} for each worktree."""
    result = git(["worktree", "list", "--porcelain"], repo)
    if result.returncode != 0:
        return []
    worktrees = []
    current: dict = {}
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line[len("worktree "):], "branch": "", "head": "", "is_main": False}
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):]
        elif line == "bare":
            current["is_main"] = False
    if current:
        worktrees.append(current)
    # First entry is always the main worktree
    if worktrees:
        worktrees[0]["is_main"] = True
    return worktrees


def changed_files_in_worktree(wt_path: Path) -> set[str]:
    """Return all uncommitted changed files relative to worktree root."""
    files: set[str] = set()
    for args in [
        ["diff", "--name-only", "HEAD"],
        ["diff", "--cached", "--name-only"],
        ["diff", "--name-only"],
        ["ls-files", "--others", "--exclude-standard"],
    ]:
        r = git(args, wt_path)
        if r.returncode == 0:
            for raw in r.stdout.splitlines():
                name = raw.strip()
                if name:
                    files.add(name)
    return files


def extract_task_id_from_branch(branch: str) -> str | None:
    m = re.search(r"(TASKRUN-\d+|SKILL-\d+|RETRO-CMD-\d+)", branch, re.IGNORECASE)
    return m.group(0).upper() if m else None


def overlap_analysis(
    worktrees: list[dict],
    changed: dict[str, set[str]],
) -> dict:
    """Compute overlap between all worktree pairs."""
    wt_paths = list(changed.keys())
    overlaps: list[dict] = []
    all_high_risk_overlapping: set[str] = set()

    for i in range(len(wt_paths)):
        for j in range(i + 1, len(wt_paths)):
            a, b = wt_paths[i], wt_paths[j]
            shared = changed[a] & changed[b]
            if shared:
                high_risk = {f for f in shared if is_high_risk(f)}
                overlaps.append(
                    {
                        "worktree_a": a,
                        "worktree_b": b,
                        "shared_files": sorted(shared),
                        "high_risk_files": sorted(high_risk),
                    }
                )
                all_high_risk_overlapping |= high_risk

    return {
        "overlaps": overlaps,
        "high_risk_files": sorted(all_high_risk_overlapping),
        "has_any_overlap": bool(overlaps),
        "has_high_risk_overlap": bool(all_high_risk_overlapping),
    }


def recommend_apply_mode(analysis: dict) -> tuple[str, str]:
    """Return (mode, reason)."""
    if analysis["has_high_risk_overlap"]:
        files = ", ".join(analysis["high_risk_files"][:5])
        suffix = " …" if len(analysis["high_risk_files"]) > 5 else ""
        return "immediate", f"high-risk overlap in shared control files: {files}{suffix}"
    if analysis["has_any_overlap"]:
        return "immediate", "file overlap detected across worktrees — safer to apply sequentially"
    return "deferred", "no file overlap detected — worktrees are disjoint"


def suggest_apply_order(worktrees: list[dict], changed: dict[str, set[str]]) -> list[str]:
    """Return worktree paths in recommended apply order (task-id alphabetical as proxy for deps)."""
    items = []
    for wt in worktrees:
        path = wt["path"]
        if path not in changed:
            continue
        task_id = extract_task_id_from_branch(wt.get("branch", ""))
        items.append((task_id or path, path))
    items.sort(key=lambda x: x[0])
    return [p for _, p in items]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preflight worktree overlap analyzer — recommends immediate or deferred apply mode"
    )
    parser.add_argument("--repo", default=".", help="Repository root (default: current directory)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--include-main",
        action="store_true",
        help="Include the main worktree in overlap analysis (default: non-main only)",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists() and not any(repo.glob(".git")):
        r = git(["rev-parse", "--git-dir"], repo)
        if r.returncode != 0:
            msg = f"not a git repository: {repo}"
            if args.json:
                print(json.dumps({"error": msg}))
            else:
                print(f"ERROR: {msg}", file=sys.stderr)
            return 2

    worktrees = get_worktrees(repo)
    if not worktrees:
        msg = "no git worktrees found"
        if args.json:
            print(json.dumps({"error": msg, "recommendation": "deferred", "reason": "no worktrees"}))
        else:
            print(f"No git worktrees found in {repo}.")
        return 0

    # Collect changed files per non-main worktree (or all if --include-main)
    changed: dict[str, set[str]] = {}
    for wt in worktrees:
        if wt.get("is_main") and not args.include_main:
            continue
        wt_path = Path(wt["path"])
        if not wt_path.exists():
            continue
        files = changed_files_in_worktree(wt_path)
        if files:
            changed[wt["path"]] = files

    if not changed:
        msg = "no changed files found in any worktree"
        if args.json:
            print(json.dumps({"recommendation": "deferred", "reason": msg, "worktrees": []}))
        else:
            print(f"OK: {msg} — deferred apply is safe.")
        return 0

    analysis = overlap_analysis(worktrees, changed)
    mode, reason = recommend_apply_mode(analysis)
    apply_order = suggest_apply_order(worktrees, changed)

    if args.json:
        print(
            json.dumps(
                {
                    "recommendation": mode,
                    "reason": reason,
                    "apply_order": apply_order,
                    "worktrees_with_changes": list(changed.keys()),
                    "overlaps": analysis["overlaps"],
                    "high_risk_files": analysis["high_risk_files"],
                },
                indent=2,
            )
        )
        return 1 if mode == "immediate" else 0

    print(f"Worktree preflight analysis for: {repo}")
    print(f"Worktrees with changes: {len(changed)}")
    print()

    if analysis["overlaps"]:
        print(f"Overlap detected ({len(analysis['overlaps'])} pair(s)):")
        for ov in analysis["overlaps"]:
            a = Path(ov["worktree_a"]).name
            b = Path(ov["worktree_b"]).name
            count = len(ov["shared_files"])
            high = len(ov["high_risk_files"])
            print(f"  {a} ↔ {b}: {count} shared file(s), {high} high-risk")
            for f in ov["high_risk_files"]:
                print(f"    ! {f}  [{CONTROL_FILE_LABEL}]")
    else:
        print("No file overlap between worktrees.")

    print()
    print(f"RECOMMENDATION: {mode.upper()} apply — {reason}")
    print()
    print("Suggested apply order:")
    for i, path in enumerate(apply_order, 1):
        branch = next((w.get("branch", "") for w in worktrees if w["path"] == path), "")
        task_id = extract_task_id_from_branch(branch) or Path(path).name
        print(f"  {i}. {task_id}  ({path})")

    return 1 if mode == "immediate" else 0


if __name__ == "__main__":
    sys.exit(main())
