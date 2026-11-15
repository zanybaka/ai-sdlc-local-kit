# AI Task Ops Command Router

Use skill: **ai-task-ops**.

Additional skills when relevant:
- **sdlc-backlog-add** (file the incident/monitoring task in the target repo)
- **lessons-learned** (structured post-mortem for sev1/sev2)
- **ai-task-product** (when an ops task needs DoR shaping before delivery)
- **kaizen** (preventive tuning after a recurring incident)

## Task

Run the **post-release operations stage**: watch a live service's signals, triage incidents, and turn each incident or monitoring signal into a backlog task with `Source:`/`Incident:` provenance and correct Priority. Hand sev1/sev2 to **lessons-learned** for a post-mortem.

**Do not** run delivery waves (that is **ai-task-teamlead**) or author PRDs (that is **ai-task-product**). You file the work; teamlead delivers it in a later wave.

## Target repos

| Repo | Role |
|------|------|
| **Target** (the live service) | Read monitoring/logs/runbooks; write `OPS-*`/`FLOW-*` tasks + post-mortems |
| **ai-sdlc-local-kit** (this profile repo) | Skill/process improvements only when the user confirms |

Ops backlog tasks land in the **target repo** (that service's own work).

## Typical requests (say any of these)

| User says | You do |
|-----------|--------|
| «сервис упал», «инцидент на проде» | Triage severity → file `Source: incident` task (Priority per severity) → lessons-learned post-mortem |
| «capacity/сертификат/секрет скоро истекут» | File `Source: monitoring` task (proactive, no `Incident:` needed) |
| «разбор инцидента», «post-mortem» | Run **lessons-learned**, link it from the incident task |
| «заведи задачу по инциденту» | `sdlc-backlog-add` with `Source:`/`Incident:` provenance |

## Intake shape (provenance mandatory)

```md
- [ ] OPS-NNN <fix title>
Task Context
<sevN, window, signal, user impact>; link post-mortem.
Task DOD
<healthy + guardrail + post-mortem linked>
Priority: P0        # sev1→P0, sev2→P1, sev3→P2, sev4→P3
Size: M
Depends on:
Agent: auto         # human for owner-only drills/accounts (headless runs skip it)
Source: incident
Incident: INC-YYYY-MM-DD-NN sevN (<signal + impact>)
Risk: P0, ack owner YYYY-MM-DD.   # P0/P1 only
```

## Output

- Triaged severity + Priority per live signal that needs work
- Backlog task(s) in the target repo with `Source:`/`Incident:` provenance
- lessons-learned post-mortem for sev1/sev2, linked from the task
- Owner-only ops filed as `Agent: human`

## Examples

- «Heartbeat сервиса флатлайнул на 12 минут — заведи инцидент и разбор»
- «Сертификат домена истекает через 2 недели — проактивная задача»
- «Restore-drill Postgres не прошёл — что заводим?»
