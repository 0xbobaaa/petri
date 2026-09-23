import unittest

from petri import context
from petri.game import NAMES, Ask

from helpers import RULES, run


def season_start():
    return {"seq": 1, "round": 0, "phase": "setup", "kind": "season_start",
            "roster": [{"name": n, "model": "mock"} for n in NAMES]}


class WindowTest(unittest.TestCase):
    def test_only_last_40_public_messages(self):
        events = [season_start()]
        for i in range(100):
            events.append({"round": 1 + i // 50, "phase": "talk", "kind": "say",
                           "player": NAMES[i % 7], "text": f"msg-{i:03d}", "thought": f"secret-{i:03d}"})
        ask = Ask("Claude", 3, "talk", "say", (), 1)
        prompt = context.build(events, ask, RULES)[1]["content"]
        shown = [i for i in range(100) if f"msg-{i:03d}" in prompt]
        self.assertEqual(shown, list(range(60, 100)))
        # older messages are summarised by code, one line per round
        self.assertIn("Round 1: 50 earlier public messages not shown", prompt)
        self.assertIn("Round 2: 10 earlier public messages not shown", prompt)
        self.assertNotIn("secret-", prompt)

    def test_rules_are_the_system_message(self):
        msgs = context.build([season_start()], Ask("GPT", 1, "talk", "say", (), 1), RULES)
        self.assertEqual(msgs[0], {"role": "system", "content": RULES})
        self.assertIn("You are GPT.", msgs[1]["content"])

    def test_prompts_stay_small_all_season(self):
        sizes = []
        run(on_prompt=lambda ask, msgs: sizes.append(sum(len(m["content"]) for m in msgs)))
        self.assertLess(max(sizes), 12_000)


class NoLeakTest(unittest.TestCase):
    def test_no_prompt_holds_another_players_whisper_or_thought(self):
        """Every text a model writes gets a unique marker; then check every prompt."""
        counter = [0]
        owner = {}  # marker -> (author, kind, recipient)

        def mark(author, kind, to=None):
            counter[0] += 1
            m = f"MARK{counter[0]:05d}X"
            owner[m] = (author, kind, to)
            return m

        def fn(ask, reply):
            reply = dict(reply)
            reply["thought"] = mark(ask.player, "thought")
            if ask.action == "whisper" and not reply.get("skip"):
                reply["text"] = mark(ask.player, "whisper", reply["to"])
            elif ask.action == "say":
                reply["text"] = mark(ask.player, "say")
            elif "reason" in reply:
                reply["reason"] = mark(ask.player, "reason")
            return reply

        prompts = []
        _, events, _ = run(fn, on_prompt=lambda ask, msgs: prompts.append((ask.player, msgs)))
        self.assertGreater(len(prompts), 100)
        whispers_seen = 0
        for player, msgs in prompts:
            text = "\n".join(m["content"] for m in msgs)
            for m in [w for w in text.split() if "MARK" in w]:
                key = m[m.index("MARK"):m.index("MARK") + 10]
                author, kind, to = owner[key]
                self.assertNotEqual(kind, "thought", f"{player} saw a thought by {author}")
                self.assertNotEqual(kind, "reason", f"{player} saw a vote reason by {author}")
                if kind == "whisper":
                    self.assertIn(player, (author, to), f"{player} saw {author}'s whisper to {to}")
                    whispers_seen += 1
        self.assertGreater(whispers_seen, 0)  # own whispers do show up

    def test_ballots_are_blind_until_reveal(self):
        prompts = []
        _, events, _ = run(on_prompt=lambda ask, msgs: prompts.append((ask, msgs[1]["content"])))
        for ask, text in prompts:
            if ask.phase == "vote":
                self.assertNotIn(f"Round {ask.round} vote:", text)


if __name__ == "__main__":
    unittest.main()
