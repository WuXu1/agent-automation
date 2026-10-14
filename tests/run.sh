#!/usr/bin/env bash
# Every check that runs without a server: shell syntax, then the Python tests. Run from anywhere: bash tests/run.sh
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
for f in install.sh crew laptop/*.sh vm/*.sh vm/stages/*.sh vm/bin/crew-* vm/backup/crew-backup vm/backup/crew-addon-backup vm/backup/crew-restore vm/backup/*.sh vm/tools/moodle/*.sh dashboard/bridge/deploy/*.sh; do
  [ -f "$f" ] || continue
  bash -n "$f" || { echo "syntax error: $f"; fail=1; }
done
command -v shellcheck >/dev/null && { shellcheck -S error install.sh crew laptop/*.sh vm/*.sh vm/stages/*.sh vm/bin/crew-* || fail=1; }
python3 -c "import yaml" 2>/dev/null || { echo "(installing PyYAML for the tests)"; python3 -m pip install -q pyyaml; }
python3 -B -m unittest discover -s tests || fail=1
python3 -B -m unittest discover -s vm/tools/weather || fail=1
python3 -B -m unittest discover -s vm/plugins/crew-voice/tests || fail=1
python3 -B -m unittest discover -s dashboard/bridge/tests || fail=1
[ $fail = 0 ] && echo "ALL CHECKS PASSED" || { echo "SOME CHECKS FAILED"; exit 1; }
