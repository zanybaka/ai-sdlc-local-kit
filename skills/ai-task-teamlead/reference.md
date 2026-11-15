# Teamlead reference — delivery SDLC

## Delivery pipeline (stages)

```text
[Product DoR] → dor (start) → ┌─ wave loop ─────────────────────────────┐
                              │ plan --auto-batch --json → parallel-plan? → run sub-waves │
                              │ → verify → review → verdict → release  │
                              │ → wave gate → product? → next wave     │
                              └────────────────────────────────────────┘
                              → Retro (engagement end)
```

**Default:** many waves, not one `backlog-order` + run-all. Between waves: re-read backlog, `plan` again, product may add/defer tasks.

## Delivery scenarios

Before W0 for bulk delivery, run a blocking shore interview and map answers to one scenario id.

Under an owner's intent that forbids questions there is no interview: the teamlead picks `wave_monolithic` itself, logs it with `"source": "intent"` and reports it in one line (SKILL.md → Delivering an intent).

### Scenario ids

| Scenario id | Scope and cadence | Quality and product | Parallelism and isolation | Failure policy |
|-------------|-------------------|---------------------|---------------------------|----------------|
| `wave_full` | Iterative waves, user summary between waves | Full verify → review → verdict every run, strict `delivery_feedback` loop | W1 `plan --auto-batch`; W2 per the dispatch rules (`parallel-plan` + sub-wave dispatch when allowed); main tree unless Q6 says worktrees | Stop on configured policy (recommended: finish wave then stop) |
| `wave_monolithic` | Iterative internals, no user pause between waves | Same as `wave_full` | Same W1/W2 as `wave_full` | Continue by selected Q7 policy |
| `wave_monolithic_sequential` | No pause, sequential execution | Full quality gates still required | W1 `plan --auto-batch` (or fixed `--batch N`), W2 sequential only, `run --wait` per task/sub-wave | Continue or stop by Q7 |
| `single_next` | Next eligible task only, then stop | Full verify/review/verdict on that task | `dor` → `run --wait` (optional bare `plan` to preview queue head only; **not** for explicit task ids) | Stop after one task |
| `isolated_worktree_batch` | Batch delivery with isolation | Full quality gates; product handoff per Q4 | Worktrees on, W1 `plan --auto-batch` or fixed `--batch N`, W2 per the dispatch rules unless Q5 forced sequential | Continue or stop by Q7 |

Recommended safe default when signals are mixed: **`wave_full`**.

### Blocking questionnaire (one question per message)

If `[scenario] default` is set in the active policy, skip the questionnaire (see SKILL.md → Policy default fast path). Without a default, ask Q2 + Q7 only (Q3/Q4 are mandated constants; Q1/Q5/Q6 default to all-eligible/auto/per-policy) — full Q1-Q7 only when wording is genuinely ambiguous or it is the first-ever bulk run in the repo.

Use numbered options each turn. Skip already-fixed topics from the user's first message.

| ID | Topic | Options to present |
|----|-------|--------------------|
| Q1 | Scope | `1)` all eligible open tasks, `2)` next wave only, `3)` explicit ids (user list) |
| Q2 | User cadence | `1)` summary between waves, `2)` no pause between waves (monolithic UX) |
| Q3 | Quality bar | `1)` full verify+review+verdict every run, `2)` verify every run and review on gates only, `3)` abbreviated checks (list explicit skips) |
| Q4 | Product handoff | `1)` strict W6 `delivery_feedback` loop, `2)` ask user before backlog metadata changes |
| Q5 | Parallelism | `1)` auto (`plan --auto-batch` + `parallel-plan` + sub-wave dispatch per the dispatch rules), `2)` sequential only (`parallel-plan` sequential + `run --wait`) |
| Q6 | Isolation | `1)` main tree, `2)` worktrees when policy/config allows |
| Q7 | Failure policy | `1)` stop batch on first failed run, `2)` finish current wave then stop, `3)` log and continue batch |

Answer parsing:

- Accept number, letter, or short paraphrase.
- If unclear, ask one clarifying question and wait.

### Confirmation turn (required)

After Q&A completion, print a compact summary table:

| Field | Value |
|-------|-------|
| scope | ... |
| cadence | ... |
| quality | ... |
| product | ... |
| parallelism | ... |
| isolation | ... |
| failure | ... |

Then ask: `Стартуем сценарий <id>?`

Wait for explicit yes unless the user already confirmed in the same message (for example: «погнали»).

