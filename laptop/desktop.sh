#!/usr/bin/env bash
# desktop.sh: the Hermes desktop app on a Mac, already connected to YOUR server. Nothing of Hermes runs on this Mac: no local agent, no Python, no `hermes` command.
#
#   bash laptop/desktop.sh                        (or: ./hermes desktop)
#   bash laptop/desktop.sh --host 100.x.y.z --admin yourlogin      (when this Mac never ran ./install.sh)
#   bash laptop/desktop.sh --rebuild              build the app again (after the kit moves to a newer Hermes)
#   bash laptop/desktop.sh --remove               take it off this Mac again
#
# Why not the app from hermes-agent.nousresearch.com? Its installer puts a full second copy of Hermes (agent, Python, gateway) on this Mac and the app then talks to that.
# This builds ONLY the app (from the same Hermes release your server runs, so the two always match), signs it on this Mac, and saves one connection to your server
# (over Tailscale, SSH) as the main one. The first start opens your agents straight away.
#
# It needs: this Mac on Tailscale (same account as the server), about 5 GB of free disk and 10-15 minutes the first time (it compiles the app). It installs Apple's
# command line tools and Node 24 through Homebrew if they are missing. Re-running is safe: it fixes the connection and only rebuilds when asked.
# Never put a key or password on this command line: it asks for nothing secret (your Mac makes its own key and asks the server's admin login to accept it).
set -euo pipefail

# The Hermes release the server runs. Keep in step with vm/lib.sh (tests/run.sh checks it).
HERMES_TAG=v2026.9.24
HERMES_COMMIT=f97608f178d1ffeca59860195ab7da295f7c8e5f

STATE_DIR="${HERMES_SETUP_STATE_DIR:-$HOME/.agent-automation}"
SETTINGS="$STATE_DIR/settings"
HH="$HOME/.hermes"                                         # where the app looks for its checkout (and puts its logs)
SRC="$HH/hermes-agent"
MARK="$SRC/.desktop-only-build"                            # says this checkout is ours (build only, no local agent)
APP="${HERMES_DESKTOP_APP_DIR:-/Applications}/Hermes.app"       # (the folder can be overridden for tests)
SUPPORT="$HOME/Library/Application Support/Hermes"
REGISTRY="$SUPPORT/connections.json"
KEY="$HOME/.ssh/id_ed25519_hermes_desktop"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; N=$'\033[0m'; else B=""; G=""; Y=""; R=""; C=""; N=""; fi
say()  { printf '%s\n' "$*"; }
step() { printf '\n%s==> %s%s\n' "$B$C" "$*" "$N"; }
ok()   { printf '%s  ✓ %s%s\n' "$G" "$*" "$N"; }
warn() { printf '%s  ! %s%s\n' "$Y" "$*" "$N" >&2; }
die()  { printf '%s  ✗ %s%s\n' "$R" "$*" "$N" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
ask() {                                                    # ask "Question" "default"
  local a; if [ -n "${2:-}" ]; then printf '%s  ? %s [%s]%s ' "$B" "$1" "$2" "$N" >&2; else printf '%s  ? %s%s ' "$B" "$1" "$N" >&2; fi
  IFS= read -r a </dev/tty || a=""; printf '%s' "${a:-${2:-}}"
}
setting() { [ -f "$SETTINGS" ] && sed -n "s/^$1=//p" "$SETTINGS" | tail -n 1 || true; }

HOST="" ADMIN="" LABEL="My Hermes server" REBUILD=0 REMOVE=0 PRINT_CONFIG=0
while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="${2:-}"; shift 2 ;;
    --admin) ADMIN="${2:-}"; shift 2 ;;
    --label) LABEL="${2:-}"; shift 2 ;;
    --rebuild) REBUILD=1; shift ;;
    --remove) REMOVE=1; shift ;;
    --print-config) PRINT_CONFIG=1; shift ;;               # tests: print the connection file this would save, change nothing
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "Unknown option $1 (see: bash laptop/desktop.sh --help)" ;;
  esac
done

