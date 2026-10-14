#!/bin/bash
# Keeps the agents' Moodle session alive (any page load refreshes it). A script-only job on the tutor every 30 minutes:
# silent while the session works; one message when it has ended. @URL@ is filled in by `crew-addon moodle`.
# The job may not get the cookie in its environment: then read it from the tutor's own .env (this runs as hermes).
[ -n "${MOODLE_TOKEN:-}" ] || MOODLE_TOKEN="$(sed -n 's/^MOODLE_TOKEN=//p' /data/.hermes/profiles/tutor/.env 2>/dev/null | tail -n1 | tr -d "\"'")"
[ -n "${MOODLE_TOKEN:-}" ] || { echo "Moodle keep-alive: the Moodle cookie isn't available to this job. Run: sudo crew-addon moodle"; exit 0; }
result=$(printf 'url = "@URL@/my/"\ncookie = "MoodleSession=%s"\n' "$MOODLE_TOKEN" | curl -s -o /dev/null -m 30 -w "%{http_code} %{redirect_url}" -K -)
case "$result" in
  200*) ;;
  30*sso*|30*SSO*|30*login*|30*auth*)
    echo "Your Moodle session has ended, so the agents can't see Moodle. Log in to Moodle in a private window, copy the MoodleSession cookie and run on the server: sudo crew-addon moodle" ;;
  *) ;;   # Moodle unreachable or slow: stay quiet, the next run retries
esac
