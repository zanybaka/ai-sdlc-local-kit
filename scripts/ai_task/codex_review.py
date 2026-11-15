"""Codex as a second review vendor for `ai-task review`.

The three review passes of the ai-task-reviewer skill run with the teamlead's
vendor. With `[review.codex] enabled = true` (off by default) `ai-task review`
also runs `codex exec review` on the run's diff and writes its findings into
the run's `review-findings.md`, each tagged with its source. The pass only
reports: the teamlead still records the verdict.

The command reuses the `[backends.codex]` argv recipe of the worker, so the
pass runs the way a Codex worker does after no personal
config.toml, the same instruction budget, the home hooks trust and trust for
the run directory as -c overrides. Two parts differ. The sandbox is
read-only, because a review writes nothing, and the final message has no
worker-done schema, because Codex renders its own review text.

The findings sit between two markers in `review-findings.md`, so a repeated
pass replaces only its own block and the reviewer's findings stay as written.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from ai_task._shared import now
from ai_task.lifecycle import backend_env
from ai_task.policy import bundled_template_policy
from ai_task.review import collect_git_changed_paths
from ai_task.runs import codex_home_hook_trust_args, codex_project_trust_args

CODEX_REVIEW_START = "<!-- codex-review:start -->"
CODEX_REVIEW_END = "<!-- codex-review:end -->"
CODEX_REVIEW_OUTPUT = "codex-review.md"
CODEX_REVIEW_LOG = "codex-review.jsonl"
CODEX_REVIEW_STDERR = "codex-review-stderr.log"
DEFAULT_CODEX_REVIEW_TIMEOUT = 1200
DEFAULT_CODEX_REVIEW_SANDBOX = "read-only"

# Codex priority to the reviewer's severity scale; the reviewer may recalibrate.
CODEX_PRIORITY_SEVERITY = {0: "blocking", 1: "major", 2: "minor", 3: "nit"}

# One finding as codex-rs/protocol/src/review_format.rs renders it:
# "- [P2] Title — /abs/path/file.py:3-5", the body indented by two spaces.
FINDING_LINE_RE = re.compile(
    r"^- (?P<title>.+) — (?P<path>[^—]+):(?P<start>\d+)-(?P<end>\d+)$"
)
PRIORITY_RE = re.compile(r"^\[P(?P<p>\d)\]\s*")
FINDINGS_HEADERS = {"Review comment:", "Full review comments:"}


def codex_review_settings(policy: dict[str, Any]) -> dict[str, Any]:
    section = policy.get("review", {}).get("codex", {})
    return section if isinstance(section, dict) else {}


def codex_review_enabled(policy: dict[str, Any], override: bool | None = None) -> bool:
    if override is not None:
        return override
    return bool(codex_review_settings(policy).get("enabled", False))


def codex_review_backend(policy: dict[str, Any]) -> dict[str, Any]:
    """The `[backends.codex]` recipe of the pass.
    """
    backend = policy.get("backends", {}).get("codex", {})
    if isinstance(backend, dict) and backend.get("args"):
        return backend
    return bundled_template_policy()["backends"]["codex"]


def git_out(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=False
    )
    return (completed.stdout or "").strip() if completed.returncode == 0 else ""


def codex_review_target(
    root: Path,
    run_cwd: Path,
    run_record: dict[str, Any],
    *,
    base: str | None = None,
    commit: str | None = None,
) -> tuple[list[str], str]:
    """The `codex exec review` target flags for the run's diff, and a label.

    An explicit --codex-commit or --codex-base wins. Otherwise uncommitted
    changes in the run cwd are the run's diff, the same set the review packet
    lists. A worktree run whose worker committed is reviewed against the
    branch the repository root has checked out. With neither: ([], reason).
    """
    if commit:
        return ["--commit", commit], f"--commit {commit}"
    if base:
        return ["--base", base], f"--base {base}"
    if collect_git_changed_paths(run_cwd):
        return ["--uncommitted"], "--uncommitted"
    if run_record.get("worktree_path") and run_cwd != root.resolve():
        root_branch = git_out(root, "rev-parse", "--abbrev-ref", "HEAD")
        if root_branch and root_branch != "HEAD":
            ahead = git_out(run_cwd, "rev-list", "--count", f"{root_branch}..HEAD")
            if ahead and ahead != "0":
                return ["--base", root_branch], f"--base {root_branch}"
    return [], "no diff in the run cwd (pass --codex-commit or --codex-base)"


def replace_sandbox(args: list[str], sandbox: str) -> list[str]:
    result: list[str] = []
    replaced = False
    skip = False
    for index, arg in enumerate(args):
        if skip:
            skip = False
            continue
        if arg in {"--sandbox", "-s"} and index + 1 < len(args):
            result.extend(["--sandbox", sandbox])
            replaced = True
            skip = True
            continue
        if arg.startswith("--sandbox="):
            result.append(f"--sandbox={sandbox}")
            replaced = True
            continue
        result.append(arg)
    if not replaced:
        result.extend(["--sandbox", sandbox])
    return result


def codex_review_command(
    policy: dict[str, Any],
    target: list[str],
    *,
    run_cwd: Path,
    output_path: Path,
) -> list[str]:
    """`codex exec ... review <target> -o <file>` from the worker recipe."""
    backend = codex_review_backend(policy)
    settings = codex_review_settings(policy)
    sandbox = str(settings.get("sandbox") or DEFAULT_CODEX_REVIEW_SANDBOX)
    args = [str(arg) for arg in backend.get("args", [])]
    args.extend(str(arg) for arg in backend.get("extra_args", []))
    if not args or args[0] != "exec":
        args = ["exec", *args]
    command = [str(backend.get("command") or "codex"), *replace_sandbox(args, sandbox)]
    if backend.get("hook_trust_from_home"):
        command.extend(codex_home_hook_trust_args())
    if backend.get("trust_run_directory"):
        command.extend(codex_project_trust_args(run_cwd))
    command.append("review")
    command.extend(target)
    command.extend(["--output-last-message", str(output_path)])
    return command


def strip_cwd(text: str, run_cwd: Path) -> str:
    """Drop the run cwd from absolute paths: findings name repository paths."""
    for prefix in {str(run_cwd), str(run_cwd.resolve())}:
        text = text.replace(prefix.rstrip("/") + "/", "")
    return text


def parse_codex_review_text(text: str, run_cwd: Path) -> dict[str, Any]:
    """Split the rendered review into the overall explanation and findings."""
    lines = strip_cwd(text, run_cwd).splitlines()
    explanation: list[str] = []
    findings: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        match = FINDING_LINE_RE.match(line)
        if match:
            title = match.group("title").strip()
            priority = None
            prio = PRIORITY_RE.match(title)
            if prio:
                priority = int(prio.group("p"))
                title = title[prio.end() :].strip()
            current = {
                "title": title,
                "priority": priority,
                "file": match.group("path"),
                "start": int(match.group("start")),
                "end": int(match.group("end")),
                "body": [],
            }
            findings.append(current)
            continue
        if current is not None:
            if line.startswith("  ") or not line.strip():
                current["body"].append(line[2:] if line.startswith("  ") else "")
                continue
            current = None
        if line.strip() in FINDINGS_HEADERS:
            continue
        explanation.append(line)
    for item in findings:
        item["body"] = "\n".join(item["body"]).strip()
    return {"explanation": "\n".join(explanation).strip(), "findings": findings}


def render_codex_block(
    *,
    label: str,
    model: str,
    status: str,
    parsed: dict[str, Any] | None,
    note: str = "",
) -> str:
    lines = [
        CODEX_REVIEW_START,
        "## Codex review pass",
        "",
        f"Source: codex exec review {label}"
        + (f", model {model}" if model else "")
        + f", {now()}. Raw output: `{CODEX_REVIEW_OUTPUT}` in this run directory.",
        (
            "Codex only reports. The reviewer deduplicates and calibrates these findings,"
            " and the teamlead records the verdict."
        ),
        "",
    ]
    if status != "ok" or parsed is None:
        lines.append(
            f"The Codex pass did not finish ({status}): {note or 'no detail'}."
        )
        lines.append(CODEX_REVIEW_END)
        return "\n".join(lines) + "\n"
    if parsed["explanation"]:
        lines.extend([parsed["explanation"], ""])
    if not parsed["findings"]:
        lines.append("Codex reported no findings.")
    for index, item in enumerate(parsed["findings"], start=1):
        priority = item["priority"]
        severity = (
            CODEX_PRIORITY_SEVERITY.get(priority, "minor")
            if priority is not None
            else "minor"
        )
        tag = f" (codex P{priority})" if priority is not None else ""
        lines.extend(
            [
                f"### CX-{index:03d} — {severity}{tag}",
                "- **Source:** codex",
                f"- **File:** {item['file']}:{item['start']}-{item['end']}",
                f"- **Issue:** {item['title']}",
            ]
        )
        if item["body"]:
            body = item["body"].replace("\n", "\n  ")
            lines.append(f"- **Detail:** {body}")
        lines.append("")
    while lines and not lines[-1]:
        lines.pop()
    lines.append(CODEX_REVIEW_END)
    return "\n".join(lines) + "\n"


def write_codex_block(
    findings_path: Path, block: str, *, run_id: str, task_id: str
) -> None:
    """Put the block into review-findings.md, replacing an earlier one."""
    if findings_path.is_file():
        text = findings_path.read_text(encoding="utf-8")
    else:
        text = f"# Review findings\n\nRun: {run_id}\nTask: {task_id}\n"
    start = text.find(CODEX_REVIEW_START)
    end = text.find(CODEX_REVIEW_END)
    if start != -1 and end != -1 and end > start:
        tail = text[end + len(CODEX_REVIEW_END) :].lstrip("\n")
        text = text[:start] + block + (("\n" + tail) if tail else "")
    else:
        text = text.rstrip("\n") + "\n\n" + block
    findings_path.write_text(text, encoding="utf-8")


def last_error_line(*texts: str) -> str:
    for text in texts:
        for line in reversed((text or "").splitlines()):
            if line.strip():
                return line.strip()[:300]
    return ""


def backend_model(backend: dict[str, Any]) -> str:
    args = [str(arg) for arg in backend.get("args", [])]
    for flag in ("--model", "-m"):
        if flag in args and args.index(flag) + 1 < len(args):
            return args[args.index(flag) + 1]
    return ""


def run_codex_review_pass(
    root: Path,
    policy: dict[str, Any],
    run_record: dict[str, Any],
    *,
    run_dir: Path,
    run_cwd: Path,
    base: str | None = None,
    commit: str | None = None,
) -> dict[str, Any]:
    """Run the pass, write the findings block, return the run-record summary."""
    run_id = str(run_record.get("id", "") or run_dir.name)
    task_id = str(run_record.get("task_id", "") or "")
    backend = codex_review_backend(policy)
    model = backend_model(backend)
    findings_path = run_dir / "review-findings.md"
    output_path = run_dir / CODEX_REVIEW_OUTPUT
    target, label = codex_review_target(
        root, run_cwd, run_record, base=base, commit=commit
    )
    summary: dict[str, Any] = {"target": label, "model": model, "at": now()}

    def finish(
        status: str, parsed: dict[str, Any] | None = None, note: str = ""
    ) -> dict[str, Any]:
        summary["status"] = status
        if note:
            summary["note"] = strip_cwd(note, run_cwd)
        if parsed is not None:
            summary["findings"] = len(parsed["findings"])
        block = render_codex_block(
            label=label,
            model=model,
            status=status,
            parsed=parsed,
            note=summary.get("note", ""),
        )
        write_codex_block(findings_path, block, run_id=run_id, task_id=task_id)
        summary["findings_file"] = str(findings_path.relative_to(root))
        return summary

    if not target:
        return finish("skipped", note=label)
    command = codex_review_command(
        policy, target, run_cwd=run_cwd, output_path=output_path
    )
    output_path.unlink(missing_ok=True)
    settings = codex_review_settings(policy)
    timeout = int(settings.get("timeout_seconds") or DEFAULT_CODEX_REVIEW_TIMEOUT)
    log_path = run_dir / CODEX_REVIEW_LOG
    stderr_path = run_dir / CODEX_REVIEW_STDERR
    summary["log"] = str(log_path.relative_to(root))
    try:
        completed = subprocess.run(
            command,
            cwd=run_cwd,
            env=backend_env(backend, root),
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=timeout if timeout > 0 else None,
            check=False,
        )
    except FileNotFoundError:
        return finish("failed", note=f"{command[0]} not found on PATH")
    except subprocess.TimeoutExpired as exc:
        log_path.write_text(str(exc.stdout or ""), encoding="utf-8")
        stderr_path.write_text(str(exc.stderr or ""), encoding="utf-8")
        return finish("timeout", note=f"no result after {timeout} s")
    log_path.write_text(completed.stdout or "", encoding="utf-8")
    stderr_path.write_text(completed.stderr or "", encoding="utf-8")
    summary["exit_code"] = completed.returncode
    if completed.returncode != 0:
        note = (
            last_error_line(completed.stderr, completed.stdout)
            or f"exit {completed.returncode}"
        )
        return finish("failed", note=note)
    try:
        text = output_path.read_text(encoding="utf-8")
    except OSError:
        return finish("failed", note=f"no {CODEX_REVIEW_OUTPUT} after a clean exit")
    summary["output"] = str(output_path.relative_to(root))
    return finish("ok", parse_codex_review_text(text, run_cwd))


def codex_review_line(summary: dict[str, Any]) -> str:
    """One console line about the pass for the teamlead."""
    status = summary.get("status", "?")
    target = summary.get("target", "")
    if status == "ok":
        return (
            f"codex review ({target}): {summary.get('findings', 0)} finding(s) "
            f"in {summary.get('findings_file')}"
        )
    return f"codex review {status}: {summary.get('note', '')}"


def codex_packet_section(summary: dict[str, Any] | None) -> str:
    """The review packet paragraph about the pass, empty when it did not run."""
    if not summary:
        return ""
    status = summary.get("status", "?")
    if status == "ok":
        result = (
            f"{summary.get('findings', 0)} finding(s), already in `review-findings.md` "
            "between the codex-review markers, each with **Source:** codex"
        )
    else:
        result = f"{status}: {summary.get('note', '')}"
    return (
        "## Codex review pass\n\n"
        f"`codex exec review {summary.get('target', '')}` ran as a second vendor: {result}. "
        "Keep that block when you write the findings; the verdict stays with the teamlead.\n\n"
    )