# ---- the connection file the app reads (its own format, version 2; merged into any file that is already there)
write_registry() {                                         # write_registry <host> <label> <keyfile> [--stdout]
  python3 - "$REGISTRY" "$1" "$2" "$3" "${4:-}" <<'PY'
import json, os, re, sys, time
path, host, label, key, mode = sys.argv[1:6]
try:
    reg = json.load(open(path))
    if not isinstance(reg, dict):
        reg = {}
except (OSError, ValueError):
    reg = {}
conns = [c for c in reg.get("connections") or [] if isinstance(c, dict)]
if not any(c.get("kind") == "local" for c in conns):
    conns.insert(0, {"id": "local", "kind": "local", "label": "This device"})
slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "hermes-server"
conns = [c for c in conns if not (c.get("kind") == "ssh" and (c.get("host") == host or c.get("id") == slug))]
taken = {str(c.get("label", "")).lower() for c in conns}
name = label
n = 2
while name.lower() in taken:
    name, n = f"{label} {n}", n + 1
conns.append({"id": slug, "kind": "ssh", "label": name, "host": host, "user": "hermes", "keyPath": key})
out = {"version": 2, "primary": slug, "launchMode": "primary", "lastUsed": slug, "connections": conns}
text = json.dumps(out, indent=2) + "\n"
if mode == "--stdout":
    sys.stdout.write(text)
    sys.exit(0)
os.makedirs(os.path.dirname(path), exist_ok=True)
if os.path.exists(path):
    if open(path).read() == text:                   # nothing to change: no new backup either
        sys.exit(0)
    os.replace(path, f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
tmp = path + ".part"
with open(tmp, "w") as f:
    f.write(text)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PY
}

if [ "$PRINT_CONFIG" = 1 ]; then write_registry "${HOST:-100.64.0.1}" "$LABEL" "${KEY}" --stdout; exit 0; fi

[ "$(uname -s)" = Darwin ] || die "This is for a Mac. (On Windows or Linux, use the dashboard: ./hermes dashboard.)"

# ---- take it off again
if [ "$REMOVE" = 1 ]; then
  step "Removing Hermes Desktop from this Mac"
  pgrep -f "Hermes.app/Contents/MacOS" >/dev/null && die "Quit Hermes first (Cmd+Q), then run this again."
  rm -rf "$APP"; ok "Removed $APP"
  if [ -f "$MARK" ]; then rm -rf "$HH"; ok "Removed $HH (it only held the build)"; else warn "Left $HH alone: it was not made by this script."; fi
  rm -rf "$SUPPORT"; ok "Removed the app's saved settings"
  rm -f "$KEY" "$KEY.pub"; ok "Removed this Mac's key for the server"
  say "  The server still accepts that key until its admin removes the line containing 'hermes-desktop' from /home/hermes/.ssh/authorized_keys."
  exit 0
fi

# ---- where the server is
[ -n "$HOST" ] || HOST="$(setting VM_TS_IP)"
[ -n "$ADMIN" ] || ADMIN="$(setting VM_ADMIN)"
if [ -z "$HOST" ]; then
  say "  I need your server's private Tailscale address (a number like 100.x.y.z, shown in the Tailscale app or at login.tailscale.com/admin/machines)."
  HOST="$(ask "Server address" "")"
fi
[ -n "$HOST" ] || die "No server address given."
case "$HOST" in *[!A-Za-z0-9._:-]*) die "That address has odd characters in it." ;; esac
if [ -z "$ADMIN" ]; then ADMIN="$(ask "The server's admin login (what you type after 'ssh', e.g. your first name)" "")"; fi
case "$ADMIN" in ""|*[!a-z0-9_-]*) die "The admin login is lower-case letters, numbers, - or _ ." ;; esac

step "Step 1 of 5: is the server reachable?"
if ! nc -z -G 6 "$HOST" 22 >/dev/null 2>&1; then
  die "Can't reach $HOST. Open the Tailscale app on this Mac, make sure it's on and signed in with the same account as the server, then run this again."
fi
ok "Reached $HOST over Tailscale"

# ---- this Mac's own key, accepted by the server's 'hermes' user (the account the agents run as; it has no admin rights)
step "Step 2 of 5: a key for the app"
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
if [ ! -f "$KEY" ]; then
  ssh-keygen -q -t ed25519 -N "" -C "hermes-desktop-$(scutil --get LocalHostName 2>/dev/null | tr -c 'A-Za-z0-9\n' '-' | head -c 40)" -f "$KEY"
  ok "Made a key only for this app: $KEY"
