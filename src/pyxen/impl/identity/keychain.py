"""``keychain`` identity impl — reads identity from macOS Keychain.

This is a stub for the MVP. The real implementation needs the ``keyring``
package; we deliberately don't import it at module top so the rest of the
runtime loads cleanly on systems without keyring support.

Callers can opt in by adding ``keyring`` to their environment.
"""

from __future__ import annotations

from typing import Any

from ...core.errors import IdentityError
from ...core.identity import Credential, Identity


class KeychainIdentity:
    """Identity impl backed by macOS Keychain (via the ``keyring`` package)."""

    def __init__(self, config: dict[str, object]) -> None:
        self._service = str(config.get("service", "pyxen"))

    def _backend(self) -> Any:
        try:
            import keyring  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise IdentityError(
                "keychain identity impl requires the 'keyring' package; "
                "install it with `pip install keyring`"
            ) from exc
        return keyring

    async def current(self) -> Identity:
        keyring = self._backend()
        ident_id = keyring.get_password(self._service, "identity_id") or "anonymous"
        name = keyring.get_password(self._service, "identity_name")
        return Identity(id=ident_id, name=name, source="keychain")

    async def for_target(self, target: str) -> Credential:
        keyring = self._backend()
        token = keyring.get_password(self._service, target)
        if token is None:
            raise IdentityError(f"no credential for target {target!r} in keychain")
        return Credential(token=token, target=target)


def build(config: dict[str, object]) -> KeychainIdentity:
    return KeychainIdentity(config)


def _main() -> None:
    """Test entry point for keychain identity impl. Skips if `keyring` not installed."""
    from pyxen._testlib import skip, run_tests

    try:
        import keyring  # noqa: F401
    except ImportError:
        def test_raises_identity_error() -> None:
            impl = KeychainIdentity({})
            import asyncio
            try:
                asyncio.run(impl.current())
            except IdentityError as e:
                assert "keyring" in str(e).lower()
            else:
                raise AssertionError("should have raised IdentityError when keyring missing")

        run_tests(test_raises_identity_error)
        skip("keyring not installed")
        return

    def test_build_succeeds() -> None:
        impl = KeychainIdentity({"service": "pyxen-test-service"})
        assert impl._service == "pyxen-test-service"

    run_tests(test_build_succeeds)


if __name__ == "__main__":
    _main()
