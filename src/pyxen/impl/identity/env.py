"""``env`` identity impl — reads identity from environment variables.

Useful for dev / CI. The current identity is whatever ``PYXEN_IDENTITY_ID``
is set to; ``for_target`` reads ``PYXEN_CRED_<TARGET_UPPER>``.
"""

from __future__ import annotations

import os

from ...core.identity import Credential, Identity


class EnvIdentity:
    """Identity impl backed by environment variables."""

    def __init__(self, config: dict[str, object]) -> None:
        self._id = str(config.get("id_env", "PYXEN_IDENTITY_ID"))
        self._name_env = str(config.get("name_env", "PYXEN_IDENTITY_NAME"))
        self._cred_prefix = str(config.get("cred_prefix", "PYXEN_CRED_"))

    async def current(self) -> Identity:
        return Identity(
            id=os.environ.get(self._id, "anonymous"),
            name=os.environ.get(self._name_env) or None,
            source="env",
        )

    async def for_target(self, target: str) -> Credential:
        env_name = f"{self._cred_prefix}{target.upper().replace('.', '_').replace('-', '_')}"
        token = os.environ.get(env_name)
        if token is None:
            raise KeyError(f"no credential for target {target!r} (env: {env_name})")
        return Credential(
            token=token,
            target=target,
            expires_at=None,
        )


def build(config: dict[str, object]) -> EnvIdentity:
    return EnvIdentity(config)


def _main() -> None:
    """Test entry point for env identity impl."""
    import os

    # Save original env state for restore on failure or completion
    _saved = {}
    for _k in ("PYXEN_IDENTITY_ID", "PYXEN_IDENTITY_NAME", "MYAPP_USER", "MYAPP_USER_NAME",
               "PYXEN_CRED_GITHUB_COM", "PYXEN_CRED_API_NOTHING"):
        _saved[_k] = os.environ.get(_k)
    try:
        # Default: PYXEN_IDENTITY_ID unset -> "anonymous"
        os.environ.pop("PYXEN_IDENTITY_ID", None)
        os.environ.pop("PYXEN_IDENTITY_NAME", None)
        impl = EnvIdentity({})
        import asyncio
        me = asyncio.run(impl.current())
        assert me.id == "anonymous"
        assert me.name is None
        assert me.source == "env"

        # With env vars set
        os.environ["PYXEN_IDENTITY_ID"] = "alice@x.com"
        os.environ["PYXEN_IDENTITY_NAME"] = "Alice"
        me2 = asyncio.run(impl.current())
        assert me2.id == "alice@x.com"
        assert me2.name == "Alice"

        # Custom env var names via config
        os.environ["MYAPP_USER"] = "bob"
        os.environ["MYAPP_USER_NAME"] = "Bob"
        custom = EnvIdentity({"id_env": "MYAPP_USER", "name_env": "MYAPP_USER_NAME"})
        me3 = asyncio.run(custom.current())
        assert me3.id == "bob"
        assert me3.name == "Bob"

        # for_target reads PYXEN_CRED_<UPPER_TARGET>
        os.environ["PYXEN_CRED_GITHUB_COM"] = "ghp_xxx"
        cred = asyncio.run(impl.for_target("github.com"))
        assert cred.token == "ghp_xxx"
        assert cred.target == "github.com"

        # for_target with dots and dashes in target name
        os.environ["PYXEN_CRED_API_OPENAI_COM"] = "sk-xxx"
        cred2 = asyncio.run(impl.for_target("api.openai.com"))
        assert cred2.token == "sk-xxx"
        os.environ["PYXEN_CRED_MY_SERVICE_COM"] = "token-xxx"
        cred3 = asyncio.run(impl.for_target("my-service.com"))
        assert cred3.token == "token-xxx"

        # Missing cred raises KeyError
        os.environ.pop("PYXEN_CRED_API_NOTHING", None)
        try:
            asyncio.run(impl.for_target("api.nothing"))
        except KeyError as e:
            assert "api.nothing" in str(e)
        else:
            raise AssertionError("missing cred should raise KeyError")

        # Custom cred prefix
        custom_cred = EnvIdentity({"cred_prefix": "MY_CRED_"})
        os.environ["MY_CRED_EXAMPLE_COM"] = "my-token"
        cred4 = asyncio.run(custom_cred.for_target("example.com"))
        assert cred4.token == "my-token"
        os.environ.pop("MY_CRED_EXAMPLE_COM", None)
    finally:
        # Restore original env state
        for _k, _v in _saved.items():
            if _v is None:
                os.environ.pop(_k, None)
            else:
                os.environ[_k] = _v


if __name__ == "__main__":
    _main()
