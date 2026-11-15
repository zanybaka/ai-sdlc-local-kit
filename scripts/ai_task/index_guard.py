"""Tracked backlog index guard: generate, refresh, verify.

This module closes that gap with ONE TRACKED, self-contained file in the
consumer, ``scripts/backlog-index-guard.py``, whose body is the store's own
code - bundled, never re-implemented:

- the bundle is ``ai_task/_shared.py`` + ``ai_task/backlog.py`` +
  ``ai_task/backlog_store.py`` concatenated with their intra-package imports
  stripped (those three import only the stdlib and each other), plus a small
  generated CLI trailer exposing ``check`` (what CI runs), ``regenerate``
  (the fix) and ``source-hash`` (provenance);
- it is TRACKED on purpose. That is the single documented exception to the
  data-tracked / tool-gitignored split (docs/ai-task.md): CI must run the
  guard from a plain checkout, so the guard - and only the guard - travels
  with the data it guards. Writers keep using the vendored store;
- staleness is detectable rather than silently old, by two detectors covering
  two different hops. The file embeds ``GUARD_SOURCE_SHA256`` over its own
  inputs, and ``backlog-store.py guard --check`` recomputes that digest from
  the modules PRESENT IN THAT REPO: it catches a hand-edited guard, or one
  left behind by an init that refreshed the modules. It deliberately cannot
  see the profile - a consumer has no path to it - so a repo that has not
  re-initialized reads ``fresh`` while the profile moves on. Closing that hop
  is ``ai-task init``, which re-vendors and rewrites; the guard being tracked
  is what turns that refresh into a git diff instead of a silent update.

Bundling rather than vendoring the package: the consumer's tracked tree gains
ONE obviously-generated artifact instead of an ``ai_task/`` subpackage, and a
future intra-package import that would silently break a vendored copy at CI
time instead breaks :func:`build_guard_source` here, inside ai-sdlc-local-kit's own
test suite.

The generated file is deliberately byte-identical in every repo (no path
probing in the header), so the digest means the same thing everywhere. It is
also NOT named ``backlog-store.py``: ``backlog_store.GENERATOR_RELS`` resolves
the regenerate command named in the index marker from the tool paths present
in the tree, and a second file with that name would make the marker - and so
the guard's own byte comparison - differ between a local run and a CI
checkout.
"""

from __future__ import annotations

import ast
import hashlib
import io
import tokenize
from pathlib import Path

from ai_task._shared import die

# Destination in the consuming repo, relative to its root. Tracked.
GUARD_REL = "scripts/backlog-index-guard.py"
# Bundled store modules, in dependency order (each may import only the stdlib
# and modules earlier in this tuple).
GUARD_MODULES: tuple[str, ...] = ("_shared.py", "backlog.py", "backlog_store.py")
# Bump when the bundling layout (header/trailer/assembly) changes so every
# consumer's digest moves and `guard --check` reports the copy as stale.
# 2: header carries the linter/formatter exemptions.
# 3: comments and docstrings are stripped from the bundled bodies, and the
#    header and trailer name no repository or task: the file lands in public repos too.
GUARD_FORMAT_VERSION = "3"

# Emitted into the header, before the first line of code. Order matters only for
# `fmt: off`, which must precede what it silences; the rest are file-scoped and
# read top-down by a human. Pinned by tests so a bundler refactor cannot drop
# them silently - a dropped line means a consumer's CI goes red for artifacts of
# OUR bundling, in a file their repo is not supposed to care about.
GUARD_LINT_DIRECTIVES: tuple[str, ...] = (
    "# ruff: noqa",
    "# flake8: noqa",
    "# pylint: skip-file",
    "# fmt: off",
)

_BUNDLED_IMPORT_NAMES = tuple(f"ai_task.{Path(name).stem}" for name in GUARD_MODULES)

