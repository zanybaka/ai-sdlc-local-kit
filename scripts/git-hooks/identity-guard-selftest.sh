#!/usr/bin/env bash
# documented, self-contained proof of the identity guard.
#
# Runs ENTIRELY inside a mktemp -d sandbox HOME + a throwaway git repo — it
# NEVER touches the real environment, ~/.config, or the real global git config.
# It exercises the guard the same way git does (args + refs on stdin) and
# asserts:
#   (a) dirty tree (denylisted string present) + github remote -> BLOCK (exit 1)
#   (b) clean tree                             + github remote -> PASS  (exit 0)
#   (c) dirty tree                             + non-github    -> PASS  (exit 0)
#   (d) dirty tree + github + IDENTITY_GUARD=warn              -> PASS  (exit 0)
#   (e) guard installed under a global core.hooksPath runs the repo-local
#       .git/hooks/pre-push and returns its exit code
#
# Usage: bash scripts/git-hooks/identity-guard-selftest.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="$SCRIPT_DIR/identity-guard-pre-push.sh"
[ -f "$GUARD" ] || { echo "selftest: missing guard: $GUARD" >&2; exit 1; }

sandbox="$(mktemp -d)"
trap 'rm -rf "$sandbox"' EXIT

export HOME="$sandbox"
export XDG_CONFIG_HOME="$sandbox/.config"
export GIT_CONFIG_GLOBAL="$sandbox/.gitconfig"
TOKEN="SECRET-IDENTITY-TOKEN-92"
deny="$sandbox/identity-denylist.txt"
printf '%s\n# a comment line\n\n' "$TOKEN" > "$deny"

repo="$sandbox/repo"
mkdir -p "$repo"
git -C "$repo" init -q
git -C "$repo" config user.email "test@example.test"
git -C "$repo" config user.name "Selftest"

zero=0000000000000000000000000000000000000000
fails=0

# Run the guard as git would: args = <remote-name> <remote-url>, ref line on
# stdin. Returns the guard's exit code. Never aborts the script (guarded ||).
run_guard() { # $1=remote-url $2=extra-env(optional) $3=guard path(optional)
    local url="$1" extra="${2:-}" guard="${3:-$GUARD}"
    local sha
    sha="$(git -C "$repo" rev-parse HEAD)"
    local rc=0
    # git invokes pre-push with cwd = the pushing repo, so run it from $repo.
    printf 'refs/heads/main %s refs/heads/main %s\n' "$sha" "$zero" \
        | ( cd "$repo" && env IDENTITY_DENYLIST="$deny" HOME="$sandbox" ${extra:+$extra} \
              bash "$guard" origin "$url" ) >/dev/null 2>&1 || rc=$?
    echo "$rc"
}

assert_rc() { # $1=label $2=expected $3=actual
    if [ "$2" = "$3" ]; then
        echo "  PASS  $1 (exit $3)"
    else
        echo "  FAIL  $1 — expected exit $2, got $3"
        fails=$((fails + 1))
    fi
}

# --- Case (a): dirty tree + github -> BLOCK -----------------------------------
printf 'owner: %s\n' "$TOKEN" > "$repo/doc.md"
git -C "$repo" add -A
git -C "$repo" commit -qm "dirty: contains denylisted token"
assert_rc "(a) dirty tree + github url blocks" 1 "$(run_guard "https://github.com/acme/x.git")"

# --- Case (c): SAME dirty tree + non-github remote -> PASS --------------------
assert_rc "(c) dirty tree + non-github url passes" 0 "$(run_guard "https://gitlab.example/acme/x.git")"

# --- Case (d): dirty tree + github + IDENTITY_GUARD=warn -> PASS --------------
assert_rc "(d) dirty tree + github + IDENTITY_GUARD=warn passes" 0 "$(run_guard "https://github.com/acme/x.git" "IDENTITY_GUARD=warn")"

# --- Case (b): clean tree + github -> PASS ------------------------------------
printf 'owner: your-public-handle\n' > "$repo/doc.md"
git -C "$repo" add -A
git -C "$repo" commit -qm "clean: no denylisted token"
assert_rc "(b) clean tree + github url passes" 0 "$(run_guard "https://github.com/acme/x.git")"

# --- Case (e): installed under a global core.hooksPath -> runs the repo hook --
# git answers `--git-path hooks/pre-push` with the global dir there, so a guard
# that asked it found itself and skipped the repo gate.
mkdir -p "$sandbox/hooks"
cp "$GUARD" "$sandbox/hooks/pre-push"
chmod +x "$sandbox/hooks/pre-push"
git config --global core.hooksPath "$sandbox/hooks"
marker="$sandbox/repo-hook-ran"
printf "#!/usr/bin/env bash\ncat >/dev/null\ntouch %q\nexit 3\n" "$marker" > "$repo/.git/hooks/pre-push"
chmod +x "$repo/.git/hooks/pre-push"
assert_rc "(e) global hooksPath guard returns the repo hook exit code" 3 \
    "$(run_guard "https://github.com/acme/x.git" "" "$sandbox/hooks/pre-push")"
if [ -f "$marker" ]; then
    echo "  PASS  (e) the repo-local pre-push ran"
else
    echo "  FAIL  (e) the repo-local pre-push did not run"
    fails=$((fails + 1))
fi

echo ""
if [ "$fails" -eq 0 ]; then
    echo "identity-guard selftest: ALL PASS"
    exit 0
fi
echo "identity-guard selftest: $fails FAILURE(S)"
exit 1
