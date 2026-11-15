"""Backlog domain for the ai-task CLI.

Standalone by design: imports only the stdlib and ai_task._shared - no
subprocess, no state.json. Policy reaches risk_gates as a plain dict
argument, so there is no ai_task.policy import. A mover function that drags
in run-state or journal helpers belongs elsewhere: `enforce_risk_confirm`
wraps `risk_gates` but logs a `--risk-ack` to the decision journal, so it
lives in ai_task.decisions, not here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ai_task._shared import die

# Checkbox states. ``c`` is the negative terminal added by work
# that was dropped, not paused. It is ONE marker, not one per reason - duplicate
# and won't-fix are written on the required ``Canceled:`` line instead of each
# earning a checkbox, because every extra done-like state has to be taught to
# selection, rotation and analytics to buy information a reason string already
# carries.
TASK_STATUSES = " x~c"
CANCELED_STATUS = "c"
_STATUS_CLASS = f"[{TASK_STATUSES}]"

TASK_RE = re.compile(
    rf"^- \[(?P<status>{_STATUS_CLASS})\]\s+(?P<id>[A-Z][A-Z0-9-]*-\d+)\s+"
    r"(?P<title>.+?)\s*$"
)
CHECKBOX_LINE_RE = re.compile(
    rf"^- \[(?P<status>{_STATUS_CLASS})\]\s+(?P<rest>.+?)\s*$"
)
TASK_ID_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9-]*-\d+$")
TASK_ID_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9-]*-")
RISK_WORDS = (
    "contract",
    "schema",
    "migration",
    "auth",
    "oauth",
    "security",
    "protocol",
    "public api",
    "runtime topology",
    "trust boundary",
    "data boundary",
)
# phrases that contain a risk word but are benign (an error-mapping,
# not an API/schema contract). Scrubbed from the text before the word-boundary scan
# so they no longer trip a false-positive risk-keyword gate.
BENIGN_RISK_COMPOUNDS = (
    "error contract",
    "contract test",
)
# anchor on the WORD START only (leading \b, no trailing \b). This
# rejects the false positive "subcontractor" (the risk word is not at a word start)
# while still catching legitimate derived/plural forms the prior substring scan
# flagged — "contracts", "schemas", "migrations", "authentication", "authorization".
# A trailing \b would silently drop all of those, turning a genuine trust-boundary
# task (e.g. "Add OAuth login" / "run database migrations") into a false negative
# that bypasses the gate. Over-matching here is the safe direction (a human just
# confirms); under-matching is not. "oauth" is listed explicitly in RISK_WORDS
# because a leading \b before "auth" cannot reach it inside "oauth".
RISK_WORD_PATTERNS = tuple(
    (word, re.compile(r"\b" + re.escape(word))) for word in RISK_WORDS
)


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    status: str
    phase: str
    index: int
    block: str
    priority: str
    size: str
    depends_on: tuple[str, ...]
    agent: str
    # Provenance: where this task came from, so post-release/ops work is
    # machine-distinguishable from planned delivery. `source` is an enum (planned by
    # default → existing backlogs stay valid); `incident` carries the ref + severity
    # for post-release incident tasks (`Source: incident`).
    source: str = "planned"
    incident: str = ""

    @property
    def is_open(self) -> bool:
        return self.status == " "

    @property
    def is_canceled(self) -> bool:
        """Dropped work. Never selected, archived like done.

        Distinct from deferred on purpose: ``- [~]`` means paused with intent
        and stays in the active file, ``- [c]`` means it will not be done and
        the reason is on the block.
        """
        return self.status == CANCELED_STATUS


def task_metadata(block_lines: list[str], key: str, default: str = "") -> str:
    prefix = f"{key}:"
    for line in block_lines[1:]:
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return default


def parse_backlog(root: Path) -> list[Task]:
    """Canonical backlog reader.

    When ``backlog/tasks/*.md`` exists it is the ONLY source of task blocks:
    the root BACKLOG.md is a regenerated read-only index and is never parsed
    for tasks. An inline task block found next to a populated task-file store
    aborts loudly instead of merging - the dual-read transition window is
    closed, and silently preferring either source is the merge hazard the
    store exists to remove. A repo with no ``backlog/tasks/`` files keeps the
    original inline behavior unchanged (consuming repos migrate on their own
    schedule).
    """
    backlog_path = root / "BACKLOG.md"
    if not backlog_path.exists():
        die(f"BACKLOG.md not found in {root}")
    lines = backlog_path.read_text(encoding="utf-8").splitlines()
    file_tasks = parse_task_files(root)
    if file_tasks:
        inline = parse_backlog_blocks(lines)
        if inline:
            inline_ids = ", ".join(task.id for task in inline)
            die(
                f"inline task block(s) in {backlog_path} alongside a populated "
                f"backlog/tasks/ store: {inline_ids}. BACKLOG.md is a generated "
                "index; move each block into backlog/tasks/<TASK-ID>.md and "
                "regenerate it (python scripts/backlog-store.py regenerate)"
            )
        return file_tasks
    return parse_backlog_blocks(lines)


def store_task_files(root: Path) -> list[Path]:
    """Per-task store files, sorted by filename; [] when the store is absent.

    Only the literal ``backlog/tasks/`` directory counts - ``backlog/archive/``
    (including an archived ``tasks/`` subdirectory) stays invisible to every
    delivery reader.
    """
    tasks_dir = root / "backlog" / "tasks"
    if not tasks_dir.is_dir():
        return []
    return sorted(tasks_dir.glob("*.md"))


def archive_task_files(root: Path) -> list[Path]:
    """Rotated-out per-task files under backlog/archive/tasks/, sorted.

    AUDIT readers only (recurrence, dashboard, artifact check): delivery
    readers never see these. Rotation moves a closed task file here verbatim,
    so history-facing tooling merges this directory alongside the legacy
    ``backlog/archive/BACKLOG-*.md`` archives.
    """
    archive_dir = root / "backlog" / "archive" / "tasks"
    if not archive_dir.is_dir():
        return []
    return sorted(archive_dir.glob("*.md"))


# The numbered archives rotation wrote before the file-per-task store existed.
LEGACY_ARCHIVE_GLOB = "backlog/archive/BACKLOG-*.md"


def archive_id_sources(root: Path) -> tuple[list[Path], list[Path]]:
    """(legacy numbered archives, archived per-task files).

    The rotated-out half of known_id_sources, named once so the id scan and
    the done-id scan below read the same files. A legacy
    backlog/archive/BACKLOG-NNN.md holds many task blocks; an archived
    backlog/archive/tasks/<TASK-ID>.md holds one.
    """
    return sorted(root.glob(LEGACY_ARCHIVE_GLOB)), archive_task_files(root)


def known_id_sources(root: Path) -> tuple[list[Path], list[Path]]:
    """(text files holding task blocks, task files named by their id).

    The same sources scripts/backlog-id-registry.py derives its floors from:
    BACKLOG.md and the legacy archives are read as text, the active and archived
    task dirs by filename. The registry is a standalone vendored script and this
    module is bundled into the tracked CI guard, so neither can import the
    other; tests/test_backlog_store_add.py pins the two source lists together
    instead, so "known" cannot mean one thing to id allocation and another to
    the dependency check.
    """
    legacy_archives, archived_tasks = archive_id_sources(root)
    text_sources: list[Path] = []
    active = root / "BACKLOG.md"
    if active.exists():
        text_sources.append(active)
    text_sources.extend(legacy_archives)
    return text_sources, [*store_task_files(root), *archived_tasks]


def archived_done_ids(root: Path) -> set[str]:
    """Ids of tasks rotation archived as done (`- [x]`).

    The done half of what known_task_ids knows: an archived id is out of the
    active store, so the scheduler cannot see it at all and an open task that
    depends on it waits forever. Rotation archives both terminal
    states, so the blocks are read for their checkbox instead of taking the id
    alone: a canceled (`- [c]`) task was dropped, not delivered, and must keep
    blocking its dependent. A block that does not parse
    contributes nothing, which keeps the dependent blocked rather than
    unblocking it on a file nobody can read.
    """
    legacy_archives, archived_tasks = archive_id_sources(root)
    done: set[str] = set()
    for path in (*legacy_archives, *archived_tasks):
        lines = path.read_text(encoding="utf-8").splitlines()
        done.update(
            task.id for task in parse_backlog_blocks(lines) if task.status == "x"
        )
    return done


def known_task_ids(root: Path) -> set[str]:
    """Every task id this repo has filed: active, archived, legacy-archived.

    What a `Depends on:` may name. Deliberately wider than what delivery reads:
    a dependency on closed work that rotation already moved out is still a real
    dependency, not a typo.
    """
    text_sources, id_files = known_id_sources(root)
    ids = {path.stem for path in id_files if TASK_ID_TOKEN_RE.match(path.stem)}
    for path in text_sources:
        lines = path.read_text(encoding="utf-8").splitlines()
        ids.update(task.id for task in parse_backlog_blocks(lines))
    return ids


def parse_task_files(root: Path) -> list[Task]:
    """Parse the per-task store: one standard task block per file.

    Each ``backlog/tasks/<TASK-ID>.md`` holds one block in the exact
    BACKLOG.md grammar, optionally preceded by its ``## <phase>`` heading (the
    phase-membership record the index generator reads), so the same block
    parser reads it. Files are read sorted by filename with ``index`` growing
    across files, so the (priority, file order) tie-break is deterministic. A
    task id that duplicates an already-parsed id aborts loudly naming both
    files - never silent shadowing.
    """
    sources: dict[str, str] = {}
    file_tasks: list[Task] = []
    index_offset = 0
    for task_file in store_task_files(root):
        file_lines = task_file.read_text(encoding="utf-8").splitlines()
        for task in parse_backlog_blocks(file_lines):
            previous = sources.get(task.id)
            if previous is not None:
                die(
                    f"duplicate task id {task.id}: {task_file} duplicates {previous}"
                )
            sources[task.id] = str(task_file)
            file_tasks.append(replace(task, index=task.index + index_offset))
        index_offset += len(file_lines)
    return file_tasks


def parse_backlog_blocks(lines: list[str]) -> list[Task]:
    tasks: list[Task] = []
    phase = ""
    current_start: int | None = None
    current_match: re.Match[str] | None = None

    def flush(end: int) -> None:
        nonlocal current_start, current_match
        if current_start is None or current_match is None:
            return
        block_lines = lines[current_start:end]
        depends = task_metadata(block_lines, "Depends on")
        # The contract spells an empty value `Depends on:` or `none`.
        if depends.lower() == "none":
            depends = ""
        depends_on = tuple(part.strip() for part in depends.split(",") if part.strip())
        tasks.append(
            Task(
                id=current_match.group("id"),
                title=current_match.group("title"),
                status=current_match.group("status"),
                phase=phase,
                index=current_start,
                block="\n".join(block_lines).strip() + "\n",
                # The defaults below are read-time fallbacks for blocks written
                # before the metadata was required, and they are the reason
                # `backlog-order` once reported `"priority": "P2"` for a block
                # that never said P2. They stay for those older blocks, but the
                # store path can no longer reach them: `backlog-store.py check`
                # and `backlog-order` both refuse an open block that omits what
                # the scheduler acts on, so nothing is scheduled on a value
                # nobody wrote.
                priority=task_metadata(block_lines, "Priority", "P2") or "P2",
                size=task_metadata(block_lines, "Size", "M") or "M",
                depends_on=depends_on,
                agent=task_metadata(block_lines, "Agent", "auto") or "auto",
                source=task_metadata(block_lines, "Source", "planned") or "planned",
                incident=task_metadata(block_lines, "Incident", ""),
            )
        )
        current_start = None
        current_match = None

    for idx, line in enumerate(lines):
        match = TASK_RE.match(line)
        if match:
            flush(idx)
            current_start = idx
            current_match = match
            continue
        if line.startswith("## "):
            flush(idx)
            phase = line[3:].strip()
    flush(len(lines))
    return tasks


DOR_REQUIRED_KEYS = ("Priority", "Size", "Depends on", "Agent")
VALID_PRIORITIES = frozenset({"P0", "P1", "P2", "P3"})
VALID_SIZES = frozenset({"S", "M", "L"})
VALID_AGENTS = frozenset({"auto", "claude", "cursor", "codex", "devin", "human"})
# Task provenance. Optional — a missing `Source:` line means `planned`,
# so existing backlogs stay valid. `incident` is reactive post-release work and must
# name its `Incident:` (ref + severity); `monitoring` is proactive from a signal/trend;
# `owner` is owner-requested ops; `retro` is raised by ai-task-retro.
VALID_SOURCES = frozenset({"planned", "incident", "monitoring", "owner", "retro"})
# Severity → Priority convention for `Source: incident` tasks (documented, not enforced
# by DoR — severity is a judgment): sev1→P0, sev2→P1, sev3→P2, sev4→P3.
INCIDENT_SEVERITY_PRIORITY = {"sev1": "P0", "sev2": "P1", "sev3": "P2", "sev4": "P3"}


@dataclass(frozen=True)
class SharedContractClass:
    name: str
    change_cue: re.Pattern[str]  # task INTRODUCES/CHANGES this shared contract
    already_named: re.Pattern[str]  # DoD already names the matching rebuild doc
    rebuild_invariant: str  # what the DoD must require
    rebuild_doc: str  # the cross-cutting doc that must be rebuilt in the same PR
    # Extra token that must ALSO be present (lowercased text) for the class to fire.
    # Used to scope an ambiguous noun (e.g. "node" only counts inside an n8n context).
    context: re.Pattern[str] | None = None
    # Optional cue matched against the ORIGINAL-case text, for signals that are
    # case-carrying (an UPPER_SNAKE env var name is lost after `.lower()`).
    raw_cue: re.Pattern[str] | None = None


# Change verbs, shared by every class. `change|changes` covers wire-format edits;
# `define/gain` cover common label phrasings ("define a bug label", "the pipeline
# gains a needs-refinement label") the first cut missed.
_CONTRACT_VERBS = (
    r"new|add|adds|added|adding|introduce|introduces|introducing|create|creates|"
    r"creating|register|registers|expose|exposes|rename|renames|change|changes|"
    r"define|defines|defining|gain|gains"
)
# Result verbs (noun-then-verb order), a subset that reads as a completed change.
_CONTRACT_RESULT_VERBS = r"added|introduced|created|registered|renamed|changed|exposed|defined"


def _contract_change_cue(*nouns: str) -> re.Pattern[str]:
    """Match a change verb next to a shared-contract noun on the SAME line.

    Same-line proximity (``[^\\n]``) stops two unrelated sentences from combining
    into a false positive, mirroring the word-boundary discipline of the
    risk-keyword scan: over-matching only costs one advisory WARN
    line, so the cues stay readable rather than exhaustive.
    """
    alt = "|".join(re.escape(noun) for noun in nouns)
    return re.compile(
        rf"\bnew\s+(?:{alt})\b"
        rf"|\b(?:{_CONTRACT_VERBS})\b[^\n]{{0,60}}\b(?:{alt})\b"
        rf"|\b(?:{alt})\b[^\n]{{0,60}}\b(?:{_CONTRACT_RESULT_VERBS})\b"
    )


# Phrases scrubbed (lowercased) before per-class matching, so a UI/accessibility
# "label" does not trip the onboarding-label class. Same shape as the risk-keyword
# BENIGN_RISK_COMPOUNDS scrub.
CONTRACT_CUE_SCRUB = ("aria-label", "aria label", "label component", "<label")

# A DoD that already names any rebuild doc, or explicitly marks the invariant
# not-applicable NEXT TO a rebuild/contract word, has imprinted the invariant --
# suppress the reminder. The not-applicable / n/a marker is anchored to the concept
# (not a bare token) so an unrelated "Estimate: n/a" cannot silence every class.
# This is the "OR explicitly marked not-applicable" escape hatch from the DoD.
REBUILD_SATISFIED_GENERIC = re.compile(
    r"rebuild (?:runbook|doc|docs|checklist)"
    r"|(?:rebuild|invariant|onboarding|contract)[^\n]{0,30}(?:not[- ]applicable|\bn/a\b)"
    r"|(?:not[- ]applicable|\bn/a\b)[^\n]{0,30}(?:rebuild|invariant|onboarding|contract)"
)

SHARED_CONTRACT_CLASSES: tuple[SharedContractClass, ...] = (
    SharedContractClass(
        name="label",
        change_cue=re.compile(
            r"\bnew label\b"
            rf"|\b(?:{_CONTRACT_VERBS})\b[^\n]{{0,60}}\blabels?\b"
            r"|\blabels?\b[^\n]{0,60}\b(?:added|introduced|created|registered|defined)\b"
            # Russian: waves are Russian. "добавить/ввести/создать метку".
            r"|\b(?:добав|введ|созда|регистр)\w*[^\n]{0,40}\bметк\w*"
            r"|\bметк\w*[^\n]{0,40}\b(?:добав|введ|созда|регистр)\w*"
            r"|\bновая метка\b|\bновую метку\b"
        ),
        already_named=re.compile(
            r"\bonboarding label\b|\blabel onboarding\b|\blabel set\b"
            r"|\bonboarding\b[^\n]{0,30}\blabels?\b|\bнабор меток\b"
            r"|\bонбординг\w*[^\n]{0,20}метк"
        ),
        rebuild_invariant="add the new label to the repo's onboarding label set",
        rebuild_doc="the onboarding label set (canonical label-bootstrap list)",
    ),
    SharedContractClass(
        name="n8n node",
        change_cue=re.compile(
            r"\bn8n node\b"
            rf"|\b(?:{_CONTRACT_VERBS})\b[^\n]{{0,60}}\bnode\b"
            r"|\bnode\b[^\n]{0,60}\b(?:added|introduced|created|registered)\b"
        ),
        # "node" is generic (tree node, DOM node, Node.js in a CI workflow), so
        # require an explicit n8n context. A real n8n task names n8n.
        context=re.compile(r"\bn8n\b"),
        already_named=re.compile(r"\bworkflow rebuild\b|\bn8n[^\n]{0,20}runbook\b"),
        rebuild_invariant="add the node to the n8n workflow rebuild runbook",
        rebuild_doc="the n8n workflow rebuild runbook",
    ),
    SharedContractClass(
        name="endpoint",
        # Server-side sense only: bare "route" fires on frontend routers (React/Vue),
        # so require "endpoint" or an explicit "api/http/rest route".
        change_cue=_contract_change_cue(
            "endpoint", "api route", "http route", "rest route"
        ),
        already_named=re.compile(
            r"\bapi surface\b|\boperator checklist\b|\bendpoint list\b"
        ),
        rebuild_invariant="add the endpoint to the API-surface list / operator checklist",
        rebuild_doc="the API-surface list or operator rebuild checklist",
    ),
    SharedContractClass(
        name="env var",
        change_cue=re.compile(
            r"\bnew env[- ]?var\b"
            rf"|\b(?:{_CONTRACT_VERBS})\b[^\n]{{0,60}}"
            r"\b(?:env[- ]?var|environment variable)\b"
            r"|\b(?:env[- ]?var|environment variable)\b[^\n]{0,60}"
            r"\b(?:added|introduced)\b"
        ),
        # Bare UPPER_SNAKE var names (DATABASE_URL, REDIS_URL) survive only in the
        # original-case text; require an env/deploy/secret context to avoid firing
        # on arbitrary snake_case identifiers.
        raw_cue=re.compile(
            r"(?i:\benv\b|\benvironment\b|\bdeploy\b|\bsecrets?\b)[^\n]{0,40}"
            r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b"
            r"|\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b[^\n]{0,40}"
            r"(?i:\benv\b|\benvironment\b|\bdeploy\b|\bsecrets?\b)"
        ),
        already_named=re.compile(
            r"\benv template\b|\benv\.example\b|\bdeploy env\b|\bsecret template\b"
            r"|\benvironment doc\b"
        ),
        rebuild_invariant="add the variable to the env template / deploy env doc",
        rebuild_doc="the env template (.env.example) or deploy env doc",
    ),
    SharedContractClass(
        name="wire format",
        change_cue=re.compile(
            r"\bnew (?:wire[- ]format|wire protocol|message schema|message format"
            r"|payload schema|payload format)\b"
            rf"|\b(?:{_CONTRACT_VERBS})\b[^\n]{{0,60}}"
            r"\b(?:wire[- ]format|on-the-wire|wire protocol|protocol version"
            r"|message schema|message format|json payload|message payload"
            r"|payload schema|payload format|serialization format)\b"
            r"|\b(?:wire[- ]format|on-the-wire|protocol version|message schema"
            r"|json payload|message payload|payload schema|serialization format)\b"
            r"[^\n]{0,60}\b(?:changed|added|introduced)\b"
        ),
        already_named=re.compile(
            r"\bprotocol (?:doc|spec|schema|runbook)\b|\bschema doc\b"
            r"|\bwire[- ]format (?:doc|spec)\b"
        ),
        rebuild_invariant="update the protocol/schema rebuild doc",
        rebuild_doc="the protocol/schema rebuild doc",
    ),
)


@dataclass(frozen=True)
class DorGap:
    task_id: str
    field: str
    reason: str
    action: str | None = None

    def as_dict(self) -> dict[str, str]:
        payload = {"task_id": self.task_id, "field": self.field, "reason": self.reason}
        if self.action is not None:
            payload["action"] = self.action
        return payload


def task_block_lines(task: Task) -> list[str]:
    return task.block.splitlines()


def task_has_metadata_line(task: Task, key: str) -> bool:
    prefix = f"{key}:"
    return any(line.startswith(prefix) for line in task_block_lines(task)[1:])


def collect_unparsed_checkbox_gaps(
    backlog_lines: list[str],
    *,
    task_id: str | None = None,
) -> list[DorGap]:
    """Flag backlog checkbox lines that look like tasks but do not match TASK_RE."""
    gaps: list[DorGap] = []
    for lineno, line in enumerate(backlog_lines, 1):
        checkbox = CHECKBOX_LINE_RE.match(line)
        if not checkbox:
            continue
        if TASK_RE.match(line):
            continue
        rest = checkbox.group("rest").strip()
        if not rest:
            gaps.append(
                DorGap(
                    "(backlog)",
                    "Task id",
                    f"line {lineno}: checkbox line has no task id or title",
                    action="fix_task_id_format",
                )
            )
            continue
        token = rest.split(None, 1)[0]
        if not TASK_ID_PREFIX_RE.match(token):
            continue
        if task_id is not None and token != task_id:
            continue
        if TASK_ID_TOKEN_RE.match(token):
            reason = (
                f"line {lineno}: task id {token!r} must be followed by a short title "
                "(expected: - [ ] PREFIX-123 Title)"
            )
        else:
            reason = (
                f"line {lineno}: task id {token!r} must end with digits only "
                "(e.g. BUG-003, not BUG-B1); put batch labels in the title"
            )
        gaps.append(DorGap(token, "Task id", reason, action="fix_task_id_format"))
    return gaps


def collect_dor_gaps(
    tasks: list[Task],
    *,
    open_only: bool = True,
    task_id: str | None = None,
    backlog_lines: list[str] | None = None,
    extra_known_ids: set[str] | None = None,
) -> list[DorGap]:
    gaps: list[DorGap] = []
    if backlog_lines is not None:
        gaps.extend(collect_unparsed_checkbox_gaps(backlog_lines, task_id=task_id))
    # `extra_known_ids`: ids that exist outside `tasks`. The store
    # validates a single new block before writing it, and with only that block
    # as `tasks` every dependency it names looked unknown.
    known_ids = {task.id for task in tasks} | (extra_known_ids or set())
    for task in tasks:
        if open_only and not task.is_open:
            continue
        if task_id is not None and task.id != task_id:
            continue
        for key in DOR_REQUIRED_KEYS:
            if not task_has_metadata_line(task, key):
                gaps.append(
                    DorGap(task.id, key, f"missing {key}: line in backlog block")
                )
        if (
            task_has_metadata_line(task, "Priority")
            and task.priority not in VALID_PRIORITIES
        ):
            gaps.append(
                DorGap(
                    task.id, "Priority", f"invalid value {task.priority!r} (use P0–P3)"
                )
            )
        if task_has_metadata_line(task, "Size") and task.size not in VALID_SIZES:
            gaps.append(
                DorGap(
                    task.id,
                    "Size",
                    (
                        f"invalid value {task.size!r} (use S, M, or L only; "
                        "XL+ requires product split into S/M child tasks before delivery)"
                    ),
                    action="split_required",
                )
            )
        if task_has_metadata_line(task, "Agent") and task.agent not in VALID_AGENTS:
            gaps.append(DorGap(task.id, "Agent", f"invalid value {task.agent!r}"))
        # Provenance validation. `Source:` is optional but must be a known
        # value when present; a `Source: incident` task must name its `Incident:` so
        # post-release work is traceable to the signal that raised it.
        if task_has_metadata_line(task, "Source") and task.source not in VALID_SOURCES:
            gaps.append(
                DorGap(
                    task.id,
                    "Source",
                    (
                        f"invalid value {task.source!r} "
                        "(use planned, incident, monitoring, owner, or retro)"
                    ),
                )
            )
        if task.source == "incident" and not task.incident.strip():
            gaps.append(
                DorGap(
                    task.id,
                    "Incident",
                    "Source: incident requires an Incident: line (ref + severity, "
                    "e.g. 'Incident: INC-YYYY-MM-DD-01 sev1 (heartbeat flatline)')",
                    action="add_incident_ref",
                )
            )
        for dep in task.depends_on:
            if dep not in known_ids:
                gaps.append(
                    DorGap(task.id, "Depends on", f"unknown dependency {dep!r}")
                )
        if task.priority in {"P0", "P1"} and "risk:" not in task.block.lower():
            gaps.append(
                DorGap(
                    task.id,
                    "Task Context",
                    f"{task.priority} requires Risk: acknowledgment in the task block",
                )
            )
    return gaps


@dataclass(frozen=True)
class RebuildInvariantReminder:
    task_id: str
    contract_class: str
    rebuild_invariant: str
    rebuild_doc: str

    def as_dict(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "contract_class": self.contract_class,
            "rebuild_invariant": self.rebuild_invariant,
            "rebuild_doc": self.rebuild_doc,
        }


def rebuild_invariant_reminders_for_task(task: Task) -> list[RebuildInvariantReminder]:
    """shared-contract changes whose rebuild invariant is not yet in the DoD.
    """
    raw = f"{task.title}\n{task.block}"
    text = raw.lower()
    for phrase in CONTRACT_CUE_SCRUB:
        text = text.replace(phrase, " ")
    reminders: list[RebuildInvariantReminder] = []
    for contract in SHARED_CONTRACT_CLASSES:
        hit = bool(contract.change_cue.search(text))
        if not hit and contract.raw_cue is not None:
            hit = bool(contract.raw_cue.search(raw))
        if not hit:
            continue
        if contract.context is not None and not contract.context.search(text):
            continue
        if contract.already_named.search(text) or REBUILD_SATISFIED_GENERIC.search(text):
            continue
        reminders.append(
            RebuildInvariantReminder(
                task.id,
                contract.name,
                contract.rebuild_invariant,
                contract.rebuild_doc,
            )
        )
    return reminders


def collect_rebuild_invariant_reminders(
    tasks: list[Task],
    *,
    open_only: bool = True,
    task_id: str | None = None,
) -> list[RebuildInvariantReminder]:
    reminders: list[RebuildInvariantReminder] = []
    for task in tasks:
        if open_only and not task.is_open:
            continue
        if task_id is not None and task.id != task_id:
            continue
        reminders.extend(rebuild_invariant_reminders_for_task(task))
    return reminders


def format_rebuild_invariant_reminders(
    reminders: list[RebuildInvariantReminder],
) -> str | None:
    """One 'rebuild invariant missing' soft note for `dor` (not a DoR gap), or None."""
    if not reminders:
        return None
    lines = [
        (
            "shared-contract rebuild invariants missing from DoD (advisory, "
            "not a DoR gap -- imprint into the DoD or mark not-applicable):"
        )
    ]
    for rem in reminders:
        lines.append(
            f"- {rem.task_id}: {rem.contract_class} change -- {rem.rebuild_invariant} "
            f"(rebuild doc: {rem.rebuild_doc})"
        )
    return "\n".join(lines)


def dor_gaps_for_root(
    root: Path,
    *,
    open_only: bool = True,
    task_id: str | None = None,
) -> list[DorGap]:
    tasks = parse_backlog(root)
    task_files = store_task_files(root)
    if task_files:
        # File-per-task store: malformed checkbox lines live in
        # the task files now; the generated index is never scanned for tasks.
        gaps: list[DorGap] = []
        for task_file in task_files:
            gaps.extend(
                collect_unparsed_checkbox_gaps(
                    task_file.read_text(encoding="utf-8").splitlines(),
                    task_id=task_id,
                )
            )
        gaps.extend(collect_dor_gaps(tasks, open_only=open_only, task_id=task_id))
        return gaps
    backlog_path = root / "BACKLOG.md"
    lines = backlog_path.read_text(encoding="utf-8").splitlines()
    return collect_dor_gaps(
        tasks,
        open_only=open_only,
        task_id=task_id,
        backlog_lines=lines,
    )


def print_dor_gaps(gaps: list[DorGap], *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps([gap.as_dict() for gap in gaps], indent=2))
        return
    if not gaps:
        print("DoR: all checked tasks passed.")
        return
    print("DoR failures:")
    for gap in gaps:
        print(f"- {gap.task_id} | {gap.field} | {gap.reason}")


def enforce_dor_gaps(gaps: list[DorGap]) -> None:
    if not gaps:
        return
    print_dor_gaps(gaps)
    die("DoR check failed", 1)


def risk_gates(task: Task, policy: dict[str, Any]) -> list[str]:
    gates: list[str] = []
    high_priority = set(policy.get("review", {}).get("high_priority", ["P0", "P1"]))
    if task.priority in high_priority:
        gates.append(f"high-priority:{task.priority}")
    lowered = f"{task.title}\n{task.block}".lower()
    if policy.get("review", {}).get("require_for_risk_keywords", True):
        # scrub benign compounds first (so "error contract" cannot
        # expose a bare "contract"), then match risk words on word boundaries.
        scrubbed = lowered
        for compound in BENIGN_RISK_COMPOUNDS:
            scrubbed = scrubbed.replace(compound, " ")
        for word, pattern in RISK_WORD_PATTERNS:
            if pattern.search(scrubbed):
                gates.append(f"risk-keyword:{word}")
                break
    return gates
