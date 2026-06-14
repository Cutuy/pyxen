"""``dotenv`` secrets impl — reads from a ``.env`` file.

For dev and tests. Production should use ``keychain`` (local) or the
``openai_env_injection`` impl (cloud, which wraps the OpenAI Agents SDK
Manifest.environment helper).
"""

from __future__ import annotations

import os
from pathlib import Path

from ...core.errors import SecretsError


class DotEnvSecrets:
    """Read-only secrets backed by a ``.env`` file."""

    def __init__(self, config: dict[str, object]) -> None:
        path_str = config.get("path")
        if not isinstance(path_str, str):
            raise SecretsError("dotenv secrets impl requires config['path']")
        self._path = Path(path_str)
        self._values: dict[str, str] = self._parse(self._path)

    @staticmethod
    def _parse(path: Path) -> dict[str, str]:
        if not path.is_file():
            return {}
        values: dict[str, str] = {}
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            values[key] = value
        return values

    async def get(self, name: str) -> str:
        if name in self._values:
            return self._values[name]
        env_value = os.environ.get(name)
        if env_value is not None:
            return env_value
        raise SecretsError(f"secret {name!r} not found in {self._path} or environment")

    async def set(self, name: str, value: str) -> None:
        # We don't write back to the file; the dotenv impl is read-only.
        # This matches the contract of a typical .env file workflow.
        self._values[name] = value


def build(config: dict[str, object]) -> DotEnvSecrets:
    return DotEnvSecrets(config)


def _main() -> None:
    """Test entry point for dotenv secrets impl."""
    import asyncio
    import tempfile
    from pathlib import Path

    from pyxen.core import SecretsError

    async def go() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text(
                "FOO=bar\n"
                "# this is a comment\n"
                "\n"
                "BAZ=qux\n"
                'QUOTED="hello world"\n'
                "SINGLE='single quoted'\n"
            )
            s = build({"path": str(env)})

            # Basic key=value
            assert await s.get("FOO") == "bar"
            # Skip blank lines and comments
            assert await s.get("BAZ") == "qux"
            # Strip surrounding double quotes
            assert await s.get("QUOTED") == "hello world"
            # Strip surrounding single quotes
            assert await s.get("SINGLE") == "single quoted"

            # Missing secret raises SecretsError
            try:
                await s.get("NOPE")
            except SecretsError as e:
                assert "NOPE" in str(e)
            else:
                raise AssertionError("missing secret should raise SecretsError")

            # set updates in-memory dict
            await s.set("NEW", "value")
            assert await s.get("NEW") == "value"

        # Falls back to env vars if not in file
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("")  # empty file
            s = build({"path": str(env)})
            import os
            os.environ["PYXEN_TEST_FALLBACK"] = "from-env"
            try:
                assert await s.get("PYXEN_TEST_FALLBACK") == "from-env"
            finally:
                os.environ.pop("PYXEN_TEST_FALLBACK", None)

        # Missing path config raises
        try:
            build({})
        except SecretsError:
            pass
        else:
            raise AssertionError("missing path should raise SecretsError")

        # Nonexistent file is OK (no secrets)
        with tempfile.TemporaryDirectory() as tmp:
            s = build({"path": str(Path(tmp) / "nope.env")})
            try:
                await s.get("X")
            except SecretsError:
                pass
            else:
                raise AssertionError("get on empty impl should raise SecretsError")

    asyncio.run(go())


if __name__ == "__main__":
    _main()
