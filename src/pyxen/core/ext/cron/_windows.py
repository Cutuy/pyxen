from __future__ import annotations

import asyncio
import shutil
import subprocess

from .errors import CronBackendError, CronScheduleError
from .models import CronJob, CronStatus

_WD_NAMES = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
_WD_MAP = {"sun": 0, "mon": 1, "tue": 2, "wed": 3,
           "thu": 4, "fri": 5, "sat": 6}


def probe() -> bool:
    if shutil.which("schtasks") is None:
        return False
    try:
        subprocess.run(
            ["schtasks", "/query", "/tn", "pyxen_probe"],
            capture_output=True,
            timeout=10,
        )
        return True
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


async def schedule(job: CronJob) -> None:
    args = _build_schtasks_args(job)
    proc = await asyncio.create_subprocess_exec(
        "schtasks", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise CronBackendError(
            f"schtasks /create failed for {job.name}: "
            f"{stderr.decode(errors='replace').strip()}"
        )


async def unschedule(name: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "schtasks", "/delete", "/tn", f"pyxen.{name}", "/f",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


async def list_jobs() -> list[CronJob]:
    proc = await asyncio.create_subprocess_exec(
        "schtasks", "/query", "/fo", "CSV", "/v",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return []

    jobs: list[CronJob] = []
    for line in stdout.decode(errors="replace").splitlines()[1:]:
        if "pyxen." in line:
            parts = line.split(",")
            if len(parts) >= 2:
                taskname = parts[0].strip('"')
                if taskname.startswith("pyxen."):
                    name = taskname[len("pyxen."):]
                    jobs.append(CronJob(name=name, command="", schedule=""))
    return jobs


async def status(name: str) -> CronStatus | None:
    proc = await asyncio.create_subprocess_exec(
        "schtasks", "/query", "/tn", f"pyxen.{name}", "/fo", "CSV", "/v",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    return CronStatus(name=name, enabled=True, active=True)


def _build_schtasks_args(job: CronJob) -> list[str]:
    taskname = f"pyxen.{job.name}"
    schedule_type, mods = _cron_to_schtasks(job.schedule)

    args: list[str] = [
        "/create", "/tn", taskname, "/tr", job.command,
        "/sc", schedule_type, "/f",
    ]

    if mods.get("mo") is not None:
        args.extend(["/mo", str(mods["mo"])])
    if mods.get("st") is not None:
        args.extend(["/st", str(mods["st"])])
    if mods.get("d") is not None:
        args.extend(["/d", str(mods["d"])])

    return args


def _cron_to_schtasks(expr: str) -> tuple[str, dict[str, object]]:
    expr = expr.strip()

    shorthands: dict[str, tuple[str, dict[str, object]]] = {
        "@reboot": ("ONSTART", {}),
        "@yearly": ("YEARLY", {"mo": 1}),
        "@annually": ("YEARLY", {"mo": 1}),
        "@monthly": ("MONTHLY", {"mo": 1}),
        "@weekly": ("WEEKLY", {"d": "SUN"}),
        "@daily": ("DAILY", {}),
        "@midnight": ("DAILY", {}),
        "@hourly": ("HOURLY", {}),
    }

    if expr in shorthands:
        return shorthands[expr]

    parts = expr.split()
    if len(parts) != 5:
        raise CronScheduleError(f"invalid cron expression: {expr!r}")

    minute, hour, day, month, weekday = parts

    if hour != "*" and minute != "*" and day == "*" and weekday == "*":
        return "DAILY", {"st": f"{hour.zfill(2)}:{minute.zfill(2)}"}

    if weekday != "*" and day == "*" and month == "*":
        wd_idx = _WD_MAP.get(weekday.lower())
        if wd_idx is None and weekday.isdigit():
            wd_idx = int(weekday)
        if wd_idx is not None and 0 <= wd_idx <= 6:
            st = f"{hour.zfill(2) if hour != '*' else '00'}:{minute.zfill(2) if minute != '*' else '00'}"
            return "WEEKLY", {"d": _WD_NAMES[wd_idx], "st": st}

    if minute.startswith("*/"):
        return "HOURLY", {}

    if hour == "*" and minute != "*":
        return "HOURLY", {}

    return "DAILY", {"st": "00:00"}


def _main() -> None:
    from pyxen._testlib import run_tests

    def test_build_schtasks_args_daily() -> None:
        job = CronJob(name="test", command="echo hi", schedule="@daily")
        args = _build_schtasks_args(job)
        assert "/tn" in args
        assert "pyxen.test" in args
        assert "/sc" in args
        assert "DAILY" in args

    def test_build_schtasks_args_reboot() -> None:
        job2 = CronJob(name="test", command="echo hi", schedule="@reboot")
        args2 = _build_schtasks_args(job2)
        assert "ONSTART" in args2

    def test_cron_to_schtasks_daily() -> None:
        sc, mods = _cron_to_schtasks("30 4 * * *")
        assert sc == "DAILY"
        assert mods.get("st") == "04:30"

    def test_cron_to_schtasks_hourly() -> None:
        sc2, mods2 = _cron_to_schtasks("@hourly")
        assert sc2 == "HOURLY"

    def test_cron_to_schtasks_weekly() -> None:
        sc3, mods3 = _cron_to_schtasks("0 9 * * 1")
        assert sc3 == "WEEKLY"
        assert mods3.get("d") == "MON"
        assert mods3.get("st") == "09:00"

    def test_cron_to_schtasks_hourly_step() -> None:
        sc4, mods4 = _cron_to_schtasks("*/10 * * * *")
        assert sc4 == "HOURLY"

    def test_cron_to_schtasks_zero_hour() -> None:
        sc5, mods5 = _cron_to_schtasks("0 * * * *")
        assert sc5 == "HOURLY"

    def test_cron_to_schtasks_weekly_shorthand() -> None:
        sc6, mods6 = _cron_to_schtasks("@weekly")
        assert sc6 == "WEEKLY"

    def test_cron_to_schtasks_bad_expression() -> None:
        try:
            _cron_to_schtasks("bad")
        except CronScheduleError:
            pass
        else:
            raise AssertionError("expected CronScheduleError")

    def test_probe_return_type() -> None:
        result = probe()
        assert isinstance(result, bool)

    run_tests(
        test_build_schtasks_args_daily,
        test_build_schtasks_args_reboot,
        test_cron_to_schtasks_daily,
        test_cron_to_schtasks_hourly,
        test_cron_to_schtasks_weekly,
        test_cron_to_schtasks_hourly_step,
        test_cron_to_schtasks_zero_hour,
        test_cron_to_schtasks_weekly_shorthand,
        test_cron_to_schtasks_bad_expression,
        test_probe_return_type,
    )


if __name__ == "__main__":
    _main()
