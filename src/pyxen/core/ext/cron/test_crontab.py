"""Integration test for the crontab backend.

Saves the user's crontab, runs real schedule/list/status/unschedule
operations against it, then restores. Requires ``crontab`` on PATH.
"""

from __future__ import annotations

import asyncio
import os
import sys

from . import CronJob, CronScheduler


def _main() -> int:
    from pyxen._testlib import skip

    if os.environ.get("PYXEN_INTEGRATION", "").strip().lower() not in ("1", "true", "yes"):
        skip("set PYXEN_INTEGRATION=true to run crontab integration tests")
        return 0
    return asyncio.run(_run())


async def _run() -> int:
    from pyxen._testlib import skip, arun_tests
    from ._crontab import probe, _crontab_read, _crontab_write

    if not probe():
        skip("crontab not available")
        return 0

    sched = CronScheduler(backend="crontab")
    uniq = f"pyxen-inttest-{os.urandom(4).hex()}"

    # Save original crontab (minus any stale pyxen-managed lines for a clean start)
    raw_saved = await _crontab_read()
    clean_base = [l for l in raw_saved if "# pyxen:" not in l]

    try:
        j1 = CronJob(name=f"{uniq}-a", command="echo hi", schedule="* * * * *")
        j2 = CronJob(name=f"{uniq}-b", command="echo there", schedule="*/5 * * * *")

        async def test_schedule_and_list() -> None:
            await sched.schedule(j1)
            await sched.schedule(j2)
            jobs = await sched.list()
            ours = [j for j in jobs if uniq in j.name]
            assert len(ours) == 2, f"expected 2 jobs, got {len(ours)}"

        async def test_status() -> None:
            s_a = await sched.status(f"{uniq}-a")
            assert s_a is not None
            assert s_a.enabled is True and s_a.active is True

        async def test_status_nonexistent() -> None:
            s_m = await sched.status(f"{uniq}-nonexistent")
            assert s_m is None

        async def test_idempotency() -> None:
            j1_dup = CronJob(name=f"{uniq}-a", command="echo hi again", schedule="0 * * * *")
            await sched.schedule(j1_dup)
            jobs2 = await sched.list()
            ours2 = [j for j in jobs2 if uniq in j.name]
            assert len(ours2) == 2, f"expected 2 after replace, got {len(ours2)}"
            dup_job = [j for j in ours2 if j.name == f"{uniq}-a"][0]
            assert "hi again" in dup_job.command

        async def test_unschedule() -> None:
            await sched.unschedule(f"{uniq}-a")
            jobs3 = await sched.list()
            ours3 = [j for j in jobs3 if uniq in j.name]
            assert len(ours3) == 1 and ours3[0].name == f"{uniq}-b"

        async def test_cleanup() -> None:
            await sched.unschedule(f"{uniq}-b")
            jobs4 = await sched.list()
            ours4 = [j for j in jobs4 if uniq in j.name]
            assert len(ours4) == 0

        async def test_non_pyxen_preserved() -> None:
            non_pyxen = "# this is a non-pyxen comment"
            await _crontab_write([*clean_base, non_pyxen])
            j3 = CronJob(name=f"{uniq}-c", command="echo preserve", schedule="30 9 * * *")
            await sched.schedule(j3)
            final = await _crontab_read()
            assert non_pyxen in final, "non-pyxen entry should be preserved"
            pyxen_lines = [l for l in final if "# pyxen:" in l]
            assert len(pyxen_lines) == 1, f"expected 1 pyxen line, got {len(pyxen_lines)}"
            await sched.unschedule(f"{uniq}-c")

        await arun_tests(
            test_schedule_and_list,
            test_status,
            test_status_nonexistent,
            test_idempotency,
            test_unschedule,
            test_cleanup,
            test_non_pyxen_preserved,
        )

    finally:
        await _crontab_write(raw_saved)
        restored = await _crontab_read()
        assert restored == raw_saved, "crontab should be restored to original"

    return 0


if __name__ == "__main__":
    sys.exit(_main())
