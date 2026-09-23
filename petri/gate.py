"""The gate: every model reply is parsed and checked here before the game sees it.

A reply is untrusted text. The gate turns it into one of a small set of legal
moves or into a fallback, and says why. It asks the model at most twice.
"""

from __future__ import annotations

import json
import re
import time
from typing import Callable

from .game import Ask

MAX_TEXT = 280
SILENCE = "(silence)"
BACKOFF_SECONDS = 2.0
MAX_ECHO = 2000  # how much of a bad reply is shown back in the correction


class ApiError(Exception):
    """A request to the model failed. The message must never carry a secret."""

    def __init__(self, message: str, ms: int = 0):
        super().__init__(message)
        self.ms = ms


def parse(raw: object, action: str) -> tuple[dict | None, str | None]:
    """Return (object, None) or (None, reason)."""
    obj = _loads(raw) if isinstance(raw, str) else None
    if obj is None:
        return None, "invalid_json"
    if obj.get("action") != action:
        return None, "wrong_action"
    return obj, None


def _loads(text: str) -> dict | None:
    # Tolerate the two usual wrappers — a code fence, or prose around one
    # object — but only ever accept a single JSON object.
    text = text.strip()
    candidates = [text]
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        candidates.append(fence.group(1).strip())
    i, j = text.find("{"), text.rfind("}")
    if 0 <= i < j:
        candidates.append(text[i:j + 1])
    for c in candidates:
        try:
            obj = json.loads(c)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def clip(value: object) -> tuple[str, bool]:
    """Any text field: a string of at most MAX_TEXT chars, plus whether it was cut."""
    if not isinstance(value, str):
        return "", False
    if len(value) > MAX_TEXT:
        return value[:MAX_TEXT], True
    return value, False


def resolve_name(value: object, names: tuple[str, ...]) -> str | None:
    if not isinstance(value, str):
        return None
    wanted = value.strip().lstrip("@").casefold()
    for n in names:
        if n.casefold() == wanted:
            return n
    return None


def _target_problem(target: str | None, ask: Ask) -> str | None:
    if target is None:
        return "target_unknown"
    if target == ask.player:
        return "target_is_self"
    if target not in ask.options:
        return "target_not_in_revote" if ask.phase == "revote" else "target_exiled"
    return None


def fallback(ask: Ask, thought: str = "", truncated: bool = False) -> dict:
    base = {"thought": thought, "truncated": truncated, "fallback": True}
    if ask.action == "say":
        return {"text": SILENCE, **base}
    if ask.action == "whisper":
        return {"skip": True, **base}
    if ask.action == "vote":
        return {"target": None, "reason": "", **base}
    return {"winner": None, "reason": "", **base}


def validate(obj: dict, ask: Ask, names: tuple[str, ...]) -> tuple[dict, str | None]:
    """Turn a parsed object into a legal move. Returns (reply, fallback_reason)."""
    thought, cut = clip(obj.get("thought"))

    if ask.action == "say":
        text, cut_text = clip(obj.get("text"))
        if not text.strip():
            return fallback(ask, thought, cut), "empty_text"
        return {"text": text, "thought": thought, "truncated": cut or cut_text, "fallback": False}, None

    if ask.action == "whisper":
        if obj.get("skip") is True:
            return {"skip": True, "thought": thought, "truncated": cut, "fallback": False}, None
        to = resolve_name(obj.get("to"), names)
        problem = _target_problem(to, ask)
        if problem:
            return fallback(ask, thought, cut), problem
        text, cut_text = clip(obj.get("text"))
        if not text.strip():
            return fallback(ask, thought, cut), "empty_text"
        return {"to": to, "text": text, "thought": thought,
                "truncated": cut or cut_text, "fallback": False}, None

    reason, cut_reason = clip(obj.get("reason"))
    if ask.action == "vote":
        target = resolve_name(obj.get("target"), names)
        problem = _target_problem(target, ask)
        if problem:
            return {**fallback(ask, thought, cut or cut_reason), "reason": reason}, problem
        return {"target": target, "reason": reason, "thought": thought,
                "truncated": cut or cut_reason, "fallback": False}, None

    winner = resolve_name(obj.get("winner"), names)
    if winner not in ask.options:
        return {**fallback(ask, thought, cut or cut_reason), "reason": reason}, "not_a_finalist"
    return {"winner": winner, "reason": reason, "thought": thought,
            "truncated": cut or cut_reason, "fallback": False}, None


def correction(reason: str, action: str) -> str:
    problem = "was not a single valid JSON object" if reason == "invalid_json" \
        else f'had the wrong "action"; this phase needs "{action}"'
    return (f"Your last reply {problem}. Reply again with exactly one JSON object "
            f'with "action": "{action}" and nothing else.')


def consult(call: Callable[[list[dict]], str], messages: list[dict], ask: Ask,
            names: tuple[str, ...], sleep: Callable[[float], None] = time.sleep) -> tuple[dict, str | None]:
    """Ask the model, retry once at most, then fall back. Returns (reply, fallback_reason).

    `call` returns the raw reply text or raises ApiError. Anything else it
    raises (such as a budget stop) passes straight through.
    """
    reason = None
    attempt_messages = messages
    for attempt in (1, 2):
        try:
            raw = call(attempt_messages)
        except ApiError:
            reason = "api_error"
            if attempt == 1:
                sleep(BACKOFF_SECONDS)
            continue
        obj, reason = parse(raw, ask.action)
        if obj is not None:
            return validate(obj, ask, names)
        attempt_messages = messages + [
            {"role": "assistant", "content": raw[:MAX_ECHO] if isinstance(raw, str) else ""},
            {"role": "user", "content": correction(reason, ask.action)},
        ]
    return fallback(ask), reason
