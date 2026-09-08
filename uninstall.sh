#!/usr/bin/env bash
# Remove claude-shunt from this machine. Leaves ~/.config/shunt/env (your keys) in place.
set -euo pipefail
SETTINGS="$HOME/.claude/settings.json"
rm -f "$HOME/.local/bin/bulk-read" "$HOME/.local/bin/code-write" "$HOME/.local/bin/shunt" "$HOME/.claude/skills/shunt"
[ -f "$SETTINGS" ] && python3 - "$SETTINGS" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
pre = d.get("hooks", {}).get("PreToolUse", [])
pre[:] = [e for e in pre if not any("shunt-hook" in h.get("command", "") for h in e.get("hooks", []))]
json.dump(d, open(p, "w"), indent=2); open(p, "a").write("\n"); print("hook removed")
PY
echo "done. Restart open Claude Code sessions."
