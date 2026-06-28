"""``opentelemetry`` observability impl — OTLP gRPC exporter for traces.

Requires the optional ``opentelemetry-sdk`` and
``opentelemetry-exporter-otlp-proto-grpc`` packages::

    pip install pyxen[otel]

Config (in ``runtime.json``):

.. code-block:: json

    "observability": {
        "implementation": "opentelemetry",
        "config": {
            "endpoint": "http://localhost:4317",
            "service_name": "my-app"
        }
    }

The ``endpoint`` and ``headers`` config values support ``$secret`` refs so
they can be loaded from the secrets primitive at runtime:

.. code-block:: json

    "observability": {
        "implementation": "opentelemetry",
        "config": {
            "endpoint": {"$secret": "otel-endpoint"},
            "headers": {"$secret": "otel-headers"},
            "service_name": "my-app"
        }
    }
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import Status, StatusCode, TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _HAS_OTEL = True
except ImportError:  # pragma: no cover — environment-dependent
    _HAS_OTEL = False

_SECRET_REF_KEY = "$secret"


class _OTelSpan:
    """Adapter from pyxen's ``Span`` interface to an OTel span."""

    def __init__(self, span: Any) -> None:
        self._span = span

    def set_attribute(self, key: str, value: Any) -> None:
        self._span.set_attribute(key, value)

    def log(self, level: str, message: str, **fields: Any) -> None:
        attributes: dict[str, Any] = {"level": level, "message": message}
        attributes.update(fields)
        self._span.add_event("log", attributes)


class _OTelTraceContext:
    """Async context manager wrapping an OTel span."""

    def __init__(self, parent: OpenTelemetryObservability, name: str) -> None:
        self._parent = parent
        self._name = name
        self._span: Any = None

    async def __aenter__(self) -> _OTelSpan:
        await self._parent._ensure_resolved()
        self._span = self._parent._tracer.start_span(self._name)
        return _OTelSpan(self._span)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._span is None:
            return
        if exc_type is not None:
            self._span.record_exception(exc)
            self._span.set_status(Status(StatusCode.ERROR))
        self._span.end()
        self._span = None


class OpenTelemetryObservability:
    """Observability impl that exports spans via OTLP gRPC."""

    def __init__(
        self,
        config: dict[str, object],
        secrets: Any | None = None,
    ) -> None:
        self._config = config
        self._secrets = secrets
        self._resolved = False
        self._tracer: Any = None

    async def _ensure_resolved(self) -> None:
        if self._resolved:
            return
        self._resolved = True

        if not _HAS_OTEL:
            raise RuntimeError(
                "opentelemetry requires the opentelemetry-sdk and "
                "opentelemetry-exporter-otlp-proto-grpc packages; "
                "install with `pip install pyxen[otel]`"
            )

        endpoint = self._config.get("endpoint")
        headers = self._config.get("headers")

        if self._secrets is not None:
            if isinstance(endpoint, dict) and _SECRET_REF_KEY in endpoint:
                endpoint = await self._secrets.get(endpoint[_SECRET_REF_KEY])
            if isinstance(headers, dict) and _SECRET_REF_KEY in headers:
                headers = await self._secrets.get(headers[_SECRET_REF_KEY])

        service_name = str(self._config.get("service_name", "pyxen-app"))

        resource = Resource(attributes={"service.name": service_name})
        tracer_provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers=headers,
        )
        processor = BatchSpanProcessor(exporter)
        tracer_provider.add_span_processor(processor)
        self._tracer = tracer_provider.get_tracer("pyxen")

    def trace(self, name: str) -> _OTelTraceContext:
        return _OTelTraceContext(self, name)


def build(
    config: dict[str, object],
    secrets: Any | None = None,
) -> OpenTelemetryObservability:
    return OpenTelemetryObservability(config, secrets)


def _main() -> None:
    """Test entry point for the opentelemetry impl. Skips if SDK not installed."""
    if not _HAS_OTEL:
        import asyncio

        from pyxen._testlib import arun_tests, skip

        async def _run_tests() -> None:

            async def test_eager_build_does_not_raise() -> None:
                build({})

            async def test_raises_on_first_trace() -> None:
                obs = build({})
                try:
                    async with obs.trace("fail"):
                        pass
                except RuntimeError as e:
                    assert "opentelemetry" in str(e)
                else:
                    raise AssertionError(
                        "should raise RuntimeError on first trace when OTel SDK missing"
                    )

            await arun_tests(
                test_eager_build_does_not_raise,
                test_raises_on_first_trace,
            )

        asyncio.run(_run_tests())
        skip("opentelemetry-sdk not installed")
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

            async def test_config_service_name() -> None:
                obs2 = build({"service_name": "test-app"})
                async with obs2.trace("named") as span:
                    span.set_attribute("key", "val")

            await arun_tests(
                test_set_attribute_and_log,
                test_nested_spans,
                test_error_inside_span,
                test_config_service_name,
            )
        finally:
            pass

    asyncio.run(_run_tests())


if __name__ == "__main__":
    _main()
