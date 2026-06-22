from __future__ import annotations


class CronError(Exception):
    ...


class CronBackendError(CronError):
    ...


class CronScheduleError(CronError):
    ...


def _main() -> None:
    err = CronError("base")
    assert isinstance(err, Exception)
    assert "base" in str(err)

    backend_err = CronBackendError("backend")
    assert isinstance(backend_err, CronError)

    sched_err = CronScheduleError("bad expr")
    assert isinstance(sched_err, CronError)

    assert issubclass(CronBackendError, CronError)
    assert issubclass(CronScheduleError, CronError)


if __name__ == "__main__":
    _main()
