"""Init/bootstrap machinery for the ai-task CLI.

`ai-task init` scaffolding: the default config template, repo stack
detection, the bootstrap doc/script manifests vendored into a target repo's
gitignored `.ai-task/`, the ai-sdlc-local-kit profile-root anchor, and the statusline
helper paths derived from it. The `init` command shell itself stays in the
entrypoint, as do the statusline CHECK helpers that consult the patched
``quota_status``/``statusline_settings_command`` entrypoint globals.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath

import tomllib

from ai_task._shared import APP_DIR
from ai_task.index_guard import guard_applies, write_guard
from ai_task.state import STATE_SCHEMA

# Minimal delivery docs copied into a target repo on `ai-task init` when missing.
# The manifest entries are SOURCE paths relative to the ai-sdlc-local-kit profile checkout
# (the directory holding scripts/ai-task.py); the DESTINATION is the same relative
# path under the target repo's gitignored `.ai-task/`, e.g. source
# `docs/ai-task-backlog-contract.md` -> dest `<repo>/.ai-task/docs/ai-task-backlog-contract.md`.
# They are operator tooling, not tracked content, so they live under `.ai-task/`
# (gitignored) and are reproduced by `ai-task init`. Profile-only docs (full
# docs/ai-task.md, teamlead playbooks, ~/.claude/skills) are intentionally NOT
# bootstrapped — see docs/ai-task.md.
BOOTSTRAP_DOCS: tuple[str, ...] = (
    "docs/ai-task-backlog-contract.md",
    "docs/ai-task-verify.md",
)
# Profile-owned helper scripts vendored into a target repo on `ai-task init`.
# As with docs, the manifest holds SOURCE paths relative to the profile checkout
# and the DESTINATION is under the target repo's gitignored `.ai-task/`:
# source `scripts/backlog-id-registry.py` -> dest
# `<repo>/.ai-task/scripts/backlog-id-registry.py`. Delivery skills invoke these
# from the vendored `.ai-task/scripts/<name>` path (and fall back to the profile
# source when running inside ai-sdlc-local-kit itself). Scripts are profile tooling, not
# operator data: each is created when missing and refreshed to the profile
# version when it differs, so an old repo picks up new/updated tools on re-init.
# `.ai-task` operator state/data (state.json, decisions.jsonl, …) is never
# touched. Scripts that accept `--repo` (e.g. check-delivery-artifacts.py,
# worktree-preflight.py) run from the profile and are intentionally NOT vendored
# — see docs/ai-task.md.
QUOTA_STATUSLINE_HELPER = "scripts/ai-task-quota-statusline.py"
QUOTA_STATUSLINE_DISPATCHER = "scripts/ai-task-quota-statusline-dispatch.py"
# The backlog store CLI is a thin shim over the ai_task store
# modules, not a self-contained script like the other two helpers,
# so vendoring it means vendoring its module subset with it: the four files
# below land at `.ai-task/scripts/ai_task/<name>.py`, WITHOUT the facade
# `__init__.py` (which would drag the whole package in). The shim detects the
# missing `__init__.py` and registers a synthetic parent package anchored on
# the vendored directory, so the copies resolve from the consuming repo with
# no ai-sdlc-local-kit path anywhere. Same create-or-refresh flow as every entry.
# `index_guard.py` joins the subset in it generates the repo's
# TRACKED CI guard by bundling the other three, and it must run from the
# consumer's own vendored copies so the guard matches the tool that repo runs.
BACKLOG_STORE_CLI = "scripts/backlog-store.py"
BACKLOG_STORE_MODULES: tuple[str, ...] = (
    "scripts/ai_task/_shared.py",
    "scripts/ai_task/backlog.py",
    "scripts/ai_task/backlog_store.py",
    "scripts/ai_task/index_guard.py",
)
BOOTSTRAP_SCRIPTS: tuple[str, ...] = (
    "scripts/backlog-id-registry.py",
    QUOTA_STATUSLINE_HELPER,
    BACKLOG_STORE_CLI,
    *BACKLOG_STORE_MODULES,
)


# Infra stacks never pick the language verify profile (docker-build etc. are
# opt-in profiles, not defaults) and never count as "mixed stacks".
INFRA_STACKS = {"docker", "terraform"}


def default_config(root: Path, *, enable_worktrees: bool = False) -> str:
    project_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", root.name).strip("-") or "project"
    wt = "true" if enable_worktrees else "false"
    return f"""# ai-task project configuration
