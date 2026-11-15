# External skills

This kit ships only its own skills. Skills from other authors stay in their
upstream repositories, and the kit pulls them onto your machine: you get the
author's current version under the author's license, and this repository never
redistributes someone else's files.

## Connect a skill pack

1. Add the pack to `third-party-skills.json`:

   ```json
   {
     "path": "third_party/<pack-name>",
     "repo": "https://github.com/<owner>/<repo>",
     "skillPaths": ["skills/<skill-name>"]
   }
   ```

   `skillPaths` is optional. Without it the link script takes every folder with
   a `SKILL.md` from the pack's `skills/`, `.agents/skills/` or root. An entry
   may also be `{"path": ".", "name": "<skill-name>"}`
   when the whole repository is one skill.

2. Run the sync script:

   ```bash
   ./scripts/sync-third-party-skills.sh
   ```

   On Windows:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-third-party-skills.ps1
   ```

   The script adds the pack as a git submodule under `third_party/`, links its
   skills into `skills/` and, through the profile links, into `~/.claude/skills`
   and `~/.cursor/skills`. Add `--remote` to move every pack to its upstream head.

3. Commit `third-party-skills.json` and `.gitmodules` in your fork.

Packs that install through their own CLI go into the `installers` list of the
same file. The sync script runs such an installer when its CLI is on `PATH`;
with `--install-tools` it first installs a missing Python CLI into a virtualenv
under `~/.venv/`.

## Change an external skill for yourself

The link script never overwrites a real folder in `skills/`. To change an
external skill, for example to narrow its description so it triggers less often,
copy the upstream folder into `skills/<skill-name>/`, edit it, and keep the
upstream license file next to it. Sync then prints
`WARN: refusing to overwrite local skill` for that name, and your copy wins.

Keep such a copy in your fork only if its license allows that. A copy stops
receiving upstream updates, so note at the top of its `SKILL.md` what you changed
and why.
