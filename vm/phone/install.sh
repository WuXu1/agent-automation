#!/usr/bin/env bash
# The chief can be rung, and can ring you (docs/PHONE.md). Called by `sudo hermes-addon phone`.
#   sudo hermes-addon phone           set it up (safe to run again: it only fills in what is missing)
#   sudo hermes-addon phone number    give the phone agent a Twilio number (the Twilio login is typed once and not stored)
#   sudo hermes-addon phone voice     choose a different voice for the chief (changes the ElevenLabs agents too)
#   sudo hermes-addon phone update    copy the newest desk code in and restart it quietly (hermes-update does this by itself)
#   sudo hermes-addon phone off       switch it off (the code and the settings stay)
# Money: ElevenLabs minutes (they come out of the ElevenLabs plan), a Twilio number and its per-minute calls.
set -euo pipefail
. /opt/agent-automation/vm/lib.sh
[ "$(id -u)" = 0 ] || exec sudo "$0" "$@"
SRC="$KIT/vm/phone"; DEST=/data/tools/voice-desk; STATE="$HH/voice-desk"; PORT=8800
mode="${1:-setup}"
chief="$(cj '.agents[0].name')"; owner="$(cj .owner.name)"

in_desk() { ( cd "$DEST" && as_hermes "$@" ); }
desk_admin() { in_desk python3 -m desk.admin --state-dir "$STATE" "$@"; }

render_code() {   # the desk's files with the names filled in, then the service unit
  install -d -o hermes -g hermes -m 755 "$DEST"
  python3 "$SRC/render.py" "$SRC" "$DEST.new" --setup "$HERMES_SETUP_JSON" >/dev/null
  rm -rf "$DEST.new/tests" "$DEST.new/desk/tests" "$DEST.new/render.py" "$DEST.new/install.sh" "$DEST.new/voice-desk.service"
  rm -rf "$DEST/desk" "$DEST/agents"; mv "$DEST.new/desk" "$DEST/desk"; mv "$DEST.new/agents" "$DEST/agents"
  mv -f "$DEST.new/STYLE.md" "$DEST/STYLE.md"; rm -rf "$DEST.new"
  chown -R hermes:hermes "$DEST"
  install -m 644 "$SRC/voice-desk.service" /etc/systemd/system/voice-desk.service
  systemctl daemon-reload
}

quiet_restart() {   # restart the desk only when no call is going on
  local n; n="$(desk_admin status 2>/dev/null | jq -r '.active_calls // 0' 2>/dev/null || echo 0)"
  if [ "$n" = 0 ]; then systemctl restart voice-desk; else warn "A call is in progress: restart later with: sudo systemctl restart voice-desk"; fi
}

pick_voice() {   # asks which ElevenLabs voice the chief speaks with; saves it in the setup file
  local key voices pick vid
  key="$(env_get "$(env_of chief)" ELEVENLABS_API_KEY)"
  voices="$(curl_body "url = \"https://api.elevenlabs.io/v1/voices\"
header = \"xi-api-key: $key\"" | jq -r '.voices[] | [.voice_id, .name, ((.labels // {}) | [.gender, .accent, .description] | map(select(. != null)) | join(", "))] | @tsv')"
  [ -n "$voices" ] || die "Couldn't list your ElevenLabs voices."
  say "  Pick $chief's voice (add voices from ElevenLabs' Voice Library first if none suits):"
  printf '%s\n' "$voices" | awk -F'\t' '{printf "   %2d) %-18s %s\n", NR, $2, $3}'
  while :; do
    pick="$(ask "Voice for $chief (number)" "1")"
    vid="$(printf '%s\n' "$voices" | sed -n "${pick}p" | cut -f1)"
    printf '%s' "$vid" | grep -Eq '^[A-Za-z0-9]{10,40}$' && break
    warn "Pick a number from the list."
  done
  cj_set '.voices.chief' "$(jstr "$vid")"
}

case "$mode" in
  voice)
    [ "$(cj .features.phone)" = true ] || die "Set the phone line up first: sudo hermes-addon phone"
    env_has "$(env_of chief)" ELEVENLABS_API_KEY || die "ElevenLabs first: sudo hermes-key elevenlabs"
    pick_voice
    as_hermes python3 -c "import sys; sys.path.insert(0, '$DEST'); from desk import config; config.update_config_json('$STATE', {'voice_id': '$(cj .voices.chief)'})"
    in_desk python3 -m desk.push_agent --state-dir "$STATE" --agents-dir "$DEST/agents" --style "$DEST/STYLE.md" || die "Updating the ElevenLabs agents failed (above)."
    quiet_restart; ok "$chief now speaks with the new voice."; exit 0 ;;
  off)
    systemctl disable --now voice-desk >/dev/null 2>&1 || true
    tailscale funnel --https=8443 off >/dev/null 2>&1 || true
    cj_set '.features.phone' false; ok "Phone line off (the desk's code and settings stay; the number still points at ElevenLabs)."; exit 0 ;;
  update)
    [ "$(cj .features.phone)" = true ] || exit 0
    render_code; quiet_restart; ok "Phone desk updated."; exit 0 ;;
  number)
    [ "$(cj .features.phone)" = true ] || die "Set the phone line up first: sudo hermes-addon phone"
    step "A number for $chief's phone"
    say "  The number must already be in your Twilio account (a UK number needs Twilio's address and regulatory bundle approved)."
    say "  Your Twilio account SID and auth token are used once, to let ElevenLabs answer the number, and are not kept on this server."
    num="$(ask "The number, with country code (for example +44141...)" "")"
    printf '%s' "$num" | tr -d ' ' | grep -Eq '^\+[0-9]{10,15}$' || die "That doesn't look like a number with a country code. Nothing changed."
    sid="$(ask_secret "Twilio account SID (starts AC)")"; printf '%s' "$sid" | grep -Eq '^AC[0-9a-f]{32}$' || die "That isn't an account SID. Nothing changed."
    tok="$(ask_secret "Twilio auth token")"
    printf '%s\n%s\n' "$sid" "$tok" | in_desk python3 -m desk.number --state-dir "$STATE" import "$(printf '%s' "$num" | tr -d ' ')" || die "ElevenLabs refused it (above)."
    sid=""; tok=""; quiet_restart
    ok "Done: ring that number and $chief answers. To try a call out: sudo -u hermes python3 -m desk.admin test-call (see docs/PHONE.md)"; exit 0 ;;
  setup) ;;
  *) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac

