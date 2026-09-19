#!/usr/bin/env python3
"""shunt stats [--since 7d|24h|all] [--session ID] [--last N]  Summarise ~/.config/shunt/log.jsonl.
Events: block (hook refused a big read), slice (targeted read of a big file), delegate (Claude ran
bulk-read/code-write), call (the worker model ran, with token counts)."""
import argparse, os, sys, time
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib; shlog = importlib.import_module("shunt-log")

UNITS = {"h": 3600, "d": 86400, "w": 604800}
W = 72

def since_arg(s):
    return None if s == "all" else time.time() - int(s[:-1]) * UNITS[s[-1]]

def agent_key(r):
    return r.get("agent_type") or r.get("agent_id") or "main"

def short(s, n):
    return s if len(s) <= n else "…" + s[-(n - 1):]

def k(n):
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.1f}K" if n >= 1e3 else str(n)

def meter(frac, width=24):
    filled = int(round(max(0.0, min(1.0, frac)) * width))
    return "█" * filled + "░" * (width - filled)

def section(title):
    print(f"\n{title}\n" + "─" * W)

def table(rows, headers, right=()):
    rows = [[str(c) for c in row] for row in rows]
    w = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    fmt = lambda r: "  ".join((c.rjust(w[i]) if i in right else c.ljust(w[i])) for i, c in enumerate(r))
    print(fmt(headers))
    for r in rows:
        print(fmt(r))

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="7d", help="7d, 24h, 2w, or all")
    ap.add_argument("--session", help="only this session id (prefix ok)")
    ap.add_argument("--last", type=int, default=0, help="also print the last N raw events")
    a = ap.parse_args(argv)
    ev = list(shlog.read(since_arg(a.since)))
    if a.session:
        ev = [r for r in ev if (r.get("session_id") or "").startswith(a.session)]
    if not ev:
        print(f"no events in {shlog.path()} for --since {a.since}")
        return
    kinds = Counter(r["event"] for r in ev)
    calls = [r for r in ev if r["event"] == "call"]
    sliced = [r for r in ev if r["event"] == "slice"]
    tin = sum(r.get("tokens_in", 0) for r in calls)
    tout = sum(r.get("tokens_out", 0) for r in calls)
    # ponytail: 10 tokens/line is a rough code average; the hook never sees the file's token count
    est = sum(r.get("lines", 0) - (r.get("limit") or 0) for r in sliced) * 10
    frac = (tin - tout) / tin if tin else 0.0

    print(f"Shunt Telemetry (last {a.since}, {len({r.get('session_id') for r in ev})} sessions)")
    print("═" * W)
    print(f"Blocked reads:     {kinds['block']}")
    print(f"Delegated:         {kinds['delegate']}   (worker calls {len(calls)})")
    print(f"Sliced instead:    {kinds['slice']}")
    print(f"Worker read:       {k(tin)} tokens")
    print(f"Returned to Claude:{k(tout):>7} tokens")
    print(f"Kept out of Claude:{k(tin - tout):>7} tokens ({frac:.1%}, exact)")
    print(f"Slices avoided:   ~{k(est)} tokens (estimate, 10 tok/line)")
    print(f"Delegation meter:  {meter(frac)} {frac:.1%}")

    if calls:
        section("By Provider")
        prov = defaultdict(lambda: [0, 0, 0, 0.0])
        for r in calls:
            p = prov[f"{r.get('cmd')} {r.get('provider')}"]
            p[0] += 1; p[1] += r.get("tokens_in", 0); p[2] += r.get("tokens_out", 0); p[3] += r.get("seconds", 0)
        table([[n, v[0], k(v[1]), k(v[2]), f"{1 - v[2] / v[1]:.1%}" if v[1] else "-", f"{v[3] / v[0]:.1f}s",
                meter((v[1] - v[2]) / max(tin - tout, 1), 10)] for n, v in sorted(prov.items(), key=lambda kv: -kv[1][1])],
              ["Provider", "Calls", "In", "Out", "Saved%", "Avg", "Share"], right={1, 2, 3, 4, 5})

    hook_ev = [r for r in ev if r["event"] in ("block", "slice", "delegate")]
    if hook_ev:
        section("By Agent")
        ag = defaultdict(Counter)
        for r in hook_ev:
            ag[agent_key(r)][r["event"]] += 1
        table([[n, c["block"], c["delegate"], c["slice"]] for n, c in sorted(ag.items(), key=lambda kv: -sum(kv[1].values()))],
              ["Agent", "Blocks", "Delegates", "Slices"], right={1, 2, 3})

        section("By Session")
        se = defaultdict(Counter); tok = Counter()
        for r in ev:
            s = (r.get("session_id") or "?")[:8]
            se[s][r["event"]] += 1
            if r["event"] == "call":
                tok[s] += r.get("tokens_in", 0) - r.get("tokens_out", 0)
        rows = sorted(se.items(), key=lambda kv: -tok[kv[0]])[:15]
        table([[s, c["block"], c["delegate"], c["slice"], c["call"], k(tok[s])] for s, c in rows],
              ["Session", "Blocks", "Delegates", "Slices", "Calls", "Kept out"], right={1, 2, 3, 4, 5})

        section("Most Blocked Files")
        files = Counter(p for r in ev if r["event"] == "block" for p in r.get("paths", []))
        table([[n, short(p, 60)] for p, n in files.most_common(10)], ["N", "Path"], right={0})

    if a.last:
        section(f"Last {a.last} Events")
        for r in ev[-a.last:]:
            t = time.strftime("%m-%d %H:%M", time.localtime(r["ts"]))
            what = r.get("cmd") or ",".join(short(p, 40) for p in r.get("paths", []))
            extra = f"{r.get('tokens_in', 0)}/{r.get('tokens_out', 0)} tok" if r["event"] == "call" else f"{r.get('lines', '')} lines"
            print(f"{t}  {r['event']:<8} {agent_key(r):<10} {what}  {extra}")

if __name__ == "__main__":
    main()
