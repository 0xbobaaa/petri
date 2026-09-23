import unittest

from petri import game
from petri.budget import Budget, BudgetStop

from helpers import Scripted, run

PRICE = {"paid": (1.00, 5.00)}  # usd per million in / out


class BudgetUnitTest(unittest.TestCase):
    def test_cost_from_usage(self):
        b = Budget(PRICE)
        self.assertAlmostEqual(b.cost("paid", 1_000_000, 0), 1.00)
        self.assertAlmostEqual(b.cost("paid", 2000, 400), 0.002 + 0.002)

    def test_max_calls(self):
        b = Budget(PRICE, max_calls=2)
        b.reserve("paid", 10)
        b.reserve("paid", 10)
        with self.assertRaises(BudgetStop) as cm:
            b.reserve("paid", 10)
        self.assertEqual(cm.exception.reason, "max_calls")

    def test_max_usd_stops_before_the_call_that_could_cross_it(self):
        b = Budget(PRICE, max_usd=0.01, max_tokens=400)
        b.charge("paid", 1000, 1000)  # spent 0.006
        b.reserve("paid", 3000)  # worst 0.001 + 0.002 = 0.003 -> 0.009, allowed
        b.charge("paid", 1000, 400)  # spent 0.009
        with self.assertRaises(BudgetStop) as cm:
            b.reserve("paid", 3000)  # would reach 0.012
        self.assertEqual(cm.exception.reason, "max_usd")

    def test_from_env(self):
        b = Budget.from_env({"PETRI_MAX_USD": "0.5", "PETRI_MAX_CALLS": "7"}, PRICE)
        self.assertEqual((b.max_usd, b.max_calls), (0.5, 7))
        b = Budget.from_env({}, PRICE)
        self.assertEqual((b.max_usd, b.max_calls), (3.00, 200))
        with self.assertRaises(ValueError):
            Budget.from_env({"PETRI_MAX_USD": "lots"}, PRICE)


class SeasonStopsTest(unittest.TestCase):
    def paid_players(self, tokens):
        return {n: Scripted(n, 42, lambda ask, r: r, tokens=tokens) for n in game.NAMES}

    def test_stops_at_max_usd(self):
        budget = Budget(PRICE, max_usd=0.05, max_calls=10_000)
        summary, events, _ = run(players=self.paid_players((2000, 200)), budget=budget,
                                 models={n: "paid" for n in game.NAMES})
        self.assertEqual(summary["status"], "budget_stop")
        self.assertIsNone(summary["winner"])
        last = events[-1]
        self.assertEqual((last["kind"], last["reason"]), ("budget_stop", "max_usd"))
        self.assertLessEqual(last["usd_est_total"], 0.05)
        perf_total = sum(e["usd_est"] for e in events if e["kind"] == "perf")
        self.assertAlmostEqual(perf_total, last["usd_est_total"], places=5)
        self.assertEqual(last["calls"], len([e for e in events if e["kind"] == "perf"]))
        self.assertNotIn("winner", [e["kind"] for e in events])
        self.assertNotIn("season_end", [e["kind"] for e in events])

    def test_stops_at_max_calls(self):
        budget = Budget(PRICE, max_usd=1000, max_calls=30)
        summary, events, _ = run(players=self.paid_players((10, 10)), budget=budget,
                                 models={n: "paid" for n in game.NAMES})
        self.assertEqual(summary["status"], "budget_stop")
        self.assertEqual((events[-1]["reason"], events[-1]["calls"]), ("max_calls", 30))
        self.assertEqual(len([e for e in events if e["kind"] == "perf"]), 30)

    def test_no_retry_past_the_cap(self):
        budget = Budget(PRICE, max_usd=1000, max_calls=1)
        summary, events, _ = run(lambda ask, r: "garbage", budget=budget)
        self.assertEqual(summary["calls"], 1)
        self.assertEqual(events[-1]["kind"], "budget_stop")


if __name__ == "__main__":
    unittest.main()
