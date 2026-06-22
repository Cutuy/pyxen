from __future__ import annotations


class CronError(Exception):
    ...


class CronBackendError(CronError):
    ...


class CronScheduleError(CronError):
    ...


def _main() -> None:
    from pyxen._testlib import run_tests

    def test_cronerror_base() -> None:
        err = CronError("base")
        assert isinstance(err, Exception)
        assert "base" in str(err)

    def test_cronbackenderror_inheritance() -> None:
        backend_err = CronBackendError("backend")
        assert isinstance(backend_err, CronError)
        assert issubclass(CronBackendError, CronError)

    def test_cronscheduleerror_inheritance() -> None:
        sched_err = CronScheduleError("bad expr")
        assert isinstance(sched_err, CronError)
        assert issubclass(CronScheduleError, CronError)

    run_tests(
        test_cronerror_base,
        test_cronbackenderror_inheritance,
        test_cronscheduleerror_inheritance,
    )


if __name__ == "__main__":
    _main()
