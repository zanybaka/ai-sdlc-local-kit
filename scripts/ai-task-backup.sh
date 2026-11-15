#!/usr/bin/env bash
# ai-task-backup.sh — archive/restore the durable `.ai-task` data set.
#
# Everything under `.ai-task/` is gitignored by design, so a lost disk loses
# months of decision history and telemetry. This helper archives the
# recoverable-valuable subset (decisions.jsonl, quota-telemetry.jsonl,
# config.toml, state.json, policies/, reports/) from one or many repos into a
# timestamped tar. Sources are only ever read. See docs/ai-task.md
# "Data durability" for the per-file inventory.
#
# Usage:
#   ai-task-backup.sh [--target DIR] REPO [REPO...]
#   ai-task-backup.sh --restore ARCHIVE --repo PATH [--from NAME] [--force]
#
# Backup target dir default: ~/Backups/ai-task (override with --target or the
# AI_TASK_BACKUP_DIR env var). Each repo lands in a per-repo subdir inside the
# tar, named "<basename>" or "<basename>__<project_id>" when config.toml has a
# readable project_id. Repos without .ai-task are skipped with a notice.
#
# Restore extracts one repo subdir into PATH/.ai-task. It refuses to write
# into a non-empty .ai-task unless --force is given. When the archive holds
# several repos, pick one with --from NAME (names are listed on error).
# Note: leases/locks inside a restored state.json are machine-local stale data.
set -euo pipefail

BACKUP_ITEMS="decisions.jsonl quota-telemetry.jsonl config.toml state.json policies reports"

usage() {
  cat <<'EOF'
usage: ai-task-backup.sh [--target DIR] REPO [REPO...]
       ai-task-backup.sh --restore ARCHIVE --repo PATH [--from NAME] [--force]

Backs up the durable .ai-task set (decisions.jsonl, quota-telemetry.jsonl,
config.toml, state.json, policies/, reports/) into a timestamped tar under
--target (default ~/Backups/ai-task, env override AI_TASK_BACKUP_DIR).
Restore refuses a non-empty .ai-task without --force.
EOF
}

TARGET="${AI_TASK_BACKUP_DIR:-$HOME/Backups/ai-task}"
MODE="backup"
ARCHIVE=""
RESTORE_REPO=""
FROM_NAME=""
FORCE=0
REPOS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --target)  [ $# -ge 2 ] || { echo "ERROR: --target needs a value" >&2; exit 2; }
               TARGET="$2"; shift 2 ;;
    --restore) [ $# -ge 2 ] || { echo "ERROR: --restore needs an archive path" >&2; exit 2; }
               MODE="restore"; ARCHIVE="$2"; shift 2 ;;
    --repo)    [ $# -ge 2 ] || { echo "ERROR: --repo needs a path" >&2; exit 2; }
               RESTORE_REPO="$2"; shift 2 ;;
    --from)    [ $# -ge 2 ] || { echo "ERROR: --from needs a name" >&2; exit 2; }
               FROM_NAME="$2"; shift 2 ;;
    --force)   FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --*)       echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
    *)         REPOS+=("$1"); shift ;;
  esac
done

STAGE="$(mktemp -d "${TMPDIR:-/tmp}/ai-task-backup.XXXXXX")"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

if [ "$MODE" = "restore" ]; then
  [ -n "$RESTORE_REPO" ] || { echo "ERROR: --restore requires --repo PATH" >&2; exit 2; }
  [ -f "$ARCHIVE" ] || { echo "ERROR: archive not found: $ARCHIVE" >&2; exit 1; }
  [ -d "$RESTORE_REPO" ] || { echo "ERROR: repo path is not a directory: $RESTORE_REPO" >&2; exit 1; }
  dest="$RESTORE_REPO/.ai-task"
  if [ -d "$dest" ] && [ -n "$(find "$dest" -mindepth 1 -print 2>/dev/null | head -1)" ] \
    && [ "$FORCE" -ne 1 ]; then
    echo "ERROR: $dest is not empty — pass --force to overwrite existing files" >&2
    exit 1
  fi
  tar -xzf "$ARCHIVE" -C "$STAGE"
  subs=()
  while IFS= read -r d; do
    [ -n "$d" ] && subs+=("$(basename "$d")")
  done <<EOF_SUBS
