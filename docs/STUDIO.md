# The content studio (add-on)

For an owner who runs a short-video page: a raw 15-second scene, a few plain words over it, a sound added in TikTok. The team prepares everything up to the
last tap; **the owner approves every post in the dashboard, then posts by hand** (TikTok library sounds cannot be attached through an API, and direct posting
needs an audited TikTok app). Install: `sudo hermes-addon studio` on the server (it asks for the page name and a one-line brief).
The team's own manual is `vm/studio/skills/content-studio/SKILL.md`; this page is for whoever works on the code.

## Pieces

| Piece | Where | What |
|---|---|---|
| Tools and the `cy` command | `vm/tools/studio/` | ingest (small 1080x1920 copy of each clip), tag (Gemini watches each clip once, about a cent), plan, render (ffmpeg, text laid over, no sound), lines, sounds, queue. `cy_worker.py` runs the heavy jobs |
| Four agents | `vm/studio/profiles/` | Content Director (the gate), Clip Curator, Overlay Copywriter, Video Editor: board workers on the kanban, one card at a time; the chief hands off with the `studio-handoff` skill |
| Worker service | `vm/studio/deploy/studio-worker.{path,service}` | picks up request files the dashboard drops (ingest, tag, render) so the web server never does heavy work |
| Dashboard bridge | `dashboard/bridge/studio.py` (tests `bridge/tests/test_studio.py`) | reads `/data/studio`; the owner's writes go through the same `cy_plan`/`cy_ingest` functions the agents use. Needs the owner's Tailscale login header |
| Dashboard page | `dashboard/src/modules/studio/`, `dashboard/src/telemetry/studio.ts` (+ `demo/studio.ts`) | tabs Posts (the queue), Scenes, Lines, Sounds, Look & settings. Registered through `Features.studio`, `ViewId`, `VIEWS`, the lazy map in `app/Shell.tsx` |
| Data | `/data/studio` on the server | `library.json`, `lines.json`, `sounds.json`, `queue.json`, `style.json`, `settings.json`, `voice.md`, `clips/`, `thumbs/`, `out/`. Never edit by hand |

## The flow

`cy plan` pairs a free clip, an approved line and a sound for each day (Plan posts in the dashboard is the free version; "Ask the team to plan" gives the Director a card).
Post states: `proposed` -> `ready` (video made) -> `approved` (owner) -> `delivered` -> `posted`, or `skipped`. Clips, lines and sounds rest for `settings.*_rest_days` before reuse.
Only the owner approves, skips or marks "posted"; the agents never do. Lines the Copywriter writes are always `suggested` until the owner approves them.
Settings: `page_name` (1-40 chars), `post_every_days` (1-2 to start), `plan_days`, `cta_every` (every Nth post carries the soft book pointer).

## Dashboard details worth knowing

- Feeds use `makeFeed`/`useFeed`/`reloadFeed`; writes go through `api<T>` (sets `X-Hermes-Dash: 1`); in demo mode the same writes edit feed state in place.
- Uploads are XHR `PUT /api/studio/clips|fonts/<name>` with progress; the video and still are served with Range support.
- The Second Brain page shows only the owner's own agents (Chief, Tutor, Assistant, Coach) as dots, each with its role under the name. Two traps there: the roster also lists the
  content team's workers, so it is filtered by the team feed; and drei leaves the first `<Html>` it mounts in a canvas empty (the chief's name was the one missing), so
  `scene/Agents.tsx` mounts a throwaway `<Html>` first. Keep it.

## Not done yet

- Delivery step: a Telegram nudge/file when a post is approved, and the `delivered` status.
- A daily planner (timer or script) so plans appear without anyone pressing the button.
- The studio's text look is the kit default; match the owner's real font, size and position from a sample video.
- TikTok "drafts" API check (could replace the hand-post step if it allows sounds).
- Not yet checked on a real owner's clips end to end beyond a synthetic test clip.

## Checks

`bash tests/run.sh`; after dashboard source changes `npm ci && npm run lint && npm run build` in `dashboard/` and commit `dist/`. To look at a page without a server, build,
serve `dist/` with `python3 -m http.server` and drive it with Playwright (chromium is at `/opt/pw-browsers/chromium`, use swiftshader args for WebGL).
