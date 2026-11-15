#!/usr/bin/env bash
# Keep each project's AGENTS.md copy in sync with the shared source.
#
# Model: a project's AGENTS.md is a REAL file (a copy of the shared source), not
# a symlink into ai-sdlc-local-kit, which dangles where ai-sdlc-local-kit is absent. In a PRIVATE
# repository the copy is committed, so it works in cloud/mobile checkouts too. In
# a PUBLIC repository the copy stays local, in .gitignore, and this script never
# commits or pushes it. Visibility is
# read with `gh repo view --json isPrivate`; no answer means public, as the canon
# says (fail closed). This script refreshes both kinds of copies from the single
# source.
#
# Source of truth: <repo>/context/AGENTS.md.
# Collection: the folder that CONTAINS the ai-sdlc-local-kit repo (its parent) — derived
# from this script's own location, no absolute paths.
#
# Scan (no project arg): refresh every ALREADY-CONNECTED project in the collection
#   — one whose AGENTS.md is a symlink to the source or a known copy of it. Projects
#   with NO AGENTS.md are skipped (connect them with the single-project mode below or
#   via the bootstrap skill). A project's own unrelated AGENTS.md is never touched.
# Single project (arg = folder name or path): connect/refresh just that one — this is
#   what bootstrap calls; it is idempotent (re-running on a current copy is a no-op).
#
# Usage:
#   propagate-agents.sh [<project>]            write fresh copies + per-project review (branch + diff). No git changes.
#   propagate-agents.sh --check [<project>]    report stale/symlink/missing copies and overrides without the first line, write nothing (exit 1 if any)
#   propagate-agents.sh --commit [<project>]   write, then commit + push — with an all-or-nothing safety preflight
#
# A public project (or one whose visibility gh does not answer) is refreshed in
# every mode but is never part of a commit: the output names it as a local copy,
# and warns when its AGENTS.md is still tracked or not ignored.
#
# --commit commits every connected PRIVATE project whose AGENTS.md (or the obsolete shared
# .cursor/rules/writing-style.mdc, or .gitignore) is dirty in git — including copies
# already materialised by a prior review run. Preflight (Q1): it refuses to commit
# ANYTHING unless EVERY project it would touch is on its default branch, has no
# unpushed commits, and a clean index. If any one fails, it lists the offenders and
# does nothing. Then the CI gate: the canon rule is to push only the fix
# onto a red default branch, so a project whose default-branch head is red on GitHub
# Actions is skipped with an explicit line (nothing written, nothing pushed) and the
# summary lists it; the others sync. No gh, no access or no completed CI run is
# reported as "ci not checked" and does not block. GH overrides the gh binary.
#
# bash 3.2 compatible (macOS default): every array expansion is length-guarded.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
COLLECTION="$(cd "$REPO/.." && pwd)"
SRC="$REPO/context/AGENTS.md"

GH="${GH:-gh}"

# Paths this tool is allowed to stage in a project commit.
COMMIT_PATHS=(AGENTS.md .gitignore .cursor/rules/writing-style.mdc)

OVERRIDE_FIRST_LINE='Read AGENTS.md at the repository root first: it is the shared canon, and this file only adds the rules of this repository and wins on conflict.'

mode="write"
one=""
for arg in "$@"; do
  case "$arg" in
    --check) mode="check" ;;
    --commit) mode="commit" ;;
    --*) echo "usage: $(basename "$0") [--check|--commit] [<project>]" >&2; exit 2 ;;
    *) one="$arg" ;;
  esac
done

[[ -f "$SRC" ]] || { echo "error: missing source $SRC" >&2; exit 1; }
SRC_REAL="$(cd "$(dirname "$SRC")" && pwd)/$(basename "$SRC")"

realp() {
  if command -v python3 >/dev/null 2>&1; then python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$1"
  elif command -v realpath >/dev/null 2>&1; then realpath "$1"
  else readlink -f "$1"; fi
}

is_git() { git -C "$1" rev-parse --is-inside-work-tree >/dev/null 2>&1; }

