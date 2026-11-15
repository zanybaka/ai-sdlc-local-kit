---
name: ai-task-retro
description: Interactive decision retrospective after a large ai-task batch — review teamlead judgment, improve ai-sdlc-local-kit skills and ai-task CLI, add backlog tasks. Use for ревью decisionов, retro decisions, ретро тимлида, decision analytics review, improve teamlead/product skills after delivery, lessons from decisions.jsonl. After an owner's intent, counts every owner intervention as a system defect and files the mechanism that would have caught it. Not for delivery run/plan (ai-task-teamlead) or PRD authoring (ai-task-product). Trigger via cursor-commands/ai-task-retro.md.
---

# AI Task Retro

You run an **interactive retrospective** on **teamlead judgment** after a large delivery batch. The user answers blocking questions; you end with improvement tasks (default: **ai-sdlc-local-kit** `BACKLOG.md`), retro reports in the **target repo**, and concrete skill/cli recommendations.

## Purpose (what this retro is for)

The decision journal captures **how the teamlead thinks**, not only what ran:

| Capture | Improves |
|---------|----------|
| Problems, options, choice, self-grade (`good`/`bad` + reflection) | **ai-task-teamlead** skill |
| `delivery_feedback`, DoR gaps | **ai-task-product** skill |
| Override patterns, anomaly handling | **ai-task** CLI (`parallel-plan`, verify, policy) |

**Judgment** is primary. Run telemetry and coverage metrics are **anchors**, not a substitute for rich `reason` / `reflection`.

## Two repos

| Repo | You read | You write |
|------|----------|-----------|
| **Target** (delivery project) | `.ai-task/decisions.jsonl`, `state.json`, factual reports | `decisions-YYYY-MM-retro.md/html`, `decision log --phase cross --choice retro_complete` |
| **ai-sdlc-local-kit** (profile) | `BACKLOG.md`, skills | Improvement tasks under `## Retro improvements (YYYY-MM)`; one-line append to `docs/retro-lessons.md`; skill edits only when user confirms or task explicitly says so |

If the user works from ai-sdlc-local-kit chat but retro targets another repo, use `--repo` or `cd` to that path for CLI and report paths. Improvement tasks still land in **ai-sdlc-local-kit** unless the user asks for target-repo backlog only.

**Privacy:** when a retro/TCO/value-scorecard artifact reads another repo's `.ai-task` data into a **tracked** ai-sdlc-local-kit file (`BACKLOG.md`, `docs/*`, `tasks/*`), use **anonymized project ids** (`Project A/B/C`), never real repo names, infra hostnames, or home/user paths. Keep the numbers/methodology; anonymize the identity.

## Bootstrap (run before interview)

From **target repo root**:

```bash
python /path/to/ai-sdlc-local-kit/scripts/ai-task.py retro --since 30d
# full batch (common after monolithic run):
python /path/to/ai-sdlc-local-kit/scripts/ai-task.py retro
```

Then read:

1. `.ai-task/packets/retro-YYYY-MM.md` (analytics JSON snapshot)
2. `.ai-task/reports/decisions-YYYY-MM.md` (factual, read-only)
3. `.ai-task/decisions.jsonl` (full entries, not only aggregates)
4. `.ai-task/state.json` — cross-check: implicit retries, failed runs, runs without verdict, phases missing from journal

If the packet is missing, run `ai-task retro` first.

### Journal credibility check (before Q&A)

The factual report (`decisions-YYYY-MM.md` / `.html`) includes a **Journal credibility** subsection when analytics trigger any of:

- All `good`, zero `bad`, and decisions &lt; runs/10 (sparse journal)
- `implicit_rework_detected` in `report.warnings`
- &gt;80% of decisions share the same `reflected_at` minute (bulk reflection)

`ai-task retro` prints a short credibility note when the same flags apply. Also watch manually:

- Empty `run_ids` on most entries — the fix is the **ai-task-teamlead** Run-id linkage rule: plan/parallel rows backfilled with `--run-ids` at the W5 wave gate, delivery/verdict rows logged with `--run-ids`. Cite it as the corrective action, not only the symptom.
- Identical `reflection` text across entries
- Only `phase=parallel` for a multi-phase batch
- **`bad` only ever owner-sourced** — the teamlead never self-graded `bad`. Then `bad`-count measures *owner disagreement*, not call quality; an all-`good` self-graded journal is a smell to challenge, not a pass.

