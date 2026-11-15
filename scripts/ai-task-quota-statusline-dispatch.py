#!/usr/bin/env python3
"""Global statusLine dispatcher for ai-task quota snapshots.

This command is safe for global Cursor/Claude settings because it does not
hardcode a repo path. It inspects the statusLine JSON payload, resolves the
active workspace directory (`cwd` / `workspace.current_dir`), walks parent
directories, and delegates to a repo-local quota helper when found:

  <repo>/.ai-task/scripts/ai-task-quota-statusline.py --repo <repo>

No matching repo/helper is a no-op (exit 0) so unrelated workspaces keep a
healthy status line.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

APP_DIR = ".ai-task"
HELPER_REL = Path(APP_DIR) / "scripts" / "ai-task-quota-statusline.py"


def _normalize_dir(raw: Any, *, cwd: Path) -> Path | None:
    if not isinstance(raw, (str, Path)):
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = (cwd / path).resolve()
        else:
            path = path.resolve()
    except (OSError, RuntimeError):
        return None
    return path


def _candidate_workspace_dirs(payload: dict[str, Any], *, cwd: Path) -> list[Path]:
    candidates: list[Path] = []
    workspace = payload.get("workspace")
    if isinstance(workspace, dict):
        for key in ("current_dir", "cwd", "root", "workspace_root", "path"):
            candidate = _normalize_dir(workspace.get(key), cwd=cwd)
            if candidate is not None:
                candidates.append(candidate)
    elif workspace is not None:
        candidate = _normalize_dir(workspace, cwd=cwd)
        if candidate is not None:
            candidates.append(candidate)
    for key in ("cwd", "current_dir", "workspace_dir", "repo_root", "repo"):
        candidate = _normalize_dir(payload.get(key), cwd=cwd)
        if candidate is not None:
            candidates.append(candidate)
    candidates.append(cwd.resolve())
    return candidates


def _walk_parent_dirs(start: Path) -> list[Path]:
    return [start, *start.parents]


def find_repo_helper(payload: dict[str, Any], *, cwd: Path) -> tuple[Path, Path] | None:
    seen: set[Path] = set()
    for candidate in _candidate_workspace_dirs(payload, cwd=cwd):
        for parent in _walk_parent_dirs(candidate):
            if parent in seen:
                continue
            seen.add(parent)
            helper = parent / HELPER_REL
            if helper.is_file():
                return parent, helper
    return None


def main() -> int:
    raw_input = sys.stdin.read()
    if not raw_input.strip():
        return 0
    try:
        payload = json.loads(raw_input)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    cwd = Path.cwd()
    resolved = find_repo_helper(payload, cwd=cwd)
    if resolved is None:
        return 0
    repo_root, helper = resolved
    completed = subprocess.run(
        [sys.executable, str(helper), "--repo", str(repo_root)],
        input=raw_input,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
