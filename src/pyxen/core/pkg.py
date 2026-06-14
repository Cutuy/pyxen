"""Pkg primitive — environment / dependency declaration and satisfaction.

The pkg primitive declares what an app needs to run (Python deps, system
packages, repos, mounts, env vars) and the runtime satisfies them. The
runtime doesn't reinstall on every call; it caches, resolves conflicts, and
leaves the heavy lifting to the underlying backend (pip, OpenAI Manifest,
Docker, Nix, etc.).
"""

from __future__ import annotations

from typing import Protocol


class PkgImpl(Protocol):
    """Implementation protocol for the pkg primitive."""

    async def ensure_python(self, requirements: list[str]) -> None:
        """Ensure the given Python packages are available."""
        ...

    async def ensure_from_manifest(self, path: str) -> None:
        """Ensure dependencies declared in a manifest file (e.g., pyproject.toml)."""
        ...


def _main() -> None:
    """Test entry point for this module.

    ``PkgImpl`` is a Protocol with no own data. The meaningful tests live in
    each concrete implementation (impl/pkg/*.py).
    """
    # Verify the protocol shape is right
    assert hasattr(PkgImpl, "ensure_python")
    assert hasattr(PkgImpl, "ensure_from_manifest")
    # PkgImpl has Protocol in its bases (or _is_protocol is set)
    bases_names = {getattr(b, "__name__", "") for b in PkgImpl.__bases__}
    assert "Protocol" in bases_names or hasattr(PkgImpl, "_is_protocol")


if __name__ == "__main__":
    _main()
