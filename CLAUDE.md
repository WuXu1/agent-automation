# agent-automation: instructions for Claude Code

This repo installs four Hermes Agent agents (Chief of Staff, Tutor, Assistant, Coach) on the owner's Azure for
Students VM, chatting on Telegram, with shared Mem0 memory and a private dashboard. The person you're helping is usually a
student who is new to servers and AI agents: plain words, one step at a time, and the money impact of anything you suggest.

## Helping someone install
Follow the `setup-hermes` skill (`.claude/skills/setup-hermes/SKILL.md`). The short version:
- The person runs `./install.sh` **themselves, in their own terminal**. It asks questions and takes keys at hidden prompts,
  which can't work through your shell. You explain, check and troubleshoot.
- **Never ask for keys, tokens, passwords or app passwords in the chat**, and never put one on a command line or in a file
  in this repo. Every secret is typed at a hidden prompt on the server (`install.sh`, `./hermes key …`, `./hermes addon …`).
- The installer's log, which never contains keys, is at `~/.agent-automation/install.log` on their computer and
  `/var/log/agent-automation.log` on the server (`./hermes ssh`, then `sudo tail -n 80 /var/log/agent-automation.log`).
  Read these instead of guessing.
- After the install: `./hermes status` is the health check. Its output says what's wrong and the command that fixes it.

## Rules on the server
- Restart the agents only with `sudo hermes-restart`, which waits until they're idle. Never use `hermes update`: Hermes is pinned
  on purpose (docs/UPDATING.md).
- Change agent settings through `vm/hermeslib.py`, then `./hermes update`. Don't edit `config.yaml` by hand unless the owner asks.
  The owner's own `SOUL.md` edits on the server are theirs, and updates keep them.
- Ask before anything that costs money (bigger VM, paid plans), deletes data (`./hermes destroy`, restores) or sends anything as the owner.

## Layout
| Path | What |
|---|---|
| `install.sh`, `hermes`, `laptop/` | The laptop side: prerequisites, the Azure VM (`laptop/azure.sh`), Tailscale join, copying the kit to `/opt/agent-automation` |
| `vm/install.sh`, `vm/stages/` | The server side, in stages: system, questions, hermes, keys, agents, memory, gateway, jobs, dashboard. Each run checks what's already done |
| `vm/hermeslib.py` | Turns `/data/.hermes/hermes.json` (the owner's answers, no secrets) into each agent's config, SOUL, skills |
| `vm/agents/` | Personality templates (`{{OWNER}}`, `{{CHIEF}}` … placeholders), role skills, house rules, the briefing prompt |
| `vm/bin/hermes-*` | Server commands: `hermes-doctor`, `hermes-key`, `hermes-restart`, `hermes-voice`, `hermes-addon` |
| `vm/backup/` | The optional nightly encrypted Google Drive backup and restore |
| `vm/studio/`, `vm/tools/studio/` | The optional content studio add-on (`sudo hermes-addon studio`): four agents, the `cy` tools, a worker service; how it works: `docs/STUDIO.md` |
| `dashboard/` | Command Center: React page (prebuilt in `dist/`) and a Python bridge (`dashboard/bridge`, tests in `bridge/tests`) |

## Checks before committing
`bash tests/run.sh` (shell syntax, Python tests for hermeslib, the weather tool, the voice plugin and the dashboard bridge).
If you change the dashboard's source, run `npm ci && npm run lint && npm run build` in `dashboard/` and commit `dist/` too.

## Working from a cloud session (Claude Code on the web)
- The server has no public SSH: join the owner's tailnet first (`tailscale up` with an auth key kept as a secret in the environment, or a login link the owner approves), then
  ssh over `tailscale nc <host> 22`. A container holds more than one tailnet login (`tailscale switch --list`, `tailscale switch <id>`): switch back to the user's own when done.
- Deploy a change with `sudo hermes-update` on the server (git pull into `/opt/agent-automation`, then `vm/install.sh`). Restart only with `sudo hermes-restart`.
- Keep the notes true as you go: in the same commit as each change update the docs that describe it (`docs/STUDIO.md` for the studio), and tell the user what you changed in plain words.
- Never put a key, token, address of a private machine or phone number in this public repo.
