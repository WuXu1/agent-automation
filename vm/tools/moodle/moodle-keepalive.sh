#!/bin/bash
# Keeps the agents' Moodle session alive (any page load refreshes it). A script-only job on the tutor every 30 minutes:
# silent while the session works; one message when it has ended. @URL@ is filled in by `hermes-addon moodle`.
# The job may not get the cookie in its environment: then read it from the tutor's own .env (this runs as hermes).
# With `hermes-addon moodle-login` set up, an ended session is renewed by itself (uni-login request) and the owner is only
# told when that fails (once per reason per 12 hours).
[ -n "${MOODLE_TOKEN:-}" ] || MOODLE_TOKEN="$(sed -n 's/^MOODLE_TOKEN=//p' /data/.hermes/profiles/tutor/.env 2>/dev/null | tail -n1 | tr -d "\"'")"
[ -n "${MOODLE_TOKEN:-}" ] || { echo "Moodle keep-alive: the Moodle cookie isn't available to this job. Run: sudo hermes-addon moodle"; exit 0; }
result=$(printf 'url = "@URL@/my/"\ncookie = "MoodleSession=%s"\n' "$MOODLE_TOKEN" | curl -s -o /dev/null -m 30 -w "%{http_code} %{redirect_url}" -K -)
case "$result" in
  200*) ;;
  30*sso*|30*SSO*|30*login*|30*auth*)
    if [ -x /usr/local/bin/uni-login ]; then
      read -r cfg res ts why < <(/usr/local/bin/uni-login state 2>/dev/null)
      if [ "${cfg:-none}" = configured ]; then
        marker="$(dirname "$0")/.uni-login-told"
        now="$(date +%s)"
        if [ "$res" = failed ]; then
          told="$(cat "$marker" 2>/dev/null)"; tts="${told##* }"
          case "$tts" in ""|*[!0-9]*) tts=0 ;; esac
          if [ "${told%% *}" != "$why" ] || [ $((now - tts)) -gt 43200 ]; then
            case "$why" in
              wrong-password)         what="the university says the password is wrong (change it again with: sudo uni-login setup)" ;;
              bad-code)               what="the authenticator code was refused (check the secret: sudo uni-login setup)" ;;
              only-push|needs-setup)  what="the university wants a sign-in method the helper can't do (it needs an authenticator-app code)" ;;
              *)                      what="the sign-in page didn't look as expected ($why)" ;;
            esac
            echo "Your Moodle session ended and the automatic sign-in failed: $what. Or paste a fresh cookie: sudo hermes-addon moodle"
            echo "$why $now" > "$marker"
          fi
        fi
        [ "$res" = running ] || { case "$why" in wrong-password) ;; *) /usr/local/bin/uni-login request >/dev/null 2>&1 ;; esac; }
        exit 0
      fi
    fi
    echo "Your Moodle session has ended, so the agents can't see Moodle. Log in to Moodle in a private window, copy the MoodleSession cookie and run on the server: sudo hermes-addon moodle" ;;
  *) ;;   # Moodle unreachable or slow: stay quiet, the next run retries
esac
