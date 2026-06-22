"""pyxen cron — cross-platform task scheduling via OS-native backends.

Supports:
- Linux: systemd --user timers (no sudo)
- macOS: launchd agents
- Windows: Task Scheduler (schtasks.exe)

Usage::

    from pyxen.core.cron import CronScheduler, CronJob

    async def main():
        scheduler = CronScheduler()
        job = CronJob(name="backup", command="/usr/bin/backup.sh",
                      schedule="0 3 * * *")
        await scheduler.schedule(job)
        # ...
        await scheduler.unschedule("backup")
"""

from __future__ import annotations

from .errors import CronBackendError, CronError, CronScheduleError
from .models import CronJob, CronStatus
from .scheduler import CronScheduler

__all__ = [
    "CronBackendError",
    "CronError",
    "CronJob",
    "CronScheduleError",
    "CronScheduler",
    "CronStatus",
]
