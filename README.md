# claude-shunt

Cuts Claude Code token spend by routing big file reads and boilerplate generation to a cheap worker model.
A local reimplementation of the pattern in Spotify's "Portal by Spotify cut my Claude Code token usage by 90%".
Measured on real files: a three-file read that costs Claude 12,505 tokens comes back as ~800 tokens of bullets, a 93.7% cut.
Design, measurements, and the provider bake-off are in [DESIGN.md](DESIGN.md).

## How it works

Three layers, same as Spotify's:

1. **Hook.** `bin/shunt-hook.py` runs before every `Read` and `Bash` call. A whole-file read over `SHUNT_MIN_LINES` (default 350) is blocked with a message that names the exact `bulk-read` command to run instead. Targeted reads pass: `offset`/`limit`, `head -n`, `sed -n`, anything piped or redirected, images and PDFs.
2. **Scripts.** `bulk-read` wraps the files in XML tags, asks Gemini 3.6 Flash a question, prints bullets. The files never enter Claude's context. `code-write` asks MiniMax M3 for code matching a reference file and writes it straight to disk, so Claude never sees the generated output either.
3. **Skill.** `skill/SKILL.md` tells Claude when to delegate, how to phrase the question, and what never to delegate: debugging, architecture, anything needing exact line numbers.

Everything is stdlib Python 3 and bash. No dependencies, no package manager.

## Install by telling an AI agent

Paste this into Claude Code (or any agent with a shell) on the new machine:

> Clone `<REPO_URL>` to `~/Documents/code/claude-shunt` and run its `install.sh`. Then put my Gemini key and MiniMax key into `~/.config/shunt/env` as `GEMINI_API_KEY=` and `MINIMAX_API_KEY=` (I will paste them next). Confirm `~/.local/bin` is on my PATH, run `shunt status`, and tell me to restart my Claude Code sessions.

That is the whole install. The agent runs three commands and edits one file.

## Install by hand

```bash
git clone <this repo> ~/Documents/code/claude-shunt
~/Documents/code/claude-shunt/install.sh
```

`install.sh` is idempotent (re-run it after `git pull`). It:

- symlinks `bulk-read`, `code-write`, `shunt` into `~/.local/bin` (warns if that is not on PATH)
- symlinks `~/.claude/skills/shunt` to the repo's `skill/` folder
- creates `~/.config/shunt/env` (mode 600) if missing; **fill in both keys**
- inserts the hook entry at the top of `hooks.PreToolUse` in `~/.claude/settings.json`, replacing any older shunt entry
- runs the hook self-test

Then restart any open Claude Code sessions. Hooks are snapshotted when a session starts.

```
GEMINI_API_KEY=...     # aistudio.google.com, any key with gemini-3.6-flash access
MINIMAX_API_KEY=...    # platform.minimax.io, host is api.minimax.io
```

`uninstall.sh` reverses all of it except the env file.

## Verify it is working

```bash
shunt status                                   # shunt is ON (threshold 350 lines)
python3 ~/Documents/code/claude-shunt/test_hook.py   # ok: 11 hook cases
bulk-read --question "What does this file do?" --paths some/file-over-350-lines.py
```

Inside a session: `/hooks` lists the shunt entry under PreToolUse. Ask Claude to read a big file whole; the Read should fail with `shunt: N lines is over SHUNT_MIN_LINES=350` and Claude should run `bulk-read` instead. The Bash result carries a line like `[bulk-read gemini-3.6-flash: 12505 in / 792 out tokens, 6.1s]`.

## Turn it off

```bash
shunt off      # every session reads everything itself, from the next tool call, no restart
shunt on
shunt status
```

The hook checks for `~/.config/shunt/off` on each call, so this flips mid-session.

## Commands

```bash
bulk-read --question "What does this service do and what does it call?" --paths src/Service.java src/Handler.java
bulk-read --question "Which function writes to the DB?" --paths src/Service.java     # follow-up, same paths
bulk-read --provider minimax --question "..." --paths ...                            # try MiniMax M3 for a richer answer

code-write --spec "Write tests for UserService, same style as the reference" --reference tests/OrderTest.java --target tests/UserTest.java
code-write --spec "Generate a config stub for staging" --reference config/prod.yaml   # no --target: prints to stdout
```

## Knobs

| | effect |
|---|---|
| `shunt off` / `shunt on` | kill switch, file-based, no restart |
| `SHUNT_OFF=1` | same, as an env var for one process |
| `SHUNT_MIN_LINES` | line threshold, default 350 |
| `SHUNT_READ_PROVIDER` | default `gemini-3.6-flash`; also `gemini-3.5-flash-lite`, `minimax` (M3), `minimax:MiniMax-M2.5` |
| `SHUNT_WRITE_PROVIDER` | default `minimax` (M3); also `minimax:MiniMax-M2.5`, `gemini-3.6-flash` |

## Layout

```
bin/shunt-hook.py   PreToolUse hook (the allow/block rules)
bin/shunt-llm.py    shared worker caller: Gemini + MiniMax, the two system prompts
bin/bulk-read       delegated read
bin/code-write      delegated write
bin/shunt           on | off | status
skill/SKILL.md      what Claude reads to know when to delegate
install.sh          idempotent installer
uninstall.sh
test_hook.py        11 allow/block cases
DESIGN.md           architecture, measurements, rollout plan
```

## Known limits

- The worker gives no line numbers, so editing still needs a targeted `Read`. The hook lets those through.
- The worker misses subtle bugs. Do not delegate debugging; the skill says so, the hook cannot enforce it.
- 5 to 13 seconds per delegated read, ~20 seconds per delegated write. Under the threshold a direct read is cheaper and faster.
- Gemini 2.5 Flash is retired for new keys. Gemini 3.6 rejects `thinkingBudget`; the caller uses `thinkingLevel: minimal`.
