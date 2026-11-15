---
name: ai-task-init
description: Initialize optional `.ai-task` infrastructure in a repository for the reusable ai-task orchestrator. Use when the user asks to set up, initialize, bootstrap, or enable `.ai-task` or the ai-task runner in the current project.
---

# Initialize AI Task

Use this skill only when the user explicitly wants `.ai-task` in the current repository. Do not add `.ai-task` just because a project has `AGENTS.md`, `BACKLOG.md`, Cursor commands, or Claude Code skills.

## Preconditions

Before creating files:

1. Confirm the current directory is the intended repository root.
2. Read root `AGENTS.md` and `BACKLOG.md` when present.
3. If `.ai-task/` already exists, inspect it and preserve user-managed files.
4. Ask before overwriting any non-generated file.

## Minimal Infrastructure

Create or update this opt-in layout:

```text
.ai-task/
  config.toml
  state.json
  inbox.jsonl
  policies/
    default.toml
  runs/
    .gitkeep
  packets/
    .gitkeep
  cleanup/
    .gitkeep
  decisions.jsonl
```

`decisions.jsonl` starts empty and **accumulates** teamlead choices (see `docs/ai-task-decisions.md`). It is not removed by `prune` or `cleanup`.

In this repo, use `scripts/ai-task.py init` or the `ai-task init` wrapper to create this layout.

## Own or foreign repository

`ai-task init` decides whose repository it is before it writes anything, and prints the answer as `Repository ownership: own` or `foreign`, with the reason.

- **Own.** The `origin` remote, written as `host/owner/repo`, matches a pattern in `own_remotes`. Init behaves as before: whether to track `.ai-task/config.toml` and `policies/` is the operator's choice, and a `.gitignore` block for the runtime files is fine.
- **Foreign.** Any other origin, no origin, or no `own_remotes` configured. Init writes `/.ai-task/` into `.git/info/exclude`, which is local to the checkout and never committed. In this mode do **not** append `.ai-task` lines to `.gitignore` and do **not** commit any `.ai-task` file: the repository belongs to someone else (an employer, a client), and the operator's tooling must not land in its history. If the repository already tracks `.ai-task` files or names `.ai-task` in `.gitignore`, init prints the exact `git rm -r --cached` command and the `.gitignore` lines to delete. It runs none of them; show them to the operator and let them decide.

`own_remotes` is operator data, so it lives in the profile checkout, not in the target repository: `ai-task-profile.local.toml` next to the tracked template `ai-task-profile.example.toml` (or the file named by `AI_TASK_PROFILE_CONFIG`). A pattern without a wildcard covers everything below it, so `github.com/your-name` means every repository of that owner. When init reports foreign because the owner is unknown (no origin, a local-path origin, or no `own_remotes`), ask the operator once whether the repository is theirs. If it is, re-run with `--ownership own` or add the owner to the file. An explicit `own` is recorded in the repo's `.ai-task/config.toml` and later runs keep it. `--ownership foreign` forces the cautious mode and drops a recorded `own`.

## Bootstrap delivery docs

`ai-task init` also copies a **minimal bootstrap doc bundle** into the target repo's gitignored **`.ai-task/docs/`** so the local references skills and `dor` hints rely on resolve. The manifest is `BOOTSTRAP_DOCS` in `scripts/ai-task.py` (source path in the profile → same relative path under `.ai-task/`); today it is:

- source `docs/ai-task-backlog-contract.md` → dest `.ai-task/docs/ai-task-backlog-contract.md` — backlog/DoR contract.
- source `docs/ai-task-verify.md` → dest `.ai-task/docs/ai-task-verify.md` — verify stack profiles.

Behavior: each file is copied from the ai-sdlc-local-kit profile checkout **only when the destination is missing**. Operator edits are never overwritten, init lists every copied path, and a second init is a no-op for files that already exist. `ai-task self-test` warns when an initialized repo is missing any bootstrap doc.

## Bootstrap helper scripts

`ai-task init` also **vendors profile-owned helper scripts** into the target repo's gitignored **`.ai-task/scripts/`**. The manifest is `BOOTSTRAP_SCRIPTS` in `scripts/ai_task/init.py` (source path in the profile → same relative path under `.ai-task/`); today it is:

