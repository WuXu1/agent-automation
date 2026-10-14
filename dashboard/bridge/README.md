# Crew Command bridge

One small Python process (standard library only) that serves the built dashboard and an `/api` in front of Mem0, the
agents, the board and the VM. It runs on the VM as `hermes-dash.service` (user `hermes`, `127.0.0.1:8890`) and is published
**tailnet-only** with `tailscale serve --https=8444`. Cost: nothing (about 20 MB of memory, capped at 384 MB).

## Install, update, undo

On the VM, from the kit's checkout (the page is already built in `dashboard/dist/`):

```bash
sudo bash <kit>/dashboard/bridge/deploy/install.sh          # install or update; prints the address
sudo bash <kit>/dashboard/bridge/deploy/install.sh --undo   # stop it, its helpers and the address (files kept)
```

It needs: Hermes installed (user `hermes`, data in `/data/.hermes`), Mem0 (`/data/.hermes/mem0-server/server.env`),
`/data/.hermes/crew.json`, `python3`, `curl` and a signed-in `tailscale`. It asks no questions. It:

1. checks every bridge file parses, then copies them to `/data/tools/hermes-dash/` and the page to `.../dist/`;
2. installs the root-owned helpers (`restart-gateway.sh`, `restart_when_quiet.sh`, `backup-now.sh`) in
   `/usr/local/lib/hermes-dash/` and the units `hermes-dash` and `hermes-dash-{restart,jobs,backup}.{path,service}`;
3. on the first install writes `/data/.hermes/hermes-dash/config.json` (mode 600): `mem0_user` is crew.json's `owner.id`,
   `allowed_logins` is crew.json's `owner.tailscale_login`, or else the Tailscale login that owns the VM;
4. starts the bridge, checks `/api/health`, Mem0 and the feeds through it, then runs
   `tailscale serve --bg --https=8444 http://127.0.0.1:8890` (never Funnel; other serve entries stay as they are).

It restarts nothing but its own service.

## crew.json

The bridge reads `/data/.hermes/crew.json` (`crew.py`) whenever the file changes on disk, so an add-on switched on later
shows without a restart. Fields it uses:

| Field | Used for |
|---|---|
| `owner.name` | the name on the page, in Brief, on board answers ("Sam (dashboard): …"), in the AI prompts and the generated team skill |
| `owner.id` | the Mem0 user (written into `config.json` at install) and a reserved profile name |
| `owner.tailscale_login` | who may open the page (written into `config.json` at install) |
| `timezone` | the page's clock and dates |
| `agents[]`: `id`, `profile`, `role`, `name`, `title` | every agent name and id; `profile: "default"` is the chief. The page speaks ids, the bridge maps them to profiles |
| `features`: `voice`, `gmail`, `moodle`, `icloud`, `backup` | which add-ons are on. Off: their Integrations card says "not switched on", `/api/inbox` and `/api/backup` answer 404, the page hides the Inbox and the backup panel |

A renamed agent (Agent Studio writes `display_name` in its `profile.yaml`) shows its new name. A missing or broken file
falls back to plain names (Chief, Tutor, Assistant, Coach) and no add-ons.

`GET /api/crew` returns `{owner: {name, pronouns}, timezone, chief, agents: [{id, profile, role, name, title}], features}`.
It never returns the login or the Mem0 id.

## Routes

Reads:

| Route | Does |
|---|---|
| `GET /`, `/assets/*` | the page (`dist/`); any unknown path gets the page, never a file outside `dist/` |
| `GET /api/health`, `GET /api/crew` | `{ok, version}`; the crew (above) |
| `GET /api/memories`, `POST /api/memories/search` | every note of the owner's Mem0 user; vector search, filtered to that user |
| `GET /api/agents` | per agent: model, MCP servers, board load, last activity, its last runs and 30-day reliability; gateway health; recent hand-offs; `talks` (open cards between two agents right now) |
| `GET /api/agents/{id}/terminal` | one agent's runs from its own `state.db` (opened read only) as terminal lines; keys, tokens, passwords and phone numbers blanked |
| `GET /api/infra` | CPU, memory, disk, load, uptime, the services, the backup's last run, the credit snapshot, cleanable folders |
| `GET /api/board` | cards not archived (done ones from the last 14 days) |
| `GET /api/integrations`, `GET /api/registry`, `GET /api/inbox` | the Integrations hub, the registry's labels, Gmail (read only, add-on) |

