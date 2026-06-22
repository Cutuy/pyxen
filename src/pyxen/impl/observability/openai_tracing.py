"""``openai_tracing`` observability impl — wraps the OpenAI Agents SDK tracing.

The simplest OpenAI SDK piece to consume per-primitive. The OpenAI Agents
SDK ships ``agents.tracing`` (a sync context manager); this impl wraps it
behind the pyxen ``ObservabilityImpl`` interface (which is async).

Requires the optional ``openai-agents`` package:

    pip install pyxen[openai]

If the package isn't installed at import time, ``build()`` raises a
clear ``RuntimeError`` so the user knows which optional dep to install.

---

This module wraps the OpenAI Agents SDK tracing API
(``agents.tracing``). The OpenAI Agents SDK is
Copyright (c) 2025 OpenAI and is licensed under the MIT License.
See ``NOTICE.md`` in the pyxen repository root for the full license text.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

# Optional dep. Imported lazily so the rest of pyxen loads cleanly on
# systems without the OpenAI Agents SDK.
try:
    from agents import tracing as _openai_tracing
    _HAS_OPENAI_TRACING = True
except ImportError:  # pragma: no cover — environment-dependent
    _openai_tracing = None  # type: ignore[assignment]
    _HAS_OPENAI_TRACING = False


class _OpenAITracingSpan:
    """Adapter that satisfies pyxen's ``Span`` shape over the SDK's Span.

    The SDK's ``Span`` exposes ``span_data`` (a dict-like ``SpanData``);
    pyxen's interface takes ``set_attribute(k, v)`` and ``log(level, msg, ...)``.
    We store the SDK span and forward.
    """

    def __init__(self, sdk_span: Any) -> None:
        self._sdk = sdk_span

    def set_attribute(self, key: str, value: Any) -> None:
        # The SDK's SpanData has an `export` method; we mutate the underlying
        # dict-like store if available, else fall back to a no-op.
        import contextlib
        data = getattr(self._sdk, "span_data", None)
        if data is not None and hasattr(data, "__setitem__"):
            data[key] = value
        elif data is not None:
            # Pydantic-style: try setattr
            with contextlib.suppress(Exception):
                setattr(data, key, value)

    def log(self, level: str, message: str, **fields: Any) -> None:
        # Encode the log as a structured attribute so it travels with the span.
        self.set_attribute(f"log.{level}.message", message)
        for k, v in fields.items():
            self.set_attribute(f"log.{level}.{k}", v)



class _OpenAITracingContext:
    """Async context manager wrapping the SDK's sync context manager.

    The OpenAI Agents SDK tracing is synchronous (``with custom_span(...)``);
    pyxen's observability interface is async (``async with rt.observ.trace(...)``).
    This adapter lets the two meet.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._sync_cm: Any = None
        self._sdk_span: _OpenAITracingSpan | None = None

    async def __aenter__(self) -> _OpenAITracingSpan:
        if _openai_tracing is None:
            raise RuntimeError(
                "openai_tracing requires the openai-agents package; "
                "install with `pip install pyxen[openai]`"
            )
        # `custom_span` is the most generic SDK span constructor.
        self._sync_cm = _openai_tracing.custom_span(self._name)
        sdk = self._sync_cm.__enter__()
        self._sdk_span = _OpenAITracingSpan(sdk)
        return self._sdk_span

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._sync_cm is not None:
            self._sync_cm.__exit__(exc_type, exc, tb)


class OpenAITracingObservability:
    """Observability impl that emits traces to the OpenAI Agents SDK."""

    def __init__(self, config: dict[str, object]) -> None:
        if not _HAS_OPENAI_TRACING:
            raise RuntimeError(
                "openai_tracing requires the openai-agents package; "
                "install with `pip install pyxen[openai]`"
            )

    def trace(self, name: str) -> _OpenAITracingContext:
        return _OpenAITracingContext(name)


def build(config: dict[str, object]) -> OpenAITracingObservability:
    return OpenAITracingObservability(config)


def _main() -> None:
    """Test entry point for the openai_tracing impl. Skips if SDK not installed."""
    if not _HAS_OPENAI_TRACING:
        try:
            build({})
        except RuntimeError as e:
            assert "openai-agents" in str(e)
        else:
            raise AssertionError("build() should raise when openai-agents missing")
        from pyxen._testlib import skip
        skip("openai-agents not installed")
        return

    import asyncio

    from pyxen._testlib import arun_tests

    async def _run_tests() -> None:
        obs = build({})
        try:
            async def test_set_attribute_and_log() -> None:
                async with obs.trace("test-span") as span:
                    span.set_attribute("user", "alice")
                    span.set_attribute("count", 42)
                    span.log("info", "starting work", extra="x")
                    span.log("warn", "something happened", code=500)

            async def test_nested_spans() -> None:
                async with obs.trace("outer"), obs.trace("inner") as inner:
                    inner.set_attribute("nested", True)

            async def test_error_inside_span() -> None:
                try:
                    async with obs.trace("error-span") as span:
                        span.set_attribute("op", "test")
                        raise ValueError("boom")
                except ValueError:
                    pass

            await arun_tests(
                test_set_attribute_and_log,
                test_nested_spans,
                test_error_inside_span,
            )
        finally:
            pass

    asyncio.run(_run_tests())


if __name__ == "__main__":
    _main()
