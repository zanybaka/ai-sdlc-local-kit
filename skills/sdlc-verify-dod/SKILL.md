---
name: sdlc-verify-dod
description: Run relevant checks and verify Definition of Done before handoff. Use after implementation and before final delivery.
---

# Verification and DoD

Confirm the change is valid before handoff.

## Steps

1. Run relevant checks for changed behavior (tests/lint/build as applicable).
2. Confirm task DoD items are satisfied.
3. Confirm assumptions and unresolved risks are explicitly listed.
4. **Rebuild-completeness check.** When the change touches a shared contract (a new label, an n8n node, an endpoint, an env var, a wire format), confirm the matching cross-cutting rebuild doc is updated in the same change, or explicitly note it as not-applicable. This widens the doc-in-same-PR policy from "docs" to "rebuild docs": a from-scratch rebuild must not silently drift because an onboarding label set, rebuild runbook, or operator checklist was left behind. The contract classes and their rebuild docs are listed in `docs/ai-task-backlog-contract.md` (Shared-contract rebuild invariants).
5. Record pass/fail outcomes in the handoff summary.

## Guardrails

- Prefer targeted checks when full suite is unnecessary.
- Follow verification policy in workspace-root **`AGENTS.md`**.
