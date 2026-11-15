#!/usr/bin/env bash
# Link third-party skill folders into this repo's skills/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
THIRD_PARTY="$REPO/third_party"
DEST="$REPO/skills"
CONFIG="$REPO/third-party-skills.json"

realp() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1"
  elif command -v realpath >/dev/null 2>&1; then
    realpath "$1"
  else
    readlink -f "$1"
  fi
}

relpath() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$1" "$2"
  else
    printf '%s\n' "$1"
  fi
}

is_managed_link() {
  local link="$1" target=""
  [[ -L "$link" ]] || return 1
  target="$(realp "$link" 2>/dev/null || true)"
  [[ -n "$target" ]] || return 1
  [[ "$target" == "$THIRD_PARTY_ABS"/* ]] || return 1
  [[ -f "$target/SKILL.md" ]]
}

link_skill() {
  local src="$1" name="${2:-}" src_abs="" dest="" current="" target_rel=""
  [[ -d "$src" ]] || return 0
  [[ -f "$src/SKILL.md" ]] || return 0

  if [[ -z "$name" ]]; then
    name="$(basename "$src")"
  fi
  src_abs="$(realp "$src")"
  dest="$DEST/$name"

  case "$seen_names" in
    *"|$name|"*)
      echo "WARN: duplicate third-party skill name '$name'; keeping the first match."
      skipped=$((skipped + 1))
      return 0
      ;;
  esac
  seen_names="${seen_names}${name}|"

  if [[ -e "$dest" || -L "$dest" ]]; then
    if [[ -L "$dest" ]]; then
      current="$(realp "$dest" 2>/dev/null || true)"
      if [[ "$current" == "$src_abs" ]]; then
        echo "OK (unchanged): skills/$name"
        linked=$((linked + 1))
        return 0
      fi
      if is_managed_link "$dest"; then
        rm "$dest"
        echo "Refreshed managed link: skills/$name"
      else
        echo "WARN: refusing to overwrite non-managed link: skills/$name"
        skipped=$((skipped + 1))
        return 0
      fi
    else
      echo "WARN: refusing to overwrite local skill or file: skills/$name"
      skipped=$((skipped + 1))
      return 0
    fi
  fi

  target_rel="$(relpath "$src_abs" "$DEST_ABS")"
  ln -s "$target_rel" "$dest"
  echo "Linked: skills/$name -> $target_rel"
  linked=$((linked + 1))
}

configured_skill_paths() {
  local pack_rel="$1"
  [[ -f "$CONFIG" ]] || return 0
  python3 - "$CONFIG" "$pack_rel" <<'PY'
import json
import sys

config_path, pack_rel = sys.argv[1], sys.argv[2]
with open(config_path, encoding="utf-8") as f:
    data = json.load(f)

for pack in data.get("packs", []):
    if pack.get("path") != pack_rel:
        continue
    for entry in pack.get("skillPaths", []) or []:
        if isinstance(entry, str):
            skill_path = entry
            skill_name = ""
        elif isinstance(entry, dict):
            skill_path = entry.get("path", "")
            skill_name = entry.get("name", "")
        else:
            raise SystemExit(f"invalid skill path entry for {pack_rel}: {entry!r}")
        if not skill_path:
            raise SystemExit(f"empty skill path for {pack_rel}")
        parts = skill_path.split("/")
        if skill_path.startswith("/") or ".." in parts:
            raise SystemExit(f"invalid skill path for {pack_rel}: {skill_path}")
        if skill_name and ("/" in skill_name or skill_name in {".", ".."}):
            raise SystemExit(f"invalid skill name for {pack_rel}: {skill_name}")
        print(f"{skill_path}\t{skill_name}")
PY
}

mkdir -p "$DEST"

if [[ ! -d "$THIRD_PARTY" ]]; then
  echo "No third_party directory found - nothing to link."
  exit 0
fi

THIRD_PARTY_ABS="$(realp "$THIRD_PARTY")"
DEST_ABS="$(realp "$DEST")"
seen_names="|"
linked=0
skipped=0

shopt -s nullglob
for pack in "$THIRD_PARTY"/*; do
  pack_rel="${pack#$REPO/}"
  has_configured_paths=0
  [[ -d "$pack" ]] || continue
  while IFS=$'\t' read -r skill_path skill_name; do
    has_configured_paths=1
    if [[ -f "$pack/$skill_path/SKILL.md" ]]; then
      link_skill "$pack/$skill_path" "$skill_name"
    else
      echo "WARN: configured skill not found: $pack_rel/$skill_path"
      skipped=$((skipped + 1))
    fi
  done < <(configured_skill_paths "$pack_rel")
  if [[ "$has_configured_paths" -eq 1 ]]; then
    continue
  fi
  for src in "$pack"/skills/* "$pack"/.agents/skills/* "$pack"/*; do
    link_skill "$src"
  done
done
shopt -u nullglob

if [[ "$linked" -eq 0 && "$skipped" -eq 0 ]]; then
  echo "No third-party skills found under supported third_party layouts."
fi
