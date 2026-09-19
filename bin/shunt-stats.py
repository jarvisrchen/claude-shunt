#!/usr/bin/env python3
"""shunt stats [--since 7d|24h|all] [--session ID] [--last N]  Summarise ~/.config/shunt/log.jsonl.
Events: block (hook refused a big read), slice (targeted read of a big file), delegate (Claude ran
bulk-read/code-write), call (the worker model ran, with token counts)."""
import argparse, os, sys, time
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib; shlog = importlib.import_module("shunt-log")

UNITS = {"h": 3600, "d": 86400, "w": 604800}

def since_arg(s):
    if s == "all":
        return None
    return time.time() - int(s[:-1]) * UNITS[s[-1]]

def agent_key(r):
    a = r.get("agent_type") or r.get("agent_id")
    return f"{a}" if a else "main"

def short(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"

def table(rows, headers):
    rows = [[str(c) for c in row] for row in rows]
    w = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    print("  ".join(h.ljust(w[i]) for i, h in enumerate(headers)))
    for r in rows:
        print("  ".join(c.ljust(w[i]) for i, c in enumerate(r)))

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
    tin = sum(r.get("tokens_in", 0) for r in calls)
    tout = sum(r.get("tokens_out", 0) for r in calls)
    blocks = kinds["block"]
    print(f"shunt telemetry, last {a.since}, {len(ev)} events, {len({r.get('session_id') for r in ev})} sessions")
    print(f"  blocks {blocks}  slices {kinds['slice']}  delegates {kinds['delegate']}  worker calls {len(calls)}")
    if blocks:
        print(f"  after a block Claude delegated {kinds['delegate'] / blocks:.0%} of the time, sliced {kinds['slice'] / blocks:.0%}")
    print(f"  routed to workers: {tin:,} tokens read by Gemini/MiniMax, {tout:,} returned to Claude, net {tin - tout:,} kept out of Claude (exact)")
    # ponytail: 10 tokens/line is a rough code average; the hook never sees the file's token count
    sliced = [r for r in ev if r["event"] == "slice"]
    est = sum(r.get("lines", 0) - (r.get("limit") or 0) for r in sliced) * 10
    if sliced:
        print(f"  sliced instead of whole-file: {len(sliced)} reads, about {est:,} tokens avoided (estimate at 10 tokens/line)")

    if calls:
        print("\nby provider")
        prov = defaultdict(lambda: [0, 0, 0, 0.0])
        for r in calls:
            p = prov[f"{r.get('cmd')}/{r.get('provider')}"]
            p[0] += 1; p[1] += r.get("tokens_in", 0); p[2] += r.get("tokens_out", 0); p[3] += r.get("seconds", 0)
        table([[k, v[0], f"{v[1]:,}", f"{v[2]:,}", f"{v[3] / v[0]:.1f}s"] for k, v in sorted(prov.items())],
              ["cmd/provider", "calls", "in", "out", "avg time"])

    hook_ev = [r for r in ev if r["event"] in ("block", "slice", "delegate")]
    if hook_ev:
        print("\nby agent (who hit the hook)")
        ag = defaultdict(Counter)
        for r in hook_ev:
            ag[agent_key(r)][r["event"]] += 1
        table([[k, c["block"], c["slice"], c["delegate"]] for k, c in sorted(ag.items(), key=lambda kv: -sum(kv[1].values()))],
              ["agent", "blocks", "slices", "delegates"])

        print("\nby session")
        se = defaultdict(Counter)
        tok = Counter()
        for r in ev:
            s = (r.get("session_id") or "?")[:8]
            se[s][r["event"]] += 1
            if r["event"] == "call":
                tok[s] += r.get("tokens_in", 0)
        rows = sorted(se.items(), key=lambda kv: -sum(kv[1].values()))[:15]
        table([[s, c["block"], c["slice"], c["delegate"], c["call"], f"{tok[s]:,}"] for s, c in rows],
              ["session", "blocks", "slices", "delegates", "calls", "worker in"])

        print("\nmost blocked files")
        files = Counter()
        for r in ev:
            if r["event"] == "block":
                for p in r.get("paths", []):
                    files[p] += 1
        table([[n, short(p, 90)] for p, n in files.most_common(10)], ["n", "path"])

    if a.last:
        print(f"\nlast {a.last} events")
        for r in ev[-a.last:]:
            t = time.strftime("%m-%d %H:%M", time.localtime(r["ts"]))
            what = r.get("cmd") or ",".join(short(p, 40) for p in r.get("paths", []))
            extra = f"{r.get('tokens_in', 0)}/{r.get('tokens_out', 0)} tok" if r["event"] == "call" else f"{r.get('lines', '')} lines"
            print(f"  {t} {r['event']:<8} {agent_key(r):<12} {what} {extra}")

if __name__ == "__main__":
    main()
