#!/usr/bin/env bash
# The guided install. Run it in a terminal on your own computer (Mac, Linux, or Ubuntu inside WSL on Windows):
#     ./install.sh
# It is safe to run again: every step checks what is already done and carries on from there.
#   1. tools on this computer (Azure CLI, Tailscale, a login key)
#   2. one small server on your Azure for Students credit
#   3. that server joins your private Tailscale network (it never gets a public port)
#   4. on the server: Hermes Agent, your four agents, their memory and the dashboard. Keys are typed there, hidden.
set -euo pipefail
KIT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$KIT_DIR/laptop/lib.sh"
. "$KIT_DIR/laptop/prereqs.sh"
. "$KIT_DIR/laptop/azure.sh"

LOG="$STATE_DIR/install.log"
case "${1:-}" in
  -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac
[ -t 0 ] || die "Run ./install.sh in a terminal window you type in (it asks questions and hidden keys). If Claude is helping you, run it yourself in a separate terminal and tell Claude what it says."

say "${B}agent-automation${N}: your own Hermes agents on a server you control."
say "This takes about 30 to 45 minutes. Have these open: README → 'Before you start' (the accounts you need)."
note "A log without any keys is kept in $LOG (Claude can read it if something goes wrong)."
exec > >(tee -a "$LOG") 2>&1
printf '\n--- %s install.sh ---\n' "$(date '+%Y-%m-%d %H:%M:%S')"

[ "$(get STEP_PREREQS)" = "done" ] && have az && [ -f "$SSH_KEY" ] && ok "Step 1 done before: tools on this computer" || prereqs
azure_login
[ "$(get STEP_VM)" = "done" ] && az vm show -g "$(get AZ_RG)" -n "$(get AZ_VM)" -o none 2>/dev/null && ok "Server '$(get AZ_VM)' exists" || create_vm
join_tailnet

step "Step 4 of 4: set up the server"
say "  Putting the kit on the server…"
ship_kit
ok "The kit lives on the server now (/opt/agent-automation)"
say "  The rest happens on the server. It asks a few questions and your keys at hidden prompts"
say "  (what you type or paste does not show; that's normal). Keys never touch this computer's disk."
# -t: a real terminal on the server so hidden prompts work. The log here still never sees a key.
vm_ssh -t "sudo bash /opt/agent-automation/vm/install.sh" </dev/tty || die "The server setup stopped (message above). Fix what it says, then run ./install.sh again: it carries on where it stopped."
put STEP_SERVER "done"

say
ok "All done."
if sync_local_kit; then
  ok "The everyday commands are kept in $STATE_DIR/kit, so this folder isn't needed any more"
  hermes_cmd="$STATE_DIR/bin/hermes"
  if [ -n "$(command -v hermes 2>/dev/null)" ] && [ "$(command -v hermes)" != "$hermes_cmd" ]; then
    warn "Another program called 'hermes' is already on this computer, so I'm not adding ours. Run ours as: $hermes_cmd status"
  elif confirm "Add the 'hermes' command to your terminal, so you can type 'hermes status' from anywhere?" y; then
    if rc="$(add_hermes_to_path)"; then ok "Added to $rc: open a new terminal window and 'hermes status' works. Until then: $hermes_cmd status"
    else warn "I couldn't tell which shell you use. Run it as: $hermes_cmd status"; fi
  else note "No problem. Run it as: $hermes_cmd status"; fi
  "$hermes_cmd" status || true
  say
  say "${B}You can delete this folder now${N}: the server has its own copy and looks after itself. Everything day to day happens in Telegram and on your dashboard. If something ever needs attention, open a terminal and type ${B}hermes status${N}, or clone this kit again and say 'help me with my setup' to Claude Code."
  say "Next: message your chief of staff on Telegram. ${B}hermes help${N} lists everyday commands (dashboard link, updates, voice later)."
else
  warn "I couldn't copy the everyday commands from the server, so keep this folder for now. Running ./hermes update later tries again."
  "$KIT_DIR/hermes" status || true
  say
  say "Next: message your chief of staff on Telegram. ${B}./hermes help${N} lists everyday commands (dashboard link, updates, voice later)."
fi
