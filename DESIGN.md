# claude-shunt: design and rollout plan

Source pattern: Spotify Engineering, "Portal by Spotify cut my Claude Code token usage by 90%" (2026-09-03).
Local extract: `~/Documents/code/_vault/resources/Portal-Spotify-Claude-Code-Token-Delegation.md`.

## Goal

Stop paying frontier-model prices for two predictable kinds of work: reading large files to get their gist, and emitting boilerplate that mirrors an existing file.
Keep Claude on reasoning, debugging, and editing.

## What Spotify has that we do not, and what replaces it

| Spotify piece | Ours |
|---|---|
| Portal AiKA modes (hosted worker agents, YAML config, precedence rules) | Two direct API calls. A mode is just a system prompt plus a model name, so `shunt-llm.py` holds both prompts inline. No mode registry until there is a third mode. |
| Portal CLI + auth (`/portal:setup`) | Keys in `~/.config/shunt/env`, mode 600. |
| Shunt plugin from a marketplace | Three files in `bin/`, a hook entry in `settings.json`, a skill file. |
| Gemini 2.5 Flash worker | `gemini-3.6-flash` for reads (2.5 is retired for new keys). MiniMax-M2.5 for writes, since Richard already pays for it and it is cheaper on output. |

## Architecture: the same three layers

```
Claude Code
   │  Read / Bash(cat …)
   ▼
[Layer 1] shunt-hook.py  (PreToolUse, matcher Read|Bash)
   │  > SHUNT_MIN_LINES and not targeted?  → exit 2, stderr names the fix
   ▼
[Layer 3] ~/.claude/skills/shunt/SKILL.md  (when + how; the hook message carries the syntax too)
   │
   ▼
[Layer 2] bulk-read / code-write  → shunt-llm.py → Gemini Flash | MiniMax
   │  bullets to stdout            │  code to --target on disk
   ▼                               ▼
Claude reads ~800 tokens      Claude reads one "wrote X (N lines)" line
```

Hook contract (Claude Code): stdin JSON `{tool_name, tool_input}`; exit 2 blocks the call and feeds stderr back to Claude as the reason.

Allow rules, in order:
1. `SHUNT_OFF` set → allow everything.
2. `Read` with `offset` or `limit` → allow (targeted, needed for edits).
3. Images, PDFs, notebooks → allow (line count is meaningless).
4. Bash with `|` or `>` → allow (grep-style query, or output not entering context).
5. `head`/`tail` with any flag → allow (`head -n 50`).
6. Only `cat head tail less more` are inspected; `rtk` prefix is stripped since the rtk hook may rewrite the command first.
7. Sum of lines across the named files > threshold → block.

## Measured on real files (2026-09-07)

Three vault files, 902 lines total: `site/build.mjs`, `agents/buildsheetsync/README.md`, `personal/finance/build.py`.
Question: "What does each file do, and which external services or files does each one touch?"

| | tokens Claude would ingest | tokens Claude actually ingests | saving | latency |
|---|---|---|---|---|
| direct Read of all three | 12,505 | 12,505 | 0 | 0 |
| bulk-read, gemini-3.6-flash | 12,505 at worker | 792 | 93.7% | 19.0s |
| bulk-read, minimax M2.5 | 12,505 at worker | ~600 | ~95% | ~15s |

code-write, MiniMax-M2.5, README for a new agent from two reference READMEs: 688 in / 681 out at the worker, 39 lines to disk, 10.7s, Claude ingests one line.

Quality check on the sample: the gemini answer correctly separated "documented only" (the README) from "actually touches" (the scripts), and listed every read and write path in `build.py`. That matches the article's finding: structural questions delegate well.

Gemini gotcha found in testing: `thinkingConfig.thinkingBudget` is rejected by 3.6; `thinkingLevel: "minimal"` works and spends zero thought tokens.

## Rollout plan

- [x] Step 1. Prove the workers: both keys answer, model names confirmed, keys stored in `~/.config/shunt/env`.
- [x] Step 2. `bulk-read` and `code-write` scripts, stdlib only, on PATH via `~/.local/bin`.
- [x] Step 3. Hook with the allow matrix above; `test_hook.py` covers 10 cases.
- [x] Step 4. Install: settings.json entry (first in PreToolUse so it runs before rtk), skill file.
- [x] Step 5. Live test in a session: whole-file Read of a 561-line file blocked, offset read passed.
- [ ] Step 6. Run for a week at 350 lines. Watch for two failure modes: Claude ignoring the block and re-reading in slices (the threshold is too low for that file type), and Claude delegating a debugging question (the skill wording needs tightening).
- [ ] Step 7. Measure. Compare `rtk gain` and ccusage-style per-session totals for the week before and after. Decide the threshold from that, not from the article.
- [ ] Step 8. Decide whether `bulk-read` should become an `rtk` subcommand. Argument for: one hook chain, one place for token accounting. Argument against: rtk is a filter over shell output, not an LLM caller, and mixing keys into it widens its blast radius. Default: keep separate unless step 7 shows the two hooks fighting.

## Deliberately skipped

- Mode registry / YAML config: two prompts, inline. Add when a third worker prompt appears.
- Caching worker answers by file hash: the article does not, and repeated questions on the same paths are rare. Add if step 7 shows repeat calls.
- A PostToolUse token counter: `rtk gain` already tracks shell-side savings; bulk-read prints its own in/out counts to stderr, which the session transcript keeps.
- Splitting oversized inputs across calls: Gemini 3.6 Flash takes 1M tokens; MiniMax M2.5 takes 200k+. A single call covers any realistic `--paths` list.

## Limits carried over from the article

- No line numbers from the worker, so editing still needs a targeted Read. The hook lets those through.
- No reasoning delegation. The skill file says so; the hook cannot enforce it.
- 10 to 20 seconds per delegation. Below the threshold, a direct read is both cheaper and faster.
