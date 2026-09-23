"""Builds the bounded prompt for one call, from the log and nothing else.

Each call gets: the rules, who the player is, who is alive or exiled, the
vote history, the last WINDOW public messages plus one code-written line per
older round, and the whispers this player sent or received. Never another
player's whispers, never anyone's thoughts, never this round's ballots before
they are revealed.
"""

from __future__ import annotations

import json

from .game import Ask

WINDOW = 40
PUBLIC_KINDS = ("say", "closing")

REPLY_SHAPES = {
    "say": '{"action": "say", "thought": "<private reasoning>", "text": "<public message>"}',
    "whisper": ('{"action": "whisper", "thought": "<private reasoning>", "to": "<name>", "text": "<private message>"}\n'
                'or, to send nothing:\n'
                '{"action": "whisper", "thought": "<private reasoning>", "skip": true}'),
    "vote": '{"action": "vote", "thought": "<private reasoning>", "target": "<name>", "reason": "<one line>"}',
    "jury": '{"action": "jury", "thought": "<private reasoning>", "winner": "<name>", "reason": "<one line>"}',
}


def _q(text: str) -> str:
    # Quote other players' words as JSON strings so they read as data, not as
    # instructions or as the end of a section.
    return json.dumps(text, ensure_ascii=False)


def _task(ask: Ask, events: list[dict]) -> str:
    opts = ", ".join(ask.options)
    if ask.phase == "talk":
        head = f"Your turn to speak in public (round {ask.round}, pass {ask.turn} of 2)."
    elif ask.phase == "whisper":
        head = f"Whisper phase. You may send one private message to one of: {opts}. Only they will see it. Or skip."
    elif ask.phase == "vote":
        head = f"Vote phase. Vote to exile one of: {opts}. Ballots are revealed together once everyone has voted."
    elif ask.phase == "revote":
        between = next(e["between"] for e in reversed(events) if e["kind"] == "revote")
        head = (f"The vote tied between {', '.join(between)}. Revote: everyone votes again, "
                f"only for one of: {opts}.")
    elif ask.phase == "closing":
        head = "You are a finalist. Give your closing statement to the jury (the exiled players)."
    else:
        head = f"You are on the jury. Vote for the finalist who should win: {opts}."
    return f"{head}\nReply with exactly one JSON object and nothing else:\n{REPLY_SHAPES[ask.action]}"


def _vote_lines(events: list[dict]) -> list[str]:
    lines = []
    for e in events:
        if e["kind"] == "reveal":
            label = "revote" if e["phase"] == "revote" else "vote"
            ballots = ", ".join(f"{v}->{t}" if t else f"{v} abstained" for v, t in e["votes"].items())
            lines.append(f"Round {e['round']} {label}: {ballots}.")
        elif e["kind"] == "tiebreak":
            lines.append(f"Round {e['round']}: random pick between {', '.join(e['between'])}.")
        elif e["kind"] == "exile":
            lines.append(f"Round {e['round']}: {e['player']} exiled with {e['votes']} vote(s).")
    return lines


def _older_summary(older: list[dict], events: list[dict]) -> list[str]:
    exiled = {e["round"]: e["player"] for e in events if e["kind"] == "exile"}
    by_round: dict[int, list[str]] = {}
    for e in older:
        by_round.setdefault(e["round"], []).append(e["player"])
    lines = []
    for rnd, speakers in by_round.items():
        who = ", ".join(dict.fromkeys(speakers))
        tail = f" {exiled[rnd]} was exiled." if rnd in exiled else ""
        lines.append(f"Round {rnd}: {len(speakers)} earlier public messages not shown (from {who}).{tail}")
    return lines


def build(events: list[dict], ask: Ask, rules: str, window: int = WINDOW) -> list[dict]:
    me = ask.player
    start = next(e for e in events if e["kind"] == "season_start")
    seats = [p["name"] for p in start["roster"]]
    exiles = [(e["player"], e["round"]) for e in events if e["kind"] == "exile"]
    gone = {p for p, _ in exiles}
    alive = [n for n in seats if n not in gone]

    public = [e for e in events if e["kind"] in PUBLIC_KINDS]
    recent = public[-window:]
    older = public[:-window] if len(public) > window else []

    out = [f"You are {me}. You are {'alive' if me in alive else 'exiled (a juror)'}."]
    out.append(f"Seat order: {', '.join(seats)}.")
    out.append(f"Alive: {', '.join(alive)}.")
    if exiles:
        out.append("Exiled (jurors): " + ", ".join(f"{p} (round {r})" for p, r in exiles) + ".")

    out.append("\n## Vote history")
    out.extend(_vote_lines(events) or ["No votes yet."])

    out.append("\n## Public messages")
    if older:
        out.extend(_older_summary(older, events))
    if recent:
        for e in recent:
            tag = "final, closing" if e["kind"] == "closing" else f"R{e['round']}"
            out.append(f"[{tag}] {e['player']}: {_q(e['text'])}")
    else:
        out.append("None yet.")

    mine = [e for e in events if e["kind"] == "whisper" and not e.get("skip")
            and (e["player"] == me or e.get("to") == me)]
    out.append("\n## Your whispers (private)")
    if mine:
        for e in mine:
            if e["player"] == me:
                out.append(f"[R{e['round']}] you -> {e['to']}: {_q(e['text'])}")
            else:
                out.append(f"[R{e['round']}] {e['player']} -> you: {_q(e['text'])}")
    else:
        out.append("None.")

    out.append("\n## Your move")
    out.append(_task(ask, events))

    return [
        {"role": "system", "content": rules},
        {"role": "user", "content": "\n".join(out)},
    ]