GUARD_HEADER = '''#!/usr/bin/env python3
"""GENERATED FILE - DO NOT EDIT. Backlog index guard.

The file-per-task backlog store's own code, bundled into one self-contained
script so a plain checkout - a CI runner, which never has the gitignored
`.ai-task/` tree - can verify that BACKLOG.md still equals a fresh
regeneration from `backlog/tasks/`. Tracked on purpose: the store tool is
otherwise operator-local, and CI cannot run a tool it never checks out.

Usage:
    python3 @@GUARD_REL@@ check        # exit 1 when the index drifted (CI)
    python3 @@GUARD_REL@@ regenerate   # rebuild BACKLOG.md from backlog/tasks/
    python3 @@GUARD_REL@@ source-hash  # provenance of this generated copy

A repo that has not migrated to the file-per-task store (no
`backlog/index-skeleton.md`) passes `check` untouched - there is no generated
index to guard.

Refresh - never hand-edit - with the backlog store tool:
    python3 .ai-task/scripts/backlog-store.py guard
`guard --check` exits 1 when this file is stale or hand-edited, and
`ai-task init` rewrites it whenever the profile moves; being tracked, every
refresh shows up in `git status` instead of ageing silently.

Bundled from: @@MODULES@@ (intra-package imports, comments and docstrings
stripped).
Source digest: sha256:@@SHA@@ (bundle format @@FORMAT@@).
"""

# Inert to linters and formatters BY CONSTRUCTION, so a repo that
# vendors this file needs no lint configuration of its own. Flattening leaves
# artifacts that are correct for a bundle and meaningless as project debt: each
# bundled module keeps its own stdlib imports, so the same import repeats and
# sits mid-file, and the code is formatted to the profile's width rather than
# this repo's. Suppress here rather than rewriting the code: the guard's whole
# value is being the store's own code byte-for-byte, and a bundler that also
# reformats would be a second thing to trust.
@@LINT@@

from __future__ import annotations
'''

GUARD_TRAILER = '''# ===========================================================================
# generated guard CLI
# ===========================================================================

# sha256 over the bundled module sources plus the generator templates. The
# store's `guard --check` recomputes it from the local modules, so a copy that
# fell behind the profile - or was hand-edited - is detected, not trusted.
GUARD_SOURCE_SHA256 = "@@SHA@@"
GUARD_REL = "@@GUARD_REL@@"


def guard_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=Path(GUARD_REL).name,
        description=(
            "Backlog index guard: verify the generated BACKLOG.md against a "
            "fresh regeneration from backlog/tasks/. Generated "
            "file - refresh it with the backlog store's `guard` command."
        ),
    )
    parser.add_argument(
        "--repo", default=".", help="Repository root (default: current directory)"
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("check", help="Exit 1 when BACKLOG.md drifted (default; CI gate)")
    sub.add_parser("regenerate", help="Rebuild BACKLOG.md from backlog/tasks/")
    sub.add_parser("source-hash", help="Print the digest of the bundled sources")
    args = parser.parse_args(argv)

    if (args.command or "check") == "source-hash":
        print(GUARD_SOURCE_SHA256)
        return 0

    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"error: repo path does not exist: {repo}", file=sys.stderr)
        return 2
    if (args.command or "check") == "regenerate":
        print(f"regenerated {regenerate(repo)}")
        return 0

    if not (repo / SKELETON_REL).exists():
        print(
            f"{SKELETON_REL} absent: {repo} is not on the file-per-task store, "
            "so BACKLOG.md is not a generated index - nothing to guard."
        )
        return 0
    problems = check(repo)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        # The problem text names the store tool, which lives in the gitignored
        # `.ai-task/` tree - right for the operator who will fix this locally,
        # absent for whoever is reading a CI log. Name the fix that works from
        # a plain checkout too.
        print(
            f"fix: edit backlog/tasks/<TASK-ID>.md, then run `python3 "
            f"{GUARD_REL} regenerate` (works from any checkout) and commit "
            "the regenerated index.",
            file=sys.stderr,
        )
        return 1
    print("BACKLOG.md matches regeneration.")
    return 0


if __name__ == "__main__":
    sys.exit(guard_main())
'''


def module_dir() -> Path:
    """Directory holding the store modules bundled into the guard.

    Anchored on this file, so it resolves to the profile package in ai-sdlc-local-kit
    and to the vendored ``.ai-task/scripts/ai_task/`` copy in a consuming repo
    - the guard a consumer generates is built from the modules that consumer
    actually runs.
    """
    return Path(__file__).resolve().parent


