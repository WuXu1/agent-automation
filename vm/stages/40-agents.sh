# shellcheck shell=bash
# Stage: the four agents' settings, personalities, skills and tools, from crew.json and the kit's templates.

stage_agents() {
  step "Setting up your four agents"
  local bad; bad="$(as_hermes "$HPY" -I "$KIT/vm/crewlib.py" check-names)" || die "crew.json has a problem: $bad (run the installer again to re-answer)"
  as_hermes "$HPY" -I "$KIT/vm/crewlib.py" configs | sed 's/^/    /'
  as_hermes "$HPY" -I "$KIT/vm/crewlib.py" souls | sed 's/^/    /'
  as_hermes "$HPY" -I "$KIT/vm/crewlib.py" skills >/dev/null
  as_hermes "$HPY" -I "$KIT/vm/crewlib.py" workspace
  local prof skill
  for prof in default tutor assistant coach; do
    case "$prof" in default) skill=team-lead ;; *) skill=$prof ;; esac
    hermes_cli -p "$prof" curator pin "$skill" >/dev/null 2>&1 || true     # the background tidier never edits a role skill
  done
  ok "Settings, personalities (SOUL.md) and role skills written"

  # Small helpers the agents run themselves (standard library only).
  install -d -o hermes -g hermes -m 755 "$DATA/tools/weather" "$DATA/tools/gmail"
  install -o hermes -g hermes -m 755 "$KIT/vm/tools/weather/forecast.py" "$DATA/tools/weather/forecast.py"
  install -o hermes -g hermes -m 755 "$KIT/vm/tools/gmail/gmail_read.py" "$DATA/tools/gmail/gmail_read.py"
  ok "Tools: weather (Open-Meteo, free), Gmail reader (switched on later with: sudo crew-addon gmail)"
}
