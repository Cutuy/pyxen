"""Secrets primitive — named, audited access to credentials.

The runtime's secrets interface is a single ``get(name)`` call. Every
access is logged; secrets are never exposed to a model context window or
echoed in agent instructions. The impl decides where the secret lives
(macOS Keychain, Vault, .env, K8s Secrets, OpenAI Manifest.environment, etc.).
"""

from __future__ import annotations

from typing import Protocol


class SecretsImpl(Protocol):
    """Implementation protocol for the secrets primitive."""

    async def get(self, name: str) -> str:
        """Return the secret named ``name``. Raises if missing or inaccessible."""
        ...

    async def set(self, name: str, value: str) -> None:
        """Persist a secret (impl-dependent; some backends are read-only)."""
        ...


def _main() -> None:
    """Test entry point for this module.

    ``SecretsImpl`` is a Protocol. Concrete tests live in ``impl/secrets/*.py``.
    """
    assert hasattr(SecretsImpl, "get")
    assert hasattr(SecretsImpl, "set")
    bases_names = {getattr(b, "__name__", "") for b in SecretsImpl.__bases__}
    assert "Protocol" in bases_names or hasattr(SecretsImpl, "_is_protocol")


if __name__ == "__main__":
    _main()
