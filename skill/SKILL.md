---
name: shunt
description: Delegate large file reads and boilerplate generation to a cheap worker model instead of spending Claude tokens. Use when a Read or cat is blocked by the shunt hook, when you need the gist of files over ~350 lines, or when generating tests/config/stubs that mirror an existing file.
---

# shunt: bulk-read and code-write

## `/shunt <args>` runs `shunt <args>`

Same subcommands as the CLI, same arguments. The block below is the output of `shunt $ARGUMENTS` (with no arguments: `shunt status`).

```
!`shunt $ARGUMENTS`
```

Relay that block to the user verbatim in one fenced code block, then stop. Two exceptions:

- `config pick [read|write]`: the block is a numbered model list. Use AskUserQuestion to let the user choose, first the vendor (only those with a key), then the model within it (newest first, at most four options; any other id via Other). Then run `shunt config <read|write> <chosen model>` and relay its output.
- no arguments: after the status line, the user probably wants the guide below, so answer their question from it.

```bash
shunt status | on | off                  # the hook: state, enable, disable (no restart)
shunt stats [--since 7d|all] [--last N]  # telemetry: blocks, delegations, tokens kept out of Claude, per provider/agent/session
shunt config                             # show providers, threshold, which keys are set
shunt config read gemini-3.8-flash       # default worker for bulk-read; runs a test call before saving
shunt config write minimax               # default worker for code-write
shunt config threshold 500               # block whole-file reads over this many lines
shunt config key gemini <key>            # store an API key: gemini | minimax | deepseek | anthropic
shunt config models [gemini]             # list the models each vendor offers, in the form read/write accept
shunt config pick [read|write]           # choose one from a menu
shunt log [N]                            # tail the raw telemetry
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
