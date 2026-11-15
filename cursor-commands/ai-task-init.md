# Initialize AI Task Command Router

Use skill: "ai-task-init".

Additional skill loaded when relevant:
- "ai-task-maintainer"

## Task
- Initialize optional `.ai-task` infrastructure in the current repository.
- Follow root "AGENTS.md" and preserve existing project conventions.
- Do not require `.ai-task` for repositories that only want ordinary "BACKLOG.md", "AGENTS.md", shared skills, and Cursor or Claude workflows.

## Output
- Created or reused `.ai-task` files and directories.
- Default backend policy summary.
- Point the user to `/ai-task-teamlead` for planning, runs, and status.
