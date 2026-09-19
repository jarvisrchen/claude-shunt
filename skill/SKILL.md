---
name: shunt
description: Delegate large file reads and boilerplate generation to a cheap worker model instead of spending Claude tokens. Use when a Read or cat is blocked by the shunt hook, when you need the gist of files over ~350 lines, or when generating tests/config/stubs that mirror an existing file.
---

# shunt: bulk-read and code-write

## Current configuration

```
!`shunt config $ARGUMENTS`
```

If the user invoked `/shunt` with arguments, the block above is the result of `shunt config <arguments>`: relay it verbatim in a code block, then stop.
To change a setting for the user, run one of these and relay the output:

```bash
shunt config read gemini-3.8-flash      # default worker for bulk-read; runs a test call before saving
shunt config write minimax              # default worker for code-write
shunt config threshold 500              # block whole-file reads over this many lines
shunt config key gemini <key>           # store an API key: gemini | minimax | deepseek | anthropic
```

A provider that fails its test call (bad key, unknown model) is refused and nothing changes.

Two commands, both on PATH. They call the read and write providers shown above; keys live in `~/.config/shunt/env`.

## bulk-read: understand big files without reading them

```bash
bulk-read --question "What does this service do and what does it call?" --paths src/Service.java src/Handler.java
bulk-read --question "Which function writes to the DB, and what does it validate first?" --paths src/Service.java
```

- Ask one specific question. Vague questions get long answers, which wastes the savings.
- Repeat with the same `--paths` for follow-ups. Files never enter your context, only the bullets do.
- Answers name files and symbols, not line numbers. To edit, ask which function or section to look at, then do a targeted `Read` with `offset`/`limit` of just that part.
- `--provider minimax` swaps the worker. Default is `gemini-3.6-flash`.

## code-write: boilerplate to disk

```bash
code-write --spec "Write tests for UserService, same style as the reference" --reference tests/OrderTest.java --target tests/UserTest.java
code-write --spec "Generate a config stub for the staging env" --reference config/prod.yaml
```

- A reference file is required; the worker matches its patterns.
- With `--target` the output goes straight to disk and you never see it. Verify it by running the tests or a targeted Read, not by reading the whole file.
- Without `--target` the code prints to stdout.

## What not to delegate

Debugging, architecture decisions, security-sensitive review, and anything where you need exact line numbers. The worker finds surface patterns and misses subtle bugs. Those are your job.

## Escape hatches

`shunt off` disables the hook for every session until `shunt on`; run it when the user says they want plain Claude for a while. `shunt status` shows the state. `shunt stats` reports blocks, delegations, and worker token counts per provider, agent, and session from `~/.config/shunt/log.jsonl`. `SHUNT_MIN_LINES=800` raises the threshold for one process.
