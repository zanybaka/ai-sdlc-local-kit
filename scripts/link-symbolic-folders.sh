#!/usr/bin/env bash
# Same layout as link-symbolic-folders.ps1: ~/.claude and ~/.cursor -> this repo,
# one link per skill in ~/.agents/skills for Codex, and the hooks registered
# for Claude Code and Codex.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
HOME="${HOME:?}"

link_dir() {
  local link="$1" target="$2"
  mkdir -p "$(dirname "$link")"
  if [[ -L "$link" ]] && [[ "$(readlink "$link")" == "$target" ]]; then
    echo "Already linked: $link"
    return 0
  fi
  if [[ -e "$link" || -L "$link" ]]; then
    if [[ -L "$link" ]]; then rm "$link"; else mv "$link" "${link}.bak.$(date +%Y%m%d_%H%M%S)"; fi
  fi
  ln -sfn "$target" "$link"
  echo "OK: $link -> $target"
}

link_file() {
  local link="$1" target="$2"
  mkdir -p "$(dirname "$link")"
  if [[ -L "$link" ]] && [[ "$(readlink "$link")" == "$target" ]]; then
    echo "Already linked: $link"
    return 0
  fi
  if [[ -e "$link" || -L "$link" ]]; then
    if [[ -L "$link" ]]; then rm "$link"; else mv "$link" "${link}.bak.$(date +%Y%m%d_%H%M%S)"; fi
  fi
  ln -sfn "$target" "$link"
  echo "OK: $link -> $target"
}

mkdir -p "$REPO/skills" "$REPO/context" "$REPO/cursor-rules/shared" "$REPO/cursor-commands" "$REPO/hooks"
mkdir -p "$HOME/.claude" "$HOME/.cursor"

# Optional context/PRD.md and context/TECHSPEC.md are not auto-created; add them by hand if needed.
for f in AGENTS.md CLAUDE.md; do
  if [[ ! -f "$REPO/context/$f" ]]; then
    printf '# %s\n\n' "$f" > "$REPO/context/$f"
    echo "Created: $REPO/context/$f"
  fi
done

link_dir "$HOME/.claude/skills"       "$REPO/skills"
link_dir "$HOME/.claude/context"      "$REPO/context"
link_dir "$HOME/.claude/hooks"        "$REPO/hooks"
link_dir "$HOME/.cursor/skills"       "$REPO/skills"
link_dir "$HOME/.cursor/context"      "$REPO/context"
link_dir "$HOME/.cursor/rules"        "$REPO/cursor-rules/shared"
link_dir "$HOME/.cursor/commands"     "$REPO/cursor-commands"

for x in global-docs global-rules; do
  p="$HOME/.cursor/$x"
  if [[ -L "$p" ]]; then rm "$p" && echo "Removed legacy: $p"; fi
done

if [[ -L "$HOME/.claude/AGENTS.md" ]]; then
  rm "$HOME/.claude/AGENTS.md"
  echo "Removed legacy: $HOME/.claude/AGENTS.md"
fi

link_file "$HOME/.claude/CLAUDE.md" "$REPO/context/CLAUDE.md"

install_ai_task_cli() {
  local local_bin="$HOME/.local/bin"
  local dest="$local_bin/ai-task"
  chmod +x "$REPO/bin/ai-task" "$REPO/scripts/ai-task.sh" 2>/dev/null || true
  mkdir -p "$local_bin"
  if [[ -L "$dest" ]] && [[ "$(readlink "$dest")" == "$REPO/bin/ai-task" ]]; then
    echo "Already linked: $dest"
  else
    if [[ -e "$dest" || -L "$dest" ]]; then
      if [[ -L "$dest" ]]; then rm "$dest"; else mv "$dest" "${dest}.bak.$(date +%Y%m%d_%H%M%S)"; fi
    fi
    ln -sfn "$REPO/bin/ai-task" "$dest"
    echo "OK: $dest -> $REPO/bin/ai-task"
  fi
  if command -v ai-task >/dev/null 2>&1; then
    echo "ai-task CLI: $(command -v ai-task)"
  else
    echo "ai-task CLI: installed at $dest (add to PATH if needed):"
    echo "  export PATH=\"$local_bin:\$PATH\""
  fi
}
install_ai_task_cli