### Decision log payload

On confirmation:

```bash
ai-task decision log --phase plan --choice delivery_scenario:<id> --signals-json '{...}'
```

`signals-json` should include:

- `questionnaire_version`
- `questions[]` with `id`, `topic`, `options`
- `answers[]` with selected option label and raw user text
- `scenario_summary` (`scope`, `cadence`, `quality`, `product`, `parallelism`, `isolation`, `failure`)

### Resume / continue rules

For `continue` with many tasks open (`>=2`) or incomplete last batch:

1. Read latest `delivery_scenario:*` decision.
2. If missing, stale (`>[scenario] stale_days`, default 7d), or conflicting with user wording, fall back to `[scenario] default` when set (announce and proceed); otherwise run mini-interview:
   - Q2 cadence
   - Q7 failure policy
3. If fresh and matching, ask:
   - `Продолжаем <id>. Сменить формат? (1) да, опрос заново (2) нет, продолжаем`
4. Wait for answer before W0.

### Example transcript (compressed)

1. Teamlead: `Q1 scope: 1) all eligible 2) next wave only 3) explicit ids. Recommended: 1.`
2. User: `1`
3. Teamlead: `Q2 cadence: 1) summary between waves 2) no pauses.`
4. User: `2`
5. Teamlead asks Q3-Q7 one by one, user replies.
6. Teamlead prints summary table and: `Стартуем сценарий wave_monolithic?`
7. User: `погнали`
8. Teamlead logs `delivery_scenario:wave_monolithic` and starts W0.

| Stage | Owner | Primary actions |
|-------|-------|-----------------|
| DoR CLI | Teamlead | `dor` / `plan --strict` at start; again if BACKLOG changed |
| Wave plan | Teamlead | `plan --auto-batch --json` (or user-fixed `--batch N --json`), then `parallel-plan` if batch ≥2 |
| Assign | Teamlead | `run --dry-run`, backend override, `decision log` |
| Execute | CLI agent | sub-wave dispatch: background `run TASK-ID` up to `max_concurrent`, then verify/review/verdict per run before next sub-wave; `run --wait` only for sequential waves |
| Verify | Teamlead + agent | `verify` before review |
| Review | Teamlead + **ai-task-reviewer** | `review` → **ai-task-reviewer** (stack skills from `review-skills.json`); optional reviewer subagent |
| Verdict | Teamlead (+ user on escalate) | approve / rework / split / defer / escalate |
| Wave gate | Teamlead | `status --json`, summary; full-template rows present for overrides / escalations / `delivery_feedback` / `mechanical_metadata_fix` |
| Release | User + teamlead | merge, `complete`, `[x]`, docs |
| Retro | Teamlead | end of engagement: `decision reflect --since 7d` + grading, `retro`, `prune` offer |
| Project dashboard | Teamlead | `report` when user wants HTML charts (backlog + runs); not decision journal |

## Monolithic clarification (required)

Monolithic delivery means one continuous operator flow with no user confirmation between waves. It does not skip W5 wave gate, W6 product handoff, or W7 replan-next-wave.

Even in monolithic mode:

1. Finish W4 verify, review, verdict for each run.
2. Run W5 `status --json` and a one-line wave summary (reflect/grading waits for retro).
3. Run W6 product handoff when any trigger below appears.
4. Continue W7 automatically without asking the user again.

## W6 product handoff triggers (required)

Command order:

1. `decision log --phase cross --choice delivery_feedback`
2. Load **ai-task-product** with a gap list and evidence
3. After product updates BACKLOG, log `decision log --phase cross --choice product_response` (or include product response in wave summary)
4. Run `dor` or `plan --strict`, then continue W7

Trigger handoff when any condition is true:

1. Verify failed or was skipped and DoD implies another profile (for example UI/Playwright context with only `Verify: node-web`).
2. Predecessor run is `failed` or `needs_review` without approve, but dependent task is eligible or already `[x]`.
3. `dor` or `plan --strict` reports a gap in the next slice.
4. Verdict is `split`, or scope is outside the current task block.
5. You are about to make a **judgment-bearing** metadata change (scope, split/defer, priority, `Verify:` semantics) just to make delivery pass. Mechanical validator-named fixes take the `mechanical_metadata_fix` route instead (see `docs/ai-task-backlog-contract.md` → Metadata ownership).

Do not skip this in monolithic mode. Teamlead does not own judgment-bearing metadata edits in trigger cases; an inline mechanical fix without its journal row is still a violation.

