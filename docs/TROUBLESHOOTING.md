# Troubleshooting

Start with `./hermes status`: every ✗ line says what's wrong and the command that fixes it. Claude can help: open this folder in
Claude Code and paste the output (it never contains keys).

| Problem | Fix |
|---|---|
| `./install.sh` stopped | Read the ✗ line, fix that, run `./install.sh` again: it carries on where it stopped |
| Azure: no region has room | Student capacity is busy; try again in an hour |
| Can't reach the server | Turn Tailscale on (same account as the server). On Windows/WSL: the Windows Tailscale app must be signed in |
| A bot doesn't answer | `./hermes status`; a refused token → `./hermes key telegram-chief` (or tutor/assistant/coach) |
| Bots ignore you | They only answer your own Telegram account: `./hermes key telegram-me` |
| "DeepSeek balance is low" | Top up at platform.deepseek.com; with a Gemini key they fall back to Gemini meanwhile |
| Dashboard won't load | Tailscale on for that device; in the Tailscale admin's DNS page MagicDNS and HTTPS Certificates on; then `./hermes update` |
| Agents forget things | Memory keeps lasting facts only by design; tell them "remember that …" for something specific |
| Disk nearly full | `./hermes ssh`, then `sudo du -xh /data --max-depth 2 \| sort -h \| tail` and ask Claude what's safe to delete |
| Memory tight / slow | `sudo hermes-restart`; the 2 GB swap file helps; don't upgrade the VM size without checking the cost (it doubles) |
| Moodle stopped | The session cookie expired: `./hermes addon moodle` with a fresh one |
| Gmail stopped | Make a new app password, `./hermes addon gmail` |

Logs: `./hermes logs` (the agents), `/var/log/agent-automation.log` on the server (the installer), `~/.agent-automation/install.log` here.

Start again from scratch: `./hermes destroy` (deletes the server; asks twice), then `./install.sh`.
