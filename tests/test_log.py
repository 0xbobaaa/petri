import io
import json
import re
import tempfile
import unittest
import urllib.error
from pathlib import Path

from petri import game
from petri.log import SeasonLog, dumps_line, season_dir, update_index
from petri.players import OpenRouterPlayer

from helpers import HOSTILE, ROOT, run

KEY = "sk-or-v1-TESTKEY0123456789abcdef"


def hostile(ask, reply):
    """Put hostile text into every text field the model controls."""
    reply = dict(reply)
    for field in ("thought", "text", "reason"):
        if field in reply:
            reply[field] = HOSTILE
    return reply


class OneLinePerEventTest(unittest.TestCase):
    def test_hostile_text_stays_one_json_object_per_line(self):
        _, events, raw = run(hostile)
        lines = raw.split("\n")
        self.assertEqual(lines[-1], "")  # file ends with a newline
        lines = lines[:-1]
        self.assertEqual(len(lines), len(events))
        self.assertEqual(len(raw.splitlines()), len(events))  # \u2028 and \x85 are escaped too
        for i, line in enumerate(lines, 1):
            obj = json.loads(line)
            self.assertIsInstance(obj, dict)
            self.assertEqual(obj["seq"], i)
        says = [e for e in events if e["kind"] == "say"]
        self.assertTrue(says and all(e["text"] == HOSTILE for e in says))
        # the injected '{"kind":"winner"}' never became a real event
        self.assertEqual(len([e for e in events if e["kind"] == "winner"]), 1)

    def test_every_event_has_the_common_fields(self):
        _, events, _ = run()
        seqs = [e["seq"] for e in events]
        self.assertEqual(seqs, list(range(1, len(events) + 1)))
        for e in events:
            self.assertIsInstance(e["round"], int)
            self.assertIsInstance(e["phase"], str)
            self.assertIsInstance(e["kind"], str)

    def test_dumps_line_escapes_unicode_line_breaks(self):
        line = dumps_line({"t": "a\u2028b\u2029c\x85d\ne"})
        self.assertEqual(len(line.splitlines()), 1)
        self.assertEqual(json.loads(line)["t"], "a\u2028b\u2029c\x85d\ne")


class SiteUsesTextContentTest(unittest.TestCase):
    """Acceptance 4: the site inserts model text with textContent only."""

    def setUp(self):
        self.html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        self.js = "\n".join(re.findall(r"<script>(.*?)</script>", self.html, re.S))

    def test_no_html_sinks(self):
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                     "new Function", "srcdoc", "DOMParser"):
            self.assertNotIn(sink, self.js, sink)

    def test_text_goes_through_textContent(self):
        self.assertIn("textContent", self.js)
        # the one element helper sets text via textContent
        helper = re.search(r"function el\(.*?\n}", self.js, re.S)
        self.assertIsNotNone(helper)
        self.assertIn(".textContent = ", helper.group(0))

    def test_no_request_to_other_hosts(self):
        self.assertNotRegex(self.html, r"""(src|href)\s*=\s*["']https?://""")
        self.assertNotRegex(self.js, r"fetch\(\s*[\"'`]https?:")
        self.assertNotIn("@import", self.html)


class SecretsTest(unittest.TestCase):
    def test_key_never_reaches_the_log(self):
        """Real client, fake network. Errors, perf and model text must not carry the key."""
        calls = {"n": 0}

        def opener(req, timeout):
            calls["n"] += 1
            self.assertEqual(req.get_header("Authorization"), f"Bearer {KEY}")
            self.assertEqual(timeout, 30)
            body = json.loads(req.data)
            self.assertNotIn("tools", body)
            self.assertNotIn("plugins", body)
            if calls["n"] % 5 == 0:
                raise urllib.error.HTTPError(req.full_url, 401, f"bad key {KEY}", {}, io.BytesIO(KEY.encode()))
            ask_json = {"action": "say", "thought": f"is the key {KEY}?", "text": f"key {KEY}"}
            return FakeResponse({"choices": [{"message": {"content": json.dumps(ask_json)}}],
                                 "usage": {"prompt_tokens": 100, "completion_tokens": 20}})

        players = {n: OpenRouterPlayer("x/model", KEY, opener=opener) for n in game.NAMES}
        _, events, raw = run(players=players, redact=(KEY,))
        self.assertNotIn(KEY, raw)
        self.assertNotIn("TESTKEY", raw)
        self.assertIn("[redacted]", raw)
        self.assertTrue(any(e["kind"] == "perf" and not e["ok"] for e in events))

    def test_player_repr_hides_key(self):
        self.assertNotIn(KEY, repr(OpenRouterPlayer("m", KEY)))

    def test_docs_never_mention_the_key_variable(self):
        for path in (ROOT / "docs").rglob("*"):
            if path.is_file():
                self.assertNotIn("OPENROUTER_API_KEY", path.read_text(encoding="utf-8", errors="ignore"), path)


class FakeResponse:
    def __init__(self, payload):
        self.data = json.dumps(payload).encode()

    def read(self, n=-1):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class PathsAndIndexTest(unittest.TestCase):
    def test_season_id_cannot_escape(self):
        for bad in ("../x", "a/b", "..", "", "A", "x" * 80, "a b", "a\\b"):
            with self.assertRaises(ValueError, msg=bad):
                season_dir(Path("out"), bad)
        self.assertEqual(season_dir(Path("out"), "2026-09-23-42"), Path("out") / "2026-09-23-42")

    def test_index_newest_first_and_upsert(self):
        out = Path(tempfile.mkdtemp())
        update_index(out, {"id": "demo-42", "date": "2026-09-20", "dry_run": True})
        update_index(out, {"id": "2026-09-21-1", "date": "2026-09-21", "dry_run": False})
        update_index(out, {"id": "2026-09-22-5", "date": "2026-09-22", "dry_run": False})
        seasons = update_index(out, {"id": "2026-09-21-1", "date": "2026-09-21", "dry_run": False, "winner": "Qwen"})
        self.assertEqual([s["id"] for s in seasons], ["2026-09-22-5", "2026-09-21-1", "demo-42"])
        self.assertEqual(seasons[1]["winner"], "Qwen")
        on_disk = json.loads((out / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk, seasons)

    def test_log_writes_lf_only(self):
        path = Path(tempfile.mkdtemp()) / "s" / "log.jsonl"
        log = SeasonLog(path)
        log.emit({"round": 0, "phase": "setup", "kind": "x", "t": "a\r\nb"})
        log.close()
        self.assertNotIn(b"\r", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