**Selection-bias guard (metric honesty):** if the batch was *selected* by a criterion — e.g. a "sibling hunt", a single subsystem, a re-run of failures — do **not** report the in-batch rate (e.g. "recurrence 88%") as a population health signal; it is near-tautological (you searched for X, you found X). Measure over the full population (all delivered tasks / all bugs), and say so in the report.

**Recurrence vs rework:** `good/bad` and `rework_rate` measure *judgment and delivery*, not whether fixes **generalize**. A batch where most tasks are siblings/regressions of already-fixed bugs (high recurrence) while `rework_rate`≈0 is the classic blind spot — flag it explicitly and push the Sibling-DoD (below) rather than celebrating the low rework rate.

Do not treat credibility flags as delivery failure; they mean **judgment log was thin**.

## Blocking interview (required)

- **One question per message.** Do not ask two questions in one turn.
- **Do not** add backlog tasks or write retro files until scope is clear.
- Stop when you know: **period**, **main pain or “smooth”**, **improvement target** (skills / cli / product / combo), **backfill vs forward-only**.

### First question when credibility flags fired

When the factual report has **Journal credibility** (or the checklist above matches), ask this **first** and wait for an answer before period, pain, focus, or improvement tasks:

> Given sparse or bulk-reflected decisions and/or implicit retries in `state.json`, do you trust this journal coverage for retro conclusions, or should we prioritize logging-discipline tasks before judgment improvements?

### Suggested questions (pick unknowns)

1. **Period** — entire batch or `--since` window?
2. **Pain** — parallel, verify, review/rework, backend limits, or mostly smooth?
3. **Focus** — teamlead judgment, product/DoR, ai-task CLI/policy, or combo?
4. **Backfill** — forward-only in ai-sdlc-local-kit (default), backfill target `decisions.jsonl`, or both?

### Optional ingest (when journal is thin)

If the user wants a **gap list from run telemetry** without hand-writing stubs, offer (do not run silently):

```bash
python /path/to/ai-sdlc-local-kit/scripts/ai-task.py decision ingest --since 30d --dry-run
```

Dry-run prints proposed judgment stubs from `state.json` (retries, verify fail, verdict rework/split/escalate) with `source_run_id`. Append only after operator review:

```bash
python /path/to/ai-sdlc-local-kit/scripts/ai-task.py decision ingest --since 30d --apply --confirm
```

`--apply` without `--confirm` exits with error (never silent backfill). Prefer manual `decision log` for rich judgment; ingest rows set `signals.ingest = true`.

## Analysis (during retro, not optional)

Compare **journal narrative** vs **state.json facts**:

| Look for | Skill/cli signal |
|----------|------------------|
| Override of `parallel-plan` | Tune heuristics or teamlead override playbook |
| Verify profile manual fix | Policy template + teamlead `--phase verify` examples |
| Retry after `needs_review` without `delivery` decision | Teamlead W5 gap |
| `delivery_feedback` missing but backlog/DoD mismatch obvious | Product skill gap |
| Empty reasons / copy-paste reflections | Teamlead **Judgment template** (`reference-journal.md`) not followed |
| Empty `run_ids` across most entries (journal not auto-correlatable to runs) | Teamlead **Run-id linkage** rule |
| Most delivered tasks are siblings/regressions of fixed bugs; `rework_rate`≈0 but recurrence high | Teamlead **Sibling-DoD** (sibling must add a class-guard, not a point-fix); product class-guard DoD; track a `sibling_rate` metric |
| Only owner-sourced `bad`; all self-grades `good` | Honest-grading rule in teamlead (grade `bad` when overruled or when a fix leaves the class open) |

Extract **2–5 concrete rules** for teamlead or product (“when X, log Y with Z”), not generic advice.

### Owner interventions are defects

When the batch delivered an owner's intent ("Намерение: ...", an epic carried in rounds), every time the owner had to step in is a defect of the system (canon `AGENTS.md`, section "Delivering an intent"). List them before you extract rules: `user_escalation` rows and owner-sourced `bad` grades in `decisions.jsonl`, verdicts the owner overrode, and what the owner tells you in the interview. Put one question for that into the interview when the journal does not show them: "Где вам пришлось вмешаться в этот прогон?"

Sort each intervention into its kind and the mechanism that would have caught it first:

