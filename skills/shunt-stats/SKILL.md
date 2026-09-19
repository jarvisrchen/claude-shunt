---
name: shunt-stats
description: Show claude-shunt telemetry (blocked reads, slices, delegations, worker token counts per provider, agent, and session). Use when the user asks how much shunt is being used or saving.
---

Print the report below to the user verbatim, inside one fenced code block, with no summary before or after it. Arguments pass through (`--since 7d|24h|all`, `--session ID`, `--last N`).

```
!`shunt stats $ARGUMENTS`
```

If the user then asks what the events mean: block = the hook refused a whole-file read over the threshold, slice = a targeted read of a big file went through, delegate = Claude ran bulk-read or code-write, call = the worker model ran and these are its tokens.
