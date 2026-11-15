---
name: ai-task-reviewer
description: Stack-aware code review after ai-task verify — three passes, structured review-findings.md, handoff to teamlead for verdict. Use when teamlead ran ai-task review or asks for delivery review on a run. Not for implement runs or backlog planning.
---

# ai-task reviewer

You review **one run** after deterministic `verify` passed. You do **not** approve, change backlog, or start `ai-task run`.

## Inputs (read in order)

1. `.ai-task/runs/<run-id>/review-packet.md` (CLI-generated)
2. `review-skills.json` in the same run dir (which stack skills to load)
3. Task packet `.ai-task/packets/<TASK-ID>.md`
4. `verify-report.md` in the run dir
5. Full diff in the run cwd (worktree or repo root), not only diff stat
6. Root `AGENTS.md` and task DoD from the backlog block

Resolve stack skills listed in `review-skills.json` (for example `qt-cpp-review`, `engineering:code-review`); they are **loaded in the fresh review context** (below), not in this session. On contract/migration/`review_gates`, also include **sdlc-contract-guard**. If a listed skill is absent from `skills/` (and not plugin-namespaced), or status is `none-detected`, fall back to **engineering:code-review** / built-in `/code-review`.

## Reviewer independence — bug-finding runs in a fresh context

This session typically just drove the implementation (teamlead invokes review after verify), so it has seen the reasoning that produced the change and will anchor on it. The **three passes execute in a fresh agent context** that has never seen that reasoning:

- **Claude Code:** spawn a subagent — optionally a `.claude/agents` reviewer definition with read-only tools — or invoke the built-in `/code-review` when available.
- **Cursor:** fresh subagent.

For non-Python diffs touching auth/login, user-input rendering (XSS/CSRF), network exposure/ports, container images/manifests, or secrets (`security-review` in `review-skills.json`), also run the built-in `/security-review` in this fresh-context pass and fold its findings into pass 2 (logic).

The fresh context receives **only**:

1. The diff — `git diff` of the run cwd (worktree or repo root), or the changed-file list from the run record / `review-packet.md`
2. The task block (TASK-ID, Task Context, Task DOD) from the task packet / backlog
3. The registry-resolved stack skills to load (with the fallback rule above)
4. The three-pass definitions below (including the UI-interaction template and real-browser evidence gate when applicable) and the raw-findings return format

It must explicitly **NOT** receive the implementing conversation, the implementation reasoning, or run notes explaining why the change was made.

The fresh context returns findings as **raw structured data** — per finding: `file:line`, severity, pass, issue, suggestion. It writes no files and gives no verdict.

**Stays in this session (you):** findings triage and dedup, severity calibration, ADR/registry anchoring, `review-findings.md` assembly (format below, unchanged), and the verdict handoff to teamlead.

### Fresh-context prompt — worked example

```text
You are an adversarial code reviewer. You have NOT seen how this change was
implemented and must not ask for that context.

Task under review:
  WEB-091 — review registry integrity
  DoD: <Task DOD block verbatim>

Load these review skills first: qt-cpp-review, sdlc-contract-guard.
If one is unavailable: engineering:code-review / built-in /code-review.

Evidence (the only code context you get):
  git diff main...HEAD in .ai-task/worktrees/<run-id>
  (or the changed-file list from review-packet.md)

Run three passes: architecture (right files, boundaries, approach);
logic (correctness, edge cases, errors); conventions (style, tests, docs).

Return raw findings only — no verdict, no files. One block per finding:
  file: path/to/file:LINE
  severity: blocking|major|minor|nit|praise
  pass: architecture|logic|conventions
  issue: ...
  suggestion: ...
```

### Fallback — no subagent capability

When the environment cannot spawn a fresh context (no subagent capability, no built-in `/code-review`), same-session review is allowed, but `review-findings.md` MUST open with the one-line warning header:

`> WARNING: same-session review — reviewer saw the implementing reasoning (anchoring-bias risk).`

## Codex pass as a second vendor

When the repository policy has `[review.codex] enabled = true`, or the teamlead ran `ai-task review <run-id> --codex`, the CLI has already run `codex exec review` on the run diff. Its findings sit in `review-findings.md` between `<!-- codex-review:start -->` and `<!-- codex-review:end -->`, with ids `CX-NNN`, a `- **Source:** codex` line each and a severity suggested from the Codex priority. `review-packet.md` says whether the pass ran and how it ended. The switch and its keys are described in `docs/ai-task.md`, section Codex review pass.

- Keep the block when you write the file: put your summary and findings above it and do not edit inside the markers. A repeated pass replaces only the block.
- Every finding of yours carries a source line too: `- **Source:** <vendor of the fresh context>` (for example `claude`).
- Where a `CX` finding and one of yours name the same defect, keep yours, add `Also: CX-NNN` to it, and say so in Summary. Where you disagree with a `CX` finding or its severity, say why in Summary; the block stays as Codex wrote it.
- A `CX` finding counts toward the completion rule and the recommended verdict like your own. Codex gives no verdict: the teamlead records it.
- A pass recorded as `failed`, `timeout` or `skipped` is not a review. Name it in Summary and review the diff as usual.

