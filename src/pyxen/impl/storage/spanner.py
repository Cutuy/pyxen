"""``spanner`` storage backend — Cloud Spanner-backed key-value store.

Each ``(namespace, key)`` pair is stored as a row in a Cloud Spanner table
with columns ``namespace STRING, key STRING, value JSON``.

Requires the ``google-cloud-spanner`` package:

    pip install pyxen[cloud]

Config (in ``runtime.json``):

.. code-block:: json

    "storage": {
        "implementation": "spanner",
        "config": {
            "project": "my-gcp-project",
            "instance": "my-instance",
            "database": "my-database",
            "table": "items",
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
import threading
from typing import Any

try:
    from google.cloud import spanner
    from google.oauth2 import service_account

    _HAS_SPANNER = True
except ImportError:
    _HAS_SPANNER = False


from ...core.errors import StorageError
from ...core.storage import QueryFilter


class SpannerStorage:
    """Storage impl backed by Cloud Spanner."""

    def __init__(self, config: dict[str, object]) -> None:
        if not _HAS_SPANNER:
            raise StorageError(
                "google-cloud-spanner is not installed. Run: pip install pyxen[cloud]"
            )

        project = config.get("project")
        if not isinstance(project, str) or not project:
            raise StorageError("spanner storage requires config['project']")
        self._project: str = project

        instance_id = config.get("instance")
        if not isinstance(instance_id, str) or not instance_id:
            raise StorageError("spanner storage requires config['instance']")
        self._instance_id: str = instance_id

        database_id = config.get("database")
        if not isinstance(database_id, str) or not database_id:
            raise StorageError("spanner storage requires config['database']")
        self._database_id: str = database_id

        table = config.get("table")
        if not isinstance(table, str) or not table:
            raise StorageError("spanner storage requires config['table']")
        self._table: str = table

        self._credentials_path: str | None = None
        raw_creds_path = config.get("credentials_path")
        if raw_creds_path is not None:
            self._credentials_path = str(raw_creds_path)

        self._credentials_json: str | None = None
        raw_creds_json = config.get("credentials_json")
        if raw_creds_json is not None:
            self._credentials_json = str(raw_creds_json)

        self._client: spanner.Client | None = None
        self._database: Any = None
        self._table_ready = False
        self._lock = threading.Lock()

    def _ensure_client(self) -> None:
        """Lazy client construction — create on first use, thread-safe."""
        with self._lock:
            if self._client is not None:
                return

            if self._credentials_path is not None:
                self._client = spanner.Client.from_service_account_json(
                    self._credentials_path, project=self._project
                )
            elif self._credentials_json is not None:
                creds_info = json.loads(self._credentials_json)
                creds = service_account.Credentials.from_service_account_info(
                    creds_info
                )
                self._client = spanner.Client(
                    project=self._project, credentials=creds
                )
            else:
                self._client = spanner.Client(project=self._project)

            instance = self._client.instance(self._instance_id)
            self._database = instance.database(self._database_id)

    def _ensure_table(self) -> None:
        """Create the items table if it doesn't exist (one-time)."""
        self._ensure_client()
        with self._lock:
            if self._table_ready:
                return
            ddl = (
                f"CREATE TABLE IF NOT EXISTS {self._table} ("
                f"  namespace STRING(MAX) NOT NULL,"
                f"  key STRING(MAX) NOT NULL,"
                f"  value JSON NOT NULL"
                f") PRIMARY KEY (namespace, key)"
            )
            operation = self._database.update_ddl([ddl])
            operation.result()
            self._table_ready = True

    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        self._ensure_table()
        try:

            def _update(transaction: Any) -> None:
                transaction.execute_update(
                    f"INSERT OR UPDATE INTO {self._table} "
                    f"(namespace, key, value) "
                    f"VALUES (@namespace, @key, @value)",
                    params={
                        "namespace": namespace,
                        "key": key,
                        "value": json.dumps(value),
                    },
                    param_types={
                        "namespace": spanner.param_types.STRING,
                        "key": spanner.param_types.STRING,
                        "value": spanner.param_types.JSON,
                    },
                )

            self._database.run_in_transaction(_update)
        except Exception as exc:
            raise StorageError(f"spanner put failed: {exc}") from exc

    async def get(
        self, namespace: str, key: str
    ) -> dict[str, Any] | None:
        self._ensure_table()
        try:
            with self._database.snapshot() as snapshot:
                results = snapshot.execute_sql(
                    f"SELECT value FROM {self._table} "
                    f"WHERE namespace = @namespace AND key = @key",
                    params={"namespace": namespace, "key": key},
                    param_types={
                        "namespace": spanner.param_types.STRING,
                        "key": spanner.param_types.STRING,
                    },
                )
                rows = list(results)
                if not rows:
                    return None
                val = rows[0][0]
                if isinstance(val, dict):
                    return val
                if isinstance(val, str):
                    loaded = json.loads(val)
                    if isinstance(loaded, dict):
                        return loaded
                return None
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"spanner get failed: {exc}") from exc

    async def query(
        self, namespace: str, filter: QueryFilter | None = None
    ) -> list[dict[str, Any]]:
        self._ensure_table()
        try:
            with self._database.snapshot() as snapshot:
                results = snapshot.execute_sql(
                    f"SELECT value FROM {self._table} "
                    f"WHERE namespace = @namespace",
                    params={"namespace": namespace},
                    param_types={
                        "namespace": spanner.param_types.STRING,
                    },
                )
                values = [row[0] for row in results]

            result_list: list[dict[str, Any]] = []
            for val in values:
                if isinstance(val, dict):
                    result_list.append(val)
                elif isinstance(val, str):
                    loaded = json.loads(val)
                    if isinstance(loaded, dict):
                        result_list.append(loaded)

            if filter is not None and filter.equals:
                result_list = [
                    r
                    for r in result_list
                    if all(r.get(k) == v for k, v in filter.equals.items())
                ]
            if filter is not None and filter.limit is not None:
                result_list = result_list[: filter.limit]

            return result_list
        except Exception as exc:
            raise StorageError(f"spanner query failed: {exc}") from exc

    async def delete(self, namespace: str, key: str) -> bool:
        self._ensure_table()
        try:
            existing = await self.get(namespace, key)
            if existing is None:
                return False

            def _delete(transaction: Any) -> None:
                transaction.execute_update(
                    f"DELETE FROM {self._table} "
                    f"WHERE namespace = @namespace AND key = @key",
                    params={"namespace": namespace, "key": key},
                    param_types={
                        "namespace": spanner.param_types.STRING,
                        "key": spanner.param_types.STRING,
                    },
                )

            self._database.run_in_transaction(_delete)
            return True
        except Exception as exc:
            raise StorageError(f"spanner delete failed: {exc}") from exc


