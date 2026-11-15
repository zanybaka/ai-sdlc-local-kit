# Setup (this repo on a machine)

Do this once per machine. After it, Claude Code and Cursor load the skills, commands and hooks of this clone in every project, and the `ai-task` command works from any folder. To give a project the shared rules after that, continue with [SETUP_NEW_PROJECT.md](SETUP_NEW_PROJECT.md).

Before you start:

- You need `git`, `python3` and the GitHub CLI `gh`, logged in with `gh auth login`. `scripts/propagate-agents.sh` asks `gh` whether a project is private, and without an answer it treats every project as public, so a private project's copy of the rules is never committed.

## Quickstart

macOS or Linux, from any folder:

```bash
git clone https://github.com/zanybaka/ai-sdlc-local-kit.git && cd ai-sdlc-local-kit
./scripts/link-symbolic-folders.sh
./scripts/sync-third-party-skills.sh --install-tools
scripts/install-identity-guard.sh
export PATH="$HOME/.local/bin:$PATH"
```

The first script links your profile folders to this clone (the table below lists them). The second fills the `third_party/` submodules and links those packs into `skills/`. With `--install-tools` it also installs the command-line tools some packs declare in `third-party-skills.json`: today that is the `gradio` package from PyPI into its own virtual environment, followed by the pack's installer. The third installs the [global identity guard](#global-identity-guard-every-github-repository), which protects every GitHub repository on the machine. A plain clone is enough, because the sync script initializes the submodules. Put the `PATH` line into `~/.zshrc` or `~/.bashrc` if `ai-task` is not found in a new terminal.

