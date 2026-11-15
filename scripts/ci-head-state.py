#!/usr/bin/env python3
"""read the CI state of one commit from a GitHub Actions runs answer.

propagate-agents.sh --commit pipes the answer of
`gh api repos/<owner>/<repo>/actions/runs?head_sha=<full sha>&status=completed`
into this script before it pushes onto a default branch. The canon rule
(context/AGENTS.md, Pushing when CI is metered) is to push only the fix onto a
red default branch, so a red head makes the caller skip that repository.

Each workflow counts by its latest completed run for the commit. The head is red
when the latest run of any workflow failed, timed out or could not start. It is
green when at least one workflow has a run and none of them is red. With no
completed run the state is unknown, and the caller reports it as not checked.

Runs with the event "dynamic" do not count. GitHub starts them on
the default-branch head by itself, for example a Dependabot updates job that
could not open a PR, so no push started them and no fix push turns them green.

Output: one line "<state> <detail>", state is red, green or none.
Exit codes: 0 parsed, 2 the input is not a runs answer.
"""

from __future__ import annotations

import json
import sys

RED_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})
# GitHub-managed runs (Dependabot updates and the like), not CI of the commit.
IGNORED_EVENTS = frozenset({"dynamic"})


def latest_per_workflow(runs: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for run in runs:
        if run.get("status") != "completed" or run.get("event") in IGNORED_EVENTS:
            continue
        key = str(run.get("workflow_id") or run.get("name") or "?")
        stamp = (str(run.get("created_at") or ""), int(run.get("run_attempt") or 0))
        held = latest.get(key)
        if held is None or stamp > held["_stamp"]:
            latest[key] = {**run, "_stamp": stamp}
    return latest


def classify(answer: object) -> tuple[str, str]:
    """Return (state, detail) for a decoded runs answer."""
    if not isinstance(answer, dict) or not isinstance(answer.get("workflow_runs"), list):
        raise TypeError("not an actions runs answer")
    latest = latest_per_workflow(answer["workflow_runs"])
    if not latest:
        return "none", "no completed CI run for the head"
    red = sorted(
        f"{run.get('name') or key}={run.get('conclusion')}"
        for key, run in latest.items()
        if run.get("conclusion") in RED_CONCLUSIONS
    )
    if red:
        return "red", ", ".join(red)
    return "green", f"{len(latest)} workflow(s), none red"


def main() -> int:
    try:
        state, detail = classify(json.load(sys.stdin))
    except (ValueError, TypeError) as exc:
        print(f"unreadable runs answer: {exc}", file=sys.stderr)
        return 2
    print(f"{state} {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
