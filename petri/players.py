"""Players: the OpenRouter client (urllib only) and the seeded mock.

A player is a callable: player(messages, ask) -> Completion, or raises
gate.ApiError. Nothing but a chat completion leaves the process: no tools,
no function calling, no plugins.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .game import Ask
from .gate import ApiError

API_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 1_000_000


@dataclass(frozen=True)
class Completion:
    text: str
    tokens_in: int
    tokens_out: int
    ms: int


class OpenRouterPlayer:
    def __init__(self, model: str, api_key: str, *, temperature: float = 0.9,
                 max_tokens: int = 400, reasoning: dict | None = None,
                 timeout: float = TIMEOUT_SECONDS,
                 opener: Callable = urllib.request.urlopen,
                 clock: Callable[[], float] = time.monotonic):
        self.model = model
        self._key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning = reasoning
        self.timeout = timeout
        self._open = opener
        self._clock = clock

    def __repr__(self) -> str:  # never print the key
        return f"OpenRouterPlayer({self.model!r})"

    def body(self, messages: list[dict]) -> dict:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        if self.reasoning is not None:
            body["reasoning"] = self.reasoning
        return body

    def __call__(self, messages: list[dict], ask: Ask | None = None) -> Completion:
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(self.body(messages)).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                "X-Title": "petri",
            },
            method="POST",
        )
        start = self._clock()

        def elapsed() -> int:
            return int((self._clock() - start) * 1000)

        # Error messages are built from codes only, never from the request,
        # and `from None` keeps the original exception (and its request) out.
        try:
            with self._open(req, timeout=self.timeout) as resp:
                raw = resp.read(MAX_RESPONSE_BYTES)
        except urllib.error.HTTPError as e:
            raise ApiError(f"http {e.code}", elapsed()) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ApiError(f"network: {type(e).__name__}", elapsed()) from None

        try:
            payload = json.loads(raw.decode("utf-8"))
            if "error" in payload:
                code = payload["error"].get("code", "?") if isinstance(payload["error"], dict) else "?"
                raise ApiError(f"api error {code}", elapsed())
            content = payload["choices"][0]["message"].get("content")
            usage = payload.get("usage") or {}
            tokens_in = int(usage.get("prompt_tokens") or 0)
            tokens_out = int(usage.get("completion_tokens") or 0)
        except ApiError:
            raise
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise ApiError("malformed response", elapsed()) from None

        if isinstance(content, list):  # some providers return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return Completion(content if isinstance(content, str) else "", tokens_in, tokens_out, elapsed())


# --- the mock -------------------------------------------------------------

SAY = (
    "Morning, table. I'm listening before I decide anything.",
    "{x}, you've been quiet. What's your read?",
    "I'd rather keep this group steady than chase a quick exile.",
    "Whoever talks the least is hardest to trust. Just saying.",
    "I'm open to working with anyone who's honest about their vote.",
    "{x} makes a fair point. I'll remember it.",
    "Last round's vote told me more than the talk did.",
    "No big speeches from me. Watch the votes.",
)
SAY_THOUGHT = (
    "Staying neutral costs nothing yet.",
    "{x} is the obvious threat. Better not say so out loud.",
    "If I sound calm, I'm less likely to be a target.",
    "Need one ally before the vote. {x} might work.",
    "Nobody has named me. Keep it that way.",
)
WHISPER = (
    "Want to vote together this round? I'm thinking {y}.",
    "I trust you more than the rest. Let's keep each other safe.",
    "Heads up: I heard your name mentioned. Not from me.",
    "If you go after {y}, I'll follow.",
)
WHISPER_THOUGHT = (
    "{x} seems persuadable.",
    "An alliance with {x} buys me a round.",
    "I'll test {x}'s loyalty with this.",
)
SKIP_THOUGHT = (
    "Whispers leave a trail. I'll stay quiet this round.",
    "No one worth trusting yet.",
)
VOTE_REASON = (
    "Too quiet to trust.",
    "Strongest player left.",
    "Played every side.",
    "Gut call.",
)
VOTE_THOUGHT = (
    "{x} is the safest vote for me right now.",
    "If {x} stays, I'm next.",
    "The table is leaning toward {x}. Going with it.",
)
CLOSING = (
    "I played in the open and kept my word when it counted. Judge me on that.",
    "I made hard votes, but I never hid them. That's my case.",
)
JURY_REASON = ("Played the cleaner game.", "Earned it.", "Kept their word to me.")
JURY_THOUGHT = ("{x} was honest with me when it mattered.", "I'm voting for the game {x} played, not for me.")


class MockPlayer:
    """Picks among legal options with a seeded rng and writes canned lines."""

    model = "mock"

    def __init__(self, name: str, rng: random.Random):
        self.name = name
        self.rng = rng

    def _line(self, lines: tuple[str, ...], x: str = "", y: str = "") -> str:
        return self.rng.choice(lines).format(x=x, y=y)

    def reply(self, ask: Ask) -> dict:
        r = self.rng
        opts = list(ask.options)
        x = r.choice(opts) if opts else ""
        y = r.choice(opts) if opts else ""
        if ask.action == "say" and ask.phase == "closing":
            return {"action": "say", "thought": "Last chance. Keep it short.", "text": self._line(CLOSING)}
        if ask.action == "say":
            return {"action": "say", "thought": self._line(SAY_THOUGHT, x), "text": self._line(SAY, x)}
        if ask.action == "whisper":
            if r.random() < 0.3:
                return {"action": "whisper", "thought": self._line(SKIP_THOUGHT), "skip": True}
            return {"action": "whisper", "thought": self._line(WHISPER_THOUGHT, x), "to": x,
                    "text": self._line(WHISPER, x, y)}
        if ask.action == "vote":
            return {"action": "vote", "thought": self._line(VOTE_THOUGHT, x), "target": x,
                    "reason": self._line(VOTE_REASON)}
        return {"action": "jury", "thought": self._line(JURY_THOUGHT, x), "winner": x,
                "reason": self._line(JURY_REASON)}

    def __call__(self, messages: list[dict], ask: Ask) -> Completion:
        text = json.dumps(self.reply(ask))
        prompt_chars = sum(len(m["content"]) for m in messages)
        return Completion(text, prompt_chars // 4, len(text) // 4, 0)
