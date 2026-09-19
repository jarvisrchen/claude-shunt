#!/usr/bin/env bash
# Install claude-shunt on this machine. Idempotent: safe to re-run after git pull.
# Needs: python3, Claude Code, a Gemini key and a MiniMax key.
# Two ways to run it:
#   from a clone:      ./install.sh
#   without a clone:   curl -fsSL https://raw.githubusercontent.com/jarvisrchen/claude-shunt/main/install.sh | bash
# The second clones into $SHUNT_HOME (default ~/.claude-shunt) and continues from there.
set -euo pipefail
case "$(uname -s)" in Darwin|Linux) ;; *) echo "claude-shunt supports macOS and Linux (needs symlinks and ~/.local/bin). On Windows use WSL."; exit 1;; esac
for tool in git python3; do command -v "$tool" >/dev/null || { echo "missing: $tool. Install it and re-run. (macOS: xcode-select --install)"; exit 1; }; done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' || { echo "python3 is $(python3 -V 2>&1); need 3.8+"; exit 1; }
[ -d "$HOME/.claude" ] || echo "note: ~/.claude not found. Install Claude Code first (https://claude.com/claude-code) or the hook has nowhere to go; continuing anyway."
REPO="https://github.com/jarvisrchen/claude-shunt"
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/bin/shunt-hook.py" ]; then
  HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
  HERE="${SHUNT_HOME:-$HOME/.claude-shunt}"
  if [ -d "$HERE/.git" ]; then git -C "$HERE" pull -q --ff-only; echo "updated $HERE"
  else git clone -q "$REPO" "$HERE"; echo "cloned into $HERE"; fi
fi
BIN="$HOME/.local/bin"; CFG="$HOME/.config/shunt"; SETTINGS="$HOME/.claude/settings.json"

mkdir -p "$BIN" "$CFG" "$HOME/.claude/skills"
for f in bulk-read code-write shunt; do ln -sf "$HERE/bin/$f" "$BIN/$f"; done
ln -sfn "$HERE/skill" "$HOME/.claude/skills/shunt"

if [ ! -f "$CFG/env" ]; then
  umask 077; cat > "$CFG/env" <<'ENV'
# Keys. Fill in the ones for the providers you use; leave the others blank.
GEMINI_API_KEY=
MINIMAX_API_KEY=

# Which model handles each job. Uncomment to override the defaults.
# Any gemini-* model name, or minimax (= MiniMax-M3), or minimax:<model>.
#SHUNT_READ_PROVIDER=gemini-3.6-flash
#SHUNT_WRITE_PROVIDER=minimax
ENV
  echo "created $CFG/env: fill in your key(s) and pick providers"
fi

python3 - "$SETTINGS" "$HERE" <<'PY'
import json, os, sys
path, here = sys.argv[1], sys.argv[2]
d = json.load(open(path)) if os.path.exists(path) else {}
pre = d.setdefault("hooks", {}).setdefault("PreToolUse", [])
pre[:] = [e for e in pre if not any("shunt-hook" in h.get("command", "") for h in e.get("hooks", []))]
pre.insert(0, {"matcher": "Read|Bash", "hooks": [{"type": "command",
    "command": f'python3 "{here}/bin/shunt-hook.py"', "timeout": 5, "statusMessage": "shunt: checking read size"}]})
json.dump(d, open(path, "w"), indent=2); open(path, "a").write("\n")
print(f"hook installed in {path}")
PY

case ":$PATH:" in *":$BIN:"*) ;; *) echo "add $BIN to PATH (e.g. export PATH=\"\$HOME/.local/bin:\$PATH\" in ~/.zshrc)";; esac
python3 "$HERE/test_hook.py"
echo "done. Restart open Claude Code sessions, then: shunt status"