else ok "Using the key from before: $KEY"; fi
PUB="$(cat "$KEY.pub")"
case "$PUB" in "ssh-ed25519 "*) ;; *) die "$KEY.pub does not look like a public key." ;; esac
ssh_hermes() { ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "hermes@$HOST" "$@"; }
if ssh_hermes true >/dev/null 2>&1; then ok "The server already accepts this key"
else
  say "  Asking the server's admin login to accept it (this only lets the app in as 'hermes', the agents' own account)."
  AUTH="set -e; sudo install -d -o hermes -g hermes -m 700 /home/hermes/.ssh; sudo touch /home/hermes/.ssh/authorized_keys;
        sudo grep -qxF '$PUB' /home/hermes/.ssh/authorized_keys || echo '$PUB' | sudo tee -a /home/hermes/.ssh/authorized_keys >/dev/null;
        sudo chown hermes:hermes /home/hermes/.ssh/authorized_keys; sudo chmod 600 /home/hermes/.ssh/authorized_keys"
  done_auth=0
  if [ -f "$STATE_DIR/id_ed25519" ]; then       # the key ./install.sh made for the admin login
    ssh -i "$STATE_DIR/id_ed25519" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$ADMIN@$HOST" "$AUTH" 2>/dev/null && done_auth=1 || true
  fi
  if [ "$done_auth" = 0 ]; then                  # any other key this Mac already has for that login
    ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$ADMIN@$HOST" "$AUTH" 2>/dev/null && done_auth=1 || true
  fi
  if [ "$done_auth" = 0 ]; then
    warn "This Mac can't log in to the server as '$ADMIN' (it has no key for that login)."
    say "  Someone who can (you from another computer, or whoever set the server up) runs this one line, in a terminal that can reach the server:"
    say
    say "    ssh $ADMIN@$HOST \"echo '$PUB' | sudo tee -a /home/hermes/.ssh/authorized_keys\""
    say
    say "  (If it says the folder doesn't exist, first: ssh $ADMIN@$HOST \"sudo install -d -o hermes -g hermes -m 700 /home/hermes/.ssh\")"
    printf '%s  … press Enter when that is done%s ' "$B" "$N" >&2; IFS= read -r _ </dev/tty || true
  fi
  ssh_hermes true >/dev/null 2>&1 || die "The server still doesn't accept the key. Check the line was added to /home/hermes/.ssh/authorized_keys, then run this again."
  ok "The server accepts this Mac's key"
fi
HHOME="$(ssh_hermes 'echo "$HERMES_HOME"' 2>/dev/null || true)"
[ -n "$HHOME" ] || die "The server didn't say where the agents live (HERMES_HOME is empty in a plain ssh session). On the server run: sudo hermes-update, then try again."
ssh_hermes 'command -v hermes' >/dev/null 2>&1 || die "The 'hermes' command isn't on the hermes user's path on the server. Run: sudo hermes-update there, then try again."
ok "The server's agents are in $HHOME"

# ---- the app
BUILT="$(cat "$HH/.desktop-built-commit" 2>/dev/null || true)"
if [ -d "$APP" ] && [ "$REBUILD" = 0 ] && [ "$BUILT" = "$HERMES_COMMIT" ]; then
  step "Step 3 of 5: the app"; ok "Hermes.app is already here (built from the server's release). Use --rebuild to build it again."
