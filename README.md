# claude-shunt

Cuts Claude Code token spend by routing big file reads and boilerplate generation to a cheap worker model.
A local reimplementation of the pattern in Spotify Engineering's [Portal by Spotify cut my Claude Code token usage by 90%](https://engineering.atspotify.com/2026/9/portal-by-spotify-cut-my-claude-code-token-usage-by-90) (Dimitri Mazmanov, 2026-09-03). Same three layers, hook / scripts / skill, without the hosted Portal service.
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

> Clone `https://github.com/jarvisrchen/claude-shunt` somewhere permanent (it runs from the clone) and run its `install.sh`. Then put my Gemini key and MiniMax key into `~/.config/shunt/env` as `GEMINI_API_KEY=` and `MINIMAX_API_KEY=` (I will paste them next). Confirm `~/.local/bin` is on my PATH, run `shunt status`, and tell me to restart my Claude Code sessions.

That is the whole install. The agent runs three commands and edits one file.

## Install by hand

```bash
git clone https://github.com/jarvisrchen/claude-shunt
cd claude-shunt && ./install.sh
```

The clone can live anywhere. Nothing is copied out of it: the commands, the skill, and the hook all point back into the clone by absolute path, which `install.sh` works out for itself. So put it somewhere you will not delete, and re-run `install.sh` if you ever move it.

`install.sh` is idempotent (re-run it after `git pull`). It:

- symlinks `bulk-read`, `code-write`, `shunt` into `~/.local/bin` (warns if that is not on PATH)
- symlinks `~/.claude/skills/shunt` to the repo's `skill/` folder
- creates `~/.config/shunt/env` (mode 600) if missing; **fill in both keys**
- inserts the hook entry at the top of `hooks.PreToolUse` in `~/.claude/settings.json`, replacing any older shunt entry
- runs the hook self-test

Then restart any open Claude Code sessions. Hooks are snapshotted when a session starts.

`uninstall.sh` reverses all of it except the env file.

## Choosing which LLM does the work

Everything about models lives in one file, `~/.config/shunt/env`. You need a key for at least one provider. Leave the other blank.

```
GEMINI_API_KEY=...     # aistudio.google.com
MINIMAX_API_KEY=...    # platform.minimax.io

#SHUNT_READ_PROVIDER=gemini-3.6-flash   # who answers bulk-read
#SHUNT_WRITE_PROVIDER=minimax           # who generates code-write output
```

Defaults are Gemini 3.6 Flash for reads and MiniMax M3 for writes, the winners of the bake-off in [DESIGN.md](DESIGN.md). To change either, uncomment the line and set it. Takes effect on the next call, no restart.

| you want | set |
|---|---|
| Gemini for everything, no MiniMax account | `SHUNT_WRITE_PROVIDER=gemini-3.6-flash` and leave `MINIMAX_API_KEY` blank |
| MiniMax for everything, no Gemini account | `SHUNT_READ_PROVIDER=minimax` and leave `GEMINI_API_KEY` blank |
| a different Gemini model | any model name from `/v1beta/models`, e.g. `gemini-3.5-flash-lite` |
| a different MiniMax model | `minimax:MiniMax-M2.5` |
| try one call on another model | `bulk-read --provider minimax ...` or `code-write --provider gemini-3.6-flash ...` |

Adding a provider that is not Gemini or MiniMax (OpenAI, a local Ollama, anything with a chat endpoint) is one `elif` in `call()` in `bin/shunt-llm.py`: build the request, return `(text, prompt_tokens, completion_tokens)`. The rest of the tool does not care who answered.

## Verify it is working

```bash
shunt status                                   # shunt is ON (threshold 350 lines)
shunt test                                     # ok: 11 hook cases
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
| `SHUNT_READ_PROVIDER` / `SHUNT_WRITE_PROVIDER` | which model does each job; see "Choosing which LLM does the work" |

## Layout

```
bin/shunt-hook.py   PreToolUse hook (the allow/block rules)
bin/shunt-llm.py    shared worker caller: Gemini + MiniMax, the two system prompts
bin/bulk-read       delegated read
bin/code-write      delegated write
bin/shunt           on | off | status | test
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
