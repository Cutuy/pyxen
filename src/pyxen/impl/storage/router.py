"""``router`` storage impl — namespace-routed multi-backend storage.

The router exposes the same ``StorageImpl`` interface (``put``/``get``/
``query``/``delete``) but delegates each namespace to a different configured
back end. This lets a single application use SQLite for persistent data,
Redis for cache, and local filesystem for blobs — all from one ``rt.storage``
object.

Config (in ``runtime.json``):

.. code-block:: json

    {
        "storage": {
            "implementation": "router",
            "config": {
                "default": {
                    "implementation": "local_sqlite",
                    "config": { "path": "./data/default.db" }
                },
                "namespaces": {
                    "cache": {
                        "implementation": "redis",
                        "config": { "url": "redis://localhost:6379/0", "prefix": "app:cache:" }
                    },
                    "blobs": {
                        "implementation": "local_fs_mount",
                        "config": {
                            "mounts": [
                                { "namespace": "blobs", "type": "local_dir", "src": "./data/blobs" }
                            ]
                        }
                    }
                }
            }
        }
    }

Namespaces not listed in ``namespaces`` fall back to the ``default`` backend.
If no default is configured and the namespace has no explicit backend, the
call raises ``StorageError``.

Backward compatibility: single-backend configs (``local_sqlite``, ``inmemory``,
etc.) continue to work exactly as before. The router is an opt-in upgrade.
"""

from __future__ import annotations

import importlib
from typing import Any

from ...core.errors import StorageError
from ...core.storage import QueryFilter, StorageImpl


def _build_sub_backend(cfg: dict[str, Any]) -> StorageImpl:
    """Resolve and instantiate a sub-backend from a config dict.

    The config must have ``implementation`` (a module name under
    ``pyxen.impl.storage``) and optionally ``config`` (a dict of
    implementation-specific options). This mirrors the import/dynamic
    resolution that the ``Runtime`` class uses for top-level primitives.
    """
    impl_name = cfg.get("implementation")
    if not isinstance(impl_name, str) or not impl_name:
        raise StorageError(
            "sub-backend config requires a non-empty 'implementation' string"
        )
    impl_cfg = cfg.get("config", {})
    if not isinstance(impl_cfg, dict):
        raise StorageError("sub-backend 'config' must be a JSON object")

    module_name = f"pyxen.impl.storage.{impl_name}"
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise StorageError(
            f"sub-backend module '{module_name}' not found: {exc}"
        ) from exc

    build = getattr(module, "build", None)
    if build is None:
        raise StorageError(
            f"sub-backend module '{module_name}' is missing a 'build' function"
        )
    result = build(impl_cfg)
    # If build is async (unlikely for storage backends but future-proof)
    if hasattr(result, "__await__"):
        import asyncio
        result = asyncio.run(result)
    # Duck-type check: verify the result has the protocol methods.
    # (Cannot use isinstance() against a plain Protocol without @runtime_checkable.)
    for method in ("put", "get", "query", "delete"):
        if not callable(getattr(result, method, None)):
            raise StorageError(
                f"sub-backend '{impl_name}' returned an object missing "
                f"required method '{method}'"
            )
    return result  # type: ignore[no-any-return]


class RouterStorage:
    """Storage impl that routes namespace operations to sub-backends.

    Each namespace is mapped to a separate backend instance. A default
    backend handles namespaces without an explicit mapping.
    """

    def __init__(self, config: dict[str, object]) -> None:
        self._backends: dict[str, StorageImpl] = {}
        self._default_backend: StorageImpl | None = None

        # Parse the optional default backend
        default_raw = config.get("default")
        if default_raw is not None:
            if not isinstance(default_raw, dict):
                raise StorageError("router 'default' must be a JSON object")
            self._default_backend = _build_sub_backend(default_raw)

        # Parse namespace backends
        namespaces_raw = config.get("namespaces")
        if namespaces_raw is not None:
            if not isinstance(namespaces_raw, dict):
                raise StorageError("router 'namespaces' must be a JSON object")
            for ns, backend_cfg in namespaces_raw.items():
                if not isinstance(ns, str) or not ns:
                    raise StorageError("each namespace key must be a non-empty string")
                if not isinstance(backend_cfg, dict):
                    raise StorageError(
                        f"namespace {ns!r}: backend config must be a JSON object"
                    )
                if ns in self._backends:
                    raise StorageError(f"duplicate namespace {ns!r}")
                self._backends[ns] = _build_sub_backend(backend_cfg)

        # At least one backend must be configured (default or namespaces)
        if not self._backends and self._default_backend is None:
            raise StorageError(
                "router storage requires at least one backend "
                "(either 'default' or non-empty 'namespaces')"
            )

    def _resolve(self, namespace: str) -> StorageImpl:
        """Return the backend for *namespace*, checking explicit mapping
        before falling back to the default."""
        backend = self._backends.get(namespace)
        if backend is not None:
            return backend
        if self._default_backend is not None:
            return self._default_backend
        raise StorageError(
            f"namespace {namespace!r} has no explicit backend and "
            "no default backend is configured; "
            f"available namespaces: {sorted(self._backends)}"
        )

    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        await self._resolve(namespace).put(namespace, key, value)

    async def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        return await self._resolve(namespace).get(namespace, key)

    async def query(
        self, namespace: str, filter: QueryFilter | None = None
    ) -> list[dict[str, Any]]:
        return await self._resolve(namespace).query(namespace, filter)

    async def delete(self, namespace: str, key: str) -> bool:
        return await self._resolve(namespace).delete(namespace, key)


