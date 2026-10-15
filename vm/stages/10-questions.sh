# shellcheck shell=bash
# Stage: the owner's answers (name, pronouns, place, the agents' names). Saved in /data/.hermes/hermes.json, which holds no secrets.

stage_questions() {
  step "About you and your agents"
  if [ -s "$HERMES_SETUP_JSON" ] && [ -n "$(cj .owner.name)" ] && [ -n "$(cj '.agents[3].name')" ]; then
    ok "Answers saved before: $(cj .owner.name), with $(jq -r '[.agents[].name] | join(", ")' "$HERMES_SETUP_JSON")"
    confirm "Keep them?" y && return 0
  fi
  install -d -o hermes -g hermes -m 700 "$HH"

  local name pron tz place studies
  name="$(ask "Your first name (the agents call you this)" "$(cj .owner.name)")"
  until printf '%s' "$name" | grep -Eq "^[A-Za-z][A-Za-z0-9 '\-]{0,23}$"; do name="$(ask "Letters please (24 at most). Your first name" "")"; done
  say "  Pronouns: 1) he/him  2) she/her  3) they/them  (or type your own)"
  pron="$(ask "Which?" "3")"
  case "$pron" in 1) pron="he/him" ;; 2) pron="she/her" ;; 3|"") pron="they/them" ;; esac
  local oid; oid="$(printf '%s' "$name" | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9' | cut -c1-20)"; [ -n "$oid" ] || oid=owner
  cj_set '.version' 1
  cj_set '.owner.name' "$(jstr "$name")"; cj_set '.owner.id' "$(jstr "$oid")"; cj_set '.owner.pronouns' "$(jstr "$pron")"

  tz="$(ask "Your timezone" "$(cj .timezone || true)")"; tz="${tz:-Europe/London}"
  until [ -f "/usr/share/zoneinfo/$tz" ]; do tz="$(ask "Not a timezone I know. Like Europe/London or Europe/Dublin" "Europe/London")"; done
  cj_set '.timezone' "$(jstr "$tz")"
  timedatectl set-timezone "$tz" 2>/dev/null || true

  # Home place, for the weather helper: looked up on Open-Meteo (free, no key) so the agents get exact coordinates.
  while :; do
    place="$(ask "Your town or city (for the weather)" "$(cj .home.name)")"
    [ -n "$place" ] || { warn "Skipped: the weather helper will ask for a place each time."; break; }
    local hits; hits="$(curl -s -m 15 -G https://geocoding-api.open-meteo.com/v1/search --data-urlencode "name=$place" -d count=5 -d language=en -d format=json \
                        | jq -r '.results[]? | [.name, (.admin1 // ""), .country, .latitude, .longitude] | @tsv')"
    if [ -z "$hits" ]; then warn "I couldn't find '$place'. Try a nearby bigger town."; continue; fi
    printf '%s\n' "$hits" | awk -F'\t' '{printf "    %d) %s, %s, %s\n", NR, $1, $2, $3}'
    local pick line; pick="$(ask "Which one? (number)" "1")"
    line="$(printf '%s\n' "$hits" | sed -n "${pick}p")"; [ -n "$line" ] || continue
    cj_set '.home' "$(printf '%s' "$line" | jq -R 'split("\t") | {name: .[0], region: .[1], country: .[2], lat: (.[3]|tonumber), lon: (.[4]|tonumber)}')"
    ok "Home: $(cj .home.name), $(cj .home.country)"; break
  done
  [ "$(cj .home.country)" = "United States" ] && cj_set '.wind_unit' '"mph"'
  case "$(cj .home.country)" in "United Kingdom") cj_set '.wind_unit' '"mph"' ;; esac

  studies="$(ask "What and where do you study? (one line, e.g. '1st year Law at Leeds'; Enter to skip)" "$(cj .studies)")"
  cj_set '.studies' "$(jstr "${studies:-not given}")"

  say
  say "  Now name your four agents. Each gets its own Telegram bot with this name. Press Enter to keep a suggestion."
  local role title def n id i=0
  for role in $ROLES; do
    case "$role" in
      chief) title="Chief of Staff"; def="Atlas" ;;   tutor) title="Tutor"; def="Sage" ;;
      assistant) title="Assistant"; def="Ivy" ;;      coach) title="Coach"; def="Rocky" ;;
    esac
    n="$(cj ".agents[$i].name")"; n="$(ask "$title's name" "${n:-$def}")"
    until printf '%s' "$n" | grep -Eq "^[A-Za-z][A-Za-z0-9 '\-]{0,23}$"; do n="$(ask "Letters please. $title's name" "$def")"; done
    id="$(printf '%s' "$n" | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9' | cut -c1-24)"
    case "$id" in [a-z]*) ;; *) id="agent$i" ;; esac
    case " default user worker dashboard all none test helper owner tutor assistant coach chief $oid " in *" $id "*) id="${id}bot" ;; esac
    cj_set ".agents[$i]" "$(jq -n --arg id "$id" --arg p "$(profile_of "$role")" --arg r "$role" --arg n "$n" --arg t "$title" \
                              '{id: $id, profile: $p, role: $r, name: $n, title: $t}')"
    i=$((i+1))
  done
  [ -n "$(cj .features)" ] || cj_set '.features' '{"voice": false, "gmail": false, "moodle": false, "icloud": false, "backup": false}'
  cj_set '.installed_at' "$(jstr "$(date -u +%F)")"

  # The Tailscale account that owns this server is the only one the dashboard lets in.
  local login; login="$(tailscale status --json 2>/dev/null | jq -r '.User[(.Self.UserID|tostring)].LoginName // empty')"
  [ -n "$login" ] && cj_set '.owner.tailscale_login' "$(jstr "$login")"
  chown hermes:hermes "$HERMES_SETUP_JSON"; chmod 640 "$HERMES_SETUP_JSON"
  ok "Saved: you are $name ($pron); your agents are $(jq -r '[.agents[].name] | join(", ")' "$HERMES_SETUP_JSON")"
}
