# cron_app

Demonstrates pyxen's declarative cron job scheduling. The app declares cron jobs
in `runtime.json` — the runtime auto-schedules them via the OS-native backend on
startup. The app code never touches a scheduler API.

## What it does

1. Loads `runtime.json` which declares two cron jobs:
   - `pyxen-example-heartbeat` — runs `heartbeat.sh` every 5 minutes, writing a timestamp to `/tmp`
   - `pyxen-example-cleanup` — removes stale heartbeat files every hour
2. The runtime auto-schedules both jobs via `crontab` (Linux/macOS) or `schtasks` (Windows)
3. The app verifies the jobs are scheduled and prints a summary

## Run

From the repo root:

```bash
PYTHONPATH=src python examples/cron_app/main.py
```

Expected output (with crontab available):

```
loaded runtime for anonymous (version=1)
cron.on_duplicate = replace
declared 2 cron job(s):
  backend: crontab
  [scheduled] pyxen-example-heartbeat: */5 * * * * → bash examples/cron_app/heartbeat.sh
  [scheduled] pyxen-example-cleanup: 0 * * * * → find /tmp -name 'pyxen-heartbeat-*' ...
  2 pyxen-example job(s) active in crontab
```

If no cron backend is available (e.g. in a container), the app prints a note and exits cleanly.

## Clean up

```bash
# Linux/macOS — remove the pyxen-example lines from your crontab
crontab -e

# Windows
schtasks /delete /tn pyxen-example-heartbeat /f
schtasks /delete /tn pyxen-example-cleanup /f
```
