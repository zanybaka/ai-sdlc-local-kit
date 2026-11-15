#!/usr/bin/env python3
"""Delivery artifact consistency checker.

Validates that recent delivery commits have matching
entries in the backlog store and CHANGELOG.md. Every id named in a commit
subject must exist in the backlog — inline BACKLOG.md, a per-task file under
``backlog/tasks/``, or a rotated archive (legacy
``BACKLOG-NNN.md`` or ``backlog/archive/tasks/``); a CHANGELOG entry is
required only once the task is delivered (marked ``[x]``) — a filed-but-open
task does not need one. In a migrated repo the generated
BACKLOG.md index is also checked against a fresh regeneration (hand-edit
guard).

Usage:
    python scripts/check-delivery-artifacts.py [--since N] [--repo PATH] [--json]
    python scripts/check-delivery-artifacts.py --commits SHA1,SHA2,...
    python scripts/check-delivery-artifacts.py --stop-hook < hook.json

``--stop-hook`` is the Stop hook of a Claude Code session, registered
in .claude/settings.json. It blocks the end of a turn while a task this session
flipped to [x] since the last push has no CHANGELOG.md entry, and always exits 0.

Exit codes:
    0  All checked task ids satisfy the artifact requirements
    1  One or more task ids are missing from BACKLOG.md, or a delivered ([x])
       task is missing from CHANGELOG.md

Designed for local verify flow and optional CI hook.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

TASK_ID_RE = re.compile(r"\b(TASKRUN-\d+|SKILL-\d+|RETRO-CMD-\d+)\b")
DEFAULT_SINCE_COMMITS = 20

# rotated-out tasks live here. Files matching this glob (relative to
# the repo root) are scanned alongside BACKLOG.md so a post-rotation check does
# not false-fail on an id that now only exists in the archive.
ARCHIVE_GLOB = "backlog/archive/BACKLOG-*.md"

# file-per-task store. The canonical layout is defined by
# ai_task.backlog / ai_task.backlog_store; this checker reads the same file
# sets instead of assuming everything lives inline in BACKLOG.md.
STORE_GLOB = "backlog/tasks/*.md"
ARCHIVE_STORE_GLOB = "backlog/archive/tasks/*.md"


def archive_files(repo: Path) -> list[Path]:
    """Return archive backlog files for the repo, or [] when none exist.

    Backward compatible: when ``backlog/archive/`` is absent, this is empty and
    every downstream scan behaves exactly as before rotation existed. Includes
    rotated-out per-task files alongside the legacy
    ``BACKLOG-NNN.md`` archives.
    """
    return sorted(repo.glob(ARCHIVE_GLOB)) + sorted(repo.glob(ARCHIVE_STORE_GLOB))


def store_files(repo: Path) -> list[Path]:
    """Active per-task store files; [] in a non-migrated repo."""
    return sorted(repo.glob(STORE_GLOB))


def _load_backlog_store_module(repo: Path):
    """Import ai_task.backlog_store for the index guard; None when absent.

    The module lives next to this script in the ai-sdlc-local-kit profile. A consuming
    repo without the package simply skips the index-freshness guard (its
    BACKLOG.md is not generated).
    """
    import importlib

    for scripts_dir in (Path(__file__).resolve().parent, repo / "scripts"):
        if not (scripts_dir / "ai_task" / "backlog_store.py").is_file():
            continue
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        try:
            return importlib.import_module("ai_task.backlog_store")
        except ImportError:  # pragma: no cover - defensive
            return None
    return None


def check_backlog_index(repo: Path) -> list[dict]:
    """Generated-index guard: fail when BACKLOG.md drifted.

    Applies only to a migrated repo (backlog/index-skeleton.md present); a
    hand edit to the generated index - or task-file edits without a
    regeneration - is a delivery-artifact failure with a named fix.
    """
    if not (repo / "backlog" / "index-skeleton.md").exists():
        return []
    store = _load_backlog_store_module(repo)
    if store is None:
        return []
    try:
        problems = store.check(repo)
    except SystemExit as exc:  # store internally dies on malformed input
        problems = [f"backlog store unreadable: {exc}"]
    return [
        {"task_id": "(backlog-index)", "commit": "", "missing_from": [], "reason": p}
        for p in problems
    ]


def git_log_messages(
    repo: Path, *, n: int | None = None, commits: list[str] | None = None
) -> list[tuple[str, str]]:
    """Return list of (short_hash, first_subject_line) for recent commits."""
    if commits:
        result = []
        for sha in commits:
            out = subprocess.run(
                ["git", "log", "-1", "--format=%h %s", sha],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            if out.returncode == 0 and out.stdout.strip():
                parts = out.stdout.strip().split(" ", 1)
                result.append((parts[0], parts[1] if len(parts) > 1 else ""))
        return result
    count = n or DEFAULT_SINCE_COMMITS
    out = subprocess.run(
        ["git", "log", f"-{count}", "--format=%h %s"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        return []
    lines = [line.strip() for line in out.stdout.splitlines() if line.strip()]
    result = []
    for line in lines:
        parts = line.split(" ", 1)
        result.append((parts[0], parts[1] if len(parts) > 1 else ""))
    return result


def extract_task_ids(messages: list[tuple[str, str]]) -> dict[str, str]:
    """Return {task_id: commit_hash} for all delivery task ids in commit subjects."""
    found: dict[str, str] = {}
    for sha, subject in messages:
        for m in TASK_ID_RE.finditer(subject):
            tid = m.group(0)
            if tid not in found:
                found[tid] = sha
    return found


def ids_in_backlog(
    backlog_path: Path, archive_paths: list[Path] | None = None
) -> set[str]:
    """Return all task ids mentioned in BACKLOG.md (any status).

    When ``archive_paths`` is given, ids mentioned in those rotated
    archive files count too, so resolving a delivered id does not false-fail
    after its block was moved out of the active backlog.
    """
    found: set[str] = set()
    for path in [backlog_path, *(archive_paths or [])]:
        if path.exists():
            found.update(TASK_ID_RE.findall(path.read_text(encoding="utf-8")))
    return found


def ids_done_in_backlog(
    backlog_path: Path, archive_paths: list[Path] | None = None
) -> set[str]:
    """Return task ids marked done ([x]) in BACKLOG.md (and archives if given)."""
    done: set[str] = set()
    for path in [backlog_path, *(archive_paths or [])]:
        if path.exists():
            done.update(ids_done_in_text(path.read_text(encoding="utf-8")))
    return done


def ids_done_in_text(text: str) -> set[str]:
    """Return task ids on ``- [x]`` lines of one backlog text (index, task file, archive)."""
    done: set[str] = set()
    for line in text.splitlines():
        if re.match(r"\s*-\s*\[x\]", line):
            done.update(m.group(0) for m in TASK_ID_RE.finditer(line))
    return done


def ids_in_changelog(changelog_path: Path) -> set[str]:
    """Return all task ids mentioned in CHANGELOG.md."""
    if not changelog_path.exists():
        return set()
    text = changelog_path.read_text(encoding="utf-8")
    return set(TASK_ID_RE.findall(text))


def check_artifacts(
    task_ids: dict[str, str],
    backlog_path: Path,
    changelog_path: Path,
    archive_paths: list[Path] | None = None,
) -> list[dict]:
    """Return list of failure dicts for task ids missing from a required file.

    ``archive_paths`` extends the BACKLOG.md id lookup with rotated
    archive files so an id present only in the archive still resolves.
    """
    backlog_ids = ids_in_backlog(backlog_path, archive_paths)
    done_ids = ids_done_in_backlog(backlog_path, archive_paths)
    changelog_ids = ids_in_changelog(changelog_path)
    failures = []
    for tid, sha in sorted(task_ids.items()):
        missing_files = []
        if tid not in backlog_ids:
            missing_files.append("BACKLOG.md")
        if tid in done_ids and tid not in changelog_ids:
            missing_files.append("CHANGELOG.md")
        if missing_files:
            failures.append(
                {"task_id": tid, "commit": sha, "missing_from": missing_files}
            )
    return failures


# the Stop hook of a Claude Code session. Pre-push catches a closed task
# without a CHANGELOG entry only when the owner pushes; by then the session that
# closed it is over. The hook asks the same question at the end of every turn,
# for tasks flipped to [x] since the last push (unpushed commits and the working
# tree, committed or not).
BACKLOG_PATHSPEC = ("BACKLOG.md", "backlog/")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )


def push_base(repo: Path) -> str | None:
    """Commit the session's work is compared against: what was last pushed.

    The upstream of the current branch, else origin's main; without a remote, HEAD
    (then only uncommitted flips count). None in a repo with no commits.
    """
    for ref in ("@{upstream}", "origin/HEAD", "origin/main", "HEAD"):
        out = _git(repo, "rev-parse", "--verify", "-q", ref + "^{commit}")
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    return None


def newly_done_ids(repo: Path, base: str) -> set[str]:
    """Task ids that are [x] in the working tree but were not [x] at ``base``.

    Only backlog files that differ from ``base`` (or are new) are read, so the
    check stays cheap. A task moved to the archive was [x] before the move as
    well and does not count as newly closed.
    """
    changed = _git(repo, "diff", "--name-only", base, "--", *BACKLOG_PATHSPEC)
    untracked = _git(
        repo, "ls-files", "--others", "--exclude-standard", "--", *BACKLOG_PATHSPEC
    )
    paths = {
        line.strip()
        for line in (changed.stdout + untracked.stdout).splitlines()
        if line.strip().endswith(".md")
    }
    now: set[str] = set()
    before: set[str] = set()
    for rel in sorted(paths):
        current = repo / rel
        if current.is_file():
            now |= ids_done_in_text(current.read_text(encoding="utf-8"))
        old = _git(repo, "show", f"{base}:{rel}")
        if old.returncode == 0:
            before |= ids_done_in_text(old.stdout)
    return now - before


def session_task_ids(transcript: str | None) -> set[str] | None:
    """Task ids named in this session's own tool calls; None when unreadable.

    Several sessions share one checkout here, so a task another session closed
    without its entry yet is that session's business. The hook judges only ids
    this session touched: a file path, a command or a text it sent to a tool.
    """
    if not transcript:
        return None
    try:
        lines = Path(transcript).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    found: set[str] = set()
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "tool_use":
                found |= set(TASK_ID_RE.findall(json.dumps(part.get("input") or {})))
    return found


def stop_hook(payload: str) -> str:
    """Answer the Stop hook: a block decision as JSON, or "" to let the turn end."""
    try:
        hook = json.loads(payload or "{}")
    except ValueError:
        return ""
    # One reminder per stop: when the agent is already continuing because of a
    # Stop hook, let it end, or the hook would loop the turn forever.
    if not isinstance(hook, dict) or hook.get("stop_hook_active"):
        return ""
    top = _git(Path(hook.get("cwd") or "."), "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return ""
    repo = Path(top.stdout.strip())
    base = push_base(repo)
    if base is None:
        return ""
    missing = newly_done_ids(repo, base) - ids_in_changelog(repo / "CHANGELOG.md")
    own = session_task_ids(hook.get("transcript_path"))
    if own is not None:
        missing &= own
    if not missing:
        return ""
    ids = ", ".join(sorted(missing))
    reason = (
        f"{ids}: marked [x] since the last push, but CHANGELOG.md has no entry for it. "
        "Add the entry under Unreleased, regenerate the index "
        "(python3 scripts/backlog-store.py regenerate), commit and push, then answer "
        "the owner. If the task is not done, put it back to [ ]."
    )
    return json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that recent delivery commits have entries in BACKLOG.md and CHANGELOG.md"
    )
    parser.add_argument(
        "--repo", default=".", help="Repository root (default: current directory)"
    )
    parser.add_argument(
        "--since",
        type=int,
        default=DEFAULT_SINCE_COMMITS,
        metavar="N",
        help=f"Number of recent commits to scan (default: {DEFAULT_SINCE_COMMITS})",
    )
    parser.add_argument(
        "--commits",
        help="Comma-separated list of specific commit SHAs to check",
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument(
        "--stop-hook",
        action="store_true",
        help="Claude Code Stop hook: read the hook JSON on stdin",
    )
    args = parser.parse_args(argv)

    if args.stop_hook:
        try:
            answer = stop_hook(sys.stdin.read())
        except (OSError, UnicodeDecodeError):
            answer = ""  # a broken checkout must not trap the session
        if answer:
            print(answer)
        return 0

    repo = Path(args.repo).resolve()
    backlog = repo / "BACKLOG.md"
    changelog = repo / "CHANGELOG.md"
    archives = archive_files(repo)

    specific_commits = (
        [c.strip() for c in args.commits.split(",") if c.strip()]
        if args.commits
        else None
    )
    messages = git_log_messages(repo, n=args.since, commits=specific_commits)
    task_ids = extract_task_ids(messages)

    index_failures = check_backlog_index(repo)

    if not task_ids and not index_failures:
        if args.json:
            print(json.dumps({"checked": 0, "failures": [], "status": "ok"}))
        else:
            print("No delivery task ids found in recent commits.")
        return 0

    # task blocks may live as per-task files; their ids (and the
    # rotated-out archive files) resolve exactly like inline / legacy-archive
    # ids do.
    failures = check_artifacts(
        task_ids, backlog, changelog, store_files(repo) + archives
    )
    failures.extend(index_failures)

    if args.json:
        print(
            json.dumps(
                {
                    "checked": len(task_ids),
                    "failures": failures,
                    "status": "ok" if not failures else "fail",
                },
                indent=2,
            )
        )
    else:
        print(
            f"Checked {len(task_ids)} delivery task id(s) from {len(messages)} commit(s)."
        )
        if failures:
            print(f"\nFAIL: {len(failures)} artifact problem(s):")
            for f in failures:
                if f.get("reason"):
                    print(f"  {f['task_id']}: {f['reason']}")
                    continue
                files = ", ".join(f["missing_from"])
                print(f"  {f['task_id']} (commit {f['commit']}): missing from {files}")
        else:
            print("OK: all task ids present in the backlog store and CHANGELOG.md.")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