def build(config: dict[str, object]) -> RouterStorage:
    return RouterStorage(config)


def _main() -> None:
    """Test entry point for router storage impl."""
    import asyncio
    import tempfile
    from pathlib import Path

    async def go() -> None:
        # --- Config with default + namespaces ---
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            (data_dir / "greeting.json").write_text(
                '{"text": "Hello from fs", "n": 42}'
            )

            cfg: dict[str, object] = {
                "default": {
                    "implementation": "inmemory",
                    "config": {},
                },
                "namespaces": {
                    "fs": {
                        "implementation": "local_fs_mount",
                        "config": {
                            "mounts": [
                                {"namespace": "fs", "type": "local_dir", "src": str(data_dir)}
                            ]
                        },
                    },
                },
            }
            router = build(cfg)

            # Default backend: inmemory
            await router.put("any_ns", "a", {"x": 1})
            got = await router.get("any_ns", "a")
            assert got == {"x": 1}

            # Named backend: fs mount
            fs_got = await router.get("fs", "greeting")
            assert fs_got == {"text": "Hello from fs", "n": 42}

            # Write via router to fs namespace
            await router.put("fs", "written", {"via": "router"})
            written = await router.get("fs", "written")
            assert written == {"via": "router"}

            # File actually exists on disk
            assert (data_dir / "written.json").is_file()

            # Namespace isolation
            assert await router.get("any_ns", "greeting") is None  # default backend
            assert await router.get("fs", "a") is None  # fs backend

        # --- Config with only namespaces (no default) ---
        with tempfile.TemporaryDirectory() as tmp:
            a_dir = Path(tmp) / "a"
            b_dir = Path(tmp) / "b"
            a_dir.mkdir()
            b_dir.mkdir()

            cfg2: dict[str, object] = {
                "namespaces": {
                    "alpha": {
                        "implementation": "local_fs_mount",
                        "config": {
                            "mounts": [
                                {"namespace": "alpha", "type": "local_dir", "src": str(a_dir)}
                            ]
                        },
                    },
                    "beta": {
                        "implementation": "local_fs_mount",
                        "config": {
                            "mounts": [
                                {"namespace": "beta", "type": "local_dir", "src": str(b_dir)}
                            ]
                        },
                    },
                },
            }
            router2 = build(cfg2)

            await router2.put("alpha", "k1", {"val": "a-val"})
            await router2.put("beta", "k1", {"val": "b-val"})
            assert (await router2.get("alpha", "k1")) == {"val": "a-val"}
            assert (await router2.get("beta", "k1")) == {"val": "b-val"}

            # Unmapped namespace with no default raises
            try:
                await router2.get("no_mapping", "anything")
            except StorageError as e:
                assert "no explicit backend" in str(e)
            else:
                raise AssertionError("unmapped namespace should raise")

        # --- Query delegates correctly ---
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "q"
            d.mkdir()
            (d / "red.json").write_text('{"color": "red", "v": 1}')
            (d / "blue.json").write_text('{"color": "blue", "v": 2}')

            cfg3: dict[str, object] = {
                "namespaces": {
                    "colors": {
                        "implementation": "local_fs_mount",
                        "config": {
                            "mounts": [
                                {"namespace": "colors", "type": "local_dir", "src": str(d)}
                            ]
                        },
                    },
                },
            }
            router3 = build(cfg3)
            # Query does NOT pass the namespace to the sub-backend as-is
            # because local_fs_mount.query("colors", ...) resolves the mount
            reds = await router3.query("colors", QueryFilter(equals={"color": "red"}))
            assert len(reds) == 1
            assert reds[0]["color"] == "red"

            # Delete via router
            assert await router3.delete("colors", "red") is True
            assert (d / "red.json").exists() is False
            assert await router3.delete("colors", "red") is False  # already gone

        # --- Error: empty config ---
        try:
            build({})
        except StorageError as e:
            assert "at least one backend" in str(e)
        else:
            raise AssertionError("empty config should raise")

        # --- Error: bad sub-backend name ---
        try:
            build({
                "namespaces": {
                    "x": {"implementation": "not_a_real_impl", "config": {}},
                },
            })
        except StorageError as e:
            assert "not found" in str(e) or "not_a_real_impl" in str(e)
        else:
            raise AssertionError("bad impl name should raise")

        # --- Error: missing implementation key ---
        try:
            build({
                "namespaces": {
                    "x": {"config": {}},
                },
            })
        except StorageError as e:
            assert "implementation" in str(e)
        else:
            raise AssertionError("missing implementation should raise")

        # (Duplicate namespace check is in the code path but can't be
        # triggered from Python dict literal — duplicate keys are silently
        # overwritten at the dict level. The check exists as a defense
        # against non-literal config loading.)

        # --- Error: null/empty namespace key ---
        try:
            build({
                "namespaces": {
                    "": {"implementation": "inmemory", "config": {}},
                },
            })
        except StorageError as e:
            assert "non-empty" in str(e)
        else:
            raise AssertionError("empty namespace should raise")

        # --- Error: default is not a dict ---
        try:
            build({"default": "not a dict"})
        except StorageError as e:
            assert "must be a JSON object" in str(e)
        else:
            raise AssertionError("non-dict default should raise")

        # --- Success with only default (no namespaces) ---
        cfg_only_default: dict[str, object] = {
            "default": {"implementation": "inmemory", "config": {}},
        }
        router_only_default = build(cfg_only_default)
        await router_only_default.put("anything", "k", {"v": 1})
        assert await router_only_default.get("anything", "k") == {"v": 1}

    asyncio.run(go())


if __name__ == "__main__":
    _main()
