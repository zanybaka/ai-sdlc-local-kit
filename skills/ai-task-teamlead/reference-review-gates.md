# Teamlead reference — W4 review gates, release contract, W6 product handoff

Companion to `SKILL.md` (ai-task-teamlead); loaded on demand. Normative.

## UI-interaction review template (W4, React/UI/browser tasks)

Named review template — formerly the improvised «UI interaction & effect-deps» checklist; **ai-task-reviewer** mirrors it in pass 2. When the task touches hooks, effects, popups, SVG/canvas interactions, network-gated UI, or persisted view state, **review must catch what verify cannot**. Green `tsc` / unit tests do not replace this pass.

| Check | Pass when |
|-------|-----------|
| **Effect-dep stability** | No fresh object/array/function literals in `useEffect` / `useLayoutEffect` deps unless intentionally stable; prefer stable refs (`useCallback` / `useMemo`) or primitive fields, not whole popup/controller objects that change every render |
| **Fire-on-action-not-on-mount** | Pulse/nonce effects fire on the user action, not from the stale mount value, and re-fire on repeat actions (a pulse hook that is 0 on mount and +1 after it; a reviewer can prove the guard with a planted violation) |
| **Shared-state brushing** | Linked hover/spotlight surfaces (chips, legend rows, zones) reuse **one shared state**, not a forked copy, so hovering one lights the others (a second spotlight task reuses the state of the first instead of forking it) |
| **Persistence keys** | Persisted view state restores as a **coherent pair** (camera + content together), uses per-mode storage keys, and writes only while the owning mode is active so leaving does not overwrite the memory; explicit deep-links still win |
| **Interaction paths** | Click/open/close flows the profile cannot run (SVG nodes, canvas, drag) are exercised in review (manual reasoning on diff, Playwright if available, or explicit gap note) |
| **Verify coverage gap** | If no automated test covers the interaction, log **`decision log --phase review`** before `verdict approve` documenting the gap and what you checked manually |

**Worked example (effect deps):** a run added popup **objects** to a `useEffect` dependency array, but the popup hook returned a new object literal each render, so the effect ran every render and dismissed popups as soon as they opened. `tsc -b` and `vitest` stayed green (preview harness cannot click SVG). Review caught unstable deps; verify alone would have shipped the bug. Folded-only verdict without a `phase=review` row is an anti-pattern — log review when verify cannot exercise the path.

**Worked example (persistence keys):** entering a tree view restored the camera from localStorage while the collapse set was force-reset to the default, so the restored camera pointed at content that was no longer expanded and only one card remained, off-screen. jsdom cannot observe an off-screen camera (no real layout); review passed it by tracing every collapse entry site and the persisted-pair precedence, logged as `approve_manual_interaction_check`.

Load **ai-task-reviewer** for the structured pass; teamlead still owns the checklist before approve.


## Real-browser evidence gate (W4 review — blocking)

When the change **gates on a cross-origin resource, network-status visibility, or a browser-only interaction** (pointer capture, hover, SVG click, real layout/geometry), **mocked-fetch/jsdom green is insufficient evidence** — the harness cannot observe the very thing the change gates on:

| Trigger in the diff | Why mocked green lies |
|---------------------|-----------------------|
| UI state decided by a fetch/XHR to **another origin** | CORS hides the cross-origin response status: `res.status` is unreadable, the real fetch throws and the gate never trips — while stubbed fetch in jsdom returns the 401 the code expects |
| Behavior keyed on a **response status** (401/403 gate, health probe) | The mock asserts the code you wrote, not what the browser lets you observe |
| **Pointer capture, hover, drag, SVG/canvas click** | jsdom has no real hit-testing or pointer events |
| **Real layout/geometry** (off-screen checks, scroll-into-view, bounding boxes) | jsdom layout returns zeros; an off-screen camera looks fine |

Before `verdict approve`, review must include **one of**:

1. **Real-browser probe** — preview/Playwright run of the gated path (trigger the interaction, read console/network), or a minimal standalone probe in a real browser context: an **`Image()` load/error probe** for cross-origin media (image events are observable cross-origin even when fetch status is not), or a live `fetch` against the real origin reading the actual status. Cite the observed result in the review findings or decision row.
2. **Logged coverage-gap decision plus follow-up task** — `decision log --phase review --choice approve_with_coverage_gap` naming exactly what was not exercised and why approve is still safe, **and** a follow-up task filed via product/sdlc-backlog-add to close the gap. A silent approve on mocked green is not an option.

