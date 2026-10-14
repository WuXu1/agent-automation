# shellcheck shell=bash
# Step 1: the tools this laptop needs (Azure CLI, Tailscale, ssh). Sourced by install.sh.

prereqs() {
  local os; os="$(os_kind)"
  step "Step 1 of 4: tools on this computer"
  case "$os" in
    mac|linux|wsl) ok "This computer: $os" ;;
    *) die "Run this from macOS, Linux, or on Windows inside WSL (Ubuntu). See README: 'On Windows'." ;;
  esac

  have ssh && have ssh-keygen || {
    [ "$os" = mac ] && die "ssh is missing, which is unusual on a Mac. Install Apple's command line tools: xcode-select --install"
    say "  Installing OpenSSH (your computer password may be asked)…"
    sudo apt-get update -qq && sudo apt-get install -y -qq openssh-client curl
  }
  have curl || { sudo apt-get update -qq && sudo apt-get install -y -qq curl; }
  ok "ssh"

  # Azure CLI
  if have az; then ok "Azure CLI $(az version --query '"azure-cli"' -o tsv 2>/dev/null)"
  else
    say "  The Azure CLI creates and looks after your server. Installing it now."
    case "$os" in
      mac)
        if ! have brew; then
          say "  It comes through Homebrew, the usual Mac installer, which isn't on this Mac yet."
          confirm "Install Homebrew now? It asks for your Mac password" y || die "Install Homebrew from https://brew.sh, then run ./install.sh again."
          /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/tty
          [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
          [ -x /usr/local/bin/brew ] && eval "$(/usr/local/bin/brew shellenv)"
        fi
        brew install azure-cli ;;
      linux|wsl)
        if have apt-get; then curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
        else die "Install the Azure CLI for your Linux (https://aka.ms/installazurecli), then run ./install.sh again."; fi ;;
    esac
    have az || die "The Azure CLI did not install. Open a new terminal and run ./install.sh again."
    ok "Azure CLI installed"
  fi

  # Tailscale: the private network between this computer and the server (nothing on the server is open to the internet).
  if tailnet_up_here; then ok "Tailscale is on and signed in"
  else
    say
    say "  ${B}Tailscale${N} makes a private network between your devices and the server, so nothing on the server"
    say "  is open to the internet. It's free for personal use."
    case "$os" in
      mac)
        say "  1. Install the Tailscale app: https://tailscale.com/download/mac (the App Store version is fine)."
        say "  2. Open it, sign in (Google, Microsoft, GitHub or Apple: pick one and use the same one every time)."
        (open "https://tailscale.com/download/mac" 2>/dev/null || true) ;;
      wsl)
        say "  1. In Windows (not here), install Tailscale: https://tailscale.com/download/windows"
        say "  2. Open it from the system tray and sign in (Google, Microsoft, GitHub or Apple: use the same one every time)."
        say "  Windows' Tailscale also covers this Ubuntu window." ;;
      linux)
        if ! have tailscale; then curl -fsSL https://tailscale.com/install.sh | sh; fi
        say "  Sign in with the link below (Google, Microsoft, GitHub or Apple: use the same one every time)."
        sudo tailscale up ;;
    esac
    say "  3. Also install Tailscale on your phone and sign in with the same account, so the dashboard opens there too."
    pause "When Tailscale shows you as connected"
    tailnet_up_here || [ "$os" = wsl ] || warn "I can't see Tailscale's address on this computer yet. Carrying on; we'll test the real connection later."
  fi

  [ -f "$SSH_KEY" ] || {
    ssh-keygen -q -t ed25519 -N "" -C "agent-automation $(hostname 2>/dev/null)" -f "$SSH_KEY"
    ok "Made a login key for your server ($SSH_KEY). Keep it: it is how this computer gets in."
  }
  put STEP_PREREQS "done"
}

# Does this machine have a Tailscale (100.64.0.0/10) address? WSL can't see Windows' one, so it answers no there.
tailnet_up_here() {
  if have tailscale && tailscale status >/dev/null 2>&1; then return 0; fi
  if have ifconfig; then ifconfig 2>/dev/null | grep -Eq 'inet 100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.'; return; fi
  have ip && ip -4 addr 2>/dev/null | grep -Eq 'inet 100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.'
}
