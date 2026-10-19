# Helpers shared by hermes-addon-backup and hermes-restore. Sourced after /opt/agent-automation/vm/lib.sh, never run. Runs as root.
# shellcheck shell=bash disable=SC2034   # the BK_* names are used by the scripts that source this

BK_CONF=/etc/hermes-backup                  # root only: passphrase, rclone.conf (the Google Drive sign-in), keep-days
BK_OUT=/var/backups/hermes-backup           # last-status
BK_FOLDER=agent-automation-backups        # the folder in your Google Drive
BK_LOCK=/run/hermes-backup.lock             # the nightly backup and a restore never run at the same time

# read_hidden "Prompt" -> exactly what was typed, on stdout (spaces kept, unlike ask_secret). Never shown, never on a command line.
read_hidden() {
  local v
  printf '%s  🔑 %s (hidden, nothing shows as you type; then Enter):%s ' "$B" "$1" "$N" >&2
  IFS= read -rs v </dev/tty || v=""
  printf '\n' >&2
  printf '%s' "$v"
}

# read_token -> the text `rclone authorize` printed on the laptop, pasted at a hidden prompt. Copes with a paste of one line (the
# {...} line) or of the whole block with the "Paste the following" and "<---End paste" lines around it.
read_token() {
  local line all="" _i
  printf '%s  🔑 Paste what rclone printed on your laptop (the line that starts with {"access_token"; hidden), then Enter:%s ' "$B" "$N" >&2
  for _i in 1 2 3 4 5 6; do
    IFS= read -rs line </dev/tty || break
    [ -z "$line" ] && [ -z "$all" ] && break
    all="$all$line"
    case "$line" in *'}'*) break ;; esac
  done
  while IFS= read -rs -t 0.5 line </dev/tty; do :; done      # swallow the rest of a longer paste ("<---End paste")
  printf '\n' >&2
  printf '%s' "$all"
}

ensure_rclone() {
  command -v rclone >/dev/null && return 0
  say "  Installing rclone (the tool that talks to Google Drive; Ubuntu's own package)…"
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rclone >/dev/null 2>&1 \
    || { apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rclone >/dev/null; } \
    || die "rclone could not be installed (sudo apt install rclone shows why)."
  command -v gpg >/dev/null || DEBIAN_FRONTEND=noninteractive apt-get install -y -qq gnupg >/dev/null
  ok "rclone installed ($(rclone version 2>/dev/null | head -n1))"
}

# rclone_conf_from_token: the pasted text on stdin -> an rclone.conf on stdout (remote "gdrive", scope drive.file). The token goes
# through stdin and a root-only file only, never a command line.
rclone_conf_from_token() {
  python3 -I -c '
import base64, json, re, sys
raw = sys.stdin.read()
t = None
m = re.search(r"\{.*\}", raw, re.S)
if m:
    try:
        t = json.loads(m.group(0))
    except ValueError:
        t = None
if t is None:                                    # some rclone versions print a base64 blob instead of the {...} text
    s = re.sub(r"\s+", "", raw)
    try:
        t = json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode())
    except Exception:
        t = None
if isinstance(t, dict) and isinstance(t.get("token"), str):
    try:
        t = json.loads(t["token"])
    except ValueError:
        pass
if not isinstance(t, dict) or not (t.get("refresh_token") or t.get("access_token")):
    sys.exit("That is not the sign-in text rclone printed (it starts with {\"access_token\").")
if not t.get("access_token"):
    t.update(access_token="", token_type="Bearer", expiry="2000-01-01T00:00:00Z")
print("[gdrive]\ntype = drive\nscope = drive.file\ntoken = " + json.dumps(t, separators=(",", ":")))
'
}

# rclone_ok FILE: does this sign-in work? (lists the folders rclone may see, then makes sure the backup folder exists)
rclone_ok() {
  local f="$1" err; err="$(mktemp "$BK_CONF/err.XXXXXX")"
  if rclone --config "$f" lsd gdrive: >/dev/null 2>"$err" && rclone --config "$f" mkdir "gdrive:$BK_FOLDER" 2>>"$err"; then
    rm -f "$err"; return 0
  fi
  warn "Google did not accept it. What rclone said (no secrets):"
  sed -E 's/(token|secret|key)[^ ]*/\1 …/Ig' "$err" | grep -v '^$' | tail -n 3 >&2
  rm -f "$err"; return 1
}

# setup_drive: ask for the token from the laptop, check it, save it as $BK_CONF/rclone.conf. Returns 1 if the owner gave up.
setup_drive() {
  install -d -m 700 "$BK_CONF"
  say "  The server has no web browser, so you sign in to Google on your laptop and paste the result here:"
  say "    1. On your laptop, in a ${B}new${N} terminal:  ${B}hermes backup-login${N}"
  note "   (or: bash vm/backup/laptop-authorize.sh). A Google page opens: pick the account for the backups and Allow."
  say "    2. rclone then prints a line that starts with ${B}{\"access_token\"${N}. Copy that whole line."
  say "    3. Paste it below (nothing shows; that's normal) and press Enter."
  note "The permission is Google's narrow 'drive.file': rclone sees only the files it makes itself, never the rest of your Drive."
  local tries tmp
  for tries in 1 2 3; do
    tmp="$(mktemp "$BK_CONF/rclone.conf.XXXXXX")"
    if ! read_token | rclone_conf_from_token > "$tmp"; then
      rm -f "$tmp"; warn "Try again (copy the whole {...} line)."; continue
    fi
    if rclone_ok "$tmp"; then
      chmod 600 "$tmp"; mv -f "$tmp" "$BK_CONF/rclone.conf"      # rclone may have refreshed the token while checking: keep its file
      ok "Google Drive connected: the folder '$BK_FOLDER' is in your Drive (My Drive)"
      return 0
    fi
    rm -f "$tmp"
    [ "$tries" -lt 3 ] && warn "Run hermes backup-login on your laptop again for a fresh token, then paste it here."
  done
  return 1
}

drive_ok() { [ -s "$BK_CONF/rclone.conf" ] && rclone --config "$BK_CONF/rclone.conf" lsd gdrive: >/dev/null 2>&1; }