# is_linked_worktree <proj>: its git dir differs from the common dir of the repository.
is_linked_worktree() {
  local gd cd
  gd="$(git -C "$1" rev-parse --absolute-git-dir 2>/dev/null)" || return 1
  cd="$(git -C "$1" rev-parse --git-common-dir 2>/dev/null)" || return 1
  cd="$(cd "$1" && cd "$cd" 2>/dev/null && pwd -P)" || return 1
  [[ "$(cd "$gd" && pwd -P)" != "$cd" ]]
}

# True if FILE matches ANY committed version of context/AGENTS.md in the ai-sdlc-local-kit
# repo — i.e. a known (possibly stale) copy of the shared source, safe to refresh.
is_known_shared_copy() {
  local file="$1" dest_hash commit blob_hash
  dest_hash="$(git -C "$REPO" hash-object "$file" 2>/dev/null)" || return 1
  while IFS= read -r commit; do
    blob_hash="$(git -C "$REPO" rev-parse "$commit:context/AGENTS.md" 2>/dev/null)" || continue
    [[ "$blob_hash" == "$dest_hash" ]] && return 0
  done < <(git -C "$REPO" rev-list HEAD -- context/AGENTS.md 2>/dev/null)
  return 1
}

# classify <proj> -> uptodate | symlink | stalecopy | absent | unknown
classify() {
  local proj="$1" tgt
  local dest="$proj/AGENTS.md"
  if [[ -L "$dest" ]]; then
    tgt="$(realp "$dest" 2>/dev/null || true)"
    [[ "$tgt" == "$SRC_REAL" ]] && { echo symlink; return; }
    echo unknown; return
  fi
  if [[ -f "$dest" ]]; then
    cmp -s "$SRC" "$dest" && { echo uptodate; return; }
    is_known_shared_copy "$dest" && { echo stalecopy; return; }
    echo unknown; return
  fi
  echo absent
}

default_branch() {
  local proj="$1" d
  d="$(git -C "$proj" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')"
  if [[ -z "$d" ]]; then
    for b in main master; do
      git -C "$proj" show-ref --verify --quiet "refs/heads/$b" && { d="$b"; break; }
    done
  fi
  printf '%s' "$d"
}

# github_slug <proj>: owner/repo of a github.com origin, empty otherwise. Reads the
# raw config value, so a local url.insteadOf rewrite does not hide the slug.
github_slug() {
  local url
  url="$(git -C "$1" config --get remote.origin.url 2>/dev/null || true)"
  printf '%s\n' "$url" \
    | sed -nE 's#^(https?://([^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+/[^/]+)$#\3#p' \
    | sed 's#\.git$##'
}

ci_state() {
  local proj="$1" def="$2" slug sha runs out
  command -v "$GH" >/dev/null 2>&1 || { echo "unchecked no gh CLI"; return; }
  command -v python3 >/dev/null 2>&1 || { echo "unchecked no python3"; return; }
  slug="$(github_slug "$proj")"
  [[ -n "$slug" ]] || { echo "unchecked origin is not a GitHub repo"; return; }
  [[ -n "$def" ]] || { echo "unchecked no default branch"; return; }
  sha="$("$GH" api "repos/$slug/commits/$def" --jq .sha 2>/dev/null)" || sha=""
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "unchecked no access to $slug through gh"; return; }
  runs="$("$GH" api "repos/$slug/actions/runs?head_sha=$sha&status=completed&per_page=100" 2>/dev/null)" \
    || { echo "unchecked no access to the CI runs of $slug"; return; }
  out="$(printf '%s' "$runs" | python3 "$SCRIPT_DIR/ci-head-state.py" 2>/dev/null)" \
    || { echo "unchecked unreadable CI answer for $slug"; return; }
  case "$out" in
    red\ * | green\ *) echo "$out" ;;
    *) echo "unchecked ${out#none }" ;;
  esac
}

