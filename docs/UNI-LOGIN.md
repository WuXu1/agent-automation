# The agents sign in to the university themselves (`hermes addon moodle-login`)

Without this, the Moodle add-on needs you to paste a `MoodleSession` cookie whenever the session ends. With it, the server
signs in for you with a headless browser and puts the new cookie where the agents read it.

## What it needs from you
- Your **university email and password**, and an **authenticator secret**: the text key shown next to the QR code when you
  add an authenticator *app* (any app: Microsoft Authenticator, Google Authenticator, Authy, 1Password...). The server computes
  the same six-digit codes from that secret, and your phone keeps working because it holds the same one.
  A "tap the number on your phone" approval can't be automated, so the account must have an app-code method.
  Microsoft accounts: https://mysignins.microsoft.com/security-info -> Add sign-in method -> Authenticator app ->
  "I want to use a different authenticator app" -> "Can't scan the image?" Scan the QR with your phone's app as well, then
  copy the secret into the server's hidden prompt.
- You type all three at hidden prompts on the server (`sudo uni-login setup`). Nobody else ever sees them, Claude included.

## The risks, plainly
- A password and an authenticator secret kept together are the whole login. Anyone who got into the server could sign in as
  you at the university. They sit in a folder only a locked-down user (`unilogin`) can open, not the agents, but the risk is real.
- The university may forbid automatic sign-ins, or lock the account if a datacentre address looks odd. Check its IT rules.
- Costs: nothing monthly. About 300 MB of disk for the browser; a few seconds of about 600 MB of memory per sign-in, capped at 1 GB.

## How it works
1. The agents' keep-alive (every 30 minutes) sees the Moodle session has ended and runs `uni-login request` (touches
   `/run/uni-login/request`; the agents can do nothing else with it).
2. A root-owned systemd unit (`uni-login-refresh.path`) starts `uni-login refresh`: the helper (`uni_login.py`, as the `unilogin`
   user) walks the sign-in pages in headless Chromium, types the password once and the code, and prints only the cookie.
3. Root checks the cookie against Moodle, writes it into the tutor's and assistant's `.env` (`MOODLE_TOKEN`), and asks for a
   quiet restart (`hermes-restart` waits until the agents are idle) so the running agents pick it up.
4. If it fails, the owner gets one Telegram message with the reason (once per reason per 12 hours).
- Safety stops: the password is typed once per attempt; after a *wrong password* it never tries again until `setup` is run;
  other failures wait 30 minutes; the same code is never sent twice in a window.

## Commands
| | |
|---|---|
| `sudo hermes addon moodle-login` | Install and set up (asks first) |
| `uni-login status` | Set up? How did the last sign-in go? (no secrets) |
| `sudo uni-login refresh --force` | Sign in now |
| `sudo uni-login setup` | New password or secret |
| `sudo hermes addon moodle-login off` | Delete the password and the secret |

If it stops working the reason code is in `uni-login status` (`wrong-password`, `bad-code`, `only-push`, `needs-setup`, `stuck`,
`browser-...`). A screenshot of the last failed page is in `/var/lib/uni-login/private/last-failure.png` (root only).
