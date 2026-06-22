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
    from pyxen._testlib import run_tests

    def test_budget_normal() -> None:
        b = Budget(daily_limit=100, spent=30)
        assert b.spent == 30
        assert b.remaining == 70

    def test_budget_over_limit() -> None:
        b_over = Budget(daily_limit=100, spent=200)
        assert b_over.remaining == 0
        assert b_over.remaining == max(0, b_over.daily_limit - b_over.spent)

    def test_budget_spent_equals_limit() -> None:
        b_edge = Budget(daily_limit=100, spent=100)
        assert b_edge.remaining == 0

    def test_budget_spent_zero() -> None:
        b_zero = Budget(daily_limit=100, spent=0)
        assert b_zero.remaining == 100

    def test_checkresult_ok() -> None:
        cr_ok = CheckResult(allowed=True, remaining=50)
        assert cr_ok.allowed is True
        assert cr_ok.remaining == 50
        assert cr_ok.reason is None
        assert cr_ok.budget is None

    def test_checkresult_fail() -> None:
        cr_fail = CheckResult(allowed=False, remaining=0, reason="over daily budget")
        assert cr_fail.allowed is False
        assert cr_fail.remaining == 0
        assert cr_fail.reason == "over daily budget"

    def test_checkresult_with_budget() -> None:
        cr_with_budget = CheckResult(
            allowed=True, remaining=20, reason=None, budget=Budget(daily_limit=100, spent=80)
        )
        assert cr_with_budget.budget is not None
        assert cr_with_budget.budget.remaining == 20

    def test_charge() -> None:
        c = Charge(model="gpt-4o", tokens=1500, dollars=0.045)
        assert c.model == "gpt-4o"
        assert c.tokens == 1500
        assert c.dollars == 0.045

    run_tests(
        test_budget_normal,
        test_budget_over_limit,
        test_budget_spent_equals_limit,
        test_budget_spent_zero,
        test_checkresult_ok,
        test_checkresult_fail,
        test_checkresult_with_budget,
        test_charge,
    )


if __name__ == "__main__":
    _main()
