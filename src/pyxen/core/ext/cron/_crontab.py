from __future__ import annotations

import asyncio
import shutil
import subprocess

from .errors import CronBackendError
from .models import CronJob, CronStatus

_MARKER_PREFIX = "# pyxen:"


def probe() -> bool:
    if shutil.which("crontab") is None:
        return False
    try:
        subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            timeout=10,
        )
        return True
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


async def schedule(job: CronJob) -> None:
    env_prefix = " ".join(
        f"{k}={v}" for k, v in sorted(job.environment.items())
    )
    if env_prefix:
        env_prefix += " "

    line = f"{job.schedule} {env_prefix}{job.command} {_MARKER_PREFIX}{job.name}\n"

    if job.enabled:
        await _crontab_add_line(line)
    else:
        await _crontab_add_line(f"# {line}")


async def unschedule(name: str) -> None:
    marker = f"{_MARKER_PREFIX}{name}"
    await _crontab_remove_marker(marker)


async def list_jobs() -> list[CronJob]:
    lines = await _crontab_read()
    jobs: list[CronJob] = []
    for line in lines:
        entry = _parse_entry(line.strip())
        if entry:
            jobs.append(entry)
    return jobs


async def status(name: str) -> CronStatus | None:
    lines = await _crontab_read()
    enabled_marker = f"{_MARKER_PREFIX}{name}"
    disabled_marker = f"# {_MARKER_PREFIX}{name}"

    for line in lines:
        stripped = line.strip()
        if stripped.endswith(enabled_marker):
            return CronStatus(name=name, enabled=True, active=True)
        if disabled_marker in stripped:
            return CronStatus(name=name, enabled=False, active=False)

    return None


def _parse_entry(line: str) -> CronJob | None:
    if not line or line.startswith("#"):
        return None

    marker_idx = line.find(_MARKER_PREFIX)
    if marker_idx == -1:
        return None

    name = line[marker_idx + len(_MARKER_PREFIX):].strip()

    before_marker = line[:marker_idx].strip()
    parts = before_marker.split()
    if len(parts) < 2:
        return None

    if parts[0].startswith("@"):
        schedule = parts[0]
        command = " ".join(parts[1:])
    elif len(parts) >= 6:
        schedule = " ".join(parts[:5])
        command = " ".join(parts[5:])
    else:
        return None

    return CronJob(name=name, command=command, schedule=schedule, enabled=True)


async def _crontab_read() -> list[str]:
    proc = await asyncio.create_subprocess_exec(
        "crontab", "-l",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        if "no crontab" in stderr.decode(errors="replace").lower():
            return []
        raise CronBackendError(
            f"crontab -l failed: {stderr.decode(errors='replace').strip()}"
        )
    return stdout.decode(errors="replace").splitlines()


async def _crontab_write(lines: list[str]) -> None:
    content = "\n".join(lines)
    if content and not content.endswith("\n"):
        content += "\n"
    proc = await asyncio.create_subprocess_exec(
        "crontab", "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(content.encode("utf-8"))
    if proc.returncode != 0:
        raise CronBackendError(
            f"crontab write failed: {stderr.decode(errors='replace').strip()}"
        )


async def _crontab_add_line(line: str) -> None:
    existing = await _crontab_read()
    marker = f"{_MARKER_PREFIX}{line.rsplit(_MARKER_PREFIX, 1)[1].strip()}"

    cleaned: list[str] = []
    for line in existing:
        if marker.strip("# ") not in line:
            cleaned.append(line)
    cleaned.append(line.rstrip("\n"))
    await _crontab_write(cleaned)


async def _crontab_remove_marker(marker: str) -> None:
    existing = await _crontab_read()
    cleaned = [line for line in existing if marker not in line]
    await _crontab_write(cleaned)


def _main() -> None:
    import asyncio

    entry = _parse_entry(
        "0 9 * * * /usr/bin/backup.sh # pyxen:backup"
    )
    assert entry is not None
    assert entry.name == "backup"
    assert entry.schedule == "0 9 * * *"
    assert entry.command == "/usr/bin/backup.sh"
    assert entry.enabled is True

    entry2 = _parse_entry(
        "*/5 * * * * echo hi # pyxen:greet"
    )
    assert entry2 is not None
    assert entry2.schedule == "*/5 * * * *"
    assert entry2.command == "echo hi"

    entry3 = _parse_entry(
        "0 9 * * 1 /bin/ls -la /tmp # pyxen:cleanup"
    )
    assert entry3 is not None
    assert entry3.command == "/bin/ls -la /tmp"

    entry4 = _parse_entry(
        "@daily /bin/run.sh # pyxen:daily_task"
    )
    assert entry4 is not None
    assert entry4.schedule == "@daily"
    assert entry4.command == "/bin/run.sh"

    assert _parse_entry("# comment") is None
    assert _parse_entry("") is None
    assert _parse_entry("no marker here") is None

    result = probe()
    assert isinstance(result, bool)

    async def go() -> None:
        s = await status("nonexistent")
        assert s is None

    asyncio.run(go())


if __name__ == "__main__":
    _main()
