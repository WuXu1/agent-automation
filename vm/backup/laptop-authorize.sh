#!/usr/bin/env bash
# laptop-authorize.sh: the Google Drive sign-in for the server's nightly backups. Runs on YOUR computer (Mac, Linux, or Ubuntu in
# WSL on Windows), because the server has no web browser.   ./crew backup-login   (or: bash vm/backup/laptop-authorize.sh)
# It installs rclone if it is missing (asks first), then runs `rclone authorize "drive"` with Google's narrow drive.file permission:
# rclone can only see and change the files it creates itself (the backups), never anything else in your Drive.
# rclone prints the sign-in token on this screen. This script saves nothing and sends nothing: you copy the token and paste it at the
# server's hidden prompt (./crew addon backup).
set -euo pipefail
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then B=$'\033[1m'; Y=$'\033[33m'; N=$'\033[0m'; else B=""; Y=""; N=""; fi
say() { printf '%s\n' "$*"; }
die() { printf '%s  ✗ %s%s\n' "$Y" "$*" "$N" >&2; exit 1; }

case "$(uname -s)" in
  Darwin) os=mac ;;
  Linux)  if grep -qi microsoft /proc/version 2>/dev/null; then os=wsl; else os=linux; fi ;;
  *) die "Run this on a Mac, on Linux, or in Ubuntu inside WSL. On plain Windows: winget install Rclone.Rclone, then in PowerShell: rclone authorize \"drive\" --drive-scope drive.file" ;;
esac

if ! command -v rclone >/dev/null 2>&1; then
  say "${B}rclone${N} (a free, open-source tool for cloud storage) is needed once, to sign in to Google Drive."
  printf '  ? Install it now? (y/n) [y] '; IFS= read -r a </dev/tty || a=y
  case "${a:-y}" in [Yy]*) ;; *) die "Not installed. Mac: brew install rclone   Linux/WSL: curl https://rclone.org/install.sh | sudo bash" ;; esac
  if [ "$os" = mac ] && command -v brew >/dev/null 2>&1; then
    brew install rclone
  else
    command -v curl >/dev/null 2>&1 || die "curl is missing (Ubuntu: sudo apt install -y curl)."
    if ! command -v unzip >/dev/null 2>&1; then
      if command -v apt-get >/dev/null 2>&1; then sudo apt-get install -y unzip; else die "unzip is missing; install it, then run this again."; fi
    fi
    say "  Installing with rclone's official script (asks for your computer's password, for sudo)…"
    curl -fsSL https://rclone.org/install.sh | sudo bash
  fi
  command -v rclone >/dev/null 2>&1 || die "rclone didn't install (message above)."
fi

say
say "${B}Sign in to Google Drive for your server's backups${N}"
if [ "$os" = mac ]; then
  say "  1. A Google page opens in your browser in a moment."
else
  say "  1. A link appears below (http://127.0.0.1:53682/auth?...). Open it in your browser (Ctrl+click, or copy it)."
  [ "$os" = wsl ] && say "     In WSL, paste it into your normal Windows browser: it works from there."
fi
say "  2. Pick the Google account whose Drive should hold the backups, and click ${B}Allow${N}. Google says rclone may"
say "     'see, edit, create and delete only the specific Google Drive files you use with this app': that's the narrow permission."
say "  3. Come back here. rclone prints a line that starts with ${B}{\"access_token\"${N}."
say

args=(authorize "drive" --drive-scope drive.file)
if [ "$os" != mac ] && { [ "$os" = wsl ] || [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; }; then args+=(--auth-no-open-browser); fi
rclone "${args[@]}" || die "The sign-in didn't finish. Run it again (if it says the port is in use, close the other rclone first)."

say
say "${B}Next${N}"
say "  1. Copy the whole line above that starts with {\"access_token\" and ends with } (between '--->' and '<---End paste')."
say "  2. In the agent-automation folder:  ${B}./crew addon backup${N}  (or on the server: sudo crew-addon backup)"
say "     and paste it at its hidden prompt for the Google Drive token."
say "  Treat that line like a password: don't put it in a chat or an email. After pasting, clear this window"
say "  (Mac: Cmd+K; Linux/WSL: type clear). Nothing was saved on this computer."