Windows, from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\link-symbolic-folders.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-third-party-skills.ps1 -InstallTools
```

Check the result. Each line has to behave as its comment says:

```bash
ls -la ~/.claude/skills ~/.claude/CLAUDE.md ~/.cursor/commands   # links into this clone
find skills -type l ! -exec test -e {} \; -print                  # prints nothing
ai-task --help                                                     # usage text, not "command not found"
```

The profile uses symbolic links rather than Claude Code plugins: one working copy serves Claude Code and Cursor at once and an edit takes effect immediately, while a plugin serves only Claude Code and adds a prefix to skill names.

## What the link script sets up

The script creates any missing folder of the clone, links the profile folders to it and moves a real folder that was in the way to a `.bak.<date>` name. Then it registers the Claude Code hooks in `~/.claude/settings.json`, merged into the entries you already have (see [Claude Code hooks](#claude-code-hooks)), registers two of them for Codex in `~/.codex/hooks.json` and has Codex trust them (see [The same hooks in Codex](#the-same-hooks-in-codex)), and gives Codex one link per skill in `~/.agents/skills` (see [Codex](#codex)). Running it again changes nothing. Run it again after you move the clone.

| Link | Target in this clone | Who reads it |
|------|----------------------|--------------|
| `~/.claude/skills` | `skills/` | Claude Code |
| `~/.claude/CLAUDE.md` | `context/CLAUDE.md` | Claude Code, as the global context of every session |
| `~/.claude/hooks` | `hooks/` | Claude Code, through the entries the script adds to `~/.claude/settings.json` (see [Claude Code hooks](#claude-code-hooks)), and Codex through `~/.codex/hooks.json` |
| `~/.claude/context` | `context/` | tools that read the shared files from the profile |
| `~/.cursor/skills` | `skills/` | Cursor |
| `~/.agents/skills/<name>`, one per skill | `~/.claude/skills/<name>` | Codex. Other entries of that folder stay as they are, see [Codex](#codex) |
| `~/.cursor/commands` | `cursor-commands/` | Cursor slash commands such as `/make-prd`, in every workspace including a new empty folder |
| `~/.cursor/context` | `context/` | tools that read the shared files from the profile |
| `~/.cursor/rules` | `cursor-rules/shared/` | profile-wide Cursor rules. The folder is empty |
| `AGENTS.md` in the clone root | `context/AGENTS.md` | agents working on this repository, which reads its own canon like any project. The link is in `.gitignore` |
| `~/.local/bin/ai-task` | `bin/ai-task` | your shell. On Windows the script writes `ai-task.cmd`, which calls `scripts/ai-task.ps1` |

Claude Code and Cursor take the rules of a project from that project's root `AGENTS.md`, a copy of `context/AGENTS.md` that [SETUP_NEW_PROJECT.md](SETUP_NEW_PROJECT.md) puts there. The shared writing rule is part of that file, so Cursor needs no User Rules line for it. Add a User Rules line such as `@~/.cursor/rules/<your-rule>.mdc` only if you put a Cursor-only rule into `cursor-rules/shared/`, and use an absolute path if your Cursor build does not expand `~` there.

### Codex

Codex reads the project's root `AGENTS.md` by itself too. In a repository that also has an `AGENTS.override.md`, Codex reads only the override, and the first line of every override sends the agent to open `AGENTS.md`.

Codex takes user skills from `~/.agents/skills` and follows links there. Other tools install their own skills into the same folder, so the link script runs `scripts/link-codex-skills.py`, which gives every skill of this clone its own link `~/.agents/skills/<name>` pointing at `~/.claude/skills/<name>`. The script considers a link its own when the link leads into `~/.claude/skills` or into `skills/` of this clone. It creates missing links, repoints its own links with a wrong target and removes its own links whose skill is gone. A folder, a file or a link to anywhere else stays as it is, even under the name of one of our skills, and the script names it in its output, because Codex then loads that entry instead of ours. A copy of one of our skills left by hand in `~/.codex/skills/<name>`, the older Codex folder, would load next to the link and drift from the source, so the script moves it to `~/.codex/skills.bak.<date>/`. `python3 scripts/link-codex-skills.py --dry-run` prints what it would change. The sync script of third-party skills runs it too, so pack skills reach Codex as soon as their submodules are filled. Codex shows some pack skills with a prefix of the pack, such as `modern-python:modern-python`. `codex debug prompt-input </dev/null` prints the skill list Codex gives the model.

To use Codex as an `ai-task` worker, follow "Native Codex CLI" in [docs/ai-task.md](docs/ai-task.md). Codex loads instruction files only up to `project_doc_max_bytes`, 32768 bytes by default, and cuts the rest. That section gives the larger value the `ai-task` policy passes to its Codex workers and the same setting for an interactive Codex in `~/.codex/config.toml`. Set it before a repository's override grows past the default.

## Keeping a second machine in sync

Two clones of this repository share the remote but not the machine-local files: the root `AGENTS.md` link, the Codex links in `~/.agents/skills`, the identity guard copy in your global hooks folder and `.venv`. A `git pull` brings new rules and skills, but it does not run the link scripts, so a skill that was added or moved upstream stays invisible until you relink. Run this on the second machine whenever you sit down at it:

```bash
git pull
./scripts/link-symbolic-folders.sh
./scripts/sync-third-party-skills.sh
scripts/install-identity-guard.sh
```

The link script points the profile at the pulled tree, and after a skill rename upstream it replaces the old-name Codex links with the new ones. The sync script links new or moved third-party skills. The installer copies the guard rather than linking it, so a fixed guard reaches your hooks folder only when you run it again.

## Third-party skills

External skill packs are listed in `third-party-skills.json` and live as submodules under `third_party/`. The sync script initializes the submodules, installs the declared Python tools into `~/.venv/<repo-name>/` virtual environments when you pass `--install-tools` (`-InstallTools` on Windows), runs the declared installers and links the skills into `skills/`. `AI_SDLC_KIT_TOOL_VENV_ROOT` moves the virtual environments elsewhere. To refresh the submodules from upstream before relinking:

```bash
./scripts/sync-third-party-skills.sh --remote
```

`--remote` pulls the upstream head of every pack, which nobody has reviewed yet, and changes the submodule pointers tracked in git. Read the resulting `.gitmodules` and submodule diff before you commit it.

The kit keeps no copies of other authors' skills: every pack comes from its upstream repository. To change an external skill for yourself, see [docs/external-skills.md](docs/external-skills.md).

### Playwright browser automation (`playwright-skill`)

The pack comes from [lackeyjb/playwright-skill](https://github.com/lackeyjb/playwright-skill) into `third_party/playwright-skill`. Agents load `skills/playwright-skill` from the profile only, and `ai-task` never installs Playwright into a project. To use it:

1. Run `./scripts/sync-third-party-skills.sh` so the submodule is filled.
2. Install the browsers in the project where you run the end-to-end tests, usually `npx playwright install` from that project's `package.json`.
3. Set the `web-e2e` verify profile in that project's `.ai-task/policies/default.toml`, see [docs/ai-task-verify.md](docs/ai-task-verify.md).

### Retro skills (kaizen, lessons-learned)

The `ai-task-retro` skill uses two upstream packs, which the sync script pulls like any other pack of `third-party-skills.json`.

| Skill | Upstream |
|--------------|----------|
| `skills/kaizen` | [NeoLabHQ/context-engineering-kit](https://github.com/NeoLabHQ/context-engineering-kit) (`plugins/kaizen/skills/kaizen`) |
| `skills/lessons-learned` | [aplaceforallmystuff/claude-lessons-learned](https://github.com/aplaceforallmystuff/claude-lessons-learned) |

For an analysis of Claude Code session transcripts, see [agent-retro](https://github.com/giannimassi/agent-retro) in [docs/ai-task-decisions.md](docs/ai-task-decisions.md). It is not a submodule here.

## Claude Code hooks

The link script makes the hooks available as `~/.claude/hooks` and then registers them in `~/.claude/settings.json` through `scripts/register-claude-hooks.py`. You do not edit the file by hand. This kit ships one hook, `telegram-notify.py`. The registrars also know a lint gate (`lint-gate.py`) and a guard against CI polling loops (`no-expensive-ci-polling.py`), which this kit does not ship, and skip them while their files are missing from `~/.claude/hooks`.

| Hook | Event | When it fails | What it does |
|------|-------|---------------|--------------|
| `telegram-notify.py` | `Notification` and `Stop` | lets the session go on (timeout 30 s) | Sends a Telegram message when Claude Code shows a notification, and when a turn ends in a session that has changed at least one file. A notification and the stop of the same turn within 25 seconds give one message. Registered only when its config exists, see below |

The registrar only adds and updates. Every key, event and hook you already have stays where it is. A hook of this repository that is already registered, found by its file name in a command of the same event, keeps its command and extra keys such as `statusMessage`; the script sets only `timeout` and `onFailure`. A hook whose file is missing from `~/.claude/hooks` is skipped. Before a write it saves the old file as `settings.json.bak.<date>`, and a run with nothing to add does not touch the file. A file that is not valid JSON, or whose `hooks` has an unexpected shape, is left as it was, and the link script prints a warning.

To see the change before it is made, run the registrar alone:

```bash
python3 scripts/register-claude-hooks.py --dry-run
```

The resulting entries look like this (the Telegram ones only with its config):

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [
        { "type": "command", "command": "python3 \"$HOME/.claude/hooks/telegram-notify.py\"", "timeout": 30 } ] }
    ],
    "Notification": [
      { "hooks": [{ "type": "command", "command": "python3 \"$HOME/.claude/hooks/telegram-notify.py\"", "timeout": 30 }] }
    ]
  }
}
```

