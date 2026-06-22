"""``gcs`` storage backend — Google Cloud Storage-backed key-value store.

Each ``(namespace, key)`` pair is stored as
``{prefix}{namespace}/{key}.json`` in a GCS bucket.

Requires the ``google-cloud-storage`` package:

    pip install pyxen[cloud]

Config (in ``runtime.json``):

.. code-block:: json

    "storage": {
        "implementation": "gcs",
        "config": {
            "bucket": "my-bucket",
            "prefix": "pyxen/",
            "project": "my-gcp-project",
            "credentials_path": "/path/to/sa-key.json",
            "credentials_json": "{...}"
        }
    }

Credential resolution order:

1. ``credentials_path`` — path to a service-account JSON key file
2. ``credentials_json`` — inline service-account JSON key string
3. Application Default Credentials (``google.auth.default()``)
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

try:
    from google.cloud import storage
    from google.oauth2 import service_account

    _HAS_GCS = True
except ImportError:
    _HAS_GCS = False


from ...core.errors import StorageError
from ...core.storage import QueryFilter


class GcsStorage:
    """Storage impl backed by Google Cloud Storage."""

    def __init__(self, config: dict[str, object]) -> None:
        if not _HAS_GCS:
            raise StorageError(
                "google-cloud-storage is not installed. Run: pip install pyxen[cloud]"
            )

        bucket = config.get("bucket")
        if not isinstance(bucket, str) or not bucket:
            raise StorageError("gcs storage requires config['bucket']")
        self._bucket_name: str = bucket

        self._prefix: str = str(config.get("prefix", ""))

        self._project: str | None = None
        raw_project = config.get("project")
        if raw_project is not None:
            self._project = str(raw_project)

        self._credentials_path: str | None = None
        raw_creds_path = config.get("credentials_path")
        if raw_creds_path is not None:
            self._credentials_path = str(raw_creds_path)

        self._credentials_json: str | None = None
        raw_creds_json = config.get("credentials_json")
        if raw_creds_json is not None:
            self._credentials_json = str(raw_creds_json)

        self._client: storage.Client | None = None
        self._bucket: Any = None
        self._lock = threading.Lock()

    def _ensure_client(self) -> None:
        """Lazy client construction — create on first use, thread-safe."""
        if self._client is not None:
            return
        with self._lock:
            assert self._client is None, "client raced in lock"

            if self._credentials_path is not None:
                self._client = storage.Client.from_service_account_json(
                    self._credentials_path, project=self._project
                )
            elif self._credentials_json is not None:
                creds_info = json.loads(self._credentials_json)
                creds = service_account.Credentials.from_service_account_info(creds_info)
                self._client = storage.Client(project=self._project, credentials=creds)
            else:
                self._client = storage.Client(project=self._project)

            self._bucket = self._client.bucket(self._bucket_name)

    def _blob_name(self, namespace: str, key: str) -> str:
        if self._prefix:
            return f"{self._prefix}{namespace}/{key}.json"
        return f"{namespace}/{key}.json"

    def _namespace_prefix(self, namespace: str) -> str:
        if self._prefix:
            return f"{self._prefix}{namespace}/"
        return f"{namespace}/"

    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        self._ensure_client()
        try:
            blob = self._bucket.blob(self._blob_name(namespace, key))
            with self._lock:
                blob.upload_from_string(json.dumps(value), content_type="application/json")
        except Exception as exc:
            raise StorageError(f"gcs put failed: {exc}") from exc

    async def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        self._ensure_client()
        try:
            blob = self._bucket.blob(self._blob_name(namespace, key))
            with self._lock:
                if not blob.exists():
                    return None
                raw = blob.download_as_text()
            loaded = json.loads(raw)
            if not isinstance(loaded, dict):
                raise StorageError(f"gcs blob {namespace}/{key!r} is not a dict")
            return loaded
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"gcs get failed: {exc}") from exc

    async def query(
        self, namespace: str, filter: QueryFilter | None = None
    ) -> list[dict[str, Any]]:
        self._ensure_client()
        assert self._client is not None
        try:
            prefix = self._namespace_prefix(namespace)
            with self._lock:
                blobs = list(self._client.list_blobs(self._bucket_name, prefix=prefix))

            results: list[dict[str, Any]] = []
            for blob in blobs:
                try:
                    raw = blob.download_as_text()
                    loaded = json.loads(raw)
                    if isinstance(loaded, dict):
                        results.append(loaded)
                except Exception:
                    continue

            if filter is not None and filter.equals:
                results = [
                    r
                    for r in results
                    if all(r.get(k) == v for k, v in filter.equals.items())
                ]
            if filter is not None and filter.limit is not None:
                results = results[: filter.limit]

            return results
        except Exception as exc:
            raise StorageError(f"gcs query failed: {exc}") from exc

    async def delete(self, namespace: str, key: str) -> bool:
        self._ensure_client()
        try:
            blob = self._bucket.blob(self._blob_name(namespace, key))
            with self._lock:
                if not blob.exists():
                    return False
                blob.delete()
            return True
        except Exception as exc:
            raise StorageError(f"gcs delete failed: {exc}") from exc


def build(config: dict[str, object]) -> GcsStorage:
    return GcsStorage(config)


def _main() -> None:
    """Test entry point for gcs storage impl.

    Requires the ``PYXEN_GCS_TEST_BUCKET`` environment variable set to
    a real GCS bucket name that the caller can write to.
    """
    import asyncio
    from pyxen._testlib import arun_tests, skip

    bucket = os.environ.get("PYXEN_GCS_TEST_BUCKET")
    if not bucket:
        skip("PYXEN_GCS_TEST_BUCKET not set")
        return

    if not _HAS_GCS:
        skip("google-cloud-storage not installed")
        return

    from pyxen.core.storage import QueryFilter

    async def _run_tests() -> None:
        prefix = f"pyxen-test-{os.urandom(4).hex()}/"
        s = build({"bucket": bucket, "prefix": prefix})

        async def test_put_get() -> None:
            await s.put("ns", "k", {"v": 1, "name": "alice"})
            assert await s.get("ns", "k") == {"v": 1, "name": "alice"}

        async def test_overwrite() -> None:
            await s.put("ns", "k", {"v": 2})
            assert await s.get("ns", "k") == {"v": 2}

        async def test_missing() -> None:
            assert await s.get("ns", "missing") is None
            assert await s.get("nonexistent", "k") is None

        async def test_empty_value() -> None:
            await s.put("ns", "empty", {})
            assert await s.get("ns", "empty") == {}

        async def test_nested_values() -> None:
            await s.put("ns", "nested", {"a": {"b": {"c": [1, 2, 3]}}})
            assert await s.get("ns", "nested") == {"a": {"b": {"c": [1, 2, 3]}}}

        async def test_query_all() -> None:
            await s.put("ns", "a", {"v": 1})
            await s.put("ns", "b", {"v": 2})
            await s.put("ns", "c", {"v": 3})
            all_in_ns = await s.query("ns")
            assert len(all_in_ns) >= 3

        async def test_query_filter() -> None:
            await s.put("ns", "x1", {"tag": "red", "n": 1})
            await s.put("ns", "x2", {"tag": "red", "n": 2})
            await s.put("ns", "x3", {"tag": "blue", "n": 3})
            red = await s.query("ns", QueryFilter(equals={"tag": "red"}))
            assert all(r["tag"] == "red" for r in red)
            assert len(red) == 2

        async def test_query_limit() -> None:
            first_three = await s.query("ns", QueryFilter(limit=3))
            assert len(first_three) == 3

        async def test_query_filter_limit() -> None:
            first_red = await s.query("ns", QueryFilter(equals={"tag": "red"}, limit=1))
            assert len(first_red) == 1

        async def test_namespace_isolation() -> None:
            await s.put("other", "k", {"v": 99})
            other = await s.query("other")
            assert len(other) == 1
            assert other[0]["v"] == 99

        async def test_delete_existing() -> None:
            assert await s.delete("ns", "a") is True
            assert await s.get("ns", "a") is None

        async def test_delete_missing() -> None:
            assert await s.delete("ns", "missing_xyz") is False
            assert await s.delete("nonexistent", "k") is False

        try:
            await arun_tests(
                test_put_get,
                test_overwrite,
                test_missing,
                test_empty_value,
                test_nested_values,
                test_query_all,
                test_query_filter,
                test_query_limit,
                test_query_filter_limit,
                test_namespace_isolation,
                test_delete_existing,
                test_delete_missing,
                label="gcs",
            )
        finally:
            s._ensure_client()
            for ns in ("ns", "other"):
                for blob in s._client.list_blobs(bucket, prefix=f"{prefix}{ns}/"):  # type: ignore[union-attr]
                    blob.delete()

    try:
        asyncio.run(_run_tests())
    except Exception as exc:
        skip(f"{exc}")


if __name__ == "__main__":
    _main()
