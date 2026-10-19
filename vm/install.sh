#!/usr/bin/env bash
# The server half of the install. Started by ./install.sh on your computer; you can also run it on the server yourself:
#     sudo bash /opt/agent-automation/vm/install.sh            (safe to run again: finished stages are checked, not redone)
#     sudo bash /opt/agent-automation/vm/install.sh --redo X   (run one stage again: system questions hermes keys agents memory gateway jobs dashboard)
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run it with sudo" >&2; exit 1; }
cd /   # the agents' user can't read the admin's home folder (mode 750), and tools like uv look for config files in the working directory
. /opt/agent-automation/vm/lib.sh
for f in "$KIT"/vm/stages/*.sh; do . "$f"; done
umask 022

REDO=""
case "${1:-}" in
  --redo) REDO="${2:-}"; [ -n "$REDO" ] || die "--redo needs a stage name" ;;
  -h|--help) sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac

run() {  # run STAGE: once, unless --redo names it. Stages marked 'always' re-run every time (they are cheap and keep things in step).
  local s="$1" mode="${2:-once}"
  if [ "$mode" = once ] && done_stage "$s" && [ "$REDO" != "$s" ]; then return 0; fi
  "stage_$s"
  mark_stage "$s"
}

say "${B}Setting up your server${N} (log of what changed: /var/log/agent-automation.log; it never contains keys)"
exec > >(tee -a /var/log/agent-automation.log) 2>&1
chmod 600 /var/log/agent-automation.log
printf '\n--- %s vm/install.sh %s ---\n' "$(date '+%F %T')" "${*:-}"

run system once
run questions always
run hermes always     # cheap when done; re-checks the pin and the patches
run keys always       # asks only for keys that are missing (or offers to keep them)
run agents always     # settings and skills follow the kit and hermes.json; your SOUL.md edits are kept
run memory once
run gateway always
run jobs once
run dashboard always
[ "$(cj .features.phone)" = true ] && [ -x "$KIT/vm/phone/install.sh" ] && { bash "$KIT/vm/phone/install.sh" update || warn "couldn't update the phone desk"; }

step "Checking everything"
/usr/local/bin/hermes-doctor || true
say
ok "Your Hermes agents are ready. Say hello to $(cj '.agents[0].name') on Telegram: https://t.me/$(cj .bots.chief)"
[ -n "$(cj .dashboard_url)" ] && say "  Dashboard (from your own devices with Tailscale on): $(cj .dashboard_url)"
say "  Later, when you want them: voice replies (sudo hermes-voice), Gmail, Moodle (sudo hermes-addon), backups. See the README."
