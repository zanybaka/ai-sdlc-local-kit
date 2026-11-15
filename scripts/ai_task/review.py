"""Review-planning domain for the ai-task CLI.

The review skill registry and everything that decides WHICH review skills a
task or a diff pulls in: registry loading, stack detection (path suffixes,
repo markers, Task Context keywords), the conditional rows (contract guard,
playwright, security, UI design), the plan-time projection
``review_planning_for_task``, changed-path collection, and the rework block
that carries a prior review's findings into the next packet.

Imports: ``_shared``, ``backlog`` (Task), ``init`` (legacy stack detection),
``verify`` (the web-e2e heuristic the playwright row reuses). Nothing above
those; ``packets`` imports this module, not the other way round.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ai_task._shared import die
from ai_task.backlog import Task, rebuild_invariant_reminders_for_task, risk_gates
from ai_task.init import detect_repo_stacks, repo_has_marker, scan_repo_paths
from ai_task.verify import task_context_suggests_web_e2e

PROFILE_ROOT = Path(__file__).resolve().parents[2]


REVIEW_REGISTRY_REL = Path("skills") / "ai-task-reviewer" / "registry.json"
# Plugin-provided review skills: plugin-namespaced ids (any name
# containing ":") or names listed here cannot exist as dirs under skills/, so
# the registry existence check treats them as installed and valid.
KNOWN_PLUGIN_SKILLS = {"engineering:code-review", "security-review"}
CONTRACT_REVIEW_KEYWORDS = (
    "contract",
    "schema",
    "migration",
    "breaking",
    "api surface",
    "protocol",
)
# Security review routing: web/auth/infra security surfaces load
# the built-in /security-review in the fresh-context review pass. Keywords are
# scoped tightly (word-ish forms, no bare "auth"/"session") so the row does
# not fire on every diff; py-security still owns the Python OWASP sweep.
SECURITY_REVIEW_KEYWORDS = (
    " auth ",
    "authentication",
    "authorization",
    "oauth",
    "login",
    "session token",
    "session cookie",
    "xss",
    "csrf",
    "user input",
    "sanitiz",
    "secret",
    "exposed port",
    "network exposure",
    "container image",
    "k8s manifest",
    "kubernetes manifest",
)
# Changed-path surfaces: container images/manifests and network-exposure infra.
SECURITY_REVIEW_PATH_SUFFIXES = [
    "dockerfile",
    "docker-compose.yml",
    "compose.yaml",
    ".tf",
]
# UI/UX design routing: a UI-shaped diff loads the matching design
# skill next to the stack review rows. Two independent triggers per skill —
# changed paths of UI file types, and Task Context phrases that name UI work.
QT_UI_DESIGN_PATH_SUFFIXES = [".qml", ".ui"]
QT_UI_DESIGN_KEYWORDS = (
    "qml",
    "qt quick",
    "qtquick",
    "qt widgets",
    "qwidget",
    "pyside",
    "pyqt",
)
WEB_UI_DESIGN_PATH_SUFFIXES = [
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".jsx",
    ".tsx",
    ".vue",
    ".svelte",
]
WEB_UI_DESIGN_KEYWORDS = (
    "landing page",
    "tailwind",
    "css",
    "html markup",
    # Stems, so Russian case endings match ("вёрстку", "вёрсткой").
    "вёрстк",
    "верстк",
)
# Shared UI vocabulary. Bare "design" and "layout" also describe schema and
# architecture work, so the generic words appear only in UI-bound forms, and
# this list fires only next to a matching UI stack — never on its own.
UI_DESIGN_REVIEW_KEYWORDS = (
    "ui design",
    "ux design",
    "ui/ux",
    "ui-фикс",
    "ui фикс",
    "design system",
    "screen layout",
    "ui layout",
    "дизайн интерфейса",
    "макет экрана",
    "mockup",
    "мокап",
    "wireframe",
    "responsive layout",
    "accessibility",
)
QT_UI_DESIGN_STACKS = {"qt-qml", "qt-cpp"}
WEB_UI_DESIGN_STACKS = {"javascript", "typescript"}


def review_registry_paths(root: Path) -> list[Path]:
    candidates = [
        root / REVIEW_REGISTRY_REL,
        PROFILE_ROOT / REVIEW_REGISTRY_REL,
    ]
    return [path for path in candidates if path.is_file()]


def load_review_registry(root: Path) -> dict[str, Any]:
    for path in review_registry_paths(root):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            die(f"invalid review registry {path}: {exc}")
    die(
        f"review registry not found (expected {REVIEW_REGISTRY_REL} in repo or ai-sdlc-local-kit profile)"
    )


def registry_stack_ids(registry: dict[str, Any]) -> set[str]:
    stacks = registry.get("stacks", {})
    return set(stacks.keys()) if isinstance(stacks, dict) else set()


def review_skill_exists(name: str, root: Path | None = None) -> bool:
    """A registry skill is installed if plugin-provided or a skills/ dir exists.

    Checked roots mirror review_registry_paths: the target repo (when given)
    and the ai-sdlc-local-kit profile checkout that hosts this script.
    """
    if ":" in name or name in KNOWN_PLUGIN_SKILLS:
        return True
    candidates = [PROFILE_ROOT / "skills" / name]
    if root is not None:
        candidates.append(root / "skills" / name)
    return any((path / "SKILL.md").is_file() for path in candidates)


def _path_matches_suffix(path: str, suffixes: list[str]) -> bool:
    lowered = path.lower()
    return any(lowered.endswith(suffix.lower()) for suffix in suffixes)


def detect_stacks_from_paths(
    paths: Iterable[str], registry: dict[str, Any]
) -> set[str]:
    stacks_cfg = registry.get("stacks", {})
    if not isinstance(stacks_cfg, dict):
        return set()
    found: set[str] = set()
    for stack_id, cfg in stacks_cfg.items():
        if not isinstance(cfg, dict):
            continue
        suffixes = [str(item) for item in cfg.get("path_suffixes", [])]
        if suffixes and any(_path_matches_suffix(path, suffixes) for path in paths):
            found.add(stack_id)
    return found


# Repo-marker stacks per (resolved root, registry content), for the life of the
# process. dor, plan and packet generation ask once per task, and one ai-task
# process is one command on one repository state, so the tree is walked once per
# run instead of once per task. The key holds the registry's
# content because packet generation reloads it into a new dict for every task.
_REPO_MARKER_STACKS: dict[tuple[Path, str], frozenset[str]] = {}


def detect_stacks_from_repo_markers(root: Path, registry: dict[str, Any]) -> set[str]:
    key = (root.resolve(), json.dumps(registry, sort_keys=True))
    if key not in _REPO_MARKER_STACKS:
        _REPO_MARKER_STACKS[key] = frozenset(_scan_repo_marker_stacks(root, registry))
    return set(_REPO_MARKER_STACKS[key])


def _scan_repo_marker_stacks(root: Path, registry: dict[str, Any]) -> set[str]:
    stacks_cfg = registry.get("stacks", {})
    if not isinstance(stacks_cfg, dict):
        return set()
    paths = scan_repo_paths(root)
    found: set[str] = set()
    for stack_id, cfg in stacks_cfg.items():
        if not isinstance(cfg, dict):
            continue
        for marker in cfg.get("repo_markers", []):
            pattern = str(marker)
            if "*" in pattern:
                if repo_has_marker(paths, pattern):
                    found.add(stack_id)
                    break
            elif (root / pattern).exists():
                found.add(stack_id)
                break
    legacy = detect_repo_stacks(root, paths)
    if "python" in legacy:
        found.add("python")
    if "go" in legacy:
        found.add("go")
    if "dotnet" in legacy:
        found.add("dotnet")
    if "node" in legacy:
        found.add("javascript")
        if repo_has_marker(paths, "tsconfig.json"):
            found.add("typescript")
    return found


def detect_stacks_from_task_context(
    task: Task | None, registry: dict[str, Any]
) -> set[str]:
    if not task:
        return set()
    text = f"{task.title}\n{task.block}".lower()
    stacks_cfg = registry.get("stacks", {})
    if not isinstance(stacks_cfg, dict):
        return set()
    found: set[str] = set()
    for stack_id, cfg in stacks_cfg.items():
        if not isinstance(cfg, dict):
            continue
        for keyword in cfg.get("context_keywords", []):
            if str(keyword).lower() in text:
                found.add(stack_id)
                break
    return found


def detect_stacks_predictive(
    root: Path, task: Task | None, registry: dict[str, Any]
) -> set[str]:
    stacks = detect_stacks_from_repo_markers(root, registry)
    stacks |= detect_stacks_from_task_context(task, registry)
    return stacks


def review_skills_status(
    registry: dict[str, Any], stacks: set[str], *, paths_present: bool = False
) -> str:
    known = registry_stack_ids(registry)
    if not stacks:
        return "none-detected" if paths_present else "ok"
    if stacks <= known:
        return "ok"
    if stacks & known:
        return "partial"
    return "missing"


def task_context_names_unknown_stack(
    task: Task | None, registry: dict[str, Any]
) -> bool:
    if not task:
        return False
    text = f"{task.title}\n{task.block}".lower()
    hints = (
        "rust",
        "ruby",
        "kotlin",
        "swift",
        "java",
        "scala",
        "php",
        "elixir",
        "haskell",
        # Infra/SQL hints: suppressed while the shipped registry
        # rows carry matching context_keywords; fire on stripped-down registries.
        "docker",
        "terraform",
        "kubernetes",
        "helm",
        "sql",
    )
    known_keywords: set[str] = set()
    stacks_cfg = registry.get("stacks", {})
    if isinstance(stacks_cfg, dict):
        for cfg in stacks_cfg.values():
            if isinstance(cfg, dict):
                known_keywords.update(
                    str(k).lower() for k in cfg.get("context_keywords", [])
                )
    for hint in hints:
        if (
            hint in text
            and hint not in known_keywords
            and not any(hint in k for k in known_keywords)
        ):
            return True
    return False


def resolve_review_skills(
    registry: dict[str, Any],
    *,
    stacks: set[str],
    task: Task | None,
    run_record: dict[str, Any] | None,
    policy: dict[str, Any] | None,
    root: Path | None = None,
    changed_paths: list[str] | None = None,
) -> dict[str, Any]:
    stacks_cfg = registry.get("stacks", {})
    skills: list[str] = []
    for stack_id in sorted(stacks):
        cfg = stacks_cfg.get(stack_id, {}) if isinstance(stacks_cfg, dict) else {}
        if isinstance(cfg, dict):
            for skill in cfg.get("skills", []):
                name = str(skill).strip()
                if name and name not in skills:
                    skills.append(name)
    gates = list(run_record.get("review_gates", [])) if run_record else []
    contract_signal = gates or (
        task
        and any(
            word in f"{task.title}\n{task.block}".lower()
            for word in CONTRACT_REVIEW_KEYWORDS
        )
    )
    if contract_signal and "sdlc-contract-guard" not in skills:
        skills.append("sdlc-contract-guard")
    if (
        task
        and task_context_suggests_web_e2e(task)
        and "playwright-skill" not in skills
    ):
        skills.append("playwright-skill")
    # Security routing: built-in /security-review for web/auth/infra
    # security surfaces — Task Context keywords or changed image/manifest paths.
    task_text = f"{task.title}\n{task.block}".lower() if task else ""
    if "security-review" not in skills and (
        any(word in task_text for word in SECURITY_REVIEW_KEYWORDS)
        or any(
            _path_matches_suffix(path, SECURITY_REVIEW_PATH_SUFFIXES)
            for path in changed_paths or []
        )
    ):
        skills.append("security-review")
    # UI/UX design routing: UI-shaped diffs load the design skills.
    for skill_name, suffixes, own_keywords, ui_stacks in (
        (
            "qt-ui-design",
            QT_UI_DESIGN_PATH_SUFFIXES,
            QT_UI_DESIGN_KEYWORDS,
            QT_UI_DESIGN_STACKS,
        ),
        (
            "dev-web-ui-design",
            WEB_UI_DESIGN_PATH_SUFFIXES,
            WEB_UI_DESIGN_KEYWORDS,
            WEB_UI_DESIGN_STACKS,
        ),
    ):
        if skill_name in skills:
            continue
        if (
            any(
                _path_matches_suffix(path, suffixes) for path in changed_paths or []
            )
            or any(word in task_text for word in own_keywords)
            or (
                stacks & ui_stacks
                and any(word in task_text for word in UI_DESIGN_REVIEW_KEYWORDS)
            )
        ):
            skills.append(skill_name)
    status = review_skills_status(registry, stacks, paths_present=bool(changed_paths))
    missing = sorted(stacks - registry_stack_ids(registry))
    # Registry rows can point at skills that exist nowhere (phantom rows);
    # downgrade to partial and name them instead of false "ok".
    missing_skills = sorted(
        skill for skill in skills if not review_skill_exists(skill, root)
    )
    if status == "ok" and missing_skills:
        status = "partial"
    return {
        "stacks": sorted(stacks),
        "skills": skills,
        "status": status,
        "missing_stacks": missing,
        "missing_skills": missing_skills,
        "review_skills_missing": status in {"missing", "none-detected"}
        or (status == "partial" and bool(missing))
        or bool(missing_skills)
        or task_context_names_unknown_stack(task, registry),
        "registry_hint": "docs/ai-task-review-registry.md",
    }


def task_risk_class(task: Task, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Risk classification for one task, stamped at DoR time.

    ``class`` is a single coarse label for scanning: ``high-priority`` when a
    priority gate fires (it needs an explicit approval), else
    ``shared-contract`` when the task touches a rebuild-invariant contract
    class, else ``risk-keyword``, else ``plain``.
    """
    gates = risk_gates(task, policy or {})
    contract_classes = sorted(
        {rem.contract_class for rem in rebuild_invariant_reminders_for_task(task)}
    )
    if any(gate.startswith("high-priority:") for gate in gates):
        label = "high-priority"
    elif contract_classes:
        label = "shared-contract"
    elif gates:
        label = "risk-keyword"
    else:
        label = "plain"
    return {
        "class": label,
        "gates": gates,
        "contract_classes": contract_classes,
    }


