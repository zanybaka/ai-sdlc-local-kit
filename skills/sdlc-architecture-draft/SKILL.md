---
name: sdlc-architecture-draft
description: Produce a concise architecture-committee-ready solution draft from PRD and TECHSPEC, including trade-offs, risks, and explicit decision requests. Use when preparing architecture review materials.
---

# Solution architecture draft

Create a concise architecture draft for committee review.

## Inputs to read first

1. `docs/prd.md` (or `PRD.md`).
2. `docs/techspec.md` (or `TECHSPEC.md`).
3. Workspace-root **`AGENTS.md`**.

## Steps

1. Summarize the proposed solution scope and constraints.
2. Present viable alternatives and explicit trade-offs.
3. List assumptions, risks, and mitigations.
4. Add open architecture questions and open information security questions.
5. End with a `Decision request` section and required approvals.

## Depth handoff

Substantive system design (API shape, data stores, queues, service boundaries) → the `engineering:system-design` / `engineering:architecture` plugin skills; this skill owns the committee artifact format (`docs/architecture-draft.md`, decision request).
Infra topology, image strategy, and IaC decisions → `engineering:system-design` for analysis + `adr-skill` for the record.

## Output

- Create or update `docs/architecture-draft.md`.
- Keep content concise and review-oriented.
