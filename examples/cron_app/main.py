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

HERE = Path(__file__).resolve().parent


def _setup_pythonpath() -> None:
    src = Path(__file__).resolve().parents[2] / "src"
    if "PYTHONPATH" not in os.environ and src.is_dir():
        os.environ["PYTHONPATH"] = str(src)


async def _run(cleanup: bool) -> None:
    rt = await Runtime.load(HERE / "runtime.json")

    who = await rt.identity.current()
    print(f"loaded runtime for {who.id} (version={rt.manifest.version})")

    cron_jobs = rt.manifest.cron_jobs
    if not cron_jobs:
        print("no cron jobs declared in manifest")
        return

    on_dup = rt.manifest.cron_on_duplicate
    print(f"cron.on_duplicate = {on_dup}")
    print(f"declared {len(cron_jobs)} cron job(s):")

    from pyxen.core.cron import CronBackendError, CronScheduler

    try:
        scheduler = CronScheduler()
    except CronBackendError:
        print("  (no cron backend available — skipping)")
        return

    print(f"  backend: {scheduler.backend}")

    for job in cron_jobs:
        existing = await scheduler.status(job.name)
        status = "scheduled" if existing is None else "replaced"
        print(f"  [{status}] {job.name}: {job.schedule} -> {job.command}")

    scheduled = await scheduler.list()
    ours = [j for j in scheduled if j.name.startswith("pyxen-example-")]
    print(f"  {len(ours)} pyxen-example job(s) active in {scheduler.backend}")

    if cleanup:
        for job in cron_jobs:
            await scheduler.unschedule(job.name)
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
