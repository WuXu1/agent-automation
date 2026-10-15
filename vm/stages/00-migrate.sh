# shellcheck shell=bash
# Stage: move an install made before 15 Oct 2026 to the current names. Everything this kit installs used to carry a different word in its names
# (the answers file, two helper files, the server commands); now it is all "hermes". Safe to run any time: it only renames what it finds.

stage_migrate() {
  local H=/data/.hermes old=crew f d moved=0
  mv_if() { [ -e "$1" ] && [ ! -e "$2" ] && mv "$1" "$2" && moved=1 && return 0; return 1; }

  mv_if "$H/$old.json" "$H/hermes.json" && ok "Your answers file is now $H/hermes.json"
  for d in "$H" "$H"/profiles/*; do
    [ -d "$d" ] && mv_if "$d/.$old-soul-template" "$d/.hermes-soul-template"
    for f in "$d"/*.bak-before-"$old"; do [ -e "$f" ] && mv_if "$f" "${f%-before-$old}-before-hermes"; done
  done
  for f in "$H/config.yaml" "$H"/profiles/*/config.yaml; do
    [ -f "$f" ] && grep -q "vm/${old}lib.py" "$f" && sed -i "s#vm/${old}lib.py#vm/hermeslib.py#" "$f" && moved=1
  done
  mv_if "/etc/postgresql/16/main/conf.d/$old-small.conf" /etc/postgresql/16/main/conf.d/hermes-small.conf
  # the server commands: install the real hermes-* ones, then drop the old names (and any shortcuts that pointed at them)
  install -m 755 "$KIT/vm/bin/"hermes-* /usr/local/bin/
  for f in /usr/local/bin/$old-*; do [ -e "$f" ] || [ -L "$f" ] && rm -f "$f" && moved=1; done
  [ "$moved" = 1 ] && ok "Names brought up to date" || true
}
