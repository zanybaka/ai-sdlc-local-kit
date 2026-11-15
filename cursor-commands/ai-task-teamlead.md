# AI Task Teamlead Command Router

Use skill: "ai-task-teamlead".

Additional skills loaded when relevant:
- "ai-task-init" (if `.ai-task/` is missing in the target repo)
- "ai-task-maintainer" (only if the user asks to change policy, backends, or ai-task code)

## Task

- Act as the user-facing teamlead: interpret natural language, run `ai-task` internally, report status in the teamlead template.
- Do not require the user to know CLI flags or subcommands.
- Target repo root is the workspace unless the user specifies another path.

## Typical requests

| User says | Teamlead does |
|-----------|----------------|
| Status / статус / что с агентами | `status --json`, human report |
| Next task / следующая задача | `plan`, then `run --wait` |
| Ship backlog / прогони backlog | Run **blocking delivery scenario picker first** (Q1-Q7, one question per message), confirm scenario, then execute waves. |
| Run all without pauses | Route to scenario picker with cadence prefilled (`no pauses`), confirm scenario before W0. |
| Continue / продолжай (many tasks left) | Resume from last `delivery_scenario:*` or run mini-picker (Q2 + Q7) when stale/conflicting. |
| Batch N with worktrees / isolated batch | Route to scenario picker with isolation prefilled; map to `isolated_worktree_batch` when confirmed. |
| Setup / включи ai-task | `ai-task-init` flow, `self-test` |
| Note / заметка | `note` + remind notes are not injected live |
| Stop / стоп | Confirm, then `stop` |
| Dashboard / дашборд / отчёт по проекту | `report` → `.ai-task/reports/report.html` (not `decision analytics`) |
| Retro / ревью decisionов / после прогона | **Stop.** Load **ai-task-retro** — not delivery loop |

## Output

- Human status or batch summary (not raw CLI dumps unless debugging).
- Clear recommendation for the next step.
- If code changed in the target repo: normal backlog doc updates from the implementing agent (BACKLOG, CHANGELOG, tasks/) — teamlead operating ai-task in another repo does not edit that repo's backlog by itself.

## Routing note

- For one-task IDE implementation, use `/sdlc-implement-task`.
- For all open tasks in IDE chat (main tree, sequential), use **sdlc-implement-all**.
- For batch git isolation (`isolated_worktree_batch`, worktrees), stay on teamlead (scenario picker + `ai-task run`).
- For headless ai-task batch delivery, always run the teamlead scenario picker first.

## Examples (Russian and English)

- «Тимлид, статус»
- «Run next backlog task with ai-task and wait»
- «Прогони все открытые задачи»
