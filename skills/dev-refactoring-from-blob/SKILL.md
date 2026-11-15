---
name: dev-refactoring-from-blob
description: Analyze a concatenated project snapshot and produce ranked, evidence-based refactoring zones with safe incremental plans. Use when running make-a-refactoring-from-blob workflows.
---

# Refactoring from blob

Produce a high-leverage refactoring report from a concatenated project snapshot.

## Inputs to read first

1. Snapshot text produced from project files (for example via `./blob`).
2. `reference.md` as the detailed analysis protocol.

## Steps

1. Parse snapshot boundaries and identify modules and hotspots.
2. Extract explicit rules/constraints from included docs.
3. Build evidence-based smell map across files.
4. Produce a ranked Top-10 refactoring-zones report with safe incremental plans and tests.
5. Include coverage/self-audit and evidence gaps.

## Output

- Refactoring report aligned to the protocol in `reference.md`.

