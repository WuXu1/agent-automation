#!/bin/bash
# Restart hermes-gateway only when it is idle; then wait until it is serving again.
# Run on the VM as root (the dashboard's restart helper) or as an admin user with sudo.
# Exit 2 = not quiet, try again later. With --check: only report.
set -uo pipefail
running=$(sudo -u hermes -i hermes kanban list < /dev/null 2>/dev/null | grep -c ' running ' || true)
if [ "$running" != "0" ]; then echo "not quiet: $running kanban card(s) running"; exit 2; fi
last5=$(sudo awk -v since="$(date -d '-5 min' '+%Y-%m-%d %H:%M:%S')" 'substr($0,1,19) >= since' /data/.hermes/logs/gateway.log 2>/dev/null | grep -cE 'Sending response|inbound message|Processing message' || true)
if [ "${last5:-0}" != "0" ]; then echo "not quiet: $last5 message event(s) in the last 5 minutes"; exit 2; fi
if [ "${1:-}" = "--check" ]; then echo "quiet"; exit 0; fi
echo "quiet; restarting hermes-gateway"
# Hermes only sends its "Gateway online" notice after a restart it knows was planned (this marker). Without it a
# plain systemctl restart sends only the "shutting down" notice and never the "back" one.
sudo -u hermes bash -c 'printf "{\"requested_at\": %s, \"via_service\": true, \"detached\": false}" "$(date +%s)" > /data/.hermes/.restart_pending.json'
sudo systemctl restart hermes-gateway
for i in $(seq 1 24); do
  sleep 5
  if systemctl is-active --quiet hermes-gateway && curl -s -m 3 127.0.0.1:8642/health >/dev/null 2>&1; then
    echo "gateway up and API answering after $((i*5))s"; exit 0
  fi
done
echo "gateway did not come back with the API within 120s"; sudo journalctl -u hermes-gateway -n 40 --no-pager; exit 1
