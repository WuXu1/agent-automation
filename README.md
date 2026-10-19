# agent-automation

**Your own Hermes agents, on a server you control, that you talk to on Telegram.** One guided install, built for students
with the Azure for Students credit.

| Agent | What they do |
|---|---|
| **Chief of Staff** | Your main contact. Morning briefing, reminders, decisions; hands bigger jobs to the other three and reports back |
| **Tutor** | Explains topics, quizzes you, plans revision, finds papers and sources, gives feedback on your own drafts (never writes work for you) |
| **Assistant** | Research with sources, planning your day and week, your task list, admin, email drafts |
| **Coach** | Training, food, sleep, habits and recovery, with the weather for outdoor plans |

You name them. Each has its own Telegram bot, and they share one long-term memory (a "second brain") so what you tell one, the
others know. You can also watch everything on **Command Center**, a private dashboard: the memory as a 3D star map, the agents
and what they're doing live, their board of jobs, the server's health and your balances.

It runs [Hermes Agent](https://github.com/NousResearch/hermes-agent) (open source, by Nous Research) on a small Linux server
in your own Azure account. Nothing is open to the internet: you reach the server and the dashboard over
[Tailscale](https://tailscale.com), a free private network between your own devices.

## Before you start (15 minutes, all free)

Make these accounts first. The installer tells you exactly when it needs each one.

1. **Azure for Students**: https://azure.microsoft.com/free/students (sign in with your university email; $100 credit, no card).
2. **Tailscale**: https://tailscale.com (sign in with Google, Microsoft, GitHub or Apple; use the same one everywhere). Put
   the app on your computer and your phone.
3. **Telegram** on your phone.
4. **DeepSeek** (the agents' brain, pay as you go): https://platform.deepseek.com. Top up $2-5 and make an API key.
5. **Gemini** (free backup brain, optional but recommended): https://aistudio.google.com/apikey.

You'll also make four Telegram bots during the install. It's two messages each to @BotFather, and the installer walks you through it.

## Install

On a **Mac or Linux** computer, open Terminal. On **Windows**, first install Ubuntu ([below](#on-windows)) and use its window.

```bash
git clone https://github.com/WuXu1/agent-automation.git
cd agent-automation
./install.sh
```

It takes 30 to 45 minutes. Most of that is waiting, and you can stop and run `./install.sh` again at any point to carry on.

1. It installs the tools this computer needs: the Azure CLI, Tailscale and a login key.
2. It creates the server: 2 processors, 4 GB of memory, Ubuntu 24.04.
3. It connects the server to your Tailscale network. You approve it with one click.
4. On the server, it asks your name and your agents' names, then your keys (hidden as you type), and sets everything up.

**Using Claude?** Open this folder in Claude Code and say *"help me set this up"*. It knows this kit (see `CLAUDE.md`) and
can explain each step and fix problems. Run `./install.sh` yourself in a normal terminal, because it asks for keys at hidden prompts.

### On Windows
1. Open **PowerShell as administrator** and run `wsl --install`, then restart your PC.
2. Open **Ubuntu** from the Start menu and pick a username and password.
3. Install **Tailscale for Windows** (https://tailscale.com/download/windows) and sign in. It covers the Ubuntu window too.
4. In the Ubuntu window, run the three commands above.

## Everyday use

Talk to your agents on Telegram. Send a voice note and they understand it; typing works the same. In a terminal on your computer (any folder):

| Command | What it does |
|---|---|
| `hermes status` | Health check: services, bots, memory, DeepSeek balance, disk, Azure days used |
| `sudo hermes-update` (on the server) | Gets the latest kit straight from GitHub and applies it: no laptop folder needed |
| `hermes dashboard` | Opens Command Center (Tailscale must be on) |
| `hermes update` | Gets the latest version of this kit and applies it. Your answers, keys, memory and edits stay |
| `hermes restart` | Restarts the agents (it waits until they're idle) |
| `hermes key deepseek` | Changes a key: `deepseek`, `gemini`, `elevenlabs`, `telegram-chief`… |
| `hermes logs` | The agents' recent log (useful to paste to Claude when something's wrong) |
| `hermes ssh` | A terminal on the server |

### Later, when you want them
| Command | Adds |
|---|---|
| `hermes voice` | **Voice replies**: send a voice note, get one back in that agent's own voice. You choose each agent's voice from ElevenLabs (free plan: about 60 short replies a month). [docs/VOICE.md](docs/VOICE.md) |
| `hermes addon gmail` | Chief and Assistant read your Gmail and save drafts (they can never send, delete or move mail) |
| `hermes addon moodle` | Tutor and Assistant read your university's Moodle: deadlines, courses, grades (never submit) |
| `hermes addon moodle-login` | The server signs in to the university for you (password + authenticator code, kept locked away) so you never paste a cookie again: [docs/UNI-LOGIN.md](docs/UNI-LOGIN.md) |
| `hermes desktop` | **The Hermes app on your Mac** (Mac only), already connected to your server. It builds just the app, nothing of Hermes runs on the Mac. Needs Tailscale on and about 10 minutes the first time |
| `hermes addon backup` | A nightly encrypted backup of everything to your Google Drive. [docs/BACKUPS.md](docs/BACKUPS.md) |

Phone calls aren't in this kit yet. Voice notes work.

**You can delete the `agent-automation` folder once the install has finished.** The server keeps its own copy and updates itself, and the `hermes` command above is kept in `~/.agent-automation` (the installer offers to add it to your terminal, so `hermes status` works from anywhere; until you open a new terminal window, use `~/.agent-automation/bin/hermes status`). If something ever needs a fix with Claude, clone this repository again and open it in Claude Code.

## Money

| What | Cost |
|---|---|
| Server (Azure: VM, disk, internet address) | about **$1.25 a day** from your $100 student credit, so it lasts **about 80 days**. No card is charged; when the credit runs out Azure switches the server off |
| DeepSeek | pay as you go: light personal use is usually a few dollars a month. `hermes status` shows the balance |
| Gemini, Telegram, Tailscale, Open-Meteo weather, OpenAlex papers | free |
| ElevenLabs (voice replies, optional) | free plan, or a student offer |

Your chief of staff reminds you on Telegram after 70 days. Your options then:
- **Azure for Students renews** every 12 months while you're a student. Check your balance at
  https://www.microsoftazuresponsorships.com/Balance.
- **Move to a cheaper server.** For example, Hetzner's CX23 costs about €5.50 a month. Restore your backup there.
- **Delete it** with `hermes destroy`. It asks twice before deleting anything.

Don't "Stop" the server in the Azure portal to save credit: student subscriptions can struggle to get it started again.

## What's on the server

| Piece | |
|---|---|
| Hermes Agent v0.21.5 | Pinned to one tested release, plus three small fixes in `vm/hermes-patches/`. It never updates itself; see [docs/UPDATING.md](docs/UPDATING.md) |
| Your four agents | One process (`hermes-gateway`) runs all four, as an unprivileged user `hermes`. Settings come from `vm/hermeslib.py`; personalities from `vm/agents/souls/` (yours to edit afterwards: `/data/.hermes/SOUL.md` and `profiles/*/SOUL.md`) |
| Memory | [Mem0](https://github.com/mem0ai/mem0) with Postgres on the server; searching runs locally, so your notes aren't sent anywhere to be searched |
| Dashboard | Command Center, only on your Tailscale network, only for your account |
| Security | No public ports at all. Keys are typed at hidden prompts and stored only on the server (mode 600). Security updates install themselves |

More: [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md) · [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) · [docs/UPDATING.md](docs/UPDATING.md)

## Licence

MIT (see [LICENSE](LICENSE)). Hermes Agent and Mem0 are separate projects under their own licences; the installer downloads them from their official repositories.
