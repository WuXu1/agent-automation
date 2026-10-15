# shellcheck shell=bash
# Stage: the keys. Each is typed at a hidden prompt, checked against its service, and written straight into the .env file of the
# agent(s) that need it (mode 600, owned by hermes). Nothing is printed, logged, or put in hermes.json.

check_deepseek() { [ "$(curl_status "url = \"https://api.deepseek.com/models\"
header = \"Authorization: Bearer $1\"")" = 200 ]; }
check_gemini() { [ "$(curl_status "url = \"https://generativelanguage.googleapis.com/v1beta/models?pageSize=1\"
header = \"x-goog-api-key: $1\"")" = 200 ]; }
tg_api() {  # tg_api TOKEN METHOD [extra curl config lines]
  curl_body "url = \"https://api.telegram.org/bot$1/$2\"
${3:-}"
}

key_for_all() {  # key_for_all KEY  (value on stdin): the same key in all four agents' .env files
  local v r; v="$(cat)"
  for r in $ROLES; do printf '%s\n' "$v" | env_set "$(env_of "$r")" "$1"; done
}

stage_keys() {
  step "Your keys (typed hidden; checked before they're saved)"
  local chief_env; chief_env="$(env_of chief)"

  # DeepSeek: the agents' brain. Required.
  if env_has "$chief_env" DEEPSEEK_API_KEY && confirm "A DeepSeek key is saved. Keep it?" y; then ok "DeepSeek key kept"
  else
    say "  ${B}DeepSeek${N} runs the agents (a few pence a day for normal use; you top up a balance, there's no subscription)."
    say "  Make a key at https://platform.deepseek.com/api_keys (top up \$2-5 first under Top up)."
    local k
    while :; do
      k="$(ask_secret "DeepSeek API key")"
      [ -n "$k" ] || die "A DeepSeek key is required. Run the installer again when you have one."
      if check_deepseek "$k"; then break; fi
      warn "DeepSeek didn't accept that key (or has no balance yet). Try again."
    done
    printf '%s\n' "$k" | key_for_all DEEPSEEK_API_KEY; k=""
    ok "DeepSeek key saved"
  fi

  # Gemini: a free backup brain when DeepSeek is down. Optional but recommended.
  if env_has "$chief_env" GEMINI_API_KEY; then ok "Gemini backup key saved before"; cj_set '.has_gemini' true
  elif [ -n "${HERMES_SETUP_UNATTENDED:-}" ]; then cj_set '.has_gemini' false
  else
    say "  ${B}Gemini${N} (Google) is the free backup: if DeepSeek is down, the agents quietly switch to it."
    say "  Make a key at https://aistudio.google.com/apikey (free tier is enough). Press Enter to skip."
    local g
    while :; do
      g="$(ask_secret "Gemini API key (Enter to skip)")"
      [ -n "$g" ] || { warn "Skipped: no backup brain. Add it later with: sudo hermes-key gemini"; cj_set '.has_gemini' false; break; }
      if check_gemini "$g"; then printf '%s\n' "$g" | key_for_all GEMINI_API_KEY; cj_set '.has_gemini' true; ok "Gemini key saved"; break; fi
      warn "Google didn't accept that key. Try again, or press Enter to skip."
    done
    g=""
  fi

  stage_telegram
}

stage_telegram() {
  step "Telegram: one bot per agent"
  say "  You'll talk to each agent in its own Telegram chat. Bots are free and made in Telegram itself:"
  say "  open ${B}@BotFather${N} (https://t.me/BotFather), send ${B}/newbot${N}, give the name below and any username"
  say "  ending in 'bot'. BotFather replies with a token (looks like 123456789:AAE…): paste it here."
  local i=0 role name envf tok me uname
  for role in $ROLES; do
    name="$(cj ".agents[$i].name")"; envf="$(env_of "$role")"; i=$((i+1))
    if env_has "$envf" TELEGRAM_BOT_TOKEN && [ -n "$(cj ".bots.$role")" ]; then ok "$name: @$(cj ".bots.$role") (saved before)"; continue; fi
    say
    say "  ${B}$name${N} ($(cj ".agents[$((i-1))].title")): in BotFather send /newbot, name it '$name'."
    while :; do
      tok="$(ask_secret "$name's bot token")"
      printf '%s' "$tok" | grep -Eq '^[0-9]{6,12}:[A-Za-z0-9_-]{30,}$' || { warn "That doesn't look like a bot token. Copy the whole line BotFather sent."; continue; }
      me="$(tg_api "$tok" getMe)"
      uname="$(printf '%s' "$me" | jq -r '.result.username // empty')"
      [ -n "$uname" ] && break
      warn "Telegram didn't accept that token. Try again."
    done
    if grep -rqs "$(printf '%s' "$tok" | cut -d: -f1):" "$HH/.env" "$HH"/profiles/*/.env 2>/dev/null && ! env_has "$envf" TELEGRAM_BOT_TOKEN; then
      die "That bot is already used by another of your agents. Each agent needs its own bot: make a new one in BotFather."
    fi
    printf '%s\n' "$tok" | env_set "$envf" TELEGRAM_BOT_TOKEN
    # Tidy the bot's profile: its display name and a one-line description (both public, both harmless).
    tg_api "$tok" setMyName "data-urlencode = \"name=$name\"" >/dev/null || true
    tg_api "$tok" setMyShortDescription "data-urlencode = \"short_description=$(cj ".agents[$((i-1))].title") in $(cj .owner.name)'s private Hermes team.\"" >/dev/null || true
    cj_set ".bots.$role" "$(jstr "$uname")"
    tok=""
    ok "$name: @$uname"
  done

  # Who may talk to the bots: only the owner's Telegram account. We read its id from a message to the chief's bot.
  local tid; tid="$(cj .telegram_user_id)"
  if [ -z "$tid" ]; then
    local ctok; ctok="$(env_get "$(env_of chief)" TELEGRAM_BOT_TOKEN)"
    systemctl stop hermes-gateway 2>/dev/null || true      # it would take the message before we see it
    tg_api "$ctok" deleteWebhook >/dev/null || true
    say
    say "  Last bit: open ${B}https://t.me/$(cj .bots.chief)${N} on your phone, press ${B}Start${N} (or send 'hi')."
    say "  That tells the bots it's you; nobody else will be able to use them."
    local upd who n=0
    while [ $n -lt 60 ]; do
      upd="$(tg_api "$ctok" getUpdates "data = \"timeout=10\"")"
      tid="$(printf '%s' "$upd" | jq -r '[.result[]? | (.message // .edited_message) | select(.chat.type == "private") | .from][-1].id // empty')"
      [ -n "$tid" ] && break
      n=$((n+1))
    done
    [ -n "$tid" ] || die "No message arrived at @$(cj .bots.chief). Run the installer again and press Start in that chat."
    who="$(printf '%s' "$upd" | jq -r '[.result[]? | (.message // .edited_message) | .from][-1] | "\(.first_name // "") \(.last_name // "") (@\(.username // "no username"))"')"
    confirm "Is this you on Telegram: $who?" y || die "Then someone else messaged the bot first. Run the installer again and send the first message yourself."
    cj_set '.telegram_user_id' "$(jstr "$tid")"
    # Mark the updates as read so the gateway doesn't answer that 'hi' twice.
    local last; last="$(printf '%s' "$upd" | jq -r '[.result[]?.update_id] | max // empty')"
    [ -n "$last" ] && tg_api "$ctok" getUpdates "data = \"offset=$((last+1))\"" >/dev/null || true
    ctok=""
  fi
  for role in $ROLES; do
    printf '%s\n' "$tid" | env_set "$(env_of "$role")" TELEGRAM_ALLOWED_USERS
    printf '%s\n' "$tid" | env_set "$(env_of "$role")" TELEGRAM_HOME_CHANNEL
  done
  ok "Only your Telegram account ($tid) can talk to the bots"

  # Hermes's local API (the dashboard uses it): on this machine only, a separate random key per agent.
  local f
  for role in $ROLES; do
    f="$(env_of "$role")"
    env_has "$f" API_SERVER_KEY || openssl rand -hex 32 | env_set "$f" API_SERVER_KEY
  done
  f="$(env_of chief)"
  echo true | env_set "$f" API_SERVER_ENABLED; echo 127.0.0.1 | env_set "$f" API_SERVER_HOST; echo 8642 | env_set "$f" API_SERVER_PORT
}
