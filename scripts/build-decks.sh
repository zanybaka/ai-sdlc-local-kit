#!/usr/bin/env bash
# Regenerate the presentation decks from their docs/*.build.js generators.
#
# On-demand build tool — deliberately NOT wired into pre-push/CI, so it adds no
# enforced dependency (honors AGENTS.md "Ask first: new dependencies"). The decks
# (.pptx/.pdf) are gitignored build artifacts; only the *.build.js generators are
# tracked. Run it directly:
#
#   scripts/build-decks.sh              # rebuild every docs/*.build.js
#   scripts/build-decks.sh ai-sdlc      # rebuild only generators matching "ai-sdlc"
#
# Needs Node (pptxgenjs is auto-installed once into a gitignored .deck-build/).
# PDF rendering also needs LibreOffice (soffice); without it, only .pptx is produced.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCS="$REPO/docs"
BUILD="$REPO/.deck-build"
PATTERN="${1:-}"

command -v node >/dev/null 2>&1 || { echo "✗ node not found — install Node.js first" >&2; exit 1; }

mkdir -p "$BUILD"
if [ ! -d "$BUILD/node_modules/pptxgenjs" ]; then
  echo "→ installing pptxgenjs into .deck-build/ (one-time)…"
  ( cd "$BUILD" && npm install --silent --no-fund --no-audit pptxgenjs >/dev/null )
fi

SOFFICE=""
if command -v soffice >/dev/null 2>&1; then
  SOFFICE="soffice"
elif [ -x "/Applications/LibreOffice.app/Contents/MacOS/soffice" ]; then
  SOFFICE="/Applications/LibreOffice.app/Contents/MacOS/soffice"
fi
[ -z "$SOFFICE" ] && echo "⚠ LibreOffice (soffice) not found — producing .pptx only, no .pdf" >&2

shopt -s nullglob
built=0
for gen in "$DOCS"/*.build.js; do
  base="$(basename "$gen" .build.js)"
  if [ -n "$PATTERN" ] && [[ "$base" != *"$PATTERN"* ]]; then continue; fi
  echo "→ $base"
  ( cd "$BUILD" && NODE_PATH="$BUILD/node_modules" node "$gen" >/dev/null )
  cp "$BUILD/$base.pptx" "$DOCS/$base.pptx"
  if [ -n "$SOFFICE" ]; then
    ( cd "$BUILD" && "$SOFFICE" --headless "-env:UserInstallation=file://$BUILD/.lo-profile" \
        --convert-to pdf --outdir "$BUILD" "$base.pptx" >/dev/null 2>&1 )
    cp "$BUILD/$base.pdf" "$DOCS/$base.pdf"
  fi
  built=$((built + 1))
done

if [ "$built" -eq 0 ]; then
  echo "✗ no generators matched${PATTERN:+ \"$PATTERN\"} in docs/*.build.js" >&2
  exit 1
fi
echo "✓ rebuilt $built deck(s) → docs/ (.pptx$([ -n "$SOFFICE" ] && echo " + .pdf"))"
echo "  decks are gitignored build artifacts; generators are tracked"
