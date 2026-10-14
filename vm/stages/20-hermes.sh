# shellcheck shell=bash
# Stage: Hermes Agent itself, pinned to one tested stable release (v0.21.5) plus three small patches, and the four profiles.
# It is pinned on purpose: `hermes update` would jump to the development branch. The git remote is switched off so an
# accidental update fails harmlessly. To move to a newer release later, see docs/UPDATING.md.

stage_hermes() {
  step "Installing Hermes Agent (pinned release $HERMES_TAG, about 5 minutes)"
  if [ ! -x /home/hermes/.local/bin/uv ]; then
    as_hermes bash -c "curl -LsSf https://astral.sh/uv/$UV_VERSION/install.sh | env UV_INSTALL_DIR=/home/hermes/.local/bin INSTALLER_NO_MODIFY_PATH=1 sh" >/dev/null
  fi
  ok "uv $(as_hermes /home/hermes/.local/bin/uv --version | cut -d' ' -f2)"

  if [ ! -d "$AGENT_SRC/.git" ]; then
    as_hermes git -c advice.detachedHead=false clone -q --depth 1 --branch "$HERMES_TAG" https://github.com/NousResearch/hermes-agent.git "$AGENT_SRC"
  fi
  [ "$(as_hermes git -C "$AGENT_SRC" rev-parse HEAD)" = "$HERMES_COMMIT" ] || die "Hermes is not at the pinned commit; refusing to go on (see docs/UPDATING.md)."
  local p name
  for p in "$KIT"/vm/hermes-patches/*.patch; do
    name="$(basename "$p")"
    if as_hermes git -C "$AGENT_SRC" apply --reverse --check "$p" 2>/dev/null; then note "patch $name already in"
    else as_hermes git -C "$AGENT_SRC" apply "$p" || die "patch $name did not apply"; ok "patch $name"; fi
  done
  as_hermes git -C "$AGENT_SRC" remote set-url origin "DISABLED-pinned-by-agent-automation--see-docs-UPDATING.md"

  # Python packages from Hermes's own lock file: the release's extras plus messaging (Telegram) and voice (speech to text).
  as_hermes bash -c "cd $AGENT_SRC && UV_PROJECT_ENVIRONMENT=$AGENT_SRC/venv /home/hermes/.local/bin/uv sync -q --extra all --extra messaging --extra voice --locked --python python3.12" \
    || die "installing Hermes's Python packages failed (above). Run the installer again; it retries."
  # The memory plugin's SDK, installed now so the plugin doesn't fetch it by itself on first use.
  as_hermes /home/hermes/.local/bin/uv pip install -q --python "$HPY" "mem0ai==2.2.1"
  as_hermes ln -sfn "$AGENT_SRC/venv/bin/hermes" /home/hermes/.local/bin/hermes
  ok "Installed: $(hermes_cli --version 2>/dev/null | head -n1)"

  # The chief's home is created by Hermes on first use; the specialists are profiles beside it.
  [ -f "$HH/config.yaml" ] || printf '_config_version: 46\n' | install -o hermes -g hermes -m 600 /dev/stdin "$HH/config.yaml"
  hermes_cli config path >/dev/null
  local role prof desc
  for role in tutor assistant coach; do
    prof="$(profile_of "$role")"
    case "$role" in
      tutor) desc="Study help: explanations, quizzes, revision plans, sources and feedback on the owner's own drafts." ;;
      assistant) desc="Everyday research with sources, planning, the task list, admin and email drafts." ;;
      coach) desc="Training, food, sleep, habits and recovery, with the weather for outdoor plans." ;;
    esac
    if [ ! -d "$HH/profiles/$prof" ]; then hermes_cli profile create "$prof" --no-alias --description "$desc" >/dev/null; ok "profile $prof"; fi
  done

  # Plugins from Hermes's catalog, each pinned to a reviewed commit: live-time (the real time on every turn) for all,
  # OpenAlex (scholarly search, no key) for the tutor.
  for prof in default tutor assistant coach; do
    [ -d "$(home_of "$prof")/plugins/live-time" ] || hermes_cli -p "$prof" plugins install live-time --ref "$LIVE_TIME_SHA" --no-enable >/dev/null 2>&1 || warn "plugin live-time did not install for $prof (the agents work without it)"
  done
  [ -d "$HH/profiles/tutor/plugins/openalex" ] || hermes_cli -p tutor plugins install openalex --ref "$OPENALEX_SHA" --no-enable >/dev/null 2>&1 || warn "plugin openalex did not install (the tutor works without it)"
  ok "Plugins: live-time (all four), openalex (tutor)"
}
