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
    import os
    import tempfile
    from pathlib import Path

    from pyxen._testlib import arun_tests
    from pyxen.core import SecretsError

    async def _run_tests() -> None:
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

            try:
                async def test_basic_key_value() -> None:
                    assert await s.get("FOO") == "bar"
                    assert await s.get("BAZ") == "qux"
                    assert await s.get("QUOTED") == "hello world"
                    assert await s.get("SINGLE") == "single quoted"

                async def test_empty_value() -> None:
                    env2 = Path(tmp) / "empty.env"
                    env2.write_text("KEY=\n")
                    s_empty = build({"path": str(env2)})
                    assert await s_empty.get("KEY") == ""

                async def test_spaces_value() -> None:
                    env3 = Path(tmp) / "spaces.env"
                    env3.write_text("KEY=   \n")
                    s_spaces = build({"path": str(env3)})
                    assert await s_spaces.get("KEY") == ""

                async def test_missing_secret_raises() -> None:
                    try:
                        await s.get("NOPE")
                    except SecretsError as e:
                        assert "NOPE" in str(e)
                    else:
                        raise AssertionError("missing secret should raise SecretsError")

                async def test_set_updates_in_memory() -> None:
                    await s.set("NEW", "value")
                    assert await s.get("NEW") == "value"

                async def test_fallback_to_env_var() -> None:
                    with tempfile.TemporaryDirectory() as tmp2:
                        env_fb = Path(tmp2) / ".env"
                        env_fb.write_text("")
                        s2 = build({"path": str(env_fb)})
                        os.environ["PYXEN_TEST_FALLBACK"] = "from-env"
                        try:
                            assert await s2.get("PYXEN_TEST_FALLBACK") == "from-env"
                        finally:
                            os.environ.pop("PYXEN_TEST_FALLBACK", None)

                async def test_missing_path_config_raises() -> None:
                    try:
                        build({})
                    except SecretsError:
                        pass
                    else:
                        raise AssertionError("missing path should raise SecretsError")

                async def test_nonexistent_file_raises_on_get() -> None:
                    with tempfile.TemporaryDirectory() as tmp3:
                        s3 = build({"path": str(Path(tmp3) / "nope.env")})
                        try:
                            await s3.get("X")
                        except SecretsError:
                            pass
                        else:
                            raise AssertionError("get on empty impl should raise SecretsError")

                await arun_tests(
                    test_basic_key_value,
                    test_empty_value,
                    test_spaces_value,
                    test_missing_secret_raises,
                    test_set_updates_in_memory,
                    test_fallback_to_env_var,
                    test_missing_path_config_raises,
                    test_nonexistent_file_raises_on_get,
                )
            finally:
                pass

    asyncio.run(_run_tests())


if __name__ == "__main__":
    _main()
