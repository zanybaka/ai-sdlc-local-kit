#!/usr/bin/env python3
"""Backlog store CLI: split / regenerate / check / rotate.

Thin wrapper over ``ai_task.backlog_store`` so the storage tool shares the
canonical block parser instead of growing another shadow regex. See that
module and docs/ai-task-backlog-contract.md for the contract.

Runs from two layouts:

- the ai-sdlc-local-kit profile checkout, where the sibling ``ai_task/`` directory is
  the full package with its facade ``__init__.py``;
- a consuming repo, where ``ai-task init`` vendors this shim plus only the
  store's module subset (``ai_task/_shared.py``, ``ai_task/backlog.py``,
  ``ai_task/backlog_store.py``) into gitignored ``.ai-task/scripts/``,
  deliberately WITHOUT the facade ``__init__.py``. For that layout the shim
  registers a synthetic parent package anchored on the sibling directory, so
  ``ai_task.*`` imports resolve against the vendored copies deterministically
  (a same-named package elsewhere on ``sys.path`` cannot shadow them, and no
  ai-sdlc-local-kit path is assumed anywhere).

Usage (``<tool>`` is ``.ai-task/scripts/backlog-store.py`` in a consuming
repo, ``scripts/backlog-store.py`` in the ai-sdlc-local-kit profile):
    python <tool> [--repo PATH] split
    python <tool> [--repo PATH] regenerate
    python <tool> [--repo PATH] check
    python <tool> [--repo PATH] rotate [--dry-run]
    python <tool> [--repo PATH] guard [--check]

``guard`` writes the repo's TRACKED CI guard,
``scripts/backlog-index-guard.py`` - this shim and its modules are gitignored
in a consuming repo, so CI cannot run them; the generated guard is the same
store code bundled into one tracked file. See ai_task/index_guard.py.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PKG_DIR = SCRIPTS_DIR / "ai_task"

if (PKG_DIR / "__init__.py").is_file():
    # Profile checkout: import through the real package (facade __init__).
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
elif "ai_task" not in sys.modules:
    # Vendored layout: synthetic parent package pinned to the sibling dir.
    _package = types.ModuleType("ai_task")
    _package.__path__ = [str(PKG_DIR)]
    sys.modules["ai_task"] = _package

from ai_task.backlog_store import main

if __name__ == "__main__":
    sys.exit(main())
