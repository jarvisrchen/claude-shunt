# claude-shunt: design and rollout plan

Source pattern: Spotify Engineering, "Portal by Spotify cut my Claude Code token usage by 90%" (2026-09-03).
Article: https://engineering.atspotify.com/2026/9/portal-by-spotify-cut-my-claude-code-token-usage-by-90

## Goal

Stop paying frontier-model prices for two predictable kinds of work: reading large files to get their gist, and emitting boilerplate that mirrors an existing file.
Keep Claude on reasoning, debugging, and editing.

## What Spotify has that we do not, and what replaces it

| Spotify piece | Ours |
|---|---|
| Portal AiKA modes (hosted worker agents, YAML config, precedence rules) | Two direct API calls. A mode is just a system prompt plus a model name, so `shunt-llm.py` holds both prompts inline. No mode registry until there is a third mode. |
| Portal CLI + auth (`/portal:setup`) | Keys in `~/.config/shunt/env`, mode 600. |
| Shunt plugin from a marketplace | Three files in `bin/`, a hook entry in `settings.json`, a skill file. |
| Gemini 2.5 Flash worker | `gemini-3.6-flash` for reads (2.5 is retired for new keys). MiniMax-M3 for writes: best output quality in the bake-off, and generated code never enters Claude's context so its latency is the only cost. |

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
1. `~/.config/shunt/off` exists (`shunt off`) or `SHUNT_OFF` set → allow everything.
2. `Read` with `offset` or `limit` → allow (targeted, needed for edits).
3. Images, PDFs, notebooks → allow (line count is meaningless).
4. Bash with `|` or `>` → allow (grep-style query, or output not entering context).
5. `head`/`tail` with any flag → allow (`head -n 50`).
6. Only `cat head tail less more` are inspected; `rtk` prefix is stripped since the rtk hook may rewrite the command first.
7. Sum of lines across the named files > threshold → block.

## Measured on real files (2026-09-07)

Three files from a private docs repo, 902 lines total: a Node build script, an agent README, and a Python report generator.
Question: "What does each file do, and which external services or files does each one touch?"

| | tokens Claude would ingest | tokens Claude actually ingests | saving | latency |
|---|---|---|---|---|
| direct Read of all three | 12,505 | 12,505 | 0 | 0 |
| bulk-read, gemini-3.6-flash | 12,505 at worker | 792 | 93.7% | 19.0s |
| bulk-read, minimax M2.5 | 12,505 at worker | ~600 | ~95% | ~15s |

### Provider bake-off (2026-09-08, same three files, two runs each)

| provider | out tokens (enter Claude) | latency | notes |
|---|---|---|---|
| gemini-3.6-flash | 789, 843 | 9.6s, 5.3s | tight bullets; the 19s first run was a one-off under load |
| gemini-3.5-flash-lite | 514, 540 | 55.2s, 2.5s | terse but wildly variable latency |
| MiniMax-M3 | 1064, 1592 | 11.0s, 13.1s | richest answer (named service accounts, plists), but 1.3 to 2x the tokens into Claude |
| MiniMax-M2.5 | 1194, 746 | 18.0s, 11.1s | middle on both |

Read default stays `gemini-3.6-flash`: fastest median and the fewest tokens landing in Claude's context, which is the number that matters.

### Claude Haiku bake-off (2026-09-09)

Added `claude` as a third `bulk-read`/`code-write` provider (`bin/shunt-llm.py`, raw HTTP to `api.anthropic.com/v1/messages`, `ANTHROPIC_API_KEY`, no thinking - mirrors the Gemini `thinkingLevel: minimal` treatment). No Anthropic key was configured on this machine, so the read side of the comparison used `claude -p --model haiku --system-prompt <bulk-read's SYSTEM>` as a stand-in for the real API call, fed the exact same `wrap_files()` payload `bulk-read` would send. This machine also had no working Gemini/MiniMax bake-off history to compare against directly (different corpus, private repo), so all three providers were re-run once each on the same new corpus: `bin/shunt-hook.py`, `bin/shunt-llm.py`, `README.md`, `DESIGN.md` (398 lines) with the question "What does each file do, and which external services or files does each one touch?"

| provider | in / out tokens (enter Claude) | latency | $/call (list price) | notes |
|---|---|---|---|---|
| gemini-3.6-flash | 6376 / 491 | 69.4s | $0.0066 | tightest bullets, stuck strictly to the four given files; latency was a slow outlier here (original bake-off median was 5-10s) |
| MiniMax-M3 | 5878 / 2437 | 25.4s | $0.0047 | richest answer again, 5x the tokens back into Claude |
| claude haiku 4.5 (via `claude -p` proxy) | ~5400 / 412 visible (1100 billed, 584 of them thinking) | 13.5s API time | ~$0.0075 est. | honest about scope ("not shown but referenced" for files outside the corpus); tightest visible answer of the three once CC's session-default thinking is subtracted |