- source `scripts/backlog-id-registry.py` → dest `.ai-task/scripts/backlog-id-registry.py` — per-prefix id floors read by **sdlc-backlog-rotate**, **sdlc-backlog-add**, and **sdlc-backlog-decompose**.
- source `scripts/ai-task-quota-statusline.py` → dest `.ai-task/scripts/ai-task-quota-statusline.py` — repo-local Claude Code `statusLine` helper that writes `.ai-task/quota-snapshot.json` for quota supervision.
- source `scripts/backlog-store.py` → dest `.ai-task/scripts/backlog-store.py` — the file-per-task backlog store CLI (`split` / `regenerate` / `check` / `rotate` / `guard`). It is a thin shim over the `ai_task` store modules, so init vendors the subset with it: `scripts/ai_task/_shared.py`, `scripts/ai_task/backlog.py`, `scripts/ai_task/backlog_store.py`, and `scripts/ai_task/index_guard.py` land under `.ai-task/scripts/ai_task/` (no facade `__init__.py`; the shim resolves the vendored copies itself). Consumer migration runbook: docs/ai-task.md, "Consumer adoption runbook".

**The one tracked artifact: `scripts/backlog-index-guard.py`.** In a repo that has migrated to the file-per-task store, init also generates this guard **into the tracked tree** and reports it as `created` / `updated` / `up to date`. It is the store's own `check`, bundled into a stdlib-only script, so the consumer's CI can run `python3 scripts/backlog-index-guard.py check` — CI checks out tracked files only, so a gitignored tool can never guard it. Tell the operator to **commit it** and wire that one line into CI. Init skips it for repos that have not migrated (nothing to guard) and for the ai-sdlc-local-kit profile itself (its test suite is the guard). A hand-edited copy, or one left behind by an init that refreshed the vendored modules, is caught by `python3 .ai-task/scripts/backlog-store.py guard --check` — that check compares against the modules in that repo and cannot see the profile, so re-running init is what closes the gap, and `guard --check` is what confirms it afterwards. The file is **lint-exempt by construction** (the header carries `# ruff: noqa`, `# flake8: noqa`, `# pylint: skip-file`, `# fmt: off`), so never tell an operator to add an `extend-exclude` for it — and remove one if a repo carries it from before. Never hand-write an index checker in a consuming repo either — that is a second source of truth for the layout.

Why a script (not just docs) must land in the repo: some skills invoke helpers from the *target repo's own vendored copy* (`python .ai-task/scripts/backlog-id-registry.py …`, no `--repo` flag), and the quota helper must live next to the repo-local `.ai-task/quota-snapshot.json` it writes. (In the ai-sdlc-local-kit profile itself — which has no `.ai-task/` — skills run tracked source helpers from `scripts/`.) A script is profile-owned tooling, not operator-editable content, so the copy rule differs from docs: init **creates it when missing and refreshes it to the profile version when the bytes differ** — reported as `(created)` / `(updated)`. That is what makes re-running init useful: a repo initialized before a tool existed (or before it was updated) picks it up on the next `ai-task init`. `ai-task self-test` warns when a bootstrap script is missing.

Quota setup remains explicit and non-invasive. Claude Code `statusLine` is a standard Claude Code setting; `.ai-task/quota-snapshot.json` is the ai-sdlc-local-kit contract. `ai-task init` vendors the repo-local helper and prints the next step, but it does not edit Claude Code settings. Use `ai-task quota setup-statusline --global` (recommended) to print the repo-agnostic dispatcher snippet for global settings, or `--project` for this repo only, then run `ai-task quota setup-statusline --check` from this repo after Claude Code renders once. For unattended headless delivery, `run` and `plan --bulk` also call `ai-task quota refresh` automatically when the snapshot is missing or stale; the operator does not need interactive statusLine rendering during the wave. By default refresh uses the existing Claude Code OAuth credential via built-in `claude_oauth`, then falls back to `ccquota --json` if installed.

**Re-running `init` is data-safe.** Everything under `.ai-task/` (`state.json`, `decisions.jsonl`, `inbox.jsonl`, `config.toml`, `policies/`) is left untouched unless `--force`; only bootstrap **docs** (when missing) and bootstrap **scripts** (when missing or stale) are topped up. So an old repo can re-run `ai-task init` purely to receive new scripts/docs without disturbing its run state.

