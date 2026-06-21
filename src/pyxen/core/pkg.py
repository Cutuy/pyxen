"""Pkg primitive — lock-file-first dependency declaration and satisfaction.

The pkg primitive declares what an app needs to run via lock files (e.g.
``requirements.txt``, ``uv.lock``, ``package-lock.json``) and the runtime
satisfies them by delegating to the package manager that owns the lock
file. The runtime does not parse lock files itself; it shells out to the
underlying tool (``pip``, ``uv``, ``npm``) which already does the
hard part of resolution and hashing.

Three-tier model:
    1. ``ensure()``    — read the configured lock file(s) and install
       any missing deps. Returns a :class:`Snapshot` of what got resolved.
    2. ``verify()``    — fast check that all declared deps are already
       satisfied. No installs. Good for startup health checks.
    3. ``snapshot()``  — return the current resolved state with no
       changes to the environment. For diagnostics, audit, and
       lockfile generation.

The legacy imperative helpers (``ensure_python``, ``ensure_from_manifest``)
remain so an app (or an agent) can request ad-hoc installs at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class PackageInfo:
    """A single resolved package."""

    name: str
    version: str
    source: str  # e.g. "uv", "pip", "npm"


@dataclass
class Snapshot:
    """The resolved state of an environment at a point in time."""

    packages: list[PackageInfo]
    timestamp: float


@dataclass
class VerificationResult:
    """Outcome of a ``verify()`` call."""

    satisfied: bool
    missing: list[str]  # package names not installed


class PkgImpl(Protocol):
    """Implementation protocol for the pkg primitive.

    Implementations delegate to an underlying package manager (``pip``,
    ``uv``, ``npm``, …). They do not reimplement resolution.
    """

    async def ensure(self) -> Snapshot:
        """Read configured lock file(s) and install any missing deps.

        Returns the resolved :class:`Snapshot` describing what is now
        installed. Idempotent: calling on a satisfied env is a no-op
        for the package manager's perspective.
        """
        ...

    async def verify(self) -> VerificationResult:
        """Fast check — are all declared deps satisfied? No installs.

        Suitable for startup health checks and ``pyxen doctor``.
        """
        ...

    async def snapshot(self) -> Snapshot:
        """Current resolved state — no changes to the environment."""
        ...

    async def ensure_python(self, requirements: list[str]) -> None:
        """Ad-hoc imperative install. An app (or agent) can ask for
        extra Python packages at runtime, outside the lock-file path."""
        ...

    async def ensure_from_manifest(self, path: str) -> None:
        """Install deps from an external manifest file (e.g.
        ``pyproject.toml``). Kept for backward compatibility."""
        ...


def _main() -> None:
    """Test entry point for this module.

    Verifies the protocol shape and the dataclass invariants.
    """
    # Protocol shape
    assert hasattr(PkgImpl, "ensure")
    assert hasattr(PkgImpl, "verify")
    assert hasattr(PkgImpl, "snapshot")
    assert hasattr(PkgImpl, "ensure_python")
    assert hasattr(PkgImpl, "ensure_from_manifest")
    bases_names = {getattr(b, "__name__", "") for b in PkgImpl.__bases__}
    assert "Protocol" in bases_names or hasattr(PkgImpl, "_is_protocol")

    # Dataclass round-trips
    pkg = PackageInfo(name="numpy", version="2.1.0", source="pip")
    assert pkg.name == "numpy"
    assert pkg.version == "2.1.0"
    assert pkg.source == "pip"

    snap = Snapshot(packages=[pkg], timestamp=1719000000.0)
    assert len(snap.packages) == 1
    assert snap.timestamp == 1719000000.0

    # Empty packages list
    empty_snap = Snapshot(packages=[], timestamp=0.0)
    assert empty_snap.packages == []
    assert empty_snap.timestamp == 0.0

    result = VerificationResult(satisfied=True, missing=[])
    assert result.satisfied is True
    assert result.missing == []

    fail = VerificationResult(satisfied=False, missing=["numpy", "pandas"])
    assert fail.satisfied is False
    assert fail.missing == ["numpy", "pandas"]

    # Snapshot equality is by value (dataclass default)
    s1 = Snapshot(packages=[PackageInfo("a", "1", "pip")], timestamp=100.0)
    s2 = Snapshot(packages=[PackageInfo("a", "1", "pip")], timestamp=100.0)
    assert s1 == s2


if __name__ == "__main__":
    _main()
