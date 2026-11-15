# Backlog Rotate Command Router

Use skill: **sdlc-backlog-rotate**.

Additional skills when relevant:
- **sdlc-backlog-add** / **sdlc-backlog-decompose** (read `backlog/id-registry.toml` before allocating new ids)
- **commit-current-changes** (when the user asks to commit the rotation)

## Task

Rotate the workspace backlog: move **only closed** (`- [x]`) tasks into the archive, keep **open** (`- [ ]`) and **deferred** (`- [~]`) verbatim, refresh `backlog/id-registry.toml`. In a file-per-task repo (`backlog/tasks/*.md` populated) that is a file move owned by the store tool: `python scripts/backlog-store.py rotate --dry-run`, confirm, then `rotate` (moves `- [x]` files to `backlog/archive/tasks/`, regenerates the `BACKLOG.md` index, refreshes the registry). Only a non-migrated repo uses the legacy text-surgery flow into `backlog/archive/BACKLOG-NNN.md` plus `INDEX.md`. Follow the invariants and workflows in `skills/sdlc-backlog-rotate/SKILL.md`.

**Always** show the pre-flight counts (N closed → archive, M open / K deferred staying) and **wait for confirmation** before writing. Never auto-rotate. Never renumber existing ids. Never move `- [~]` to the archive.

## Typical requests (say any of these)

| User says | You do |
|-----------|--------|
| «разбить backlog», «backlog слишком большой» | Full **sdlc-backlog-rotate** flow with pre-flight confirmation |
| «архивировать закрытые», «archive closed tasks» | Same |
| «backlog rotate» | Same |

For PRD re-decompose use **sdlc-backlog-decompose**; for adding one task use **sdlc-backlog-add**; for documenting shipped work use **sdlc-backlog-retroactive** — not this command.

## Output

- File-per-task repo: closed task files moved to `backlog/archive/tasks/`, regenerated `BACKLOG.md` index, refreshed `backlog/id-registry.toml`.
- Legacy repo: `backlog/archive/BACKLOG-NNN.md` with the dated `## Archived from active YYYY-MM-DD (BACKLOG-NNN)` section, slimmed `BACKLOG.md` (open + deferred only) with updated header, refreshed registry, `backlog/archive/INDEX.md` row.
- Chat summary: archive path + N moved, M open / K deferred remaining, next-free ids.

## Examples

- «Backlog слишком большой, разбей его»
- «Архивируй закрытые задачи и обнови реестр id»
- «Rotate the backlog, keep deferred active»
