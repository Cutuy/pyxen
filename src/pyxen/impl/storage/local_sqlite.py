"""``local_sqlite`` storage impl — single-file SQLite backend.

The MVP impl. No external services, no network. Uses the stdlib ``sqlite3``
module. Each (namespace, key) is a row in a single ``items`` table.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from ...core.errors import StorageError
from ...core.storage import QueryFilter


class LocalSqliteStorage:
    """SQLite-backed key/value store. One file, one ``items`` table."""

    def __init__(self, config: dict[str, object]) -> None:
        path_str = config.get("path")
        if not isinstance(path_str, str):
            raise StorageError("local_sqlite storage requires config['path']")
        self._path = Path(path_str)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS items ("
            "  namespace TEXT NOT NULL,"
            "  key TEXT NOT NULL,"
            "  value TEXT NOT NULL,"
            "  PRIMARY KEY (namespace, key)"
            ")"
        )
        self._conn.commit()

    def _row_to_value(self, row: tuple[str, str, str]) -> dict[str, Any]:
        loaded = json.loads(row[2])
        if not isinstance(loaded, dict):
            raise StorageError(f"storage row at key {row[1]!r} is not a dict")
        return loaded

    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        encoded = json.dumps(value)
        with self._lock:
            self._conn.execute(
                "INSERT INTO items (namespace, key, value) VALUES (?, ?, ?)"
                " ON CONFLICT(namespace, key) DO UPDATE SET value=excluded.value",
                (namespace, key, encoded),
            )
            self._conn.commit()

    async def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT namespace, key, value FROM items WHERE namespace = ? AND key = ?",
                (namespace, key),
            )
            row = cur.fetchone()
        return self._row_to_value(row) if row is not None else None

    async def query(
        self, namespace: str, filter: QueryFilter | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT namespace, key, value FROM items WHERE namespace = ?",
                (namespace,),
            )
            rows = cur.fetchall()
        results = [self._row_to_value(r) for r in rows]
        if filter is not None and filter.equals:
            results = [
                r for r in results
                if all(r.get(k) == v for k, v in filter.equals.items())
            ]
        if filter is not None and filter.limit is not None:
            results = results[: filter.limit]
        return results

    async def delete(self, namespace: str, key: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM items WHERE namespace = ? AND key = ?",
                (namespace, key),
            )
            self._conn.commit()
            return cur.rowcount > 0


def build(config: dict[str, object]) -> LocalSqliteStorage:
    return LocalSqliteStorage(config)


def _main() -> None:
    """Test entry point for local_sqlite storage impl. Thorough coverage."""
    import asyncio
    import tempfile
    from pathlib import Path

    from pyxen.core import QueryFilter

    async def go() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            s = build({"path": str(db_path)})

            # put then get
            await s.put("ns", "k", {"v": 1, "name": "alice"})
            assert await s.get("ns", "k") == {"v": 1, "name": "alice"}

            # put overwrites
            await s.put("ns", "k", {"v": 2})
            assert await s.get("ns", "k") == {"v": 2}

            # get missing returns None
            assert await s.get("ns", "missing") is None
            assert await s.get("nonexistent", "k") is None

            # put with empty dict
            await s.put("ns", "empty", {})
            assert await s.get("ns", "empty") == {}

            # put with nested values (json round-trip)
            await s.put("ns", "nested", {"a": {"b": {"c": [1, 2, 3]}}})
            assert await s.get("ns", "nested") == {"a": {"b": {"c": [1, 2, 3]}}}

            # multiple keys
            await s.put("ns", "a", {"v": 1})
            await s.put("ns", "b", {"v": 2})
            await s.put("ns", "c", {"v": 3})
            all_in_ns = await s.query("ns")
            assert len(all_in_ns) >= 3  # includes k, empty, nested, a, b, c

            # query with filter
            await s.put("ns", "x1", {"tag": "red", "n": 1})
            await s.put("ns", "x2", {"tag": "red", "n": 2})
            await s.put("ns", "x3", {"tag": "blue", "n": 3})
            red = await s.query("ns", QueryFilter(equals={"tag": "red"}))
            assert all(r["tag"] == "red" for r in red)
            assert len(red) == 2

            # query with limit
            first_three = await s.query("ns", QueryFilter(limit=3))
            assert len(first_three) == 3

            # delete existing
            assert await s.delete("ns", "a") is True
            assert await s.get("ns", "a") is None

            # delete missing
            assert await s.delete("ns", "missing_xyz") is False
            assert await s.delete("nonexistent", "k") is False

            # cross-namespace isolation
            await s.put("other", "k", {"v": 99})
            other_items = await s.query("other")
            assert len(other_items) == 1
            assert other_items[0]["v"] == 99
            assert len(await s.query("ns")) != len(await s.query("other"))

            # Query with filter that matches nothing
            empty_filtered = await s.query("ns", QueryFilter(equals={"tag": "nonexistent"}))
            assert empty_filtered == []

            # Put with very long key and namespace
            long_ns = "ns_" + ("x" * 200)
            long_key = "key_" + ("y" * 200)
            await s.put(long_ns, long_key, {"v": 1})
            assert await s.get(long_ns, long_key) == {"v": 1}

            # Put with unicode values
            await s.put("ns", "unicode", {"emoji": "\U0001f600", "chinese": "\u4e2d\u6587"})
            got_unicode = await s.get("ns", "unicode")
            assert got_unicode == {"emoji": "\U0001f600", "chinese": "\u4e2d\u6587"}

            # Persistence: close and reopen should preserve data
            s._conn.close()
            s2 = build({"path": str(db_path)})
            assert await s2.get("ns", "k") == {"v": 2}
            assert await s2.get("other", "k") == {"v": 99}
            assert await s2.get("ns", "unicode") == {"emoji": "\U0001f600", "chinese": "\u4e2d\u6587"}

    asyncio.run(go())

    # Missing config path raises
    try:
        build({})
    except StorageError:
        pass
    else:
        raise AssertionError("missing path should raise StorageError")


if __name__ == "__main__":
    _main()