# Link health check: warn about dangling symlinks under skills/. Targets differ by
# origin, so group by category and print the correct fix per group:
#   - third_party/* (uninitialized submodules) -> run sync-third-party-skills.sh
#   - ~/.agents/skills/* (corporate, pre-tooling) -> re-link with absolute target
#   - anything else -> generic re-link hint
check_dangling_skill_links() {
  local broken third_party corporate other link target resolved
  broken="$(find "$REPO/skills" -type l ! -exec test -e {} \; -print 2>/dev/null || true)"
  [[ -n "$broken" ]] || return 0
  third_party=""; corporate=""; other=""
  while IFS= read -r link; do
    [[ -n "$link" ]] || continue
    target="$(readlink "$link")"
    # Resolve a relative target against the link's own directory.
    case "$target" in
      /*) resolved="$target" ;;
      *)  resolved="$(dirname "$link")/$target" ;;
    esac
    case "$resolved" in
      "$REPO/third_party/"*|*/third_party/*)
        third_party="$third_party  $link -> $target"$'\n' ;;
      "$HOME/.agents/skills/"*)
        corporate="$corporate  $link -> $target"$'\n' ;;
      *)
        other="$other  $link -> $target"$'\n' ;;
    esac
  done <<< "$broken"

  echo ""
  echo "WARNING: dangling symlinks in $REPO/skills (these skills will NOT load):"
  if [[ -n "$third_party" ]]; then
    printf '%s' "$third_party"
    echo "  Fix: run ./scripts/sync-third-party-skills.sh [--install-tools]"
  fi
  if [[ -n "$corporate" ]]; then
    printf '%s' "$corporate"
    echo "  Fix with absolute targets, e.g.: ln -sfn \"\$HOME/.agents/skills/<name>\" \"$REPO/skills/<name>\""
  fi
  if [[ -n "$other" ]]; then
    printf '%s' "$other"
    echo "  Fix: re-create each link pointing at its real target."
  fi
}
check_dangling_skill_links

# the repo-root AGENTS.md is a symlink to context/AGENTS.md, so this
# repository loads its own canon like any consumer (Claude, Codex and Cursor read
# the workspace-root AGENTS.md). It stays in .gitignore. The target is relative,
# so the link survives a move of the clone. A symlink follows editor atomic writes
# (temp + rename), which used to detach the old hardlink. A regular
# file left from that hardlink is removed when it matches the canon and kept as a
# backup when it diverged.
link_root_agents() {
  local root_agents="$REPO/AGENTS.md" target="context/AGENTS.md"
  if [[ -L "$root_agents" ]] && [[ "$(readlink "$root_agents")" == "$target" ]]; then
    echo "Already linked: $root_agents"
    return 0
  fi
  if [[ -L "$root_agents" ]]; then
    rm "$root_agents"
  elif [[ -e "$root_agents" ]]; then
    if cmp -s "$root_agents" "$REPO/$target"; then
      rm "$root_agents"
      echo "Removed old copy of the canon: $root_agents"
    else
      local bak
      bak="$REPO/AGENTS.md.bak.$(date +%Y%m%d_%H%M%S)"
      mv "$root_agents" "$bak"
      echo "WARNING: $root_agents differed from $target; moved to $bak"
    fi
  fi
  ln -s "$target" "$root_agents"
  echo "OK: $root_agents -> $target"
}
link_root_agents

# register the hooks of ~/.claude/hooks in ~/.claude/settings.json.
# The registrar merges into the user's own entries and changes nothing on a
# second run; scripts/register-claude-hooks.py says which hook gets which
# onFailure and why. A failure here warns and leaves the file as it was.
# the same step registers two of these hooks for Codex in
# ~/.codex/hooks.json and has Codex trust them; scripts/register-codex-hooks.py
# says why trust is saved instead of bypassed.
register_hooks() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "WARNING: python3 not found; Claude Code and Codex hooks are not registered (see SETUP.md, Claude Code hooks)"
    return 0
  fi
  python3 "$REPO/scripts/register-claude-hooks.py" \
    || echo "WARNING: Claude Code hooks are not registered; fix $HOME/.claude/settings.json and run this script again"
  python3 "$REPO/scripts/register-codex-hooks.py" \
    || echo "WARNING: Codex hooks are not registered or not trusted; see the message above and run this script again"
}
register_hooks

# Codex reads user skills from ~/.agents/skills, a folder other tools
# fill too, so each skill of this clone gets its own link there. The script
# removes only links it made (by target) and leaves every other entry alone;
# scripts/link-codex-skills.py says how.
link_codex_skills() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "WARNING: python3 not found; Codex skills are not linked (see SETUP.md, Codex)"
    return 0
  fi
  python3 "$REPO/scripts/link-codex-skills.py" \
    || echo "WARNING: Codex skills are not linked; see the message above and run this script again"
}
link_codex_skills

echo ""
echo "Cursor: slash commands (e.g. /make-prd) load from $HOME/.cursor/commands in every workspace."
echo "Project AGENTS.md: see SETUP_NEW_PROJECT.md and scripts/propagate-agents.sh (not run from this script)."
