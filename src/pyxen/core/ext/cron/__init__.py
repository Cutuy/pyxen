"""pyxen cron extension — cross-platform task scheduling via OS-native backends.

Supports:
- Linux/macOS: crontab
- Windows: Task Scheduler (schtasks.exe)

This is a runtime extension (``pyxen.core.ext.cron``), not a core primitive.
It is initialized from the ``cron`` section of ``runtime.json`` and exposed
as ``rt.cron`` so apps can query job state.

Usage:

    rt = await Runtime.load("runtime.json")
    status = await rt.cron.status("heartbeat")
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import CronBackendError
from .models import CronJob, CronStatus
from .scheduler import CronScheduler
from .state import CronStateStore

__all__ = [
    "CronBackendError",
    "CronError",
    "CronJob",
    "CronScheduleError",
    "CronScheduler",
    "CronStatus",
]


@dataclass
class CronExtension:
    """The cron extension instance exposed as ``rt.cron``.

    Wraps a ``CronScheduler`` and a ``CronStateStore`` so apps can query
    both the scheduling state and execution history of their cron jobs.
    """

    scheduler: CronScheduler
    state_store: CronStateStore | None = None
    _jobs: dict[str, CronJob] = field(default_factory=dict)

    async def schedule(self, job: CronJob) -> None:
        await self.scheduler.schedule(job)
        self._jobs[job.name] = job

    async def unschedule(self, name: str) -> None:
        await self.scheduler.unschedule(name)
        self._jobs.pop(name, None)

    async def list(self) -> list[CronJob]:
        return list(self._jobs.values())

    async def status(self, name: str) -> CronStatus | None:
        """Return the combined status (scheduler + execution history)."""
        sched_status = await self.scheduler.status(name)
        if sched_status is None and self.state_store is None:
            return None
        if sched_status is None:
            return self.state_store.status(name) if self.state_store else None

        if self.state_store:
            stored = self.state_store.status(name)
            if stored:
                if stored.last_run:
                    sched_status.last_run = stored.last_run
                if stored.last_result:
                    sched_status.last_result = stored.last_result
                if stored.active:
                    sched_status.active = stored.active
        return sched_status

    @property
    def backend(self) -> str:
        return self.scheduler.backend


async def init(config: dict[str, Any], app_dir: Path | None) -> CronExtension | None:
    """Initialize the cron extension from its manifest config section.

    Called by the extension loader during ``Runtime.load()``. Creates a
    ``CronScheduler``, optionally wraps commands with state recording, and
    schedules all declared jobs.

    Args:
        config: The ``cron`` section from ``runtime.json``.
        app_dir: The application root directory.

    Returns:
        A ``CronExtension`` if scheduling succeeds, or ``None`` if the
        platform has no supported cron backend.
    """
    jobs_raw = config.get("jobs", [])
    if not jobs_raw:
        return None

    if not isinstance(jobs_raw, list):
        raise CronBackendError("cron 'jobs' must be a JSON array")

    try:
        scheduler = CronScheduler()
    except CronBackendError:
        return None

    state_store = _make_state_store(config, app_dir)

    parsed_jobs = _parse_manifest_jobs(jobs_raw)
    ext = CronExtension(scheduler=scheduler, state_store=state_store)

    for job in parsed_jobs:
        resolved = _resolve_cron_command(job, app_dir)

        if state_store and resolved.enabled:
            resolved = _wrap_with_state_recording(resolved, state_store._path)

        existing = await scheduler.status(resolved.name)
        if existing is not None:
            on_dupe = config.get("on_duplicate", "replace")
            if on_dupe == "fail":
                raise CronBackendError(
                    f"cron job '{resolved.name}' already exists; "
                    "set cron.on_duplicate to 'replace' to overwrite"
                )
            await scheduler.unschedule(resolved.name)
        await scheduler.schedule(resolved)
        ext._jobs[resolved.name] = resolved

    return ext


# ── helpers ──────────────────────────────────────────────────────────


def _make_state_store(config: dict[str, Any], app_dir: Path | None) -> CronStateStore | None:
    if app_dir is None:
        return None
    state_cfg = config.get("state", {})
    if isinstance(state_cfg, dict):
        explicit = state_cfg.get("path")
        if explicit:
            return CronStateStore(Path(explicit))
    return CronStateStore(app_dir / ".pyxen" / "cron-state.jsonl")


def _parse_manifest_jobs(jobs_raw: list[Any]) -> list[CronJob]:
    from .models import CronJob

    result: list[CronJob] = []
    for idx, raw in enumerate(jobs_raw):
        if not isinstance(raw, dict):
            raise CronBackendError(f"cron job at index {idx} must be a JSON object")
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise CronBackendError(f"cron job at index {idx} is missing a string 'name'")
        command = raw.get("command")
        if not isinstance(command, str) or not command:
            raise CronBackendError(f"cron job at index {idx} is missing a string 'command'")
        schedule = raw.get("schedule")
        if not isinstance(schedule, str) or not schedule:
            raise CronBackendError(f"cron job at index {idx} is missing a string 'schedule'")
        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise CronBackendError(f"cron job '{name}': 'enabled' must be a boolean")
        env = raw.get("environment", {})
        if not isinstance(env, dict):
            raise CronBackendError(f"cron job '{name}': 'environment' must be a JSON object")
        result.append(CronJob(
            name=name, command=command, schedule=schedule,
            enabled=enabled, environment=env,
        ))
    return result


def _resolve_cron_command(job: CronJob, app_dir: Path | None) -> CronJob:
    if app_dir is None or "{APP_DIR}" not in job.command:
        return job
    resolved = job.command.replace("{APP_DIR}", str(app_dir))
    return CronJob(
        name=job.name, command=resolved, schedule=job.schedule,
        enabled=job.enabled, environment=job.environment,
    )


def _wrap_with_state_recording(job: CronJob, state_path: Path) -> CronJob:
    python = sys.executable
    record_mod = "pyxen.core.ext.cron.record"
    sq = _sh_quote
    prefix = (
        f"{python} -m {record_mod} start {sq(job.name)} {sq(str(state_path))}"
        f" && "
    )
    suffix = (
        f" ; EXIT=$? ; "
        f"{python} -m {record_mod} end {sq(job.name)} {sq(str(state_path))} $EXIT"
        f" ; exit $EXIT"
    )
    return CronJob(
        name=job.name, command=prefix + job.command + suffix,
        schedule=job.schedule, enabled=job.enabled,
        environment=job.environment,
    )


def _sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _main() -> None:
    """Unit tests for the cron extension init logic."""
    import asyncio
    import json
    import tempfile

    async def go() -> None:
        # init with empty config returns None
        ext = await init({}, None)
        assert ext is None

        # init with no jobs returns None
        ext2 = await init({"jobs": []}, None)
        assert ext2 is None

        # init creates CronExtension when crontab available
        ext3 = await init({"jobs": [{"name": "t", "command": "echo hi", "schedule": "* * * * *"}]}, Path("/tmp"))
        # ext3 may be None if no crontab on this machine
        if ext3 is not None:
            jobs = await ext3.list()
            assert len(jobs) == 1
            assert jobs[0].name == "t"
            await ext3.unschedule("t")

        # _resolve_cron_command replaces {APP_DIR}
        src_dir = Path(__file__).resolve().parent
        job_in = CronJob(name="t", command="bash {APP_DIR}/scripts/t.sh", schedule="* * * * *")
        job_out = _resolve_cron_command(job_in, src_dir)
        assert "{APP_DIR}" not in job_out.command
        assert str(src_dir) in job_out.command

        # _wrap_with_state_recording wraps the command
        job_raw = CronJob(name="test-job", command="/usr/bin/backup.sh", schedule="0 3 * * *")
        wrapped = _wrap_with_state_recording(job_raw, Path("/tmp/state.jsonl"))
        assert "pyxen.core.ext.cron.record" in wrapped.command
        assert "/usr/bin/backup.sh" in wrapped.command
        assert wrapped.schedule == job_raw.schedule

        # _sh_quote handles simple and tricky strings
        assert _sh_quote("hello") == "'hello'"
        assert _sh_quote("it's") == "'it'\\''s'"

        # _make_state_store uses custom path from config
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            s1 = _make_state_store({}, app_dir)
            assert s1 is not None
            assert str(app_dir / ".pyxen" / "cron-state.jsonl") in str(s1._path)

            s2 = _make_state_store({"state": {"path": "/custom/state.jsonl"}}, app_dir)
            assert s2 is not None
            assert str(s2._path) == "/custom/state.jsonl"

            s3 = _make_state_store({}, None)
            assert s3 is None

    asyncio.run(go())


if __name__ == "__main__":
    _main()
