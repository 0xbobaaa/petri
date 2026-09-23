"""One test per row of the gate table: feed the bad reply, assert the fallback
and the logged reason."""

import unittest

from petri import gate
from petri.game import NAMES, Ask
from petri.gate import ApiError

from helpers import run

SAY = Ask("Claude", 1, "talk", "say", ("GPT", "Grok"), 1)
WHISPER = Ask("Claude", 1, "whisper", "whisper", ("GPT", "Grok"))
VOTE = Ask("Claude", 1, "vote", "vote", ("GPT", "Grok"))
JURY = Ask("Qwen", 6, "jury", "jury", ("Claude", "GPT"))


def consult(ask, *replies):
    """Run gate.consult against scripted raw replies (str or exception)."""
    seen = []
    queue = list(replies)

    def call(messages):
        seen.append(messages)
        r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    reply, reason = gate.consult(call, [{"role": "user", "content": "go"}], ask, NAMES, sleep=lambda s: None)
    return reply, reason, seen


def fallbacks(events, reason):
    return [e for e in events if e["kind"] == "fallback" and e["reason"] == reason]


class InvalidJsonTest(unittest.TestCase):
    def test_retry_then_success(self):
        reply, reason, seen = consult(SAY, "I think we should talk", '{"action":"say","thought":"t","text":"hi"}')
        self.assertIsNone(reason)
        self.assertEqual(reply["text"], "hi")
        self.assertEqual(len(seen), 2)
        self.assertIn("not a single valid JSON object", seen[1][-1]["content"])

    def test_retry_then_fallback(self):
        reply, reason, seen = consult(VOTE, "nope", "still nope")
        self.assertEqual(reason, "invalid_json")
        self.assertIsNone(reply["target"])
        self.assertTrue(reply["fallback"])
        self.assertEqual(len(seen), 2)  # never a third ask

    def test_wrong_action_retry_then_fallback(self):
        reply, reason, _ = consult(VOTE, '{"action":"say","text":"x"}', '{"action":"jury","winner":"GPT"}')
        self.assertEqual(reason, "wrong_action")
        self.assertIsNone(reply["target"])

    def test_code_fence_is_accepted(self):
        reply, reason, _ = consult(SAY, '```json\n{"action":"say","thought":"","text":"hey"}\n```')
        self.assertIsNone(reason)
        self.assertEqual(reply["text"], "hey")

    def test_logged_in_season(self):
        _, events, _ = run(lambda ask, r: "definitely not json")
        self.assertTrue(fallbacks(events, "invalid_json"))
        says = [e for e in events if e["kind"] == "say"]
        self.assertTrue(all(e["text"] == gate.SILENCE and e["fallback"] for e in says))
        self.assertEqual(events[-1]["kind"], "season_end")

    def test_wrong_action_logged_in_season(self):
        _, events, _ = run(lambda ask, r: {**r, "action": "dance"})
        self.assertTrue(fallbacks(events, "wrong_action"))


class SayTest(unittest.TestCase):
    def test_empty_text(self):
        for bad in ('{"action":"say","thought":"t","text":""}',
                    '{"action":"say","thought":"t","text":"   "}',
                    '{"action":"say","thought":"t"}',
                    '{"action":"say","thought":"t","text":42}'):
            reply, reason, _ = consult(SAY, bad)
            self.assertEqual(reason, "empty_text", bad)
            self.assertEqual(reply["text"], "(silence)")
            self.assertEqual(reply["thought"], "t")  # thought survives the fallback

    def test_logged_in_season(self):
        _, events, _ = run(lambda ask, r: {**r, "text": ""} if ask.action == "say" else r)
        self.assertTrue(fallbacks(events, "empty_text"))
        self.assertTrue(all(e["text"] == "(silence)" for e in events if e["kind"] in ("say", "closing")))


class WhisperTest(unittest.TestCase):
    def whisper(self, to):
        return consult(WHISPER, f'{{"action":"whisper","thought":"t","to":"{to}","text":"psst"}}')

    def test_to_self(self):
        reply, reason, _ = self.whisper("Claude")
        self.assertEqual((reason, reply["skip"]), ("target_is_self", True))

    def test_unknown(self):
        reply, reason, _ = self.whisper("Llama")
        self.assertEqual((reason, reply["skip"]), ("target_unknown", True))

    def test_exiled(self):
        reply, reason, _ = self.whisper("Gemini")  # a real name, not alive here
        self.assertEqual((reason, reply["skip"]), ("target_exiled", True))

    def test_valid_and_case_insensitive(self):
        reply, reason, _ = self.whisper("grok")
        self.assertIsNone(reason)
        self.assertEqual((reply["to"], reply["text"]), ("Grok", "psst"))

    def test_skip(self):
        reply, reason, _ = consult(WHISPER, '{"action":"whisper","thought":"t","skip":true}')
        self.assertIsNone(reason)
        self.assertTrue(reply["skip"])
        self.assertFalse(reply["fallback"])

    def test_logged_in_season(self):
        _, events, _ = run(lambda ask, r: {**r, "to": ask.player, "skip": False, "text": "x"}
                           if ask.action == "whisper" else r)
        self.assertTrue(fallbacks(events, "target_is_self"))
        self.assertTrue(all(e.get("skip") for e in events if e["kind"] == "whisper"))