The Telegram hook reads the bot token from `~/.claude/channels/telegram/.env` (`TELEGRAM_BOT_TOKEN=...`) and the chat id from the first entry of `allowFrom` in `~/.claude/channels/telegram/access.json`. Install the Telegram channel plugin of Claude Code and run its pairing command, `/telegram:access` in a Claude Code terminal: it writes both files. Then run the link script again, and it registers the hook.

The project Stop hook below stays in the project file `.claude/settings.json` and is never copied into your user settings.

### The same hooks in Codex

In the same step the link script runs `scripts/register-codex-hooks.py`, which registers the lint gate and the CI-polling guard for Codex in `~/.codex/hooks.json` (or `$CODEX_HOME/hooks.json`) and has Codex trust them. Neither hook ships in this kit, so on a fresh clone it registers nothing. The merge works as for Claude: your entries stay, ours are found by file name, and only `timeout` is set. `--dry-run` prints the change of `hooks.json` and asks Codex nothing:

```bash
python3 scripts/register-codex-hooks.py --dry-run
```

### The project Stop hook of this repository

This repository also commits a project hook in `.claude/settings.json`. It matters only in a clone that keeps its own `BACKLOG.md` and `CHANGELOG.md`; without them it has nothing to check. At the end of every Claude Code turn here it runs `scripts/check-delivery-artifacts.py --stop-hook`, which catches a task closed with `[x]` that has no entry in `CHANGELOG.md`.

