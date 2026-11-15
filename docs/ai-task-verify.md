# ai-task verify — configurable gates

Deterministic checks (lint, tests, build) run **before** AI code review.

**Each stack has its own commands.** Ruff/pytest only under `python-*`. JS/TS use `node-*` (npm/pnpm/yarn scripts you define). .NET uses `dotnet` CLI. Go uses `go vet` / `go test`. Nothing assumes one linter for all repos.

CLI: **`ai-task verify`**. Chain: `run --wait` → `verify --run-id` → `review`.

## Three levels of choice

| Level | Where | Example |
|-------|-------|---------|
| **Repo** | `.ai-task/policies/default.toml` → `default_profile` | `default_profile = "node-full"` |
| **Task** | `BACKLOG.md` block | `Verify: dotnet-full` |
| **Run** | CLI | `ai-task verify --run-id … --profile node-quick` |

Resolution: **CLI `--profile`** → task **`Verify:`** → policy **`default_profile`**.

## Stack profiles (shipped in `default.toml`)

| Profile | Stack | Commands (edit per repo) |
|---------|-------|---------------------------|
| `python-full` | Python | `ruff check .`, `pytest -q` |
| `python-quick` | Python | `ruff check .` |
| `node-full` | JS/TS | `npm run lint`, `npm test` |
| `node-quick` | JS/TS | `npm run lint` |
| `dotnet-full` | .NET (C#, F#, VB) | `dotnet build --no-restore`, `dotnet test --no-build` |
| `dotnet-quick` | .NET | `dotnet build --no-restore` |
| `go-full` | Go | `go vet ./...`, `go test ./...` |
| `go-quick` | Go | `go vet ./...` |
| `web-e2e` | Web/UI (Playwright) | `npx playwright test` (edit per repo) |
| `web-e2e-quick` | Web/UI smoke | `npm run test:e2e` (when defined) |
| `docker-build` | Containers | `docker build -q .` (hadolint as commented opt-in) |
| `compose-config` | Containers | `docker compose config -q` |
| `terraform-validate` | IaC | `terraform fmt -check`, `terraform validate` (module dir) |
| `helm-lint` | Helm | `helm lint .` (chart dir; kube-score as commented opt-in) |
| `full` / `quick` | Python aliases | Same as `python-full` / `python-quick` |
| `none` | Opt-out | `[]` — no shell commands; verify writes a report and sets `verify_status: passed` so review can proceed |

### Auto `web-e2e` from Task Context

When a backlog block has **no** `Verify:` line, `ai-task verify` may select **`web-e2e`** if Task Context text matches UI keywords (web, frontend, playwright, streamlit, gradio, dashboard, etc.). Resolution is recorded in `verify-report.md` as `Resolution: task_context`. Override with an explicit `Verify:` line or `--profile`.

Packets for UI tasks instruct implementers to load **`playwright-skill`** (profile-level; see `SETUP.md`).

### Smoke-first convention (`web-e2e`)

For web apps that accept user-supplied data, a **smoke test** (open app → wait 2 s → assert zero console errors, no crash UI) must be the **first** test executed. Name it `smoke.test.ts` or `00_smoke.test.ts` so it runs before feature tests alphabetically. If no smoke test exists and the task touches state initialisation or data loading, teamlead should flag this as a review gap during W4. See [`docs/stability-testing.md`](stability-testing.md) for the idle-state principle and anti-patterns.

**TypeScript and JavaScript** share **`node-*`** profiles: one `package.json`, scripts like `lint`, `test`, `typecheck` (you wire `eslint`, `tsc`, `vitest`, `jest` there).

Add more names freely (`node-ci`, `rust-full`, `java-maven`, …). Commands run in the run cwd (repo root or worktree).

### Pipefail contract (pipes in profile commands)

Commands execute through bash/zsh with **`-o pipefail`**: if any stage of a pipe **written in the profile command itself** fails, the step fails with that stage's exit code. `npm run build 2>&1 | tail -5` fails when the build fails — tail's exit 0 cannot mask it (previously `sh -c` returned only the last stage's code and reported a false PASS).

**Nested-shell caveat.** Pipefail does **not** propagate into a nested shell: `bash -c 'cd web && npm run build 2>&1 | tail -5'` starts an inner shell *without* pipefail, the pipe lives there, and tail's exit code wins again — empirically `bash -o pipefail -c "bash -c 'false 2>&1 | tail -5'"` exits 0 while the flat form exits 1. `policy sync` preserves local profiles, so a repo that vendored a nested-wrapper profile keeps the hole until the profile is edited (one `node-web` profile was fixed by de-nesting). Convention: keep profile commands **flat** — `cd web && npm run build 2>&1 | tail -5`, not `bash -c '…'`. If a wrapper is unavoidable, start the inner command with `set -o pipefail;`. `ai-task verify` warns when a profile command nests a pipe inside `bash -c` / `sh -c` / `zsh -c` (names the profile and the inner command, suggests de-nesting); set `nested_shell_pipe = "fail"` under `[verify]` to refuse to run such profiles instead of warning.

Shipped profile templates are flat and pipe-free. On hosts without bash/zsh (Windows `cmd.exe`) there is no pipefail equivalent — keep profile commands pipe-free there.

### Per-repo setup

On **`ai-task init`**, the CLI sets `default_profile` from repo markers:

| Detected | `default_profile` |
|----------|-------------------|
| `package.json` only | `node-full` (JS/TS and frontend tooling) |
| `go.mod` only | `go-full` |
| `pyproject.toml` / `requirements.txt` / `ruff.toml` only | `python-full` |
| `.sln` / `.csproj` only | `dotnet-full` |
| Several stacks | `none` (set `Verify:` per task or edit policy) |
| Nothing obvious | `none` (you configure commands) |

You can override anytime in `default.toml`.

```toml
# Frontend monorepo
default_profile = "node-full"

# .NET service
default_profile = "dotnet-full"

# Python library
default_profile = "python-full"
```

Tune command strings to match **your** `package.json` scripts and solution layout.

### Your profile commands and `policy sync`

A repository may keep a shipped profile name and give it its own commands, for example `node-quick` with pnpm instead of npm and with tests added. `ai-task policy sync` treats `commands` of a profile as one value, not a set of items: order and composition are what the profile means. When your list differs from the bundled one, sync leaves it as is, appends nothing and lists it under "Local differs from bundled (kept as-is, not synced)" with the note "recipe list: local override kept whole". `--force` does not replace it either and lists it under "Kept on force sync". The same rule covers backend argv lists (`backends.<name>.args` and `extra_args`), except `backends.claude.args`, which the template still sets on purpose.

To take the bundled commands for a profile, delete its `commands` key or the whole `[verify.profiles.<name>]` table and run `ai-task policy sync`: a missing key is added from the template. A profile name the template does not ship is never touched.

### Mixed-stack backlog

One repo, several stacks: set **`Verify:` per task** (required when default is wrong for that task):

```md
- [ ] WEB-001 Add API client
Verify: node-full
Task DOD
…

- [ ] SVC-002 Fix billing endpoint
Verify: dotnet-full
Task DOD
…
```

### Composite profile (mixed python+node)

For a repo where most tasks touch both stacks, define one profile that chains both checks. The shipped template carries a commented `fullstack-example` block — uncomment and edit:

```toml
[verify.profiles.fullstack-example]
description = "Composite: python backend lint + node frontend lint"
commands = ["ruff check .", "cd web && npm run lint"]
```

Then `default_profile = "fullstack-example"`. Per-task `Verify:` remains the precise override — a python-only task can still declare `Verify: python-quick` and skip the frontend commands.

## Recommended settings for a Python repository

| Setting | Value |
|---------|--------|
| `require_before_review` | **`true`** |
| `allow_skip` | **`false`** |
| Python tasks | `Verify: python-full` or policy `default_profile = "python-full"` |

**Ruff is not universal.** Init on a Node repo sets `node-full`; on .NET sets `dotnet-full`; mixed repos get `none` until you configure.

## Teamlead

1. After `run --wait`, run **`ai-task verify --run-id <id>`** with the resolved profile.
2. If the repo has multiple stacks, infer or ask once:
   - `package.json` at root → suggest `node-*`
   - `*.sln` / `*.csproj` → suggest `dotnet-*`
   - `pyproject.toml` / `ruff` → suggest `python-*`
3. Map user phrases: «полный прогон фронта» → `node-full`, «собери .NET» → `dotnet-quick`, etc.
4. Verify failed + `require_before_review` → verdict **rework**, not approve. **No `--skip`** when `allow_skip = false`.

## Product / DoR

`Verify:` must name an existing profile in that repo's policy (or `none`). Product skill validates before handoff to teamlead.

## Commands

```bash
ai-task verify --run-id <run-id>
ai-task verify --task-id TASK-001 --dry-run
ai-task verify --run-id <run-id> --profile dotnet-full
```

`review <run-id>` requires `verify_status: passed` when `require_before_review = true`. Tasks with `Verify: none` (or profile `none`) still run `ai-task verify --run-id` once; empty profiles count as passed, not skipped.

See [ai-task-teamlead-sdlc.md](ai-task-teamlead-sdlc.md).
