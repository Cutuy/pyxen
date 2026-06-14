"""Tokens primitive — model/token budget check and charge.

This is the runtime-native primitive. The OpenAI Agents SDK has no budget
enforcement; the runtime owns the policy and the bookkeeping.

The check is *soft* in MVP — the impl can warn without blocking, or block
hard, depending on the implementation config.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CheckResult:
    """Result of a budget check."""

    allowed: bool
    remaining: int
    reason: str | None = None
    budget: Budget | None = None


@dataclass(frozen=True)
class Budget:
    """A budget configuration."""

    daily_limit: int
    spent: int

    @property
    def remaining(self) -> int:
        return max(0, self.daily_limit - self.spent)


@dataclass(frozen=True)
class Charge:
    """A record of tokens actually consumed."""

    model: str
    tokens: int
    dollars: float


class TokensImpl(Protocol):
    """Implementation protocol for the tokens primitive."""

    async def check(self, model: str, estimated_tokens: int) -> CheckResult:
        """Check whether ``estimated_tokens`` for ``model`` is within budget."""
        ...

    async def charge(self, model: str, tokens: int, dollars: float) -> None:
        """Record actual consumption after a call finishes."""
        ...


def _main() -> None:
    """Test entry point for this module."""
    # --- Budget dataclass ---
    b = Budget(daily_limit=100, spent=30)
    assert b.spent == 30
    assert b.remaining == 70

    # Spent can exceed daily_limit; remaining clamps at 0
    b_over = Budget(daily_limit=100, spent=200)
    assert b_over.remaining == 0
    assert b_over.remaining == max(0, b_over.daily_limit - b_over.spent)

    # Edge: spent == daily_limit
    b_edge = Budget(daily_limit=100, spent=100)
    assert b_edge.remaining == 0

    # Edge: spent == 0
    b_zero = Budget(daily_limit=100, spent=0)
    assert b_zero.remaining == 100

    # --- CheckResult ---
    cr_ok = CheckResult(allowed=True, remaining=50)
    assert cr_ok.allowed is True
    assert cr_ok.remaining == 50
    assert cr_ok.reason is None
    assert cr_ok.budget is None

    cr_fail = CheckResult(allowed=False, remaining=0, reason="over daily budget")
    assert cr_fail.allowed is False
    assert cr_fail.remaining == 0
    assert cr_fail.reason == "over daily budget"

    cr_with_budget = CheckResult(
        allowed=True, remaining=20, reason=None, budget=Budget(daily_limit=100, spent=80)
    )
    assert cr_with_budget.budget is not None
    assert cr_with_budget.budget.remaining == 20

    # --- Charge ---
    c = Charge(model="gpt-4o", tokens=1500, dollars=0.045)
    assert c.model == "gpt-4o"
    assert c.tokens == 1500
    assert c.dollars == 0.045


if __name__ == "__main__":
    _main()
