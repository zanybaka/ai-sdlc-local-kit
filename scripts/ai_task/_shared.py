"""Cross-domain primitives shared by ai_task package modules.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path
from typing import Any, NoReturn

APP_DIR = ".ai-task"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def die(message: str, code: int = 1) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def app_path(root: Path) -> Path:
    return root / APP_DIR


def pid_alive(pid: Any) -> bool | None:
    if not isinstance(pid, int):
        return None
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
