# New project setup (shared AGENTS.md)

Use this after [SETUP.md](SETUP.md), once the ai-sdlc-local-kit clone is linked into your profile. Here you connect a project to the shared rules.

A project needs a copy of the shared `AGENTS.md`, and it may add an `AGENTS.override.md` with the rules of that one repository. `scripts/propagate-agents.sh` places the copy. In a public project it does not touch `.gitignore`, so add the line yourself, or a later `git add .` publishes the copy:

```bash
printf '/AGENTS.md\n' >> <project>/.gitignore
```

The project's root `AGENTS.md` is a real file, a copy of `ai-sdlc-local-kit/context/AGENTS.md`. Cursor, Claude Code and Codex all read the workspace-root `AGENTS.md` by themselves. The shared writing rule lives inside it, so a project needs no `.cursor/rules/*.mdc` and no links into ai-sdlc-local-kit.

Where the copy lives depends on the repository's visibility:

- **Private repository:** the copy is committed. Because it is a real file, it also works in cloud and mobile checkouts, where ai-sdlc-local-kit is absent.
- **Public repository:** the copy stays on your machine, `/AGENTS.md` is in `.gitignore`, and nothing commits it. The canon is not published there and has no short public version. A cloud session in a public repository runs without the canon.

`propagate-agents.sh` reads visibility with `gh repo view --json isPrivate`. Without an answer (no `gh`, no access, an origin outside GitHub) it treats the repository as public, as the canon requires. `AGENTS.override.md`, the file with the rules of one repository, is committed in both cases.

Run every command below from the ai-sdlc-local-kit root, the folder that contains `scripts/`.

## Connect or refresh one project

```bash
scripts/propagate-agents.sh <project>      # folder name (sibling of ai-sdlc-local-kit) or a path
```

The script creates `<project>/AGENTS.md` as a copy of the shared source, or reports "up to date" when it already matches. For a public repository it also prints `local copy only (...)` and warns when the copy is tracked or not ignored. Add the `.gitignore` line yourself. Running it again changes nothing that is already right.

## Refresh every connected project at once

After an edit of `context/AGENTS.md`, refresh all projects that already carry a copy:

```bash
scripts/propagate-agents.sh            # writes fresh copies and prints a diff per project, no git changes
scripts/propagate-agents.sh --check    # report only: which copies are stale, exit 1 if any
scripts/propagate-agents.sh --commit   # writes, then commits and pushes each private project
```

A public project is refreshed in every mode and never committed or pushed. The summary lists it after `local only (never committed):`.

The scan touches only projects that are already connected, whose `AGENTS.md` is a copy of the shared source. A project with no `AGENTS.md`, or with its own unrelated one, is left alone. In a real terminal the scan then offers to connect each unconnected git project (`connect <name>? [y/N]`); a non-interactive run only lists them. The single-project form above connects one explicitly.

### `--commit` safety

`--commit` checks every private project it would touch before it commits anything: each one has to be on its default branch, with no unpushed commits and a clean index. If one fails, the script lists the offenders and does nothing, so a sync never lands on your feature branch or carries unrelated local commits along.

## Taking a committed copy out of git in a public repository

A public repository whose copy was committed earlier still has `AGENTS.md` in git, and `propagate-agents.sh` warns about it. You move it out by hand, once per repository.

```bash
cd <project>
git switch main && git pull --ff-only
git rm --cached AGENTS.md          # the file stays on disk
printf '/AGENTS.md\n' >> .gitignore
git add .gitignore
git commit -m "chore: keep the shared AGENTS.md out of git"
git push
git check-ignore -q AGENTS.md && echo "ignored"
git ls-files --error-unmatch AGENTS.md 2>/dev/null || echo "not tracked"
```

Git history keeps every old version of the file, and anyone can still read it in earlier commits. That is accepted, because the canon is written for public readers. Purging the history would rewrite every commit of the repository and is not part of this migration.
