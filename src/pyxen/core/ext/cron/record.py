"""CLI entry point: ``python -m pyxen.core.ext.cron.record <start|end> <name> <state-file> [exit-code]``

Called by wrapped cron job commands to log execution to the state file.

Example crontab entry (after wrapping)::

    */5 * * * * python -m pyxen.core.ext.cron.record start backup /tmp/app-cron.jsonl && /usr/bin/backup.sh ; EXIT=$? ; python -m pyxen.core.ext.cron.record end backup /tmp/app-cron.jsonl $EXIT ; exit $EXIT
"""

from __future__ import annotations

import sys

from .state import CronStateStore


def _main() -> None:
    if len(sys.argv) < 4:
        print("Usage: python -m pyxen.core.ext.cron.record <start|end> <name> <state-file> [exit-code]", file=sys.stderr)
        sys.exit(1)

    action = sys.argv[1]
    name = sys.argv[2]
    state_file = sys.argv[3]

    store = CronStateStore(state_file)

    if action == "start":
        store.record_start(name)
    elif action == "end":
        exit_code = int(sys.argv[4]) if len(sys.argv) > 4 else 0
        store.record_end(name, exit_code)
    else:
        print(f"Unknown action: {action}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _main()
