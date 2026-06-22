from __future__ import annotations

import contextlib
import importlib
import sys
from typing import Any, cast

from .errors import CronBackendError
from .models import CronJob, CronStatus


class CronScheduler:
    def __init__(self, backend: str | None = None) -> None:
        self._backend_name = backend if backend is not None else _detect_platform()
        self._backend: Any = _load_backend(self._backend_name)

    @property
    def backend(self) -> str:
        return self._backend_name

    async def schedule(self, job: CronJob) -> None:
        await self._backend.schedule(job)

    async def unschedule(self, name: str) -> None:
        await self._backend.unschedule(name)

    async def list(self) -> list[CronJob]:
        return cast(list[CronJob], await self._backend.list_jobs())

    async def status(self, name: str) -> CronStatus | None:
        return cast(CronStatus | None, await self._backend.status(name))


def _detect_platform() -> str:
    platform = sys.platform
    backends: list[str]

    if platform in ("linux", "darwin"):
        backends = ["crontab"]
    elif platform == "win32":
        backends = ["windows"]
    else:
        backends = ["crontab", "windows"]

    for name in backends:
        with contextlib.suppress(Exception):
            mod = _import_backend_module(f"_{name}")
            if mod.probe():
                return name

    raise CronBackendError(
        f"no supported cron backend found on {platform}. "
        "Linux/macOS require crontab, Windows requires schtasks.exe."
    )


def _import_backend_module(name: str) -> Any:
    return importlib.import_module(f".{name}", __package__)


def _load_backend(name: str) -> Any:
    try:
        mod = _import_backend_module(f"_{name}")
    except (ImportError, ModuleNotFoundError) as exc:
        raise CronBackendError(
            f"cron backend {name!r} not found: {exc}"
        ) from exc
    for attr in ("probe", "schedule", "unschedule", "list_jobs", "status"):
        if not hasattr(mod, attr):
            raise CronBackendError(
                f"cron backend {name!r} is missing required '{attr}'"
            )
    return mod


def _main() -> None:
    import asyncio
    import contextlib

    sched = CronScheduler(backend="crontab")
    assert sched.backend == "crontab"

    sched2 = CronScheduler(backend="windows")
    assert sched2.backend == "windows"

    try:
        CronScheduler(backend="nonexistent")
    except CronBackendError:
        pass
    else:
        raise AssertionError("expected CronBackendError for unknown backend")

    with contextlib.suppress(CronBackendError):
        _detect_platform()

    async def go() -> None:
        sched = CronScheduler(backend="crontab")
        assert sched.backend == "crontab"

    asyncio.run(go())


if __name__ == "__main__":
    _main()
