#!/usr/bin/env python3
"""Append-only JSONL telemetry shared by the hook and the scripts. One line per event.
SHUNT_LOG overrides the path (tests use it). Never raises: telemetry must not break a tool call."""
import json, os, time

def path():
    return os.environ.get("SHUNT_LOG") or os.path.expanduser("~/.config/shunt/log.jsonl")

def log(event, **fields):
    rec = {"ts": round(time.time(), 3), "event": event,
           "session_id": os.environ.get("CLAUDE_CODE_SESSION_ID"), **fields}
    try:
        p = path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a") as f:
            f.write(json.dumps({k: v for k, v in rec.items() if v not in (None, "", [])}) + "\n")
    except OSError:
        pass

def read(since=None):
    """Yield events newer than `since` (epoch seconds). Skips corrupt lines."""
    try:
        with open(path()) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if since is None or r.get("ts", 0) >= since:
                    yield r
    except OSError:
        return
