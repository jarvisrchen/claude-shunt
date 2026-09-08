#!/usr/bin/env python3
"""PreToolUse hook: block big reads and point Claude at bulk-read.
Exit 2 + stderr = block with the message fed back to Claude. Exit 0 = allow.
Set SHUNT_OFF=1 to disable. SHUNT_MIN_LINES (default 350) is the threshold."""
import json, os, re, shlex, sys

MIN = int(os.environ.get("SHUNT_MIN_LINES", "350"))
READ_CMDS = {"cat", "head", "tail", "less", "more"}

def lines_in(path):
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0

def block(paths, n):
    files = " ".join(shlex.quote(p) for p in paths)
    sys.stderr.write(
        f"shunt: {n} lines is over SHUNT_MIN_LINES={MIN}. Do not read this whole file into context. "
        f"Either read a targeted slice (Read with offset/limit, or sed -n 'A,Bp'), or delegate:\n"
        f"  bulk-read --question \"<what you need to know>\" --paths {files}\n"
        f"bulk-read returns bullets from a cheap worker model; the file never enters your context. "
        f"For editing, ask bulk-read which function/section to look at, then do a targeted Read of just that.\n")
    sys.exit(2)

def main():
    if os.environ.get("SHUNT_OFF"):
        return
    d = json.load(sys.stdin)
    tool, inp = d.get("tool_name"), d.get("tool_input", {})
    if tool == "Read":
        if inp.get("offset") is not None or inp.get("limit") is not None:
            return
        p = inp.get("file_path", "")
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
