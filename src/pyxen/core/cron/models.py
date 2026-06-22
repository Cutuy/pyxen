from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CronJob:
    name: str
    command: str
    schedule: str
    enabled: bool = True
    environment: dict[str, str] = field(default_factory=dict)


@dataclass
class CronStatus:
    name: str
    enabled: bool
    active: bool
    next_run: str | None = None
    last_run: str | None = None
    last_result: str | None = None


def _main() -> None:
    job = CronJob(name="test", command="echo hi", schedule="0 * * * *")
    assert job.name == "test"
    assert job.command == "echo hi"
    assert job.schedule == "0 * * * *"
    assert job.enabled is True
    assert job.environment == {}

    job2 = CronJob(
        name="backup",
        command="/usr/bin/backup.sh",
        schedule="@daily",
        environment={"PATH": "/usr/bin"},
    )
    assert job2.name == "backup"
    assert job2.environment == {"PATH": "/usr/bin"}

    status = CronStatus(name="test", enabled=True, active=False)
    assert status.name == "test"
    assert status.enabled is True
    assert status.active is False

    status.next_run = "2025-01-01 00:00:00"
    assert status.next_run == "2025-01-01 00:00:00"
    status.last_run = "2024-12-31 23:59:00"
    assert status.last_run == "2024-12-31 23:59:00"

    # Frozen dataclass — can't mutate
    try:
        job.name = "changed"  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("CronJob should be frozen")

    # CronStatus equality
    s1 = CronStatus(name="a", enabled=True, active=False)
    s2 = CronStatus(name="a", enabled=True, active=False)
    assert s1 == s2


if __name__ == "__main__":
    _main()
