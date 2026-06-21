"""``file`` observability impl — structured JSON to a local log file.

Useful for production daemons, Docker, systemd services, or anywhere you
want traces persisted to disk without depending on OpenAI's cloud backend.

Config (in ``runtime.json``):

.. code-block:: json

    "observability": {
        "implementation": "file",
        "config": {
            "path": "/var/log/capex-traces.jsonl",
            "level": "info"
        }
    }

The ``path`` defaults to ``pyxen-traces.jsonl`` in the current working
directory. Each trace event is one JSON line (JSONL format), making it easy
to tail, grep, or pipe into log aggregators.

``level`` is currently advisory; the impl accepts all events regardless.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import TracebackType
from typing import Any


class _FileSpan:
    """A single trace span. Captures attributes and log events."""

    def __init__(self, name: str, sink: _FileObservability) -> None:
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


class _FileObservability:
    """Observability impl that appends JSON lines to a file."""

    def __init__(self, config: dict[str, object]) -> None:
        raw_path = str(config.get("path", "pyxen-traces.jsonl"))
        self._path = Path(raw_path).expanduser().resolve()
        self._level = str(config.get("level", "info"))

        # Ensure parent directory exists
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Open in append mode; create if doesn't exist
        self._file = open(self._path, "a", encoding="utf-8")  # noqa: SIM115 — file lives for object lifetime

    def _emit(self, record: dict[str, Any]) -> None:
        self._file.write(json.dumps(record, default=str) + "\n")
        self._file.flush()
        # Also fsync for durability (only on POSIX)
        os.fsync(self._file.fileno())

    def trace(self, name: str) -> _FileTraceContext:
        return _FileTraceContext(self, name)

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()


class _FileTraceContext:
    """Async context manager returned by ``trace()``."""

    def __init__(self, parent: _FileObservability, name: str) -> None:
        self._parent = parent
        self._name = name
        self._span: _FileSpan | None = None

    async def __aenter__(self) -> _FileSpan:
        self._span = _FileSpan(self._name, self._parent)
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


def build(config: dict[str, object]) -> _FileObservability:
    return _FileObservability(config)


def _main() -> None:
    """Test entry point for file observability impl. Verifies JSON emission."""
    import asyncio
    import json
    import tempfile
    from pathlib import Path

    async def go() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = str(Path(tmp) / "traces.jsonl")

            obs = build({"path": log_path, "level": "info"})
            try:
                async with obs.trace("test-span") as span:
                    span.set_attribute("user", "alice")
                    span.set_attribute("count", 42)
                    span.log("info", "starting work", extra="x")
                    span.log("warn", "something happened", code=500)
            finally:
                obs.close()

            # Read back and verify
            lines = Path(log_path).read_text(encoding="utf-8").splitlines()
            assert len(lines) == 4, f"expected 4 lines, got {len(lines)}: {lines!r}"

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
        with tempfile.TemporaryDirectory() as tmp:
            log_path = str(Path(tmp) / "errors.jsonl")
            obs2 = build({"path": log_path})
            try:
                try:
                    async with obs2.trace("error-span") as span:
                        span.set_attribute("op", "test")
                        raise ValueError("boom")
                except ValueError:
                    pass
            finally:
                obs2.close()

            end_err = json.loads(
                [line for line in Path(log_path).read_text(encoding="utf-8").splitlines() if line][-1]
            )
            assert end_err["error"] == "ValueError"

        # Default path
        obs3 = build({})
        try:
            async with obs3.trace("default") as span:
                span.set_attribute("key", "val")
        finally:
            obs3.close()
            default_path = Path.cwd() / "pyxen-traces.jsonl"
            assert default_path.exists()
            default_path.unlink()

        # Parent dirs are auto-created
        with tempfile.TemporaryDirectory() as tmp:
            deep_path = str(Path(tmp) / "a" / "b" / "c" / "deep.jsonl")
            obs4 = build({"path": deep_path})
            try:
                async with obs4.trace("nest") as span:
                    span.set_attribute("depth", 3)
            finally:
                obs4.close()
            assert Path(deep_path).exists()

        # Unicode span name, attributes, and log data
        with tempfile.TemporaryDirectory() as tmp:
            unicode_path = str(Path(tmp) / "unicode.jsonl")
            obs5 = build({"path": unicode_path})
            try:
                async with obs5.trace("span-\U0001f600-\u4e2d\u6587") as span:
                    span.set_attribute("emoji", "\U0001f600")
                    span.set_attribute("greeting", "\u4f60\u597d")
                    span.log("info", "\u043f\u0440\u0438\u0432\u0435\u0442", lang="ru")
            finally:
                obs5.close()
            unicode_lines = Path(unicode_path).read_text(encoding="utf-8").splitlines()
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