| Owner intervention | Mechanism that missed it |
|--------------------|--------------------------|
| Bare approval of a choice the system could make | Product or teamlead asked outside taste, money, access, public or irreversible steps |
| "Почему остановился", "сделай сам" | Teamlead waited on a task-level decision |
| Status question, "завис?" | Teamlead did not raise a stall or a slow wave first |
| Quality complaint (placeholder art, bad sound, a level won with one cheap move) | Acceptance against the intent as a user was skipped or too shallow |
| "Не понял" | Report not short or not in the owner's language |
| "Можно закрыть чат?" | Report did not end with the Итог: Я / Вам block |

Each kind that occurred becomes one improvement task (for a skill rule or a CLI check) that names the mechanism, not a reminder to try harder. An answer the owner gave to a legitimate batched question (taste, money, access, a public or irreversible step) is the system working and is not counted.

## Third-party handoffs (optional)

| Signal | Load skill |
|--------|------------|
| Spike in `bad`, rework, escalate, or user describes incident | **lessons-learned** |
| Routine tuning, smooth batch | **kaizen** |
| Session friction (not decisions.jsonl) | Mention **agent-retro** (`docs/ai-task-decisions.md`) |

## Deliverables (in order)

1. **Backlog tasks (ai-sdlc-local-kit)** — **sdlc-backlog-add** or edit `BACKLOG.md`. Phase: `## Retro improvements (YYYY-MM)`. Each task: judgment quality, auto-hooks for anomalies, skill template, or product loop. Priority P2 unless urgent.
   **Evidence apart from the rule.** When the fix is a change to a shared skill or the canon, the task text has two parts: "Улики" (evidence: the case with its numbers, file names, repositories, hosts) and "Правило" (the rule: the general wording without them, with placeholders where a form is needed). The DoD refers only to the rule. Values of a foreign layer (design-system sizes and thresholds, screen sizes, paths to an application's files) never move from the evidence into the skill: the skill sends the reader to their owner (the task, the vendored kit, the repository's `AGENTS.override.md`). See `docs/skill-authoring.md`, "What does not go into a skill".
2. **Retro reports (target repo)** — both:
   - `.ai-task/reports/decisions-YYYY-MM-retro.md`
   - `.ai-task/reports/decisions-YYYY-MM-retro.html`
3. **Summary** — new task ids, links to factual + retro reports (repo-relative markdown links), 1–3 skill/cli bullets.
4. **Target repo** — `decision log --phase cross --choice retro_complete --reason "..."`.
5. **Cross-repo lessons index (ai-sdlc-local-kit, mandatory)** — append **one line** to ai-sdlc-local-kit `docs/retro-lessons.md`, creating the file on first use (date, target repo, top lesson, filed task ids). Repo-local journals and reports are gitignored; this tracked index is the only place lessons aggregate across repos.
6. **Standing audit questions (ai-sdlc-local-kit, closing step)** — offer the owner 2–3 unexplored (`open`) questions from ai-sdlc-local-kit `docs/audit-questions.md` (skip this step while the profile clone has no such catalog); update statuses there for anything newly asked or filed during this retro (`open` → `filed TASK-ID` / `done TASK-ID`).
7. **Project memory drop (optional)** — if the host project has Claude Code auto-memory (a `MEMORY.md` for the project), record the top lesson there so future sessions in that repo start with it. Skip silently when no auto-memory exists.

Default: **forward-only** (no editing target `decisions.jsonl` history) unless user chose backfill.

## Retro report template

```markdown
# ai-task retro (YYYY-MM)

## Executive summary
(3–5 sentences: delivery outcome, journal quality, main learning; if credibility flags fired, state the coverage gap in the opening sentence)

## Journal credibility
(flags observed, judgment vs telemetry gap)

## Q&A log
| # | Question | Answer |
|---|----------|--------|
| 1 | … | … |

## Owner interventions
(intent batches only: each intervention, its kind, the mechanism filed)

## Teamlead judgment highlights
(overrides, anomalies, good/bad patterns — cite decision ids)

## Improvement tasks (ai-sdlc-local-kit)
- <task id> — …

## Policy / skill recommendations
(concrete before/after rules for teamlead, product, maintainer)
```

## Rules

- Do not run `ai-task run` for delivery during retro.
- Factual `decisions-YYYY-MM.md` / `.html` are **read-only** (CLI-generated).
- Improvement tasks default to **ai-sdlc-local-kit**, not the target app repo.
- Prefer **few meaningful judgment improvements** over many telemetry-only tasks.

## Triggers

ревью decisionов, retro decisions, ретро тимлида, decision review, improve teamlead after batch, journal quality, lessons learned, improvement tasks for ai-task, что улучшить после прогона
