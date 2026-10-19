# Voice

**Voice notes in** work from day one: send any agent a Telegram voice note and it's transcribed on your server
(faster-whisper, free, nothing leaves the server).

**Voice replies** are optional: `hermes voice`.
- You need an ElevenLabs account (https://elevenlabs.io). The free plan gives about 10,000 characters a month, roughly 60 short
  replies; students can often get a discount. Make an API key with "Text to Speech" and "Voices: read".
- It lists the voices in your ElevenLabs account with a sample link for each. Add voices you like from ElevenLabs' Voice Library
  first, then pick one per agent.
- From then on, a voice note gets a voice note back in that agent's voice; typed messages stay text. In any chat, `/voice`
  changes this (`off`, `voice_only`, `all`).
- Long replies are first shortened to one to three spoken sentences (a fraction of a penny with DeepSeek), so they're quick to
  listen to and use fewer ElevenLabs characters.
- Change voices: run `hermes voice` again. Switch off: `hermes voice off`.

**Phone calls** (ringing your agents, or them ringing you) aren't in this kit yet.
