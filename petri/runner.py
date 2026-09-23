"""Plays one season: drives game.play(), routes every call through context,
budget and gate, and writes every event to the log."""

from __future__ import annotations

import hashlib
import random
import time
from pathlib import Path
from typing import Callable, Mapping

from . import context, game, gate
from .budget import Budget, BudgetStop
from .game import Ask, event
from .log import SeasonLog, season_dir


def rules_version(rules: str) -> str:
    return hashlib.sha256(rules.encode("utf-8")).hexdigest()[:12]


def run_season(*, players: Mapping[str, Callable], models: Mapping[str, str], seed: int,
               season_id: str, out_dir: Path, rules: str, budget: Budget, dry_run: bool,
               sleep: Callable[[float], None] = time.sleep, redact: tuple[str, ...] = (),
               on_prompt: Callable[[Ask, list[dict]], None] | None = None) -> dict:
    """Returns a summary: season, status, winner, usd_est_total, calls, rounds."""
    rules = rules.replace("\r\n", "\n")
    rng = random.Random(seed)
    seats = game.seat(game.NAMES, rng)
    log = SeasonLog(season_dir(out_dir, season_id) / "log.jsonl", redact)
    names = tuple(game.NAMES)
    where = {"round": 0, "phase": "setup"}

    log.emit(event(0, "setup", "season_start", season=season_id, seed=seed, dry_run=dry_run,
                   rules_version=rules_version(rules),
                   roster=[{"name": n, "model": models[n]} for n in seats]))

    def ask_player(ask: Ask) -> dict:
        model = models[ask.player]
        player = players[ask.player]

        def call(messages: list[dict]) -> str:
            budget.reserve(model, sum(len(m["content"]) for m in messages))
            if on_prompt:
                on_prompt(ask, messages)
            try:
                c = player(messages, ask)
            except gate.ApiError as e:
                log.emit(event(ask.round, ask.phase, "perf", player=ask.player, model=model,
                               tokens_in=0, tokens_out=0, usd_est=0.0, ms=e.ms, ok=False))
                raise
            usd = budget.charge(model, c.tokens_in, c.tokens_out)
            log.emit(event(ask.round, ask.phase, "perf", player=ask.player, model=model,
                           tokens_in=c.tokens_in, tokens_out=c.tokens_out,
                           usd_est=round(usd, 6), ms=c.ms, ok=True))
            return c.text

        messages = context.build(log.events, ask, rules)
        reply, reason = gate.consult(call, messages, ask, names, sleep)
        if reason:
            log.emit(event(ask.round, ask.phase, "fallback", player=ask.player, reason=reason))
        return reply

    status, winner = "complete", None
    plays = game.play(seats, rng)
    try:
        item = next(plays)
        while True:
            if isinstance(item, Ask):
                where = {"round": item.round, "phase": item.phase}
                item = plays.send(ask_player(item))
            else:
                log.emit(item)
                if item["kind"] == "winner":
                    winner = item["player"]
                item = next(plays)
    except StopIteration:
        pass
    except BudgetStop as stop:
        status = "budget_stop"
        log.emit(event(where["round"], where["phase"], "budget_stop", reason=stop.reason,
                       usd_est_total=round(budget.spent, 6), calls=budget.calls))

    if status == "complete":
        log.emit(event(where["round"], "end", "season_end",
                       usd_est_total=round(budget.spent, 6), calls=budget.calls))
    log.close()
    return {
        "season": season_id,
        "status": status,
        "winner": winner,
        "usd_est_total": round(budget.spent, 6),
        "calls": budget.calls,
        "rounds": where["round"],
        "path": str(log.path),
    }