def _read_modules(modules_dir: Path) -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    for name in GUARD_MODULES:
        path = modules_dir / name
        if not path.is_file():
            die(
                f"cannot build the backlog index guard: {path} not found "
                "(re-run `ai-task init` to refresh the vendored store modules)"
            )
        sources.append((name, path.read_text(encoding="utf-8")))
    return sources


def _catches_import_error(node: ast.Try) -> bool:
    for handler in node.handlers:
        expr = handler.type
        names = []
        if isinstance(expr, ast.Name):
            names = [expr.id]
        elif isinstance(expr, ast.Tuple):
            names = [e.id for e in expr.elts if isinstance(e, ast.Name)]
        guarded = ("ImportError", "ModuleNotFoundError", "Exception")
        if any(name in guarded for name in names):
            return True
    return False


def _is_main_guard(node: ast.If) -> bool:
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.comparators) != 1:
        return False
    left, right = test.left, test.comparators[0]
    return (
        isinstance(left, ast.Name)
        and left.id == "__name__"
        and isinstance(right, ast.Constant)
        and right.value == "__main__"
    )


def _imported_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    return [node.module or ""]


def _is_ai_task(name: str) -> bool:
    return name == "ai_task" or name.startswith("ai_task.")


def _strip_module(name: str, source: str) -> str:
    """Module body with `__future__` and bundled intra-package imports removed.

    Dies loudly on any other ``ai_task`` import that is not wrapped in an
    ImportError-guarded ``try`` (the store's own optional hook back into this
    module is - it degrades to "guard generation unavailable" inside the
    bundle). That refusal is the point: a new hard dependency must break the
    bundler in ai-sdlc-local-kit's test suite, not the guard in someone's CI.
    """
    tree = ast.parse(source, filename=name)
    dropped: set[int] = set()
    optional_spans: list[tuple[int, int]] = []
    for node in tree.body:
        if isinstance(node, ast.Try) and _catches_import_error(node):
            optional_spans.append((node.lineno, node.end_lineno or node.lineno))
            continue
        if isinstance(node, ast.If) and _is_main_guard(node):
            # A bundled module's own `if __name__ == "__main__":` would run
            # ITS cli instead of the guard's, since the bundle is the module.
            dropped.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        if module == "__future__" or module in _BUNDLED_IMPORT_NAMES:
            dropped.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
        elif _is_ai_task(module):
            die(
                f"cannot bundle {name}: top-level `from {module} import ...` at "
                f"line {node.lineno} is outside the guard's module set "
                f"{list(GUARD_MODULES)}. Add the module to GUARD_MODULES, move "
                "the import into an ImportError-guarded try, or keep the store "
                "modules stdlib-only (ai_task/index_guard.py)."
            )
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if not any(_is_ai_task(target) for target in _imported_names(node)):
            continue
        if node.lineno in dropped:
            continue
        if any(low <= node.lineno <= high for low, high in optional_spans):
            continue
        die(
            f"cannot bundle {name}: ai_task import at line {node.lineno} is "
            "neither in the guard's module set nor guarded by "
            "`except ImportError` (ai_task/index_guard.py)."
        )
    lines = source.splitlines()
    kept = [line for number, line in enumerate(lines, 1) if number not in dropped]
    return "\n".join(kept).strip("\n")


def _docstring_spans(tree: ast.AST) -> list[tuple[int, int, int, bool]]:
    """(first line, last line, indent, sole statement) of every docstring in the tree."""
    spans = []
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = node.body
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            spans.append(
                (body[0].lineno, body[0].end_lineno or body[0].lineno,
                 body[0].col_offset, len(body) == 1)
            )
    return spans


def _strip_comments_and_docstrings(source: str) -> str:
    """The module body without comments and docstrings.

    The bundle lands in every repo that uses the store, public ones included, and
    the comments of this profile are internal notes that the bundle does not need. The
    code stays as written: only comment tokens and docstring statements go, so the
    guard is still the store's own code. A docstring that is the whole body becomes
    ``pass`` to keep the block valid.
    """
    lines = source.split("\n")
    tree = ast.parse(source)
    remove: set[int] = set()
    replace: dict[int, str] = {}
    for first, last, indent, sole in _docstring_spans(tree):
        if sole:
            replace[first] = " " * indent + "pass"
            remove.update(range(first + 1, last + 1))
        else:
            remove.update(range(first, last + 1))
    trimmed: dict[int, str] = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        number, column = token.start
        if number in remove:
            continue
        if lines[number - 1][:column].strip() == "":
            remove.add(number)
        else:
            trimmed[number] = lines[number - 1][:column].rstrip()
    kept = []
    for number, line in enumerate(lines, 1):
        if number in remove:
            continue
        kept.append(replace.get(number, trimmed.get(number, line)))
    text = "\n".join(kept)
    # Removing a comment block can leave runs of blank lines; two is enough.
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")
    return text.strip("\n")