Cost math: Gemini 3.6 Flash $0.75/$3.75 per MTok, MiniMax M3 $0.30/$1.20 per MTok, Claude Haiku 4.5 $1.00/$5.00 per MTok (all list, Sep 2026). The Haiku row is an estimate, not a measured API call - the `claude -p` proxy call is not representative of `bin/shunt-llm.py`'s real request shape:

- **Cost is contaminated by the CLI harness and not usable directly.** The proxy call billed $0.0616 - 8 to 13x the other two providers - because `claude -p`, even with `--system-prompt` replacing the prompt, still creates ~27-32k cache tokens of tool-schema/environment overhead per process launch (confirmed by re-running the identical trivial prompt twice: 24,938 and 32,043 cache-creation tokens, neither reused across processes) and the session defaults turned thinking on (584 of the 1100 output tokens). None of that exists in the real `elif` this session added to `shunt-llm.py`, which sends only the bake-off's own system+user text and no thinking. The $0.0075 estimate above backs out that overhead: measured visible-answer tokens (412) at Haiku's real output rate, plus the payload's character count / 4 as a rough stand-in for input tokens (input-token count barely matters for cost either way - output dominates on all three providers here).
- **Latency is more trustworthy** - `duration_api_ms` (13.5s) isolates the actual model call from `claude -p` process startup (39s wall clock), and lands between MiniMax and Gemini's slow outlier run.
- **Quality was good and the visible-answer token count was the best of the three** in this single run, but a Claude-family worker adds nothing a Gemini/MiniMax worker doesn't already have for this task (structural "what does this file do" questions were already the strength of both, per the original bake-off's quality note above), while costing about as much as Gemini and 60% more than MiniMax per call.

Defaults are unchanged: `gemini-3.6-flash` for reads, `MiniMax-M3` for writes. `claude` stays available as an opt-in third option (`SHUNT_READ_PROVIDER=claude` / `SHUNT_WRITE_PROVIDER=claude`) for anyone who would rather manage one Anthropic key than two separate provider keys, not because it measurably beats the incumbents here. Re-run this bake-off with a real `ANTHROPIC_API_KEY` (not the `claude -p` proxy) before trusting the cost number for a decision.

### DeepSeek bake-off (2026-09-10)

Added `deepseek` as a fourth provider, `deepseek-v4-flash` with `thinking: {"type": "disabled"}` (confirmed non-thinking with a separate throwaway call: no `reasoning_content` field, `completion_tokens: 1` for a one-word answer). Same corpus and question as the Claude Haiku run above, real measured API call (an actual `DEEPSEEK_API_KEY` was available, unlike the Haiku run):

| provider | in / out tokens (enter Claude) | latency | $/call (list, off-peak) |
|---|---|---|---|
| gemini-3.6-flash | 6376 / 491 | 69.4s (slow outlier) | $0.0066 |
| MiniMax-M3 | 5878 / 2437 | 25.4s | $0.0047 |
| claude haiku 4.5 (est., see above) | ~5400 / 412 | 13.5s | ~$0.0075 |
| **deepseek-v4-flash** | 7556 / 674 | **3.9s** | **$0.0021** |

DeepSeek V4-Flash list pricing: $0.22 per MTok input / $0.66 per MTok output off-peak (cache-miss rate; this call was off-peak per the 01:00-04:00 + 06:00-10:00 UTC Mon-Fri peak window), doubling to $0.44/$1.32 at peak. Even at peak pricing ($0.0042/call) it undercuts every other provider here. It was also the fastest by a wide margin and the answer was comparable in structure and accuracy to MiniMax's (per-function detail, correct external services and env vars, correctly picked up the Claude/DeepSeek additions just made to `shunt-llm.py`) without MiniMax's token bloat.

On this single-run, single-corpus bake-off, DeepSeek wins on cost and latency and is not visibly worse on quality than the incumbents. Worth a proper multi-run bake-off (the gemini/minimax methodology above used two runs each) before moving it from opt-in to default - one good run is promising, not proof.

**Bug found and fixed during this test:** `load_env()` split every `KEY=value` line on `=` only, so the README's own documented format (`KEY=...  # comment`) silently appended the comment text onto the key's value when someone actually used it - copying the doc literally broke the key with no error beyond an opaque 401 further down the stack. Fixed by stripping anything from the first ` #` onward before storing the value; see the README's own note on this in the env-file example.

