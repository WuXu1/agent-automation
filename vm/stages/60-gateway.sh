# shellcheck shell=bash
# Stage: start the agents (the Hermes gateway) and check every bot came online.

stage_gateway() {
  step "Starting your agents"
  local uid tz; uid="$(id -u hermes)"; tz="$(cj .timezone)"; tz="${tz:-UTC}"
  sed -e "s|@UID@|$uid|g" -e "s|@TZ@|$tz|g" "$KIT/vm/systemd/hermes-gateway.service" > /etc/systemd/system/hermes-gateway.service
  chmod 644 /etc/systemd/system/hermes-gateway.service
  systemctl start "user@$uid.service" 2>/dev/null || true
  systemctl daemon-reload
  systemctl enable --quiet hermes-gateway
  # A planned restart: Hermes then sends its "back online" note itself.
  printf '{"requested_at": %s, "via_service": true, "detached": false}' "$(date +%s)" | install -o hermes -g hermes -m 600 /dev/stdin "$HH/.restart_pending.json"
  systemctl restart hermes-gateway

  local i up=0
  for i in $(seq 1 36); do
    sleep 5
    systemctl is-active --quiet hermes-gateway || continue
    if curl -s -m 3 127.0.0.1:8642/health >/dev/null 2>&1; then up=1; break; fi
  done
  [ $up = 1 ] || { journalctl -u hermes-gateway -n 40 --no-pager; die "the agents didn't start (log above). Fix it, then run the installer again."; }
  ok "Gateway running"
  local log="$HH/logs/gateway.log" n
  sleep 5
  n="$(grep -ciE 'telegram.*(connected|polling|started)' "$log" 2>/dev/null || echo 0)"
  note "Telegram connections seen in the log: $n (four expected; 'sudo crew-doctor' checks properly)"
}

# Stage: the scheduled jobs: the chief's morning briefing, and one reminder before the Azure credit runs out.
stage_jobs() {
  step "Scheduled jobs"
  local have; have="$(hermes_cli cron list 2>/dev/null || true)"
  if ! printf '%s' "$have" | grep -q "Morning briefing"; then
    local t h m; t="$(ask "What time should $(cj '.agents[0].name') send your morning briefing? (HH:MM, 24-hour; 'none' to skip)" "08:00")"
    if [ "$t" != none ] && printf '%s' "$t" | grep -Eq '^([01]?[0-9]|2[0-3]):[0-5][0-9]$'; then
      h="${t%%:*}"; m="${t##*:}"; h=$((10#$h)); m=$((10#$m))
      hermes_cli cron create "$m $h * * *" "$(as_hermes "$HPY" -I "$KIT/vm/crewlib.py" briefing)" --name "Morning briefing" --deliver telegram >/dev/null \
        && ok "Morning briefing every day at $t" || warn "couldn't create the briefing; ask $(cj '.agents[0].name') to set one up"
    fi
  else ok "Morning briefing already scheduled"; fi

  if ! printf '%s' "$have" | grep -q "Azure credit"; then
    local when; when="$(date -d "+70 days" '+%Y-%m-%d 10:00')"
    hermes_cli cron create "$when" "Send $(cj .owner.name) this reminder in one or two short sentences, no tools: the server has been running about 70 days, so the \$100 Azure for Students credit is nearly used up (about \$1.25 a day). Check the balance at https://www.microsoftazuresponsorships.com/Balance and read 'Money' in the agent-automation README for what to do next." \
      --name "Azure credit check" --deliver telegram >/dev/null && ok "A reminder on $when to check your Azure credit" || true
  fi
}
