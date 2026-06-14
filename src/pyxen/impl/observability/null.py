"""``null`` observability impl — drop everything.

Useful for tests where telemetry would be noise. The interface is satisfied
without doing any I/O.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any


class _NullSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def log(self, level: str, message: str, **fields: Any) -> None:
        return None


class _NullTraceContext:
    async def __aenter__(self) -> _NullSpan:
        return _NullSpan()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class NullObservability:
    def __init__(self, config: dict[str, object]) -> None:
        pass

    def trace(self, name: str) -> _NullTraceContext:
        return _NullTraceContext()


def build(config: dict[str, object]) -> NullObservability:
    return NullObservability(config)


def _main() -> None:
    """Test entry point for null observability impl. No-op verification."""
    import asyncio

    async def go() -> None:
        obs = build({})

        # Span context manager does not raise
        async with obs.trace("span") as span:
            span.set_attribute("k", "v")
            span.set_attribute("count", 42)
            span.log("info", "hello", extra=1)
            span.log("error", "bad", code=500)

        # Nested spans are also fine
        async with obs.trace("outer"), obs.trace("inner") as inner:
            inner.set_attribute("nested", True)

        # Trace context outside a span doesn't blow up either
        ctx = obs.trace("never-entered")
        # Don't enter; just verify the context object exists.
        assert ctx is not None

    asyncio.run(go())


if __name__ == "__main__":
    _main()
