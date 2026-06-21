"""``stdout`` observability impl — structured JSON to stdout.

Useful for dev, CI, and any environment where logs are already being
collected. For production, the OTel or Langfuse impls would be a swap-in
in the ``runtime.json`` config.
"""

from __future__ import annotations

import json
import sys
from types import TracebackType
from typing import Any


class _StdoutSpan:
    """A single trace span. Captures attributes and log events."""

    def __init__(self, name: str, sink: _StdoutObservability) -> None:
        self._name = name
        self._sink = sink
        self._attributes: dict[str, Any] = {}
        self._closed = False

    def set_attribute(self, key: str, value: Any) -> None:
        self._attributes[key] = value

    def log(self, level: str, message: str, **fields: Any) -> None:
        self._sink._emit(
            {"event": "log", "span": self._name, "level": level, "message": message, **fields}
        )

    def _close(self, exc: BaseException | None) -> None:
        if self._closed:
            return
        self._closed = True
        self._sink._emit(
            {
                "event": "span_end",
                "span": self._name,
                "attributes": self._attributes,
                "error": type(exc).__name__ if exc else None,
            }
        )


class _StdoutObservability:
    """Observability impl that emits JSON to stdout."""

    def __init__(self, config: dict[str, object]) -> None:
        self._level = str(config.get("level", "info"))
        self._sink_target = sys.stdout

    def _emit(self, record: dict[str, Any]) -> None:
        self._sink_target.write(json.dumps(record, default=str) + "\n")
        self._sink_target.flush()

    def trace(self, name: str) -> _StdoutTraceContext:
        return _StdoutTraceContext(self, name)


class _StdoutTraceContext:
    """Async context manager returned by ``trace()``."""

    def __init__(self, parent: _StdoutObservability, name: str) -> None:
        self._parent = parent
        self._name = name
        self._span: _StdoutSpan | None = None

    async def __aenter__(self) -> _StdoutSpan:
        self._span = _StdoutSpan(self._name, self._parent)
        self._parent._emit({"event": "span_start", "span": self._name})
        return self._span

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._span is not None:
            self._span._close(exc)


def build(config: dict[str, object]) -> _StdoutObservability:
    return _StdoutObservability(config)


def _main() -> None:
    """Test entry point for stdout observability impl. Verifies JSON emission."""
    import asyncio
    import io
    import json
    import sys

    async def go() -> None:
        # Capture stdout by replacing sys.stdout
        captured = io.StringIO()
        original_stdout = sys.stdout
        sys.stdout = captured
        try:
            obs = build({"level": "info"})
            async with obs.trace("test-span") as span:
                span.set_attribute("user", "alice")
                span.set_attribute("count", 42)
                span.log("info", "starting work", extra="x")
                span.log("warn", "something happened", code=500)
        finally:
            sys.stdout = original_stdout

        # Parse each line as JSON
        output = captured.getvalue()
        lines = [line for line in output.splitlines() if line.startswith("{")]
        assert len(lines) == 4, f"expected 4 lines, got {len(lines)}: {output!r}"

        # span_start
        start = json.loads(lines[0])
        assert start["event"] == "span_start"
        assert start["span"] == "test-span"

        # log lines
        log1 = json.loads(lines[1])
        assert log1["event"] == "log"
        assert log1["span"] == "test-span"
        assert log1["level"] == "info"
        assert log1["message"] == "starting work"
        assert log1["extra"] == "x"

        log2 = json.loads(lines[2])
        assert log2["level"] == "warn"
        assert log2["code"] == 500

        # span_end
        end = json.loads(lines[3])
        assert end["event"] == "span_end"
        assert end["span"] == "test-span"
        assert end["attributes"]["user"] == "alice"
        assert end["attributes"]["count"] == 42
        assert end["error"] is None

        # Span inside an exception captures the error name
        captured2 = io.StringIO()
        sys.stdout = captured2
        try:
            obs2 = build({})
            try:
                async with obs2.trace("error-span") as span:
                    span.set_attribute("op", "test")
                    raise ValueError("boom")
            except ValueError:
                pass
        finally:
            sys.stdout = original_stdout

        end_err = json.loads(
            [line for line in captured2.getvalue().splitlines() if line.startswith("{")][-1]
        )
        assert end_err["error"] == "ValueError"

        # Unicode span name, attributes, and log data
        captured3 = io.StringIO()
        sys.stdout = captured3
        try:
            obs3 = build({})
            async with obs3.trace("span-\U0001f600-\u4e2d\u6587") as span:
                span.set_attribute("emoji", "\U0001f600")
                span.set_attribute("greeting", "\u4f60\u597d")
                span.log("info", "\u043f\u0440\u0438\u0432\u0435\u0442", lang="ru")
        finally:
            sys.stdout = original_stdout

        unicode_lines = [line for line in captured3.getvalue().splitlines() if line.startswith("{")]
        assert len(unicode_lines) == 3  # span_start, log, span_end
        unicode_start = json.loads(unicode_lines[0])
        assert "\u4e2d\u6587" in unicode_start["span"]
        unicode_end = json.loads(unicode_lines[-1])
        assert unicode_end["event"] == "span_end"
        assert "\U0001f600" in unicode_end["attributes"]["emoji"]
        assert unicode_end["attributes"]["greeting"] == "\u4f60\u597d"

    asyncio.run(go())


if __name__ == "__main__":
    _main()