def source_digest(modules_dir: Path | None = None) -> str:
    """sha256 over the bundle inputs: module sources plus the generator templates."""
    sources = _read_modules(modules_dir or module_dir())
    digest = hashlib.sha256()
    digest.update(GUARD_FORMAT_VERSION.encode("utf-8"))
    for name, text in sources:
        digest.update(b"\0")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(text.encode("utf-8"))
    digest.update(b"\0")
    digest.update(GUARD_HEADER.encode("utf-8"))
    digest.update(b"\0")
    digest.update(GUARD_TRAILER.encode("utf-8"))
    # The directives live outside the template, so hash them too - otherwise
    # editing the list would leave every vendored copy reading as fresh.
    for directive in GUARD_LINT_DIRECTIVES:
        digest.update(b"\0")
        digest.update(directive.encode("utf-8"))
    return digest.hexdigest()


def _render(template: str, sha: str) -> str:
    return (
        template.replace("@@SHA@@", sha)
        .replace("@@GUARD_REL@@", GUARD_REL)
        .replace("@@MODULES@@", ", ".join(f"ai_task/{name}" for name in GUARD_MODULES))
        .replace("@@FORMAT@@", GUARD_FORMAT_VERSION)
        .replace("@@LINT@@", "\n".join(GUARD_LINT_DIRECTIVES))
    )


def build_guard_source(modules_dir: Path | None = None) -> str:
    """Render the tracked guard: header, bundled module bodies, guard CLI."""
    modules_dir = modules_dir or module_dir()
    sources = _read_modules(modules_dir)
    sha = source_digest(modules_dir)
    parts = [_render(GUARD_HEADER, sha)]
    for name, text in sources:
        parts.append(
            "# ===========================================================================\n"
            f"# ai_task/{name} (bundled, intra-package imports stripped)\n"
            "# ===========================================================================\n"
            f"{_strip_comments_and_docstrings(_strip_module(name, text))}\n"
        )
    parts.append(_render(GUARD_TRAILER, sha))
    return "\n\n".join(parts)


def guard_applies(root: Path) -> bool:
    """True when the repo is on the store, or already carries a guard to refresh."""
    from ai_task.backlog_store import SKELETON_REL

    return (root / SKELETON_REL).is_file() or (root / GUARD_REL).is_file()


def write_guard(root: Path, *, modules_dir: Path | None = None) -> tuple[Path, str]:
    """Create or refresh the tracked guard. Returns (path, created|updated|unchanged)."""
    dest = root / GUARD_REL
    source = build_guard_source(modules_dir)
    if dest.is_file() and dest.read_text(encoding="utf-8") == source:
        return dest, "unchanged"
    action = "updated" if dest.exists() else "created"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(source, encoding="utf-8")
    return dest, action


def guard_status(root: Path, *, modules_dir: Path | None = None) -> tuple[str, str]:
    """(state, message) for the tracked guard: missing | stale | fresh."""
    dest = root / GUARD_REL
    if not dest.is_file():
        missing = (
            f"{GUARD_REL} not generated - run `backlog-store.py guard` and "
            "commit it, so this repo's CI can run the index guard"
        )
        return "missing", missing
    if dest.read_text(encoding="utf-8") != build_guard_source(modules_dir):
        stale = (
            f"{GUARD_REL} differs from the store modules in this repo "
            "(hand-edited, or left behind by an `ai-task init` that refreshed "
            "them) - run `backlog-store.py guard` and commit the refresh"
        )
        return "stale", stale
    fresh = (
        f"{GUARD_REL} matches the store sources "
        f"(sha256:{source_digest(modules_dir)})"
    )
    return "fresh", fresh
