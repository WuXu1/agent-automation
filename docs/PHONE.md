# Phone calls (`sudo hermes-addon phone`)

Your Chief of Staff gets a phone number. You ring it and talk; it already knows your Moodle deadlines, your task board and the last
Telegram chat, can ask your other agents things during the call, and rings you back with results. With your
spoken yes each time, it can also ring people from a small contact book.

## What you need first
- **ElevenLabs** (the voice and the conversation): an API key saved with `sudo hermes-key elevenlabs`. A paid plan that includes
  Conversational AI and phone numbers (Creator works). Every call minute comes out of that plan.
- **A Twilio number** in your Twilio account. A UK number needs Twilio's address and regulatory bundle approved first.
  The number costs a little a month, plus per-minute call charges.
- **Tailscale Funnel** on the server. ElevenLabs has to reach the desk from the internet; Funnel publishes just that one small
  service (port 8443) and nothing else. An admin of your Tailscale network switches it on once for this machine:
  admin console -> Access controls -> add the `funnel` node attribute (https://tailscale.com/kb/1223/funnel). If it isn't on, the
  installer stops and says so.

## Setting it up
1. `sudo hermes-addon phone`. It asks for a voice for your chief, your own mobile number (hidden; kept only on the server, it is
   the number the chief treats as you), starts the desk, and creates everything in ElevenLabs (the secret, the webhook, the tools,
   the phone agent and the guest agent). It is safe to run again.
2. `sudo hermes-addon phone number` gives the phone agent a Twilio number. It asks for the number, your Twilio account SID and
   auth token (hidden). Those are used once, to let ElevenLabs answer the number, and are **not kept on the server**.
   If the number lives in somebody else's Twilio account, that person can run the import for you without your server ever
   holding their login (`python3 -m desk.number import NUMBER`, with the SID and token on two lines of stdin).
3. Ring the number.

## How it behaves
- Only your own number gets the brief and the tools. Anybody else who rings gets a polite message-taking mode.
- The chief says plainly that it is not a person if asked.
- People it rings for you must be in the contact book (`python3 -m desk.admin contact add ...`, numbers typed hidden), and it reads
  back what it will say and waits for your clear yes first. Calls are limited per hour and per day, and quiet hours (23:00 to 07:00
  UK time) are respected.
- A minutes guard keeps the month's calls inside what your plan includes.
- After each call you get a short note on Telegram.

## Commands (as the hermes user, in `/data/tools/voice-desk`)
`python3 -m desk.admin status`, `self-check`, `ask tutor|assistant|coach QUESTION`, `contact list`, `notify-test`,
`dial-mode live|dry`, `notify-mode live|dry`. `sudo hermes-addon phone update` copies the newest desk code in and restarts it
quietly (`sudo hermes-update` does it by itself). `sudo hermes-addon phone off` switches the desk off.

## Good to know
- The desk's code lives in `vm/phone/` with the names as `{{OWNER}}`-style placeholders that the installer fills in from your setup
  (`vm/phone/render.py`); `tests/test_phone_desk.py` runs its 350 tests with two different sets of names.
- How the chief speaks to you is the `STYLE.md` register (a composed, exact butler). The address it uses ("sir" or your first name)
  is `phone_address` in `/data/.hermes/hermes.json`, else your first name. Edit `/data/tools/voice-desk/STYLE.md` and
  `agents/chief.prompt.md`, then `python3 -m desk.push_agent` to change the voice's manner.
- The prompts assume he/him for the owner.
