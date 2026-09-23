"""The season log (append-only jsonl) and docs/seasons/index.json.

Model output is stored only as JSON string values. File names come from the
season id, which code makes; never from anything a model said.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

SEASON_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
REDACTED = "[redacted]"

# json.dumps(ensure_ascii=False) leaves these raw. They are line breaks to
# some readers, so escape them to keep one event per line for everyone.
_LINE_BREAKS = {"\u2028": "\\u2028", "\u2029": "\\u2029", "\x85": "\\u0085"}


def dumps_line(record: dict) -> str:
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    for raw, esc in _LINE_BREAKS.items():
        line = line.replace(raw, esc)
    return line


def season_dir(out_dir: Path, season_id: str) -> Path:
    if not SEASON_ID.match(season_id):
        raise ValueError(f"bad season id: {season_id!r}")
    return Path(out_dir) / season_id


class SeasonLog:
    def __init__(self, path: Path, redact: tuple[str, ...] = ()):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.events: list[dict] = []
        self._redact = tuple(s for s in redact if s)
        self._f = open(path, "w", encoding="utf-8", newline="\n")

    def emit(self, ev: dict) -> dict:
        record = {"seq": len(self.events) + 1, **ev}
        line = dumps_line(record)
        for secret in self._redact:
            line = line.replace(secret, REDACTED)
        self._f.write(line + "\n")
        self._f.flush()
        self.events.append(record)
        return record

    def close(self) -> None:
        self._f.close()


def read_log(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="\n") as f:
        return [json.loads(line) for line in f.read().split("\n") if line]


def update_index(out_dir: Path, entry: dict) -> list[dict]:
    """Insert or replace one season in index.json, newest first."""
    path = Path(out_dir) / "index.json"
    try:
        seasons = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(seasons, list):
            seasons = []
    except (OSError, ValueError):
        seasons = []
    seasons = [s for s in seasons if isinstance(s, dict) and s.get("id") != entry["id"]]
    seasons.insert(0, entry)
    # Demo seasons sink below real ones; within each group, newest first.
    seasons.sort(key=lambda s: (not s.get("dry_run"), s.get("date") or ""), reverse=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(seasons, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return seasons
