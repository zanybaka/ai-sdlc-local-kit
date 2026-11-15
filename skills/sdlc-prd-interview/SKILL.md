---
name: sdlc-prd-interview
description: Conducts a one-question-at-a-time product discovery interview and produces a complete PRD draft with assumptions, risks, and ADR-candidate decisions. Use when creating or refining PRD artifacts from user ideas.
---

# PRD Interview

## Goal

Produce a decision-ready PRD from a user idea, with clear scope, constraints, and risks, based on project constraints.

## Policy inputs (before discovery)

- Read workspace-root **`AGENTS.md`**.
- When you also read **`PRD.md`** / **`TECHSPEC.md`**, honor precedence already declared in those files.

## Workflow

1. Run discovery in a strict one-question-at-a-time loop.
2. Challenge vague statements and confirm measurable outcomes.
3. Capture assumptions and unresolved questions explicitly.
4. Mark long-term technical-impact choices as ADR candidates.
5. Generate or update the PRD artifact based on project constraints.

## Interview Rules

- Ask exactly one focused question per turn.
- Prefer concrete prompts over broad brainstorming prompts.
- If an answer is ambiguous, ask a clarifying follow-up before moving on.
- Keep momentum: move from problem -> users -> scope -> constraints -> success metrics.

## Express mode (small features)

For a small feature, cap the interview at ~5 questions instead of running the full track:

- Applies when the change is S/M-sized, adds no new user group or platform, and changes no external contract. When in doubt, ask the user "full interview or express?" as the first question.
- The ~5 questions cover only: problem, affected users, scope boundary, one success signal, and (if relevant) the riskiest constraint.
- Everything else is filled with explicit assumptions, clearly marked as assumptions in the PRD, for the user to correct in review — do not ask more questions to close gaps.

## Interview depth by product type

Identify the product type early (it is usually obvious from the idea; otherwise ask). Beyond the common track (problem -> users -> scope -> constraints -> metrics), probe the matching question areas:

| Product type | Question areas (2-3 each) |
|--------------|---------------------------|
| Web / UI | Funnel: where do users enter and drop off? Which steps/events must be instrumented? Which user segments matter (new vs returning, role, device)? |
| Service / API | Who are the consumers and what do they call today? What SLO/latency/error budget is expected? What happens to consumers on breaking change? |
| CLI / tooling | In which contexts is it invoked (interactive, CI, scripts)? What does failure look like to the user (exit codes, messages, partial state)? How is it installed/updated? |
| Desktop | Which platforms/OS versions are in scope? How does the app update (store, auto-update, manual)? What offline/local-data expectations exist? |

For mixed products (e.g. a service with a web console), take the rows for each surface; in express mode, take only the single most load-bearing area from the matching row.

## Good-metric bar

Every success metric must pass three checks before it enters the PRD:

- **Measurable with available data** — an existing data source or a named event to instrument; "users are happier" fails, "activation event X per week from analytics table Y" passes.
- **Leading where possible** — prefer a signal that moves within weeks of shipping over a lagging quarterly outcome.
- **Owner named** — one person/role who will look at the number at the check-back date.

## ADR-Candidate Rule

Add `ADR-CANDIDATE: <decision>` when product direction implies long-term technical consequences, including:

- Platform path decisions (for example native app vs WebView).
- Integration or data-boundary model decisions.
- Security or compliance posture decisions affecting architecture.
- Other choices likely to constrain future implementation paths.

For each ADR candidate, include short rationale and alternatives considered.

## Output Requirements

Create or update `docs/prd.md` (or `PRD.md` if that is the project convention) with:

- Problem statement and target users.
- Goals, non-goals, and scope boundaries.
- Functional requirements and success metrics.
- Constraints, assumptions, risks, and open questions.
- **Measurement plan** — for each success metric: its data source or the event to instrument, and a check-back date. Missing instrumentation becomes ordinary backlog tasks via the decomposer; the check-back review is routed through the product skill (metrics-review).
- `ADR-CANDIDATE` entries when applicable.

## Quality Gate Before Handoff

- PRD is specific enough to be decomposed into backlog tasks.
- Scope and acceptance intent are testable.
- Every success metric passes the good-metric bar and has a measurement-plan entry (data source/event, check-back date).
- Assumptions/risks are explicit, not implied.
- ADR-candidate decisions are recorded when triggered.
