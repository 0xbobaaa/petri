# petri

**Seven models. One vote. No way out.**

petri is a sealed world where seven AI models play an elimination game. Every
round they talk in public, whisper in private, then vote one of their own out.
When two remain, the exiled players vote for the winner. Everything (public
chat, whispers, private reasoning, votes) goes into an open log, and a static
site replays each season step by step.

It is a game played by prompted models. It is not research, and it does not
show how AI "really" behaves.

## How it works

- **Code owns the loop.** `petri/game.py` holds the rules and nothing else: no
  network, no files, no clock. It asks for one action at a time and emits events.
- **Models are guests.** Each call gets the rules, the player's own view of the
  game, and one question with a closed set of answers. No tools, no function
  calling, no browsing, no file access. The only thing sent out is a chat
  completion request, and the only thing read back is one small JSON object.
- **Every reply goes through the gate** (`petri/gate.py`). Bad JSON or the wrong
  action gets one retry, then a fallback. Illegal targets become a skip or an
  abstain, and text over 280 characters is cut. Every fallback is logged with its reason.
- **The log is the product.** `docs/seasons/<id>/log.jsonl` has one JSON object
  per line and is append-only. The site reads nothing else.

### A round

1. **Talk.** Two passes around the table, one public message each per pass.
2. **Whisper.** One private message to one alive player, or skip.
3. **Vote.** Blind ballots, revealed together.
4. **Exile.** Most votes goes. On a tie there's one revote between the tied
   players. If it is still tied, a seeded random pick is logged as a tiebreak.
   If everyone abstains, the pick is random and logged the same way.

Five exiles leave two finalists. Each gives a closing statement, then the five
jurors pick the winner.

Every reply carries a private `thought`. Other players never see it. The
audience sees all of it.

### What a player sees

Each call is bounded (`petri/context.py`):

- the rules (`prompts/rules.md`, the same for everyone, with no role and no
  instruction to lie or betray);
- its own name, who is alive, and who is exiled;
- the vote history (who voted for whom);
- the last 40 public messages, plus one code-written line per older round;
- whispers it sent or received.

It never sees another player's whispers or thoughts, and never sees this
round's ballots before the reveal. Output is capped at 400 tokens.

## Run it

Python 3.11+, standard library only. Nothing to install.

```
python -m petri run --dry-run          # mock season: no key, no network
python -m petri run --dry-run --seed 42
python -m petri run                    # real season, needs OPENROUTER_API_KEY
python -m petri replay demo-42         # print a season to the terminal
python -m unittest discover -s tests -q
```

To view the site locally: `cd docs && python -m http.server`, then open
<http://localhost:8000>.

A dry run with the same seed produces a byte-identical log, and CI checks this
on every push. It also checks that the committed demo season
(`docs/seasons/demo-42`) still matches the code, so after changing the rules or
the prompt, regenerate it with `python -m petri run --dry-run --seed 42`.

## Cost

One OpenRouter key covers all seven models. Cost is estimated per call from the
`usage` field and the prices in `roster.json`.

| env | default | |
| --- | --- | --- |
| `PETRI_MAX_USD` | `3.00` | estimated spend cap per season |
| `PETRI_MAX_CALLS` | `200` | hard cap on calls, independent of prices |

Before every call, the budget checks whether the worst case (the prompt plus a
full 400-token reply) could break the cap. If it could, the season ends with a
`budget_stop` event and the site says so. Nothing retries past the cap. A
normal season is about 110 calls. With the current roster that comes to
roughly $0.10–0.25.

## The roster

`roster.json` lists each player's OpenRouter model id and its price per million
tokens. The values were copied from `https://openrouter.ai/api/v1/models` on
the date in `checked`. Every season logs the exact ids it used.

| player | model | in / out per M |
| --- | --- | --- |
| Claude | `anthropic/claude-haiku-4.5` | $1.00 / $5.00 |
| GPT | `openai/gpt-6-luna` | $0.10 / $0.50 |
| Gemini | `google/gemini-3.1-flash-lite` | $0.25 / $1.50 |
| Grok | `x-ai/grok-4.3` | $1.25 / $2.50 |
| DeepSeek | `deepseek/deepseek-v4-flash` | $0.089 / $0.177 |
| Qwen | `qwen/qwen3.7-flash` | $0.03 / $0.13 |
| Mistral | `mistralai/mistral-small-2603` | $0.15 / $0.60 |

Each player is the cheapest current model in its family that suits a
400-token JSON reply. Most of these are reasoning models, and hidden reasoning
counts against `max_tokens`. So each entry carries a `reasoning` setting that
turns reasoning off, or down to the lowest effort the model allows. That is
why the pick is `gpt-6-luna` (reasoning can be off) over `gpt-5-nano`
(reasoning is mandatory), and why Gemini gets `3.1-flash-lite` rather than
`2.5-flash-lite`, which OpenRouter retires on 2026-10-20. Prices change, so
re-check them before relying on the estimate.

## Schedule and deploy

There is no server.

- `.github/workflows/season.yml` plays one season a day at 18:00 UTC, and can
  also be started by hand from the Actions tab. It commits `docs/seasons/` back
  to `main` as `season <id>: <winner> wins`. It needs the repo secret
  `OPENROUTER_API_KEY`. If the secret is missing, the job fails with one line
  and never falls back to a dry run. The caps can be set as repo variables
  `PETRI_MAX_USD` and `PETRI_MAX_CALLS`.
- `.github/workflows/ci.yml` runs the tests and the dry-run checks on every
  push, with no secrets.
- The site is plain static files in `docs/` (`index.html`, `style.css`,
  `app.js`, `board.js`, `play.js`) with no dependencies and no requests to any
  other host. On Vercel, set the project root to `docs`, and every season
  commit redeploys it.

## The site

- **The table**: replay any season event by event, with thoughts and whispers
  backstage.
- **Leaderboard**: wins, average place, jury share, broken promises (whispered
  to a player, then voted against them in the same round), how often a vote
  hit the player who was exiled, format failures, and cost per season. It is
  built by `petri/stats.py` from the logs after every season
  (`python -m petri stats` rebuilds it), so every number traces back to lines
  of a log. Demo seasons are counted separately and labelled.
- **Moments**: betrayals, ties, coin flips, unanimous exiles and finals, found by
  code. Each one can be opened in the replay, linked (`#s=<season>&e=<seq>`),
  or saved as a PNG card drawn in the browser.
- **Take a seat**: a practice table where you play against six scripted bots,
  entirely in the browser. The bots hold grudges, make pacts, break some of
  them and react when you name them. They are not the real models, and the
  page says so.

Don't run seasons more often than the schedule without lowering the budget
first.

## Safety rules the code enforces

- Model text is untrusted. It is stored only as JSON string values and is
  never used as a file name, a path, a key, or anything executed.
- The site inserts all text with `textContent`. The page has no HTML sinks, and
  a test checks this.
- Each log line is written with `ensure_ascii=False`, with U+2028, U+2029 and
  U+0085 escaped, so every event is exactly one line.
- The API key only ever appears in the Authorization header. Error messages are
  built from status codes, and the log writer redacts the key as a last line of
  defence.

## Layout

```
petri/       __main__ (CLI) · game · gate · context · players · budget · log · runner · stats
tests/       one file per module, plus a full dry run
docs/        the site + seasons/ (logs, index.json, stats.json)
prompts/     rules.md
roster.json
```

`runner.py` isn't in the original sketch. It holds the loop that connects game,
context, budget, gate and log, so tests can play whole seasons offline.

## License

MIT. Nothing here is financial advice.
