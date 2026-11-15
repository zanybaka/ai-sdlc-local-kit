#!/usr/bin/env bash
# Initialize/update third-party skill packs, then refresh shared skills links.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
UPDATE_REMOTE=0
INSTALL_TOOLS=0
CONFIG="$REPO/third-party-skills.json"
REPO_NAME="$(basename "$REPO")"
TOOL_VENV_ROOT="${AI_SDLC_KIT_TOOL_VENV_ROOT:-$HOME/.venv/$REPO_NAME}"

tool_path() {
  local name="$1" requires="$2"
  if command -v "$requires" >/dev/null 2>&1; then
    command -v "$requires"
    return 0
  fi
  if [[ -x "$TOOL_VENV_ROOT/$name/bin/$requires" ]]; then
    printf '%s\n' "$TOOL_VENV_ROOT/$name/bin/$requires"
    return 0
  fi
  if [[ -x "$TOOL_VENV_ROOT/$name/Scripts/$requires.exe" ]]; then
    printf '%s\n' "$TOOL_VENV_ROOT/$name/Scripts/$requires.exe"
    return 0
  fi
  return 1
}

install_python_tool() {
  local name="$1" python_package="$2" venv="$TOOL_VENV_ROOT/$name"
  if [[ ! -x "$venv/bin/python" && ! -x "$venv/Scripts/python.exe" ]]; then
    python3 -m venv "$venv"
  fi
  if [[ -x "$venv/bin/python" ]]; then
    "$venv/bin/python" -m pip install --upgrade pip
    "$venv/bin/python" -m pip install "$python_package"
  else
    "$venv/Scripts/python.exe" -m pip install --upgrade pip
    "$venv/Scripts/python.exe" -m pip install "$python_package"
  fi
}

for arg in "$@"; do
  case "$arg" in
    --remote)
      UPDATE_REMOTE=1
      echo "WARN: --remote pulls unreviewed upstream HEAD into third_party/ — review the resulting .gitmodules/gitlink diff before commit." >&2
      ;;
    --install-tools)
      INSTALL_TOOLS=1
      ;;
    -h|--help)
      echo "Usage: $0 [--remote] [--install-tools]"
      echo "  --remote         update submodules to their configured upstream branch before linking"
      echo "  --install-tools  install missing CLI tools declared in third-party-skills.json"
      echo "                  tools are installed under $TOOL_VENV_ROOT"
      exit 0
      ;;
    *)
      echo "error: unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

if [[ -f "$CONFIG" ]]; then
  while IFS=$'\t' read -r path repo; do
    if [[ ! -e "$REPO/$path" ]]; then
      git -C "$REPO" submodule add "$repo" "$path"
    fi
  done < <(python3 - "$CONFIG" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)

for pack in data.get("packs", []):
    path = pack.get("path", "")
    repo = pack.get("repo", "")
    if not path.startswith("third_party/"):
        raise SystemExit(f"invalid third-party path: {path}")
    if not (repo.startswith("https://") or repo.startswith("http://") or repo.startswith("git@")):
        raise SystemExit(f"invalid repo URL for {path}: {repo}")
    print(f"{path}\t{repo}")
PY
  )

  while IFS=$'\t' read -r name requires python_package dest command_json; do
    if [[ -f "$REPO/$dest/$name/SKILL.md" ]]; then
      continue
    fi
    if ! tool="$(tool_path "$name" "$requires")"; then
      if [[ "$INSTALL_TOOLS" -eq 1 && -n "$python_package" ]]; then
        install_python_tool "$name" "$python_package"
      fi
    fi
    if ! tool="$(tool_path "$name" "$requires")"; then
      echo "WARN: skipping installer '$name'; missing command: $requires" >&2
      continue
    fi
    python3 - "$REPO" "$requires" "$tool" "$command_json" <<'PY'
import json
import subprocess
import sys

repo = sys.argv[1]
requires = sys.argv[2]
tool = sys.argv[3]
command = json.loads(sys.argv[4])
if command and command[0] == requires:
    command[0] = tool
subprocess.run(command, cwd=repo, check=True)
PY
  done < <(python3 - "$CONFIG" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)

for installer in data.get("installers", []):
    name = installer.get("name", "")
    requires = installer.get("requires", "")
    python_package = installer.get("pythonPackage", "")
    dest = installer.get("dest", "")
    command = installer.get("command", [])
    if not name:
        raise SystemExit("installer missing name")
    if not requires:
        raise SystemExit(f"installer {name} missing requires")
    if not dest.startswith("third_party/"):
        raise SystemExit(f"invalid installer dest for {name}: {dest}")
    if not isinstance(command, list) or not command:
        raise SystemExit(f"installer {name} missing command")
    print(f"{name}\t{requires}\t{python_package}\t{dest}\t{json.dumps(command)}")
PY
  )
fi

if [[ -f "$REPO/.gitmodules" ]]; then
  if [[ "$UPDATE_REMOTE" -eq 1 ]]; then
    git -C "$REPO" submodule update --init --remote --recursive
  else
    git -C "$REPO" submodule update --init --recursive
  fi
fi

"$SCRIPT_DIR/link-third-party-skills.sh"

# pack skills this sync just filled get their Codex links in
# ~/.agents/skills too, without a second run of the link script.
if command -v python3 >/dev/null 2>&1; then
  python3 "$SCRIPT_DIR/link-codex-skills.py" \
    || echo "WARNING: Codex skills are not linked; run scripts/link-symbolic-folders.sh"
fi
