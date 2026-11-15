"""Packet and handoff domain for the ai-task CLI.

Imports: ``_shared``, ``backlog`` (Task, parse_backlog, risk_gates),
``verify`` (the web-e2e heuristic behind the skill handoff block), ``review``
. Nothing imports this module inside the package; the
command shells call it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ai_task._shared import app_path
from ai_task.backlog import Task, parse_backlog, risk_gates
from ai_task.review import (
    load_review_registry,
    packet_rework_block,
    review_planning_for_task,
    review_registry_paths,
)
from ai_task.verify import task_context_suggests_web_e2e


def pending_inbox_notes(root: Path, task_id: str, state: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    inbox = app_path(root) / "inbox.jsonl"
    if inbox.exists():
        for line in inbox.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            task_ref = str(entry.get("task_id", ""))
            run_id = str(entry.get("run_id", ""))
            message = str(entry.get("message", "")).strip()
            if not message:
                continue
            if task_ref == task_id:
                messages.append(message)
                continue
            if run_id:
                run = state.get("runs", {}).get(run_id, {})
                if run.get("task_id") == task_id:
                    messages.append(message)
    return messages


def handoff_config(policy: dict[str, Any]) -> dict[str, Any]:
    raw = policy.get("handoff")
    return raw if isinstance(raw, dict) else {}


# Task reports are written on demand: the Progress line, CHANGELOG and
# the commit are the required record, and tasks/<ID>.md is kept only when there is
# something beyond them (measurements, a live probe log, the reason for a decision).
TASK_REPORT_PATTERN = "{task_id}.md"


def task_report_relpath(task_id: str, policy: dict[str, Any]) -> str:
    handoff = handoff_config(policy)
    directory = str(handoff.get("task_report_dir", "tasks")).strip() or "tasks"
    pattern = str(handoff.get("task_report_pattern", TASK_REPORT_PATTERN))
    filename = pattern.format(task_id=task_id)
    return f"{directory}/{filename}".replace("\\", "/")


def task_report_path(root: Path, task_id: str, policy: dict[str, Any]) -> Path:
    return root / task_report_relpath(task_id, policy)


def task_report_exists(root: Path, task_id: str, policy: dict[str, Any]) -> bool:
    return task_report_path(root, task_id, policy).is_file()


def require_task_report(root: Path, policy: dict[str, Any], task_id: str) -> None:
    """Fail closed when the operator asked for a report and it is absent.

    Only `complete --require-report` calls this: a report is optional by default,
    so nothing else treats its absence as a gap.
    """
    if not task_id or task_report_exists(root, task_id, policy):
        return
    rel = task_report_relpath(task_id, policy)
    print(
        f"--require-report: {task_id} has no task report, expected {rel}",
        file=sys.stderr,
    )
    raise SystemExit(1)


def backlog_task_block(root: Path, task_id: str) -> str | None:
    for task in parse_backlog(root):
        if task.id == task_id:
            return task.block
    return None


def backlog_task_is_done(root: Path, task_id: str) -> bool:
    for task in parse_backlog(root):
        if task.id == task_id:
            return task.status == "x"
    return False


def backlog_flip_target(root: Path, task_id: str) -> str:
    """Where the run must flip `- [x]` for this task.

    A migrated repo stores the block in its own file and regenerates the
    read-only BACKLOG.md index; a non-migrated repo still edits BACKLOG.md
    inline.
    """
    if (root / "backlog" / "tasks" / f"{task_id}.md").is_file():
        return f"`backlog/tasks/{task_id}.md`"
    return "`BACKLOG.md`"


def backlog_flip_instruction(root: Path, task_id: str) -> str:
    target = backlog_flip_target(root, task_id)
    if target == "`BACKLOG.md`":
        return f"Mark `- [x]` for this task in {target}"
    return (
        f"Mark `- [x]` for this task in {target}, then regenerate the "
        "BACKLOG.md index (`python scripts/backlog-store.py regenerate`, or "
        "the vendored `.ai-task/scripts/backlog-store.py`) - never edit "
        "BACKLOG.md by hand"
    )


def task_has_progress_line(root: Path, task_id: str) -> bool:
    block = backlog_task_block(root, task_id)
    if block is None:
        return True
    return any(line.strip().startswith("Progress:") for line in block.splitlines())


def warn_release_contract_gaps(
    root: Path, policy: dict[str, Any], task_id: str
) -> list[str]:
    gaps: list[str] = []
    if task_id and not backlog_task_is_done(root, task_id):
        gaps.append(
            f"{task_id} is not marked [x] in {backlog_flip_target(root, task_id)}"
        )
    if task_id and not task_has_progress_line(root, task_id):
        gaps.append(f"{task_id} has no Progress: line under its title")
    return gaps


def packet_skill_handoff_block(task: Task) -> str:
    if not task_context_suggests_web_e2e(task):
        return ""
    return """
