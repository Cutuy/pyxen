#!/usr/bin/env python3
"""Integration test for the crontab backend.

Saves the user's crontab, runs real schedule/list/status/unschedule
operations against it, then restores. Requires ``crontab`` on PATH.

Usage:
    python scripts/test_crontab.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


async def main() -> int:
    from pyxen.core.ext.cron import CronJob, CronScheduler

    # ── 1. probe ──────────────────────────────────────────────────────
    from pyxen.core.ext.cron._crontab import probe
    if not probe():
        print("SKIP: crontab not available")
        return 0

    sched = CronScheduler(backend="crontab")
    UNIQ = f"pyxen-inttest-{id(sched)}"

    # ── 2. save current crontab (minus any stale test artifacts) ──────
    from pyxen.core.ext.cron._crontab import _crontab_read, _crontab_write
    raw_saved = await _crontab_read()
    # Filter out any pyxen-managed lines so we start from a clean slate
    saved = [l for l in raw_saved if "# pyxen:" not in l]

    try:
        # ── 3. schedule ───────────────────────────────────────────────
        j1 = CronJob(name=f"{UNIQ}-a", command="echo hi", schedule="* * * * *")
        j2 = CronJob(name=f"{UNIQ}-b", command="echo there", schedule="*/5 * * * *")

        await sched.schedule(j1)
        await sched.schedule(j2)

        # ── 4. list ───────────────────────────────────────────────────
        jobs = await sched.list()
        ours = [j for j in jobs if UNIQ in j.name]
        assert len(ours) == 2, f"expected 2 jobs, got {len(ours)}: {[j.name for j in ours]}"
        print(f"  list: {len(ours)}/{len(jobs)} jobs match")

        # ── 5. status ─────────────────────────────────────────────────
        s_a = await sched.status(f"{UNIQ}-a")
        assert s_a is not None, "status should find scheduled job"
        assert s_a.enabled is True
        assert s_a.active is True
        print(f"  status({UNIQ}-a): enabled={s_a.enabled} active={s_a.active}")

        s_missing = await sched.status(f"{UNIQ}-nonexistent")
        assert s_missing is None, "status should return None for unknown job"
        print(f"  status({UNIQ}-nonexistent): None (correct)")

        # ── 6. idempotency — schedule same name again ─────────────────
        j1_dup = CronJob(name=f"{UNIQ}-a", command="echo hi again", schedule="0 * * * *")
        await sched.schedule(j1_dup)

        jobs2 = await sched.list()
        ours2 = [j for j in jobs2 if UNIQ in j.name]
        assert len(ours2) == 2, (
            f"expected 2 jobs after replacing duplicate, "
            f"got {len(ours2)}: {[j.name for j in ours2]}"
        )
        # Verify the command was updated
        dup_job = [j for j in ours2 if j.name == f"{UNIQ}-a"][0]
        assert "hi again" in dup_job.command, f"command should be updated: {dup_job.command}"
        print(f"  idempotent: 2 jobs after re-schedule (correct)")

        # ── 7. unschedule ─────────────────────────────────────────────
        await sched.unschedule(f"{UNIQ}-a")
        jobs3 = await sched.list()
        ours3 = [j for j in jobs3 if UNIQ in j.name]
        assert len(ours3) == 1, f"expected 1 job after unschedule, got {len(ours3)}"
        assert ours3[0].name == f"{UNIQ}-b"
        print(f"  unschedule: 1 job remains (correct)")

        # ── 8. cleanup remaining ──────────────────────────────────────
        await sched.unschedule(f"{UNIQ}-b")
        jobs4 = await sched.list()
        ours4 = [j for j in jobs4 if UNIQ in j.name]
        assert len(ours4) == 0, f"expected 0 jobs after cleanup, got {len(ours4)}"
        print(f"  cleanup: 0 jobs remain (correct)")

        # ── 9. non-pyxen entries preserved ────────────────────────────
        # Add a non-pyxen entry, then schedule a pyxen job
        non_pyxen = "# this is a non-pyxen comment"
        await _crontab_write([*saved, non_pyxen])
        j3 = CronJob(name=f"{UNIQ}-c", command="echo preserve", schedule="30 9 * * *")
        await sched.schedule(j3)
        final = await _crontab_read()
        assert non_pyxen in final, "non-pyxen entry should be preserved"
        pyxen_lines = [l for l in final if "# pyxen:" in l]
        assert len(pyxen_lines) == 1, f"expected 1 pyxen line, got {len(pyxen_lines)}"
        print(f"  non-pyxen preserved: {non_pyxen}")

        # Cleanup
        await sched.unschedule(f"{UNIQ}-c")

        print("\n  ALL PASSED")

    finally:
        # ── restore original crontab exactly ──────────────────────────
        await _crontab_write(raw_saved)
        restored = await _crontab_read()
        assert restored == raw_saved, "crontab should be restored to original"
        print("  original crontab restored")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
