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

    from pyxen._testlib import arun_tests

    async def _run_tests() -> None:
        obs = build({})
        try:
            async def test_span_context_manager() -> None:
                async with obs.trace("span") as span:
                    span.set_attribute("k", "v")
                    span.set_attribute("count", 42)
                    span.log("info", "hello", extra=1)
                    span.log("error", "bad", code=500)

            async def test_nested_spans() -> None:
                async with obs.trace("outer"), obs.trace("inner") as inner:
                    inner.set_attribute("nested", True)

            async def test_trace_context_object() -> None:
                ctx = obs.trace("never-entered")
                assert ctx is not None

            await arun_tests(
                test_span_context_manager,
                test_nested_spans,
                test_trace_context_object,
            )
        finally:
            pass

    asyncio.run(_run_tests())


if __name__ == "__main__":
    _main()
