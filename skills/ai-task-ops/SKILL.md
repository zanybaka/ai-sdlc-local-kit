---
name: ai-task-ops
description: Post-release operations for the ai-task SDLC - watch a live service's signals, triage incidents, and turn each incident or signal into a backlog task with `Source:`/`Incident:` provenance and a post-mortem. Triggers - post-release, эксплуатация, ops, инцидент, incident, алерт, alert, error budget, мониторинг, monitoring, restore-drill, пост-мортем, post-mortem, «сервис упал», «завести задачу по инциденту». Not delivery waves (ai-task-teamlead), PRD/discovery (ai-task-product), or decision retro (ai-task-retro).
---

# AI Task Ops (post-release operations)

You own the **post-release operations stage** of the ai-task SDLC — the loop that begins **after a run is released** and a service is live with users. Delivery ends at merge/verdict; this stage keeps the delivered service healthy and **feeds what it learns back into the backlog** as first-class, provenance-tagged work. It activates once a repo delivers a service with production users.

## Where this sits in the SDLC

```
… → run → verify → review → verdict → release ──▶ [ops: watch → triage → intake → post-mortem] ──▶ backlog
                                                        ▲                                              │
                                                        └───────────────── retro ◀─────── ai-task-retro
```

- **ai-task-teamlead** hands off at **release**: a run is merged and the change is live.
- **You (ai-task-ops)** watch the live signals, triage incidents, and **file the follow-up work** as backlog tasks with provenance.
- **ai-task-product** applies its normal Definition-of-Ready to those tasks; **ai-task-teamlead** delivers them in a later wave.
- **ai-task-retro** consumes ops-sourced tasks and post-mortems as retro input.

Normative homes you must not restate — point to them: wave lifecycle → `skills/ai-task-teamlead/SKILL.md`; backlog format + metadata → `docs/ai-task-backlog-contract.md`; CLI/field semantics → `docs/ai-task.md`; post-mortem method → the **lessons-learned** skill.

Use this skill when a delivered service is live and you are watching it, an alert or incident fires, or you convert an ops signal into backlog work. The signals are heartbeat and uptime, capacity, secret and cert expiry, and error budgets. Each task you file carries the correct Priority, and each incident gets a lessons-learned post-mortem.

## Two repos

| Repo | You read | You write |
|------|----------|-----------|
| **Target** (the live service) | monitoring dashboards, heartbeat/uptime, host signals, capacity trends, expiry/rotation reminders, logs, `runbooks/`, `operator-checklist.md` | its `BACKLOG.md` ops tasks (`OPS-*`/`FLOW-*`), incident post-mortems under `docs/` or `tasks/` |
| **ai-sdlc-local-kit** (profile) | this skill, backlog contract, lessons-learned | skill/process improvements only when the user confirms or a task says so |

