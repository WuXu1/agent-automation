#!/bin/bash
# Run as root by hermes-dash-backup.service when the dashboard asks for a backup now (the page drops
# /data/.hermes/hermes-dash/backup.request; hermes-dash-backup.path notices it). Starts the same unit the nightly timer
# starts (hermes-backup.service: encrypted, to Google Drive) and returns at once; the page reads the unit's state.
# Installed root-owned in /usr/local/lib/hermes-dash/ so the hermes user cannot change what root runs.
set -uo pipefail
STATE=/data/.hermes/hermes-dash

status() {
  python3 -I -c 'import json, sys, time; json.dump({"at": int(time.time()), "state": sys.argv[1], "message": sys.argv[2]}, open(sys.argv[3], "w"))' \
    "$1" "$2" "$STATE/backup.status"
  chown hermes:hermes "$STATE/backup.status"
}

rm -f "$STATE/backup.request"
if systemctl is-active --quiet hermes-backup.service; then
  status refused "A backup is running already"
  exit 0
fi
if systemctl start --no-block hermes-backup.service; then
  status started "Backup started"
else
  status failed "systemd would not start hermes-backup.service"
fi
exit 0