### Second bug found: MiniMax was thinking the whole time (2026-09-10)

The 69.4s gemini run and 25.4s MiniMax run above looked too slow to trust, so both got re-investigated directly against the raw APIs (trivial one-word prompts, repeated, reading the full JSON response instead of just the parsed text):

- **Gemini: thinking really is off, the slowness is the backend.** `usageMetadata.thoughtsTokenCount` was absent (i.e. zero) on every successful call, with or without `thinkingConfig.thinkingLevel: "minimal"` doing anything else unexpected. But four back-to-back trivial calls landed at 0.82s, a 503 "high demand", 33.57s, and 1.04s - Gemini 3.6 Flash's own latency is just this variable right now, independent of thinking. Two clean re-runs of the full bulk-read bake-off (below) came back at 4.6s and 5.8s, in line with the original bake-off's 9.6s/5.3s median; the 69.4s/33.57s spikes are real but intermittent, not a pattern.
- **MiniMax: thinking was on by default and the code never turned it off.** The `minimax` branch in `call()` sent no `thinking` parameter at all. A trivial one-word prompt ("40"/"42"/"44") came back with `completion_tokens_details.reasoning_tokens` of 24, 38, and 45 - nearly the entire completion-token bill was reasoning, not the visible answer. MiniMax-M3 (unlike M2.x, which accepts the flag but ignores it) honors `thinking: {"type": "disabled"}`: the same trivial prompt dropped to 1 completion token and no `reasoning_content` at all. **Fixed** by adding that flag to the minimax branch in `bin/shunt-llm.py`, unconditionally - harmless no-op on M2.x, real savings on M3.

