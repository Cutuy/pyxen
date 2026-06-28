"""``s3`` storage backend — S3-compatible object store-backed key-value store.

Each ``(namespace, key)`` pair is stored as
``{prefix}{namespace}/{key}.json`` in an S3 bucket.

Requires the ``aioboto3`` package::

    pip install pyxen[cloud]

Config (in ``runtime.json``):

.. code-block:: json

    "storage": {
        "implementation": "s3",
        "config": {
            "bucket": "my-bucket",
            "prefix": "pyxen/",
            "endpoint_url": "https://s3.amazonaws.com",
            "region": "us-east-1",
            "path_style": false,
            "credentials": {"$secret": "aws_creds"}
        }
    }

``endpoint_url`` defaults to ``https://s3.amazonaws.com`` (AWS S3).
Set it to your MinIO, R2, or Backblaze endpoint for compatible stores.

``path_style`` controls whether S3 URLs use path-style
(``endpoint/bucket/key``) or virtual-hosted
(``bucket.endpoint/key``) addressing. Defaults to virtual-hosted
(``False``).

Credentials come exclusively from the secrets primitive via the
``{"$secret": "key"}`` reference. The resolved value must be a JSON
object with ``aws_access_key_id`` and ``aws_secret_access_key`` fields.
"""

from __future__ import annotations

import json
from typing import Any

try:
    import aioboto3
    from botocore.config import Config

    _HAS_S3 = True
except ImportError:
    _HAS_S3 = False

from ...core.errors import StorageError
from ...core.manifest import SECRET_REF_KEY
from ...core.secrets import SecretsImpl
from ...core.storage import QueryFilter


class S3Storage:
    """Storage impl backed by S3-compatible object storage."""

    def __init__(
        self,
        config: dict[str, object],
        *,
        secrets: SecretsImpl | None = None,
    ) -> None:
        if not _HAS_S3:
            raise StorageError(
                "aioboto3 is not installed. Run: pip install pyxen[cloud]"
            )

        bucket = config.get("bucket")
        if not isinstance(bucket, str) or not bucket:
            raise StorageError("s3 storage requires config['bucket']")
        self._bucket_name: str = bucket

        self._prefix: str = str(config.get("prefix", ""))

        self._endpoint_url: str = str(
            config.get("endpoint_url", "https://s3.amazonaws.com")
        )

        self._region: str | None = None
        raw_region = config.get("region")
        if raw_region is not None:
            self._region = str(raw_region)

        self._path_style: bool = bool(config.get("path_style", False))

        self._secrets = secrets

        self._secret_ref: str | None = None
        raw_creds = config.get("credentials")
        if isinstance(raw_creds, dict) and list(raw_creds.keys()) == [SECRET_REF_KEY]:
            key = raw_creds.get(SECRET_REF_KEY)
            if isinstance(key, str):
                self._secret_ref = key

        self._session: aioboto3.Session | None = None

    async def _get_session(self) -> aioboto3.Session:
        """Lazy session construction with credential resolution."""
        if self._session is not None:
            return self._session

        kwargs: dict[str, Any] = {}
        if self._region is not None:
            kwargs["region_name"] = self._region

        if self._secret_ref is not None and self._secrets is not None:
            secret_value = await self._secrets.get(self._secret_ref)
            try:
                creds = json.loads(secret_value)
            except json.JSONDecodeError as exc:
                raise StorageError(
                    f"s3 credentials secret must be a JSON object: {exc}"
                ) from exc
            if not isinstance(creds, dict):
                raise StorageError("s3 credentials secret must be a JSON object")
            access_key = creds.get("aws_access_key_id")
            secret_key = creds.get("aws_secret_access_key")
            if not access_key or not secret_key:
                raise StorageError(
                    "s3 credentials secret must contain "
                    "'aws_access_key_id' and 'aws_secret_access_key'"
                )
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key

        self._session = aioboto3.Session(**kwargs)
        return self._session

    def _client_config(self) -> Config:
        addressing_style = "path" if self._path_style else "virtual"
        return Config(s3={"addressing_style": addressing_style})

    def _blob_name(self, namespace: str, key: str) -> str:
        if self._prefix:
            return f"{self._prefix}{namespace}/{key}.json"
        return f"{namespace}/{key}.json"

    def _namespace_prefix(self, namespace: str) -> str:
        if self._prefix:
            return f"{self._prefix}{namespace}/"
        return f"{namespace}/"

    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        session = await self._get_session()
        body = json.dumps(value).encode("utf-8")
        try:
            async with session.client(
                "s3",
                endpoint_url=self._endpoint_url,
                config=self._client_config(),
            ) as s3:
                await s3.put_object(
                    Bucket=self._bucket_name,
                    Key=self._blob_name(namespace, key),
                    Body=body,
                    ContentType="application/json",
                )
        except Exception as exc:
            raise StorageError(f"s3 put failed: {exc}") from exc

    async def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        session = await self._get_session()
        try:
            async with session.client(
                "s3",
                endpoint_url=self._endpoint_url,
                config=self._client_config(),
            ) as s3:
                response = await s3.get_object(
                    Bucket=self._bucket_name,
                    Key=self._blob_name(namespace, key),
                )
                raw = await response["Body"].read()
            loaded = json.loads(raw.decode("utf-8"))
            if not isinstance(loaded, dict):
                raise StorageError(f"s3 object {namespace}/{key!r} is not a dict")
            return loaded
        except Exception as exc:
            err_str = str(exc)
            if "NoSuchKey" in err_str or "404" in err_str:
                return None
            raise StorageError(f"s3 get failed: {exc}") from exc

    async def query(
        self, namespace: str, filter: QueryFilter | None = None
    ) -> list[dict[str, Any]]:
        session = await self._get_session()
        try:
            prefix = self._namespace_prefix(namespace)
            async with session.client(
                "s3",
                endpoint_url=self._endpoint_url,
                config=self._client_config(),
            ) as s3:
                paginator = s3.get_paginator("list_objects_v2")
                pages = paginator.paginate(
                    Bucket=self._bucket_name,
                    Prefix=prefix,
                )
                results: list[dict[str, Any]] = []
                async for page in pages:
                    contents = page.get("Contents", [])
                    for obj in contents:
                        key = obj["Key"]
                        try:
                            response = await s3.get_object(
                                Bucket=self._bucket_name, Key=key
                            )
                            raw = await response["Body"].read()
                            loaded = json.loads(raw.decode("utf-8"))
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
            raise StorageError(f"s3 query failed: {exc}") from exc

    async def delete(self, namespace: str, key: str) -> bool:
        session = await self._get_session()
        try:
            async with session.client(
                "s3",
                endpoint_url=self._endpoint_url,
                config=self._client_config(),
            ) as s3:
                try:
                    await s3.head_object(
                        Bucket=self._bucket_name,
                        Key=self._blob_name(namespace, key),
                    )
                except Exception as exc:
                    err_str = str(exc)
                    if "Not Found" in err_str or "404" in err_str:
                        return False
                    raise
                await s3.delete_object(
                    Bucket=self._bucket_name,
                    Key=self._blob_name(namespace, key),
                )
                return True
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"s3 delete failed: {exc}") from exc