schema_version = {STATE_SCHEMA}
project_id = "{project_id}"
backlog_path = "BACKLOG.md"
agents_path = "AGENTS.md"
default_policy = "default"
# Per-run git worktree under .ai-task/worktrees/ (requires a git repo).
worktrees_enabled = {wt}
"""


# Directories a repo-marker scan never enters at any depth: they hold other
# projects' markers, and installed dependencies are where the file count of a
# repository lives. `.ai-task/worktrees` is skipped too, but only
# at the repo root, so a repo opened from inside a worktree still scans itself.
REPO_SCAN_SKIPPED_DIRS = frozenset({"node_modules", ".git"})


def scan_repo_paths(root: Path) -> list[PurePath]:
    """Every file and directory under ``root``, relative to it, in one walk.

    Symlinked directories are listed but not entered, as with ``Path.glob``.
    """
    worktrees = os.fspath(root / APP_DIR / "worktrees")
    paths: list[PurePath] = []
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in REPO_SCAN_SKIPPED_DIRS
            and os.path.join(current, name) != worktrees
        ]
        base = PurePath(os.path.relpath(current, root))
        paths.extend(base / name for name in dirnames)
        paths.extend(base / name for name in filenames)
    return paths


def repo_has_marker(paths: Sequence[PurePath], pattern: str) -> bool:
    """True when a scanned path matches ``pattern`` at any depth."""
    return any(path.match(pattern) for path in paths)


def detect_repo_stacks(
    root: Path, paths: Sequence[PurePath] | None = None
) -> set[str]:
    """Legacy stack markers; ``paths`` reuses a scan the caller already made."""
    if paths is None:
        paths = scan_repo_paths(root)
    stacks: set[str] = set()
    if (root / "package.json").is_file():
        stacks.add("node")
    else:
        # Monorepo frontend: package.json one level below root
        # (web/, frontend/, …) also counts as node; node_modules and dot-dirs
        # are skipped. Deeper monorepos use per-task Verify:.
        for candidate in root.glob("*/package.json"):
            parent = candidate.parent.name
            if parent == "node_modules" or parent.startswith("."):
                continue
            if candidate.is_file():
                stacks.add("node")
                break
    if (root / "go.mod").is_file():
        stacks.add("go")
    if (
        (root / "pyproject.toml").is_file()
        or (root / "requirements.txt").is_file()
        or (root / "ruff.toml").is_file()
    ):
        stacks.add("python")
    if repo_has_marker(paths, "*.sln") or repo_has_marker(paths, "*.csproj"):
        stacks.add("dotnet")
    # Infra markers: Dockerfile/compose at root, *.tf at root or
    # one level below (mirrors the package.json monorepo glob; dot-dirs skipped).
    if any(
        (root / name).is_file()
        for name in ("Dockerfile", "docker-compose.yml", "compose.yaml")
    ):
        stacks.add("docker")
    if any(root.glob("*.tf")):
        stacks.add("terraform")
    else:
        for candidate in root.glob("*/*.tf"):
            if candidate.parent.name.startswith("."):
                continue
            if candidate.is_file():
                stacks.add("terraform")
                break
    return stacks


def default_verify_profile_for_repo(root: Path) -> tuple[str, str]:
    """Pick initial default_profile from repo markers. Ruff/pytest are Python-only."""
    stacks = detect_repo_stacks(root) - INFRA_STACKS
    if stacks == {"python"}:
        return (
            "python-full",
            "detected Python (pyproject.toml, requirements.txt, or ruff.toml)",
        )
    if stacks == {"node"}:
        return "node-full", "detected Node/TS (package.json)"
    if stacks == {"dotnet"}:
        return "dotnet-full", "detected .NET (*.sln / *.csproj)"
    if stacks == {"go"}:
        return "go-full", "detected Go (go.mod)"
    if len(stacks) > 1:
        return (
            "none",
            (f"mixed stacks {sorted(stacks)}: set default_profile in policy "
            "(see commented fullstack-example profile) or Verify: per task"),
        )
    return "none", "no stack markers: edit .ai-task/policies/default.toml before verify"


def profile_root() -> Path:
    """Root of the ai-sdlc-local-kit profile checkout (where scripts/ai-task.py lives).
    """
    return Path(__file__).resolve().parents[2]


def bootstrap_dest(root: Path, rel: str) -> Path:
    """Destination of a vendored bootstrap file in the target repo.

    The manifest holds a SOURCE path relative to the profile checkout; the
    destination is the same relative path under the repo's gitignored
    `.ai-task/`, e.g. ``docs/ai-task-verify.md`` ->
    ``<repo>/.ai-task/docs/ai-task-verify.md``.
    """
    return root / APP_DIR / rel


def bootstrap_doc_targets(root: Path) -> list[tuple[Path, Path]]:
    """Map each bootstrap doc to (source_in_profile, destination_in_repo)."""
    source_root = profile_root()
    pairs: list[tuple[Path, Path]] = []
    for rel in BOOTSTRAP_DOCS:
        pairs.append((source_root / rel, bootstrap_dest(root, rel)))
    return pairs


def missing_bootstrap_docs(root: Path) -> list[str]:
    """Bootstrap docs whose source exists in the profile but is absent in the repo.

    Paths are reported relative to the repo root at the vendored destination
