"""Storage primitive — key-value or document store interface.

The runtime's storage abstraction is a uniform put/get/query interface.
The same interface can be backed by SQLite (local), Postgres (shared),
S3/GCS/R2 (cloud), Redis (ephemeral), or in-memory (testing).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class QueryFilter:
    """A simple filter for storage queries."""

    equals: dict[str, Any] | None = None
    limit: int | None = None


class StorageImpl(Protocol):
    """Implementation protocol for the storage primitive."""

    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """Write a value at (namespace, key)."""
        ...

    async def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        """Read a value at (namespace, key) or return None if missing."""
        ...

    async def query(
        self, namespace: str, filter: QueryFilter | None = None
    ) -> list[dict[str, Any]]:
        """Query a namespace. Filter and backend-specific semantics apply."""
        ...

    async def delete(self, namespace: str, key: str) -> bool:
        """Delete (namespace, key). Returns True if something was deleted."""
        ...


def _main() -> None:
    """Test entry point for this module."""
    # --- QueryFilter dataclass ---
    f1 = QueryFilter()
    assert f1.equals is None
    assert f1.limit is None

    f2 = QueryFilter(equals={"status": "ok"})
    assert f2.equals == {"status": "ok"}
    assert f2.limit is None

    f3 = QueryFilter(equals={"x": 1, "y": 2}, limit=10)
    assert f3.equals == {"x": 1, "y": 2}
    assert f3.limit == 10

    f4 = QueryFilter(limit=0)
    assert f4.limit == 0
    assert f4.equals is None

    # --- StorageImpl protocol attributes are present ---
    assert hasattr(StorageImpl, "put")
    assert hasattr(StorageImpl, "get")
    assert hasattr(StorageImpl, "query")
    assert hasattr(StorageImpl, "delete")


if __name__ == "__main__":
    _main()
