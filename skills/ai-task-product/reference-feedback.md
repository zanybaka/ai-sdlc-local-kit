# ai-task-product — delivery feedback reference

Moved byte-faithfully from `SKILL.md`. Normative; load on demand.

## Delivery feedback from journal

When delivery exposes backlog or DoR gaps, teamlead logs:

```bash
ai-task decision log --phase cross --choice delivery_feedback \
  --reason "problem: … options: … choice: … expected: …" \
  --task-ids TASK-012
```

You **consume** those rows (and related verify/verdict signals) after a batch or when **ai-task-retro** hands off product/DoR focus. Default: fix backlog yourself — no user ping for wording, `Verify:`, or splits inside agreed scope.

### When to run

| Trigger | Action |
|---------|--------|
| Teamlead handoff after batch (reprioritize, DoR refresh) | Scan target `.ai-task/decisions.jsonl` |
| **ai-task-retro** Q&A: user picks product/DoR focus (question 3) | Same scan; pair with retro gap list |
| Retro credibility flag: obvious DoD/backlog mismatch, no `delivery_feedback` | Propose fixes anyway; note logging gap for teamlead |

Read from the **target repo** (delivery project), not ai-sdlc-local-kit, unless the gap is profile/skill/policy (then edit ai-sdlc-local-kit `BACKLOG.md`).

### Scan steps

1. Open `.ai-task/decisions.jsonl` in the target repo (retro packet and factual report are indexes only).
2. Filter `phase == "cross"` and `choice == "delivery_feedback"`.
3. Also read **verify** rows with `override_verify_profile`, **verdict** choices `split` / `defer`, and **cross** rows with `mechanical_metadata_fix` (audit teamlead inline fixes: was each one truly mechanical?) — they often need product follow-up even without a formal `delivery_feedback` row.
4. For each hit, extract `task_ids`, `reason`, `signals`, `run_ids`; cross-check `.ai-task/state.json` runs and verify reports when present.
5. Map each observation to a gap type: **split**, **defer**, **Verify**, **DoR**, **scope**.

Optional CLI index (same window as retro):

```bash
ai-task decision analytics --since 30d --json
```

Use `entries` and `delivery` metrics as anchors; the journal narrative in `reason` is primary.

### Output format (gap list + suggested tasks)

Send teamlead or append to retro report:

```markdown
| task_id | gap type | observation | suggested fix |
|---------|----------|-------------|---------------|
| TEST-001 | Verify | Task Context implies Playwright; backlog had node-full | Set Verify: web-e2e or split E2E child |
| TASK-012 | split | DoD mixes API + UI in one M task | sdlc-backlog-add: API child, UI child |
| TASK-020 | DoR | Missing UI surface name for web-e2e | Add surface to Task Context; extend DoR UI gate |
```

Then apply fixes per user scope:

- **Target repo** `BACKLOG.md` for delivery tasks in that project.
- **ai-sdlc-local-kit** `BACKLOG.md` for profile skills, CLI policy, or retro improvement tasks.

Use **sdlc-backlog-add** for new children; edit parent blocks for splits/deferrals (`- [~]` + reason); update the DoR table in this skill when the gap is systemic (repeat across tasks).

### Example: two UI test tasks (Playwright vs Verify)

In one retro, `TEST-001` and `TEST-002` had **failed verify runs** while formal `rework_rate` stayed 0 (implicit retries). Task Context described browser/UI work (Playwright path), but backlog blocks had **`Verify: node-full`** (unit/npm only). Teamlead overrode at runtime to **`node-web`** — logged as `--phase verify --choice override_verify_profile`, not always as `delivery_feedback`.

Product should have caught this at **DoR**: web/UI Task Context plus wrong `Verify:` profile. After batch or retro handoff, your scan and gap list would propose:

1. Set `Verify: web-e2e` on TEST-001 and TEST-002, or split into unit child + E2E child tasks.
2. **Verify pass** on the next slice: any Task Context naming browser, Playwright, or a UI surface must have `Verify: web-e2e` or an explicit override note in Task Context.
3. If a `delivery_feedback` row exists, cite it in the gap list; if missing but verify override + failed runs tell the story, still fix backlog and optionally add a ai-sdlc-local-kit task for teamlead logging discipline (see **ai-task-retro** credibility check).

### Pairing with ai-task-retro Q&A

Load **ai-task-retro** for the interview; load **this skill** when retro scope includes product/DoR or when processing `delivery_feedback` rows.

| Retro step | Product action |
|------------|----------------|
| Q3 focus = product/DoR (or combo) | Run scan steps above on target `decisions.jsonl` |
| Analysis table: `delivery_feedback` missing but mismatch obvious | Gap list + backlog edits; mention product skill gap in retro summary |
| Deliverable: improvement tasks in ai-sdlc-local-kit | Convert systemic gaps to tasks of the profile backlog via **sdlc-backlog-add** |
| Forward-only default | Edit live `BACKLOG.md` only; do not rewrite target journal history |
| `decision log --phase cross --choice retro_complete` | Re-run DoR on next slice; hand off to **ai-task-teamlead** when gates pass |

One question per retro turn stays with **ai-task-retro**; you apply this section **after** scope is clear or when teamlead escalates with `delivery_feedback` mid-batch.

## Example user phrases

- «Сделай PRD из идеи …»
- «Разбей TECHSPEC на backlog»
- «Добавь задачу: …»
- «Переприоритизируй: сначала auth»
- «Готов ли TASK-012 к прогону?» (DoR + `ai-task dor`)
- «Product lead: discovery для фичи X»
