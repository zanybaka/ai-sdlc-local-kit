---
name: sdlc-spec-sync
description: >-
  Reconciles written specs with the real codebase by reviewing git history
  (scope chosen with rationale and user confirmation when not preset), then
  verifying each material commit against current code so later changes can
  supersede earlier ones. Integrates findings natively into existing headings
  and lists. Searches for *TZ*.md, OVERVIEW.md, PRD.md, TECHSPEC.md
  (case-insensitive names). Use when aligning specs with reality, after a
  sprint, before handoff, or when backfilling forgotten requirements from
  commits.
---

# Sync ТЗ from git (spec backfill)

## Goal

Close the gap between **what the code actually does at `HEAD` (and the working tree if in scope)** and **what the spec files claim**. Git history is for **discovery** (what changed, when, hints from messages); **the live code is the source of truth** for what to write in the ТЗ. Update specs so new or corrected requirements read **native**: the right subsection, same voice and numbering style, as if the document had always described the current behavior. Avoid bolt-on blocks titled “дополнения / sync / changelog” unless the user explicitly wants that format.

## When you start

1. Confirm the **git repository root** (usually the workspace root; if the user named another path, use that). Specs are **only** those files inside that repo — do not assume a shared global `context/` or home-linked PRD outside the project.
2. **Git scope**
   - If the user already gave a **commit range**, **branch**, **tag**, **date**, or explicit **“last N commits”**: use it; state briefly what you are analyzing (no extra confirmation unless the range is enormous or ambiguous).
   - Otherwise **you choose the scope**, then **ask the user once** to confirm or adjust before you do the deep pass:
     - Skim enough history to decide (e.g. `git log --oneline` over a wider window, merge bases, tags, subject patterns, which subtrees changed).
     - Propose a concrete scope: e.g. “last **N** commits”, **`since-tag`..`HEAD`**, or **SHA range**, and explain **why** (e.g. natural story boundary, all commits touching module X, gap after last release tag, tail of noisy commits is docs-only).
     - If reasonable alternatives exist (tight vs inclusive), mention tradeoff in one sentence.
   - After confirmation, stick to that scope for traceability; if mid-work you discover the scope was wrong, say why and ask to extend or shrink it.

## After analysis → edit or ask

- If the analysis leaves **no material ambiguities** (intent of commits is clear, spec ownership is clear), **apply edits directly** to the spec `.md` files in the same turn.
- If something is **ambiguous** (e.g. experiment vs shipped feature, unclear product intent, conflicting specs), **ask the user** the minimal clarifying questions first, then apply edits once answered.

## Find specification files

In the repo root (recursive), locate existing specs using **case-insensitive** basename match where the filesystem allows:

| Pattern (intent) | Match examples |
|------------------|----------------|
| `*TZ*.md` | `TZ.md`, `01-TZ-api.md`, `technical-TZ-v2.md` |
| Overview | `OVERVIEW.md` |
| PRD | `PRD.md` |
| Tech spec | `TECHSPEC.md` |

Implementation hint: use workspace search/glob; on case-sensitive OSes, check both `TECHSPEC.md` and `TechSpec.md` if needed.

**If none match:** list a short sample of markdown files under `docs/`, `spec/`, or repo root, then **ask the user** which files are authoritative before editing anything.

## Gather evidence from git

Run commands appropriate to the **agreed scope**:

- `git log` with the chosen limit or revision range
- For commits that look relevant: `git show --stat <sha>` and, when needed, `git show <sha> -- <paths>`
- If the user cares about **uncommitted** work: `git status` and `git diff` / `git diff --cached`

Build a concise picture:

- **Which areas changed** (dirs, modules, APIs, config, migrations).
- **User-visible or contract-level behavior** (not every refactor).

If the repo has been rotated (**sdlc-backlog-rotate**), closed tasks live in `backlog/archive/BACKLOG-*.md` (index: `backlog/archive/INDEX.md`). When reconciling specs with delivered history, you **may** read those archive files — they hold the `- [x]` task blocks (context + DOD) that the active `BACKLOG.md` no longer shows. Treat the archive as read-only history; still verify each claim against current code (next section), and remember the active `BACKLOG.md` remains the only scheduling source.

## Verify every commit against the current code

Commit diffs and messages can be **misleading or stale**: a later commit may **revert, replace, or refactor away** what an earlier one introduced. Treat history as a **checklist to visit**, not as cumulative truth.

- Walk commits in the agreed scope (typically **oldest → newest** so you see evolution), but after each **material** commit, **re-read the affected files (and call sites / config consumers if needed) as they exist now** at `HEAD` (plus unstaged/staged changes if the user asked to include them).
- **Do not** document behavior that appears only in an old patch but is **gone or different** in the current tree; prefer what **actually runs** today.
- If two commits “fight” over the same behavior, **the newer state in the codebase wins**; mention both in light-touch traceability only if it helps the reader (e.g. “поведение зафиксировано после …”).

## Read the code selectively

- Start from **paths touched** in those commits, always ending on **current file contents**.
- Open **entry points** (HTTP handlers, CLI commands, main flows) and **types/schemas** when behavior is unclear.
- Do **not** paste huge files into the chat; cite only what matters for the spec delta.

## Compare to each spec file

For each discovered spec:

1. Skim **headings** and existing requirements (numbered lists, SHALL/MUST, acceptance criteria).
2. Mark:
   - **Gaps**: behavior present in **current** code (after per-commit verification above) **not** reflected in the spec.
   - **Drift**: spec claims something that code no longer does. **Rewrite in place** so the clause matches reality (remove, soften, or rephrase requirements); use strikethrough or a “не реализуется / deprecated” phrasing only if it matches the document’s existing style. If product intent is unclear (remove vs temporary), ask one focused question before rewriting narrative requirements.

## How to edit specs (native integration)

- **Place**: insert under the **most specific existing heading** that owns the behavior (feature, API, flow, NFR). If a heading is missing, add one at the **same level** as siblings in that part of the doc — not a dump at the end of the file.
- **Form**: extend existing numbered lists, acceptance criteria, tables, and scenarios; align verbs (SHALL/MUST/dolzhen) with the surrounding text.
- **Voice**: same tense and terminology as the rest of the ТЗ; no meta phrases like “добавлено при синхронизации с git”.
- **Traceability (light touch)**: prefer one unobtrusive line where it fits, e.g. at the end of the edited subsection — parenthetical source, footnote-style `[^1]`, or a single “Источник: коммиты …” line. Do not prefix every bullet with SHAs.
- **Drift**: edit the original sentences so they are true now; do not leave wrong MUSTs standing beside a disclaimer appendix.

## Output to the user

Always end with:

1. **Which spec files** were updated (after applying edits, or stating that none were changed because questions are pending).
2. **Commit range** analyzed.
3. **Top gaps** addressed (short list).
4. **Residual risks**: unclear areas, conflicts left for the user.

## Scope control

- When proposing initial git scope, if the history is huge, **prefer a bounded range** and explain the cutoff; offer widening explicitly.
- Security-sensitive details (secrets, tokens): describe behavior **without** copying secret values into specs.
