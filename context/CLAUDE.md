# CLAUDE.md

Global context for Claude Code.

## Policy source

- In each **repository you work in**, follow workspace-root **`AGENTS.md`** for workflow, constraints, verification, and ADR rules.
- If instructions conflict, follow precedence declared in that `AGENTS.md`.

## Skill routing (Claude Code)

Use skill routing and workflows declared in workspace-root **`AGENTS.md`**.
Select concrete skills from `~/.claude/skills/*/SKILL.md` by user intent, preferring specialized skills over generic execution.
Use `.ai-task` orchestration only when the current repo has opted in or the user explicitly asks to initialize it.

## Process hygiene

Orphaned busy-loop processes were repeatedly found on this machine (e.g. `python -`
pinned at 100% CPU for days). Rules to not create them:

- **Never run `python -`/`python3 -` via heredoc** (`python3 - <<EOF`). stdin scripts
  are anonymous (`sh-thd-*` temp file, deleted on start) — unidentifiable and unkillable
  by name later. Use `python3 -c '...'` for snippets or write a real `.py` file and run it.
- **Bound every one-off script's runtime**: finite loops or a deadline inside the code,
  or `timeout N <cmd>` (GNU coreutils `gtimeout` on macOS) around the command.
- **You own what you spawn**: when a command is auto-backgrounded by timeout or run in
  background, and its result is no longer needed — kill it (`kill <pid>` / kill_shell)
  instead of abandoning. A forgotten child outlives the shell and reparents to launchd.
- When diagnosing a hung process: `lsof -p <pid> -d cwd` + `sample <pid> 2` before killing.

## Writing style

Follow the **Writing style** section of the workspace `AGENTS.md`. That is the single source for these rules (shared copy: `context/AGENTS.md` in the ai-sdlc-local-kit repo). Cursor and Claude Code read `AGENTS.md` directly; Codex reads `AGENTS.override.md` instead when a repository has one, and its first line sends the agent to `AGENTS.md`.
