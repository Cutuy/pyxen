"""Sandbox primitive — portable code execution with WASI, Docker, and subprocess providers.

The sandbox primitive fills the gap identified in the prior art (WASI, Dagger
Functions): a uniform interface for running code in a sandboxed environment.
The provider manages lifecycle (start/stop) and execution (run). Output is
user-program-defined; the primitive captures stdout/stderr and the exit code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SandboxConfig:
    """Configuration for a sandbox execution environment.

    Attributes:
        packages: List of packages to install inside the sandbox.
        env: Environment variables to set inside the sandbox.
        network: Whether the sandbox has network access.
        timeout: Maximum execution time in seconds (0 = no limit).
        provider_config: Provider-specific configuration.
    """

    packages: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    network: bool = True
    timeout: int = 0
    provider_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class SandboxResult:
    """Result of a single sandbox execution."""

    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float = 0.0


class SandboxImpl(Protocol):
    """Implementation protocol for the sandbox primitive.

    Implementations manage the lifecycle of a sandboxed execution environment
    and provide a run method to execute commands inside it. Package installation
    is self-managed by the implementation.
    """

    async def start(self) -> None:
        """Start the sandbox environment.

        Installs any configured packages and prepares the environment for
        execution. Idempotent: calling start on an already-running sandbox
        is a no-op.
        """
        ...

    async def stop(self) -> None:
        """Stop the sandbox and release resources.

        After stop, the sandbox cannot be used for further execution until
        start is called again. Idempotent: calling stop on a stopped sandbox
        is a no-op.
        """
        ...

    async def run(
        self,
        command: str,
        args: list[str] | None = None,
        stdin: bytes | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Run a command inside the sandbox and return the result.

        Args:
            command: The command to run (e.g. "python", "node", "/app/script").
            args: Arguments to pass to the command.
            stdin: Optional stdin data.
            env: Optional additional environment variables for this run.

        Returns:
            A SandboxResult with stdout, stderr, and exit code.
        """
        ...


def _main() -> None:
    from pyxen._testlib import run_tests

    def test_sandboxconfig_defaults() -> None:
        c = SandboxConfig()
        assert c.packages == []
        assert c.env == {}
        assert c.network is True
        assert c.timeout == 0
        assert c.provider_config == {}

    def test_sandboxconfig_custom() -> None:
        c = SandboxConfig(
            packages=["numpy", "pandas"],
            env={"PATH": "/usr/bin"},
            network=False,
            timeout=30,
            provider_config={"wasm_file": "test.wasm"},
        )
        assert c.packages == ["numpy", "pandas"]
        assert c.env == {"PATH": "/usr/bin"}
        assert c.network is False
        assert c.timeout == 30
        assert c.provider_config == {"wasm_file": "test.wasm"}

    def test_sandboxresult_fields() -> None:
        r = SandboxResult(stdout="hello", stderr="", exit_code=0)
        assert r.stdout == "hello"
        assert r.stderr == ""
        assert r.exit_code == 0

    def test_sandboxresult_with_time() -> None:
        r = SandboxResult(stdout="out", stderr="err", exit_code=1, duration_ms=42.5)
        assert r.duration_ms == 42.5

    def test_sandboximpl_protocol_attrs() -> None:
        assert hasattr(SandboxImpl, "start")
        assert hasattr(SandboxImpl, "stop")
        assert hasattr(SandboxImpl, "run")

    run_tests(
        test_sandboxconfig_defaults,
        test_sandboxconfig_custom,
        test_sandboxresult_fields,
        test_sandboxresult_with_time,
        test_sandboximpl_protocol_attrs,
    )


if __name__ == "__main__":
    _main()
