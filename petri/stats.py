"""Leaderboard and moments, computed by code from the season logs.

No model judges anything here. Every number and every moment points back to
specific lines (`seq`) of a log, so anyone can check it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .log import SEASON_ID, read_log, season_dir

COUNTERS = ("seasons", "wins", "place_sum", "rounds", "jury_votes", "jury_possible", "whispers",
            "broken", "betrayed", "votes_cast", "read_room", "votes_against", "fallbacks", "calls",
            "said", "chars")


def season_summary(events: list[dict]) -> dict:
    """Per-player numbers and notable moments for one season."""
    start = next(e for e in events if e["kind"] == "season_start")
    seats = [r["name"] for r in start["roster"]]
    models = {r["name"]: r["model"] for r in start["roster"]}
    exiles = [e for e in events if e["kind"] == "exile"]
    exiled_in = {e["round"]: e["player"] for e in exiles}
    winner_ev = next((e for e in events if e["kind"] == "winner"), None)
    complete = winner_ev is not None and any(e["kind"] == "season_end" for e in events)

    players = {n: {"model": models[n], **{c: 0 for c in COUNTERS if c not in ("seasons", "wins", "place_sum")},
                   "usd": 0.0, "place": None} for n in seats}
    moments: list[dict] = []
    whispers: dict[tuple[int, str, str], dict] = {}
    broken_seen: set[tuple[int, str]] = set()
    voters_in: dict[tuple[int, str], int] = {}

    for e in events:
        k, p = e["kind"], e.get("player")
        if k == "round_start" and e["phase"] != "final":
            for name in e["alive"]:
                players[name]["rounds"] += 1
        elif k == "say" and not e.get("fallback"):
            players[p]["said"] += 1
            players[p]["chars"] += len(e["text"])
        elif k == "whisper" and not e.get("skip"):
            players[p]["whispers"] += 1
            whispers[(e["round"], p, e["to"])] = e
        elif k == "vote":
            voters_in[(e["round"], e["phase"])] = voters_in.get((e["round"], e["phase"]), 0) + 1
            if e.get("abstain"):
                continue
            t = e["target"]
            players[p]["votes_cast"] += 1
            players[t]["votes_against"] += 1
            if exiled_in.get(e["round"]) == t:
                players[p]["read_room"] += 1
            w = whispers.get((e["round"], p, t))
            if w and (e["round"], p) not in broken_seen:
                broken_seen.add((e["round"], p))
                players[p]["broken"] += 1
                players[t]["betrayed"] += 1
                moments.append({
                    "type": "betrayal", "round": e["round"], "seq": e["seq"], "whisper_seq": w["seq"],
                    "player": p, "target": t, "whisper": w["text"], "reason": e.get("reason", ""),
                    "thought": e.get("thought", ""), "fatal": exiled_in.get(e["round"]) == t,
                })
        elif k == "revote":
            moments.append({"type": "tie", "round": e["round"], "seq": e["seq"], "between": e["between"]})
        elif k == "tiebreak":
            picked = exiled_in.get(e["round"]) if e["phase"] != "jury" else (winner_ev or {}).get("player")
            moments.append({"type": "coin", "round": e["round"], "seq": e["seq"], "between": e["between"],
                            "picked": picked, "reason": e.get("reason", "")})
        elif k == "reveal" and e["phase"] == "vote" and len(e["tally"]) == 1:
            (target, n), = e["tally"].items()
            if n >= voters_in.get((e["round"], "vote"), 0) - 1 and n >= 2:
                moments.append({"type": "unanimous", "round": e["round"], "seq": e["seq"],
                                "player": target, "votes": n})
        elif k == "fallback":
            players[p]["fallbacks"] += 1
        elif k == "perf":
            players[p]["calls"] += 1
            players[p]["usd"] += e.get("usd_est", 0.0)

    winner = None
    if winner_ev:
        winner = winner_ev["player"]
        jury = winner_ev["jury_votes"]
        possible = sum(1 for e in events if e["kind"] == "jury")
        for f, n in jury.items():
            players[f]["jury_votes"] += n
            players[f]["jury_possible"] += possible
        runner_up = next((f for f in jury if f != winner), None)
        counts = sorted(jury.values(), reverse=True)
        moments.append({"type": "final", "round": winner_ev["round"], "seq": winner_ev["seq"], "player": winner,
                        "runner_up": runner_up, "jury_votes": jury,
                        "close": len(counts) > 1 and counts[0] - counts[1] <= 1})
        if complete:
            players[winner]["place"] = 1
            if runner_up:
                players[runner_up]["place"] = 2
            for i, ex in enumerate(reversed(exiles)):
                players[ex["player"]]["place"] = 3 + i

    for v in players.values():
        v["usd"] = round(v["usd"], 6)
    moments.sort(key=lambda m: m["seq"])
    return {"season": start["season"], "dry_run": bool(start.get("dry_run")), "complete": complete,
            "winner": winner, "players": players, "moments": moments}


def leaderboard(summaries: list[dict]) -> dict:
    agg: dict[str, dict] = {}
    totals = {"seasons": 0, "complete": 0, "messages": 0, "whispers": 0, "betrayals": 0, "votes": 0,
              "calls": 0, "usd": 0.0}
    for s in summaries:
        totals["seasons"] += 1
        for v in s["players"].values():
            totals["messages"] += v["said"]
            totals["whispers"] += v["whispers"]
            totals["betrayals"] += v["broken"]
            totals["votes"] += v["votes_cast"]
            totals["calls"] += v["calls"]
            totals["usd"] += v["usd"]
        if not s["complete"]:
            continue  # stopped seasons have no places; they count only in totals
        totals["complete"] += 1
        for name, v in s["players"].items():
            a = agg.setdefault(name, {**{c: 0 for c in COUNTERS}, "usd": 0.0, "models": []})
            a["seasons"] += 1
            a["wins"] += 1 if v["place"] == 1 else 0
            a["place_sum"] += v["place"] or 0
            for c in COUNTERS[3:]:
                a[c] += v[c]
            a["usd"] += v["usd"]
            if v["model"] not in a["models"]:
                a["models"].append(v["model"])

    def ratio(a: float, b: float) -> float | None:
        return round(a / b, 4) if b else None

    rows = []
    for name, a in agg.items():
        rows.append({
            "player": name,
            "models": a["models"],
            "seasons": a["seasons"],
            "wins": a["wins"],
            "win_rate": ratio(a["wins"], a["seasons"]),
            "avg_place": ratio(a["place_sum"], a["seasons"]),
            "avg_rounds": ratio(a["rounds"], a["seasons"]),
            "jury_share": ratio(a["jury_votes"], a["jury_possible"]),
            "whispers": a["whispers"],
            "broken": a["broken"],
            "broken_rate": ratio(a["broken"], a["whispers"]),
            "betrayed": a["betrayed"],
            "read_room": ratio(a["read_room"], a["votes_cast"]),
            "votes_against": a["votes_against"],
            "fallback_rate": ratio(a["fallbacks"], a["calls"]),
            "avg_chars": ratio(a["chars"], a["said"]),
            "usd_per_season": ratio(a["usd"], a["seasons"]),
        })
    rows.sort(key=lambda r: (-r["wins"], r["avg_place"] if r["avg_place"] is not None else 99, r["player"]))
    totals["usd"] = round(totals["usd"], 6)
    return {"totals": totals, "rows": rows}


def build(out_dir: Path) -> dict:
    """Recompute docs/seasons/stats.json from every season listed in index.json."""
    out_dir = Path(out_dir)
    try:
        index = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = []
    summaries = []
    for entry in index:
        sid = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(sid, str) or not SEASON_ID.match(sid):
            continue
        path = season_dir(out_dir, sid) / "log.jsonl"
        if path.exists():
            summaries.append(season_summary(read_log(path)))
    summaries.sort(key=lambda s: s["season"])
    stats = {
        "real": leaderboard([s for s in summaries if not s["dry_run"]]),
        "demo": leaderboard([s for s in summaries if s["dry_run"]]),
        "seasons": {s["season"]: {"winner": s["winner"], "dry_run": s["dry_run"], "complete": s["complete"],
                                  "places": {n: v["place"] for n, v in s["players"].items()},
                                  "moments": s["moments"]} for s in summaries},
    }
    path = out_dir / "stats.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(stats, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return stats
