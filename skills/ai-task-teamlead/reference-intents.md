# Teamlead reference — workflow routing and intent map

Companion to `SKILL.md` (ai-task-teamlead); loaded on demand. Normative.

## When to use which workflow

| User goal | Use |
|-----------|-----|
| PRD, TECHSPEC, new backlog tasks, DoR, reprioritize | **ai-task-product** |
| Headless backlog with Claude/Cursor policy and run logs | **This skill** + `.ai-task` |
| Ship backlog (default) | **This skill** — **iterative waves** (below) |
| «Прогони всё без пауз» / one shot | Monolithic loop (see **Non-default: monolithic run**) |
| «Прогони всё» without `.ai-task` | **ai-task-init**, then this skill, or **sdlc-implement-all** |
| All open tasks in Cursor chat (main tree, sequential) | **sdlc-implement-all** |
| Batch with git isolation / worktrees / parallel headless runs | **This skill** — scenario `isolated_worktree_batch` (Q6 worktrees); requires `.ai-task` and `worktrees_enabled` |
| One task in chat, no `.ai-task` | **/sdlc-implement-task** |
| Backlog too large / archive closed work | **sdlc-backlog-rotate** (product/hygiene; not a delivery wave) |
| Design or change ai-task code/policy | **ai-task-maintainer** |
| First-time `.ai-task` files only | **ai-task-init** (then return here) |

If the user asks for **worktree isolation** in IDE chat, do **not** route to **sdlc-implement-all** (that skill uses the main tree). Use this skill with `isolated_worktree_batch` or explain headless `ai-task run` with `worktrees_enabled`.

**Never plan from the archive.** After a **sdlc-backlog-rotate**, closed tasks live in `backlog/archive/BACKLOG-NNN.md`. You schedule **only** from active `BACKLOG.md` — `plan`, `dor`, and `backlog-order` ignore `backlog/archive/*` by design. Do not pull an archived `- [x]` back into a wave, and do not treat a missing archived id as a backlog gap (it is closed history). Allocate any new ids via product from `backlog/id-registry.toml`, never by re-using an archived number. A rotation is product/hygiene work, not a delivery wave.


## Intent to action

Map user language (English or Russian) to internal CLI. **Do not teach commands** unless the user asked for CLI; use the **status template** and plain-language answers. Full command list for you (not for the user): **`reference.md`** → CLI parity appendix.

