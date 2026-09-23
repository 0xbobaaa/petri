import random
import unittest

from petri import game
from petri.game import Ask


def say(text="hi"):
    return {"text": text, "thought": "t", "truncated": False, "fallback": False}


def vote(target):
    return {"target": target, "reason": "r", "thought": "t", "truncated": False, "fallback": False}


def skip():
    return {"skip": True, "thought": "t", "truncated": False, "fallback": False}


def drive(gen, responder):
    """Run a game generator to the end; responder(ask) -> gated reply."""
    events, asks = [], []
    item = next(gen)
    try:
        while True:
            if isinstance(item, Ask):
                asks.append(item)
                item = gen.send(responder(item))
            else:
                events.append(item)
                item = next(gen)
    except StopIteration:
        pass
    return events, asks


def first_option(ask):
    if ask.action == "say":
        return say()
    if ask.action == "whisper":
        return skip()
    if ask.action == "vote":
        return vote(ask.options[0])
    return {"winner": ask.options[0], "reason": "r", "thought": "t", "truncated": False, "fallback": False}


class TallyTest(unittest.TestCase):
    def test_counts_ignore_abstain(self):
        self.assertEqual(game.tally([("A", "B"), ("C", "B"), ("B", None), ("D", "A")]), {"B": 2, "A": 1})

    def test_leaders(self):
        order = ["A", "B", "C"]
        self.assertEqual(game.leaders({"B": 2, "A": 1}, order), ["B"])
        self.assertEqual(game.leaders({"C": 2, "A": 2}, order), ["A", "C"])
        self.assertEqual(game.leaders({}, order), [])

    def test_seating_is_seeded(self):
        a = game.seat(game.NAMES, random.Random(7))
        b = game.seat(game.NAMES, random.Random(7))
        self.assertEqual(a, b)
        self.assertEqual(sorted(a), sorted(game.NAMES))


