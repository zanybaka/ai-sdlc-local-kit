# ai-sdlc-local-kit

Skills, slash commands and tooling for running an AI-assisted development
cycle on your own machine with Claude Code, Cursor and Codex: one clone, linked
into `~/.claude` and `~/.cursor`, so the same skills work in every project
without copying files around.

Start with the [overview](docs/overview.md): what the parts are, how a task goes
from an idea to a merged change, and where each skill fits. [SETUP.md](SETUP.md)
links a clone into your profile.

## What is inside

| Folder | Role |
|--------|------|
| `skills/` | Agent skills (`*/SKILL.md`) for Claude Code and Cursor. |
| `cursor-commands/` | Cursor slash commands, linked at `~/.cursor/commands`. |
| `context/` | `AGENTS.md`, the shared policy for Cursor, Claude Code and Codex, and `CLAUDE.md`. |
| `bin/ai-task`, `scripts/ai_task/` | The `ai-task` CLI: runs backlog tasks through Claude Code, Cursor or Codex in separate worktrees and records each run. |
| `scripts/link-*`, `scripts/sync-*` | Link a clone into `~/.claude` and `~/.cursor`; pull third-party packs. |
| `docs/` | How the parts work: the [overview](docs/overview.md), the [threat model](docs/threat-model.md), [connecting external skills](docs/external-skills.md) and the reference docs. |

Third-party skill packs are not vendored here. `third-party-skills.json` lists
their upstream repositories, and `scripts/sync-third-party-skills.sh` pulls them;
see [docs/external-skills.md](docs/external-skills.md).

## Optional parts the texts mention

Some docs and skills mention parts that this kit does not contain. The kit works
without them, and a mention is not a broken step:

- a test suite (`tests/`): a test name in a doc says how a behavior is guarded,
  not a command you can run here;
- a pre-push privacy scan, a maintenance audit script, a lint gate and a
  CI-polling hook for Claude Code;
- skills for a pipeline that runs tasks from GitHub issues on a build host
  (`ai-wave-*`), host setup skills (`infra-*`) and a web UI design skill
  (`dev-web-ui-design`);
- architecture decision records (ADRs), task reports and a backlog.

Skills such as `ai-task-retro` call your clone "the profile repository" and file
improvement tasks into its `BACKLOG.md`. Create that backlog with the
`sdlc-backlog-add` skill when you first need it.

## Slides

`docs/ai-sdlc-overview.build.js` is a short deck about the approach, in Russian.
`scripts/build-decks.sh` builds it into `docs/ai-sdlc-overview.pptx` and `.pdf`
(Node.js and LibreOffice needed). A release may carry the PDF as a download.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues are welcome, and an accepted pull
request comes into the next release with credit to you.

## License

MIT, see [LICENSE](LICENSE).