## Skills (web/UI)

Load **playwright-skill** from the shared profile when available. Use it for browser automation, local E2E checks, and UI debugging during this task. For Python web UIs, also follow **dev-python-ui** and any framework skill it selects (Streamlit, Gradio, etc.).
"""


def packet_review_stamp(root: Path, task: Task, policy: dict[str, Any]) -> str:
    """Detected-stacks and risk-class lines for the packet header.

    Derived from the same review-planning projection `dor` prints, so the
    backend sees at dispatch what the reviewer will key on afterwards. Purely
    additive and best-effort: with no review registry reachable the stamp is
    empty and the packet is byte-identical to before.
    """
    if not review_registry_paths(root):
        return ""
    try:
        planning = review_planning_for_task(
            root, task, load_review_registry(root), policy
        )
    except (OSError, SystemExit):  # pragma: no cover - defensive
        return ""
    stacks = ", ".join(planning.get("detected_stacks") or []) or "none-detected"
    risk = str(planning.get("risk_class") or "plain")
    gates = ", ".join(planning.get("risk_gates") or [])
    contracts = ", ".join(planning.get("contract_classes") or [])
    detail = "; ".join(part for part in (gates, contracts) if part)
    risk_line = f"{risk} ({detail})" if detail else risk
    return f"Detected stacks: {stacks}\nRisk class: {risk_line}\n"


def packet_text(
    root: Path,
    task: Task,
    policy: dict[str, Any],
    backend_order: list[str],
    *,
    pending_notes: list[str] | None = None,
    rework_block: str = "",
) -> str:
    gates = risk_gates(task, policy)
    notes = pending_notes or []
    notes_block = ""
    if notes:
        joined = "\n".join(f"- {line}" for line in notes)
        notes_block = f"""
## Pending user notes (from inbox; apply on this run)

{joined}
"""
    skill_handoff = packet_skill_handoff_block(task)
    review_stamp = packet_review_stamp(root, task, policy)
    report_rel = task_report_relpath(task.id, policy)
    return f"""# ai-task packet: {task.id}

Task: {task.title}
Phase: {task.phase or "Unspecified"}
Priority: {task.priority}
Size: {task.size}
Depends on: {", ".join(task.depends_on) if task.depends_on else "none"}
Agent preference: {task.agent}
Source: {task.source}{f" · Incident: {task.incident}" if task.incident.strip() else ""}
Backend order: {", ".join(backend_order)}
Review gates: {", ".join(gates) if gates else "none"}
{review_stamp}
## Assigned Scope

Implement exactly this task. Do not pick another backlog item.
Follow root `AGENTS.md`, current repository rules, and the task DoD below.
Update only files needed for this task, plus required docs and task artifacts.

## Backlog Block

{task.block}
{notes_block}{rework_block}{skill_handoff}## Required Handoff

- Verification performed and result.
- A `Progress:` line under the task title: the date, DONE, and what was delivered and verified.
- Task report `{report_rel}` only when there is something to keep beyond the Progress line, `CHANGELOG.md` and the commit: measurements, a live probe log, the reason for a decision.
- {backlog_flip_instruction(root, task.id)}, and add a `CHANGELOG.md` entry when delivery is done (leave uncommitted; teamlead owns the git commit at W4 release).
- Residual risks or blockers.
- Explicit ADR decision note: create/update ADR if required, otherwise state `ADR not required` with the reason.
"""


def generate_packet(
    root: Path,
    task: Task,
    policy: dict[str, Any],
    backend_order: list[str],
    state: dict[str, Any],
    *,
    include_notes: bool = True,
    include_rework: bool = False,
) -> Path:
    packet_dir = app_path(root) / "packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    path = packet_dir / f"{task.id}.md"
    notes = pending_inbox_notes(root, task.id, state) if include_notes else []
    rework = packet_rework_block(root, state, task.id) if include_rework else ""
    path.write_text(
        packet_text(
            root,
            task,
            policy,
            backend_order,
            pending_notes=notes,
            rework_block=rework,
        ),
        encoding="utf-8",
    )
    return path
