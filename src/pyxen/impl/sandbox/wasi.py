"""WASI sandbox provider — runs WebAssembly modules with WASI via wasmtime-py.

Config shape (in ``runtime.json``)::

    {
      "implementation": "wasi",
      "config": {
        "wasm_file": "app.wasm",
        "packages": [],
        "env": {},
        "network": false,
        "timeout": 0,
        "dirs": []
      }
    }

The ``wasm_file`` is resolved relative to the working directory. The provider
instantiates the module with a WASI context, captures stdout/stderr, and
returns the exit code. Package installation is handled by pre-populating a
virtual filesystem or building dependencies into the WASM at compile time.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ...core.errors import SandboxError
from ...core.sandbox import SandboxConfig, SandboxResult

logger = logging.getLogger(__name__)

try:
    import wasmtime

    HAS_WASMTIME = True
except ImportError:
    HAS_WASMTIME = False


class WasiSandbox:
    """WASI-backed sandbox implementation using wasmtime-py.

    Manages the lifecycle of a WASM module compiled with WASI support.
    """

    def __init__(self, config: dict[str, object]) -> None:
        self._config = config
        self._wasm_file = Path(str(config.get("wasm_file", "app.wasm")))
        self._sandbox_config = SandboxConfig(
            packages=list(config.get("packages", []) or []),
            env=dict(config.get("env", {}) or {}),
            network=bool(config.get("network", False)),
            timeout=int(config.get("timeout", 0)),
            provider_config=dict(config.get("provider_config", config)),
        )
        self._started = False
        self._engine: wasmtime.Engine | None = None
        self._store: wasmtime.Store | None = None
        self._module: wasmtime.Module | None = None
        self._linker: wasmtime.Linker | None = None

    async def start(self) -> None:
        """Start the sandbox by instantiating the WASM module with WASI.

        Idempotent: subsequent calls are a no-op.
        """
        if self._started:
            return
        if not HAS_WASMTIME:
            raise SandboxError(
                "wasmtime is not installed. Install it with: pip install wasmtime"
            )
        if not self._wasm_file.is_file():
            raise SandboxError(f"WASM file not found: {self._wasm_file}")

        logger.info("sandbox[wasi]: starting with wasm_file=%s", self._wasm_file)

        try:
            self._engine = wasmtime.Engine()
            self._linker = wasmtime.Linker(self._engine)

            wasi_config = wasmtime.WasiConfig()
            wasi_config.inherit_stdin()
            wasi_config.capture_stdout()
            wasi_config.capture_stderr()

            if not self._sandbox_config.network:
                wasi_config.inherit_network(False)

            env_vars = [f"{k}={v}" for k, v in self._sandbox_config.env.items()]
            if env_vars:
                wasi_config.env = env_vars

            dirs: list[str] = list(self._config.get("dirs", []) or [])
            if dirs:
                wasi_config.preopen_dirs = dirs

            self._store = wasmtime.Store(self._engine)
            self._store.set_wasi(wasi_config)

            wasm_bytes = self._wasm_file.read_bytes()
            self._module = wasmtime.Module(self._engine, wasm_bytes)
            self._linker.define_wasi()

            wasmtime.WasiInstance(self._store, "wasi_snapshot_preview1")
            self._linker.instantiate(self._store, self._module)

            self._started = True
            logger.info("sandbox[wasi]: started successfully")
        except Exception as exc:
            raise SandboxError(
                f"sandbox[wasi]: failed to start: {exc}"
            ) from exc

    async def stop(self) -> None:
        """Stop the sandbox and release resources. Idempotent."""
        if not self._started:
            return
        self._started = False
        self._engine = None
        self._store = None
        self._module = None
        self._linker = None
        logger.info("sandbox[wasi]: stopped")

    async def run(
        self,
        command: str,
        args: list[str] | None = None,
        stdin: bytes | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Run a command inside the WASM module.

        For WASI modules, the entry point is typically ``_start``. The
        ``command`` parameter is passed as argv[0] and ``args`` as the
        remaining argv entries.
        """
        if not self._started:
            raise SandboxError("sandbox[wasi]: not started; call start() first")
        if not HAS_WASMTIME:
            raise SandboxError(
                "wasmtime is not installed. Install it with: pip install wasmtime"
            )

        cmd_args = [command] + (args or [])

        logger.info(
            "sandbox[wasi]: running command=%s args=%s",
            command,
            cmd_args,
        )

        start_time = time.monotonic()

        try:
            assert self._store is not None
            assert self._module is not None
            assert self._linker is not None

            if stdin is not None:
                wasi_config = wasmtime.WasiConfig()
                wasi_config.stdin = stdin
                wasi_config.capture_stdout()
                wasi_config.capture_stderr()
                wasi_config.args = cmd_args
                self._store.set_wasi(wasi_config)

            instance = self._linker.instantiate(self._store, self._module)
            func = instance.exports(self._store).get("_start")
            if func is None:
                raise SandboxError(
                    "sandbox[wasi]: module does not export _start"
                )

            func(self._store)

            stdout = self._store.get_wasi().stdout() or b""
            stderr = self._store.get_wasi().stderr() or b""
            exit_code = self._store.get_wasi().exit_code()

        except wasmtime.ExitError as exc:
            stdout = self._store.get_wasi().stdout() if self._store else b""
            stderr = self._store.get_wasi().stderr() if self._store else b""
            if self._store:
                exit_code = self._store.get_wasi().exit_code()
            else:
                exit_code = exc.exit_code if hasattr(exc, "exit_code") else 1
        except Exception as exc:
            raise SandboxError(
                f"sandbox[wasi]: command failed: {exc}"
            ) from exc

        duration_ms = (time.monotonic() - start_time) * 1000

        stdout_str = stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else str(stdout)
        stderr_str = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else str(stderr)

        return SandboxResult(
            stdout=stdout_str,
            stderr=stderr_str,
            exit_code=exit_code if isinstance(exit_code, int) else 1,
            duration_ms=duration_ms,
        )