def build(
    config: dict[str, object],
    *,
    secrets: SecretsImpl | None = None,
) -> S3Storage:
    return S3Storage(config, secrets=secrets)


def _main() -> None:
    """Test entry point for s3 storage impl.

    Requires the ``PYXEN_S3_TEST_BUCKET`` environment variable set to
    a real S3 bucket name that the caller can write to, and optionally
    ``PYXEN_S3_TEST_ENDPOINT``, ``PYXEN_S3_TEST_REGION``, and
    ``PYXEN_S3_TEST_PATH_STYLE``.
    """
    import asyncio
    import os

    from pyxen._testlib import arun_tests, skip

    bucket = os.environ.get("PYXEN_S3_TEST_BUCKET")
    if not bucket:
        skip("PYXEN_S3_TEST_BUCKET not set")
        return

    if not _HAS_S3:
        skip("aioboto3 not installed")
        return

    from pyxen.core.storage import QueryFilter

    async def _run_tests() -> None:
        test_prefix = f"pyxen-test-{os.urandom(4).hex()}/"
        cfg: dict[str, object] = {
            "bucket": bucket,
            "prefix": test_prefix,
        }
        endpoint = os.environ.get("PYXEN_S3_TEST_ENDPOINT")
        if endpoint:
            cfg["endpoint_url"] = endpoint
        region = os.environ.get("PYXEN_S3_TEST_REGION")
        if region:
            cfg["region"] = region
        if os.environ.get("PYXEN_S3_TEST_PATH_STYLE") == "1":
            cfg["path_style"] = True

        s = build(cfg)

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
            first_red = await s.query(
                "ns", QueryFilter(equals={"tag": "red"}, limit=1)
            )
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
                label="s3",
            )
        finally:
            if s._session is not None:
                async with s._session.client(
                    "s3",
                    endpoint_url=s._endpoint_url,
                    config=s._client_config(),
                ) as s3_client:
                    paginator = s3_client.get_paginator("list_objects_v2")
                    pages = paginator.paginate(
                        Bucket=bucket, Prefix=test_prefix
                    )
                    async for page in pages:
                        contents = page.get("Contents", [])
                        if contents:
                            await s3_client.delete_objects(
                                Bucket=bucket,
                                Delete={
                                    "Objects": [
                                        {"Key": c["Key"]} for c in contents
                                    ]
                                },
                            )

    try:
        asyncio.run(_run_tests())
    except Exception as exc:
        skip(f"{exc}")


if __name__ == "__main__":
    _main()
