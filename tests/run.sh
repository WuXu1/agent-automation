#!/usr/bin/env bash
# Every check that runs without a server: shell syntax, then the Python tests. Run from anywhere: bash tests/run.sh
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
for f in install.sh hermes laptop/*.sh vm/*.sh vm/stages/*.sh vm/bin/hermes-* vm/backup/hermes-backup vm/backup/hermes-addon-backup vm/backup/hermes-restore vm/backup/*.sh vm/tools/moodle/*.sh dashboard/bridge/deploy/*.sh; do
  [ -f "$f" ] || continue
  bash -n "$f" || { echo "syntax error: $f"; fail=1; }
done
command -v shellcheck >/dev/null && { shellcheck -S error install.sh hermes laptop/*.sh vm/*.sh vm/stages/*.sh vm/bin/hermes-* || fail=1; }
python3 -c "import yaml" 2>/dev/null || { echo "(installing PyYAML for the tests)"; python3 -m pip install -q pyyaml; }
python3 -B -m unittest discover -s tests || fail=1
python3 -B -m unittest discover -s vm/tools/weather || fail=1
python3 -B -m unittest discover -s vm/plugins/crew-voice/tests || fail=1
python3 -B -m unittest discover -s dashboard/bridge/tests || fail=1
[ $fail = 0 ] && echo "ALL CHECKS PASSED" || { echo "SOME CHECKS FAILED"; exit 1; }
