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
"$KIT_DIR/hermes" status || true
say
say "${B}You can delete this folder now${N}: the server has its own copy and updates itself. To connect later: ssh $(vm_user)@$(vm_ip), then ${B}sudo hermes-doctor${N} (health), ${B}sudo hermes-update${N} (update), ${B}sudo hermes-addon${N} (Gmail, Moodle, backups)."
say "Next: message your chief of staff on Telegram. ${B}./hermes help${N} lists everyday commands (dashboard link, updates, voice later)."