Anti-pattern callout: one chat acting as teamlead + implementer + product with zero `delivery_feedback` rows. Treat this as protocol failure even if delivery eventually passes.

## Verdict checklist (required after review)

Pick exactly one primary verdict per run (user may combine split + new tasks).

### Approve

- Verify passed and review has no blocking findings — approve **autonomously**; the user gate is verdict `escalate` only (see Involve-the-user table in the main skill).
- **Release contract:** implement run should already have shipped code, `BACKLOG.md` `[x]` with a `Progress:` line, and `CHANGELOG.md` (typically uncommitted); `tasks/<TASK-ID>.md` only when there is something to keep beyond them. Teamlead W4 owns the **git commit** (message includes task id), then `complete <run-id>` (and `--remove-worktree` if used).
- Before `complete`, confirm `[x]` and the Progress line (`complete` names either gap on stderr). When the DoD asks for a task report, `complete --require-report` fails closed without it.
- **DoD evidence rules (main skill):** entry-shaped DoD items (CHANGELOG / registry / backlog) are asserted by the dedicated **anchored entry line** (`grep -E '^- \*\*WEB-119' CHANGELOG.md`-style, `^- \*\*ID:` shape) — never a substring count (`grep -c <ID>` once approved a task whose dedicated entry was missing). Work recovered from a killed run (`needs_recovery`) is approvable only with a **per-DoD-item evidence list** (file:line or command output); «verifiably complete» without the list is not approvable — verdict `rework` or fresh run instead.
- `ai-task` does **not** auto-check backlog boxes or commit for you.

### Rework (same TASK-ID)

Align with the post-review table in `skills/ai-task-reviewer/SKILL.md` (Situation / Teamlead action): all actionable findings (including minor/nit) use this path.

- Leave task `- [ ]`.
- On the **review run** (order matters):
  1. `verdict rework`
  2. **`decision log --phase verdict --choice rework`** (judgment template in `--reason`)
  3. `note "rework: …"` with finding ids from `review-findings.md`
  4. **`complete <review-run-id>`** (required when status is `needs_review`; `stop` only if implement still `running`)
  5. **`decision log --phase delivery --choice retry_after_needs_review`** (or `run_failed` if retrying after failed run)
  6. New `run <TASK-ID> --wait` → **verify** → load **ai-task-reviewer** → **review** → verdict on new run
- The retry `run` includes the latest `review-findings.md` in its packet automatically; `packet refresh <task-id>` is an optional preview only. Findings are kept (not consumed) until the task closes — a newer review supersedes them.
- All actionable findings (minor/nit included) use this path, not IDE-only edits.

### Split

- Partial outcome: document in task report.
- **sdlc-backlog-add** for follow-ups; link `Depends on:`.
- Parent: `[x]` only if partial DoD explicitly satisfied, else stay open.

### Defer

- Set `- [~]` or add defer reason in Task Context.
- `complete <run-id>` to clear run state if no more work in this run.
- Do not claim backlog done.

### Escalate

- Stop automation; summarize risk (contract, security, architecture).
- Point to **sdlc-architecture-draft**, **sdlc-contract-guard**, or human owner.
- Do not use `--confirm-risk` or weaker fallback without explicit user approval.

## Review passes (human or reviewer agent)

Mirror common practice (Devin / human teams):

1. **Architecture** — right files and approach?
2. **Logic** — correctness, edge cases, errors?
3. **Conventions** — style, tests, docs?

Use `review-packet.md` diff stat as input. Adversarial prompt: list at least three concrete findings before «pass».

### UI-interaction review template (React / hooks / browser tasks)

Named template; full table and worked examples in main `SKILL.md`. On tasks that change hooks, effects, click-driven UI (popups, SVG, canvas), network-gated UI, or persisted view state:

1. **Effect-dep stability** — flag fresh object literals in dependency arrays (a popup hook returned a new object each render; popup objects in `useEffect` deps re-ran every render and closed popups immediately).
2. **Fire-on-action-not-on-mount** — pulse/nonce effects ignore the stale mount value and re-fire per user action (a pulse hook: 0 on mount, +1 post-mount).
3. **Shared-state brushing** — linked hover/spotlight surfaces reuse one shared state, never a fork (a second spotlight task reuses the first one's state).
4. **Persistence keys** — persisted view state restores as a coherent pair (camera + content), per-mode keys, no overwrite on leave (a restored camera over a force-reset collapse left the only visible card off-screen).
5. **Paths verify skips** — name interactions headless verify cannot run (SVG click, drag); require review evidence or a `decision log --phase review` gap note before approve.
6. **Real-browser evidence gate (blocking)** — the change gates on a cross-origin resource, network-status visibility, or a browser-only interaction (pointer capture, hover, SVG click, real layout) ⇒ mocked-fetch/jsdom green is insufficient; require a real-browser probe (preview/Playwright, or a minimal `Image()`/live-fetch status probe) **or** `decision log --phase review --choice approve_with_coverage_gap` plus a follow-up task (an avatar 401 gate: the fetch HEAD probe was CORS-blind cross-origin; the `Image()` probe is observable).
7. Do not fold review-only findings into `verdict` without a `phase=review` row when verify was green but interaction was unchecked.

## Deterministic gates (before AI review)

Gates are **required in the SDLC**, but **you choose the profile** (see `.ai-task/docs/ai-task-verify.md`).

| Level | Control |
|-------|---------|
| Repo | `.ai-task/policies/default.toml` → `default_profile` + `profiles.*` |
| Task | `Verify: python-full` / `node-full` / `web-e2e` / … in backlog |
| Run | `ai-task verify --profile …` (`--skip` only if `allow_skip`) |
| Auto | No `Verify:` + UI keywords in Task Context → `web-e2e` (`Resolution: task_context` in report) |

**Stacks (template):**

| Profile prefix | Languages | Typical commands |
|----------------|-----------|------------------|
| `python-*` | Python | ruff, pytest |
| `node-*` | JavaScript, TypeScript | npm `lint`, `test`, `typecheck` (your scripts) |
| `dotnet-*` | C#, F#, VB (.NET) | `dotnet build`, `dotnet test` |
| `go-*` | Go | `go vet`, `go test` |

Aliases `full`/`quick` = Python only. `none` = no commands; still run `verify --run-id` (passes, writes report).

Do not run ruff unless profile is `python-*` / `full` / `quick`.

**Teamlead:** after `run --wait`, run `ai-task verify --run-id`. If repo is mixed, read task `Verify:` or infer: `package.json` → node, `*.csproj`/`*.sln` → dotnet, `pyproject.toml` → python. Map user language to the right profile.

When the profile you run differs from task `Verify:` or auto-detect, log **`decision log --phase verify`** with choice `profile:…` or **`override_verify_profile`**. When you patch `.ai-task/state.json` or run metadata by hand, log **`--phase verify --choice manual_state_patch`** with what changed and why.

If `require_before_review = true` and verify fails → **rework**.

## Parallelism — `parallel-plan` + judgment (Q3+)

| Layer | Tool | Rule |
|-------|------|------|
| Inside TASK-ID | Packet text | Vendor **Task/subagents** only |
| Across TASK-IDs | `plan --auto-batch --json` then `parallel-plan --auto-batch --json` | CLI heuristics + **your** reasoning |
| Evidence | `decision log --phase parallel` | Required for batch ≥ 2 |

### CLI helper

```bash
ai-task plan --auto-batch --json
ai-task parallel-plan --auto-batch --json
```

If the user explicitly named batch size, replace auto-batch with `--batch N --json` in both commands. Do not run `parallel-plan` before `plan` in the same wave. Batch size comes from `plan`; `max_concurrent` is only the per-sub-wave dispatch cap.

Use fields:

- `signals[task_id].predicted_files` (with `file_prediction` sources and `path_tokens`), `scope_broad`, `layers`, `priority`, `size`
- `collision_edges` — pairs that must not share a wave, each with the reason they were separated
- `waves` — maximal disjoint groups packed under `max_concurrent`
- `strategy` — `parallel_waves` or `sequential`
- `reasoning` — machine-readable bullets (includes packed wave widths)
- `ask_user` / `ask_reason` — only then talk to the user

### Think beyond the JSON (favor parallel when reasonable)

| Favor parallel | Favor sequential |
|--------------|------------------|
| Different layers (`frontend` vs `backend` vs `tests`) | Shared entries in `predicted_files` / a `collision_edges` pair |
| Disjoint predicted files (even same folder) | `scope_broad` on any task |
| Small/medium tasks, no in-batch deps | In-batch `Depends on` |
| Worktrees enabled | `sequential_on_any_p0_risk` and any P0 |
| Docs/markdown-only vs code in another tree | `ask_user: true` from CLI |
| Overlap gate clean (no file predicted by ≥2 tasks) | **W2 overlap gate trips** — ≥2 tasks on one hot file, or overlap share ≥ the `[parallel] overlap_warn_share` policy value (default 0.3) |

**Overlap gate (W2, required before recommending parallel+worktrees):** estimate shared-file overlap across the batch reusing `predicted_files` / `collision_edges`. Tripped (≥2 tasks on the same hot file, or tasks-on-most-contended-file ÷ batch size ≥ the `[parallel] overlap_warn_share` policy value (default 0.3) — calibrated per repo from parallelism-ROI reflections) → recommend **sequential or pre-split waves** and present the **merge-back friction vs wall-clock** trade-off to the user before dispatch, even when `ask_user` is false. Collision-packed sub-waves do not remove worktree merge-back friction on a shared hot file. Full protocol and worked example: Overlap gate before parallel+worktrees, below.

Dispatch rule: execute `parallel-plan` sub-waves in order. In each sub-wave, start up to `max_concurrent` background `run TASK-ID` (no `--wait`), then complete verify/review/verdict for each run before moving to the next sub-wave. Use `run --wait` only when strategy is sequential (including `wave_monolithic_sequential`) or when there is one task.

Policy `[parallel]`: `allow_cross_layer`, `allow_mixed_size`, `sequential_on_broad_scope`, `sequential_on_any_p0_risk`.

After you decide: **`decision log`** with real `--reason` and `--signals-json` (paste waves + key flags). For W1 sizing, also log `decision log --phase plan --choice wave_batch:auto` (or `wave_batch:N`) with plan `batch_size`, `eligible_count`, and `batch_reasoning`.

Anti-patterns (do not):
- `parallel_waves` journal entry with single-task `last_batch`.
- "avoid parallel for state.json" blanket claims: `state.json` writes are lock-safe. Use concrete wave evidence instead.
- Skipping `parallel-plan` when planned `N >= 2`.
- Firing all wave ids in parallel and ignoring sub-wave boundaries.

### Override detection

When you log `--phase parallel`, the CLI compares your `--choice` to `parallel-plan --json` for the same `--task-ids`. If they disagree (for example plan says `parallel_waves` but you logged `sequential`), the row gets `signals.override=true` plus `plan_strategy` and `logged_choice`. Use choice **`override_parallel_plan`** when you knowingly disagree with the tool.

- **`decision reflect`** suggests renaming the choice to `override_parallel_plan` when override signals are present.
- **`decision check-overrides --since 7d`** scans existing parallel rows, patches missing override signals, and prints a report (`--dry-run` to preview).

These overrides feed **`decision analytics`** `judgment_quality.override_count` (choice prefix `override_` or `signals.override`).

### Packet snippet (intra-task)

```markdown
## Parallelism
If subtasks are independent (separate dirs, tests vs prod code), use the host CLI Task/subagents. Parent integrates results.
```

## Decision journal

**Normative home: `reference-journal.md`** — judgment template, when the full template is required (no per-wave minimum), override choices, when to log per phase, command examples, grading and self-analysis at retro, `report` analytics, maintainer handoff. CLI command semantics: `docs/ai-task-decisions.md`. Kept here: only the W5 wave-gate checklist used by the per-run stage gates.

### W5 wave gate checklist

Before W7 / next wave:

| Step | Action |
|------|--------|
| 1 | `status --json` + short wave summary |
| 2 | Confirm journal has full-template rows for overrides, escalations, `delivery_feedback`, and `mechanical_metadata_fix` this wave (auto-stubs cover routine anomalies) |
| 3 | Confirm each approve met the **DoD evidence rules** (`reference-review-gates.md`): anchored entry asserts (no substring counts), per-DoD-item evidence for runs recovered from kills, read-first shared-file merges |

Reflect/grading (`decision reflect` + `decision result`) is **not** a wave-gate step — it runs once at engagement end (retro). **Prohibited:** bulk identical `good` on all pending rows in one shot at retro; skipping retro after a large batch.

## Assignment hints

| Signal | Suggested action |
|--------|------------------|
| `Agent: claude` in backlog | CLI prefers `claude` (cooldown + limit fallback still apply) |
| `Agent: auto` (default) | Honor project routing, then host inference when enabled; fallback requires an explicit configured order |
| `Agent: codex` | Native `codex` in new policies; older policies preserve their Cursor alias until adoption |
| `Agent: cursor` | Opt-in `cursor_codex`, then `cursor_auto` on limits; sticky Cursor cooldown |
| `Agent: devin` | Opt-in `devin` (needs `devin` CLI + `devin auth login`) |
| `Agent: human` | Do not `run`; remind user |
| `Size: S`, no risk gates | Policy may prefer shorter path when `Agent: auto` |
| `review_gates` non-empty | `--confirm-risk` after explicit approval, or W3 auto-confirm-risk when scenario confirmation plus `Risk: P0/P1, approved` covers a high-priority gate |

CLI `--backend NAME` overrides backlog `Agent:` for one run. A wave pin overrides task metadata, suppresses fallback and rejects a conflicting `--backend`. Map an explicit vendor choice to `claude`, native `codex`, `cursor_codex` for Cursor, or `devin`. Otherwise group tasks by explicit Agent choices and use `pin auto` once before dispatch. Clear the pin when the wave ends. Older project policies retain their routing and legacy Codex alias until they follow the adoption steps in docs/ai-task.md.

## Verdict in state

After review:

```bash
ai-task verdict <run-id> approve --reflection "verify passed; backlog updated"
```

Values: `approve`, `rework`, `split`, `defer`, `escalate`. Exposed in `status --json` (`verdict`, `verdict_at`). On **`rework`**, also log **`decision log --phase verdict --choice rework`** (see Rework checklist and the post-review table in `skills/ai-task-reviewer/SKILL.md`).

## Status template

See main `SKILL.md` — use after every operational turn. Always call **`ai-task status --json`** first (optional `--task <id>` for routing on a specific open task). Include **`idle_seconds`**, **`signals`**, **`status_note`** per active run, **Operator alerts**, and **`routing`** when present. For `blocked_on_user` / `limit` / `stalled` / `fallback_blocked_reason`, follow the action hints in the main skill. Troubleshooting: `docs/ai-task.md` (Rate limits and cooldowns).

**User-facing rule:** never dump `ai-task` CLI usage unless they asked for commands. «Завис / долго» → main skill **Run health** section. Maintainer detail: `docs/ai-task.md` (Idle vs stalled vs blocked).

## DoR gap list (teamlead → product)

After `ai-task dor` or `plan --strict` fails, paste:

| task_id | field | observation | suggested fix |
|---------|-------|---------------|---------------|
| (from CLI) | | | |
| BUG-B1 | Task id | `action: fix_task_id_format` | rename to digit suffix (`BUG-003`), fix `Depends on:` |

JSON: `ai-task dor --json`. Contract: `.ai-task/docs/ai-task-backlog-contract.md` (task id format).

## Task targeting (do not confuse)

| Goal | Command | Notes |
|------|---------|-------|
| DoR one task | `dor --task-id TASK-ID` | Stdout may include `Review plan TASK-ID: …` — review planning inside `dor`, **not** the `plan` subcommand |
| DoR all open | `dor` or `plan --strict` | Exit 1 on gaps |
| Plan next wave slice | `plan` / `plan --auto-batch --json [--bulk]` | Queue head only; **no `--task-id`** |
| Run named task | `run TASK-ID --wait` | Positional id; run re-checks DoR for that task |
| Preview routing for id | `status --json --task TASK-ID` | Not `plan` |

**Never:** `plan --task-id` (flag does not exist).

## CLI parity appendix (teamlead internal — do not paste to user)

Maps `ai-task` commands to intents in main `SKILL.md`. Operator reference: `docs/ai-task.md`.

| Command | When teamlead uses it |
|---------|------------------------|
| `init` / `self-test` | Setup |
| `dor` / `plan --strict` | DoR gate; `dor --task-id` for one task (never `plan --task-id`) |
| `backlog-order` | Full queue preview; monolithic run |
| `plan` / `plan --auto-batch --json` / `plan --batch N --json` | W1 each wave or preview **next eligible** slice (`--batch N` only when user names N). Named task id → skip; use `run TASK-ID` |
| `parallel-plan --auto-batch --json` | W2 when planned batch ≥ 2, always after W1 plan |
| `run` / `run --wait` | Sub-wave dispatch uses background `run`; `--wait` only for sequential waves |
| `run --dry-run` / `--confirm-risk` / `--take-lease` / `--backend` | Smoke, gates, lease, per-run override |
| `pin` / `pin --clear` | Wave-level backend pin (user picked one vendor for the wave) |
| `executor --tasks N --waves M` | Before W1 of a batch: headless or in-session mode, and whether to ask the owner |
| `worker-done <run-id>` | Record an in-session subagent's outcome before verify |
| `status --json` | Every status turn; idle, signals, alerts, `routing` |
| `status --task <id>` | Routing for a specific open task (not only next eligible) |
| `cooldown clear <backend> --force` | Last resort; warn user API limits may persist |
| `watch` | Log tail; Run health |
| `pause` / `stop` / `resume` | Process control |
| `note` / `packet refresh` | Inbox; next packet |
| `verify` (+ `--dry-run`, `--skip`) | Pre-review gates |
| `review` / `verdict` | Review loop |
| `complete` (+ `--remove-worktree`) | Close run; worktree cleanup |
| `cleanup` / `prune` | Audit; disk retention |
| `policy backends` / `show` / `path` / `sync` | Health; config location; default `sync` is additive; `--force` only when user asks for full overwrite |
| `decision log\|result\|reflect\|analytics` | Journal + retro facts |
| `retro` | Start interactive retro packet |
| `report` (+ `--output`) | HTML project dashboard; wave gate or user request |

**Not in ai-task (by design):** auto `[x]` on BACKLOG; live note inject; reasoning/tool stream; subagent dashboard.

| Legacy gap | Workaround |
|------------|------------|
| No auto backlog `[x]` | Teamlead or implementer edits BACKLOG |
| Notes not live-injected | `packet refresh` + new `run` |

## Product gap list (DoR handoff)

When `dor` or `plan --strict` fails, send **ai-task-product** this table (copy from CLI output or `dor --json`):

```markdown
| task_id | field | observation | suggested fix |
|---------|-------|---------------|---------------|
| TASK-012 | Depends on | unknown dep TASK-099 | fix id or add TASK-099 |
| TASK-042 | Size | XL / `action: split_required` | product splits parent into S/M children before run |
| BUG-B1 | Task id | `fix_task_id_format` / letter suffix | rename to `BUG-003`, update deps and title |
```

If the product handoff named task ids that **`plan --json` does not list**, treat as a **Task id** gap (invalid checkbox format) and hand back to product before blaming an empty plan.

Metadata in delivery: **mechanical, validator-named fixes** (Size bucket normalization such as `Size: XS` → `Size: S`, task id format renames, dead `Depends on:` id removal) may be applied inline with one mandatory `decision log --phase cross --choice mechanical_metadata_fix` row naming task id + field + old→new. **Judgment calls** (scope mismatch, split/defer, priority changes, `Verify:` profile semantics) still go to product via `delivery_feedback`. Silently patching metadata to force delivery remains forbidden — the journal row is what makes the fix non-silent.


## Persist and resume

- Once confirmed, log:
  - `ai-task decision log --phase plan --choice delivery_scenario:<id> --signals-json '{...full_qna...}'`
- Include full interview in `signals-json` (`question_id`, options, selected label, raw user input).
- Keep `delivery_scenario:<id>` as the stable scenario row for the engagement.
- Per wave still log `wave_batch:auto` per the dispatch rules (do not replace scenario row).

For `continue` / `продолжай` with open tasks `>= 2` or incomplete last batch:

1. Read last `delivery_scenario:*` decision.
2. Re-run mini-interview if missing, stale (`>7d`), or conflicting with new user wording.
3. Mini-interview minimum: Q2 cadence + Q7 failure policy, one question per message.
4. If scenario is fresh and matches intent, ask:

`Продолжаем <id> (...). Сменить формат? (1) да, опрос заново (2) нет, продолжаем`

Wait for answer before W0.


## Parallelism (think, then act)

**Do not fight vendor tools.** Intra-task parallelism = vendor subagents in the packet. Inter-task = `parallel-plan` + your judgment + `decision log`.

### Inside one TASK-ID

Packet snippet (see `reference.md`): instruct **Claude Task / Cursor subagents** when subtasks are independent.

### Across TASK-IDs (required workflow for batch ≥ 2)

1. W1 first: run **`ai-task plan --auto-batch --json`** (or `plan --batch N --json` only when user named `N`). Never start with `parallel-plan` in the same wave.
2. Log W1 sizing: **`decision log --phase plan --choice wave_batch:auto`** (or `wave_batch:N`) with `--signals-json` containing plan `batch_size`, `eligible_count`, and `batch_reasoning`.
3. Run **`ai-task parallel-plan --auto-batch --json`** (or `--batch N` for explicit N) on that planned slice.
4. Read `strategy`, `waves`, `reasoning`, `signals` (`predicted_files`, layers, `scope_broad`, P0, deps), and `collision_edges` (why pairs were separated).
5. **Think beyond the JSON:** waves are already packed around predicted file collisions, so override on what predictions cannot see — shared contracts/schemas without file overlap → sequential; stale history predictions after a refactor → trust the tree; docs-only + code task → often parallel; two P0 risk → sequential (see `docs/ai-task-delivery-waves.md` → Collision-aware sub-wave packing).
6. **Overlap gate (required before recommending parallel+worktrees):** estimate shared-file overlap across the batch (see below); if it trips, recommend sequential or pre-split waves and present the trade-off to the user before dispatch.
7. Log strategy with **`decision log --phase parallel`**, your final `--choice`, `--task-ids` for the wave, and `--signals-json` copy of key evidence (include `hot_files`, `overlap_share`, and `expected_roi` when the batch had any shared predicted files).
8. Dispatch by sub-wave order: up to `max_concurrent` background `run TASK-ID` (no `--wait`) per sub-wave, then finish verify/review/verdict per run before moving to the next sub-wave. Use `run --wait` only for sequential / `wave_monolithic_sequential` cases.
9. Ask the user **only** if `ask_user` is true in the JSON or the overlap gate tripped (step 6).

Policy knobs: `allow_cross_layer`, `allow_mixed_size`, `sequential_on_any_p0_risk`, `sequential_on_broad_scope` in `[parallel]`.

Full rubric: `reference.md`.

### Overlap gate before parallel+worktrees (W2, required)

Overlap estimation is a **required pre-dispatch step**, not a lesson re-learned per batch. Source incident: an `isolated_worktree_batch` of 7 delivered correctly but with low parallelism ROI — 3 of 7 tasks shared one state module, the worktree merge-backs fought over it, and the teamlead self-graded the strategy advice bad: «I'd advise sequential next time for high-overlap batches and flag the trade-off before the user picks».

1. **Estimate overlap** from evidence you already have: `parallel-plan --json` `signals[task_id].predicted_files` and `collision_edges` (reuse the predictions — recompute from task text / `git log` only when predictions are empty). For each file predicted by ≥2 tasks, record the **hot file** and how many tasks touch it.
2. **Policy threshold (calibrate per repo):** the gate **trips** when **≥2 tasks touch the same hot file**, or the **overlap share** — tasks touching the most-contended file ÷ batch size — is **≥ the `[parallel] overlap_warn_share` policy value** (default 0.3; the source batch was 3/7 ≈ 43%). Adjust the repo's working threshold from accumulated parallelism-ROI reflections (step 4), not per anecdote.
3. **Tripped → do not silently dispatch parallel+worktrees.** Recommend **sequential** or **pre-split waves** (overlapping tasks serialized in one lane with immediate merge-back, disjoint tasks parallel) and present the trade-off to the user **before dispatch**, once per batch, in one message: «N of M tasks touch `<file>`; parallel+worktrees saves ~X wall-clock but each merge-back re-touches `<file>` (conflict/friction risk); sequential avoids that but takes longer. I recommend <strategy>.» This is a legitimate ask-user moment even when `parallel-plan` returned `ask_user: false`. Collision-packed sub-waves reduce in-flight conflicts but do **not** remove worktree merge-back friction on a shared hot file — deferred merges still collide at integration time.
4. **Close the loop so the threshold calibrates:** log the chosen strategy (`decision log --phase parallel`, choice `sequential`, `parallel_waves`, or `override_parallel_plan`) with `--signals-json` containing `hot_files`, `overlap_share`, and `expected_roi` (e.g. expected wall-clock saving and expected merge friction). At engagement-end reflect (retro), the **reflection records expected vs actual parallelism ROI** (see Judgment template) — actual merge conflicts/friction vs predicted, wall-clock actually saved — so over time the repo's threshold is tuned by data, not re-learned per batch. Land an agreed adjustment durably in `[parallel] overlap_warn_share` in `.ai-task/policies/default.toml` — local value wins on policy sync.

### Anti-patterns (do not)

- Calling `plan --task-id` to plan a named task, or treating `Review plan …` from `dor --task-id` as a cue to run `plan` (see **reference.md** → Task targeting).
- Logging `parallel_waves` while `last_batch` has one task id.
- Writing journal claims like "avoid parallel for state.json"; use concrete evidence and actual wave signals instead.
- Skipping `parallel-plan` when W1 planned batch has `N >= 2`.
- Launching all planned ids at once and ignoring sub-wave boundaries or `max_concurrent`.

