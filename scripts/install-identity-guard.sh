#!/usr/bin/env bash
# installer for the portable GLOBAL pre-push identity guard.
#
# Vendors the machine-local, hand-installed identity guard reproducibly:
#   - copies scripts/git-hooks/identity-guard-pre-push.sh to the global
#     core.hooksPath hooks dir as `pre-push` (chmod +x);
#   - seeds ~/.config/git/identity-denylist.txt from the placeholders-only
#     example if it is absent, then reminds you to fill real patterns locally;
#   - sets global core.hooksPath ONLY when it is unset — if it already points
#     somewhere, it installs into THAT dir and leaves core.hooksPath unchanged.
#
# Idempotent: re-running is a no-op once the guard and denylist are in place.
# Honors HOME / XDG_CONFIG_HOME so it can be exercised in a sandbox HOME.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD_SRC="$SCRIPT_DIR/git-hooks/identity-guard-pre-push.sh"
EXAMPLE="$SCRIPT_DIR/git-hooks/identity-denylist.example.txt"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/git"
DENYLIST="$CONFIG_DIR/identity-denylist.txt"

[ -f "$GUARD_SRC" ] || { echo "install-identity-guard: missing guard source: $GUARD_SRC" >&2; exit 1; }
[ -f "$EXAMPLE" ] || { echo "install-identity-guard: missing example denylist: $EXAMPLE" >&2; exit 1; }

# --- Resolve the hooks dir WITHOUT clobbering an existing core.hooksPath ------
existing="$(git config --global --get core.hooksPath || true)"
if [ -z "$existing" ]; then
    hooks_dir="$CONFIG_DIR/hooks"
    mkdir -p "$hooks_dir"
    git config --global core.hooksPath "$hooks_dir"
    echo "install-identity-guard: set global core.hooksPath = $hooks_dir"
else
    # Expand a leading ~ the way git does, so the install path is real.
    # Match a literal leading tilde in the stored value (not shell expansion) and
    # expand it as git would. shellcheck SC2088 misreads the case pattern.
    # shellcheck disable=SC2088
    case "$existing" in
        "~") hooks_dir="$HOME" ;;
        "~/"*) hooks_dir="$HOME/${existing#\~/}" ;;
        *) hooks_dir="$existing" ;;
    esac
    mkdir -p "$hooks_dir"
    echo "install-identity-guard: global core.hooksPath already set ($existing) — installing into it; leaving core.hooksPath unchanged."
fi

# --- Install the guard as <hooks_dir>/pre-push --------------------------------
target="$hooks_dir/pre-push"
if [ -f "$target" ] && cmp -s "$GUARD_SRC" "$target"; then
    echo "install-identity-guard: guard already installed at $target — no change."
elif [ -f "$target" ] && grep -q 'portable GLOBAL pre-push identity guard' "$target" 2>/dev/null; then
    cp "$GUARD_SRC" "$target"
    chmod +x "$target"
    echo "install-identity-guard: updated existing identity guard at $target."
elif [ -f "$target" ]; then
    echo "install-identity-guard: a DIFFERENT pre-push hook already exists at $target." >&2
    echo "install-identity-guard: refusing to overwrite it. Either merge the guard's logic into it," >&2
    echo "install-identity-guard: or move it aside and have the guard delegate to it (the guard already" >&2
    echo "install-identity-guard: chains to a repo-local .git/hooks/pre-push)." >&2
    exit 1
else
    cp "$GUARD_SRC" "$target"
    chmod +x "$target"
    echo "install-identity-guard: installed guard at $target."
fi

# --- Seed the operator-local denylist from the example (never overwrite) ------
mkdir -p "$CONFIG_DIR"
if [ ! -f "$DENYLIST" ]; then
    cp "$EXAMPLE" "$DENYLIST"
    echo ""
    echo "install-identity-guard: *** REMINDER ***"
    echo "install-identity-guard: seeded $DENYLIST from the example (placeholders only)."
    echo "install-identity-guard: EDIT it now and replace the placeholders with your REAL identity"
    echo "install-identity-guard: strings (corporate email/domain/username). This file is NEVER committed."
else
    echo "install-identity-guard: denylist already present at $DENYLIST — left untouched."
fi

echo "install-identity-guard: done."
