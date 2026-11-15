# Skill authoring

Conventions for first-party skills in `skills/` that go beyond the base format
(Claude Code skills follow the [Agent Skills](https://agentskills.io) open
standard: `name` and `description` frontmatter, body loaded on activation).
One normative home per topic - register new sections in the doc-ownership map
in [ai-task.md](ai-task.md).

## What does not go into a skill

A shared skill describes the process: what to open, what to run, what to record, when a
finding blocks a verdict. Values that another layer owns stay with that owner, and the skill
says where to read them instead of copying them.

- **Values of a foreign layer.** Sizes, thresholds and tokens of a design system, reference
  screen sizes, paths to files of a concrete application, names of other repositories and
  hosts. A copy turns one repository's case into a rule for every repository, and it drifts
  from its owner on the owner's next change.
- **Where the skill sends the reader instead.** The task or the epic (`Done-when:`, the
  DoD), the design system the repository vendors (its rules file for
  agents), the repository's own `AGENTS.override.md` or product documents. When none of
  them holds the value, the skill tells the session to say so and record the missing
  contract as a finding, not to fall back to a number written in the skill.
- **Case write-ups.** A case may quote numbers, file names and repositories as evidence, in
  a paragraph of its own that starts with the case label: `Случай` in Russian text,
  `The case` in English text. The numbers there are evidence, not a rule; the rule next to
  it is phrased without them, with placeholders such as `<размер окна>` where a form is
  needed.
- **Where it comes from.** Improvement tasks are written from a fresh case, so their text
  mixes evidence and rule. One improvement issue carried an application's audit file,
  two screen sizes and a pixel width, and the follow-up tasks copied them into the rules of
  two acceptance skills. Keep the two apart in the task:
  "Улики" (evidence) and "Правило" (rule), and let the DoD refer only to the rule.
- **Validation.** `tests/test_skill_layering.py` walks every own `skills/*/SKILL.md`
  (synced third-party copies excluded) and fails on screen sizes like `NNNxNNN`, pixel
  values, `--uk-*` token names and paths to application code files outside case
  paragraphs. A value that belongs to the skill itself (an icon size in an icon skill, a
  script the skill ships) goes into the test's `ALLOWED` table with its reason; an entry
  whose value disappears from the skill fails the test, so the table cannot go stale.

## The listing text: cap and no task ids

Claude Code shows every skill in a listing that loads in each session on each machine. The
`description` and `when_to_use` of one skill share a cap of 1536 characters there (Claude Code
docs, "Skill descriptions are cut short"), and the text past it never reaches the model. The
trigger phrases usually stand last, so an overlong description loses exactly the part that
makes the model pick the skill.

- **What goes into the description.** What the skill does, when to use it, its boundaries
  and its triggers. Task ids, issue numbers and ADR numbers stay out: they cost tokens in
  every session and say nothing about when to use the skill.
- **Where the ids go.** Into the body, which loads only when the skill runs. A skill
  keeps them in a line `Происхождение:` or `Origin:` under its heading.
- **Validation.** `tests/test_skill_frontmatter.py` sums `description` and `when_to_use` of
  every own skill (folded `>-` blocks joined into one line) and fails over the cap, and it
  fails on an id such as `ABC-221`, `owner/repo#17` or `ADR 3` in either field.
