# shellcheck shell=bash
# Stage: move an install made before 15 Oct 2026 to the current names. Everything this kit installs used to carry a different word in its names
# (the answers file, two helper files, the server commands); now it is all "hermes". Safe to run any time: it only renames what it finds.

stage_migrate() {
  local H=/data/.hermes old=crew f d moved=0
  mv_if() { if [ -e "$1" ] && [ ! -e "$2" ]; then mv "$1" "$2"; moved=1; fi; return 0; }   # always succeeds: the installer stops on any error

  if [ -e "$H/$old.json" ] && [ ! -e "$H/hermes.json" ]; then mv_if "$H/$old.json" "$H/hermes.json"; ok "Your answers file is now $H/hermes.json"; fi
  for d in "$H" "$H"/profiles/*; do
    if [ -d "$d" ]; then mv_if "$d/.$old-soul-template" "$d/.hermes-soul-template"; fi
    for f in "$d"/*.bak-before-"$old"; do if [ -e "$f" ]; then mv_if "$f" "${f%-before-$old}-before-hermes"; fi; done
  done
  for f in "$H/config.yaml" "$H"/profiles/*/config.yaml; do
    if [ -f "$f" ] && grep -q "vm/${old}lib.py" "$f"; then sed -i "s#vm/${old}lib.py#vm/hermeslib.py#" "$f"; moved=1; fi
  done
  mv_if "/etc/postgresql/16/main/conf.d/$old-small.conf" /etc/postgresql/16/main/conf.d/hermes-small.conf
  # the server commands: install the real hermes-* ones, then drop the old names (and any shortcuts that pointed at them)
  install -m 755 "$KIT/vm/bin/"hermes-* /usr/local/bin/
  for f in /usr/local/bin/$old-*; do if [ -e "$f" ] || [ -L "$f" ]; then rm -f "$f"; moved=1; fi; done
  if [ "$moved" = 1 ]; then ok "Names brought up to date"; fi
}
