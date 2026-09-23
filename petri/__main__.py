"""CLI front door.

    python -m petri run                 play a real season (needs OPENROUTER_API_KEY)
    python -m petri run --dry-run       mock season, no key, no network
    python -m petri run --seed 42       fix the seed
    python -m petri replay <season-id>  print a season to the terminal
"""

from __future__ import annotations

import argparse
import json
import os
import random
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import game
from .budget import Budget
from .log import read_log, season_dir, update_index
from .players import MockPlayer, OpenRouterPlayer
from .runner import run_season

ROOT = Path(__file__).resolve().parent.parent
ROSTER = ROOT / "roster.json"
RULES = ROOT / "prompts" / "rules.md"
SEASONS = ROOT / "docs" / "seasons"


def load_roster(path: Path = ROSTER) -> dict:
    roster = json.loads(path.read_text(encoding="utf-8"))
    names = [p["name"] for p in roster["players"]]
    if sorted(names) != sorted(game.NAMES):
        raise ValueError(f"roster.json must list exactly: {', '.join(game.NAMES)}")
    return roster


def cmd_run(args: argparse.Namespace) -> int:
    roster = load_roster()
    rules = RULES.read_text(encoding="utf-8")
    seed = args.seed if args.seed is not None else secrets.randbelow(10**9)
    out = Path(args.out)
    max_tokens = int(roster.get("max_tokens", 400))

    if args.dry_run:
        players = {n: MockPlayer(n, random.Random(f"{seed}:{n}")) for n in game.NAMES}
        models = {n: "mock" for n in game.NAMES}
        prices = {"mock": (0.0, 0.0)}
        season_id = f"demo-{seed}"
        redact: tuple[str, ...] = ()
    else:
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            print("error: OPENROUTER_API_KEY is not set; refusing to run a real season "
                  "(use --dry-run for a mock season)", file=sys.stderr)
            return 2
        temperature = float(roster.get("temperature", 0.9))
        players, models, prices = {}, {}, {}
        for p in roster["players"]:
            players[p["name"]] = OpenRouterPlayer(p["model"], key, temperature=temperature,
                                                  max_tokens=max_tokens, reasoning=p.get("reasoning"))
            models[p["name"]] = p["model"]
            prices[p["model"]] = (float(p["usd_in_per_m"]), float(p["usd_out_per_m"]))
        season_id = f"{datetime.now(timezone.utc):%Y-%m-%d}-{seed}"
        n = 2
        base = season_id
        while season_dir(out, season_id).exists():
            season_id = f"{base}-{n}"
            n += 1
        redact = (key,)

    try:
        budget = Budget.from_env(os.environ, prices, max_tokens)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    summary = run_season(players=players, models=models, seed=seed, season_id=season_id,
                         out_dir=out, rules=rules, budget=budget, dry_run=args.dry_run, redact=redact)
    update_index(out, {
        "id": season_id,
        "date": f"{datetime.now(timezone.utc):%Y-%m-%d}",
        "dry_run": args.dry_run,
        "status": summary["status"],
        "winner": summary["winner"],
        "usd_est_total": summary["usd_est_total"],
        "calls": summary["calls"],
        "rounds": summary["rounds"],
    })

    if summary["status"] == "complete":
        message = f"season {season_id}: {summary['winner']} wins"
    else:
        message = f"season {season_id}: budget stop"
    print(f"{summary['path']}\n{summary['calls']} calls, ~${summary['usd_est_total']:.4f}")
    print(message)
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"message={message}\nseason={season_id}\n")
    return 0


def fmt(e: dict) -> str | None:
    k, p = e["kind"], e.get("player", "")
    if k == "season_start":
        demo = " (demo, mock players)" if e.get("dry_run") else ""
        seats = ", ".join(f"{r['name']} [{r['model']}]" for r in e["roster"])
        return f"== season {e['season']}{demo}, seed {e['seed']}\n   seats: {seats}"
    if k == "round_start":
        label = "FINAL" if e["phase"] == "final" else f"ROUND {e['round']}"
        return f"\n-- {label}: {', '.join(e['alive'])}"
    if k in ("say", "closing"):
        tag = "closing " if k == "closing" else ""
        return f"{p:>9} {tag}| {e['text']}\n{'':>9}   (thinks: {e['thought']})"
    if k == "whisper":
        if e.get("skip"):
            return f"{p:>9} ~ skips whisper   (thinks: {e['thought']})"
        return f"{p:>9} ~> {e['to']}: {e['text']}\n{'':>9}   (thinks: {e['thought']})"
    if k == "vote":
        target = "abstains" if e.get("abstain") else f"votes {e['target']}"
        return f"{p:>9} {target} - {e['reason']}\n{'':>9}   (thinks: {e['thought']})"
    if k == "reveal":
        return f"   tally: {e['tally']}  abstain: {e['abstain']}"
    if k in ("revote", "tiebreak"):
        return f"   {k}: {', '.join(e['between'])} ({e['method']})"
    if k == "exile":
        return f"   >> {p} is exiled ({e['votes']} votes)"
    if k == "jury":
        pick = "abstains" if e.get("abstain") else f"picks {e['winner']}"
        return f"{p:>9} (juror) {pick} - {e['reason']}\n{'':>9}   (thinks: {e['thought']})"
    if k == "winner":
        return f"\n** {p} wins, jury {e['jury_votes']}"
    if k == "fallback":
        return f"   ! fallback for {p}: {e['reason']}"
    if k in ("budget_stop", "season_end"):
        why = f" ({e['reason']})" if k == "budget_stop" else ""
        return f"\n== {k}{why}: {e['calls']} calls, ~${e['usd_est_total']:.4f}"
    return None  # perf lines are for the site


def cmd_replay(args: argparse.Namespace) -> int:
    try:
        path = season_dir(Path(args.out), args.season_id) / "log.jsonl"
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not path.exists():
        print(f"error: no season {args.season_id!r} in {args.out}", file=sys.stderr)
        return 1
    for e in read_log(path):
        line = fmt(e)
        if line is not None:
            print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # model text may not fit the console codepage
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(prog="petri", description="Seven models, one vote, no way out.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="play a season")
    run.add_argument("--dry-run", action="store_true", help="mock players: no key, no network")
    run.add_argument("--seed", type=int, help="fix the seed")
    run.add_argument("--out", default=str(SEASONS), help="seasons directory (default docs/seasons)")
    rep = sub.add_parser("replay", help="print a season to the terminal")
    rep.add_argument("season_id")
    rep.add_argument("--out", default=str(SEASONS), help="seasons directory (default docs/seasons)")
    args = ap.parse_args(argv)
    return cmd_run(args) if args.cmd == "run" else cmd_replay(args)


if __name__ == "__main__":
    sys.exit(main())
