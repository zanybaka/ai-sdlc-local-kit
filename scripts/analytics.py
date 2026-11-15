"""Project analytics report generator.

The implementation lives in scripts/ai_task/analytics.py; this
file keeps the historical entrypoints working:

python analytics.py --repo /path/to/project
    python analytics.py --repo . --output /tmp/out/report.html
    python analytics.py --repo . --since 7d
    python analytics.py --repo . --since 2026-05-20
    python analytics.py --repo . --since 2026-05-20T14:00:00Z
    ai-task report                         # via ai-task subcommand
    ai-task report --since 7d             # filter runs to last 7 days
"""

import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from ai_task.analytics import *
from ai_task.analytics import main

if __name__ == "__main__":
    raise SystemExit(main())
