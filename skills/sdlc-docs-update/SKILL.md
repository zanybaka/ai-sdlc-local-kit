---
name: sdlc-docs-update
description: Update project docs after task delivery, including changelog, the Progress line, an on-demand task report, and ADR artifacts when required. Use at the end of implementation.
---

# Project documentation updater

Keep project artifacts synchronized with delivered work.

## Steps

1. Update `CHANGELOG.md` with the user-visible change.
2. Check the `Progress:` line under the task title: the date, DONE, what was delivered and how it was verified. It is required at close. Write or update `tasks/[TASK-ID].md` only when there is something to keep beyond the Progress line, `CHANGELOG.md` and the commit: measurements, a live probe log, the reason for a decision.
3. Apply ADR policy from workspace-root **`AGENTS.md`**:
   - promote `ADR-CANDIDATE` decisions to ADRs when implementation realizes them;
   - otherwise record `ADR not required` with a short reason.
4. Ensure docs reflect final behavior, not planned behavior.

## Guardrails

- Keep entries concise and factual.
- Do not edit unrelated documentation.