step "Phone line for $chief"
say "  $chief answers a number you ring, can ring you back with results, and (with your yes each time) can ring people you add to a contact book."
say "  ${B}Money:${N} calls use ElevenLabs minutes (your plan's), and a Twilio number costs a little a month plus per-minute call charges."
say "  The desk keeps your number and its secrets on this server only."
confirm "Set it up?" y || { say "  Nothing changed."; exit 0; }

ek="$(env_of chief)"
env_has "$ek" ELEVENLABS_API_KEY || die "ElevenLabs first: sudo hermes-key elevenlabs"
key="$(env_get "$ek" ELEVENLABS_API_KEY)"
command -v tailscale >/dev/null || die "Tailscale isn't installed on this server."

# 1. a voice for the chief
env_has "$ek" ELEVENLABS_API_KEY || true
voice="$(cj .voices.chief)"
[ -n "$voice" ] || { pick_voice; voice="$(cj .voices.chief)"; }
key=""

# 2. the code, the folder for its settings and secrets
render_code
dns="$(tailscale status --json | jq -r '.Self.DNSName' | sed 's/\.$//')"
[ -n "$dns" ] && [ "$dns" != null ] || die "Couldn't read this server's Tailscale name."
base="https://$dns:8443"
desk_admin init --public-base "$base" >/dev/null
as_hermes python3 -c "import sys; sys.path.insert(0, '$DEST'); from desk import config; config.update_config_json('$STATE', {'voice_id': '$voice'})"

# 3. the owner's own number (the one that gets the brief and the call-backs)
if [ -z "$(jq -r '.max_number // empty' "$STATE/config.json" 2>/dev/null)" ]; then
  say "  Your own mobile number is the one $chief treats as you (anyone else gets message-taking). Typed here, kept only on this server."
  while :; do
    mine="$(ask_secret "Your mobile number, with country code (e.g. +447...)")"
    printf '%s' "$mine" | grep -Eq '^(\+|0)[0-9]{9,14}$' && break
    warn "That doesn't look like a phone number."
  done
  printf '%s\n' "$mine" | desk_admin set-owner-number --stdin >/dev/null 2>&1; mine=""
fi

# 4. a public address for ElevenLabs to reach the desk: Tailscale Funnel on port 8443
out="$(timeout 40 tailscale funnel --bg --https=8443 "$PORT" 2>&1 || true)"
for _ in $(seq 1 20); do   # the first time, Tailscale needs a little while to get the address's certificate
  tailscale funnel status 2>/dev/null | grep -q ":8443 (Funnel on)" && break
  sleep 3
done
if ! tailscale funnel status 2>/dev/null | grep -q ":8443 (Funnel on)"; then
  warn "Tailscale Funnel isn't switched on for this server yet. It lets ElevenLabs (not the public) reach the phone desk."
  printf '%s\n' "$out" | grep -o 'https://login.tailscale.com[^ ]*' | head -1 | sed 's/^/    Open: /' >&2 || true
  say "  An admin of your Tailscale network does this once: admin console -> Access controls -> add the 'funnel' attribute for this machine"
  say "  (tailscale.com/kb/1223/funnel). Then run this again: sudo hermes-addon phone"
  cj_set '.features.phone' false
  exit 1
fi
ok "Public address ready: $base"

# 5. start the desk, then create everything ElevenLabs needs (idempotent)
systemctl enable --now voice-desk >/dev/null 2>&1
for _ in $(seq 1 20); do curl -s -m 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break; sleep 1; done
curl -s -m 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 || die "The desk didn't start. Look: journalctl -u voice-desk -n 30"
in_desk python3 -m desk.push_agent --state-dir "$STATE" --agents-dir "$DEST/agents" --style "$DEST/STYLE.md" || die "Creating the ElevenLabs agents failed (above)."
desk_admin dial-mode live >/dev/null; desk_admin notify-mode live >/dev/null
systemctl restart voice-desk; sleep 3
desk_admin self-check || warn "The self-check flagged something (above)."
cj_set '.features.phone' true
ok "The phone desk is running and $chief's phone agents exist in ElevenLabs."
say "  Last step: give it a number. If it is a Twilio number in your account: sudo hermes-addon phone number"
