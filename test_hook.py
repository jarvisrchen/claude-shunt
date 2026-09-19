#!/usr/bin/env python3
"""Smallest check that fails if the hook's allow/block logic breaks. Run: python3 test_hook.py"""
import json, os, subprocess, tempfile
HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "shunt-hook.py")
big = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False); big.write("x\n" * 400); big.close()
small = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False); small.write("x\n" * 10); small.close()
LOG = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
os.environ["SHUNT_LOG"] = LOG
def run(tool, inp, env=None):
    r = subprocess.run(["python3", HOOK], input=json.dumps({"tool_name": tool, "tool_input": inp, "session_id": "s1", "agent_type": "Explore"}),
                       capture_output=True, text=True, env={**os.environ, **(env or {})})
    return r.returncode
cases = [
    (run("Read", {"file_path": big.name}), 2, "Read big blocks"),
    (run("Read", {"file_path": big.name, "offset": 1, "limit": 5}), 0, "Read with offset allowed"),
    (run("Read", {"file_path": small.name}), 0, "Read small allowed"),
    (run("Bash", {"command": f"cat {big.name}"}), 2, "cat big blocks"),
    (run("Bash", {"command": f"rtk cat {big.name}"}), 2, "rtk cat big blocks"),
    (run("Bash", {"command": f"cat {big.name} | grep x"}), 0, "piped cat allowed"),
    (run("Bash", {"command": f"head -n 20 {big.name}"}), 0, "head -n allowed"),
    (run("Bash", {"command": f"sed -n '1,5p' {big.name}"}), 0, "sed slice allowed"),
    (run("Read", {"file_path": big.name}, {"SHUNT_OFF": "1"}), 0, "SHUNT_OFF disables"),
    (run("Read", {"file_path": big.name}, {"SHUNT_MIN_LINES": "1000"}), 0, "threshold env respected"),
    (run("Bash", {"command": f"bulk-read --question 'what' --paths {big.name}"}), 0, "bulk-read call allowed"),
]
off = os.path.expanduser("~/.config/shunt/off"); had = os.path.exists(off)
open(off, "w").close()
cases.append((run("Read", {"file_path": big.name}), 0, "shunt off file disables"))
if not had: os.unlink(off)
for got, want, name in cases:
    assert got == want, f"{name}: exit {got}, wanted {want}"
os.unlink(big.name); os.unlink(small.name)
events = [json.loads(l) for l in open(LOG)]
kinds = [e["event"] for e in events]
assert kinds.count("block") == 3 and kinds.count("slice") == 1 and kinds.count("delegate") == 1, kinds
assert events[0]["session_id"] == "s1" and events[0]["agent_type"] == "Explore" and events[0]["lines"] == 400, events[0]
STATS = os.path.join(os.path.dirname(HOOK), "shunt-stats.py")
out = subprocess.run(["python3", STATS, "--since", "all"], capture_output=True, text=True).stdout
assert "Blocked reads:     3" in out and "Explore" in out, out
os.unlink(LOG)
print(f"ok: {len(cases)} hook cases, {len(events)} log events, stats renders")
