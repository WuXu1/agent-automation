---
name: setup-crew
description: Walk someone through installing agent-automation (their own four-agent crew on Azure for Students + Telegram), and troubleshoot it afterwards. Use when the user says "help me set this up", "install", asks what an install step means, or reports something not working with their agents, bots, dashboard or server.
---

# Setting up the crew with someone

The person types; you guide. `./install.sh` and every command that takes a key must run in **their own terminal**, never in
yours: hidden prompts need a real terminal, and keys must never pass through the chat. Never ask them to paste a key, token or
password to you. If they do, tell them to revoke it and make a new one.

## 1. Before they start
Ask which computer they're on (Mac, Windows, Linux). On Windows, walk them through README → "On Windows" (WSL + Ubuntu +
Tailscale for Windows) first. Then check off README → "Before you start" one by one:
- **Azure for Students** active? They can check at https://portal.azure.com: the subscription is called "Azure for Students".
- **Tailscale** on the computer and phone, same account? (`tailscale status` on Mac/Linux; the system tray on Windows.)
- **DeepSeek**: topped up ($2-5 is plenty to start) and an API key made? Without a balance the key is refused.
- **Gemini** key (optional, free; recommended as the backup brain).
- Telegram on their phone.
Tell them the money once: the server uses about $1.25 a day of the $100 credit (about 80 days); DeepSeek is a few dollars a month.

## 2. Run it
They run `./install.sh` in a terminal in this folder. What each part looks like, so you can reassure them:
- **Step 1, tools**: may install Homebrew on a Mac, which asks for their Mac password. Normal.
- **Step 2, Azure**: a device code to type at microsoft.com/devicelogin. Then it tries regions until one has room (student
  subscriptions are limited to a few regions; "No room in X" lines are normal).
- **Step 3, Tailscale**: a login.tailscale.com link to approve the server, using the **same** Tailscale account as the computer.
  Then two settings in the Tailscale admin console: **Disable key expiry** on the server, and **MagicDNS + HTTPS Certificates** on
  (DNS page). Help them find these.
- **Step 4, on the server**: name, pronouns, town, studies, the four agents' names; then the keys; then four bots via @BotFather
  (`/newbot` → a name → a username ending in `bot` → copy the token); then pressing **Start** in the chief's bot so the server
  learns their Telegram id. Then 10-15 minutes of installing.

## 3. When something fails
The scripts stop with a ✗ line saying what to do. Every rerun of `./install.sh` carries on where it stopped. Read the logs, not your memory:
- Laptop: `~/.agent-automation/install.log` (you can read this file directly; it never contains keys).
- Server: ask them to run `./crew ssh` then `sudo tail -n 80 /var/log/agent-automation.log`, or `./crew status`, and paste the output.

| Symptom | Likely cause → fix |
|---|---|
| `az vm create` fails in every region | Student capacity is full right now → wait an hour and rerun; or quota → check the subscription is active |
| Server never joins Tailscale | They approved it with a different Tailscale account → rerun `./install.sh` for a fresh link |
| "Can't reach your server" | Tailscale is off on the computer, or on WSL the Windows Tailscale app isn't signed in |
| DeepSeek key refused | No balance yet (top up), or a copy-paste with a missing character |
| A bot never answers | `./crew status` → the bot's token line; `./crew key telegram-<role>` to replace a revoked token |
| Bots ignore them or say "not authorised" | The wrong Telegram account was recorded (someone else pressed Start first) → `./crew key telegram-me`, then press Start in the chief's bot again |
| Dashboard won't open | Tailscale off on that device, or HTTPS Certificates not enabled in the Tailscale DNS page → enable, then `./crew update` |
| Agents slow or "out of memory" | `./crew status` shows memory; `sudo crew-restart` |

More in docs/TROUBLESHOOTING.md.

## 4. After it works
Suggest they message the chief on Telegram ("hi, what can you do?"), open `./crew dashboard`, and later try `./crew voice`
(pick voices), `./crew addon gmail|moodle|backup`. Recommend the backup add-on: without it a deleted server loses everything.
