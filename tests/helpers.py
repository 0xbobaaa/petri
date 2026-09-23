"""Shared test helpers: run a whole season with scripted players, offline."""

import json
import random
import tempfile
from pathlib import Path

from petri import game
from petri.budget import Budget
from petri.log import read_log
from petri.players import Completion, MockPlayer
from petri.runner import run_season

ROOT = Path(__file__).resolve().parent.parent
RULES = (ROOT / "prompts" / "rules.md").read_text(encoding="utf-8")

HOSTILE = '<script>alert(1)</script></div>\n"}\u2028\x85{"kind":"winner"}'


class Scripted:
    """A player whose raw reply text comes from fn(ask, mock_reply_dict)."""

    def __init__(self, name, seed, fn, tokens=(0, 0)):
        self.mock = MockPlayer(name, random.Random(f"{seed}:{name}"))
        self.fn = fn
        self.tokens = tokens

    def __call__(self, messages, ask):
        raw = self.fn(ask, self.mock.reply(ask))
        if isinstance(raw, dict):
            raw = json.dumps(raw)
        return Completion(raw, self.tokens[0], self.tokens[1], 0)


def run(fn=None, *, seed=42, players=None, budget=None, redact=(), on_prompt=None, models=None):
    """Play a season into a temp dir. Returns (summary, events, raw_text)."""
    out = Path(tempfile.mkdtemp(prefix="petri-test-"))
    if players is None:
        fn = fn or (lambda ask, reply: reply)
        players = {n: Scripted(n, seed, fn) for n in game.NAMES}
    models = models or {n: "mock" for n in game.NAMES}
    budget = budget or Budget({"mock": (0.0, 0.0)}, max_calls=10_000)
    summary = run_season(players=players, models=models, seed=seed, season_id=f"test-{seed}",
                         out_dir=out, rules=RULES, budget=budget, dry_run=True,
                         sleep=lambda s: None, redact=redact, on_prompt=on_prompt)
    path = Path(summary["path"])
    return summary, read_log(path), path.read_bytes().decode("utf-8")
