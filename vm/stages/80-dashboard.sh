# shellcheck shell=bash
# Stage: Command Center, the dashboard. A small bridge on this server, published only inside your Tailscale network.

stage_dashboard() {
  step "The dashboard (Command Center)"
  bash "$KIT/dashboard/bridge/deploy/install.sh" || { warn "The dashboard didn't install (above). Your agents work without it; retry later with: hermes update"; return 0; }
  local dns; dns="$(tailscale status --json 2>/dev/null | jq -r '.Self.DNSName // empty' | sed 's/\.$//')"
  [ -n "$dns" ] && cj_set '.dashboard_url' "$(jstr "https://$dns:8444/")"
}
