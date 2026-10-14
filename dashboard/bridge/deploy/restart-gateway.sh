#!/bin/bash
# Run as root by hermes-dash-restart.service when the dashboard asks for a gateway restart (the page drops
# /data/.hermes/hermes-dash/restart.request; hermes-dash-restart.path notices it). The bridge itself never gets root.
# Hands over to restart_when_quiet.sh, which refuses while the gateway is busy (a card running, a recent message).
# Installed root-owned in /usr/local/lib/hermes-dash/ so the hermes user cannot change what root runs.
set -uo pipefail
STATE=/data/.hermes/hermes-dash
HERE=/usr/local/lib/hermes-dash

status() {
  python3 -I -c 'import json, sys, time; json.dump({"at": int(time.time()), "state": sys.argv[1], "message": sys.argv[2]}, open(sys.argv[3], "w"))' \
    "$1" "$2" "$STATE/restart.status"
  chown hermes:hermes "$STATE/restart.status"
}

rm -f "$STATE/restart.request"
status running "Checking that nothing is in progress"

out=$("$HERE/restart_when_quiet.sh" 2>&1); rc=$?
case $rc in
  0) status done "$(printf '%s\n' "$out" | tail -1)" ;;
  2) status refused "$(printf '%s\n' "$out" | head -1)" ;;
  *) status failed "$(printf '%s\n' "$out" | grep -v '^[[:space:]]*$' | tail -1 | cut -c1-200)" ;;
esac
exit 0
