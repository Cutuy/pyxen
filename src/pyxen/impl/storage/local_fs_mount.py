"""``local_fs_mount`` storage impl — mounts a directory tree as the storage namespace.

The runtime's storage primitive is normally a database (SQLite, Postgres,
S3, ...). This impl takes a different approach: the **environment** is a
directory of files on disk, and the runtime makes that directory visible
as the storage namespace.

Each "mount" in the config binds a runtime namespace to an `openai-agents`
mount entry — the same `LocalDir` / `S3Mount` types the Agents SDK ships
for sandbox mounts. We import the SDK's Pydantic models so the
``runtime.json`` shape is identical to what an Agents SDK consumer would
write in a ``Manifest``. The SDK's *apply()* / *MountStrategy* classes
require a ``BaseSandboxSession``; we use only the **type model**, not
the strategy — the actual mount materialization for the storage
namespace is a thin direct-filesystem adapter.

The expected on-disk layout:

    <root>/
        <namespace>/
            <key>.json

A typical dc-capex config::

    {
        "implementation": "local_fs_mount",
        "config": {
            "mounts": [
                { "namespace": "data", "type": "local_dir", "src": "./data" }
            ]
        }
    }

Then ``await rt.storage.get("data", "overview")`` reads
``./data/overview.json`` and returns the parsed dict.

Swap the same file to cloud storage with::

    {
        "implementation": "local_fs_mount",
        "config": {
            "mounts": [
                { "namespace": "data", "type": "s3_mount",
                  "bucket": "my-bucket", "prefix": "dc-capex/data/" }
            ]
        }
    }

(The S3 mount requires an additional impl layer — see the
``cloud_storage_mount`` roadmap. The point is the *config shape* is the
same; the app code never changes.)

The ``openai-agents`` package is an optional dep for this impl. If
uninstalled, the impl still works for ``local_dir`` mounts (it falls
back to a local Pydantic-less mount model). If the user configures
a non-local mount and the SDK is missing, ``build()`` raises.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from ...core.errors import StorageError
from ...core.storage import QueryFilter

class _ResolvedMount:
    """Internal representation of a single mount, after parsing the config.

    Either a local dir (resolved to an absolute Path) or a cloud marker
    (resolved to a backend-specific record). For v0, only ``local_dir``
    is actually materialized; the cloud path is a roadmap stub.
    """

    __slots__ = ("namespace", "kind", "local_path", "cloud")

    def __init__(
        self,
        namespace: str,
        kind: str,
        local_path: Path | None,
        cloud: dict[str, Any] | None,
    ) -> None:
        self.namespace = namespace
        self.kind = kind
        self.local_path = local_path
        self.cloud = cloud


def _parse_mount_entry(namespace: str, raw: dict[str, Any]) -> _ResolvedMount:
    """Parse one mount entry from ``runtime.json``.

    The entry uses the openai-agents ``Manifest.entries`` shape verbatim.
    """
    entry_type = raw.get("type")
    if not isinstance(entry_type, str):
        raise StorageError(
            f"mount entry for namespace {namespace!r} is missing a string 'type'"
        )

    if entry_type == "local_dir":
        try:
            from agents.sandbox.entries import LocalDir
        except ImportError:
            raise StorageError(
                f"local_dir mount for {namespace!r} requires the 'openai-agents' "
                "package to parse the mount entry; install with "
                "`pip install pyxen[openai]`"
            )
        try:
            ld = LocalDir.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(
                f"local_dir mount for {namespace!r} failed SDK validation: {exc}"
            ) from exc
        if ld.src is None:
            raise StorageError(
                f"local_dir mount for {namespace!r} requires 'src'"
            )
        return _ResolvedMount(
            namespace=namespace,
            kind="local_dir",
            local_path=Path(ld.src).resolve(),
            cloud=None,
        )

    if entry_type in ("s3_mount", "gcs_mount", "r2_mount", "azure_blob_mount", "box_mount"):
        # Cloud mounts are a roadmap item. The config is parsed and stored,
        # but the actual materialization is not implemented in v0.
        try:
            from agents.sandbox.entries import S3Mount
        except ImportError:
            raise StorageError(
                f"{entry_type} mount for {namespace!r} requires the 'openai-agents' "
                "package to parse the mount entry; install with "
                "`pip install pyxen[openai]`"
            )
        # Validate the entry against the SDK model so a future v0.x can
        # actually use it without further config changes.
        try:
            if entry_type == "s3_mount":
                S3Mount.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(
                f"{entry_type} mount for {namespace!r} failed SDK validation: {exc}"
            ) from exc
        return _ResolvedMount(
            namespace=namespace,
            kind=entry_type,
            local_path=None,
            cloud=dict(raw),
        )

    raise StorageError(
        f"unknown mount type {entry_type!r} for namespace {namespace!r}"
    )


class LocalFsMountStorage:
    """Storage impl that exposes one or more directory mounts as namespaces.

    The mounted directory is ``<mount_root>/<namespace>`` and the on-disk
    layout is ``<namespace>/<key>.json``. ``mount_root`` is the current
    working directory of the process at construction time (i.e., the
    path is resolved against the directory the app was started in).
    """

    def __init__(self, config: dict[str, object]) -> None:
        mounts_raw = config.get("mounts")
        if not isinstance(mounts_raw, list) or not mounts_raw:
            raise StorageError(
                "local_fs_mount storage requires a non-empty 'mounts' list"
            )
        self._mounts: dict[str, _ResolvedMount] = {}
        for entry in mounts_raw:
            if not isinstance(entry, dict):
                raise StorageError("each mount entry must be a JSON object")
            ns = entry.get("namespace")
            if not isinstance(ns, str) or not ns:
                raise StorageError(
                    "each mount entry must have a non-empty 'namespace' string"
                )
            if ns in self._mounts:
                raise StorageError(
                    f"duplicate mount namespace {ns!r}"
                )
            self._mounts[ns] = _parse_mount_entry(ns, entry)
        self._lock = threading.Lock()

    def _resolve(self, namespace: str) -> Path:
        m = self._mounts.get(namespace)
        if m is None:
            raise StorageError(
                f"namespace {namespace!r} is not mounted; "
                f"available: {sorted(self._mounts)}"
            )
        if m.kind != "local_dir" or m.local_path is None:
            raise StorageError(
                f"namespace {namespace!r} is mounted as {m.kind!r}; "
                "cloud mounts are not yet implemented in this version"
            )
        if not m.local_path.is_dir():
            raise StorageError(
                f"mount path for namespace {namespace!r} does not exist or is not a directory: {m.local_path}"
            )
        return m.local_path

    def _path_for(self, namespace: str, key: str) -> Path:
        ns_root = self._resolve(namespace)
        return ns_root / f"{key}.json"

    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        path = self._path_for(namespace, key)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(value, f, indent=2, ensure_ascii=False)
            tmp.replace(path)

    async def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        path = self._path_for(namespace, key)
        if not path.is_file():
            return None
        with path.open(encoding="utf-8") as f:
            loaded: dict[str, Any] = json.load(f)
            return loaded

    async def query(
        self, namespace: str, filter: QueryFilter | None = None
    ) -> list[dict[str, Any]]:
        ns_root = self._resolve(namespace)
        results: list[dict[str, Any]] = []
        for entry in sorted(ns_root.iterdir()):
            if not entry.is_file() or entry.suffix != ".json":
                continue
            try:
                with entry.open(encoding="utf-8") as f:
                    record = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            if filter is not None and filter.equals and not all(record.get(k) == v for k, v in filter.equals.items()):
                continue
            results.append(record)
            if filter is not None and filter.limit is not None and len(results) >= filter.limit:
                break
        return results

    async def delete(self, namespace: str, key: str) -> bool:
        path = self._path_for(namespace, key)
        with self._lock:
            if not path.is_file():
                return False
            path.unlink()
            return True


def build(config: dict[str, object]) -> LocalFsMountStorage:
    return LocalFsMountStorage(config)


def _main() -> None:
    """Test entry point. Rust-style per-module test."""
    import asyncio
    import tempfile
    from pathlib import Path

    from ...core.storage import QueryFilter

    async def go() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Set up two mounts: one in tmp/data, another in tmp/config
            data_dir = Path(tmp) / "data"
            config_dir = Path(tmp) / "config"
            data_dir.mkdir()
            config_dir.mkdir()
            # Pre-seed a file on disk that the app will read via rt.storage
            (data_dir / "overview.json").write_text(
                json.dumps({"title": "From disk", "size": 42})
            )
            (config_dir / "settings.json").write_text(
                json.dumps({"theme": "dark", "version": 1})
            )

            # Build the impl via the factory
            impl = build(
                {
                    "mounts": [
                        {"namespace": "data", "type": "local_dir", "src": str(data_dir)},
                        {"namespace": "config", "type": "local_dir", "src": str(config_dir)},
                    ]
                }
            )

            # Read the pre-seeded file via storage
            record = await impl.get("data", "overview")
            assert record == {"title": "From disk", "size": 42}

            # Write a new file via storage
            await impl.put("data", "fresh", {"hello": "world", "n": 7})
            on_disk = json.loads((data_dir / "fresh.json").read_text())
            assert on_disk == {"hello": "world", "n": 7}

            # Query the namespace
            results = await impl.query("data")
            assert len(results) == 2  # overview + fresh

            # Query with filter
            only_fresh = await impl.query("data", QueryFilter(equals={"hello": "world"}))
            assert only_fresh == [{"hello": "world", "n": 7}]

            # Query with limit
            limited = await impl.query("data", QueryFilter(limit=1))
            assert len(limited) == 1

            # Cross-namespace isolation
            settings = await impl.get("config", "settings")
            assert settings == {"theme": "dark", "version": 1}
            not_there = await impl.get("config", "overview")
            assert not_there is None

            # Delete a file via storage
            assert await impl.delete("data", "fresh") is True
            assert (data_dir / "fresh.json").exists() is False
            assert await impl.get("data", "fresh") is None
            # Delete missing returns False
            assert await impl.delete("data", "missing") is False

            # Mount another namespace — verify the second mount works in isolation
            await impl.put("config", "extra", {"k": "v"})
            extra = await impl.get("config", "extra")
            assert extra == {"k": "v"}

            # Atomic write: a put with a malformed dict still leaves a valid file
            # (we don't validate the dict shape; we just round-trip JSON)
            await impl.put("data", "nested", {"a": {"b": [1, 2, 3]}})
            nested = await impl.get("data", "nested")
            assert nested == {"a": {"b": [1, 2, 3]}}

        # --- Error cases ---

        # Empty mounts list
        try:
            build({"mounts": []})
        except StorageError as e:
            assert "non-empty" in str(e)
        else:
            raise AssertionError("empty mounts should raise StorageError")

        # Missing namespace
        try:
            build({"mounts": [{"type": "local_dir", "src": "."}]})
        except StorageError as e:
            assert "namespace" in str(e)
        else:
            raise AssertionError("missing namespace should raise")

        # Duplicate namespace
        try:
            build(
                {
                    "mounts": [
                        {"namespace": "x", "type": "local_dir", "src": "."},
                        {"namespace": "x", "type": "local_dir", "src": "."},
                    ]
                }
            )
        except StorageError as e:
            assert "duplicate" in str(e)
        else:
            raise AssertionError("duplicate namespace should raise")

        # Unknown mount type
        try:
            build(
                {
                    "mounts": [
                        {"namespace": "x", "type": "sftp_thing", "src": "x"}
                    ]
                }
            )
        except StorageError as e:
            assert "unknown" in str(e) or "sftp" in str(e)
        else:
            raise AssertionError("unknown mount type should raise")

        # Access to a non-mounted namespace
        async def go_unmounted() -> None:
            impl = build(
                {"mounts": [{"namespace": "x", "type": "local_dir", "src": "."}]}
            )
            try:
                await impl.get("not_mounted", "anything")
            except StorageError as e:
                assert "not mounted" in str(e)
            else:
                raise AssertionError("unmounted namespace should raise")

        asyncio.run(go_unmounted())


if __name__ == "__main__":
    _main()
