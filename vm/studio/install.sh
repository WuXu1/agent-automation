#!/usr/bin/env bash
# The content studio add-on: a small team of board workers that turns raw clips, approved overlay lines and TikTok sound links into planned, finished posts the owner
# approves in the dashboard and posts by hand. Started by:   sudo hermes-addon studio        (and  sudo hermes-addon studio off)
# What it adds: the tools (/data/tools/studio, the `cy` command), the data folder (/data/studio), four profiles under the chief (Content Director, Clip Curator,
# Overlay Copywriter, Video Editor; they never chat, they only work cards from the board), a manual for them and a hand-off skill for the chief. It restarts nothing
# but the agents (quietly, when idle), starts no job, sends nothing anywhere, and costs nothing until a clip is watched (about a cent) or a card runs (pence).
# Safe to run again: profiles that exist are updated, the owner's data is never touched.
set -euo pipefail
. /opt/agent-automation/vm/lib.sh
[ "$(id -u)" = 0 ] || exec sudo "$0" "$@"

DIR=/data/studio
TOOLS=/data/tools/studio
PROFILES="contentdirector clipcurator overlaycopywriter videoeditor"
DASH_STATE="$HH/hermes-dash"

display() { case "$1" in contentdirector) echo "Content Director" ;; clipcurator) echo "Clip Curator" ;; overlaycopywriter) echo "Overlay Copywriter" ;; videoeditor) echo "Video Editor" ;; esac; }
describe() {
  case "$1" in
    contentdirector) echo "Leads the content team: plans the posts, pairs a clip, a line and a sound for each day, and reports to the chief." ;;
    clipcurator) echo "Content team: has each new clip watched once by Gemini Flash and writes down what it saw; skips clips the page cannot use." ;;
    overlaycopywriter) echo "Content team: writes new overlay lines in the owner's voice; the owner approves every one." ;;
    videoeditor) echo "Content team: makes the finished 15-second videos (the best seconds of the clip, the line laid over it)." ;;
  esac
}
org_edit() {   # org_edit add|remove : the dashboard's org chart (who reports to whom); a backup is kept beside it
  as_hermes "$HPY" - "$DASH_STATE/org.json" "$1" <<'PY'
import json, shutil, sys
from pathlib import Path
path, action = Path(sys.argv[1]), sys.argv[2]
data = json.loads(path.read_text()) if path.exists() else {"version": 1}
reports = data.setdefault("reports_to", {})
crew = {"contentdirector": "default", "clipcurator": "contentdirector", "overlaycopywriter": "contentdirector", "videoeditor": "contentdirector"}
for name, boss in crew.items():
    if action == "add":
        reports[name] = boss
    else:
        reports.pop(name, None)
data.setdefault("chat_board_added", [])
data.setdefault("pinned", ["default"])
if path.exists():
    shutil.copy2(path, path.with_name("org.json.bak-before-studio"))
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, indent=2))
PY
}
apply() {   # the chief's hand-off skill and the four profiles' files follow the feature flag, then a quiet restart
  as_hermes "$HPY" -I "$KIT/vm/hermeslib.py" configs >/dev/null
  as_hermes "$HPY" -I "$KIT/vm/hermeslib.py" skills >/dev/null
  as_hermes "$HPY" -I "$KIT/vm/hermeslib.py" studio
  /usr/local/bin/hermes-restart || warn "The agents are busy; it takes effect at the next: sudo hermes-restart"
}

if [ "${1:-}" = "off" ] || [ "${1:-}" = "--off" ]; then
  step "Switching the content studio off"
  cj_set '.features.studio' false
  for p in $PROFILES; do [ -d "$(home_of "$p")" ] && hermes_cli profile delete "$p" -y >/dev/null || true; done
  org_edit remove || true
  apply
  rm -rf "$TOOLS"
  ok "The content studio is off (its team, its tools and the chief's hand-off skill are removed). Kept $DIR: your clips, lines, sounds and posts."
  exit 0
fi

step "The content studio (clips, overlay lines and sounds into planned posts you approve)"
for f in cy cy_cli.py cy_common.py cy_ingest.py cy_plan.py cy_render.py cy_tag.py; do [ -f "$KIT/vm/tools/studio/$f" ] || die "$f is missing in $KIT/vm/tools/studio (update the kit: sudo hermes-update)"; done
for p in $PROFILES; do [ -f "$KIT/vm/studio/profiles/$p/SOUL.md" ] && [ -f "$KIT/vm/studio/profiles/$p/config.overlay.yaml" ] || die "profile files for $p are missing in $KIT/vm/studio"; done
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null || die "ffmpeg and ffprobe are needed (they come with the kit: sudo hermes-update)"
[ -x "$HPY" ] || die "the Hermes Python $HPY is missing"
[ -s "$HERMES_SETUP_JSON" ] || die "$HERMES_SETUP_JSON is missing: run the installer first"
grep -q '^DEEPSEEK_API_KEY=' "$HH/.env" || die "$HH/.env needs DEEPSEEK_API_KEY"
grep -q '^GEMINI_API_KEY=' "$HH/.env" || die "The studio needs a Gemini key (a free one: aistudio.google.com/apikey): sudo hermes-key gemini"
free_kb="$(df --output=avail -k /data | tail -1 | tr -d ' ')"
[ "$free_kb" -gt 2000000 ] || die "only $((free_kb / 1024)) MB free on /data; clips need room (about 8 MB for each 15 seconds)"
systemctl is-active --quiet hermes-gateway || warn "hermes-gateway is not running; the team's cards will not start until it is"

