# Updating

## This kit
`./hermes update` on your computer: it pulls the latest kit from GitHub, copies it to the server and re-runs the server install
without questions. Your answers (`crew.json`), keys, memory, chats and your own `SOUL.md` edits are kept; role skills, settings
the kit owns and the dashboard are refreshed. If something needs a new key, it tells you to run `./install.sh`.

## Hermes itself (pinned on purpose)
The server runs Hermes Agent **v0.21.5** (tag `v2026.9.24`, commit `f97608f`) plus three small patches in `vm/hermes-patches/`.
Hermes's own updater (`hermes update`) jumps to the development branch, so the installer switches the git remote off and an
accidental `hermes update` fails harmlessly. **Don't run it.**

Moving to a newer Hermes release is a kit change, made and tested once for everyone:
1. On a test server: change `HERMES_TAG`/`HERMES_COMMIT` (and `UV_VERSION` if needed) in `vm/lib.sh`.
2. Check each patch still applies (`git apply --check`); redo any that doesn't against the new code.
3. Run the install on a fresh test server, send each bot a message, run a board job, check memory and the dashboard.
4. Release the kit; owners then run `./hermes update`. (Existing servers need the checkout moved: stop the gateway, back up,
   `git fetch --tags`, `git checkout --detach <tag>`, re-apply patches, `uv sync --extra all --extra messaging --extra voice --locked`, restart.)
