#!/usr/bin/env bash
# The lint gate. `Verify: python-quick` on a task block means this command.
#
# It resolves a ruff matching the pin in requirements-lint.txt, because an
# unpinned binary makes the finding count depend on whoever installed it last:
# ruff's default rule set changes between releases, so two machines on the same
# commit would otherwise disagree. What counts as clean is stated in ruff.toml.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PIN_FILE="requirements-lint.txt"
VERSION="$(sed -n 's/^ruff==\([0-9][0-9A-Za-z.-]*\)[[:space:]]*$/\1/p' "$PIN_FILE" | head -1)"
if [[ -z "$VERSION" ]]; then
  echo "lint: no 'ruff==<version>' pin found in $PIN_FILE" >&2
  exit 2
fi

if [[ -n "${RUFF:-}" ]]; then
  echo "lint: RUFF override in use ($RUFF); the $VERSION pin is not enforced." >&2
  RUFF_CMD=("$RUFF")
elif command -v ruff >/dev/null 2>&1 && [[ "$(ruff --version 2>/dev/null)" == "ruff $VERSION" ]]; then
  RUFF_CMD=(ruff)
elif command -v uvx >/dev/null 2>&1; then
  # The pin comes from the uv cache offline first. An online `uvx ruff@<pin>`
  # asks the index even when the pin is cached, and with PyPI out of reach that
  # call waited for minutes before it failed.
  if ! uvx --offline "ruff@$VERSION" --version >/dev/null 2>&1; then
    FETCH_TIMEOUT="${LINT_FETCH_TIMEOUT:-15}"
    echo "lint: ruff $VERSION is not in the uv cache, fetching it once (network timeout ${FETCH_TIMEOUT}s)." >&2
    # uv applies these per request. The values set here win over the shell's,
    # so a long global UV_HTTP_TIMEOUT cannot bring the hang back.
    if ! UV_HTTP_TIMEOUT="$FETCH_TIMEOUT" UV_HTTP_CONNECT_TIMEOUT="$FETCH_TIMEOUT" UV_HTTP_RETRIES=0 \
        uvx "ruff@$VERSION" --version >/dev/null; then
      echo "lint: could not fetch ruff $VERSION: the package index is out of reach or refused it." >&2
      echo "      Run 'uvx ruff@$VERSION --version' once with the network up; after that lint works offline." >&2
      exit 2
    fi
  fi
  RUFF_CMD=(uvx --offline "ruff@$VERSION")
else
  echo "lint: no ruff $VERSION available." >&2
  if command -v ruff >/dev/null 2>&1; then
    echo "      Installed ruff is $(ruff --version)." >&2
  fi
  echo "      Install the pin with: pip install -r $PIN_FILE" >&2
  echo "      Or install uv, and this script runs 'uvx ruff@$VERSION' for you." >&2
  exit 2
fi

exec "${RUFF_CMD[@]}" check "$@" .