Re-ran `bulk-read` on both providers against the current corpus (`bin/shunt-hook.py`, `bin/shunt-llm.py`, `README.md`, `DESIGN.md`, now 463 lines - it grew across the bake-off rounds above, so these numbers aren't directly comparable to the 6376/5878-input-token rows further up, only to each other):

| provider | in / out tokens (enter Claude) | latency | $/call (list) |
|---|---|---|---|
| gemini-3.6-flash, run A | 9049 / 607 | 4.6s | $0.0091 |
| gemini-3.6-flash, run B | 9049 / 708 | 5.8s | $0.0094 |
| minimax-M3, thinking disabled, run A | 8249 / 789 | 8.8s | $0.0034 |
| minimax-M3, thinking disabled, run B | 8249 / 926 | 8.6s | $0.0036 |

MiniMax's out-token count dropped roughly 3x (2437 → 789-926) and its latency dropped by two-thirds (25.4s → ~8.7s) once reasoning stopped being billed and generated; the visible bullets held the same level of detail (per-file role, inputs, external services, files touched) - if anything tighter, not thinner. This also means the original 2026-09-08 bake-off further up ("MiniMax-M3 ... richest answer ... but 1.3 to 2x the tokens into Claude") was very likely measuring the same unset-thinking behavior, not an inherent MiniMax trait - that corpus is gone (private repo) so it can't be re-run to confirm directly.

Defaults are unchanged even after the fix: Gemini still lands fewer out-tokens per call here (607-708 vs MiniMax's 789-926), so it stays the read default; MiniMax stays the write default regardless, since written code never enters Claude's context either way. The fix matters for cost and latency, not for which provider wins the read default.

### DeepSeek V4.1 Flash (2026-09-10)

DeepSeek shipped V4.1 Flash the same day as the bake-off above, under a new canonical model ID `deepseek-flash` - the old `deepseek-v4-flash` alias used in the bake-off section above now silently routes to V4.1 for compatibility, so that earlier run was very likely already partway onto the new model without anyone asking for it. Updated the `deepseek` branch in `bin/shunt-llm.py` to request `deepseek-flash` directly rather than ride an alias that DeepSeek could retire at any time. Confirmed thinking defaults to **on** on V4.1 (a trivial prompt came back with 26 of 28 completion tokens as `reasoning_content`) and that the existing `thinking: {"type": "disabled"}` flag still turns it off (same trivial prompt: 1 completion token, no `reasoning_content`) - no code change needed beyond the model ID.

Re-ran the same corpus and question, two runs, for a clean comparison against the corrected Gemini/MiniMax numbers directly above:

| provider | in / out tokens (enter Claude) | latency | $/call (list) |
|---|---|---|---|
| gemini-3.6-flash | 9049 / 607-708 | 4.6-5.8s | $0.0091-0.0094 |
| minimax-M3 | 8249 / 789-926 | 8.6-8.8s | $0.0034-0.0036 |
| **deepseek-flash (V4.1), run A** | 9290 / 719 | 4.7s | $0.0037 (peak) / ~$0.0018 (off-peak) |
| **deepseek-flash (V4.1), run B** | 9290 / 729 | 3.6s | $0.0037 (peak) / ~$0.0018 (off-peak) |

V4.1 list pricing dropped from V4's $0.22/$0.66 to $0.15/$0.60 per MTok off-peak (cache-miss input/output), doubling at peak (01:00-04:00 and 06:00-10:00 UTC Mon-Fri; both runs above landed in the peak window). Out-token count and latency are in the same range as MiniMax's corrected numbers, but DeepSeek is cheaper even at its peak rate, and roughly half MiniMax's cost off-peak. Quality held: still correctly read its own just-edited source and called out both bugs fixed in this doc.

DeepSeek stays an opt-in third/fourth option, not a default - same reasoning as Claude Haiku above: one good multi-provider bake-off is a signal, not a week of real traffic. But between the model-retirement risk of riding an unversioned alias and the price drop, anyone already using `deepseek` should have picked up the `deepseek-flash` change automatically on their next `git pull` / re-run of `install.sh`.

code-write, same README task from two reference READMEs:

| provider | out tokens | latency | quality |
|---|---|---|---|
| MiniMax-M3 | 2911, 2192 | 24.3s, 20.4s | matched the reference structure, sensible launchd/plist details, added a self-check section |
| MiniMax-M2.5 | 524, 536 | 7.0s, 6.6s | thinner, and one wrong line (symlinked a folder to a plist path) |

Write default is `MiniMax-M3`. Output goes to disk, not into Claude, so the extra tokens are free on the Claude side and 20s is cheaper than Claude emitting 500 lines itself.

Quality check on the sample: the gemini answer correctly separated "documented only" (the README) from "actually touches" (the scripts), and listed every read and write path in `build.py`. That matches the article's finding: structural questions delegate well.

Gemini gotcha found in testing: `thinkingConfig.thinkingBudget` is rejected by 3.6; `thinkingLevel: "minimal"` works and spends zero thought tokens.

## Rollout plan

- [x] Step 1. Prove the workers: both keys answer, model names confirmed, keys stored in `~/.config/shunt/env`.
- [x] Step 2. `bulk-read` and `code-write` scripts, stdlib only, on PATH via `~/.local/bin`.
- [x] Step 3. Hook with the allow matrix above; `test_hook.py` covers 10 cases.
- [x] Step 4. Install: settings.json entry (first in PreToolUse so it runs before rtk), skill file.
- [x] Step 5. Live test in a session: whole-file Read of a 561-line file blocked, offset read passed.
- [x] Step 5b. `shunt on|off|status` toggle via `~/.config/shunt/off`, read by the hook on every call, so it flips mid-session with no restart. Provider bake-off above.
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
- 5 to 13 seconds per delegated read, 20s per delegated write. Below the threshold, a direct read is both cheaper and faster.

## Telemetry (2026-09-18)

Until now the only trace was the stderr line each script printed, which survived only if Claude's transcript kept it.
Mining transcripts for the first eleven days found 226 hook blocks but only 24 delegations, and no way to tell which agent did what.

Now every hook decision and worker call appends one JSON line to `~/.config/shunt/log.jsonl` through `bin/shunt-log.py`.
Four events: `block` (whole-file read refused), `slice` (offset/limit read of a file over the threshold), `delegate` (Claude ran `bulk-read` or `code-write`), `call` (the worker ran, with the provider's own token counts and seconds).
Hook events carry `session_id`, `agent_id`, and `agent_type` from the hook payload, so subagent reads show under their agent type.
Script events carry the session id from `CLAUDE_CODE_SESSION_ID`, which is all the scripts can see, so per-agent attribution comes from hook events only.
Logging never raises.

`shunt stats` renders it in the `rtk gain` layout.
Two savings figures, kept separate on purpose: tokens routed to workers minus tokens returned is exact, while tokens avoided by slicing is an estimate at 10 tokens per line because the hook never sees a token count.
The number to watch is blocks that were followed by neither a delegate nor a slice.
That is where the hook was pure friction.

`shunt config` (and `/shunt` inside Claude Code) edits `~/.config/shunt/env`: read and write providers, threshold, keys.
`shunt config models` lists what each vendor's list endpoint returns, in the string form the setters accept, and `pick` turns that into a numbered menu.
Setting a provider runs a one-line test call first.
That check caught Gemini 3.8 Flash rejecting `thinkingLevel: minimal` on its first use; the caller now retries once with `low`.

