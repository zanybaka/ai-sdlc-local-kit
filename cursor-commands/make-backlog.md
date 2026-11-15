# Backlog Command Router

Use skill: "sdlc-backlog-decompose".

## Task
- Execute the skill end-to-end for the current PRD/TECHSPEC scope.
- Follow project rules from "AGENTS.md".

## Input
- "docs/prd.md" (or "PRD.md").
- "docs/techspec.md" (or "TECHSPEC.md").
- "AGENTS.md" project rules and priorities.

## Output
- Create or update the backlog store with phased, implementation-ready tasks in dependency-safe execution order: one `backlog/tasks/<TASK-ID>.md` per task plus a regenerated `BACKLOG.md` index in a file-per-task repo, or inline "BACKLOG.md" where not migrated (see the skill's store-layout note).
- Use BACKLOG checkbox meanings from "AGENTS.md" (`- [ ]` open, `- [~]` skipped/deferred, `- [x]` done).