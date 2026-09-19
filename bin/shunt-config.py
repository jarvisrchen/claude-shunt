#!/usr/bin/env python3
"""shunt config                      show providers, threshold, which keys are set
shunt config read <provider>      default worker for bulk-read   (gemini-3.8-flash, minimax, deepseek, claude, ...)
shunt config write <provider>     default worker for code-write
shunt config threshold <lines>    whole-file reads over this many lines get blocked
shunt config key <vendor> <key>   store an API key: gemini | minimax | deepseek | anthropic
Edits ~/.config/shunt/env in place. Setting a provider runs a one-line test call against it."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib; llm = importlib.import_module("shunt-llm")

ENV = llm.ENV
VENDORS = {"gemini": "GEMINI_API_KEY", "minimax": "MINIMAX_API_KEY", "deepseek": "DEEPSEEK_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
PREFIXES = ("gemini", "minimax", "deepseek", "claude")
VARS = {"read": "SHUNT_READ_PROVIDER", "write": "SHUNT_WRITE_PROVIDER", "threshold": "SHUNT_MIN_LINES"}
DEFAULTS = {"SHUNT_READ_PROVIDER": "gemini-3.6-flash", "SHUNT_WRITE_PROVIDER": "minimax", "SHUNT_MIN_LINES": "350"}

def set_var(name, value):
    lines = open(ENV).read().splitlines() if os.path.exists(ENV) else []
    pat = re.compile(rf"^#?\s*{name}=")
    new = f"{name}={value}"
    hit = [i for i, l in enumerate(lines) if pat.match(l)]
    if hit:
        lines[hit[0]] = new
        for i in hit[1:]:
            lines[i] = "#" + lines[i].lstrip("#")
    else:
        lines.append(new)
    os.makedirs(os.path.dirname(ENV), exist_ok=True)
    open(ENV, "w").write("\n".join(lines) + "\n")
    os.chmod(ENV, 0o600)

def vendor_of(provider):
    return "anthropic" if provider.startswith("claude") else next(v for v in VENDORS if provider.startswith(v))

def show():
    llm.load_env()
    print(f"config file: {ENV}")
    for job, var in VARS.items():
        v = os.environ.get(var, DEFAULTS[var])
        tag = "" if os.environ.get(var) else "  (default)"
        print(f"  {job:<10} {v}{tag}")
    print("keys:")
    for vendor, var in VENDORS.items():
        k = os.environ.get(var, "")
        print(f"  {vendor:<10} {k[:6] + '…' if k else 'not set'}")

def test(provider):
    try:
        text, pin, pout = llm.call(provider, "Reply with the single word ok.", "ping", timeout=60)
    except SystemExit as e:
        print(f"test call FAILED: {e}")
        return False
    print(f"test call ok: {provider} answered {text.strip()[:20]!r} ({pin} in / {pout} out)")
    return True

def main(argv):
    if not argv:
        return show()
    cmd, args = argv[0], argv[1:]
    if cmd in ("read", "write") and len(args) == 1:
        p = args[0]
        if not p.startswith(PREFIXES):
            sys.exit(f"unknown provider {p!r}: use gemini-<model>, minimax[:<model>], deepseek[:<model>], claude[:<model>]")
        llm.load_env()
        if not os.environ.get(VENDORS[vendor_of(p)]):
            sys.exit(f"no key for {vendor_of(p)}: run  shunt config key {vendor_of(p)} <key>  first")
        if not test(p):
            sys.exit(1)
        set_var(VARS[cmd], p)
        print(f"{cmd} provider = {p}  (takes effect on the next call)")
    elif cmd == "threshold" and len(args) == 1 and args[0].isdigit():
        set_var(VARS[cmd], args[0])
        print(f"threshold = {args[0]} lines  (takes effect on the next tool call)")
    elif cmd == "key" and len(args) == 2 and args[0] in VENDORS:
        set_var(VENDORS[args[0]], args[1])
        print(f"{VENDORS[args[0]]} saved")
    else:
        sys.exit(__doc__)

if __name__ == "__main__":
    main(sys.argv[1:])
