# shellcheck shell=bash
# Stage: the base system. Packages, a swap file (4 GB of memory is enough with it), the `hermes` user the agents run as, folders.

stage_system() {
  step "Preparing the server (packages, memory, a user for the agents)"
  . /etc/os-release
  [ "${ID:-}" = ubuntu ] && [ "${VERSION_ID:-}" = "24.04" ] || warn "This kit is tested on Ubuntu 24.04; this is ${PRETTY_NAME:-unknown}."
  [ "$(uname -m)" = x86_64 ] || die "This kit needs an x86_64 server (Azure's B2als_v2 is one)."

  export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l     # never let apt restart services behind our back
  say "  Updating packages (a few minutes the first time)…"
  apt-get update -qq
  apt-get -y -qq -o Dpkg::Options::=--force-confold upgrade >/dev/null
  apt-get install -y -qq git curl jq acl rsync ffmpeg sqlite3 unattended-upgrades \
      python3 python3-venv python3.12-venv python3.12-dev build-essential \
      postgresql-16 postgresql-16-pgvector >/dev/null
  ok "Packages installed (security updates install themselves daily)"

  if ! swapon --show=NAME --noheadings | grep -q .; then
    fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap -q /swapfile && swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    ok "2 GB swap file added"
  fi

  if ! id hermes >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash --comment "AI agents (agent-automation)" hermes
    ok "User 'hermes' created (the agents run as it; it has no admin rights)"
  fi
  loginctl enable-linger hermes        # board workers run in the hermes user's own systemd session
  install -d -o hermes -g hermes -m 755 "$DATA" "$DATA/tools" "$DATA/workspace"
  install -d -o hermes -g hermes -m 700 "$HH"
  install -d -o hermes -g hermes -m 755 /opt/hermes
  local bashrc=/home/hermes/.bashrc
  grep -q 'HERMES_HOME=/data/.hermes' "$bashrc" 2>/dev/null || {
    printf '# agent-automation: the hermes command and its home (also for non-login ssh commands)\nexport PATH="$HOME/.local/bin:$PATH"\nexport HERMES_HOME=/data/.hermes\n\n' | cat - "$bashrc" > /tmp/hermes-bashrc
    install -o hermes -g hermes -m 644 /tmp/hermes-bashrc "$bashrc"; rm -f /tmp/hermes-bashrc
  }
  install -m 755 "$KIT/vm/bin/"hermes-* /usr/local/bin/
  ok "Folders ready: /data (agents' data), /opt/hermes (their program)"
}
