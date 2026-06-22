"""``json_budget`` tokens impl — soft budget with JSON file backing.

The MVP impl. The budget is **soft** in this version: ``check`` returns
``allowed=True`` with a ``reason`` describing the situation; the app is
expected to read ``reason`` and decide. The interface allows a hard-block
impl in the future without changing call sites.
"""

from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path
from typing import Any

from ...core.tokens import Budget, CheckResult


def _today() -> str:
    return date.today().isoformat()


class JsonBudgetTokens:
    """JSON-file-backed token budget, one file per ``path``."""

    def __init__(self, config: dict[str, object]) -> None:
        path_str = config.get("path")
        if not isinstance(path_str, str):
            raise ValueError("json_budget tokens impl requires config['path']")
        self._path = Path(path_str)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        default_daily = config.get("daily_limit", 100_000)
        if not isinstance(default_daily, int):
            raise ValueError("daily_limit must be an int")
        self._default_daily: int = default_daily
        self._lock = threading.Lock()
        if not self._path.exists():
            self._save({"day": _today(), "spent": 0})

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {"day": _today(), "spent": 0}
        if not isinstance(data, dict):
            return {"day": _today(), "spent": 0}
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self._path.write_text(json.dumps(data), encoding="utf-8")

    def _current_budget(self) -> Budget:
        data = self._load()
        if data.get("day") != _today():
            data = {"day": _today(), "spent": 0}
            self._save(data)
        spent = int(data.get("spent", 0))
        return Budget(daily_limit=self._default_daily, spent=spent)

    async def check(self, model: str, estimated_tokens: int) -> CheckResult:
        budget = self._current_budget()
        would_spend = budget.spent + max(0, estimated_tokens)
        remaining = max(0, budget.daily_limit - would_spend)
        return CheckResult(
            allowed=True,
            remaining=remaining,
            reason=None if would_spend <= budget.daily_limit else "soft: over daily budget",
            budget=budget,
        )

    async def charge(self, model: str, tokens: int, dollars: float) -> None:
        with self._lock:
            data = self._load()
            if data.get("day") != _today():
                data = {"day": _today(), "spent": 0}
            data["spent"] = int(data.get("spent", 0)) + max(0, tokens)
            self._save(data)


def build(config: dict[str, object]) -> JsonBudgetTokens:
    return JsonBudgetTokens(config)


def _main() -> None:
    """Test entry point for json_budget tokens impl. Soft-budget semantics."""
    import asyncio
    import tempfile
    from pathlib import Path

    from pyxen._testlib import arun_tests

    async def _run_tests() -> None:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                b = build({"path": str(Path(tmp) / "b.json"), "daily_limit": 1000})

                async def test_first_check_fresh_file() -> None:
                    check = await b.check("gpt-4o", 500)
                    assert check.allowed is True
                    assert check.remaining == 500
                    assert check.reason is None

                async def test_charge_then_check() -> None:
                    await b.charge("gpt-4o", tokens=300, dollars=0.0)
                    check2 = await b.check("gpt-4o", 200)
                    assert check2.allowed is True
                    assert check2.remaining == 500

                async def test_over_budget_soft() -> None:
                    await b.charge("gpt-4o", tokens=900, dollars=0.0)
                    check3 = await b.check("gpt-4o", 100)
                    assert check3.allowed is True
                    assert check3.reason is not None
                    assert "budget" in check3.reason.lower() or "soft" in check3.reason.lower()
                    assert check3.remaining == 0

                async def test_negative_charge_noop() -> None:
                    await b.charge("gpt-4o", tokens=-100, dollars=0.0)

                await arun_tests(
                    test_first_check_fresh_file,
                    test_charge_then_check,
                    test_over_budget_soft,
                    test_negative_charge_noop,
                )

            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "b.json"
                f.write_text("not valid json")
                b2 = build({"path": str(f), "daily_limit": 100})

                async def test_corrupt_file_reset() -> None:
                    check4 = await b2.check("m", 50)
                    assert check4.allowed is True
                    assert check4.remaining == 50

                await arun_tests(test_corrupt_file_reset)

            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "b.json"
                b_default = build({"path": str(f)})

                async def test_daily_limit_default() -> None:
                    check5 = await b_default.check("m", 1)
                    assert check5.budget is not None
                    assert check5.budget.daily_limit == 100_000

                await arun_tests(test_daily_limit_default)

            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "b.json"
                b_persist = build({"path": str(f), "daily_limit": 1000})
                await b_persist.charge("gpt-4o", tokens=600, dollars=0.0)
                b_reload = build({"path": str(f), "daily_limit": 1000})

                async def test_persistence() -> None:
                    check6 = await b_reload.check("gpt-4o", 500)
                    assert check6.allowed is True
                    assert check6.reason is not None
                    assert check6.remaining == 0
                    check7 = await b_reload.check("gpt-4o", 1)
                    assert check7.remaining == 399

                await arun_tests(test_persistence)
        finally:
            pass

    asyncio.run(_run_tests())

    # Missing path raises
    try:
        build({})
    except ValueError:
        pass
    else:
        raise AssertionError("missing path should raise ValueError")

    # Non-int daily_limit raises
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            build({"path": str(Path(tmp) / "x.json"), "daily_limit": "lots"})
    except ValueError:
        pass
    else:
        raise AssertionError("non-int daily_limit should raise ValueError")


if __name__ == "__main__":
    _main()
