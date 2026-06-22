# cron_app

Demonstrates declarative cron scheduling. Declare jobs in `runtime.json`;
the runtime auto-schedules them on startup. App code never touches a
scheduler API.

## Run

```bash
PYTHONPATH=src python examples/cron_app/main.py
```

## `{APP_DIR}`

The `command` field supports `{APP_DIR}`, resolved to the directory
containing `runtime.json` at schedule time. This lets you reference scripts
inside your app tree without hardcoding paths.

```json
{"name": "heartbeat", "command": "bash {APP_DIR}/scripts/heartbeat.sh", "schedule": "*/5 * * * *"}
```

## Clean up

```bash
crontab -e                                    # Linux/macOS
schtasks /delete /tn pyxen-example-* /f       # Windows
```
