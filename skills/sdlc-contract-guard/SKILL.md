---
name: sdlc-contract-guard
description: Validate and control API/schema/protocol changes to avoid silent breakage. Use when contracts may change during task implementation.
---

# Contract change guard

Apply this only when public contracts might change.

## Steps

1. Identify the producer and all known consumers of the changed contract.
2. Check compatibility impact (breaking vs non-breaking).
3. If breaking, document migration/rollback notes before handoff.
4. Update related tests and docs in the same task.
5. Summarize compatibility risk explicitly.

## Compatibility rules by surface

Use during step 2 to classify the change.

| Surface | Non-breaking | Breaking — version, tolerate, or migrate |
| --- | --- | --- |
| REST/JSON API | Additive: new optional fields, new endpoints, widened enums consumers tolerate | Field removals/renames, type or semantics changes, new required inputs — version the API or make consumers tolerant first |
| DB schema | Expand → migrate → contract: add nullable column/table, dual-write, switch reads, drop later | Drop/rename column or table, narrow a type, add NOT NULL without default — never destructive in one step |
| Queue/event messages | Additive optional fields; consumers built as tolerant readers (ignore unknown fields) | New required field: deploy consumers before producers; removals/renames need a versioned schema and a drain window |
| CLI/config flags | New optional flag with a safe default; alias kept for renamed flags | Removing/renaming a flag or changing default behavior — deprecate first, keep the old name for one release |

- If any change lands in the breaking column, step 3 (migration/rollback notes) is mandatory.

## Migration safety

Check every row before shipping a DB migration.

| Concern | Rule |
| --- | --- |
| Reversibility | Ship a down-migration or a documented rollback path; verify it actually runs |
| Lock impact | Review ALTERs on hot tables; prefer online DDL; `CREATE INDEX CONCURRENTLY`, never a plain blocking index build |
| Backfill | Batch with throttling and resumability — never one UPDATE over the whole table |
| Deploy order | Schema must serve both old and new code during rollout; expand first, contract only after old code is gone |
| Destructive ops | Two-step rename: stop writes / soft-drop and observe in one release, physical drop in a later one |

## Guardrails

- Do not ship silent breaking changes.
- Follow contract policy in workspace-root **`AGENTS.md`**.
