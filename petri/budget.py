"""Cost estimate and the two hard stops: PETRI_MAX_USD and PETRI_MAX_CALLS."""

from __future__ import annotations

from typing import Mapping

DEFAULT_MAX_USD = 3.00
DEFAULT_MAX_CALLS = 200
CHARS_PER_TOKEN = 3  # deliberately low, so the pre-call estimate errs high


class BudgetStop(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason  # "max_usd" or "max_calls"


class Budget:
    def __init__(self, prices: Mapping[str, tuple[float, float]], *, max_usd: float = DEFAULT_MAX_USD,
                 max_calls: int = DEFAULT_MAX_CALLS, max_tokens: int = 400):
        """prices: model id -> (usd per million input tokens, usd per million output tokens)."""
        self.prices = dict(prices)
        self.max_usd = max_usd
        self.max_calls = max_calls
        self.max_tokens = max_tokens
        self.spent = 0.0
        self.calls = 0

    @classmethod
    def from_env(cls, env: Mapping[str, str], prices, max_tokens: int = 400) -> "Budget":
        try:
            max_usd = float(env.get("PETRI_MAX_USD") or DEFAULT_MAX_USD)
            max_calls = int(env.get("PETRI_MAX_CALLS") or DEFAULT_MAX_CALLS)
        except ValueError:
            raise ValueError("PETRI_MAX_USD must be a number and PETRI_MAX_CALLS an integer") from None
        return cls(prices, max_usd=max_usd, max_calls=max_calls, max_tokens=max_tokens)

    def cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        p_in, p_out = self.prices.get(model, (0.0, 0.0))
        return (tokens_in * p_in + tokens_out * p_out) / 1_000_000

    def reserve(self, model: str, prompt_chars: int) -> None:
        """Call before every request. Raises BudgetStop if the call could break a cap."""
        if self.calls >= self.max_calls:
            raise BudgetStop("max_calls")
        worst = self.cost(model, prompt_chars // CHARS_PER_TOKEN + 1, self.max_tokens)
        if self.spent + worst > self.max_usd:
            raise BudgetStop("max_usd")
        self.calls += 1

    def charge(self, model: str, tokens_in: int, tokens_out: int) -> float:
        usd = self.cost(model, tokens_in, tokens_out)
        self.spent += usd
        return usd