, so a "re-run init" hint points where the
    file should land.
    """
    return [
        f"{APP_DIR}/{rel}"
        for rel, (src, dest) in zip(
            BOOTSTRAP_DOCS, bootstrap_doc_targets(root), strict=True
        )
        if src.is_file() and not dest.exists()
    ]


def copy_bootstrap_docs(root: Path) -> list[Path]:
    """Copy missing bootstrap docs from the profile into the repo. Never overwrite.

    Returns the destination paths that were created. A destination is written only
    when it does not already exist (operator edits are preserved) and the profile
    source file is present.
    """
    created: list[Path] = []
    for src, dest in bootstrap_doc_targets(root):
        if dest.exists() or not src.is_file():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        created.append(dest)
    return created


def bootstrap_script_targets(root: Path) -> list[tuple[Path, Path]]:
    """Map each bootstrap script to (source_in_profile, destination_in_repo)."""
    source_root = profile_root()
    return [(source_root / rel, bootstrap_dest(root, rel)) for rel in BOOTSTRAP_SCRIPTS]


def missing_bootstrap_scripts(root: Path) -> list[str]:
    """Bootstrap scripts whose source exists in the profile but is absent here.

    Paths are reported relative to the repo root at the vendored destination
. The source (`scripts/<name>`) and the
    destination (`.ai-task/scripts/<name>`) are now always distinct paths, so the
    self-copy guard below never triggers in the profile; it is retained only as a
    defensive identity check.
    """
    return [
        f"{APP_DIR}/{rel}"
        for rel, (src, dest) in zip(
            BOOTSTRAP_SCRIPTS, bootstrap_script_targets(root), strict=True
        )
        if src.is_file() and src.resolve() != dest.resolve() and not dest.exists()
    ]


def copy_bootstrap_scripts(root: Path) -> list[tuple[Path, str]]:
    """Vendor profile-owned helper scripts into the repo.

    A script is profile tooling, not operator data: it is created when missing
    and refreshed to the profile version when the bytes differ, so a stale or
    absent copy in an old repo is brought current on re-init. The destination is
    the repo's gitignored `.ai-task/scripts/<name>`; the script's
    own DATA outputs (BACKLOG.md, backlog/archive/, backlog/id-registry.toml)
    stay in tracked locations regardless of where the tool lives. Operator data
    under `.ai-task/` (state.json, decisions.jsonl, …) is never touched here.
    Returns (destination, action) pairs where action is "created" or "updated".
    The identity case (src and dest resolve to the same file) is skipped as a
    defensive guard; since the destination now lives under `.ai-task/`, src and
    dest are always distinct, so running init inside ai-sdlc-local-kit vendors the script
    into ai-sdlc-local-kit's own gitignored `.ai-task/` rather than self-copying.
    """
    changed: list[tuple[Path, str]] = []
    for src, dest in bootstrap_script_targets(root):
        if not src.is_file() or src.resolve() == dest.resolve():
            continue
        if dest.exists():
            if dest.read_bytes() == src.read_bytes():
                continue
            action = "updated"
        else:
            action = "created"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        changed.append((dest, action))
    return changed


def refresh_tracked_index_guard(root: Path) -> tuple[Path, str] | None:
    """Create or refresh the repo's TRACKED backlog index guard.

    The deliberate exception to "bootstrap files are gitignored": everything
    else vendored here is operator tooling that only Claude Code delivery
    skills run, but the index guard exists FOR the repo's CI, which checks out
    only tracked files. So this one lands at `scripts/backlog-index-guard.py`
    in the repo proper, is committed, and is regenerated (never hand-edited)
    from the store modules - see `ai_task.index_guard`.

    Returns (destination, created|updated|unchanged), or None for a repo the
    guard does not apply to: one that has not migrated to the file-per-task
    store and does not already carry a guard. Init never plants a tracked file
    in a repo that has no generated index to guard.
    """
    if root.resolve() == profile_root() or not guard_applies(root):
        return None
    return write_guard(root)


def legacy_bootstrap_copies(root: Path) -> list[str]:
    """Earlier versions vendored bootstrap docs/scripts straight into the target
    repo's tracked `docs/` and `scripts/` trees. They now live under gitignored
    `.ai-task/`. This reports any leftover tracked copies so init can suggest the
    operator delete them; init never deletes files in a target repo itself.

    The ai-sdlc-local-kit profile's OWN source files live at exactly these relative paths
    (they are the bootstrap source of truth), so any legacy path that resolves to
    the profile source is excluded — running init on the profile must never flag
    its own tracked sources for deletion.
    """
    source_root = profile_root()
    found: list[str] = []
    for rel in (*BOOTSTRAP_DOCS, *BOOTSTRAP_SCRIPTS):
        legacy = root / rel
        if not legacy.is_file():
            continue
        if legacy.resolve() == (source_root / rel).resolve():
            continue
        found.append(rel)
    return found


def quota_statusline_helper_path(root: Path) -> Path:
    return bootstrap_dest(root, QUOTA_STATUSLINE_HELPER)


def quota_statusline_dispatcher_source_path() -> Path:
    return profile_root() / QUOTA_STATUSLINE_DISPATCHER


def quota_statusline_shell_command(root: Path) -> str:
    helper = quota_statusline_helper_path(root)
    return f'python3 "{helper}" --repo "{root}"'


def quota_statusline_project_settings_snippet(root: Path) -> str:
    command = quota_statusline_shell_command(root)
    return json.dumps(
        {
            "statusLine": {
                "type": "command",
                "command": command,
            }
        },
        ensure_ascii=False,
        indent=2,
    )


PROFILE_CONFIG_ENV = "AI_TASK_PROFILE_CONFIG"
PROFILE_CONFIG_LOCAL = "ai-task-profile.local.toml"
PROFILE_CONFIG_EXAMPLE = "ai-task-profile.example.toml"
OWNERSHIP_CHOICES = ("auto", "own", "foreign")
EXCLUDE_LINE = f"/{APP_DIR}/"
_EXCLUDE_EQUIVALENTS = {EXCLUDE_LINE, f"/{APP_DIR}", f"{APP_DIR}/", APP_DIR}
_EXCLUDE_COMMENT = (
    "# ai-task operator tooling: ignored locally, never committed"
)
# An explicit `--ownership own` is remembered in the repo's .ai-task/config.toml,
# so a repository the operator owns but cannot prove by its remote (no origin,
# a local path) is asked about once, not on every init. Only "own" is stored:
# foreign is what an unknown owner gets anyway, and `--ownership foreign`
# removes a stored "own".
OWNERSHIP_CONFIG_KEY = "ownership"
_OWNERSHIP_LINE_RE = re.compile(rf"^{OWNERSHIP_CONFIG_KEY}\s*=.*$", re.MULTILINE)
_OWNERSHIP_COMMENT = "# Set by ai-task init --ownership own."

_URL_REMOTE_RE = re.compile(
    r"^[A-Za-z][\w.+-]*://(?:[^@/]+@)?(?P<host>[^/:]+)(?::\d+)?/(?P<path>.+)$"
)
_SCP_REMOTE_RE = re.compile(r"^(?:[^@/:]+@)?(?P<host>[^/:]+):(?P<path>[^/].*)$")


@dataclass(frozen=True)
class RepoOwnership:
    """Outcome of the ownership decision. ``mode`` is ``own`` or ``foreign``."""

    mode: str
    reason: str
    slug: str | None = None
    #: True when the decision fell back to foreign only because own_remotes is
    #: missing, so the report can say how to configure it.
    unconfigured: bool = False


def profile_config_path() -> Path:
    override = os.environ.get(PROFILE_CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    return profile_root() / PROFILE_CONFIG_LOCAL


def load_own_remotes() -> list[str] | None:
    """Patterns from ``own_remotes`` in the profile config; None when unset.

    An absent, unreadable or malformed file counts as "not configured", and
    the caller then treats every repository as foreign: an unknown owner gets
    the cautious mode, never the one that writes into shared history.
    """
    path = profile_config_path()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    value = data.get("own_remotes")
    if not isinstance(value, list):
        return None
    return [str(item).strip() for item in value if str(item).strip()]


def remote_slug(url: str) -> str | None:
    """``host/owner/repo`` for a remote URL, or None for a local path.

    Accepts https/ssh/git URLs (with or without user and port) and the
    scp-like ``user@host:owner/repo`` form; drops a trailing ``.git``.
    """
    url = url.strip()
    match = _URL_REMOTE_RE.match(url) or _SCP_REMOTE_RE.match(url)
    if match is None:
        return None
    path = re.sub(r"\.git$", "", match.group("path").strip("/"))
    if not path:
        return None
    return f"{match.group('host').lower()}/{path}"


def remote_is_own(slug: str, patterns: list[str]) -> bool:
    """Match ``host/owner/repo`` against ``own_remotes`` glob patterns.

    A pattern without a wildcard also covers everything below it, so
    ``github.com/someone`` means every repository of that owner.
    """
    target = slug.lower()
    for raw in patterns:
        pattern = re.sub(r"^[A-Za-z][\w.+-]*://", "", raw.strip()).strip("/").lower()
        if not pattern:
            continue
        if fnmatch.fnmatchcase(target, pattern) or fnmatch.fnmatchcase(
            target, f"{pattern}/*"
        ):
            return True
    return False


def _git_output(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def decide_ownership(root: Path, override: str = "auto") -> RepoOwnership:
    """Own or foreign, from ``--ownership`` or the origin remote."""
    origin = (_git_output(root, "remote", "get-url", "origin") or "").strip()
    slug = remote_slug(origin) if origin else None
    if override in ("own", "foreign"):
        return RepoOwnership(override, f"set with --ownership {override}", slug)
    if stored_ownership(root) == "own":
        return RepoOwnership(
            "own",
            f"recorded in {APP_DIR}/config.toml by an earlier --ownership own",
            slug,
        )
    if not origin:
        return RepoOwnership("foreign", "no origin remote, owner unknown", None)
    if slug is None:
        return RepoOwnership(
            "foreign", "origin is a local path, owner unknown", None
        )
    patterns = load_own_remotes()
    if patterns is None:
        return RepoOwnership(
            "foreign",
            f"origin {slug}, but own_remotes is not configured in "
            f"{profile_config_path()}",
            slug,
            unconfigured=True,
        )
    if remote_is_own(slug, patterns):
        return RepoOwnership("own", f"origin {slug} matches own_remotes", slug)
    return RepoOwnership("foreign", f"origin {slug} is not in own_remotes", slug)


def _app_config_path(root: Path) -> Path:
    return root / APP_DIR / "config.toml"


def stored_ownership(root: Path) -> str | None:
    """``own`` when an earlier ``--ownership own`` was recorded, else None."""
    try:
        data = tomllib.loads(_app_config_path(root).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return "own" if data.get(OWNERSHIP_CONFIG_KEY) == "own" else None


def record_ownership(root: Path, override: str) -> None:
    """Remember ``--ownership own``; ``--ownership foreign`` forgets it."""
    path = _app_config_path(root)
    if override not in ("own", "foreign") or not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    lines = [
        line
        for line in text.splitlines()
        if line != _OWNERSHIP_COMMENT and not _OWNERSHIP_LINE_RE.match(line)
    ]
    if override == "own":
        # A top-level key must precede the first [table], or TOML files it
        # under that table.
        at = next(
            (i for i, line in enumerate(lines) if line.lstrip().startswith("[")),
            len(lines),
        )
        while at > 0 and not lines[at - 1].strip():
            at -= 1
        lines[at:at] = [_OWNERSHIP_COMMENT, f'{OWNERSHIP_CONFIG_KEY} = "own"']
    updated = "\n".join(lines) + "\n"
    if updated != text:
        path.write_text(updated, encoding="utf-8")


def git_exclude_path(root: Path) -> Path | None:
    """The repository's ``info/exclude`` (shared by all its worktrees)."""
    out = _git_output(root, "rev-parse", "--git-path", "info/exclude")
    if out is None or not out.strip():
        return None
    path = Path(out.strip())
    return path if path.is_absolute() else root / path


