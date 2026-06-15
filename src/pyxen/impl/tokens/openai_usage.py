"""``openai_usage`` tokens backend — structured token accounting using the OpenAI SDK.

This implementation uses ``agents.usage.Usage`` to provide a high-fidelity
token budget. Instead of just a raw number, it tracks prompt, completion,
and reasoning tokens.

Config (in ``runtime.json``):

.. code-block:: json

    "tokens": {
        "implementation": "openai_usage",
        "config": {
            "daily_limit": 1000000,
            "path": "./token-usage.json"
        }
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from agents.usage import Usage
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False


class OpenAIUsageTokens:
    """Tokens impl that tracks structured usage via the OpenAI Agents SDK."""

    def __init__(self, config: dict[str, object]) -> None:
        if not _HAS_OPENAI:
            raise RuntimeError(
                "openai-agents is not installed. Run: pip install pyxen[openai]"
            )

        self._path = Path(str(config.get("path", "token-usage.json"))).resolve()
        self._daily_limit = int(config.get("daily_limit", 1000000))
        self._usage = self._load()

    def _load(self) -> Usage:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                # Use the SDK's deserializer if available, or manual mapping
                from agents.usage import InputTokensDetails, OutputTokensDetails
                return Usage(
                    input_tokens=data.get("input_tokens", 0),
                    output_tokens=data.get("output_tokens", 0),
                    output_tokens_details=OutputTokensDetails(
                        reasoning_tokens=data.get("reasoning_tokens", 0)
                    ),
                    total_tokens=data.get("input_tokens", 0) + data.get("output_tokens", 0),
                    input_tokens_details=InputTokensDetails(
                        cached_tokens=data.get("cached_tokens", 0)
                    )
                )
            except (json.JSONDecodeError, KeyError):
                pass
        from agents.usage import InputTokensDetails, OutputTokensDetails
        return Usage(
            input_tokens=0,
            output_tokens=0,
            output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
            input_tokens_details=InputTokensDetails(cached_tokens=0),
            total_tokens=0
        )

    def _save(self) -> None:
        data = {
            "input_tokens": self._usage.input_tokens,
            "output_tokens": self._usage.output_tokens,
            "reasoning_tokens": self._usage.output_tokens_details.reasoning_tokens,
            "cached_tokens": self._usage.input_tokens_details.cached_tokens,
            "total_tokens": self._usage.total_tokens,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    async def check(
        self, model: str, estimated_tokens: int = 0
    ) -> dict[str, Any]:
        """Check if the estimated tokens fit within the daily limit."""
        current_total = self._usage.total_tokens
        allowed = (current_total + estimated_tokens) <= self._daily_limit

        return {
            "allowed": allowed,
            "remaining": max(0, self._daily_limit - current_total),
            "current_usage": {
                "total": current_total,
                "input": self._usage.input_tokens,
                "output": self._usage.output_tokens,
                "reasoning": self._usage.output_tokens_details.reasoning_tokens,
            },
            "model": model,
        }

    async def consume(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int = 0,
    ) -> None:
        """Record actual token consumption."""
        from agents.usage import InputTokensDetails, OutputTokensDetails
        self._usage.add(Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            output_tokens_details=OutputTokensDetails(reasoning_tokens=reasoning_tokens),
            input_tokens_details=InputTokensDetails(cached_tokens=0),
            total_tokens=input_tokens + output_tokens,
            requests=1
        ))
        self._save()


def build(config: dict[str, object]) -> OpenAIUsageTokens:
    return OpenAIUsageTokens(config)


def _main() -> None:
    """Test entry point for openai_usage tokens impl."""
    import asyncio
    import tempfile

    async def go() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = str(Path(tmp) / "usage.json")
            
            # 1. Initial check
            t = build({"path": log_path, "daily_limit": 1000})
            res = await t.check("gpt-4o", 100)
            assert res["allowed"] is True
            assert res["current_usage"]["total"] == 0

            # 2. Consume some
            await t.consume("gpt-4o", input_tokens=50, output_tokens=50)
            
            # 3. Check again
            res2 = await t.check("gpt-4o", 100)
            assert res2["current_usage"]["total"] == 100
            assert res2["remaining"] == 900
            
            # 4. Persistence check (re-load)
            t2 = build({"path": log_path, "daily_limit": 1000})
            res3 = await t2.check("gpt-4o", 0)
            assert res3["current_usage"]["total"] == 100

            # 5. Limit enforcement
            res4 = await t2.check("gpt-4o", 1000)
            assert res4["allowed"] is False

    if _HAS_OPENAI:
        asyncio.run(go())
    else:
        print("Skipping openai_usage tests (sdk not installed)")


if __name__ == "__main__":
    _main()