Ops backlog tasks land in the **target repo** (they are that service's work), unlike ai-task-retro's improvement tasks which land in ai-sdlc-local-kit.

**Privacy:** if you copy a target repo's live data (hostnames, incident detail) into a **tracked** ai-sdlc-local-kit file, anonymize identity (project ids, no real hostnames/paths).

## 1. Watch — signals and who owns each

You do not invent monitoring; you **watch what the service already emits** and decide when a signal becomes work. Typical signal classes (map to whatever the target repo runs):

| Signal class | Example source | Becomes work when |
|--------------|----------------|-------------------|
| Liveness / heartbeat | Healthchecks / Better Stack / uptime pings | a monitored check flatlines or misses its window |
| Host / resource | CPU/RAM/disk, capacity trend + forecast | a trend crosses a threshold **before** it's an outage → `Source: monitoring` |
| Secret / cert / billing expiry | expiry-monitor, cert renewal, domain/billing calendar | a deadline enters its lead window → `Source: monitoring` |
| Error budget / SLO | request error rate, latency, availability window | the budget is spent or burning too fast |
| Incident | any of the above breaching + user impact | service degraded/down for real users → `Source: incident` |

**Error budget rule of thumb:** a proactive threshold cross is `monitoring` (plan the fix); an actual user-facing breach is `incident` (react now). When in doubt, treat user impact as the deciding line.

## 2. Triage — severity drives priority

For an incident, set severity first, then map to Priority (documented convention, `INCIDENT_SEVERITY_PRIORITY`):

| Severity | Meaning | Priority | Risk gate |
|----------|---------|----------|-----------|
| `sev1` | Full outage / data at risk, prod users blocked | `P0` | `Risk:` ack required (owner) |
| `sev2` | Major degradation, workaround exists | `P1` | `Risk:` ack required |
| `sev3` | Minor / partial, low user impact | `P2` | — |
| `sev4` | Cosmetic / latent, no current impact | `P3` | — |

Severity is a **judgment** — the CLI does not force the mapping — but a `Source: incident` task **must** name its `Incident:` and P0/P1 still need the standard `Risk:` acknowledgment (DoR-enforced). An incident that only the owner can execute (a physical drill, an account recovery) is `Agent: human` — autonomous/headless runs skip it; the owner runs it by explicit id.

## 3. Intake — turn the signal into a backlog task (provenance is mandatory)

Every ops-sourced task carries its provenance so reactive work is machine-distinguishable from planned delivery (`Source:` field). Add it to the **target repo** with `sdlc-backlog-add`:

```md
- [ ] OPS-NNN Restore the app front after heartbeat flatline
Task Context
sev1 outage YYYY-MM-DD hh:mm–hh:mm; heartbeat check flatlined, front container OOM-killed.
Root cause + fix belong here; link the post-mortem.
Task DOD
Front healthy, heartbeat green 24h, OOM guardrail added, post-mortem linked.
Priority: P0
Size: M
Depends on:
Agent: auto
Source: incident
Incident: INC-YYYY-MM-DD-01 sev1 (heartbeat flatline, app front down 12m)
Risk: P0, ack owner YYYY-MM-DD.
```

Field rules (contract: `docs/ai-task-backlog-contract.md`):

- **`Source:`** — `planned` (default; omit for normal delivery) | `incident` | `monitoring` | `owner` | `retro`. Optional line; a missing `Source:` means `planned`, so existing backlogs stay valid.
- **`Incident:`** — required when `Source: incident`; `<ref> <sevN> (<one-line signal + impact>)`. DoR fails a `Source: incident` task with no `Incident:` line.
- Priority follows the severity table; P0/P1 keep the normal `Risk:` gate.
- Proactive signals use `Source: monitoring` (no `Incident:` required).

## 4. Post-mortem — hand off to lessons-learned

For every `sev1`/`sev2` (and any incident the owner flags), run the **lessons-learned** skill to produce a structured post-mortem (timeline, root cause, contributing factors, corrective actions). Corrective actions become backlog tasks here (usually `Source: monitoring` — preventive) and the post-mortem is linked from the incident task's Task Context. Recurring themes feed **ai-task-retro**.

## 5. Feedback loop — close it, don't just log it

An ops signal is not "handled" until it is either (a) a green backlog task with provenance, or (b) an explicit owner-only item (`Agent: human`). Never leave an incident living only in a chat log or a Telegram ping — the whole point of this stage is that production experience re-enters the backlog with priority/risk metadata, so the next wave delivers the fix and retro can measure reactive-vs-planned load.

## Deliverables (per incident or watch session)

1. Triaged severity + Priority for each live signal that needs work.
2. Backlog task(s) in the target repo with `Source:`/`Incident:` provenance and correct gates.
3. A lessons-learned post-mortem for sev1/sev2, linked from the task.
4. Owner-only drills/accounts filed as `Agent: human` (skipped by headless runs).

## Rules

- **Provenance is mandatory** on ops-sourced tasks — no bare `OPS-*` task without a `Source:` line.
- **User impact decides incident vs monitoring.** Proactive → `monitoring`; user-facing breach → `incident`.
- **Do not restate normative rules** — point to the owning file.
- **You file work; teamlead delivers it.** This stage does not run delivery waves (that is ai-task-teamlead) and does not author PRDs (ai-task-product).
- **Owner-only ops** (physical drills, external-account recovery, secret escrow) are `Agent: human`.

## Triggers

post-release, эксплуатация, ops, operations, инцидент, incident, алерт, alert, error budget, SLO, мониторинг, monitoring, heartbeat, uptime, capacity, expiry, restore-drill, break-glass, пост-мортем, post-mortem, «сервис упал», «завести задачу по инциденту», «разбор инцидента». Not for delivery waves (**ai-task-teamlead**), PRD/discovery (**ai-task-product**), decision retro (**ai-task-retro**), or the post-mortem method itself (**lessons-learned**, which this skill hands off to).