$(find "$STAGE" -mindepth 1 -maxdepth 1 -type d | sort)
EOF_SUBS
  [ "${#subs[@]}" -gt 0 ] || { echo "ERROR: no repo subdirs inside $ARCHIVE" >&2; exit 1; }
  pick=""
  if [ -n "$FROM_NAME" ]; then
    for s in "${subs[@]}"; do
      [ "$s" = "$FROM_NAME" ] && pick="$s"
    done
    [ -n "$pick" ] || { echo "ERROR: no subdir '$FROM_NAME' in archive; available: ${subs[*]}" >&2; exit 1; }
  elif [ "${#subs[@]}" -eq 1 ]; then
    pick="${subs[0]}"
  else
    echo "ERROR: archive holds several repos — pick one with --from NAME; available: ${subs[*]}" >&2
    exit 1
  fi
  mkdir -p "$dest"
  cp -Rp "$STAGE/$pick/." "$dest/"
  echo "restored $pick into $dest"
  echo "note: leases/locks inside state.json are machine-local; verify with 'ai-task status'"
  exit 0
fi

# --- backup mode -------------------------------------------------------------
[ "${#REPOS[@]}" -gt 0 ] || { usage >&2; exit 2; }

MANIFEST="$STAGE/MANIFEST.txt"
printf 'ai-task backup %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" > "$MANIFEST"
archived=0

for repo in "${REPOS[@]}"; do
  repo_abs="$(cd "$repo" 2>/dev/null && pwd)" || {
    echo "NOTICE: $repo is not a directory — skipped" >&2
    continue
  }
  src="$repo_abs/.ai-task"
  if [ ! -d "$src" ]; then
    echo "NOTICE: $repo_abs has no .ai-task — skipped" >&2
    continue
  fi
  name="$(basename "$repo_abs")"
  project_id=""
  if [ -f "$src/config.toml" ]; then
    project_id="$(sed -n 's/^[[:space:]]*project_id[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' \
      "$src/config.toml" | head -1)"
  fi
  if [ -n "$project_id" ] && [ "$project_id" != "$name" ]; then
    name="${name}__${project_id}"
  fi
  sub="$name"
  n=2
  while [ -e "$STAGE/$sub" ]; do
    sub="${name}-${n}"
    n=$((n + 1))
  done
  mkdir -p "$STAGE/$sub"
  copied=0
  for item in $BACKUP_ITEMS; do
    if [ -e "$src/$item" ]; then
      cp -Rp "$src/$item" "$STAGE/$sub/$item"
      copied=$((copied + 1))
    fi
  done
  if [ "$copied" -eq 0 ]; then
    echo "NOTICE: $src holds none of the backup set — skipped" >&2
    rmdir "$STAGE/$sub"
    continue
  fi
  printf '%s\t%s\n' "$sub" "$repo_abs" >> "$MANIFEST"
  echo "archived $sub ($copied item(s)) from $repo_abs"
  archived=$((archived + 1))
done

if [ "$archived" -eq 0 ]; then
  echo "ERROR: nothing to archive (no given repo has .ai-task data)" >&2
  exit 1
fi

mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"
stamp="$(date '+%Y%m%d-%H%M%S')"
out="$TARGET/ai-task-backup-${stamp}.tar.gz"
n=2
while [ -e "$out" ]; do
  out="$TARGET/ai-task-backup-${stamp}-${n}.tar.gz"
  n=$((n + 1))
done
(cd "$STAGE" && tar -czf "$out" .)
echo "wrote $out ($archived repo(s))"
