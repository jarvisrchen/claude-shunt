#!/usr/bin/env python3
"""PreToolUse hook: block big reads and point Claude at bulk-read.
Exit 2 + stderr = block with the message fed back to Claude. Exit 0 = allow.
Disable with `shunt off` (touches ~/.config/shunt/off) or SHUNT_OFF=1. SHUNT_MIN_LINES (default 350) is the threshold."""
import json, os, re, shlex, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib; shlog = importlib.import_module("shunt-log")

def _env_file(name):
    try:
        for line in open(os.path.expanduser("~/.config/shunt/env")):
            if line.startswith(name + "="):
                return line.split("=", 1)[1].split(" #", 1)[0].strip()
    except OSError:
        pass

MIN = int(os.environ.get("SHUNT_MIN_LINES") or _env_file("SHUNT_MIN_LINES") or 350)
READ_CMDS = {"cat", "head", "tail", "less", "more"}

def lines_in(path):
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0

CTX = {}  # session/agent fields from the hook payload, attached to every event

def block(paths, n):
    shlog.log("block", paths=paths, lines=n, **CTX)
    files = " ".join(shlex.quote(p) for p in paths)
    sys.stderr.write(
        f"shunt: {n} lines is over SHUNT_MIN_LINES={MIN}. Do not read this whole file into context. "
        f"Either read a targeted slice (Read with offset/limit, or sed -n 'A,Bp'), or delegate:\n"
        f"  bulk-read --question \"<what you need to know>\" --paths {files}\n"
        f"bulk-read returns bullets from a cheap worker model; the file never enters your context. "
        f"For editing, ask bulk-read which function/section to look at, then do a targeted Read of just that. "
        f"If the user wants Claude to read everything itself, run: shunt off\n")
    sys.exit(2)

def main():
    if os.environ.get("SHUNT_OFF") or os.path.exists(os.path.expanduser("~/.config/shunt/off")):
        return
    d = json.load(sys.stdin)
    tool, inp = d.get("tool_name"), d.get("tool_input", {})
    CTX.update({k: d.get(k) for k in ("session_id", "agent_id", "agent_type", "cwd")})
    CTX["tool"] = tool
    if tool == "Read":
        p = inp.get("file_path", "")
        if inp.get("offset") is not None or inp.get("limit") is not None:
            n = lines_in(p)
            if n > MIN:
                shlog.log("slice", paths=[p], lines=n, limit=inp.get("limit"), **CTX)
            return
        if p.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ipynb")):
            return
        n = lines_in(p)
        if n > MIN:
            block([p], n)
    elif tool == "Bash":
        cmd = inp.get("command", "")
        if "|" in cmd or ">" in cmd:
            return  # piped or redirected: targeted, or output not entering context
        try:
            toks = shlex.split(cmd)
        except ValueError:
            return
        if not toks:
            return
        if toks[0] in ("bulk-read", "code-write"):
            shlog.log("delegate", cmd=toks[0], args=cmd[:300], **CTX)
            return
        # rtk may have rewritten "cat f" to "rtk cat f"
        if toks[0] == "rtk" and len(toks) > 1:
            toks = toks[1:]
        if toks[0] not in READ_CMDS:
            return
        if toks[0] in ("head", "tail") and any(t.startswith("-") for t in toks[1:]):
            return  # head -n 50 is a targeted read
        paths = [t for t in toks[1:] if not t.startswith("-") and os.path.isfile(t)]
        total = sum(lines_in(p) for p in paths)
        if total > MIN:
            block(paths, total)

if __name__ == "__main__":
    main()
