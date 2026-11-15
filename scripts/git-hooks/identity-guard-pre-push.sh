#!/usr/bin/env bash
# portable GLOBAL pre-push identity guard (all-github-repo scope).
#
# This file is SELF-CONTAINED: it must run when copied verbatim into the global
# git hooks dir (core.hooksPath, typically ~/.config/git/hooks/pre-push). It
# does NOT source this repo — installing it only requires the single file plus a
# denylist. Install it with scripts/install-identity-guard.sh.
#
# What it does: on a push to any github.com remote it git-greps the pushed tree
# for denylisted identity strings (real corporate emails/domains/usernames that
# must never reach a public remote). A match BLOCKS the push (exit 1), because a
# leaked identity on a public remote cannot be un-published. It then delegates to any repo-local
# .git/hooks/pre-push so a repo's own richer gate still runs.
#
# Denylist (real patterns, NEVER committed): one fixed identity string per line,
# blank lines and `#` comments ignored. Default location:
#   ${IDENTITY_DENYLIST:-${XDG_CONFIG_HOME:-$HOME/.config}/git/identity-denylist.txt}
# Seed it from scripts/git-hooks/identity-denylist.example.txt (placeholders
# only) and fill the real patterns locally.
#
# Escape hatches:
#   IDENTITY_GUARD=warn git push   # downgrade a match from block to warning
#   git push --no-verify           # git-native skip of all hooks
#
# git invokes pre-push as:  pre-push <remote-name> <remote-url>
# and feeds ref lines on stdin:  <local-ref> <local-sha> <remote-ref> <remote-sha>
set -euo pipefail

remote_url="${2:-}"
zero=0000000000000000000000000000000000000000

# Capture stdin once (single-consumption): we both scan it and replay it to the
# repo-local delegate hook. Skip when stdin is a TTY (manual/test invocation).
refs_stdin=""
if [ ! -t 0 ]; then
    refs_stdin="$(cat)"
fi

# Resolve the denylist and build a pattern array. Using an -e <pattern> array
# (NOT `git grep -f <file>`) means `#`-comment and blank lines can never become
# literal search terms.
denylist="${IDENTITY_DENYLIST:-${XDG_CONFIG_HOME:-$HOME/.config}/git/identity-denylist.txt}"
patterns=()
if [ -f "$denylist" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            ''|'#'*) continue ;;
        esac
        patterns+=("$line")
    done < "$denylist"
fi

# Only scan pushes to github.com remotes (covers https://github.com/... and
# git@github.com:... SSH), and only when we actually have patterns to look for.
if [ "${#patterns[@]}" -gt 0 ]; then
    case "$remote_url" in
        *github.com*)
            pat_args=()
            for p in "${patterns[@]}"; do
                pat_args+=(-e "$p")
            done
            hit=0
            # Iterate the captured ref lines; scan each non-deleted local sha's
            # tree. git grep exits 1 on no-match, which under `set -e` is only
            # safe inside an `if` condition — so every grep is wrapped.
            while read -r _lref lsha _rref _rsha; do
                [ -z "${lsha:-}" ] && continue
                [ "$lsha" = "$zero" ] && continue   # branch/ref delete — nothing to scan
                if git grep -I -n -F "${pat_args[@]}" "$lsha" >/dev/null 2>&1; then
                    hit=1
                    echo "identity-guard: denylisted identity string(s) found in $lsha:" >&2
                    git grep -I -n -F "${pat_args[@]}" "$lsha" >&2 2>/dev/null || true
                fi
            done <<EOF
$refs_stdin
EOF
            if [ "$hit" = "1" ]; then
                if [ "${IDENTITY_GUARD:-}" = "warn" ]; then
                    echo "identity-guard: WARNING — denylisted identity string in the pushed tree (IDENTITY_GUARD=warn) — not blocking." >&2
                else
                    echo "identity-guard: BLOCKED — a denylisted identity string is in the pushed tree." >&2
                    echo "identity-guard: scrub it (prefer your public GitHub handle over a corporate identity), then re-push." >&2
                    echo "identity-guard: to override: IDENTITY_GUARD=warn git push  (or  git push --no-verify)." >&2
                    exit 1
                fi
            fi
            ;;
    esac
fi

# Always delegate to a repo-local pre-push hook when one exists, is executable,
# and is not this guard itself (realpath compare avoids self-recursion when a
# repo symlinks its hook back to the global guard). Replay the captured stdin
# and forward the original args so the delegate sees exactly what git sent.
# The delegate is looked up in the common git dir: with a global
# core.hooksPath, `git rev-parse --git-path hooks/pre-push` answers with that
# global dir, which is this guard itself, and the repo gate never ran. The
# common dir also serves a push from a linked worktree.
common_dir="$(git rev-parse --git-common-dir 2>/dev/null || true)"
delegate=""
[ -n "$common_dir" ] && delegate="$common_dir/hooks/pre-push"
if [ -n "$delegate" ] && [ -x "$delegate" ]; then
    self_real=""
    del_real=""
    if command -v realpath >/dev/null 2>&1; then
        self_real="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null || true)"
        del_real="$(realpath "$delegate" 2>/dev/null || true)"
    fi
    if [ -z "$self_real" ] || [ -z "$del_real" ] || [ "$self_real" != "$del_real" ]; then
        printf '%s\n' "$refs_stdin" | "$delegate" "$@"
        exit $?
    fi
fi

exit 0
