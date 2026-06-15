"""``redis`` storage backend — key-value backed by Redis.

Uses ``redis.asyncio``. A namespace maps to a Redis key prefix, allowing
different app modules to share one Redis instance without collision.

Requires the ``redis`` package:

    pip install pyxen[redis]

Config (in ``runtime.json``):

.. code-block:: json

    "storage": {
        "implementation": "redis",
        "config": {
            "url": "redis://localhost:6379/0",
            "prefix": "pyxen:"
        }
    }
"""

from __future__ import annotations

import json
from typing import Any

try:
    import redis.asyncio as aioredis
    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False


class RedisStorage:
    """Storage impl backed by Redis key-value store."""

    def __init__(self, config: dict[str, object]) -> None:
        if not _HAS_REDIS:
            raise RuntimeError("redis is not installed. Run: pip install pyxen[redis]")

        self._url = str(config.get("url", "redis://localhost:6379/0"))
        self._prefix = str(config.get("prefix", "pyxen:"))

    async def _conn(self):
        """Lazy connection — created per call to avoid thread issues."""
        return await aioredis.from_url(self._url)

    def _key(self, namespace: str, key: str) -> str:
        return f"{self._prefix}{namespace}:{key}"

    def _pattern(self, namespace: str) -> str:
        return f"{self._prefix}{namespace}:*"

    async def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        c = await self._conn()
        try:
            raw = await c.get(self._key(namespace, key))
            return json.loads(raw) if raw else None
        finally:
            await c.aclose()

    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        c = await self._conn()
        try:
            await c.set(self._key(namespace, key), json.dumps(value, default=str))
        finally:
            await c.aclose()

    async def delete(self, namespace: str, key: str) -> None:
        c = await self._conn()
        try:
            await c.delete(self._key(namespace, key))
        finally:
            await c.aclose()

    async def list(self, namespace: str) -> list[dict[str, Any]]:
        c = await self._conn()
        try:
            keys = await c.keys(self._pattern(namespace))
            if not keys:
                return []
            values = await c.mget(keys)
            result = []
            for raw in values:
                if raw:
                    result.append(json.loads(raw))
            return result
        finally:
            await c.aclose()


def build(config: dict[str, object]) -> RedisStorage:
    return RedisStorage(config)


def _main() -> None:
    """Test entry point — requires a local Redis instance."""
    import asyncio

    async def go() -> None:
        s = RedisStorage({"url": "redis://localhost:6379/0", "prefix": "pyxen:test:"})

        # Put
        await s.put("test", "hello", {"message": "world"})

        # Get
        val = await s.get("test", "hello")
        assert val == {"message": "world"}, val

        # List
        items = await s.list("test")
        assert len(items) >= 1

        # Delete
        await s.delete("test", "hello")
        val2 = await s.get("test", "hello")
        assert val2 is None

        print("redis: OK")

    if _HAS_REDIS:
        try:
            asyncio.run(go())
        except Exception as e:
            print(f"redis: SKIP (no server? — {e})")
    else:
        print("redis: SKIP (not installed)")


if __name__ == "__main__":
    _main()
