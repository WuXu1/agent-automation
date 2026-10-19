# shellcheck shell=bash
# Shared helpers for the laptop side (install.sh, hermes). Sourced, not run. Plain bash 3.2+ (the version macOS ships).

KIT_DIR="${KIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
STATE_DIR="${HERMES_SETUP_STATE_DIR:-$HOME/.agent-automation}"
STATE_FILE="$STATE_DIR/settings"            # plain KEY=value lines, no secrets ever
SSH_KEY="$STATE_DIR/id_ed25519"
mkdir -p "$STATE_DIR" && chmod 700 "$STATE_DIR"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  B=$'\033[1m'; DIM=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; N=$'\033[0m'
else
  B=""; DIM=""; G=""; Y=""; R=""; C=""; N=""
fi

say()   { printf '%s\n' "$*"; }
step()  { printf '\n%s==> %s%s\n' "$B$C" "$*" "$N"; }
ok()    { printf '%s  ✓ %s%s\n' "$G" "$*" "$N"; }
warn()  { printf '%s  ! %s%s\n' "$Y" "$*" "$N" >&2; }
die()   { printf '%s  ✗ %s%s\n' "$R" "$*" "$N" >&2; exit 1; }
note()  { printf '%s    %s%s\n' "$DIM" "$*" "$N"; }

# ask "Question" "default" -> echoes the answer (the default when Enter is pressed)
ask() {
  local q="$1" def="${2:-}" a
  if [ -n "$def" ]; then printf '%s  ? %s %s[%s]%s ' "$B" "$q" "$DIM" "$def" "$N" >&2
  else printf '%s  ? %s%s ' "$B" "$q" "$N" >&2; fi
  IFS= read -r a </dev/tty || a=""
  printf '%s' "${a:-$def}"
}

# confirm "Question" [y|n default] -> exit status 0 for yes
confirm() {
  local def="${2:-y}" a
  a="$(ask "$1 (y/n)" "$def")"
  case "$a" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

pause() { printf '%s  … %s (press Enter)%s ' "$B" "${1:-Ready?}" "$N" >&2; IFS= read -r _ </dev/tty || true; }

# Remembered settings (the VM's name, resource group, region...). Never secrets.
get() { [ -f "$STATE_FILE" ] && sed -n "s/^$1=//p" "$STATE_FILE" | tail -n 1; }
put() {
  local tmp; tmp="$(mktemp "$STATE_DIR/.settings.XXXXXX")"
  [ -f "$STATE_FILE" ] && grep -v "^$1=" "$STATE_FILE" > "$tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$tmp"
  mv "$tmp" "$STATE_FILE"; chmod 600 "$STATE_FILE"
}

os_kind() {
  case "$(uname -s)" in
    Darwin) echo mac ;;
    Linux)  if grep -qi microsoft /proc/version 2>/dev/null; then echo wsl; else echo linux; fi ;;
    *)      echo other ;;
  esac
}

have() { command -v "$1" >/dev/null 2>&1; }

# The VM over the tailnet (its 100.x address, so it works without MagicDNS and inside WSL).
vm_ip()   { get VM_TS_IP; }
vm_user() { get VM_ADMIN; }
vm_ssh() {
  local ip; ip="$(vm_ip)"; [ -n "$ip" ] || die "I don't know the VM's address yet: run ./install.sh first."
  ssh -i "$SSH_KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 \
      -o ServerAliveInterval=30 "$(vm_user)@$ip" "$@"
}
vm_reachable() { vm_ssh -o BatchMode=yes -o ConnectTimeout=6 true >/dev/null 2>&1; }