The hook compares the backlog files with the last pushed commit (the upstream of the branch, else `origin/main`), so it sees a task closed in unpushed commits and in the working tree. When such a task has no entry, it returns a block decision with the reason, and the agent adds the entry and goes on.

It judges only the task ids that the session named in its own tool calls, so a session that shares the checkout with another one is not blocked for the other's work. It lets the turn end when the harness says a Stop hook is already active, so it reminds once and never loops, and any other failure (no git, broken input) lets the turn end too. Local files such as `.claude/settings.local.json` and `.claude/worktrees/` stay untracked.

## Global identity guard (every GitHub repository)

The identity guard is a global pre-push hook for every repository on the machine. On a push to a `github.com` remote it searches the pushed tree for the strings of your denylist, such as an employer or client name, and blocks the push on a match. A leaked identity on a public remote cannot be taken back, so the guard blocks rather than warns.

The quickstart installs it:

```bash
scripts/install-identity-guard.sh
```

The installer copies `scripts/git-hooks/identity-guard-pre-push.sh` to `pre-push` in your global hooks folder, by default `~/.config/git/hooks/pre-push`. It creates `~/.config/git/identity-denylist.txt` from the placeholder file `scripts/git-hooks/identity-denylist.example.txt` when you have none. It sets the global `core.hooksPath` only when it is unset, and otherwise installs into the folder that value names. Running it again changes nothing when the guard is current and updates an older copy of it. When the folder already holds a different `pre-push`, the installer refuses and exits 1. Merge the two hooks by hand. The guard runs only each repository's own `.git/hooks/pre-push` after its check, so a global hook you move aside stops running unless you put it there. Fill the denylist with your real strings, one per line. The real denylist is never committed.

After its check the guard runs the repository's own `.git/hooks/pre-push`, found through the common git folder, and returns its exit code.

A global `core.hooksPath` has a side effect in every repository on the machine: git then ignores `.git/hooks`. The guard hands over only `pre-push`, so repository-local `pre-commit` or `commit-msg` hooks stop running. A repository that needs them sets them up in the global hooks folder, or uses a hook manager that writes there. `IDENTITY_GUARD=warn git push` turns a match into a warning, and `git push --no-verify` skips all hooks. `bash scripts/git-hooks/identity-guard-selftest.sh` checks the guard in a temporary home folder and never touches your real configuration.

## The ai-task CLI

`ai-task` runs backlog tasks in separate worktrees through Claude Code, Codex or Cursor and records every run. A project uses it only after you initialize `.ai-task` there. Plain `BACKLOG.md`, `AGENTS.md`, Cursor commands and Claude Code skills work without it.

The link script installed the shim. Check it:

```bash
ai-task --help
```

If the shell answers `command not found`, add `~/.local/bin` to PATH as in the quickstart. Without PATH you can run `scripts/ai-task.sh --help` from the clone.

In a project (not in ai-sdlc-local-kit) run `ai-task init` once in its root, or use the `ai-task-init` skill. That creates `.ai-task/` in the project only, and the CLI itself stays in this clone. [docs/ai-task.md](docs/ai-task.md) covers the teamlead workflow, the backends and the command reference.
