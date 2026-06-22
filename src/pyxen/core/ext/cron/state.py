from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .models import CronStatus


@dataclass
class CronRun:
    name: str
    action: Literal["start", "end"]
    timestamp: float
    pid: int | None = None
    exit_code: int | None = None


class CronStateStore:
    """Persists cron job execution history to a JSON Lines file.

    Each invocation writes two lines (start / end) so the runtime
    can answer "did my heartbeat actually run?" without the app
    doing its own logging.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record_start(self, name: str) -> None:
        run = CronRun(name=name, action="start", timestamp=time.time(), pid=None)
        with open(self._path, "a") as f:
            f.write(_encode(run) + "\n")

    def record_end(self, name: str, exit_code: int) -> None:
        run = CronRun(
            name=name, action="end", timestamp=time.time(),
            pid=None, exit_code=exit_code,
        )
        with open(self._path, "a") as f:
            f.write(_encode(run) + "\n")

    def last_run(self, name: str) -> CronRun | None:
        """Return the most recent *end* event for *name*, or ``None``."""
        best: CronRun | None = None
        for run in self._iter():
            if run.name == name and run.action == "end":
                if best is None or run.timestamp > best.timestamp:
                    best = run
        return best

    def last_start(self, name: str) -> CronRun | None:
        """Return the most recent *start* event for *name*, or ``None``."""
        best: CronRun | None = None
        for run in self._iter():
            if run.name == name and run.action == "start":
                if best is None or run.timestamp > best.timestamp:
                    best = run
        return best

    def history(self, name: str, limit: int = 10) -> list[CronRun]:
        """Return the most recent runs for *name* (start+end pairs flattened)."""
        all_runs = [r for r in self._iter() if r.name == name]
        all_runs.sort(key=lambda r: r.timestamp, reverse=True)
        return all_runs[:limit]

    def status(self, name: str) -> CronStatus | None:
        """Build a ``CronStatus`` for *name* from stored history alone.

        Returns ``None`` if nothing has ever been recorded for *name*.
        """
        end = self.last_run(name)
        start = self.last_start(name)
        if end is None and start is None:
            return None
        last_ts = end.timestamp if end else (start.timestamp if start else 0)
        return CronStatus(
            name=name,
            enabled=True,
            active=(start is not None and (end is None or start.timestamp > end.timestamp)),
            last_run=_fmt_ts(last_ts),
            last_result=str(end.exit_code) if end and end.exit_code is not None else None,
        )

    def _iter(self) -> Iterator[CronRun]:
        if not self._path.is_file():
            return
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield _decode(line)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue


def _encode(run: CronRun) -> str:
    return json.dumps({
        "name": run.name,
        "a": run.action,
        "t": run.timestamp,
        "p": run.pid,
        "e": run.exit_code,
    }, separators=(",", ":"), sort_keys=True)


def _decode(line: str) -> CronRun:
    d = json.loads(line)
    return CronRun(
        name=d["name"],
        action=d["a"],
        timestamp=d["t"],
        pid=d.get("p"),
        exit_code=d.get("e"),
    )


def _fmt_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _main() -> None:
    from pyxen._testlib import run_tests
    import tempfile
    from pathlib import Path

    def test_empty_store_returns_none() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cron-state.jsonl"
            store = CronStateStore(p)
            s = store.status("backup")
            assert s is None, "empty store should return None"

    def test_record_start_end() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cron-state.jsonl"
            store = CronStateStore(p)
            store.record_start("backup")
            store.record_end("backup", 0)
            store.record_start("heartbeat")
            store.record_end("heartbeat", 1)

            s = store.status("backup")
            assert s is not None
            assert s.last_result == "0"

            s2 = store.status("heartbeat")
            assert s2 is not None
            assert s2.last_result == "1"

    def test_history() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cron-state.jsonl"
            store = CronStateStore(p)
            store.record_start("backup")
            store.record_end("backup", 0)
            hist = store.history("backup")
            assert len(hist) == 2

    def test_active_status() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cron-state.jsonl"
            store = CronStateStore(p)
            store.record_start("longjob")
            s3 = store.status("longjob")
            assert s3 is not None
            assert s3.active is True
            assert s3.last_result is None

    run_tests(
        test_empty_store_returns_none,
        test_record_start_end,
        test_history,
        test_active_status,
    )


if __name__ == "__main__":
    _main()
