import json
import tempfile
import unittest
from pathlib import Path

from petri import stats
from petri.budget import Budget
from petri.game import NAMES
from petri.log import update_index

from helpers import run


def whisper_then_vote_same(ask, reply):
    """Every player whispers to the first option and then votes for them."""
    reply = dict(reply)
    if ask.action == "whisper":
        reply.update({"skip": False, "to": ask.options[0], "text": f"with you, {ask.options[0]}"})
    elif ask.action == "vote":
        reply["target"] = ask.options[0]
    return reply


class SeasonSummaryTest(unittest.TestCase):
    def test_places_cover_one_to_seven(self):
        _, events, _ = run()
        s = stats.season_summary(events)
        self.assertTrue(s["complete"])
        places = sorted(v["place"] for v in s["players"].values())
        self.assertEqual(places, [1, 2, 3, 4, 5, 6, 7])
        winner = next(e for e in events if e["kind"] == "winner")["player"]
        self.assertEqual(s["players"][winner]["place"], 1)
        first_out = next(e for e in events if e["kind"] == "exile")["player"]
        self.assertEqual(s["players"][first_out]["place"], 7)

    def test_betrayal_is_whisper_then_vote_same_round(self):
        _, events, _ = run(whisper_then_vote_same)
        s = stats.season_summary(events)
        betrayals = [m for m in s["moments"] if m["type"] == "betrayal"]
        self.assertTrue(betrayals)
        by_seq = {e["seq"]: e for e in events}
        for m in betrayals:
            vote, whisper = by_seq[m["seq"]], by_seq[m["whisper_seq"]]
            self.assertEqual((vote["kind"], whisper["kind"]), ("vote", "whisper"))
            self.assertEqual((vote["player"], vote["target"]), (m["player"], m["target"]))
            self.assertEqual((whisper["player"], whisper["to"]), (m["player"], m["target"]))
            self.assertEqual(vote["round"], whisper["round"])
            self.assertEqual(m["whisper"], whisper["text"])
        total_broken = sum(v["broken"] for v in s["players"].values())
        total_betrayed = sum(v["betrayed"] for v in s["players"].values())
        self.assertEqual(total_broken, len(betrayals))
        self.assertEqual(total_betrayed, len(betrayals))

    def test_no_betrayal_without_whisper(self):
        def no_whispers(ask, reply):
            return {"action": "whisper", "thought": "", "skip": True} if ask.action == "whisper" else reply
        _, events, _ = run(no_whispers)
        s = stats.season_summary(events)
        self.assertFalse([m for m in s["moments"] if m["type"] == "betrayal"])

    def test_every_moment_points_at_a_real_event(self):
        _, events, _ = run(whisper_then_vote_same)
        seqs = {e["seq"] for e in events}
        for m in stats.season_summary(events)["moments"]:
            self.assertIn(m["seq"], seqs)

    def test_final_moment(self):
        _, events, _ = run()
        final = [m for m in stats.season_summary(events)["moments"] if m["type"] == "final"]
        self.assertEqual(len(final), 1)
        self.assertEqual(sum(final[0]["jury_votes"].values()), 5)


class LeaderboardTest(unittest.TestCase):
    def test_stopped_seasons_count_in_totals_only(self):
        _, done, _ = run(seed=1)
        _, stopped, _ = run(seed=2, budget=Budget({"mock": (0.0, 0.0)}, max_calls=20))
        board = stats.leaderboard([stats.season_summary(done), stats.season_summary(stopped)])
        self.assertEqual(board["totals"]["seasons"], 2)
        self.assertEqual(board["totals"]["complete"], 1)
        self.assertEqual({r["seasons"] for r in board["rows"]}, {1})
        self.assertEqual(sum(r["wins"] for r in board["rows"]), 1)
        self.assertEqual(len(board["rows"]), 7)

    def test_rates_are_bounded(self):
        summaries = [stats.season_summary(run(seed=s)[1]) for s in (1, 2, 3)]
        board = stats.leaderboard(summaries)
        self.assertEqual(sum(r["wins"] for r in board["rows"]), 3)
        for r in board["rows"]:
            for k in ("win_rate", "jury_share", "broken_rate", "read_room", "fallback_rate"):
                if r[k] is not None:
                    self.assertTrue(0 <= r[k] <= 1, (r["player"], k, r[k]))
            self.assertTrue(1 <= r["avg_place"] <= 7)


class BuildTest(unittest.TestCase):
    def test_build_splits_real_and_demo_and_is_deterministic(self):
        summary, _, _ = run(seed=5)
        out = Path(summary["path"]).parent.parent
        update_index(out, {"id": summary["season"], "date": "2026-09-24", "dry_run": True})
        update_index(out, {"id": "../escape", "date": "2026-09-24", "dry_run": False})  # ignored
        first = stats.build(out)
        raw1 = (out / "stats.json").read_bytes()
        stats.build(out)
        self.assertEqual(raw1, (out / "stats.json").read_bytes())
        self.assertEqual(first["demo"]["totals"]["seasons"], 1)
        self.assertEqual(first["real"]["totals"]["seasons"], 0)
        self.assertEqual(list(first["seasons"]), [summary["season"]])
        self.assertEqual(json.loads(raw1)["seasons"][summary["season"]]["dry_run"], True)

    def test_build_with_no_index(self):
        out = Path(tempfile.mkdtemp())
        self.assertEqual(stats.build(out)["real"]["rows"], [])


if __name__ == "__main__":
    unittest.main()
