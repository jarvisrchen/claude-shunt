# claude-shunt

Cuts Claude Code token spend by routing big file reads and boilerplate generation to a cheap worker model.
A local reimplementation of the pattern in Spotify's "Portal cut my Claude Code token usage by 90%" (design and measurements in [DESIGN.md](DESIGN.md)).

## What it does

- `bin/shunt-hook.py`: a PreToolUse hook. Blocks `Read` and bash `cat`/`head`/`tail`/`less`/`more` on files over `SHUNT_MIN_LINES` (default 350) with a message telling Claude to use `bulk-read` or a targeted slice instead. Offset/limit reads, `head -n`, `sed -n`, and piped commands pass through.
- `bin/bulk-read`: `--question Q --paths f1 f2`. Wraps the files in XML tags, asks Gemini Flash, prints bullets. The files never enter Claude's context.
- `bin/code-write`: `--spec S --reference f [--target out]`. Generates code matching the reference files with MiniMax. With `--target`, output goes straight to disk.
- `bin/shunt-llm.py`: the shared caller. Stdlib only, Gemini and MiniMax providers.
- `bin/shunt`: `shunt on|off|status`. Off means Claude reads everything itself; takes effect on the next tool call in every running session.

## Install

```bash
ln -sf ~/Documents/code/claude-shunt/bin/bulk-read ~/.local/bin/bulk-read
ln -sf ~/Documents/code/claude-shunt/bin/code-write ~/.local/bin/code-write
ln -sf ~/Documents/code/claude-shunt/bin/shunt ~/.local/bin/shunt
```

Keys in `~/.config/shunt/env` (mode 600, never committed):

```
GEMINI_API_KEY=...
MINIMAX_API_KEY=...
```

Hook entry in `~/.claude/settings.json` under `hooks.PreToolUse`:

```json
{"matcher": "Read|Bash", "hooks": [{"type": "command", "command": "python3 \"/Users/rchen/Documents/code/claude-shunt/bin/shunt-hook.py\"", "timeout": 5}]}
```

Skill file at `~/.claude/skills/shunt/SKILL.md` tells Claude when and how to call the two commands.

## Knobs

| env var | effect |
|---|---|
| `SHUNT_MIN_LINES` | line threshold, default 350 |
| `shunt off` / `shunt on` | disable or re-enable the hook (file toggle, no restart) |
| `SHUNT_OFF=1` | same, as an env var for one process |
| `SHUNT_READ_PROVIDER` | default `gemini-3.6-flash`; also `gemini-3.5-flash-lite`, `minimax` |
| `SHUNT_WRITE_PROVIDER` | default `minimax` (MiniMax-M3); also `minimax:MiniMax-M2.5`, `gemini-3.6-flash` |

## Test

```bash
python3 ~/Documents/code/claude-shunt/test_hook.py
bulk-read --question "What does this file do?" --paths ~/Documents/code/_vault/site/build.mjs
```