**Worked example (an avatar 401 gate):** review praised an avatar «session-wide 401 gate» as well-built and tested, but mocked fetch + jsdom hid two bugs: `<img>`s rendered optimistically before the probe resolved (one request per avatar), and the `fetch(..., {method: 'HEAD'})` probe was CORS-blind cross-origin — `res.status === 401` was never readable, so the gate never tripped. The owner found the 401 console flood by running the real app, and the decision was graded bad. The follow-up fix replaced the probe with a single hidden `Image()` probe. The same window proved the compensation works when deliberate: nine review decisions (`ui_interaction_review_pass`, `approve_manual_interaction_check`, `approve_with_coverage_gap`, …) manually covered behavior jsdom cannot exercise, and one of them caught a missing CHANGELOG entry — this gate makes that compensation mandatory instead of improvised.


## Run release contract (W4, every successful task)

Use **one** contract so headless runs do not disagree about who commits or who marks `[x]` (without it, runs of one phase behaved differently).

| Role | Owns on success |
|------|-----------------|
| **Implement run** (agent in worktree or main tree) | Code and docs for the task; mark **`- [x]`** for this task with a **`Progress:`** line under its title; `CHANGELOG.md` line for the task; `tasks/<TASK-ID>.md` only when there is something to keep beyond them (measurements, a live probe log, the reason for a decision). May leave changes **uncommitted**. |
| **Teamlead W4 release** | `verify` → `review` → `verdict approve` → **`git commit`** with the task id in the message → confirm `[x]` + Progress line exist → `ai-task complete <run-id>` (and `--remove-worktree` when used). |

Do not let the implement run commit **and** the teamlead commit the same delivery without coordination. Do not approve while the task is still `- [ ]` or has no Progress line (`ai-task complete` names both gaps). A task report is a gap only when the task's DoD asks for one; then use `complete --require-report`.


## DoD evidence rules (W4 approve, W5 gate, recover-killed-run)

An approve verdict rests on **enumerated evidence**, not on summary claims. Three rules, each from a real miss:

