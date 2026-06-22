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
    from pyxen._testlib import run_tests

    def test_cron_job_basic() -> None:
        job = CronJob(name="test", command="echo hi", schedule="0 * * * *")
        assert job.name == "test"
        assert job.command == "echo hi"
        assert job.schedule == "0 * * * *"
        assert job.enabled is True
        assert job.environment == {}

    def test_cron_job_with_env() -> None:
        job2 = CronJob(
            name="backup",
            command="/usr/bin/backup.sh",
            schedule="@daily",
            environment={"PATH": "/usr/bin"},
        )
        assert job2.name == "backup"
        assert job2.environment == {"PATH": "/usr/bin"}

    def test_cron_status_basic() -> None:
        status = CronStatus(name="test", enabled=True, active=False)
        assert status.name == "test"
        assert status.enabled is True
        assert status.active is False

    def test_cron_status_next_run() -> None:
        status = CronStatus(name="test", enabled=True, active=False)
        status.next_run = "2025-01-01 00:00:00"
        assert status.next_run == "2025-01-01 00:00:00"
        status.last_run = "2024-12-31 23:59:00"
        assert status.last_run == "2024-12-31 23:59:00"

    def test_cron_job_frozen() -> None:
        job = CronJob(name="test", command="echo hi", schedule="0 * * * *")
        try:
            job.name = "changed"  # type: ignore[misc]
        except AttributeError:
            pass
        else:
            raise AssertionError("CronJob should be frozen")

    def test_cron_status_equality() -> None:
        s1 = CronStatus(name="a", enabled=True, active=False)
        s2 = CronStatus(name="a", enabled=True, active=False)
        assert s1 == s2

    run_tests(
        test_cron_job_basic,
        test_cron_job_with_env,
        test_cron_status_basic,
        test_cron_status_next_run,
        test_cron_job_frozen,
        test_cron_status_equality,
    )


if __name__ == "__main__":
    _main()
