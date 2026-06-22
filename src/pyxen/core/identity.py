"""Identity primitive — who's calling, and on whose behalf.

The identity primitive answers: who is this app on behalf of? It exposes a
"current" identity (the user the app is acting as) and a "for_target" call
that returns a credential scoped to a particular service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


@dataclass(frozen=True)
class Identity:
    """The current principal the app is acting on behalf of."""

    id: str
    name: str | None = None
    source: str = "unknown"


@dataclass(frozen=True)
class Credential:
    """A credential scoped to a specific service or API."""

    token: str
    target: str
    expires_at: datetime | None = None
    metadata: dict[str, str] | None = None


class IdentityImpl(Protocol):
    """Implementation protocol for the identity primitive."""

    async def current(self) -> Identity:
        """Return the current identity."""
        ...

    async def for_target(self, target: str) -> Credential:
        """Return a credential scoped to ``target`` (e.g., 'github.com')."""
        ...


def _main() -> None:
    from pyxen._testlib import run_tests

    def test_identity_alice() -> None:
        i = Identity(id="alice", name="Alice", source="keychain")
        assert i.id == "alice"
        assert i.name == "Alice"
        assert i.source == "keychain"

    def test_identity_bob_minimal() -> None:
        i2 = Identity(id="bob")
        assert i2.id == "bob"
        assert i2.name is None
        assert i2.source == "unknown"

    def test_identity_frozen() -> None:
        i = Identity(id="alice", name="Alice", source="keychain")
        try:
            i.id = "mutate"  # type: ignore[misc]
        except Exception:  # noqa: BLE001
            pass
        else:
            raise AssertionError("Identity should be frozen")

    def test_credential_with_expires() -> None:
        from datetime import datetime

        cred = Credential(
            token="ghp_xxx",
            target="github.com",
            expires_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
        assert cred.token == "ghp_xxx"
        assert cred.target == "github.com"
        assert cred.expires_at is not None
        assert cred.expires_at.year == 2026

    def test_credential_without_optional() -> None:
        cred2 = Credential(token="x", target="y")
        assert cred2.expires_at is None
        assert cred2.metadata is None

    run_tests(
        test_identity_alice,
        test_identity_bob_minimal,
        test_identity_frozen,
        test_credential_with_expires,
        test_credential_without_optional,
    )


if __name__ == "__main__":
    _main()