def build(config: dict[str, object]) -> SpannerStorage:
    return SpannerStorage(config)


def _main() -> None:
    """Test entry point for spanner storage impl.

    Requires the following environment variables:

    - ``PYXEN_SPANNER_TEST_PROJECT``
    - ``PYXEN_SPANNER_TEST_INSTANCE``
    - ``PYXEN_SPANNER_TEST_DATABASE``
    """
    import asyncio
    import os
    from pyxen._testlib import arun_tests, skip

    project = os.environ.get("PYXEN_SPANNER_TEST_PROJECT")
    instance_id = os.environ.get("PYXEN_SPANNER_TEST_INSTANCE")
    database_id = os.environ.get("PYXEN_SPANNER_TEST_DATABASE")
    if not project or not instance_id or not database_id:
        skip(
            "PYXEN_SPANNER_TEST_PROJECT, PYXEN_SPANNER_TEST_INSTANCE, "
            "and PYXEN_SPANNER_TEST_DATABASE must be set"
        )
        return

    if not _HAS_SPANNER:
        skip("google-cloud-spanner not installed")
        return

    from pyxen.core.storage import QueryFilter

    async def _run_tests() -> None:
        s = build(
            {
                "project": project,
                "instance": instance_id,
                "database": database_id,
                "table": "pyxen_test_items",
            }
        )

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
            await s.put(
                "ns", "nested", {"a": {"b": {"c": [1, 2, 3]}}}
            )
            assert await s.get("ns", "nested") == {
                "a": {"b": {"c": [1, 2, 3]}}
            }

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
                label="spanner",
            )
        finally:
            try:

                def _cleanup(txn: Any) -> None:
                    txn.execute_update(
                        f"DELETE FROM {s._table} "
                        f"WHERE namespace = @ns OR namespace = @other",
                        params={"ns": "ns", "other": "other"},
                        param_types={
                            "ns": spanner.param_types.STRING,
                            "other": spanner.param_types.STRING,
                        },
                    )

                s._database.run_in_transaction(_cleanup)
            except Exception:
                pass

    asyncio.run(_run_tests())


if __name__ == "__main__":
    _main()
