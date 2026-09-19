#!/usr/bin/env python3
"""Status line wrapper: shunt-statusline.py -- <your existing statusline command...>
Reads Claude Code's status JSON from stdin, runs the wrapped command on it, appends this session's
shunt counters: blocked reads, delegations, worker tokens kept out of context. With no wrapped
command it prints just the shunt segment."""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib; shlog = importlib.import_module("shunt-log")

raw = sys.stdin.read()
try:
    sid = json.loads(raw).get("session_id", "")
except ValueError:
    sid = ""
inner = sys.argv[2:] if len(sys.argv) > 2 and sys.argv[1] == "--" else sys.argv[1:]
base = ""
if inner:
    try:
        base = subprocess.run(inner, input=raw, capture_output=True, text=True, timeout=5).stdout.rstrip("\n")
    except (OSError, subprocess.TimeoutExpired):
        pass

blocks = delegates = tok = 0
if sid:
    for r in shlog.read():
        if r.get("session_id") != sid:
            continue
        e = r["event"]
        if e == "block": blocks += 1
        elif e == "delegate": delegates += 1
        elif e == "call": tok += r.get("tokens_in", 0)
off = os.path.exists(os.path.expanduser("~/.config/shunt/off"))
seg = "shunt off" if off else f"shunt {blocks}⛔ {delegates}↘ {tok // 1000}k"
print(f"{base} · \033[2m{seg}\033[0m" if base else seg)