else
  step "Step 3 of 5: building the app (10-15 minutes; it compiles on this Mac)"
  pgrep -f "Hermes.app/Contents/MacOS" >/dev/null && die "Quit Hermes first (Cmd+Q), then run this again."
  if [ -d "$SRC" ] && [ ! -f "$MARK" ]; then
    die "$SRC already exists and wasn't made by this script. It looks like this Mac has a normal Hermes install, which this script won't touch. Ask whoever gave you this script."
  fi
  FREE_KB="$(df -k "$HOME" | awk 'NR==2 {print $4}')"; [ "${FREE_KB:-0}" -gt 5000000 ] || die "Less than 5 GB free on this Mac. Free some space and run this again."
  # Apple's command line tools (git, the compiler and codesign)
  if ! xcode-select -p >/dev/null 2>&1; then
    say "  Apple's command line tools are needed. A window will ask to install them; click Install, wait for it to finish, then run this again."
    xcode-select --install >/dev/null 2>&1 || true; exit 1
  fi
  have git || die "git is missing even though the command line tools are installed: run  xcode-select --install"
  # Node: the app's own build needs 22.22+, 24.11+ or 26+
  node_ok() { have node && node -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit((a===22&&b>=22)||(a===24&&b>=11)||a>=26?0:1)' 2>/dev/null; }
  if ! node_ok; then
    say "  The build needs Node (a programming tool). Installing Node 24 through Homebrew."
    if ! have brew; then
      [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"; [ -x /usr/local/bin/brew ] && eval "$(/usr/local/bin/brew shellenv)"
    fi
    if ! have brew; then
      say "  Homebrew (the usual Mac installer for tools like this) isn't on this Mac yet; it asks for your Mac password."
      [ "$(ask "Install Homebrew now? (y/n)" y)" = y ] || die "Install Homebrew from https://brew.sh (or Node 24 from https://nodejs.org), then run this again."
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/tty
      [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"; [ -x /usr/local/bin/brew ] && eval "$(/usr/local/bin/brew shellenv)"
      have brew || die "Homebrew didn't install. Open a new terminal and run this again."
    fi
    brew install node@24 >/dev/null
    NODE_BIN="$(brew --prefix node@24)/bin"; export PATH="$NODE_BIN:$PATH"
    node_ok || die "Node didn't install properly. Open a new terminal and run this again."
  fi
  ok "Node $(node -v), git, command line tools"

  [ -f "$MARK" ] && rm -rf "$SRC"
  mkdir -p "$HH"
  say "  Downloading the app's source ($HERMES_TAG, the release your server runs)…"
  git -c advice.detachedHead=false clone -q --depth 1 --branch "$HERMES_TAG" https://github.com/NousResearch/hermes-agent.git "$SRC"
  [ "$(git -C "$SRC" rev-parse HEAD)" = "$HERMES_COMMIT" ] || { rm -rf "$SRC"; die "The download isn't the release this kit is pinned to; stopped. (Nothing was installed.)"; }
  : > "$MARK"
  say "  Installing the build's parts (a few minutes)…"
  (cd "$SRC" && npm ci --no-audit --no-fund --loglevel=error)
  say "  Compiling the app (a few more minutes; fans may spin up)…"
  (cd "$SRC/apps/desktop" && CSC_IDENTITY_AUTO_DISCOVERY=false npm run pack >/tmp/hermes-desktop-build.log 2>&1) || { tail -n 25 /tmp/hermes-desktop-build.log >&2; die "The build failed (log: /tmp/hermes-desktop-build.log). Send that file to whoever gave you this script."; }
  BUILT_APP="$(find "$SRC/apps/desktop/release" -maxdepth 3 -name Hermes.app -type d | head -n 1)"
  [ -n "$BUILT_APP" ] || die "The build finished but there is no Hermes.app (log: /tmp/hermes-desktop-build.log)."
  xattr -cr "$BUILT_APP"; codesign --force --deep --sign - "$BUILT_APP"        # signed on this Mac, so it opens without Apple's checks
  [ -d "$APP" ] && { rm -rf "$HH/Hermes.app.previous"; mv "$APP" "$HH/Hermes.app.previous"; warn "There was already a Hermes.app: moved to $HH/Hermes.app.previous"; }
  ditto "$BUILT_APP" "$APP"
  codesign --verify --deep --strict "$APP" || die "The app's signature didn't check out; try again with --rebuild."
  printf '%s\n' "$HERMES_COMMIT" > "$HH/.desktop-built-commit"
  ok "Installed $APP"
fi

# ---- the connection
step "Step 4 of 5: connecting the app to your server"
pgrep -f "Hermes.app/Contents/MacOS" >/dev/null && die "Quit Hermes first (Cmd+Q), then run this again so it reads the new connection."
write_registry "$HOST" "$LABEL" "$KEY"
ok "Saved: the app opens your server ($HOST) as its main connection"

step "Step 5 of 5: opening it"
open "$APP" || warn "Couldn't open it; open Hermes from your Applications folder."
say
say "${B}Done.${N} Hermes opens on your agents. Leave it connected: it starts what it needs on the server and stops it when you quit."
say "  - Keep Tailscale on, or it can't reach the server."
say "  - ${B}Never press Update inside the app${N} and say no to anything that says \"Set up Hermes Agent\": that would put a second copy of Hermes on this Mac."
say "    Updates come with the kit: ./hermes update on the server side, then bash laptop/desktop.sh --rebuild here."
say "  - The server keeps about 1 GB of memory busy while the app is open; closing the app frees it."