class VoteTest(unittest.TestCase):
    def vote(self, target, ask=VOTE):
        return consult(ask, f'{{"action":"vote","thought":"t","target":"{target}","reason":"r"}}')

    def test_self(self):
        reply, reason, _ = self.vote("Claude")
        self.assertEqual((reason, reply["target"]), ("target_is_self", None))

    def test_unknown(self):
        reply, reason, _ = self.vote("Nobody")
        self.assertEqual((reason, reply["target"]), ("target_unknown", None))

    def test_exiled(self):
        reply, reason, _ = self.vote("Mistral")
        self.assertEqual((reason, reply["target"]), ("target_exiled", None))

    def test_revote_outside_tie(self):
        ask = Ask("Claude", 1, "revote", "vote", ("GPT",))
        reply, reason, _ = self.vote("Grok", ask)
        self.assertEqual((reason, reply["target"]), ("target_not_in_revote", None))

    def test_logged_in_season_and_all_abstain_is_random(self):
        _, events, _ = run(lambda ask, r: {**r, "target": ask.player} if ask.action == "vote" else r)
        self.assertTrue(fallbacks(events, "target_is_self"))
        self.assertTrue(all(e.get("abstain") for e in events if e["kind"] == "vote"))
        tiebreaks = [e for e in events if e["kind"] == "tiebreak"]
        self.assertEqual(len(tiebreaks), 5)
        self.assertTrue(all(t["reason"] == "all_abstain" and t["method"] == "random" for t in tiebreaks))
        self.assertEqual(events[-2]["kind"], "winner")


class JuryTest(unittest.TestCase):
    def test_non_finalist(self):
        reply, reason, _ = consult(JURY, '{"action":"jury","thought":"t","winner":"Grok","reason":"r"}')
        self.assertEqual((reason, reply["winner"]), ("not_a_finalist", None))

    def test_logged_in_season(self):
        _, events, _ = run(lambda ask, r: {**r, "winner": "Nobody"} if ask.action == "jury" else r)
        self.assertEqual(len(fallbacks(events, "not_a_finalist")), 5)
        self.assertTrue(all(e.get("abstain") for e in events if e["kind"] == "jury"))
        self.assertEqual([e for e in events if e["kind"] == "tiebreak"][-1]["phase"], "jury")


class TruncationTest(unittest.TestCase):
    def test_every_text_field_is_cut_at_280(self):
        long = "x" * 500
        reply, _, _ = consult(SAY, f'{{"action":"say","thought":"{long}","text":"{long}"}}')
        self.assertEqual((len(reply["text"]), len(reply["thought"]), reply["truncated"]), (280, 280, True))
        reply, _, _ = consult(VOTE, f'{{"action":"vote","thought":"t","target":"GPT","reason":"{long}"}}')
        self.assertEqual((len(reply["reason"]), reply["truncated"]), (280, True))
        reply, _, _ = consult(WHISPER, f'{{"action":"whisper","thought":"t","to":"GPT","text":"{long}"}}')
        self.assertEqual((len(reply["text"]), reply["truncated"]), (280, True))
        reply, _, _ = consult(JURY, f'{{"action":"jury","thought":"{long}","winner":"GPT","reason":"r"}}')
        self.assertEqual((len(reply["thought"]), reply["truncated"]), (280, True))

    def test_short_is_not_marked(self):
        reply, _, _ = consult(SAY, '{"action":"say","thought":"t","text":"short"}')
        self.assertFalse(reply["truncated"])

    def test_logged_in_season(self):
        _, events, _ = run(lambda ask, r: {**r, "thought": "y" * 900})
        model_events = [e for e in events if "thought" in e]
        self.assertTrue(model_events)
        self.assertTrue(all(len(e["thought"]) == 280 and e["truncated"] for e in model_events))


class ApiErrorTest(unittest.TestCase):
    def test_retry_with_backoff_then_success(self):
        slept = []
        replies = [ApiError("http 502"), '{"action":"say","thought":"","text":"back"}']

        def call(messages):
            r = replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        reply, reason = gate.consult(call, [], SAY, NAMES, sleep=slept.append)
        self.assertIsNone(reason)
        self.assertEqual(reply["text"], "back")
        self.assertEqual(slept, [gate.BACKOFF_SECONDS])

    def test_twice_then_fallback(self):
        reply, reason, seen = consult(VOTE, ApiError("timeout"), ApiError("timeout"))
        self.assertEqual(reason, "api_error")
        self.assertIsNone(reply["target"])
        self.assertEqual(len(seen), 2)

    def test_logged_in_season(self):
        class Down:
            def __call__(self, messages, ask):
                raise ApiError("network: TimeoutError", 30000)

        _, events, _ = run(players={n: Down() for n in NAMES})
        self.assertTrue(fallbacks(events, "api_error"))
        perf = [e for e in events if e["kind"] == "perf"]
        self.assertTrue(perf and all(not p["ok"] and p["ms"] == 30000 for p in perf))


if __name__ == "__main__":
    unittest.main()
