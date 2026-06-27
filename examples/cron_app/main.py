"""cron_app — demonstrate declarative cron job scheduling.

Loads a runtime.json that declares two cron jobs. The runtime auto-schedules
them on startup via the OS-native backend (crontab on Linux/macOS, schtasks on
Windows). The app itself is hands-off — it never calls a scheduler API.

Run with:

    python -m examples.cron_app.main

or, from the repo root:

    PYTHONPATH=src python examples/cron_app/main.py
"""

from __future__ import annotations

import asyncio
import os

from pathlib import Path

from pyxen import Runtime
from pyxen._paths import project_root

HERE = Path(__file__).resolve().parent


def _setup_pythonpath() -> None:
    src = project_root() / "src"
    if "PYTHONPATH" not in os.environ and src.is_dir():
        os.environ["PYTHONPATH"] = str(src)


async def _run(cleanup: bool) -> None:
    rt = await Runtime.load(HERE / "runtime.json")

    who = await rt.identity.current()
    print(f"loaded runtime for {who.id} (version={rt.manifest.version})")

    if "cron" in rt.manifest.extensions:
        print("cron extension declared in manifest")
    else:
        print("no cron extension declared")
        return

    # The runtime exposes the initialized cron extension as rt.cron.
    if not hasattr(rt, "cron"):
        print("  (no cron backend available — skipping)")
        return

    cron = rt.cron
    jobs = await cron.list()
    print(f"  backend: {cron.backend}")
    print(f"declared {len(jobs)} cron job(s):")

    for job in jobs:
        existing = await cron.status(job.name)
        status = "scheduled" if existing is None else "active"
        print(f"  [{status}] {job.name}: {job.schedule} -> {job.command}")

    scheduled = await cron.list()
    ours = [j for j in scheduled if j.name.startswith("pyxen-example-")]
    print(f"  {len(ours)} pyxen-example job(s) active in {cron.backend}")

    if cleanup:
        for job in jobs:
            await cron.unschedule(job.name)
        print("  (cleaned up — test mode)")
    elif ours:
        print()
        print("remove with: crontab -e   # Linux/macOS")
        print("     or:     schtasks /delete /tn pyxen-example-* /f   # Windows")


def _main() -> None:
    _setup_pythonpath()
    asyncio.run(_run(cleanup=True))


if __name__ == "__main__":
    _setup_pythonpath()
    asyncio.run(_run(cleanup=False))