def build(config: dict[str, object]) -> WasiSandbox:
    return WasiSandbox(config)


def _main() -> None:
    """Test entry point for wasi sandbox impl."""
    import asyncio

    from pyxen._testlib import arun_tests, run_tests, skip

    def test_build_config() -> None:
        impl = build({"wasm_file": "app.wasm", "packages": ["numpy"], "env": {"KEY": "val"}})
        assert impl._wasm_file.name == "app.wasm"
        assert impl._sandbox_config.packages == ["numpy"]
        assert impl._sandbox_config.env == {"KEY": "val"}
        assert isinstance(impl, WasiSandbox)

    def test_build_defaults() -> None:
        impl = build({})
        assert impl._wasm_file.name == "app.wasm"
        assert impl._sandbox_config.packages == []
        assert impl._sandbox_config.env == {}

    run_tests(
        test_build_config,
        test_build_defaults,
    )

    if not HAS_WASMTIME:
        skip("wasmtime not installed, skipping async tests")
        return

    async def _run_tests() -> None:
        async def test_build() -> None:
            impl = build({"wasm_file": "/nonexistent/test.wasm"})
            assert impl is not None
            assert isinstance(impl, WasiSandbox)

        async def test_missing_wasm_file() -> None:
            impl = build({"wasm_file": "/nonexistent/test.wasm"})
            try:
                await impl.start()
            except SandboxError as e:
                assert "not found" in str(e)
            else:
                raise AssertionError("should have raised SandboxError")

        async def test_run_without_start() -> None:
            impl = build({"wasm_file": "/nonexistent/test.wasm"})
            try:
                await impl.run("echo", ["hi"])
            except SandboxError as e:
                assert "not started" in str(e)
            else:
                raise AssertionError("should have raised SandboxError")

        async def test_stop_idempotent() -> None:
            impl = build({"wasm_file": "/nonexistent/test.wasm"})
            await impl.stop()
            await impl.stop()

        async def test_start_stop() -> None:
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                wasm = Path(tmp) / "test.wasm"
                wasm.write_bytes(b"\x00asm")
                impl = build({"wasm_file": str(wasm)})
                try:
                    await impl.start()
                except SandboxError:
                    pass
                await impl.stop()

        await arun_tests(
            test_build,
            test_missing_wasm_file,
            test_run_without_start,
            test_stop_idempotent,
            test_start_stop,
        )

    asyncio.run(_run_tests())


if __name__ == "__main__":
    _main()