| Rule | Pass when |
|------|-----------|
| **Anchored entry assert** (CHANGELOG / registry / backlog DoD items) | The check matches the **dedicated entry line at line start** and you read the matched line — e.g. `grep -E '^- \*\*WEB-119' CHANGELOG.md` for `- **WEB-119**: …`-style changelogs (`^- \*\*ID:` shape; adapt the anchor to the repo's entry format, e.g. `^- WEB-119:` for unbolded entries) |
| **Recovered-run evidence list** | Approving work from a killed/orphaned run (`needs_recovery`, dead pid, supervisor kill) cites a **per-DoD-item evidence list**: every DoD item mapped to a `file:line` or a command plus its output |
| **Read-first shared-file merge** | Any helper script that merges run output into a shared file (CHANGELOG.md, BACKLOG.md, id registry) **reads the file fully before opening it for write**, and you re-check that pre-merge entries survived |

Known traps behind each rule:

- **Substring counting is a false-positive trap.** A task was approved on `grep -c <ID> CHANGELOG.md`: the count matched cross-references inside another task's entry while the dedicated entry was missing, and the decision was re-graded bad. A nonzero substring count anywhere in the file is not evidence the dedicated entry exists.
- **«Verifiably complete» is not approvable.** A killed run loses the premise that the agent finished and self-checked its DoD list, so a blanket completeness claim (yours or the log's) carries no evidence. No enumerated per-item list → verdict `rework` or a fresh `run`, not approve.
- **Truncate-before-read empties the file.** `open(p, "w")` truncates immediately; a lazy read generator over the same path then iterates an empty file — one CHANGELOG merge emptied CHANGELOG.md exactly this way. Materialize first (`content = p.read_text()`), then open for write.


## Sibling tasks must close the class (W4)

When a task's context says it is a **sibling / regression / "root cause" of** an earlier bug, a local point-fix is **not Done** — the same class recurs (in one delivery phase 7–8 of 8 bugs were siblings of already-fixed bugs while `rework_rate` stayed ~0). Verdict `rework`/`split` unless the change also adds a **class-guard** that makes the whole class non-recurring:

| Class signal | Class-guard the fix should add |
|--------------|-------------------------------|
| Nonce/pulse fired-on-mount, or missing re-fire pulse | a shared primitive + lint, not a per-effect patch |
| Stale state not cleared on navigation | one reset over a transient-state registry, not one more variable |
| Hand-maintained map drift from a source-of-truth | a sync-test vs the source (one map, then sweep the rest) |
| Raw comparison bypassing normalization/resolver | a guard or lint banning the raw form |
| Inline clone of a shared component | a lint flagging a local component shadowing a shared one |

Good examples: one fix generalized a pulse to all 9 modes of the view; another added a drift sync-test. Point-fix anti-pattern: a fix of one more variable in the same hash-change handler as an earlier bug, so the same class was fixed twice, one phase apart. **Before closing a phase, run a sibling sweep** (fan-out grep over recently-fixed classes) and file un-guarded siblings as new tasks; this also keeps the recurrence metric honest (measure over the whole backlog, not a hand-picked slice).


## W6 must hand off to product (required)

Run this order every time:

1. `decision log --phase cross --choice delivery_feedback`
2. Load **ai-task-product**
3. Wait for backlog edits, then log `product_response` and run `dor` or `plan --strict`

Trigger handoff when any of these happens:

1. Verify failed or was skipped and task DoD implies another profile (for example browser/UI task but backlog says only `Verify: node-web`).
2. A predecessor run is `failed` or `needs_review` without approve, but a dependent task is now eligible or already marked `[x]`.
3. `dor` or `plan --strict` shows a gap in the next wave slice.
4. Verdict is `split`, or scope is clearly outside the current task block.
5. Teamlead is about to patch backlog metadata or policy to make delivery pass instead of fixing task definition (mass `Verify:` swaps belong to product).
6. **`decision analytics` SLO gate `slo_high_rework_rate` fires** — high rework rate signals backlog or DoR quality issue that product must fix before next wave.
7. `Size:` is not S/M/L, or a DoR JSON row includes `action: split_required`.
8. A `Size: L` run stalls and the task scope looks like an XL unit (whole phase, multiple independent surfaces, or several verify profiles). Log gap type **oversized** and hand off to product for split.
9. **DoR rejects a metadata field value that needs judgment** (which S/M/L bucket actually fits the scope, `Verify:` profile semantics, a priority change, a dependency that should exist but does not). Log `delivery_feedback`, hand to product. **Exception — mechanical, validator-named fixes** (normalizing an out-of-range Size bucket such as `XS`→`S` when scope is plainly small, task id format renames, removing dead `Depends on:` ids): apply inline with one mandatory `decision log --phase cross --choice mechanical_metadata_fix` row naming task id + field + old→new, then rerun `dor`.

Teamlead does not make judgment-bearing metadata edits for these trigger cases. Silently patching metadata to force delivery remains forbidden — the `mechanical_metadata_fix` journal row is what makes an inline mechanical fix non-silent.

**Worked example (Size XS):** `dor` flags four tasks with `Size: XS` (validator allows S/M/L only) — a mechanical, validator-named gap. Right (inline fast path): fix each `Size:` line, then log once:

```bash
ai-task decision log --phase cross --choice mechanical_metadata_fix \
  --reason "DoR: Size XS invalid (validator names S/M/L); normalized Size XS→S on four small skill/doc tasks" \
  --task-ids TASK-A,TASK-B,TASK-C,TASK-D
```

Then rerun `dor` or `plan --strict`. Wrong: patching the lines with **no journal row** (silent), or using this path for a judgment call (the right bucket is genuinely unclear, the task looks XL+, `Verify:` semantics) — those still go `delivery_feedback` → product, who logs `product_response` after the fix.


## Anti-pattern to avoid

Do not run one chat wearing teamlead + implementer + product with zero `delivery_feedback` rows. In the reference case of this anti-pattern, verify and scope signals happened over three test tasks, but `inbox.jsonl` stayed empty and cross-phase handoff never occurred.

When auto-stubs appear (`verify_failed`, `retry_run`), treat them as prompts to enrich the row and open product handoff when DoD/profile mismatch is present.


## Destructive actions

Ask once before `stop` and before risky `cursor_auto` fallback on P0/P1 or risk-keyword tasks (per policy `ask_before_weaker_fallback_for_risky_tasks`). **Iterative ship:** no extra confirmation per wave if the user already asked to ship the backlog; still run **wave gate** (W5–W7) every time.

