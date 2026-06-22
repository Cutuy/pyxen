"""``bq`` storage backend — BigQuery-backed key-value store.

Each ``(namespace, key)`` pair is stored as a row in a BigQuery table
with columns ``namespace STRING, key STRING, value JSON``.

Uses the ``bq`` CLI tool (Google Cloud SDK) via subprocess — not the
``google-cloud-bigquery`` Python SDK.

Config (in ``runtime.json``):

.. code-block:: json

    "storage": {
        "implementation": "bq",
        "config": {
            "project": "my-gcp-project",
            "dataset": "my_dataset",
            "table": "items",
            "credentials": {"$secret": "gcp_sa_json"}
        }
    }

Credentials always come from the secrets primitive via the ``{"$secret": "key"}``
reference. The resolved value must be a service-account JSON key, written to a
temp file and exposed as ``GOOGLE_APPLICATION_CREDENTIALS`` in the subprocess env.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Awaitable
from typing import Any

from ...core.errors import StorageError
from ...core.manifest import SECRET_REF_KEY
from ...core.observability import ObservabilityImpl
from ...core.secrets import SecretsImpl
from ...core.storage import QueryFilter


class BqStorage:
    """Storage impl backed by BigQuery via the ``bq`` CLI."""

    def __init__(
        self,
        config: dict[str, object],
        *,
        secrets: SecretsImpl | None = None,
        observability: ObservabilityImpl | None = None,
    ) -> None:
        self._bq_path = shutil.which("bq")
        if self._bq_path is None:
            raise StorageError("bq CLI tool not found on PATH")

        project = config.get("project")
        if not isinstance(project, str) or not project:
            raise StorageError("bq storage requires config['project']")
        self._project: str = project

        dataset = config.get("dataset")
        if not isinstance(dataset, str) or not dataset:
            raise StorageError("bq storage requires config['dataset']")
        self._dataset: str = dataset

        table = config.get("table")
        if not isinstance(table, str) or not table:
            raise StorageError("bq storage requires config['table']")
        self._table: str = table

        self._secrets = secrets
        self._observability = observability

        self._secret_ref: str | None = None
        raw_creds = config.get("credentials")
        if isinstance(raw_creds, dict) and list(raw_creds.keys()) == [SECRET_REF_KEY]:
            key = raw_creds.get(SECRET_REF_KEY)
            if isinstance(key, str):
                self._secret_ref = key

        if self._secret_ref is None and secrets is None:
            raise StorageError(
                "bq storage requires config['credentials'] with a "
                f"{{{SECRET_REF_KEY!r}: 'key_name'}} reference"
            )

        self._table_ref = f"{self._project}.{self._dataset}.{self._table}"

        self._env_lock = asyncio.Lock()
        self._credentials_resolved_path: str | None = None
        self._temp_cred_file: str | None = None
        self._resolved = False

    async def _resolve_credentials(self) -> None:
        if self._resolved:
            return
        async with self._env_lock:
            if not self._resolved:
                assert self._secret_ref is not None and self._secrets is not None
                secret_value = await self._secrets.get(self._secret_ref)
                fd, path = tempfile.mkstemp(
                    suffix=".json", prefix="pyxen-bq-creds-"
                )
                try:
                    os.write(fd, secret_value.encode("utf-8"))
                finally:
                    os.close(fd)
                self._temp_cred_file = path
                self._credentials_resolved_path = path
                self._resolved = True

    def _env(self) -> dict[str, str]:
        """Build the subprocess environment."""
        env = dict(os.environ)
        env["CLOUDSDK_CORE_PROJECT"] = self._project
        if self._credentials_resolved_path is not None:
            env["GOOGLE_APPLICATION_CREDENTIALS"] = (
                self._credentials_resolved_path
            )
        return env

    async def _run_bq(
        self, args: list[str], input_data: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        await self._resolve_credentials()
        env = self._env()
        assert self._bq_path is not None
        cmd: list[str] = [self._bq_path, *args]

        def _run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                cmd,
                input=input_data,
                capture_output=True,
                text=True,
                env=env,
                timeout=60,
            )

        if self._observability is not None:
            async with self._observability.trace("bq") as span:
                span.set_attribute("args", " ".join(cmd))
                result = await asyncio.to_thread(_run)
                span.set_attribute("exit_code", result.returncode)
                if result.returncode != 0:
                    span.log("error", result.stderr.strip())
                return result

        return await asyncio.to_thread(_run)

    @staticmethod
    def _make_row(
        namespace: str, key: str, value: dict[str, Any]
    ) -> dict[str, object]:
        return {"namespace": namespace, "key": key, "value": value}

    @staticmethod
    def _parse_query_result(stdout: str) -> list[dict[str, Any]]:
        """Parse the JSON array output from ``bq query --format=json``."""
        if not stdout.strip():
            return []
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise StorageError(
                f"bq query returned non-JSON output: {exc}"
            ) from exc
        if isinstance(parsed, list):
            rows: list[dict[str, Any]] = []
            for item in parsed:
                if isinstance(item, dict):
                    fixed: dict[str, Any] = {}
                    for k, v in item.items():
                        # JSON column values may arrive as JSON strings
                        if isinstance(v, str) and k == "value":
                            try:
                                fixed[k] = json.loads(v)
                            except (json.JSONDecodeError, TypeError):
                                fixed[k] = v
                        else:
                            fixed[k] = v
                    rows.append(fixed)
                else:
                    rows.append({"value": item})
            return rows
        if isinstance(parsed, dict):
            return [parsed]
        return []

    async def put(
        self, namespace: str, key: str, value: dict[str, Any]
    ) -> None:
        # Delete existing row first (best-effort, ignore errors)
        await self._run_bq([
            "query",
            "--format=json",
            "--use_legacy_sql=false",
            "--parameter",
            f"ns:STRING:{namespace}",
            "--parameter",
            f"k:STRING:{key}",
            f"DELETE FROM {self._table_ref} WHERE namespace = @ns AND key = @k",
        ])

        row_jsonl = (
            json.dumps(self._make_row(namespace, key, value)) + "\n"
        )
        result = await self._run_bq(
            ["insert", self._table_ref], input_data=row_jsonl
        )
        if result.returncode != 0:
            raise StorageError(
                f"bq insert failed: {result.stderr.strip()}"
            )

    async def get(
        self, namespace: str, key: str
    ) -> dict[str, Any] | None:
        result = await self._run_bq([
            "query",
            "--format=json",
            "--use_legacy_sql=false",
            "--parameter",
            f"ns:STRING:{namespace}",
            "--parameter",
            f"k:STRING:{key}",
            f"SELECT value FROM {self._table_ref} WHERE namespace = @ns AND key = @k LIMIT 1",
        ])
        if result.returncode != 0:
            raise StorageError(
                f"bq get failed: {result.stderr.strip()}"
            )

        rows = self._parse_query_result(result.stdout)
        if not rows:
            return None
        val = rows[0].get("value")
        if isinstance(val, dict):
            return val
        return None

    async def query(
        self, namespace: str, filter: QueryFilter | None = None
    ) -> list[dict[str, Any]]:
        result = await self._run_bq([
            "query",
            "--format=json",
            "--use_legacy_sql=false",
            "--parameter",
            f"ns:STRING:{namespace}",
            f"SELECT value FROM {self._table_ref} WHERE namespace = @ns",
        ])
        if result.returncode != 0:
            raise StorageError(
                f"bq query failed: {result.stderr.strip()}"
            )

        results: list[dict[str, Any]] = []
        for row in self._parse_query_result(result.stdout):
            val = row.get("value")
            if isinstance(val, dict):
                results.append(val)

        if filter is not None and filter.equals:
            results = [
                r
                for r in results
                if all(
                    r.get(k) == v for k, v in filter.equals.items()
                )
            ]
        if filter is not None and filter.limit is not None:
            results = results[: filter.limit]

        return results

    async def delete(self, namespace: str, key: str) -> bool:
        existing = await self.get(namespace, key)
        if existing is None:
            return False

        result = await self._run_bq([
            "query",
            "--format=json",
            "--use_legacy_sql=false",
            "--parameter",
            f"ns:STRING:{namespace}",
            "--parameter",
            f"k:STRING:{key}",
            f"DELETE FROM {self._table_ref} WHERE namespace = @ns AND key = @k",
        ])
        if result.returncode != 0:
            raise StorageError(
                f"bq delete failed: {result.stderr.strip()}"
            )
        return True


def build(
    config: dict[str, object],
    *,
    secrets: SecretsImpl | None = None,
    observability: ObservabilityImpl | None = None,
) -> BqStorage:
    return BqStorage(config, secrets=secrets, observability=observability)


def _main() -> None:
    """Test entry point for bq storage impl.

    Requires ``PYXEN_BQ_TEST_PROJECT`` and ``bq`` on PATH. Creates a
    temporary dataset+table, runs all ``_test_*`` functions, then cleans up.
    """
    import asyncio
    import secrets as _secrets_mod

    bq = shutil.which("bq")
    if bq is None:
        print("bq: SKIP (bq CLI not on PATH)")
        return

    project = os.environ.get("PYXEN_BQ_TEST_PROJECT")
    if not project:
        print("bq: SKIP (PYXEN_BQ_TEST_PROJECT not set)")
        return

    suffix = _secrets_mod.token_hex(4)
    dataset = f"pyxen_test_{suffix}"
    table = "items"

    env = dict(os.environ)
    env["CLOUDSDK_CORE_PROJECT"] = project

    def _run(
        *args: str, input_data: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [bq, *args],
            input=input_data,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

    # Create dataset
    r = asyncio.run(asyncio.to_thread(
        _run, "mk", "--dataset", f"{project}:{dataset}"
    ))
    if r.returncode != 0:
        print(f"bq: SKIP (failed to create dataset: {r.stderr.strip()})")
        return

    # Create table
    r = asyncio.run(asyncio.to_thread(
        _run, "mk", "--table", f"{project}:{dataset}.{table}",
        "namespace:STRING,key:STRING,value:JSON",
    ))
    if r.returncode != 0:
        asyncio.run(asyncio.to_thread(
            _run, "rm", "-f", "--dataset", f"{project}:{dataset}"
        ))
        print(f"bq: SKIP (failed to create table: {r.stderr.strip()})")
        return

    try:
        s = build({"project": project, "dataset": dataset, "table": table})

        async def test_put_get(s: BqStorage) -> None:
            await s.put("ns", "k", {"v": 1, "name": "alice"})
            got = await s.get("ns", "k")
            assert got == {"v": 1, "name": "alice"}, f"got {got}"

        async def test_overwrite(s: BqStorage) -> None:
            await s.put("ns", "k", {"v": 2})
            assert await s.get("ns", "k") == {"v": 2}

        async def test_missing(s: BqStorage) -> None:
            assert await s.get("ns", "missing") is None
            assert await s.get("nonexistent", "k") is None

        async def test_empty_value(s: BqStorage) -> None:
            await s.put("ns", "empty", {})
            assert await s.get("ns", "empty") == {}

        async def test_nested(s: BqStorage) -> None:
            await s.put("ns", "nested", {"a": {"b": {"c": [1, 2, 3]}}})
            assert await s.get("ns", "nested") == {"a": {"b": {"c": [1, 2, 3]}}}

        async def test_query_all(s: BqStorage) -> None:
            await s.put("ns", "qa", {"v": 1})
            await s.put("ns", "qb", {"v": 2})
            await s.put("ns", "qc", {"v": 3})
            results = await s.query("ns")
            assert len(results) >= 3

        async def test_query_filter(s: BqStorage) -> None:
            await s.put("ns", "x1", {"tag": "red", "n": 1})
            await s.put("ns", "x2", {"tag": "red", "n": 2})
            await s.put("ns", "x3", {"tag": "blue", "n": 3})
            red = await s.query("ns", QueryFilter(equals={"tag": "red"}))
            assert all(r["tag"] == "red" for r in red)
            assert len(red) == 2

        async def test_query_limit(s: BqStorage) -> None:
            first_two = await s.query("ns", QueryFilter(limit=2))
            assert len(first_two) == 2

        async def test_namespace_isolation(s: BqStorage) -> None:
            await s.put("other", "k", {"v": 99})
            other = await s.query("other")
            assert len(other) == 1
            assert other[0]["v"] == 99

        async def test_delete_existing(s: BqStorage) -> None:
            assert await s.delete("ns", "qa") is True
            assert await s.get("ns", "qa") is None

        async def test_delete_missing(s: BqStorage) -> None:
            assert await s.delete("ns", "missing_xyz") is False
            assert await s.delete("nonexistent", "k") is False

        async def _run_tests() -> None:
            passed = 0
            failed = 0
            cases: list[tuple[str, Awaitable[Any]]] = [
                ("put/get", test_put_get(s)),
                ("overwrite", test_overwrite(s)),
                ("missing returns None", test_missing(s)),
                ("empty value", test_empty_value(s)),
                ("nested values", test_nested(s)),
                ("query all", test_query_all(s)),
                ("query filter", test_query_filter(s)),
                ("query limit", test_query_limit(s)),
                ("namespace isolation", test_namespace_isolation(s)),
                ("delete existing", test_delete_existing(s)),
                ("delete missing", test_delete_missing(s)),
            ]
            for name, coro in cases:
                try:
                    await coro
                    passed += 1
                    print(f"  ✓ {name}")
                except Exception as e:
                    failed += 1
                    print(f"  ✗ {name}: {e}")
            if failed:
                print(f"bq: {passed} passed, {failed} FAILED")
            else:
                print(f"bq: {passed} passed — OK")

        asyncio.run(_run_tests())
    except Exception as exc:
        print(f"bq: SKIP ({exc})")
    finally:
        asyncio.run(asyncio.to_thread(
            _run, "rm", "-f", "--dataset", f"{project}:{dataset}"
        ))


if __name__ == "__main__":
    _main()
