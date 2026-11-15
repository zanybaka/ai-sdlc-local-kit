---
name: commit-current-changes
description: Create one local commit from current staged and unstaged changes using repository commit style and safe git workflow. Use only when the user explicitly invokes this command (commit-current-changes, /commit-current-changes) or asks for the auto-commit flow by name — not for every "commit" phrasing.
---

# Commit current changes

Create one safe local commit for current repository changes.

## Steps

1. Run in parallel:
   - `git status --short`
   - `git diff --staged`
   - `git diff`
   - `git log --oneline -5`
2. If there are no staged or unstaged changes, stop and report that no commit is needed.
3. Analyze staged + unstaged diffs and draft a concise commit message that matches recent history style.
4. Stage explicit paths belonging to the described change with `git add <path>...` — never `git add -A`.
5. If `git status --short` shows untracked files, list them and ask the user before including any of them in the commit.
6. Create one commit with the selected message.
7. Run `git status --short` and report what was committed and what remains.

## Constraints

- Do not run `git push`.
- Do not use destructive git commands (`reset --hard`, `checkout --`, `clean -fd`).
- If commit fails because of hooks, show the error and suggest the next step.