def review_planning_for_task(
    root: Path,
    task: Task,
    registry: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stacks = detect_stacks_predictive(root, task, registry)
    resolved = resolve_review_skills(
        registry, stacks=stacks, task=task, run_record=None, policy=policy, root=root
    )
    risk = task_risk_class(task, policy)
    return {
        "task_id": task.id,
        "review_stack": resolved["stacks"],
        "detected_stacks": resolved["stacks"],
        "risk_class": risk["class"],
        "risk_gates": risk["gates"],
        "contract_classes": risk["contract_classes"],
        "review_skills_status": resolved["status"],
        "review_skills_missing": resolved["review_skills_missing"],
        "review_skills": resolved["skills"],
        "missing_skills": resolved["missing_skills"],
        "registry_hint": resolved["registry_hint"]
        if resolved["review_skills_missing"]
        else None,
    }


def collect_git_changed_paths(cwd: Path) -> list[str]:
    paths: set[str] = set()
    for cmd in (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
    ):
        completed = subprocess.run(
            cmd, cwd=cwd, text=True, capture_output=True, check=False
        )
        for raw in (completed.stdout or "").splitlines():
            line = raw.strip()
            if line:
                paths.add(line)
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    for raw in (untracked.stdout or "").splitlines():
        line = raw.strip()
        if line:
            paths.add(line)
    return sorted(paths)


def find_review_findings_path(
    root: Path, state: dict[str, Any], task_id: str
) -> Path | None:
    candidates: list[tuple[str, Path]] = []
    for run in state.get("runs", {}).values():
        if str(run.get("task_id", "")) != task_id:
            continue
        run_dir = root / str(run.get("run_dir", "") or "")
        findings = run_dir / "review-findings.md"
        if findings.is_file():
            stamp = str(run.get("finished_at") or run.get("created_at") or "")
            candidates.append((stamp, findings))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def packet_rework_block(root: Path, state: dict[str, Any], task_id: str) -> str:
    findings_path = find_review_findings_path(root, state, task_id)
    if not findings_path:
        return ""
    try:
        body = findings_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    rel = findings_path.relative_to(root)
    return f"""
## Rework from code review (apply on this run)

Source: `{rel}`

{body}
"""