Writes (each from a confirmed control on the page, logged in `/data/.hermes/hermes-dash/actions.log` without any secret
or SOUL text):

| Route | Does |
|---|---|
| `POST`/`PUT`/`DELETE /api/memories…`, `PUT /api/memories/{id}/pin` | add (word for word, `agent_id: dashboard`), edit, delete, pin a note of the owner's user |
| `PUT /api/agents/{id}` | name, description, SOUL, model, effort, MCP servers on/off. Adding (`POST /api/agents`) and moving agents are refused: that is done through Claude |
| `DELETE /api/agents/{id}` `{confirm}` | export the profile to `hermes-dash/archive/`, then delete it. The chief cannot be deleted |
| `/api/agents/{id}/skills…`, `/api/mcp…`, `/api/automations…` | skills (skills.sh only), MCP servers, Hermes cron jobs |
| `POST /api/chief/brief`, `GET /api/chief/runs/{id}` | a message to the chief through the gateway's run API; the reply |
| `POST /api/board/cards`, `POST /api/board/cards/{id}/answer` | `hermes kanban create`; `hermes kanban unblock --reason` |
| `POST /api/restart`, `POST /api/backup` | ask the root helpers for a quiet gateway restart or a backup now (backup add-on only) |
| `/api/settings`, `/api/brain…`, `/api/enhance`, `/api/memories/tidy` | the dashboard's model, brain sections and weekly check-up, AI rewrites |

Agent ids or profiles both work wherever a route names an agent.

File edits are careful: a backup `<file>.bak-before-dash-<what>-<time>` beside it, a temporary copy parsed by Hermes' own
Python with the intended values checked, then swapped in; a failed check changes nothing. CLI calls are argument lists with
`--` before free text, an empty stdin and a 90 s limit.

## How it stays safe

- **Who:** every request needs the `Tailscale-User-Login` header that `tailscale serve` adds, and that login must be in
  `allowed_logins`. No header: 401. Another login: 403.
- **Writes** need `X-Hermes-Dash: 1` and a JSON body, so another website cannot post to it from your browser.
- **Mem0:** one user only; never `/reset`, `/configure` or a delete-all (the tests prove no route reaches them). Only
  `ADMIN_API_KEY` is read from Mem0's env file, and it is only sent to `127.0.0.1:8888`.
- **Network:** the bridge may only talk to localhost. Anything that needs the internet (AI jobs, sign-in checks, the inbox,
  skills.sh) is a request file in `hermes-dash/jobs/` that `hermes-dash-jobs.service` (user `hermes`) runs from a fixed list,
  checking every argument again.
- **Root:** the bridge never gets root. A restart or backup request is a file; a `.path` unit starts a root oneshot that runs
  a root-owned script in `/usr/local/lib/hermes-dash/`. `restart_when_quiet.sh` refuses while a card is running or a message
  came in during the last 5 minutes. At most 3 restarts in 10 minutes and 4 backups an hour.
- **Secrets:** the page only ever sees where a secret lives (a path) and its name, never its value.

## Keeping it in sync: registry.json

Agents, skills, MCP servers, cron jobs and the board are read live. What the VM cannot tell (a friendly name, who uses it,
where its secret lives, a port) is in `registry.json`: integrations, built-in tools, MCP rules, teams, services and timers.
It names agents by Hermes profile; the bridge turns them into crew ids. An integration with a `feature` is an optional
add-on. Anything installed on the VM that the registry does not describe still shows up, marked **new**. When you add
something, describe it there and run the installer again.

## The Azure credit

A student subscription has no API for the balance, so the Runway counts down from a dated figure. Type the figure from the
Azure portal on the Azure card in Integrations (stored in `hermes-dash/settings.json`).

## Operating it

```bash
systemctl status hermes-dash ; sudo journalctl -u hermes-dash -n 30
curl -s -H "Tailscale-User-Login: <your login>" http://127.0.0.1:8890/api/health
tailscale serve status
```

## Tests

```bash
cd dashboard && python3 -B -m unittest discover -s bridge/tests
```

No network and no VM: a fake Mem0, a fake `hermes` CLI and gateway, a fake IMAP server, fixture SQLite files and canned
`systemctl` output, with a made-up crew in `tests/crewfix.py`.
