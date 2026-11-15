# Commit Command Router

Use skill: "commit-current-changes".

## Task
- Execute the skill end-to-end for current repository changes.
- Follow project rules from "AGENTS.md".

## Input
- Current git working tree (staged + unstaged changes).
- Recent commit history for local message style.
- "AGENTS.md" project rules and priorities.

## Output
- A single local commit when there are changes.
- Or a clear "no commit needed" result when the working tree is clean.
- Short report of what was committed and what remains uncommitted.
