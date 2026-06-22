"""Observability primitive — structured, routable telemetry.

The runtime's observability interface is a context-manager trace + a log
call. The impl routes traces to Langfuse, OTel, stdout, file, or any other
sink. The shape is normalized so the same trace shows up in any backend.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Protocol


class Span:
    """A trace span. Use as ``async with rt.observe.trace("name") as span:``."""

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a key/value attribute on the span."""
        return None

    def log(self, level: str, message: str, **fields: Any) -> None:
        """Emit a log event inside the span."""
        return None


class ObservabilityImpl(Protocol):
    """Implementation protocol for the observability primitive."""

    def trace(self, name: str) -> _TraceContext:
        """Return a context manager that opens a span of the given name."""
        ...


class _TraceContext:
    """Async context manager returned by ``ObservabilityImpl.trace``."""

    async def __aenter__(self) -> Span:
        raise NotImplementedError

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


def _main() -> None:
    from pyxen._testlib import run_tests

    def test_observabilityimpl_is_protocol() -> None:
        assert hasattr(ObservabilityImpl, "trace")
        bases_names = {getattr(b, "__name__", "") for b in ObservabilityImpl.__bases__}
        assert "Protocol" in bases_names or hasattr(ObservabilityImpl, "_is_protocol")

    def test_span_methods_dont_raise() -> None:
        s = Span()
        s.set_attribute("k", "v")
        s.log("info", "hi", extra=1)

    run_tests(
        test_observabilityimpl_is_protocol,
        test_span_methods_dont_raise,
    )