# Put the kit on the VM (/opt/agent-automation) as a git clone of the same repository, so the server can update itself (sudo hermes-update) and the folder
# on this computer is no longer needed after setup. Falls back to copying this folder when the clone is not possible (no git on the server, a private fork, no network).
ship_kit() {
  local url branch
  url="$(git -C "$KIT_DIR" remote get-url origin 2>/dev/null || true)"; url="${url:-https://github.com/WuXu1/agent-automation}"
  branch="$(git -C "$KIT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"; { [ -n "$branch" ] && [ "$branch" != HEAD ]; } || branch=main
  case "$url" in https://*) ;; *) url=https://github.com/WuXu1/agent-automation ;; esac
  if vm_ssh "set -e; command -v git >/dev/null; sudo rm -rf /opt/agent-automation.new; sudo git clone -q --depth 1 --branch '$branch' '$url' /opt/agent-automation.new;
             sudo chmod 755 /opt/agent-automation.new; sudo rm -rf /opt/agent-automation.old; [ -d /opt/agent-automation ] && sudo mv /opt/agent-automation /opt/agent-automation.old;
             sudo mv /opt/agent-automation.new /opt/agent-automation; sudo rm -rf /opt/agent-automation.old" 2>/dev/null; then
    return 0
  fi
  [ -f "$KIT_DIR/vm/install.sh" ] || die "The server could not clone the kit from GitHub, and this isn't the full kit folder to copy instead. Check the server's internet, or clone https://github.com/WuXu1/agent-automation again and run ./hermes update from that folder."
  warn "The server could not clone the kit from GitHub, so I'm copying this folder instead (keep this folder then; updates come from it)."
  tar -C "$KIT_DIR" --exclude .git --exclude node_modules --exclude '__pycache__' --exclude '.DS_Store' -czf - . \
    | vm_ssh 'set -e; t=$(mktemp -d); tar -xzf - -C "$t"; sudo rm -rf /opt/agent-automation.new; sudo mv "$t" /opt/agent-automation.new;
              sudo chown -R root:root /opt/agent-automation.new; sudo chmod -R go-w /opt/agent-automation.new; sudo chmod 755 /opt/agent-automation.new;
              sudo rm -rf /opt/agent-automation.old; [ -d /opt/agent-automation ] && sudo mv /opt/agent-automation /opt/agent-automation.old;
              sudo mv /opt/agent-automation.new /opt/agent-automation; sudo rm -rf /opt/agent-automation.old'
}

# After the install the agent-automation folder is no longer needed: the commands live in ~/.agent-automation/kit and are run through
# ~/.agent-automation/bin/hermes. The scripts are copied from the server (which holds the kit as a git clone and updates itself), so they
# stay in step with it: `hermes update` calls this again.
LOCAL_KIT_FILES="hermes laptop/lib.sh laptop/desktop.sh vm/backup/laptop-authorize.sh"
sync_local_kit() {
  local kit="$STATE_DIR/kit" new="$STATE_DIR/kit.new" remote="${REMOTE_KIT:-/opt/agent-automation}"
  rm -rf "$new"; mkdir -p "$new"
  # shellcheck disable=SC2086  # LOCAL_KIT_FILES is a list of paths without spaces
  vm_ssh "tar -C '$remote' -cf - $LOCAL_KIT_FILES" 2>/dev/null | tar -xf - -C "$new" 2>/dev/null \
    && [ -s "$new/hermes" ] && [ -s "$new/laptop/lib.sh" ] || { rm -rf "$new"; return 1; }
  rm -rf "$kit.old"; [ -d "$kit" ] && mv "$kit" "$kit.old"
  mv "$new" "$kit"; rm -rf "$kit.old"
  mkdir -p "$STATE_DIR/bin"
  printf '%s\n' '#!/usr/bin/env bash' \
    '# Runs the agent-automation commands kept in ~/.agent-automation/kit (so the cloned folder can be deleted).' \
    'exec bash "${HERMES_SETUP_STATE_DIR:-$HOME/.agent-automation}/kit/hermes" "$@"' > "$STATE_DIR/bin/hermes"
  chmod 755 "$STATE_DIR/bin/hermes"
}

# Make `hermes status` work from any terminal: one PATH line in the shell's startup file (asked first by the caller).
add_hermes_to_path() {
  local rc line
  case "$(basename "${SHELL:-}")" in zsh) rc="$HOME/.zshrc" ;; bash) if [ "$(os_kind)" = mac ]; then rc="$HOME/.bash_profile"; else rc="$HOME/.bashrc"; fi ;; *) rc="" ;; esac
  [ -n "$rc" ] || return 1
  line='export PATH="$HOME/.agent-automation/bin:$PATH"   # agent-automation: the `hermes` command'
  grep -qF '.agent-automation/bin' "$rc" 2>/dev/null || printf '\n%s\n' "$line" >> "$rc"
  printf '%s' "$rc"
}
