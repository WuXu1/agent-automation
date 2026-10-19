# shellcheck shell=bash
# Helpers for the server side (vm/install.sh and the hermes-* commands). Sourced, never run. Runs as root.

KIT=/opt/agent-automation
DATA=/data
HH=/data/.hermes                         # HERMES_HOME of the chief (the `default` profile)
HERMES_SETUP_JSON=$HH/hermes.json
AGENT_SRC=/opt/hermes/hermes-agent
HPY=$AGENT_SRC/venv/bin/python           # Hermes's Python (has PyYAML), used for vm/hermeslib.py
STAMP_DIR=/var/lib/agent-automation      # one file per finished install stage
HERMES_TAG=v2026.9.24                    # Hermes v0.21.5, commit f97608f: the pinned stable release
HERMES_COMMIT=f97608f178d1ffeca59860195ab7da295f7c8e5f
UV_VERSION=0.11.32
MEM0_TAG=v2.2.1
LIVE_TIME_SHA=8e5c80012457592f5c4fb740aa424f8512324467
OPENALEX_SHA=47aafae87256ef634f32c18a69bf35d39c2c5682
ROLES="chief tutor assistant coach"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  B=$'\033[1m'; DIM=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; N=$'\033[0m'
else B=""; DIM=""; G=""; Y=""; R=""; C=""; N=""; fi
say()  { printf '%s\n' "$*"; }
step() { printf '\n%s--> %s%s\n' "$B$C" "$*" "$N"; }
ok()   { printf '%s  ✓ %s%s\n' "$G" "$*" "$N"; }
warn() { printf '%s  ! %s%s\n' "$Y" "$*" "$N" >&2; }
die()  { printf '%s  ✗ %s%s\n' "$R" "$*" "$N" >&2; exit 1; }
note() { printf '%s    %s%s\n' "$DIM" "$*" "$N"; }

ask() {   # ask "Question" "default"   (HERMES_SETUP_UNATTENDED=1: the default, without asking)
  local q="$1" def="${2:-}" a
  if [ -n "${HERMES_SETUP_UNATTENDED:-}" ]; then printf '%s' "$def"; return; fi
  if [ -n "$def" ]; then printf '%s  ? %s %s[%s]%s ' "$B" "$q" "$DIM" "$def" "$N" >&2; else printf '%s  ? %s%s ' "$B" "$q" "$N" >&2; fi
  IFS= read -r a </dev/tty || a=""
  a="$(printf '%s' "$a" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  printf '%s' "${a:-$def}"
}
confirm() { case "$(ask "$1 (y/n)" "${2:-y}")" in [Yy]*) return 0 ;; *) return 1 ;; esac; }
pause() { [ -n "${HERMES_SETUP_UNATTENDED:-}" ] && return 0; printf '%s  … %s (press Enter)%s ' "$B" "${1:-Ready?}" "$N" >&2; IFS= read -r _ </dev/tty || true; }

# ask_secret "What" -> the value on stdout. Nothing is shown while typing or pasting; the value never goes to a log or argv.
ask_secret() {
  local v
  [ -z "${HERMES_SETUP_UNATTENDED:-}" ] || die "A key is missing ($1). Run the full installer to add it: ./install.sh"
  printf '%s  🔑 %s (hidden; paste, then Enter):%s ' "$B" "$1" "$N" >&2
  IFS= read -rs v </dev/tty || v=""
  printf '\n' >&2
  printf '%s' "$v" | tr -d '[:space:]'
}

done_stage() { [ -f "$STAMP_DIR/$1" ]; }
mark_stage() { mkdir -p "$STAMP_DIR"; date -u +%FT%TZ > "$STAMP_DIR/$1"; }

# Proxy and certificate settings pass through when the machine has them (some networks need a proxy; Azure doesn't).
_passenv() { local v; for v in HTTPS_PROXY HTTP_PROXY NO_PROXY https_proxy http_proxy no_proxy SSL_CERT_FILE REQUESTS_CA_BUNDLE PIP_CERT UV_NATIVE_TLS; do
  [ -n "${!v:-}" ] && printf '%s=%s\n' "$v" "${!v}"; done; }
# shellcheck disable=SC2046  # one KEY=value per line, split on newlines on purpose
as_hermes() { local pre=() IFS=$'\n'; [ -z "${AS_HERMES_DETACHED:-}" ] || pre=(setsid -w)
  "${pre[@]}" sudo -u hermes -H env $(_passenv) HERMES_HOME=$HH PATH=/home/hermes/.local/bin:/usr/local/bin:/usr/bin:/bin "$@"; }
# Hermes commands run from here never ask anything: detached from the terminal as well as stdin from /dev/null, because a plugin's
# optional-key prompt (getpass) reads /dev/tty and would otherwise wait for ever when the installer runs over `ssh -t`.
hermes_cli() { AS_HERMES_DETACHED=1 as_hermes /home/hermes/.local/bin/hermes "$@" </dev/null; }

profile_of() { case "$1" in chief) echo default ;; *) echo "$1" ;; esac; }
home_of()    { [ "$1" = default ] && echo "$HH" || echo "$HH/profiles/$1"; }
env_of()     { echo "$(home_of "$(profile_of "$1")")/.env"; }

# hermes.json access (jq is installed in the system stage)
cj()     { jq -r "$1 // empty" "$HERMES_SETUP_JSON" 2>/dev/null; }
cj_set() {   # cj_set '.owner.name' '"Sam"'   (the second argument is JSON)
  local tmp; tmp="$(mktemp)"
  [ -s "$HERMES_SETUP_JSON" ] || echo '{"version":1}' > "$HERMES_SETUP_JSON"
  jq "$1 = $2" "$HERMES_SETUP_JSON" > "$tmp" && install -o hermes -g hermes -m 640 "$tmp" "$HERMES_SETUP_JSON"; rm -f "$tmp"
}
jstr() { jq -Rn --arg v "$1" '$v'; }

# Secrets: written straight into an .env through stdin (never argv), file mode 600, owned by hermes.
env_set() {  # env_set FILE KEY  (value on stdin)
  local f="$1"
  [ -f "$f" ] || { install -o hermes -g hermes -m 600 /dev/null "$f"; }
  as_hermes /usr/bin/python3 -I "$KIT/vm/hermeslib.py" env-set "$f" "$2"
  chown hermes:hermes "$f"; chmod 600 "$f"
}
env_has() { [ -f "$1" ] && as_hermes /usr/bin/python3 -I "$KIT/vm/hermeslib.py" env-has "$1" "$2"; }
env_get() { [ -f "$1" ] && sed -n "s/^\(export \)\{0,1\}$2=//p" "$1" | tail -n1 | tr -d "\"'"; }

# HTTP status of a request whose secret part is fed through curl's config on stdin (so it never shows in `ps`).
curl_status() {  # curl_status CONFIG-TEXT
  printf '%s\n' "$1" | curl -s -o /dev/null -w '%{http_code}' -m 20 -K - 2>/dev/null || echo 000
}
curl_body() { printf '%s\n' "$1" | curl -s -m 30 -K - 2>/dev/null; }
