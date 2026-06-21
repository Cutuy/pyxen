"""``inmemory`` storage impl — dict-backed, for tests and fast iteration.

No persistence. Data is lost when the process exits.
"""

from __future__ import annotations

from typing import Any

from ...core.storage import QueryFilter


class InMemoryStorage:
    """In-process dict-backed storage. Not thread-safe; for tests/dev only."""

    def __init__(self, config: dict[str, object]) -> None:
        self._data: dict[tuple[str, str], dict[str, Any]] = {}

    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        self._data[(namespace, key)] = value

    async def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        return self._data.get((namespace, key))

    async def query(
        self, namespace: str, filter: QueryFilter | None = None
    ) -> list[dict[str, Any]]:
        results = [v for (ns, _k), v in self._data.items() if ns == namespace]
        if filter is not None and filter.equals:
            results = [
                r for r in results
                if all(r.get(k) == v2 for k, v2 in filter.equals.items())
            ]
        if filter is not None and filter.limit is not None:
            results = results[: filter.limit]
        return results

    async def delete(self, namespace: str, key: str) -> bool:
        return self._data.pop((namespace, key), None) is not None


def build(config: dict[str, object]) -> InMemoryStorage:
    return InMemoryStorage(config)


def _main() -> None:
    """Test entry point for inmemory storage impl. Thorough coverage."""
    import asyncio

    from pyxen.core import QueryFilter

    async def go() -> None:
        s = build({})

        # put then get
        await s.put("ns", "k", {"v": 1})
        assert await s.get("ns", "k") == {"v": 1}

        # put overwrites
        await s.put("ns", "k", {"v": 2})
        assert await s.get("ns", "k") == {"v": 2}

        # get missing returns None
        assert await s.get("ns", "missing") is None
        assert await s.get("nonexistent", "k") is None

        # put with empty dict
        await s.put("ns", "empty", {})
        assert await s.get("ns", "empty") == {}

        # put with nested values (json-like round-trip)
        await s.put("ns", "nested", {"a": {"b": {"c": [1, 2, 3]}}})
        assert await s.get("ns", "nested") == {"a": {"b": {"c": [1, 2, 3]}}}

        # put with unicode values
        await s.put("ns", "unicode", {"emoji": "\U0001f600", "chinese": "\u4e2d\u6587"})
        assert await s.get("ns", "unicode") == {"emoji": "\U0001f600", "chinese": "\u4e2d\u6587"}

        # put with very long key
        long_key = "key_" + ("x" * 200)
        await s.put("ns", long_key, {"v": 1})
        assert await s.get("ns", long_key) == {"v": 1}

        # multiple keys in same namespace
        await s.put("ns", "a", {"v": 1})
        await s.put("ns", "b", {"v": 2})
        await s.put("ns", "c", {"v": 3})
        # query with no filter returns all
        results = await s.query("ns")
        assert len(results) >= 6  # k, empty, nested, unicode, long_key, a, b, c

        # query with filter
        await s.put("ns", "d", {"v": 1, "tag": "x"})
        await s.put("ns", "e", {"v": 2, "tag": "x"})
        x_only = await s.query("ns", QueryFilter(equals={"tag": "x"}))
        assert len(x_only) == 2
        assert all(r.get("tag") == "x" for r in x_only)

        # query with filter that matches nothing
        empty_filtered = await s.query("ns", QueryFilter(equals={"tag": "nonexistent"}))
        assert empty_filtered == []

        # query with limit
        first_two = await s.query("ns", QueryFilter(limit=2))
        assert len(first_two) == 2

        # query with combined filter + limit
        first_x = await s.query("ns", QueryFilter(equals={"tag": "x"}, limit=1))
        assert len(first_x) == 1

        # query across namespaces is isolated
        await s.put("other", "k", {"v": 99})
        assert len(await s.query("ns")) >= 1
        other = await s.query("other")
        assert len(other) == 1
        assert other[0]["v"] == 99

        # delete existing returns True
        assert await s.delete("ns", "a") is True
        assert await s.get("ns", "a") is None

        # delete missing returns False
        assert await s.delete("ns", "a") is False
        assert await s.delete("nonexistent", "k") is False

    asyncio.run(go())


if __name__ == "__main__":
    _main()
