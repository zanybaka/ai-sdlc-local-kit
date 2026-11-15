---
name: sdlc-techspec-interview
description: Runs a one-question-at-a-time technical interview to turn PRD into an implementation-ready TECHSPEC with traceability, constraints, risks, and ADR-candidate decisions. Use when authoring or refining technical specifications.
---

# TECHSPEC Interview

## Goal

Convert PRD intent into an implementation-ready TECHSPEC with explicit technical decisions and trade-offs.

## Workflow

1. Read PRD, existing architecture context, constraints, and project rules before asking questions.
2. Run a strict one-question-at-a-time technical interview.
3. Preserve traceability from requirements to technical decisions.
4. Document architecture, contracts, verification strategy, and rollout constraints.
5. Mark architecture-level decisions as ADR candidates.
6. Generate or update the TECHSPEC artifact.

## Interview Focus Order

1. Architecture shape and module boundaries.
2. Contracts/schemas/interfaces and compatibility strategy.
3. Data model and migration constraints.
4. Performance, reliability, and security constraints.
5. Packaging, deployment target, and operational constraints.
   - Container image vs bare process — what the deliverable artifact is and how it is built.
   - Orchestration target: Kubernetes, single host, serverless, or developer machine only.
   - Capacity and scale expectations: request/load volume, data growth, and headroom assumptions.
   - Operational ownership: who deploys it, who monitors it, and who responds when it breaks.
6. Verification strategy and operational rollout concerns.

Routing: deep design sessions → `engineering:system-design` (plugin).
Record the container/orchestration choice as an `ADR-CANDIDATE` (runtime-topology trigger below).

## Depth handoff

Substantive system design depth (API shape, data stores, queues, service boundaries) → the `engineering:system-design` / `engineering:architecture` plugin skills; this skill keeps the artifact format (`docs/techspec.md`, traceability, `ADR-CANDIDATE` entries).
Infra topology, image strategy, and IaC decisions → `engineering:system-design` for analysis + `adr-skill` for the record.

## ADR-Candidate Rule

Add `ADR-CANDIDATE: <decision>` for long-lived technical choices, including:

- Material architecture path selections (for example WebView vs native).
- Platform/framework dependency choices with future lock-in risk.
- Contract/protocol/schema choices with migration or compatibility impact.
- Runtime topology, trust boundary, data boundary, or security-model choices.

For each ADR candidate, include context, alternatives considered, and why the chosen direction wins.

## Output Requirements

Create or update `docs/techspec.md` (or `TECHSPEC.md` if that is the project convention) with:

- Requirement-to-decision traceability.
- Proposed architecture and component responsibilities.
- Contract and compatibility notes.
- Verification and rollout strategy.
- Assumptions, risks, and unresolved open questions.
- `ADR-CANDIDATE` entries when applicable.

## Quality Gate Before Handoff

- Spec is actionable for task decomposition and implementation.
- Key trade-offs are explicit and justified.
- Contract and migration impacts are documented.
- ADR-candidate decisions are recorded when triggered.
