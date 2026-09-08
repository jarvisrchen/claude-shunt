#!/usr/bin/env bash
# Install claude-shunt on this machine. Idempotent: safe to re-run after git pull.
# Needs: python3, Claude Code, a Gemini key and a MiniMax key.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