| Intent | Examples | Internal action |
|--------|----------|-----------------|
| Setup | «включи ai-task», «initialize» | `init` (via ai-task-init), `self-test` |
| Run **named** task | «запусти QA-007», «run TASK-001» | `dor --task-id TASK-ID` → `run TASK-ID --wait` (+ `--confirm-risk` if gates and no W3 auto-confirm-risk). **Skip `plan`.** |
| Plan **next eligible** | «что дальше», «следующая в очереди» | `dor` or `plan --strict` → optional bare `plan` (preview packet for queue head) → `run --wait` |
| Plan **wave (bulk)** | «план на 3 задачи», ship backlog | After scenario picker: `plan --auto-batch --json --bulk` (or `--batch N --json --bulk` when user names N) |
| Backlog order | «покажи полную очередь», preview only | `backlog-order` (not required each wave) |
| DoR check | «готов ли backlog», «проверь DoR» | `dor` or `plan --strict` |
| DoR one task | «DoR для TASK-001» | `dor --task-id TASK-001` (`--json` → gap list for product) |
| Run one (wait) | «следующая задача», «run TASK-001 и дождись» | `run --wait` or `run TASK-001 --wait` (default delivery) |
| Run in background | «в фоне», «не жди», detached | `run` or `run TASK-001` **without** `--wait`; later **status** / Run health |
| Run backend pick | «через Claude», «на Codex», «на Devin», «всю волну на …» | Pin the requested executor once: `claude`, native `codex`, `cursor_codex` for Cursor, or `devin`. Without an explicit choice, use `pin auto` after grouping tasks by their explicit Agent choices. Host inference applies only when enabled and after project/task choices. Clear the pin after the wave; record `decision log --phase backend`. For one run use `--backend <name>`. |
| Run dry | «проверь команду без запуска» | `run --dry-run` or `plan` + read packet path |
| Lease override | «перехвати задачу», lease error | `run --take-lease` only after user accepts overriding holder run |
| Ship backlog | «прогони backlog», «delivery», «все открытые» | If `[scenario] default` set in policy: announce and proceed; else **delivery scenario picker** (blocking), then run selected scenario |
| Monolithic run | «без пауз», «одним заходом», «не останавливайся» | Start scenario picker with Q2 prefilled (no pauses), confirm scenario, then run (wording overrides a conflicting `[scenario] default`) |
| Continue batch | «continue», «продолжай», «го дальше» | Resume via last `delivery_scenario:*`; if stale/conflict, fall back to `[scenario] default` or run mini-picker (Q2 + Q7) |
| Isolated batch | «прогони три задачи с изоляцией», «batch 3 with worktrees» | Start scenario picker with isolation prefilled; recommend `isolated_worktree_batch` when policy allows |
| Status | «статус», «что с агентами», «лимиты», «завис?», «долго» | `status --json` + backlog read → **status template**; no CLI lecture |
| Watch logs | «покажи логи run …», «что в логе» | `watch <run-id>` internally; short tail in chat (`--follow` only if user waits here) |
| Pause / stop / resume | «останови», «пауза» | `pause` / `stop` / `resume` (confirm before `stop`) |
| Note | «заметка: …» | `note "..."` with `--task-id` or `--run-id`; optional `--scope` queued\|running\|review\|future |
| Rebuild packet | «учти заметки в пакете» | `packet refresh <task-id>` then `run` when ready |
| Review | «ревью последнего» | `review <run-id>` → load **ai-task-reviewer** + stack skills from `review-skills.json`; then **verdict** |
| Verify run | «прогони тесты», «lint», «собери .NET» | `verify --run-id`; profile from task `Verify:` or stack heuristics |
| Verify preview | «какие проверки будут» | `verify --run-id` or `--task-id` with `--dry-run` |
| Verify skip | «пропусти verify» | `verify --skip` only if policy `allow_skip = true`; say why if blocked |
| Verdict | «принять», «переделать», «отложить» | `verdict <run-id> approve\|rework\|split\|defer\|escalate` + backlog per `reference.md` |
| Close run | «закрой run», mark done | `complete <run-id>` (state only; worktree separate row) |
| Reprioritize (delivery) | «сначала TASK-002» | Suggest **ai-task-product**; then `plan` |
| Cleanup audit | «что можно убрать» | `cleanup --dry-run` |
| Prune runs | «убери старые run’ы» | Ask retention once if unclear; `prune --dry-run` → `--older-than` / `--keep-last` + `--yes` |
| Prune failed too | «убери и упавшие» | add `--include-failed`; optional `--cleanup-reports` with `--older-than` |
| Worktrees after merge | «убери worktree» | `complete <run-id> --remove-worktree` or `cleanup --remove-worktrees` |
| Policy health | «какие бэкенды», «модели» | `policy backends` |
| Policy file | «где policy», «покажи конфиг» | `policy path` or `policy show` (brief; deep edits → **ai-task-maintainer**) |
| Policy sync | «синкни policy», «обнови конфиг», «policy sync», after ai-sdlc-local-kit upgrade | `policy sync --dry-run` → brief side-by-side summary → `policy sync` (**no `--force` by default**) |
| Policy force sync | «принудительно», «force sync», «полный синк policy» | `policy sync --dry-run --force` → say what will overwrite → `policy sync --force` (local-only keys/backends kept) |
| Parallel plan | «можно параллель?», batch ≥ 2 | First W1 `plan --auto-batch --json` (or explicit `--batch N`), then `parallel-plan` on the same slice + `decision log` |
| Project dashboard | «дашборд», «отчёт по проекту», «analytics report», «визуализация прогресса», «burndown» | `report` → `.ai-task/reports/report.html`; optional `--output`; optional `--since 7d` / `--since YYYY-MM-DD` / `--since ISO-datetime` for a time-windowed view; `--last N` for last N runs by recency (mutually exclusive with `--since`); open in browser |
| Decision facts | «отчёт по решениям», «журнал решений», stats | `decision analytics --since 30d --format md` (factual md/html; no blocking Q&A) — **not** `report` |
| Decision reflect | «разметь решения» | `decision reflect --since 7d`; then `decision result good\|bad` |
| Decision retro | «ретро тимлида», «ревью decisionов», «retro decisions», «улучшения после прогона» | **Stop delivery loop.** Load **ai-task-retro** (or `cursor-commands/ai-task-retro.md`). Run `retro` in target repo, blocking Q&A, improvement tasks in **ai-sdlc-local-kit** BACKLOG. Not the same as `decision analytics` alone. |

### Scenario execution ids

Use named scenarios from `reference.md`:

- `wave_full` (default, safest)
- `wave_monolithic`
- `wave_monolithic_sequential`
- `single_next`
- `isolated_worktree_batch`

Execution rule: scenario decides cadence and W1/W2 style; the dispatch rules own the exact mechanics.

Monolithic means no **user confirmation pause** between waves. It does not remove W5, W6, or W7. You still run wave gate, cross-role handoff, and replanning on every wave.

Only when the user **explicitly** wants no pauses between waves. Still keep W1/W2 order (`plan` then `parallel-plan`), and use `run --wait` only for `sequential` or `wave_monolithic_sequential` strategy. You may use `backlog-order` once as a preview, then continue id-by-id, but still keep per-task verify/review/verdict and full W5 to W7 flow.


## Handoff to other skills

- **ai-task-product** — PRD, TECHSPEC, backlog, DoR, new tasks, reprioritize metadata.
- **ai-task-init** — create `.ai-task` layout.
- **ai-task-maintainer** — change policy, backends, supervision; not daily operations.
- **sdlc-implement-all** — Cursor-native sequential batch in the main working tree (no per-task git worktrees).
- **sdlc-implement-task** — one task flow when bulk scenario is not needed.
- **sdlc-backlog-add** — verdict **split** follow-up tasks.
- **sdlc-verify-dod** — when you implement code in the ai-sdlc-local-kit repo itself (not when only operating ai-task in a target repo).


## Example user phrases

- «Тимлид, статус backlog и агентов»
- «Прогони все открытые задачи через ai-task»
- «Прогони три задачи с изоляцией» (`isolated_worktree_batch` + worktrees)
- «Запусти следующую задачу и дождись»
- «Claude в лимите?»
- «Заметка на текущий run: не менять публичный API»
- «Teamlead status» / «Run the next backlog task headless»
- «Сделай дашборд по backlog и run’ам» / «Project analytics report»

