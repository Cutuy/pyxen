#!/usr/bin/env bash
# Heartbeat script — writes a timestamp to /tmp.
# Scheduled by the cron_app example via pyxen's {APP_DIR} resolution.
set -euo pipefail
echo "$(date -u -Iseconds) pyxen-cron-app heartbeat ok" >> /tmp/pyxen-heartbeat.log
