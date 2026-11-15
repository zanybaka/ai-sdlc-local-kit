#!/usr/bin/env python3
"""Link every skill of this repository into ~/.agents/skills for Codex.

Codex reads user skills from ~/.agents/skills (and the older $CODEX_HOME/skills)
and follows directory symlinks there. Other tools install their own skills into
the same folder, so it can never be one link to this repository's skills/
folder. This script, which both link scripts call, keeps one link per skill:

    ~/.agents/skills/<name>  ->  ~/.claude/skills/<name>

The target goes through ~/.claude/skills, which the link scripts point at
skills/ of this clone, so the links keep working after the clone moves and the
link script runs again.

A skill of this repository is an entry of skills/ with a SKILL.md, except one
that itself resolves into ~/.agents/skills (content another tool installed
there and that Codex already sees).

The script owns a link in ~/.agents/skills when the link's target lies under
~/.claude/skills or under skills/ of this clone. It creates the missing links,
repoints an owned link whose target is wrong, and removes an owned link whose
skill is gone. Every other entry (a real folder, a file, a link to anywhere
else) stays as it is, also when it has the name of one of our skills. A second
run with nothing new changes nothing.

A copy of one of our skills left by hand in $CODEX_HOME/skills/<name> (the
older Codex folder) would load next to the link and drift from the source. The
script moves such a folder to $CODEX_HOME/skills.bak.<date>/<name>, where Codex
does not look, and removes an owned link with such a name there.

Usage:
    python3 scripts/link-codex-skills.py            # apply
    python3 scripts/link-codex-skills.py --dry-run  # print the plan, change nothing

Exit codes: 0 done or nothing to do, 2 the script refused to run because
~/.claude/skills is not linked to this clone.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"


@dataclass(frozen=True)
class Action:
    kind: str  # link, relink, remove, skip-foreign, move-copy, remove-codex-link
    path: Path
    target: Path | None = None

    def describe(self) -> str:
        if self.kind == "link":
            return f"Codex skills: link {self.path} -> {self.target}"
        if self.kind == "relink":
            return f"Codex skills: repoint {self.path} -> {self.target}"
        if self.kind == "remove":
            return f"Codex skills: remove stale link {self.path}"
        if self.kind == "skip-foreign":
            return (
                f"Codex skills: left alone {self.path}: it is not a link of this "
                "script, so Codex loads it instead of the skill of this clone"
            )
        if self.kind == "move-copy":
            return f"Codex skills: move hand copy {self.path} -> {self.target}"
        if self.kind == "remove-codex-link":
            return f"Codex skills: remove duplicate link {self.path}"
        raise ValueError(self.kind)


def norm(path: str | os.PathLike[str]) -> str:
    """A comparable absolute form of a path or a raw link target."""
    text = os.fspath(path)
    if text.startswith("\\\\?\\"):  # Windows junction targets come back as \\?\C:\...
        text = text[4:]
    return os.path.normcase(os.path.normpath(text))


def is_link(path: Path) -> bool:
    # os.path.isjunction appeared in Python 3.12; an older Windows python sees
    # only symlinks, and a junction then counts as foreign and stays.
    isjunction = getattr(os.path, "isjunction", None)
    return path.is_symlink() or bool(WINDOWS and isjunction and isjunction(path))


def raw_target(path: Path) -> str:
    target = os.readlink(path)
    if not os.path.isabs(target):
        target = os.path.join(os.path.dirname(path), target)
    return norm(target)


def under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def own_skills(skills_dir: Path, agents_dir: Path) -> list[str]:
    agents_real = norm(os.path.realpath(agents_dir))
    names = []
    for entry in sorted(skills_dir.iterdir()):
        if entry.name.startswith(".") or not (entry / "SKILL.md").is_file():
            continue
        if under(norm(os.path.realpath(entry)), agents_real):
            continue
        names.append(entry.name)
    return names


def plan(
    *,
    home: Path,
    codex_home: Path,
    skills_dir: Path,
    stamp: str,
) -> list[Action]:
    profile_skills = home / ".claude" / "skills"
    agents_dir = home / ".agents" / "skills"
    owned_roots = (norm(profile_skills), norm(skills_dir))
    names = own_skills(skills_dir, agents_dir)
    wanted = set(names)
    actions: list[Action] = []

    present: set[str] = set()
    if agents_dir.is_dir():
        for entry in sorted(agents_dir.iterdir()):
            present.add(entry.name)
            owned = is_link(entry) and any(
                under(raw_target(entry), root) for root in owned_roots
            )
            if not owned:
                if entry.name in wanted:
                    actions.append(Action("skip-foreign", entry))
                continue
            if entry.name not in wanted:
                actions.append(Action("remove", entry))
                continue
            target = profile_skills / entry.name
            if raw_target(entry) != norm(target):
                actions.append(Action("relink", entry, target))
    for name in names:
        if name not in present:
            actions.append(Action("link", agents_dir / name, profile_skills / name))

    codex_skills = codex_home / "skills"
    if codex_skills.is_dir():
        backup = codex_home / f"skills.bak.{stamp}"
        for name in names:
            entry = codex_skills / name
            if is_link(entry):
                if any(under(raw_target(entry), root) for root in owned_roots):
                    actions.append(Action("remove-codex-link", entry))
            elif (entry / "SKILL.md").is_file():
                actions.append(Action("move-copy", entry, backup / name))
    return actions


def remove_link(path: Path) -> None:
    try:
        os.unlink(path)
    except OSError:
        # A directory symlink or junction on Windows; rmdir removes only the link.
        os.rmdir(path)


def make_link(path: Path, target: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, path, target_is_directory=True)
    except OSError:
        if not WINDOWS:
            raise
        # Without Developer Mode Windows refuses symlinks; a junction needs no right.
        subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(path), str(target)],
            check=True,
            capture_output=True,
        )


def apply(action: Action) -> None:
    if action.kind in ("remove", "remove-codex-link"):
        remove_link(action.path)
    elif action.kind == "relink":
        assert action.target is not None
        remove_link(action.path)
        make_link(action.path, action.target)
    elif action.kind == "link":
        assert action.target is not None
        make_link(action.path, action.target)
    elif action.kind == "move-copy":
        assert action.target is not None
        action.target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(action.path), str(action.target))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="print the plan, change nothing"
    )
    args = parser.parse_args(argv)

    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    skills_dir = REPO / "skills"
    profile_skills = home / ".claude" / "skills"
    agents_dir = home / ".agents" / "skills"

    if norm(os.path.realpath(profile_skills)) != norm(os.path.realpath(skills_dir)):
        print(
            f"Codex skills: nothing linked: {profile_skills} does not lead to "
            f"{skills_dir}; run the link script of this clone first",
            file=sys.stderr,
        )
        return 2
    if norm(os.path.realpath(agents_dir)) == norm(os.path.realpath(skills_dir)):
        print(f"Codex skills: {agents_dir} already is the skills folder of this clone")
        return 0

    actions = plan(
        home=home,
        codex_home=codex_home,
        skills_dir=skills_dir,
        stamp=time.strftime("%Y%m%d_%H%M%S"),
    )
    for action in actions:
        line = action.describe()
        print(f"{line} (dry run)" if args.dry_run else line)
        if not args.dry_run:
            apply(action)
    if not any(a.kind != "skip-foreign" for a in actions):
        print(f"Codex skills: {agents_dir} is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