name="${STUDIO_NAME:-$(cj .studio.name)}"
[ -n "$name" ] || name="$(ask "What is your page called?" "My page")"
printf '%s' "$name" | grep -Eq "^[A-Za-z0-9][A-Za-z0-9 '?!.&-]{0,39}$" || die "A page name is up to 40 letters, digits, spaces and ' ? ! . & -."
brief="${STUDIO_BRIEF:-}"

umask 022
install -d -o hermes -g hermes -m 755 "$DIR" "$TOOLS"
for d in clips thumbs originals out fonts work; do install -d -o hermes -g hermes -m 755 "$DIR/$d"; done
[ -f "$DIR/settings.json" ] || printf '{}\n' | install -o hermes -g hermes -m 644 /dev/stdin "$DIR/settings.json"
as_hermes python3 - "$DIR/settings.json" "$name" "$brief" <<'PY'
import json, sys
path, name, brief = sys.argv[1:4]
d = json.load(open(path))
d["page_name"] = name
if brief:
    d["page_brief"] = brief
json.dump(d, open(path, "w"), indent=1)
PY
[ -f "$DIR/voice.md" ] || install -o hermes -g hermes -m 644 /dev/stdin "$DIR/voice.md" <<VOICE
# $name: the voice guide

The Overlay Copywriter reads this every time before writing lines. Edit it in the dashboard (Style tab) or with the agents' help.

## What the page is
(One or two sentences: what the scenes are, what the words do to the viewer.)

## How the words sound
- short: under twelve words
- plain, lower case, one question or one gentle statement
- (add what makes your lines yours)

## Never
- hashtags, links, @names, emoji
- medical or therapy claims, promises, orders
- copying a sentence from a book, a song or another page

## Example lines you approved
(The approved lines in the dashboard are the best examples; they are read automatically.)

## A book or product to mention softly (optional)
(Leave empty for none. Otherwise: its name, and one or two example pointers, e.g. "the question comes from <the book>".)
VOICE
rsync -a --delete --chown=hermes:hermes --chmod=D755,F644 --exclude=tests --exclude=__pycache__ "$KIT/vm/tools/studio/" "$TOOLS/"
chmod 755 "$TOOLS/cy" "$TOOLS/cy_cli.py"
ok "Tools in $TOOLS, your data in $DIR"

for p in $PROFILES; do
  dir="$(home_of "$p")"
  if [ ! -d "$dir" ]; then
    hermes_cli profile create "$p" --no-skills --no-alias --description "$(describe "$p")" >/dev/null
    ok "Created the profile $p ($(display "$p"))"
  fi
  [ -f "$dir/config.yaml" ] || die "$dir/config.yaml was not created"
  # only the model key (and, for the curator, the Gemini key under the tool's own name), copied by name and never printed
  tmp="$(mktemp)"
  grep -m1 '^DEEPSEEK_API_KEY=' "$HH/.env" >> "$tmp"
  [ "$p" = clipcurator ] && grep -m1 '^GEMINI_API_KEY=' "$HH/.env" | sed 's/^GEMINI_API_KEY=/STUDIO_GEMINI_KEY=/' >> "$tmp"
  [ -f "$dir/.env" ] && cp -p "$dir/.env" "$dir/.env.bak-before-studio"
  install -o hermes -g hermes -m 600 "$tmp" "$dir/.env"; rm -f "$tmp"
  (cd "$AGENT_SRC" && as_hermes "$HPY" -c '
import sys
from pathlib import Path
from hermes_cli.profiles import write_profile_meta
write_profile_meta(Path(sys.argv[1]), description=sys.argv[2], description_auto=False, display_name=sys.argv[3])' "$dir" "$(describe "$p")" "$(display "$p")")
done

cj_set '.studio.name' "$(jstr "$name")"
cj_set '.features.studio' true
org_edit add
apply
hermes_cli profile list | grep -E "contentdirector|clipcurator|overlaycopywriter|videoeditor" >/dev/null || die "the profiles are not listed"
as_hermes "$TOOLS/cy" status >/dev/null || die "the cy command does not run"
ok "The content team is ready: $(for p in $PROFILES; do printf '%s, ' "$(display "$p")"; done | sed 's/, $//')."
say "  Next: open the $name page in the dashboard, add your overlay lines, sounds and a few clips; then press Plan."