def ensure_app_dir_excluded(root: Path) -> str:
    """Add ``/.ai-task/`` to info/exclude: ``added``, ``present`` or ``no-git``."""
    path = git_exclude_path(root)
    if path is None:
        return "no-git"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if any(line.strip() in _EXCLUDE_EQUIVALENTS for line in existing.splitlines()):
        return "present"
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(
        f"{existing}{prefix}{_EXCLUDE_COMMENT}\n{EXCLUDE_LINE}\n", encoding="utf-8"
    )
    return "added"


def tracked_app_files(root: Path) -> list[str]:
    out = _git_output(root, "ls-files", "-z", "--", APP_DIR)
    if not out:
        return []
    return [item for item in out.split("\0") if item]


def gitignore_app_lines(root: Path) -> list[tuple[int, str]]:
    """(line number, text) of every .gitignore line that names .ai-task."""
    path = root / ".gitignore"
    if not path.is_file():
        return []
    return [
        (number, line)
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        )
        if APP_DIR in line
    ]


def foreign_migration_notice(root: Path) -> list[str]:
    """Commands that take an already-tracked .ai-task out of a foreign repo.

    Printed, never run: untracking and editing .gitignore are commits in
    someone else's repository, and the operator makes them.
    """
    tracked = tracked_app_files(root)
    ignore_lines = gitignore_app_lines(root)
    if not tracked and not ignore_lines:
        return []
    lines = [
        (
            "This repository already carries ai-task files in git. To take them "
            "out, run these yourself (init runs none of them):"
        )
    ]
    if tracked:
        lines.append(f"  git rm -r --cached -- {APP_DIR}")
        lines.extend(f"    untracks {item}" for item in tracked)
    if ignore_lines:
        lines.append(
            "  delete these .gitignore lines (info/exclude covers .ai-task/ now):"
        )
        lines.extend(f"    line {number}: {text}" for number, text in ignore_lines)
    lines.append(
        "  then commit. Earlier commits keep the old copies; rewriting history "
        "is out of scope."
    )
    return lines
