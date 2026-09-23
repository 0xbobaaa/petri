import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT


def dry_run(out, seed="42"):
    env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
    return subprocess.run([sys.executable, "-m", "petri", "run", "--dry-run", "--seed", seed, "--out", str(out)],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)


class DryRunTest(unittest.TestCase):
    def test_full_season_with_a_winner_twice_byte_identical(self):
        a, b = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        ra, rb = dry_run(a), dry_run(b)
        self.assertEqual(ra.returncode, 0, ra.stderr)
        self.assertEqual(rb.returncode, 0, rb.stderr)
        log_a = (a / "demo-42" / "log.jsonl").read_bytes()
        log_b = (b / "demo-42" / "log.jsonl").read_bytes()
        self.assertEqual(log_a, log_b)

        events = [json.loads(line) for line in log_a.decode("utf-8").split("\n") if line]
        self.assertEqual(events[0]["kind"], "season_start")
        self.assertTrue(events[0]["dry_run"])
        self.assertEqual(events[0]["seed"], 42)
        self.assertEqual(events[-1]["kind"], "season_end")
        winner = [e for e in events if e["kind"] == "winner"]
        self.assertEqual(len(winner), 1)
        self.assertIn(f"{winner[0]['player']} wins", ra.stdout)

        index = json.loads((a / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index[0]["id"], "demo-42")
        self.assertEqual(index[0]["winner"], winner[0]["player"])
        self.assertTrue(index[0]["dry_run"])

    def test_different_seed_different_season(self):
        a, b = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        dry_run(a, "1"), dry_run(b, "2")
        self.assertNotEqual((a / "demo-1" / "log.jsonl").read_bytes(), (b / "demo-2" / "log.jsonl").read_bytes())

    def test_real_run_without_key_fails_with_one_line(self):
        env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
        out = Path(tempfile.mkdtemp())
        r = subprocess.run([sys.executable, "-m", "petri", "run", "--out", str(out)],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)
        self.assertIn("OPENROUTER_API_KEY", r.stderr)
        self.assertEqual(list(out.iterdir()), [])  # never falls back to a dry run

    def test_committed_demo_season_is_marked(self):
        index = json.loads((ROOT / "docs" / "seasons" / "index.json").read_text(encoding="utf-8"))
        demo = [s for s in index if s["dry_run"]]
        self.assertTrue(demo)
        first = (ROOT / "docs" / "seasons" / demo[0]["id"] / "log.jsonl").read_text(encoding="utf-8")
        self.assertTrue(json.loads(first.split("\n")[0])["dry_run"])

    def test_replay_prints_the_season(self):
        out = Path(tempfile.mkdtemp())
        dry_run(out)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run([sys.executable, "-m", "petri", "replay", "demo-42", "--out", str(out)],
                           cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("wins, jury", r.stdout)
        bad = subprocess.run([sys.executable, "-m", "petri", "replay", "../etc", "--out", str(out)],
                             cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(bad.returncode, 2)


if __name__ == "__main__":
    unittest.main()
