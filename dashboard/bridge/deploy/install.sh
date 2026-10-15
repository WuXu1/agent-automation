#!/usr/bin/env bash
# Install (or update) the Command Center dashboard on the VM, and publish it tailnet-only.
#   sudo bash <kit>/dashboard/bridge/deploy/install.sh          install or update, no questions asked
#   sudo bash <kit>/dashboard/bridge/deploy/install.sh --undo   remove the services and the Tailscale address
#
# Needs: the kit's checkout with the prebuilt page (dashboard/dist/), Hermes and Mem0 installed, /data/.hermes/crew.json
# (written by the kit's installer), python3, curl and a signed-in tailscale. Restarts nothing but its own service; the
# restart helper it installs runs only when the page asks, and only through restart_when_quiet.sh.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"          # <kit>/dashboard/bridge
DIST="$(cd "$SRC/.." && pwd)/dist"                # <kit>/dashboard/dist
DEST=/data/tools/hermes-dash
STATE=/data/.hermes/hermes-dash
CREW=/data/.hermes/crew.json
UNIT=/etc/systemd/system/hermes-dash.service
HELPERS=/usr/local/lib/hermes-dash
PORT=8890
TS_PORT=8444
MEM0_ENV=/data/.hermes/mem0-server/server.env

die() { echo "install: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run with sudo"

if [ "${1:-}" = "--undo" ]; then
  tailscale serve --https="$TS_PORT" off 2>/dev/null || true
  systemctl disable --now hermes-dash hermes-dash-restart.path hermes-dash-jobs.path hermes-dash-backup.path 2>/dev/null || true
  rm -f "$UNIT" /etc/systemd/system/hermes-dash-{restart,jobs,backup}.{path,service}
  rm -rf "$HELPERS"
  systemctl daemon-reload
  echo "Removed the hermes-dash service and its Tailscale address (port $TS_PORT)."
  echo "Kept $DEST and $STATE; delete them by hand if you want them gone."
  exit 0
fi

# -- checks before anything changes -------------------------------------------------------------------------------------
[ -f "$DIST/index.html" ] || die "$DIST/index.html missing: the kit ships the page prebuilt; is the checkout complete?"
for f in bridge.py crew.py feeds.py actions.py registry.py registry.json deploy/restart-gateway.sh deploy/restart_when_quiet.sh deploy/backup-now.sh deploy/hermes-dash.service; do
  [ -f "$SRC/$f" ] || die "$f missing in $SRC"
done
id hermes >/dev/null 2>&1 || die "there is no 'hermes' user: install Hermes first"
[ -f "$MEM0_ENV" ] || die "$MEM0_ENV missing: is Mem0 installed?"
command -v tailscale >/dev/null || die "tailscale is not installed"
systemctl is-active --quiet mem0-server || echo "install: warning: mem0-server is not running; the page will say so"
[ -f "$CREW" ] || echo "install: warning: $CREW missing; the page will use plain names (Chief, Tutor, ...) until the kit writes it"

PY_FILES=()
for f in "$SRC"/*.py; do PY_FILES+=("$f"); done
for f in "${PY_FILES[@]}"; do
  /usr/bin/python3 -I -c "import ast, sys; ast.parse(open(sys.argv[1]).read())" "$f" || die "$(basename "$f") does not parse"
done
/usr/bin/python3 -I -c "import json, sys; json.load(open(sys.argv[1]))" "$SRC/registry.json" || die "registry.json is not valid JSON"

# -- the bridge and the page ----------------------------------------------------------------------------------------------
umask 022
install -d -o hermes -g hermes -m 755 "$DEST"
install -o hermes -g hermes -m 644 "${PY_FILES[@]}" "$SRC/registry.json" "$DEST/"
# the page: copied beside the old one, then swapped in (no rsync needed)
rm -rf "$DEST/dist.new" "$DEST/dist.old"
cp -r "$DIST" "$DEST/dist.new"
chown -R hermes:hermes "$DEST/dist.new"
find "$DEST/dist.new" -type d -exec chmod 755 {} + && find "$DEST/dist.new" -type f -exec chmod 644 {} +
if [ -d "$DEST/dist" ]; then mv "$DEST/dist" "$DEST/dist.old"; fi
mv "$DEST/dist.new" "$DEST/dist"
rm -rf "$DEST/dist.old"

# The restart and backup helpers: root-owned, outside anything hermes can write; started by a request file from the page.
install -d -o root -g root -m 755 "$HELPERS"
install -o root -g root -m 755 "$SRC/deploy/restart-gateway.sh" "$SRC/deploy/restart_when_quiet.sh" "$SRC/deploy/backup-now.sh" "$HELPERS/"
install -o root -g root -m 644 "$SRC"/deploy/hermes-dash-{restart,jobs,backup}.{path,service} /etc/systemd/system/

# -- config.json (first install only): the Mem0 user and who may open the page, from crew.json ----------------------------
install -d -o hermes -g hermes -m 700 "$STATE"
if [ ! -f "$STATE/config.json" ]; then
  TS_OWNER="$(tailscale status --json | python3 -I -c 'import json,sys; d=json.load(sys.stdin); print(d["User"][str(d["Self"]["UserID"])]["LoginName"])' 2>/dev/null || true)"
  python3 -I - "$STATE/config.json" "$CREW" "$TS_OWNER" <<'PY'
import json, re, sys
out, crew_file, ts_owner = sys.argv[1], sys.argv[2], sys.argv[3].strip().lower()
try:
    owner = json.load(open(crew_file)).get("owner") or {}
except (OSError, ValueError):
    owner = {}
user = str(owner.get("id") or "").strip().lower()
login = str(owner.get("tailscale_login") or "").strip().lower() or ts_owner
if not re.fullmatch(r"[a-z0-9]{1,32}", user):
    sys.exit("crew.json has no valid owner.id (lowercase letters and digits): run the kit's installer first")
if not login:
    sys.exit("no Tailscale login: set owner.tailscale_login in crew.json, or sign this machine in to Tailscale")
json.dump({"port": 8890, "static_dir": "/data/tools/hermes-dash/dist", "mem0_url": "http://127.0.0.1:8888",
           "mem0_env": "/data/.hermes/mem0-server/server.env", "mem0_user": user, "allowed_logins": [login]},
          open(out, "w"), indent=2)
print(f"Wrote {out} (Mem0 user: {user}, allowed login: {login}).")
PY
  chown hermes:hermes "$STATE/config.json"
  chmod 600 "$STATE/config.json"
fi
LOGIN="$(python3 -I -c 'import json,sys; print((json.load(open(sys.argv[1])).get("allowed_logins") or [""])[0])' "$STATE/config.json")"

# -- services -------------------------------------------------------------------------------------------------------------
install -o root -g root -m 644 "$SRC/deploy/hermes-dash.service" "$UNIT"
systemctl daemon-reload
systemctl enable --quiet hermes-dash hermes-dash-restart.path hermes-dash-jobs.path hermes-dash-backup.path
rm -f "$STATE/restart.request" "$STATE/backup.request"
install -d -o hermes -g hermes -m 700 "$STATE/jobs"
systemctl restart hermes-dash
systemctl restart hermes-dash-restart.path hermes-dash-jobs.path hermes-dash-backup.path

for _ in $(seq 1 20); do
  if curl -fsS -m 2 -H "Tailscale-User-Login: $LOGIN" "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then break; fi
  sleep 0.5
done
curl -fsS -m 2 -H "Tailscale-User-Login: $LOGIN" "http://127.0.0.1:$PORT/api/health" >/dev/null || {
  journalctl -u hermes-dash -n 20 --no-pager; die "the bridge did not come up (log above); undo with --undo"; }
code="$(curl -s -o /dev/null -w '%{http_code}' -m 5 -H "Tailscale-User-Login: $LOGIN" "http://127.0.0.1:$PORT/api/memories")"
echo "Bridge up. Mem0 through the bridge: HTTP $code (200 = good)."
for feed in crew agents infra board; do
  echo "  /api/$feed: HTTP $(curl -s -o /dev/null -w '%{http_code}' -m 20 -H "Tailscale-User-Login: $LOGIN" "http://127.0.0.1:$PORT/api/$feed")"
done

# -- tailnet only (serve, never funnel); other serve entries stay as they are --------------------------------------------
# If HTTPS certificates are off in the tailnet, `tailscale serve` prints a link and waits: give it 2 minutes, then say what to do.
if ! out="$(timeout 120 tailscale serve --bg --https="$TS_PORT" "http://127.0.0.1:$PORT" 2>&1)"; then
  printf '%s\n' "$out" | grep -o 'https://login.tailscale.com[^ ]*' | head -n1 | sed 's/^/Open this link to switch on HTTPS for your tailnet: /'
  die "Tailscale couldn't publish the dashboard. In the Tailscale admin's DNS page switch on MagicDNS and HTTPS Certificates, then run on the server: sudo bash /opt/agent-automation/dashboard/bridge/deploy/install.sh"
fi
DNS="$(tailscale status --json | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
echo
echo "Open: https://$DNS:$TS_PORT/   (only from devices on your tailnet, signed in as $LOGIN)"
