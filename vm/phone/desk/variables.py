"""The dynamic variables every conversation starts with. One builder serves the initiation webhook ({{OWNER}} rings in) and
the call-backs ({{CHIEF}} rings out), so the agent's prompt always sees the same names.

ElevenLabs needs a value for every variable the agent defines. Values are strings. `secret__desk_token` is never shown to
the model; it only goes into the tool-request header.
"""
from __future__ import annotations

import re

from .calls import NO_TOKEN
from .persona import TITLE
from .util import greeting, plain, uk_time

NAMES = ("greeting", "caller_mode", "now_text", "brief", "pending_text", "minutes_text", "callback_text", "contacts_text",
         "secret__desk_token")
# The guest agent (it rings people for {{OWNER}}) is given these and nothing else: no brief, no token, nothing of {{OWNER}}'s.
GUEST_NAMES = ("greeting", "guest_name", "relationship_to_max", "purpose", "now_text")
# A calls {{CHIEF}} makes: when {{OWNER}} answers, {{CHIEF}} waits a moment before he speaks ({{OWNER}}, 5 Oct 2026: he spoke at once and {{OWNER}} missed the
# first words). Eleven v4 Turbo ignores SSML <break>; measured with its own transcription, one [long pause] delays the first word
# by only 0.2 s and two in a row by 1.2 to 1.6 s. The tags are never spoken.
ANSWER_PAUSE = "[long pause] [long pause] "
STRANGER_GREETING = (f"Good evening. This is {{CHIEF}}, {TITLE}. {{OWNER}} can't come to the phone just now. "
                     "May I take a message?")


class Variables:
    def __init__(self, cfg, clock, brief, tickets, minutes_text=None, contacts=None):
        self.cfg, self.clock, self.brief, self.tickets, self.minutes_text = cfg, clock, brief, tickets, minutes_text
        self.contacts = contacts

    def build(self, purpose: str, token: str, callback_text: str = "", opening: str = "") -> dict[str, str]:
        now = self.clock.time()
        if purpose == "stranger":
            return {"greeting": STRANGER_GREETING, "caller_mode": "stranger", "now_text": "", "brief": "",
                    "pending_text": "", "minutes_text": "", "callback_text": "", "contacts_text": "",
                    "secret__desk_token": NO_TOKEN}
        opener = {
            "max": f"{greeting(now)}, {{sir}}. What can I do for you?",
            "callback": ANSWER_PAUSE + (opening or "{{SIR}}, it's {{CHIEF}}. I have the news you were waiting for."),
            "test": ANSWER_PAUSE + "{{SIR}}, this is the test call I announced on Telegram.",
        }[purpose]
        return {
            "greeting": opener,
            "caller_mode": "max" if purpose != "callback" else "callback",
            "now_text": uk_time(now).strftime("%A %d %B %Y, %H:%M UK time"),
            "brief": self.brief.render(),
            "pending_text": self.tickets.pending_lines() or "Nothing pending.",
            "minutes_text": self.minutes_text() if self.minutes_text else "",
            "callback_text": callback_text,
            "contacts_text": self.contacts.names_text() if self.contacts else "",      # names only: {{CHIEF}} is never given a number
            "secret__desk_token": token,
        }

    def build_guest(self, contact, purpose: str) -> dict[str, str]:
        """What the guest agent knows when it rings `contact`: who they are, why it is calling and the time. The opening line says
        at once who is calling ({{CHIEF}}, with the title in persona.py) and nothing about why: that comes only once they have confirmed
        who they are. It follows the same short pause as a call-back, so that a 'Hello?' is not talked over."""
        now = self.clock.time()
        return {
            "greeting": ANSWER_PAUSE + f"Hello, is that {contact.address_as}? It's {{CHIEF}}, {TITLE}.",
            "guest_name": contact.address_as,
            "relationship_to_max": re.sub(r"(?i)^your\b", "{{OWNER}}'s", contact.display, count=1),
            "purpose": plain(purpose, 600),
            "now_text": uk_time(now).strftime("%A %d %B %Y, %H:%M UK time"),
        }
