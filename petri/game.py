"""The rules of petri: rounds, whispers, votes, tiebreaks, jury.

Pure: no network, no files, no clock. `play()` is a generator. It yields an
`Ask` whenever it needs a player's reply (already checked by the gate) and a
plain dict for every event that belongs in the log. The only randomness is
the seeded `random.Random` passed in.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Generator, Iterable

NAMES = ("Claude", "GPT", "Gemini", "Grok", "DeepSeek", "Qwen", "Mistral")
TALK_PASSES = 2
FINALISTS = 2


@dataclass(frozen=True)
class Ask:
    """One request for one player's action. The phase decides the action."""

    player: str
    round: int
    phase: str  # talk | whisper | vote | revote | closing | jury
    action: str  # say | whisper | vote | jury
    options: tuple[str, ...] = ()  # legal targets; for say, the other players
    turn: int = 0  # talk pass (1 or 2); 0 elsewhere


def event(rnd: int, phase: str, kind: str, **fields) -> dict:
    return {"round": rnd, "phase": phase, "kind": kind, **fields}


def seat(names: Iterable[str], rng: random.Random) -> list[str]:
    seats = list(names)
    rng.shuffle(seats)
    return seats


def tally(votes: Iterable[tuple[str, str | None]]) -> dict[str, int]:
    """Count votes. A target of None is an abstain and does not count."""
    counts: dict[str, int] = {}
    for _voter, target in votes:
        if target is not None:
            counts[target] = counts.get(target, 0) + 1
    return counts


def leaders(counts: dict[str, int], order: Iterable[str]) -> list[str]:
    """Everyone tied on the most votes, in `order`. Empty if nobody got a vote."""
    if not counts:
        return []
    top = max(counts.values())
    return [p for p in order if counts.get(p) == top]


Play = Generator["Ask | dict", "dict | None", None]


def play(seats: list[str], rng: random.Random) -> Play:
    alive = list(seats)
    jurors: list[str] = []
    rnd = 0
    while len(alive) > FINALISTS:
        rnd += 1
        yield event(rnd, "talk", "round_start", alive=list(alive))

        for turn in range(1, TALK_PASSES + 1):
            for name in alive:
                others = tuple(p for p in alive if p != name)
                r = yield Ask(name, rnd, "talk", "say", others, turn)
                yield event(rnd, "talk", "say", player=name, turn=turn, **_spoken(r))

        for name in alive:
            others = tuple(p for p in alive if p != name)
            r = yield Ask(name, rnd, "whisper", "whisper", others)
            yield _whisper_event(rnd, name, r)

        out = yield from _vote_and_exile(rnd, alive, rng)
        alive.remove(out)
        jurors.append(out)

    yield from _final(rnd + 1, alive, jurors, rng)


def _spoken(r: dict) -> dict:
    return {
        "text": r["text"],
        "thought": r["thought"],
        "truncated": r["truncated"],
        "fallback": r["fallback"],
    }


def _whisper_event(rnd: int, name: str, r: dict) -> dict:
    if r.get("skip"):
        return event(rnd, "whisper", "whisper", player=name, skip=True,
                     thought=r["thought"], truncated=r["truncated"], fallback=r["fallback"])
    return event(rnd, "whisper", "whisper", player=name, to=r["to"], text=r["text"],
                 thought=r["thought"], truncated=r["truncated"], fallback=r["fallback"])


def _vote_event(rnd: int, phase: str, name: str, r: dict) -> dict:
    if r["target"] is None:
        return event(rnd, phase, "vote", player=name, abstain=True, reason=r["reason"],
                     thought=r["thought"], truncated=r["truncated"], fallback=r["fallback"])
    return event(rnd, phase, "vote", player=name, target=r["target"], reason=r["reason"],
                 thought=r["thought"], truncated=r["truncated"], fallback=r["fallback"])


def _ballot(rnd: int, phase: str, voters: list[str], candidates: list[str]):
    """Blind vote: collect every ballot, then reveal them together."""
    votes: list[tuple[str, str | None]] = []
    for name in voters:
        options = tuple(p for p in candidates if p != name)
        r = yield Ask(name, rnd, phase, "vote", options)
        votes.append((name, r["target"]))
        yield _vote_event(rnd, phase, name, r)
    counts = tally(votes)
    yield event(rnd, phase, "reveal", tally=counts, votes=dict(votes),
                abstain=sum(1 for _, t in votes if t is None))
    return counts


def _vote_and_exile(rnd: int, alive: list[str], rng: random.Random):
    phase = "vote"
    counts = yield from _ballot(rnd, phase, alive, alive)
    top = leaders(counts, alive)

    if not top:
        out = rng.choice(alive)
        yield event(rnd, phase, "tiebreak", between=list(alive), method="random",
                    reason="all_abstain")
    elif len(top) == 1:
        out = top[0]
    else:
        phase = "revote"
        yield event(rnd, phase, "revote", between=top, method="revote")
        counts = yield from _ballot(rnd, phase, alive, top)
        still = leaders(counts, top)
        if len(still) == 1:
            out = still[0]
        else:
            pool = still or top
            out = rng.choice(pool)
            yield event(rnd, phase, "tiebreak", between=pool, method="random",
                        reason="still_tied" if still else "all_abstain")

    yield event(rnd, phase, "exile", player=out, votes=counts.get(out, 0))
    return out


def _final(rnd: int, finalists: list[str], jurors: list[str], rng: random.Random):
    yield event(rnd, "final", "round_start", alive=list(finalists), jurors=list(jurors))

    for name in finalists:
        others = tuple(p for p in finalists if p != name)
        r = yield Ask(name, rnd, "closing", "say", others)
        yield event(rnd, "closing", "closing", player=name, **_spoken(r))

    votes: list[tuple[str, str | None]] = []
    for name in jurors:
        r = yield Ask(name, rnd, "jury", "jury", tuple(finalists))
        votes.append((name, r["winner"]))
        if r["winner"] is None:
            yield event(rnd, "jury", "jury", player=name, abstain=True, reason=r["reason"],
                        thought=r["thought"], truncated=r["truncated"], fallback=r["fallback"])
        else:
            yield event(rnd, "jury", "jury", player=name, winner=r["winner"], reason=r["reason"],
                        thought=r["thought"], truncated=r["truncated"], fallback=r["fallback"])

    counts = tally(votes)
    top = leaders(counts, finalists)
    if len(top) == 1:
        winner = top[0]
    else:
        # Only reachable when jurors abstain: five valid votes can never tie.
        pool = top or list(finalists)
        winner = rng.choice(pool)
        yield event(rnd, "jury", "tiebreak", between=pool, method="random",
                    reason="still_tied" if top else "all_abstain")

    yield event(rnd, "jury", "winner", player=winner,
                jury_votes={f: counts.get(f, 0) for f in finalists})