class SeasonTest(unittest.TestCase):
    def test_full_season_ends_with_two_finalists_and_a_winner(self):
        seats = list(game.NAMES)
        events, asks = drive(game.play(seats, random.Random(1)), first_option)
        exiles = [e for e in events if e["kind"] == "exile"]
        self.assertEqual(len(exiles), 5)
        final = [e for e in events if e["kind"] == "round_start"][-1]
        self.assertEqual(final["phase"], "final")
        self.assertEqual(len(final["alive"]), 2)
        self.assertEqual(final["jurors"], [e["player"] for e in exiles])
        self.assertEqual(events[-1]["kind"], "winner")
        self.assertIn(events[-1]["player"], final["alive"])
        self.assertEqual(sum(events[-1]["jury_votes"].values()), 5)
        self.assertEqual(len([e for e in events if e["kind"] == "closing"]), 2)
        self.assertEqual(len([e for e in events if e["kind"] == "jury"]), 5)

    def test_round_shape(self):
        events, asks = drive(game.play(list(game.NAMES), random.Random(1)), first_option)
        r1 = [a for a in asks if a.round == 1]
        self.assertEqual([a.action for a in r1].count("say"), 14)  # two passes x 7
        self.assertEqual([a.action for a in r1].count("whisper"), 7)
        self.assertEqual([a.action for a in r1].count("vote"), 7)
        for a in r1:
            if a.action in ("whisper", "vote"):
                self.assertNotIn(a.player, a.options)

    def test_clear_majority_exiles_without_revote(self):
        seats = ["A", "B", "C", "D"]

        def responder(ask):
            if ask.action == "vote":
                return vote("D" if ask.player != "D" else "A")
            return first_option(ask)

        events, _ = drive(game._vote_and_exile(1, seats, random.Random(0)), responder)
        kinds = [e["kind"] for e in events]
        self.assertNotIn("revote", kinds)
        self.assertEqual(events[-1], {"round": 1, "phase": "vote", "kind": "exile", "player": "D", "votes": 3})

    def test_tie_goes_to_revote_between_tied_only(self):
        seats = ["A", "B", "C", "D"]
        plan = {"A": "C", "B": "D", "C": "D", "D": "C"}  # C=2, D=2

        def responder(ask):
            if ask.phase == "revote":
                self.assertTrue(set(ask.options) <= {"C", "D"})
                return vote("C" if ask.player != "C" else "D")
            return vote(plan[ask.player])

        events, asks = drive(game._vote_and_exile(1, seats, random.Random(0)), responder)
        revote = [e for e in events if e["kind"] == "revote"][0]
        self.assertEqual(revote["between"], ["C", "D"])
        self.assertEqual(revote["method"], "revote")
        revote_voters = [a.player for a in asks if a.phase == "revote"]
        self.assertEqual(revote_voters, seats)  # everyone alive votes
        self.assertEqual(events[-1]["player"], "C")
        self.assertEqual(events[-1]["phase"], "revote")
        self.assertNotIn("tiebreak", [e["kind"] for e in events])

    def test_still_tied_is_logged_random_tiebreak(self):
        seats = ["A", "B", "C", "D"]
        plan = {"A": "C", "B": "D", "C": "D", "D": "C"}

        def responder(ask):
            return vote(plan[ask.player])  # same split again in the revote

        events, _ = drive(game._vote_and_exile(1, seats, random.Random(3)), responder)
        tb = [e for e in events if e["kind"] == "tiebreak"]
        self.assertEqual(len(tb), 1)
        self.assertEqual(tb[0]["method"], "random")
        self.assertEqual(tb[0]["between"], ["C", "D"])
        self.assertEqual(tb[0]["reason"], "still_tied")
        self.assertIn(events[-1]["player"], ["C", "D"])
        again, _ = drive(game._vote_and_exile(1, seats, random.Random(3)), responder)
        self.assertEqual(events, again)  # seeded

    def test_all_abstain_is_logged_random_pick(self):
        seats = ["A", "B", "C"]
        events, asks = drive(game._vote_and_exile(2, seats, random.Random(5)), lambda a: vote(None))
        self.assertNotIn("revote", [e["kind"] for e in events])
        tb = [e for e in events if e["kind"] == "tiebreak"][0]
        self.assertEqual(tb["reason"], "all_abstain")
        self.assertEqual(tb["between"], seats)
        self.assertIn(events[-1]["player"], seats)
        self.assertTrue(all(e.get("abstain") for e in events if e["kind"] == "vote"))

    def test_reveal_carries_every_ballot(self):
        seats = ["A", "B", "C"]
        events, _ = drive(game._vote_and_exile(1, seats, random.Random(0)),
                          lambda a: vote(None if a.player == "A" else "A"))
        reveal = [e for e in events if e["kind"] == "reveal"][0]
        self.assertEqual(reveal["votes"], {"A": None, "B": "A", "C": "A"})
        self.assertEqual(reveal["tally"], {"A": 2})
        self.assertEqual(reveal["abstain"], 1)


class JuryTest(unittest.TestCase):
    def jury(self, picks, seed=0):
        finalists = ["F1", "F2"]
        jurors = ["J1", "J2", "J3", "J4", "J5"]

        def responder(ask):
            if ask.action == "say":
                return say("closing")
            w = picks[ask.player]
            return {"winner": w, "reason": "r", "thought": "t", "truncated": False, "fallback": False}

        return drive(game._final(6, finalists, jurors, random.Random(seed)), responder)

    def test_majority_wins(self):
        events, asks = self.jury({"J1": "F1", "J2": "F2", "J3": "F1", "J4": "F2", "J5": "F1"})
        self.assertEqual([a.phase for a in asks], ["closing", "closing"] + ["jury"] * 5)
        self.assertEqual(events[-1]["kind"], "winner")
        self.assertEqual(events[-1]["player"], "F1")
        self.assertEqual(events[-1]["jury_votes"], {"F1": 3, "F2": 2})

    def test_abstain_tie_is_random_and_logged(self):
        events, _ = self.jury({"J1": "F1", "J2": "F2", "J3": "F1", "J4": "F2", "J5": None})
        tb = [e for e in events if e["kind"] == "tiebreak"][0]
        self.assertEqual(tb["method"], "random")
        self.assertEqual(events[-1]["jury_votes"], {"F1": 2, "F2": 2})
        self.assertIn(events[-1]["player"], ["F1", "F2"])


if __name__ == "__main__":
    unittest.main()