**Bootstrap files are gitignored under `.ai-task/` — reproduced by init, not committed.** The vendored docs and scripts live under the target repo's `.ai-task/` tree, which is gitignored like the rest of that operator-local infrastructure. They are **operator tooling** — only the Claude Code delivery skills touch them (teammates and CI don't) — and they are fully reproducible by re-running `ai-task init`, so do **not** track them and a fresh clone or CI runner doesn't need them. A profile refresh just re-vendors on the next init.

**Data vs. tool.** The bootstrap files are *tools* (gitignored under `.ai-task/`); the **data they produce stays tracked**: `backlog-id-registry.py` reads/writes only `BACKLOG.md`, `backlog/archive/`, and `backlog/id-registry.toml` — all versioned and shared — so moving the tool under `.ai-task/` changes nothing about that data. Keep it crisp: **tools reproducible + gitignored; backlog data tracked.** Sole exception: the generated read-only `scripts/backlog-index-guard.py` is tracked, because it exists for CI. The rest of the `.ai-task/` runtime tree (`state.json`, `runs/`, `packets/`, `cleanup/`, `worktrees/`, `inbox.jsonl`) is machine-local too — `config.toml` / `policies/` are tracked at the operator's discretion in an own repository, and never in a foreign one (see "Own or foreign repository" above).

**Migration for repos initialized before the vendoring moved under `.ai-task/`.** Older repos may still have tracked copies at `scripts/backlog-id-registry.py` / `docs/ai-task-*.md` (the previous destination). `ai-task init` now vendors to `.ai-task/` and prints a note listing any leftover old copies; the operator may **delete those old tracked files** — init does not remove them, and nothing executable references them anymore.

**Profile-only (not copied into target repos):** the full `docs/ai-task.md`, teamlead/SDLC playbooks, the skills under `~/.claude/skills`, and the review registry `skills/ai-task-reviewer/registry.json` (the CLI falls back to the profile copy when a repo has none). Profile-only helper scripts such as `check-delivery-artifacts.py`, `worktree-preflight.py`, and `ai-task-quota-statusline-dispatch.py` run from the profile against any repo and are not vendored. Do not vendor the whole ai-sdlc-local-kit `docs/` tree, `scripts/` tree, or skills into a target repo — only the explicit `BOOTSTRAP_DOCS` / `BOOTSTRAP_SCRIPTS` manifests.

Suggested defaults:

- `config.toml`: project id, backlog path, agents file path, default policy name, and `worktrees_enabled` (default **true** on git repos; `--no-worktrees` to disable; `--worktrees` to force on).
- `state.json`: schema version, active runs, paused runs, known backend cooldowns, and last selected tasks.
- `inbox.jsonl`: append-only user notes for active and future runs.
- `policies/default.toml`: batch size, priority rules, review gates, backend order, verify profiles per stack (Python/Node/.NET), and fallback behavior. `ai-task init` sets `default_profile` from repo files (`package.json`, `pyproject.toml`, `.csproj`, …); ruff is only in Python profiles.
- `runs/`: per-run logs, selected backend, task packet, verification summary, review notes, and cleanup report.
- `packets/`: generated task packets passed to agents.
- `cleanup/`: records of generated files, temp dirs, worktrees, and orphaned processes safe to clean later.

## Required Defaults

The default policy should express:

- Backend order starts with Claude Code latest Sonnet with high effort for coding runs; review and verdict stay with the teamlead session.
- Cursor auto is allowed for simple work and as a fallback when higher-capability backends are limited.
- Codex is disabled until the repository or global toolchain defines a confirmed CLI contract.
- Risky tasks require review and may require user approval before fallback to a weaker backend.
- Agents receive task packets, not the entire backlog, unless broad planning is requested.

## Handoff

After initialization, report:

- Created or reused files, including any bootstrap delivery docs copied into `docs/`.
- The ownership line from init (own or foreign, and why). In a foreign repository say that `.ai-task/` is excluded locally and nothing of it may be committed, and pass on any untracking commands init printed. In an own repository say whether `.ai-task` is tracked by git or should be ignored.
- The default backend policy.
- Tell the user to use **`ai-task-teamlead`** or `/ai-task-teamlead` for status and runs (no CLI memorization). Mention `ai-task self-test` only as a one-time health check after init.