The teamlead may also add the pass after you finished with `ai-task review <run-id> --codex-only`; it then lands below your findings and needs one more look before the verdict.

## Three passes (executed in the fresh context)

1. **Architecture** — right files, boundaries, approach
2. **Logic** — correctness, edge cases, errors. For **React/UI tasks that touch hooks, effects, network-gated UI, or persisted view state**, run the **UI-interaction review template** (teamlead mirror in `skills/ai-task-teamlead/reference-review-gates.md`):
   - **Effect-dep stability** — unstable `useEffect` / `useLayoutEffect` dependencies (fresh object/array literals from hooks that return new references every render). Example: popup objects in effect deps → effect runs every render, popups close instantly; `tsc` and `vitest` can still pass
   - **Fire-on-action-not-on-mount** — pulse/nonce effects ignore the stale mount value and re-fire per user action (a pulse hook: 0 on mount, +1 post-mount)
   - **Shared-state brushing** — linked hover/spotlight surfaces reuse one shared state, never a fork (a second spotlight task reuses the first one's state)
   - **Persistence keys** — persisted view state restores as a coherent pair (camera + content), per-mode storage keys, writes only while the owning mode is active (example: a restored camera over a force-reset collapse left the only visible card off-screen; jsdom cannot see an off-screen camera)
   - User flows verify cannot exercise (SVG/canvas clicks, drag) — document in findings if tests do not cover them
3. **Conventions** — style, tests, docs. For a diff to a shared skill or the canon: a value of a foreign layer copied into a rule (design-system sizes or thresholds, screen sizes, a path to one application's file, another repository or host) is a `major` finding; the rule should name the owner of the value (the task, the vendored kit, `AGENTS.override.md`), and the value may stay only in a paragraph that starts with a case label. `tests/test_skill_layering.py` catches the mechanical part; the reviewer catches a value the patterns do not know.

When verify is green but an interaction path has no test coverage, note it in Summary and recommend teamlead log `decision log --phase review` before approve.

## Real-browser evidence gate

When the diff **gates on a cross-origin resource, network-status visibility, or a browser-only interaction** (pointer capture, hover, SVG click, real layout), **mocked-fetch/jsdom green is insufficient evidence**: CORS hides cross-origin response status from `fetch` (the status is unreadable, the gate never trips), and jsdom has no real hit-testing or layout.

**Example (an avatar 401 gate):** review praised a «session-wide 401 gate» whose `fetch` HEAD probe was CORS-blind cross-origin and whose `<img>`s rendered optimistically; mocked fetch + jsdom kept tests green while every avatar 401-flooded the live server, and the decision was graded bad. The fix was one hidden `Image()` probe — image load/error events are observable cross-origin even when fetch status is not.

Acceptable evidence — require one, otherwise file a **blocking** finding:

- A **real-browser probe** ran during review: preview/Playwright exercise of the gated path, or a minimal `Image()` / live-`fetch` status probe in a real browser context — cite the observed result in findings.
- Your Summary explicitly recommends the teamlead log **`decision log --phase review --choice approve_with_coverage_gap`** naming what was not exercised, **plus a follow-up task** to close the gap (teamlead files it via product/sdlc-backlog-add).

## Findings file

Write **`.ai-task/runs/<run-id>/review-findings.md`** with stable ids:

```markdown
# Review findings

Run: <run-id>
Task: <TASK-ID>

## Summary
(one paragraph)

## Findings

### F-001 — blocking
- **Source:** claude
- **Pass:** architecture
- **File:** path/to/file
- **Issue:** ...
- **Suggestion:** ...

### F-002 — nit
...
```

Severities: `blocking`, `major`, `minor`, `nit`, `praise`.

## Completion rule (no false nits)

Before you finish, either:

- **≥3 concrete findings** (any severity, including praise), or
- **Zero actionable issues** — state that explicitly in Summary and list praise-only or note «no code changes required»

Do not invent nits to reach a count.

## Handoff to teamlead

You do **not** run `ai-task verdict approve`. Return control to **ai-task-teamlead** with:

- Path to `review-findings.md`
- Recommended verdict: `approve` | `rework` | `split` | `defer` | `escalate`
- If `rework`: list finding ids to fix (all actionable severities use the same rework + `run` path, including minor/nit)

Teamlead records `verdict` and `decision log --phase review` / `verdict`.

## Post-review (teamlead executes, not you)

| Situation | Teamlead action |
|-----------|-----------------|
| Actionable finding | `verdict rework` → `note` → `complete` review run → `run --wait` (retry packet auto-includes `review-findings.md`) → verify → review |
| Out of scope | `verdict split` → sdlc-backlog-add |
| Clean | `verdict approve` autonomously (verify passed, no blocking findings); user gate is `escalate` only |

The post-review table above (Situation / Teamlead action) is the one teamlead follows.
