"""``local_file`` secrets backend — secrets from a local JSON file.

Each key in the file is a secret name. Nested JSON objects are returned as-is.

Config (in ``runtime.json``):

.. code-block:: json

    "secrets": {
        "implementation": "local_file",
        "config": {
            "path": "./secrets.json"
        }
    }

File format (``secrets.json``):

.. code-block:: json

    {
        "openai-api-key": "sk-...",
        "github-token": "ghp_...",
        "databases": {
            "host": "localhost",
            "port": 5432
        }
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LocalFileSecrets:
    """Secrets impl that reads from a local JSON file."""

    def __init__(self, config: dict[str, object]) -> None:
        self._path = Path(str(config.get("path", "secrets.json"))).resolve()
        self._secrets: dict[str, Any] = {}

    async def get(self, name: str) -> str | dict[str, Any] | None:
        """Return a secret by name. Nested dicts are returned whole."""
        if not self._secrets:
            await self._reload()
        return self._secrets.get(name)

    async def list(self) -> list[str]:
        """Return all secret names."""
        if not self._secrets:
            await self._reload()
        return list(self._secrets.keys())

    async def _reload(self) -> None:
        if not self._path.exists():
            self._secrets = {}
            return
        try:
            raw = self._path.read_text(encoding="utf-8")
            self._secrets = json.loads(raw)
        except (json.JSONDecodeError, OSError):
            self._secrets = {}


def build(config: dict[str, object]) -> LocalFileSecrets:
    return LocalFileSecrets(config)


def _main() -> None:
    from pyxen._testlib import ok
    """Test entry point."""
    import asyncio
    import tempfile

    async def go() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "secrets.json"
            p.write_text(json.dumps({
                "api-key": "sk-test-123",
                "github": "ghp_abc",
                "db": {"host": "db.local", "port": 5432},
            }))

            s = LocalFileSecrets({"path": str(p)})

            # Get string
            v = await s.get("api-key")
            assert v == "sk-test-123", v

            # Get nested
            v2 = await s.get("db")
            assert v2 == {"host": "db.local", "port": 5432}, v2

            # Missing key
            v3 = await s.get("nonexistent")
            assert v3 is None

            # List
            names = await s.list()
            assert sorted(names) == ["api-key", "db", "github"], names

        # Missing file = empty
        s2 = LocalFileSecrets({"path": "/tmp/nonexistent-secrets.json"})
        v4 = await s2.get("anything")
        assert v4 is None

        ok("local_file")

    asyncio.run(go())


if __name__ == "__main__":
    _main()
