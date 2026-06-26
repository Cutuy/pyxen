"""bigquery_secrets — query a BigQuery table using runtime-injected secrets.

The point: the app never touches credentials, environment variables, or
cloud SDK config directly. It only ever calls ``rt.storage.query(...)``.
The ``runtime.json`` declares *where* the secret lives (dotenv, local_file,
Vault, ...) and the app is none the wiser.

Same code. Different runtime.json. No application changes.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from pyxen import Runtime


async def query_table(runtime_path: str) -> list[dict]:
    """Load the runtime and query the configured storage backend."""
    rt = await Runtime.load(runtime_path)
    async with rt.observability.trace("bigquery_query") as span:
        span.set_attribute("impl", rt.manifest.bindings["storage"].implementation)
        rows = await rt.storage.query("items")
        span.set_attribute("row_count", len(rows))
    return rows


async def _test_main() -> None:
    """Self-test: run the same app logic with inmemory storage.

    No real BigQuery credentials, no ``bq`` CLI — demonstrates the
    same app code works against a different backend.
    """
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text(
            'GCP_SA_JSON={"type":"service_account","project_id":"test","private_key":"FAKE"}\n'
        )

        manifest = {
            "version": "1",
            "secrets": {
                "implementation": "dotenv",
                "config": {"path": str(env_path)},
            },
            "storage": {
                "implementation": "inmemory",
                "config": {},
            },
            "observability": {
                "implementation": "null",
                "config": {},
            },
        }
        rt_path = Path(tmp) / "runtime.json"
        rt_path.write_text(json.dumps(manifest))

        rt = await Runtime.load(str(rt_path))
        await rt.storage.put(
            "items", "row-1", {"name": "alice", "score": 42}
        )
        await rt.storage.put(
            "items", "row-2", {"name": "bob", "score": 99}
        )

        # query through the same runtime (inmemory keeps data in-process)
        rows = await rt.storage.query("items")
        assert len(rows) == 2, f"expected 2 rows, got {len(rows)}"
        print(f"Test passed: retrieved {len(rows)} row(s)")
        for r in rows:
            print(f"  {r}")


def main() -> None:
    if "--test" in sys.argv:
        asyncio.run(_test_main())
        return

    if shutil.which("bq") is None:
        print(
            "Error: bq CLI not found on PATH. Install Google Cloud SDK.",
            file=sys.stderr,
        )
        print(
            "Run with --test for a demo without real BigQuery.",
            file=sys.stderr,
        )
        sys.exit(1)

    here = Path(__file__).resolve().parent
    runtime_path = here / "runtime.json"
    if not runtime_path.is_file():
        print(f"Error: runtime.json not found at {runtime_path}", file=sys.stderr)
        sys.exit(1)

    os.chdir(here)
    rows = asyncio.run(query_table(str(runtime_path)))
    print(f"Queried {len(rows)} row(s) from BigQuery")
    for r in rows:
        print(f"  {r}")


if __name__ == "__main__":
    main()
