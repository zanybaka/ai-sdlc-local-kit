---
name: dev-create-blob-script
description: Build a local ./blob CLI that concatenates project code and key docs into one dehydrated text snapshot with size stats and clipboard copy. Use when the user asks to create/update the blob script for LLM analysis input.
---

# Create blob script

Build a local `./blob` CLI tool that emits a single dehydrated project snapshot suitable for LLM analysis.

## Inputs to read first

1. Repository file layout and dominant languages.
2. Existing docs and decision records (`ADR`, `TECHSPEC`, `PRD`, `CHANGELOG`, `AGENTS.md`, related docs).
3. Workspace-root **`AGENTS.md`**.

## Required behavior

1. Create a CLI named `./blob`.
2. Concatenate:
   - Project source code files.
   - Project documentation and governance artifacts (including ADRs, `TECHSPEC`, `PRD`, `CHANGELOG`, `AGENTS.md`, and similar project docs).
3. Apply output dehydration:
   - Remove comments where safe for supported file types.
   - Remove empty lines and repeated whitespace noise.
   - Keep content deterministic and readable for downstream analysis.
4. Print statistics to stdout:
   - Total output size.
   - Size breakdown by file type.
5. Copy final blob text to clipboard.

## Implementation constraints

- Keep file selection explicit and predictable; skip generated/vendor/build artifacts by default.
- Keep execution local and offline; no external uploads.
- Preserve stable ordering so repeated runs produce comparable output.
- Fail with clear messages when clipboard support or file parsing is unavailable.

## Output

- A working `./blob` CLI in the repository.
- Verified run output showing total size and per-type breakdown.
- Final concatenated dehydrated text copied to clipboard.
