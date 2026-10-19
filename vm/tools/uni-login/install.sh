#!/bin/bash
# Installs the university sign-in helper (docs/UNI-LOGIN.md): a locked-down user, a Python venv with a headless Chromium,
# the root-owned `uni-login` command and the systemd units. Called by `hermes-addon moodle-login`; safe to run again.
# Needs: UNI_MOODLE_URL, UNI_TARGETS (env files that hold MOODLE_TOKEN, space-separated), UNI_GROUP (the agents' group),
#        UNI_RESTART (a quiet-restart command, may be empty).
set -euo pipefail
[ "$(id -u)" = 0 ] || exec sudo -E "$0" "$@"
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${UNI_MOODLE_URL:?}" "${UNI_TARGETS:?}" "${UNI_GROUP:=hermes}"
PW_VERSION=1.63.0
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l

id unilogin >/dev/null 2>&1 || useradd --system --home-dir /var/lib/uni-login --shell /usr/sbin/nologin unilogin
install -d -m 755 -o root -g root /var/lib/uni-login /etc/uni-login /usr/local/lib/uni-login /opt/uni-login
install -d -m 700 -o unilogin -g unilogin /var/lib/uni-login/private
install -d -m 700 -o unilogin -g unilogin /var/lib/uni-login/home

if [ ! -x /opt/uni-login/venv/bin/python ]; then
  command -v python3 >/dev/null && python3 -c 'import venv, ensurepip' 2>/dev/null || apt-get install -y -qq python3-venv >/dev/null
  python3 -m venv /opt/uni-login/venv
fi
/opt/uni-login/venv/bin/pip install -q --disable-pip-version-check "playwright==$PW_VERSION"
if [ ! -d /opt/uni-login/browsers ] || ! ls /opt/uni-login/browsers 2>/dev/null | grep -q chromium; then
  echo "Installing the headless browser (about 300 MB, once)..."
  PLAYWRIGHT_BROWSERS_PATH=/opt/uni-login/browsers /opt/uni-login/venv/bin/playwright install --with-deps --only-shell chromium \
    || PLAYWRIGHT_BROWSERS_PATH=/opt/uni-login/browsers /opt/uni-login/venv/bin/playwright install --with-deps chromium
fi
chmod -R a+rX /opt/uni-login

install -m 755 -o root -g root "$HERE/uni_login.py" /usr/local/lib/uni-login/uni_login.py
install -m 755 -o root -g root "$HERE/uni-login" /usr/local/bin/uni-login
python3 - "$UNI_MOODLE_URL" "$UNI_TARGETS" "${UNI_RESTART:-}" <<'PY' > /etc/uni-login/config.json
import json, sys
print(json.dumps({"moodle_url": sys.argv[1].rstrip("/"), "targets": sys.argv[2].split(), "restart_cmd": sys.argv[3]}, indent=1))
PY
chmod 644 /etc/uni-login/config.json
sed "s|@GROUP@|$UNI_GROUP|" "$HERE/uni-login.tmpfiles" > /etc/tmpfiles.d/uni-login.conf
install -m 644 "$HERE/uni-login-refresh.service" "$HERE/uni-login-refresh.path" /etc/systemd/system/
systemd-tmpfiles --create /etc/tmpfiles.d/uni-login.conf
systemctl daemon-reload
systemctl enable --now uni-login-refresh.path >/dev/null
echo "uni-login installed. Next: sudo uni-login setup"
