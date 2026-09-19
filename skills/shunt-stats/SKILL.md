---
name: shunt-stats
description: Show claude-shunt telemetry (blocked reads, slices, delegations, worker token counts per provider, agent, and session). Use when the user asks how much shunt is being used or saving.
---

Report from `~/.config/shunt/log.jsonl`, arguments pass through (`--since 7d|24h|all`, `--session ID`, `--last N`):

```
!`shunt stats $ARGUMENTS`
```

Relay the numbers to the user as they are. Explain the events if asked: block = the hook refused a whole-file read over the threshold, slice = a targeted read of a big file went through, delegate = Claude ran bulk-read or code-write, call = the worker model ran and these are its tokens.
