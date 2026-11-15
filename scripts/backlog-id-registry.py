#!/usr/bin/env python3
"""Backlog id-registry helper.

Computes per-prefix task-id maxima by scanning the active ``BACKLOG.md``,
every ``backlog/archive/BACKLOG-*.md`` file, and - in a file-per-task repo
- the task-file names in ``backlog/tasks/`` and
``backlog/archive/tasks/``, so new tasks never reuse an id that already exists
in archived (rotated-out) work. Shared by the ``sdlc-backlog-rotate`` skill and
``sdlc-backlog-add`` / ``sdlc-backlog-decompose`` when allocating ids.

Usage (``<helper>`` is ``.ai-task/scripts/backlog-id-registry.py`` in a
consuming repo, ``scripts/backlog-id-registry.py`` in the ai-sdlc-local-kit profile):
    python <helper> scan [--repo PATH] [--json]
    python <helper> update [--repo PATH] [--json] [--registry PATH] \
        [--reason TEXT]

Subcommands:
    scan    Print current per-prefix maxima without writing anything.
    update  Recompute maxima and (re)write the registry TOML file.

Exit codes:
    0  Success.
    2  Error (repo path missing, etc.).

The registry is written as hand-rolled TOML (stdlib has ``tomllib`` for reads
only); the format is intentionally small and stable.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

TASK_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)-(\d+)\b")

# A backlog task line: ``- [ ]`` / ``- [x]`` / ``- [~]`` (any indentation).
CHECKBOX_RE = re.compile(r"^\s*-\s*\[[ xX~]\]\s+")

DEFAULT_REGISTRY_REL = "backlog/id-registry.toml"
ARCHIVE_GLOB = "backlog/archive/BACKLOG-*.md"

# File-per-task store dirs: the filename IS the task id
#, so floors are derived from filenames in
# both the active and the archived task directories. Text scanning of
# BACKLOG.md and the legacy BACKLOG-*.md archives stays, so non-migrated
# repos keep working unchanged.
TASK_DIR_RELS = ("backlog/tasks", "backlog/archive/tasks")
FILENAME_ID_RE = re.compile(r"^([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)-(\d+)$")

# Where this helper can live. Consuming repos get it vendored
# under gitignored ``.ai-task/scripts/`` by ``ai-task init``;
# only the ai-sdlc-local-kit profile checkout has it under ``scripts/``. The registry
# TOML is tracked while the helper is not, so a header that names one fixed
# path is wrong for every reader in the other layout.
#
# The profile path is probed FIRST: it is tracked wherever it
# exists, so the header comes out the same on every checkout of a repo. With
# the untracked vendored copy first, a profile machine that had run
# ``ai-task init`` and one that had not wrote different headers into the
# tracked TOML. A consuming repo has no ``scripts/backlog-id-registry.py`` and
# lands on the vendored path either way.
GENERATOR_RELS = (
    "scripts/backlog-id-registry.py",
    ".ai-task/scripts/backlog-id-registry.py",
)
VENDORED_GENERATOR_REL = GENERATOR_RELS[1]

# the same floors are also stated in prose, in the `next ids:`
# line of the human-readable backlog header, and until now nothing wrote it -
# a sentence in the ROTATION skill asked a human to, while ids are handed out
# by sdlc-backlog-add, so the header lagged from allocation until the next
# rotation repaired it. The regeneration guard cannot catch that by
# construction: the header reaches a fresh regeneration from the skeleton
# unchanged, so a wrong header reproduces byte for byte and the index is
# self-consistent and wrong at once. `update` now rewrites the id tokens in
# that line, in the same run that writes the TOML.
#
# Dual layout, same contract the store tool follows: the header lives in
# `backlog/index-skeleton.md` once a repo is on the file-per-task store, and
# directly in BACKLOG.md while it is not.
HEADER_RELS = ("backlog/index-skeleton.md", "BACKLOG.md")
HEADER_IDS_RE = re.compile(r"(?P<lead>next ids:\s*)(?P<ids>[^)]*)(?P<tail>\))")


def _id_width(num: int) -> int:
    """Zero-pad width for a suffix: minimum 3 digits (repo convention)."""
    return max(3, len(str(num)))


def task_ids_in_text(text: str) -> list[tuple[str, int]]:
    """Return ``(prefix, number)`` for the first id on every checkbox line.

    Only the leading id token on a task checkbox line is treated as a real task
    id. Lines that are not checkbox lines, and trailing tokens on a checkbox
    line, are ignored.
    """
    out: list[tuple[str, int]] = []
    for line in text.splitlines():
        if not CHECKBOX_RE.match(line):
            continue
        m = TASK_ID_RE.search(line)
        if m is None:
            continue
        out.append((m.group(1), int(m.group(2))))
    return out


def backlog_sources(repo: Path) -> list[Path]:
    """Active backlog plus every archive file, in deterministic order."""
    sources: list[Path] = []
    active = repo / "BACKLOG.md"
    if active.exists():
        sources.append(active)
    sources.extend(sorted(repo.glob(ARCHIVE_GLOB)))
    return sources


def task_dir_sources(repo: Path) -> list[Path]:
    """File-per-task store dirs that exist in this repo."""
    return [repo / rel for rel in TASK_DIR_RELS if (repo / rel).is_dir()]


def task_ids_from_filenames(task_dir: Path) -> list[tuple[str, int]]:
    """(prefix, number) from every ``<PREFIX-NNN>.md`` filename in a dir."""
    out: list[tuple[str, int]] = []
    for path in sorted(task_dir.glob("*.md")):
        m = FILENAME_ID_RE.match(path.stem)
        if m is None:
            continue
        out.append((m.group(1), int(m.group(2))))
    return out


def scan_maxima(repo: Path) -> dict[str, int]:
    """Per-prefix max suffix: backlog text scans plus task-file filenames."""
    maxima: dict[str, int] = {}

    def bump(prefix: str, num: int) -> None:
        if num > maxima.get(prefix, -1):
            maxima[prefix] = num

    for path in backlog_sources(repo):
        text = path.read_text(encoding="utf-8")
        for prefix, num in task_ids_in_text(text):
            bump(prefix, num)
    for task_dir in task_dir_sources(repo):
        for prefix, num in task_ids_from_filenames(task_dir):
            bump(prefix, num)
    return maxima


def registry_payload(repo: Path, *, reason: str | None = None) -> dict[str, object]:
    """Build the JSON-serializable registry payload from a fresh scan."""
    maxima = scan_maxima(repo)
    sources = [str(p.relative_to(repo)) for p in backlog_sources(repo)]
    sources.extend(
        f"{d.relative_to(repo).as_posix()}/ (filenames)"
        for d in task_dir_sources(repo)
    )
    prefixes: dict[str, dict[str, object]] = {}
    for prefix in sorted(maxima):
        max_seen = maxima[prefix]
        next_num = max_seen + 1
        prefixes[prefix] = {
            "max_seen": f"{prefix}-{max_seen:0{_id_width(max_seen)}d}",
            "max_seen_num": max_seen,
            "next_free": f"{prefix}-{next_num:0{_id_width(next_num)}d}",
            "next_free_num": next_num,
        }
    payload: dict[str, object] = {
        # UTC, matching ai_task._shared.now(), so the stamp does not depend on
        # which timezone the operator ran the update from.
        "generated": dt.datetime.now(dt.timezone.utc).date().isoformat(),
        "sources": sources,
        "prefixes": prefixes,
    }
    if reason:
        payload["reason"] = reason
    return payload


def generator_rel(repo: Path) -> str:
    """Repo-relative path of the helper a reader of this repo can actually run.

    Returns the tracked profile path when ``repo`` holds it, and the vendored
    path otherwise - which is where ``ai-task init`` will put it, so the header
    stays actionable even in a fresh clone where the gitignored copy is gone.
    Whether the vendored copy exists right now is deliberately not consulted.
    """
    profile_rel = GENERATOR_RELS[0]
    if (repo / profile_rel).is_file():
        return profile_rel
    return VENDORED_GENERATOR_REL


def header_lines(repo: Path) -> list[str]:
    """Comment block for the registry file, resolved against this repo."""
    rel = generator_rel(repo)
    return [
        "# Backlog id registry.",
        "# Regenerated by the sdlc-backlog-rotate skill, not maintained by hand.",
        f"# Regenerate: python {rel} update",
        '# Helper missing? It is vendored, not tracked - run "ai-task init" to restore it.',
        "# Per-prefix floors across active BACKLOG.md, backlog/archive/BACKLOG-*.md,",
        "# and task-file names in backlog/tasks/ and backlog/archive/tasks/.",
        "# Never allocate a new task id with a suffix <= max_seen for its prefix.",
        "",
    ]


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _toml_str_array(values: list[str]) -> str:
    inner = ", ".join(f'"{_toml_escape(v)}"' for v in values)
    return f"[{inner}]"


def render_toml(payload: dict[str, object], *, repo: Path | None = None) -> str:
    """Render the registry payload as stable, hand-rolled TOML.

    ``repo`` decides which helper path the header names; without it the header
    falls back to the vendored location that consuming repos have.
    """
    lines: list[str] = header_lines(repo if repo is not None else Path("."))
    generated = payload["generated"]
    assert isinstance(generated, str)
    lines.append(f'generated = "{_toml_escape(generated)}"')
    reason = payload.get("reason")
    if isinstance(reason, str) and reason:
        lines.append(f'reason = "{_toml_escape(reason)}"')
    sources = payload["sources"]
    assert isinstance(sources, list)
    lines.append(f"sources = {_toml_str_array([str(s) for s in sources])}")
    lines.append("")
    prefixes = payload["prefixes"]
    assert isinstance(prefixes, dict)
    for prefix, info in prefixes.items():
        assert isinstance(info, dict)
        lines.append(f"[prefixes.{prefix}]")
        lines.append(f'max_seen = "{_toml_escape(str(info["max_seen"]))}"')
        lines.append(f"max_seen_num = {int(info['max_seen_num'])}")  # type: ignore[arg-type]
        lines.append(f'next_free = "{_toml_escape(str(info["next_free"]))}"')
        lines.append(f"next_free_num = {int(info['next_free_num'])}")  # type: ignore[arg-type]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def header_path(repo: Path) -> Path | None:
    """Where the human-readable `next ids:` line lives, or None if nowhere.

    The skeleton wins when it exists: in a migrated repo BACKLOG.md is
    generated from it, so writing the index directly would be overwritten by
    the next regeneration.
    """
    for rel in HEADER_RELS:
        candidate = repo / rel
        if candidate.is_file():
            return candidate
    return None


def rewrite_header_ids(text: str, prefixes: dict[str, object]) -> str:
    """Replace each id token in the `next ids:` list with its next free id.

    Only the tokens move. The rest of the line - the registry path, the
    skill pointer, the regeneration hint - is not this function's business,
    and the prefixes keep the order the header already had. A token whose
    prefix is unknown to the registry is left alone rather than dropped:
    the header may legitimately name a prefix that has no task yet.
    """

    def replace_ids(match: re.Match[str]) -> str:
        def replace_one(id_match: re.Match[str]) -> str:
            info = prefixes.get(id_match.group(1))
            if not isinstance(info, dict):
                return id_match.group(0)
            return str(info["next_free"])

        return (
            match.group("lead")
            + TASK_ID_RE.sub(replace_one, match.group("ids"))
            + match.group("tail")
        )

    return HEADER_IDS_RE.sub(replace_ids, text, count=1)


def write_header(repo: Path, payload: dict[str, object]) -> Path | None:
    """Sync the prose header with the payload. Returns the path if it changed.

    Byte-identical output is written nowhere: a re-run with nothing newly
    allocated must not churn a diff.
    """
    path = header_path(repo)
    if path is None:
        return None
    prefixes = payload["prefixes"]
    assert isinstance(prefixes, dict)
    before = path.read_text(encoding="utf-8")
    after = rewrite_header_ids(before, prefixes)
    if after == before:
        return None
    path.write_text(after, encoding="utf-8")
    return path


def write_registry(repo: Path, registry_path: Path, *, reason: str | None = None) -> dict[str, object]:
    """Recompute and write the registry TOML; return the payload."""
    payload = registry_payload(repo, reason=reason)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(render_toml(payload, repo=repo), encoding="utf-8")
    return payload


def _print_human_scan(payload: dict[str, object]) -> None:
    prefixes = payload["prefixes"]
    assert isinstance(prefixes, dict)
    if not prefixes:
        print("No task ids found in BACKLOG.md or archives.")
        return
    print("Per-prefix id floors (active + archive):")
    for prefix, info in prefixes.items():
        assert isinstance(info, dict)
        print(f"  {prefix:<12} max_seen={info['max_seen']}  next_free={info['next_free']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute / persist per-prefix backlog id floors (active + archive)."
    )
    parser.add_argument("--repo", default=".", help="Repository root (default: current directory)")
    parser.add_argument("--json", action="store_true", help="Output payload as JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Print current per-prefix maxima (no write)")
    # Accept --json after the subcommand too, so position does not matter.
    p_scan.add_argument("--json", action="store_true", dest="json", help="Output payload as JSON")

    p_update = sub.add_parser("update", help="Recompute and (re)write the registry file")
    p_update.add_argument("--json", action="store_true", dest="json", help="Output payload as JSON")
    p_update.add_argument(
        "--registry",
        default=None,
        help=f"Registry path (default: <repo>/{DEFAULT_REGISTRY_REL})",
    )
    p_update.add_argument("--reason", default=None, help="One-line reason recorded in the registry")

    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"error: repo path does not exist: {repo}", file=sys.stderr)
        return 2

    if args.command == "scan":
        payload = registry_payload(repo)
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            _print_human_scan(payload)
        return 0

    # update
    registry_path = (
        Path(args.registry).resolve()
        if args.registry
        else repo / DEFAULT_REGISTRY_REL
    )
    payload = write_registry(repo, registry_path, reason=args.reason)
    header = write_header(repo, payload)
    # Leaving the operator half-updated is the failure this replaces, so an
    # edited skeleton says so in one line: BACKLOG.md is generated from it and
    # `backlog-store.py check` stays red until the index is regenerated.
    header_note = None
    if header is not None:
        header_rel = header.relative_to(repo)
        header_note = f"Synced `next ids:` header: {header_rel}"
        if header_rel.name != "BACKLOG.md":
            header_note += " - run `backlog-store.py regenerate` to update BACKLOG.md"
    if args.json:
        print(
            json.dumps(
                {
                    "written": str(registry_path),
                    "header_written": str(header) if header else None,
                    **payload,
                },
                indent=2,
            )
        )
    else:
        print(f"Wrote registry: {registry_path}")
        if header_note:
            print(header_note)
        _print_human_scan(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
