"""pkg_demo — shows how pyxen's ``pkg`` primitive manages dependencies.

The runtime.json declares ``pkg`` with the ``pip`` implementation,
pointing to a ``requirements.txt``. On load, app code calls
``rt.pkg.ensure()`` to install any missing PyPI packages, then
imports and uses them normally.

Run with:

    python -m examples.pkg_demo.main

or, from the repo root:

    PYTHONPATH=src python examples/pkg_demo/main.py
"""

from __future__ import annotations

import asyncio
import os

from pathlib import Path

from pyxen import Runtime
from pyxen._paths import project_root

HERE = Path(__file__).resolve().parent


async def main() -> None:
    rt = await Runtime.load(HERE / "runtime.json")

    # 1. Ensure declared PyPI deps are installed.
    snap = await rt.pkg.ensure()
    print(f"pkg ensured at t={snap.timestamp:.0f}; {len(snap.packages)} packages resolved")

    # 2. Verify everything is satisfied.
    result = await rt.pkg.verify()
    print(f"verification: {'OK' if result.satisfied else 'MISSING: ' + str(result.missing)}")

    # 3. Import and use installed dependencies normally.
    import requests

    me = await rt.identity.current()
    resp = requests.get("https://httpbin.org/uuid", timeout=10)
    uuid = resp.json()["uuid"]
    print(f"hi from {me.id}; fetched uuid={uuid}")


if __name__ == "__main__":
    if "PYTHONPATH" not in os.environ and (project_root() / "src").is_dir():
        os.environ["PYTHONPATH"] = str(project_root() / "src")
    asyncio.run(main())
