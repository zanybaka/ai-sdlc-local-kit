# AI Task Retro Command Router

Use skill: **ai-task-retro**.

Additional skills when relevant:
- **sdlc-backlog-add** (improvement tasks in ai-sdlc-local-kit)
- **ai-task-maintainer** (only if user asks to change `scripts/ai-task.py` this turn)
- **ai-task-product** (when retro surfaces DoR/backlog gaps → `delivery_feedback`)
- **lessons-learned** / **kaizen** (incident vs routine tuning)

## Task

Run an **interactive decision retrospective** after a large ai-task delivery batch. Review teamlead judgment in the target repo, improve **ai-sdlc-local-kit** skills and ai-task CLI, write retro reports in the target repo.

**Do not** run delivery (`ai-task run`) during retro.

## Target repos

| Repo | Role |
|------|------|
| **Target** (user names path or workspace) | Read `.ai-task/`, write retro MD/HTML, log `retro_complete` |
| **ai-sdlc-local-kit** (this profile repo) | Write improvement tasks to `BACKLOG.md`, skill doc updates when user confirms |

Default: improvements go to **ai-sdlc-local-kit** forward-only (no backfill in target repo unless user chooses option 2).

## Typical requests (say any of these)

| User says | You do |
|-----------|--------|
| «Ревью decisionов», «ретро тимлида», «retro decisions» | Full **ai-task-retro** flow |
| «Ревью решений после прогона в /path/to/repo» | Same; target = that path |
| «Что улучшить в ai-task после этого проекта» | Same; infer target from context or ask once |

## Bootstrap (you run this)

From target repo root (use `scripts/ai-task.py` from ai-sdlc-local-kit if needed):

```bash
ai-task retro --since 30d
# or for full batch history:
ai-task retro
```

Then read `.ai-task/packets/retro-YYYY-MM.md`, factual report, and `decisions.jsonl`. Cross-check `state.json` for implicit retries and journal gaps before interviewing.

## Output

- Blocking Q&A (one question per message) until scope is clear
- Retro reports in target: `.ai-task/reports/decisions-YYYY-MM-retro.md` + `.html`
- 3–7 improvement tasks in **ai-sdlc-local-kit** `BACKLOG.md` (phase «Retro improvements»)
- Short summary: task ids, report links, skill/cli recommendations

## Examples

- «Ревью decisionов из сделанных задач в /Users/me/project»
- «Retro after M1 delivery, forward-only improvements»
- «Decision review — was the teamlead journal good enough?»
