#!/usr/bin/env python3
"""Opt-in multi-agent backlog orchestrator - entrypoint shim.

The CLI is intentionally dependency-free so this shared repo can bootstrap
other projects without installing a Python package first. The implementation
lives in the `scripts/ai_task/` package; this
file only puts `scripts/` on sys.path so the package resolves when the script
runs by path (`python3 scripts/ai-task.py`) or through the wrappers
(`bin/ai-task` -> `scripts/ai-task.sh`), then hands over to `ai_task.cli`.

Do not add logic here, and do not import internals from this file: loading it
by path executes a second, separate module object. Import `ai_task` instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from ai_task.cli import main  # noqa: E402 (sys.path shim must run first)

if __name__ == "__main__":
    raise SystemExit(main())