# visibility <proj>: "private", "public" or "unknown <reason>". Unknown is
# treated as public by the caller: the canon fails closed on visibility.
visibility() {
  local slug ans
  command -v "$GH" >/dev/null 2>&1 || { echo "unknown no gh CLI"; return; }
  slug="$(github_slug "$1")"
  [[ -n "$slug" ]] || { echo "unknown origin is not a GitHub repo"; return; }
  ans="$("$GH" repo view "$slug" --json isPrivate --jq .isPrivate 2>/dev/null)" || ans=""
  case "$ans" in
    true) echo private ;;
    false) echo public ;;
    *) echo "unknown no answer from gh for $slug" ;;
  esac
}

# Connected projects whose copy stays local (public or unknown visibility).
public=()
is_public() {
  local p
  ((${#public[@]})) || return 1
  for p in "${public[@]}"; do [[ "$p" == "$1" ]] && return 0; done
  return 1
}

# git_dirty <proj>: any uncommitted change to the paths this tool manages.
git_dirty() {
  [[ -n "$(git -C "$1" status --porcelain -- "${COMMIT_PATHS[@]}" 2>/dev/null)" ]]
}

review() {
  local proj="$1" name cur
  name="$(basename "$proj")"
  cur="$(git -C "$proj" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  echo "=== $name  (branch: $cur) ==="
  if is_public "$proj"; then
    echo "    (local copy, never committed — $(wc -l < "$proj/AGENTS.md" | tr -d ' ') lines)"
  elif git -C "$proj" ls-files --error-unmatch AGENTS.md >/dev/null 2>&1; then
    git -C "$proj" --no-pager diff -- AGENTS.md | sed 's/^/    /' || true
  else
    echo "    (new committed AGENTS.md — $(wc -l < "$proj/AGENTS.md" | tr -d ' ') lines)"
  fi
}

# Build the target project list (absolute paths).
targets=()
if [[ -n "$one" ]]; then
  if [[ -d "$one" ]]; then targets+=("$(cd "$one" && pwd)")
  elif [[ -d "$COLLECTION/$one" ]]; then targets+=("$COLLECTION/$one")
  else echo "error: no such project: $one" >&2; exit 1; fi
else
  for d in "$COLLECTION"/*/; do
    proj="${d%/}"
    [[ "$proj" == "$REPO" ]] && continue
    is_git "$proj" || continue
    # A linked worktree shares the repository of its main checkout, which the scan
    # syncs on its own; its feature branch would fail the preflight.
    if is_linked_worktree "$proj"; then
      echo "skip (linked worktree, its main checkout is synced instead): $(basename "$proj")"
      continue
    fi
    targets+=("$proj")
  done
fi

# Pass 1: classify + report; collect connected projects and the write list (todo).
connected=()
todo=()
unconnected=()
stale=0
if ((${#targets[@]})); then
  for proj in "${targets[@]}"; do
    name="$(basename "$proj")"
    kind="$(classify "$proj")"
    case "$kind" in
      uptodate) echo "up to date: $name"; connected+=("$proj") ;;
      unknown)  echo "skip (own AGENTS.md, not touched): $name" ;;
      symlink)  echo "stale (symlink -> copy): $name"; connected+=("$proj"); todo+=("$proj"); stale=1 ;;
      stalecopy) echo "stale (old copy): $name"; connected+=("$proj"); todo+=("$proj"); stale=1 ;;
      absent)
        if [[ -n "$one" ]]; then echo "new (connect): $name"; connected+=("$proj"); todo+=("$proj"); stale=1
        else echo "not connected (no AGENTS.md): $name"; unconnected+=("$proj"); fi
        ;;
    esac
  done
fi

# Override first line: a root AGENTS.override.md of a connected project,
# and of ai-sdlc-local-kit itself on a scan, must open with OVERRIDE_FIRST_LINE. Reported in
# every mode; only --check turns it into a failing exit.
override_bad=0
check_override() {
  local proj="$1" ov first
  ov="$proj/AGENTS.override.md"
  [[ -f "$ov" ]] || return 0
  IFS= read -r first < "$ov" || first=""
  first="${first%$'\r'}"
  [[ "$first" == "$OVERRIDE_FIRST_LINE" ]] && return 0
  echo "override lacks the first line (Codex reads it instead of AGENTS.md): $(basename "$proj")"
  override_bad=1
}
[[ -z "$one" ]] && check_override "$REPO"
if ((${#connected[@]})); then
  for proj in "${connected[@]}"; do check_override "$proj"; done
fi

# Offer to connect unconnected git projects — scan mode, real terminal only (a
# non-interactive run, e.g. from tasks.json or CI, just reports them above and
# moves on). Answer y to connect a project (it joins this run), anything else skips.
if [[ -z "$one" && "$mode" != "check" && -t 0 && ${#unconnected[@]} -gt 0 ]]; then
  echo "" >&2
  echo "Unconnected git projects (no shared AGENTS.md yet):" >&2
  for proj in "${unconnected[@]}"; do
    name="$(basename "$proj")"
    printf "  connect %s? [y/N] " "$name" >&2
    if read -r ans </dev/tty; then :; else ans=""; fi
    case "$ans" in
      y|Y|yes|YES) connected+=("$proj"); todo+=("$proj"); stale=1; echo "    -> will connect $name" >&2 ;;
      *) echo "    -> skipped $name" >&2 ;;
    esac
  done
fi

if [[ "$mode" == "check" ]]; then
  if [[ "$override_bad" != "0" ]]; then
    echo "some overrides lack the first line — put it as line 1 of each AGENTS.override.md named above:" >&2
    echo "  $OVERRIDE_FIRST_LINE" >&2
  fi
  [[ "$stale" == "0" && "$override_bad" == "0" ]] && { echo "all connected copies up to date"; exit 0; }
  [[ "$stale" == "0" ]] || echo "some copies need an update — run: scripts/propagate-agents.sh   (review), then --commit" >&2
  exit 1
fi

# Visibility of every connected project: a public one keeps a local copy only.
if ((${#connected[@]})); then
  for proj in "${connected[@]}"; do
    vis="$(visibility "$proj")"
    [[ "$vis" == "private" ]] && continue
    public+=("$proj")
    name="$(basename "$proj")"
    if [[ "$vis" == "public" ]]; then why="public repository"
    else why="visibility unknown: ${vis#unknown }, treated as public"; fi
    echo "local copy only ($why; AGENTS.md is never committed or pushed): $name"
    if git -C "$proj" ls-files --error-unmatch AGENTS.md >/dev/null 2>&1; then
      echo "    warning: AGENTS.md is still tracked in git in $name; the migration out of git is manual (see SETUP_NEW_PROJECT.md)" >&2
    elif ! git -C "$proj" check-ignore -q AGENTS.md 2>/dev/null; then
      echo "    warning: AGENTS.md is not in .gitignore of $name; add the line /AGENTS.md" >&2
    fi
  done
fi

# Commit set = connected PRIVATE projects that need a fresh write OR have uncommitted changes
# to the managed paths (e.g. a copy already materialised by a prior review run).
commit_set=()
if [[ "$mode" == "commit" ]] && ((${#connected[@]})); then
  for proj in "${connected[@]}"; do
    is_public "$proj" && continue
    member=0
    if ((${#todo[@]})); then
      for t in "${todo[@]}"; do [[ "$t" == "$proj" ]] && { member=1; break; }; done
    fi
    if [[ "$member" == "1" ]] || git_dirty "$proj"; then commit_set+=("$proj"); fi
  done
fi

# Preflight: all-or-nothing across every project we would commit.
if [[ "$mode" == "commit" ]] && ((${#commit_set[@]})); then
  blockers=()
  for proj in "${commit_set[@]}"; do
    name="$(basename "$proj")"
    cur="$(git -C "$proj" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
    def="$(default_branch "$proj")"
    [[ -n "$def" && "$cur" == "$def" ]] || { blockers+=("$name: on '$cur', not default '${def:-?}'"); continue; }
    if ! ahead="$(git -C "$proj" rev-list --count '@{upstream}..HEAD' 2>/dev/null)"; then
      blockers+=("$name: no upstream tracking for '$cur'"); continue
    fi
    [[ "$ahead" == "0" ]] || blockers+=("$name: $ahead unpushed commit(s) on '$cur'")
    git -C "$proj" diff --cached --quiet 2>/dev/null || blockers+=("$name: staged changes in the index")
  done
  if ((${#blockers[@]})); then
    echo "" >&2
    echo "preflight FAILED — nothing synced. Fix these, then re-run --commit:" >&2
    printf '  - %s\n' "${blockers[@]}" >&2
    exit 1
  fi
fi

# CI gate: a red default-branch head skips that project; the others sync.
red_skipped=()
if [[ "$mode" == "commit" ]] && ((${#commit_set[@]})); then
  kept=()
  for proj in "${commit_set[@]}"; do
    name="$(basename "$proj")"
    state="$(ci_state "$proj" "$(default_branch "$proj")")"
    case "$state" in
      red\ *)
        echo "skip (default branch CI is red: ${state#red }; push only the fix there): $name"
        red_skipped+=("$proj"); continue ;;
      green\ *) echo "ci green: $name (${state#green })" ;;
      *) echo "ci not checked: $name (${state#unchecked }), syncing anyway" ;;
    esac
    kept+=("$proj")
  done
  commit_set=()
  if ((${#kept[@]})); then commit_set=("${kept[@]}"); fi
  # A skipped project is left exactly as it was: no fresh copy is written into it.
  if ((${#red_skipped[@]})) && ((${#todo[@]})); then
    kept=()
    for t in "${todo[@]}"; do
      skip=0
      for r in "${red_skipped[@]}"; do [[ "$t" == "$r" ]] && { skip=1; break; }; done
      [[ "$skip" == "1" ]] || kept+=("$t")
    done
    todo=()
    if ((${#kept[@]})); then todo=("${kept[@]}"); fi
  fi
fi

# Materialise the stale copies.
if ((${#todo[@]})); then
  for proj in "${todo[@]}"; do
    dest="$proj/AGENTS.md"
    [[ -L "$dest" ]] && rm "$dest"
    cp "$SRC" "$dest"
  done
fi

changed="${#todo[@]}"
local_note=""
if ((${#public[@]})); then
  local_note=", local only (never committed):"
  for p in "${public[@]}"; do local_note="$local_note $(basename "$p")"; done
fi
if [[ "$mode" == "commit" ]]; then
  committed=0
  if ((${#commit_set[@]})); then
    for proj in "${commit_set[@]}"; do
      review "$proj"
      (
        cd "$proj"
        for f in "${COMMIT_PATHS[@]}"; do git add -- "$f" 2>/dev/null || true; done
        # The message goes into public repositories too, so it names no repository.
        if git commit -q -m "chore: sync shared AGENTS.md"; then
          if git push -q 2>/dev/null; then
            echo "    committed + pushed"
          elif git pull --rebase -q 2>/dev/null && git push -q 2>/dev/null; then
            echo "    committed + pushed (rebased onto remote)"
          else
            git rebase --abort 2>/dev/null || true
            echo "    committed, push FAILED (remote diverged — resolve with: git -C '$proj' pull --rebase && git push)" >&2
          fi
        else
          echo "    nothing to commit"
        fi
      )
      committed=$((committed + 1))
    done
  fi
  skipped_note=""
  if ((${#red_skipped[@]})); then
    skipped_note=", ${#red_skipped[@]} skipped on red CI:"
    for r in "${red_skipped[@]}"; do skipped_note="$skipped_note $(basename "$r")"; done
  fi
  echo "done (${changed} refreshed, ${committed} projects committed + pushed${skipped_note}${local_note})"
else
  if ((${#todo[@]})); then for proj in "${todo[@]}"; do review "$proj"; done; fi
  echo "done (${changed} refreshed — review above; run --commit to commit + push${local_note})"
fi
