# Command Center (dashboard)

One private web page for your Hermes team: what your agents remember, what they are doing, what they cost and whether the
VM is healthy. It runs on your VM and is reachable only from your own devices on your Tailscale network.

## What is on it

| View | What you see and can do |
|---|---|
| **Second Brain** | Your Mem0 memory as a 3D sky of stars, grouped into sections. Search by meaning, click a star to read, edit, pin or delete a note, add notes (an AI can tidy them first). A weekly check-up suggests merges and clean-ups; nothing changes until you press Apply. |
| **Agent Studio** | The chief over the three specialists, with live lines while they hand work to each other. Click an agent for its settings; "Live logs" beside its close button opens its terminal (read only). Edit an agent's name, description, SOUL, model and effort; switch skills and MCP servers on or off; manage automations (Hermes cron jobs). New agents are added through Claude, not here. |
| **Board** | The cards the team passes around: to do, running, waiting on you, done. Add a card, or answer one that is waiting. |
| **Inbox** | Gmail, read only, with an AI summary. Shown only when the Gmail add-on is on. |
| **Runway** | How long the Azure credit lasts, the VM's CPU, memory and disk, its services, and (with the backup add-on) the nightly backup with a "Backup now" button. |
| **Integrations** | Every outside service the agents use: whether its sign-in still works, balances, add-ons not switched on yet, and anything on the VM nobody described. |
| **Settings** | The model the dashboard's own AI jobs use, and the brain's sections. |
| **⌘K** | Jump anywhere, find a memory, or type `>` to brief your chief. |

Every write sits behind a second "are you sure" click. The **Demo** switch shows the page with made-up data (an owner called
Sam and the agents Atlas, Sage, Ivy and Rocky), so you can try everything without a VM.

## Names come from hermes.json

Nothing on the page is hard-coded to one person. The bridge reads `/data/.hermes/hermes.json` (written by the kit's installer)
and serves it at `GET /api/team`: your name, your agents' names and titles, your time zone, and which add-ons are on
(`voice`, `gmail`, `moodle`, `icloud`, `backup`). Change the file and the page follows on its next load; no restart.

## Install

The kit ships the page already built in `dist/`, so the VM never needs Node. On the VM, from the kit's checkout:

```bash
sudo bash <kit>/dashboard/bridge/deploy/install.sh          # install or update
sudo bash <kit>/dashboard/bridge/deploy/install.sh --undo   # remove it again
```

It prints the address, `https://<your-vm>.<your-tailnet>.ts.net:8444/`. Details: [`bridge/README.md`](bridge/README.md).

## Money

The dashboard itself costs nothing: a static page and one small Python process (about 20 MB of memory). Its AI jobs
(tidying a note, sorting notes, the weekly check-up, the inbox summary, ✦ enhance) use your DeepSeek key, a fraction of a
penny each. The sign-in checks are free.

## Change the page

```bash
cd dashboard
npm ci
npm run dev        # http://localhost:5173 with demo data
npm run lint
npm run build      # type-check, then the page in dist/ (commit dist/: the kit ships it)
python3 -B -m unittest discover -s bridge/tests     # the bridge's tests, from dashboard/
```

To try the page against your real VM while you work on it: `ssh -N -L 8890:127.0.0.1:8890 <your VM>`, then
`BRIDGE_DEV_LOGIN=<your Tailscale login> npm run dev`.

Stack: Vite, React 19, TypeScript, Tailwind CSS v4, three.js with React Three Fiber, Motion, Lucide, cmdk, zustand. Fonts are
bundled, so the page makes no outside requests. `src/telemetry/` is the data layer (one file per bridge area, demo data in
`demo/`), `src/modules/` holds one folder per view, `src/ui/` the shared pieces. Look and feel: `DESIGN.md`.
