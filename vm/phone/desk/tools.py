"""The five tools {{CHIEF}} can call during a call: ask an agent, hand a job to {{CHIEF}}, set a reminder, check what has finished,
ring a person for {{OWNER}}.

ask_agent and do_for_max wait up to cfg.wait_secs (about 20 s) for the answer, or only cfg.long_wait_secs when {{CHIEF}} marks the job
long. A quick one comes back in the same breath; a slow one comes back as "pending" with a ticket, the work carries on, and {{CHIEF}}
rings {{OWNER}} back with the result (callbacks.py). set_reminder does not involve an agent at all: it asks Hermes' scheduler for a
one-shot Telegram message and answers in about a second.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
import subprocess

from .config import AGENTS, DISPLAY
from .util import UK, clip, truthy as _truthy, uk_time

log = logging.getLogger("desk.tools")
NOTIFY = ("when_done", "only_if_needed")
PATIENCE = ("quick", "long")
DEDUPE_SECS = 90          # the same request in the same call within this long is the same job
_DELAY = re.compile(r"^\s*(\d{1,3})\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\s*$", re.I)
_AT = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})\s*$")
_UNIT_SECS = {"m": 60, "h": 3600, "d": 86400}
TEAM = ("tutor", "assistant", "coach")

STYLE = ("Answer for the ear: one to three short spoken sentences, news first, in your usual register. Plain words only: no "
         "markdown, lists, URLs, file paths or ids. If you cannot finish without {{OWNER}}, begin your answer with 'NEEDS MAX:' and "
         "say exactly what you need from him. Do not message or phone anyone yourself: {{CHIEF}} passes your answer on. {{CHIEF}} is the "
         "only one who rings {{OWNER}}: if the request says to ring, call or message {{OWNER}}, leave that part out and just do the work and "
         "answer. Never say a password, key or token.")
ASK = "{{CHIEF}}, {{OWNER}}'s chief of staff, is asking you something on {{OWNER}}'s behalf while {{OWNER}} is on the phone. " + STYLE
DO_CONFIRMED = ("{{OWNER}} is on the phone through {{CHIEF}} and has just confirmed this request by voice. Treat it exactly as a 'yes' from "
                "{{OWNER}} on Telegram; the house rules still apply. When it is done, begin your answer with 'DONE:' and say in one to "
                "three short spoken sentences what you did and anything he must know. If you cannot finish without {{OWNER}}, begin "
                "with 'NEEDS MAX:'. Do not message or phone anyone yourself: {{CHIEF}} passes your answer on. {{CHIEF}} is the only one who "
                "rings {{OWNER}}: if the request says to ring, call or message {{OWNER}}, leave that part out. Plain words only: no "
                "markdown, lists, URLs, file paths or ids.")
DO_UNCONFIRMED = ("{{OWNER}} is on the phone through {{CHIEF}} and has asked for this, but has not confirmed it yet. If the house rules say "
                  "it needs his confirmation, do not carry it out: begin your answer with 'NEEDS MAX:' and state the action in "
                  "one sentence so {{CHIEF}} can read it back. Otherwise do it and begin with 'DONE:'. " + STYLE)


def compose(ticket: dict) -> tuple[str, str]:
    """(input, instructions) for the Hermes run behind a ticket."""
    if ticket["kind"] == "ask":
        return f"{{CHIEF}} asks, for {{OWNER}}: {ticket['request']}", ASK
    instructions = DO_CONFIRMED if ticket["kind"] == "do_confirmed" else DO_UNCONFIRMED
    return f"{{OWNER}}'s request, passed on by {{CHIEF}} from a phone call: {ticket['request']}", instructions


def parse_when(text: str, now: float) -> dt.datetime:
    """When a reminder goes off, in UK time to the minute. A delay ('10m', '2 hours', '1d') is rounded up, so it never goes off
    early; a date and time ('2026-10-05 18:30') is UK time as given. ValueError says, in words {{CHIEF}} can use, what is wrong."""
    text = str(text or "")
    delay, at = _DELAY.match(text), _AT.match(text)
    if delay:
        if int(delay.group(1)) == 0:
            raise ValueError("That time has already passed, so I cannot set it.")
        fire = uk_time(now + int(delay.group(1)) * _UNIT_SECS[delay.group(2)[0].lower()])
        if fire.second or fire.microsecond:
            fire = fire.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
    elif at:
        try:
            fire = dt.datetime(*(int(part) for part in at.groups()), tzinfo=UK)
        except ValueError:
            raise ValueError("I did not catch when that should be.") from None
    else:
        raise ValueError("I did not catch when that should be. Ask {{OWNER}} for a delay such as ten minutes, or a time such as six.")
    gap = fire.timestamp() - now
    if gap < 30:
        raise ValueError("That time has already passed, so I cannot set it.")
    if gap > 365 * 86400:
        raise ValueError("That is more than a year away, which is too far for a reminder.")
    return fire


def when_words(fire: dt.datetime, now: float) -> str:
    today = uk_time(now).date()
    clock = fire.strftime("%H:%M")
    if fire.date() == today:
        return f"{clock} today"
    if fire.date() == today + dt.timedelta(days=1):
        return f"{clock} tomorrow"
    return f"{clock} on {fire.strftime('%A %-d %B')}"


def create_reminder(cfg, fire: dt.datetime, text: str, run=subprocess.run) -> tuple[bool, str]:
    """Schedule a one-shot Telegram reminder with Hermes' own scheduler. The schedule is an exact time, because a bare '10m' on
    the command line means 'every 10 minutes, for ever'. Returns (done, the job's id or the reason it was not)."""
    prompt = ("{{OWNER}} asked {{CHIEF}}, by phone, to be reminded of this: " + text + ". Reply with one short sentence for {{OWNER}} in your "
              "usual register, for example '{{SIR}}, a reminder: ...'. Do not use any tools.")
    cmd = [cfg.hermes_bin, "cron", "create", fire.strftime("%Y-%m-%d %H:%M"), prompt,
           "--name", "Reminder: " + clip(text, 40), "--deliver", "telegram"]
    try:
        done = run(cmd, cwd="/", capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
                   env={**os.environ, "HERMES_HOME": cfg.hermes_home})
    except (OSError, subprocess.SubprocessError) as exc:
        return False, type(exc).__name__
    found = re.search(r"Created job:\s*(\w+)", done.stdout or "")
    if done.returncode == 0 and found:
        return True, found.group(1)
    return False, "the scheduler did not accept it"


class Tools:
    def __init__(self, cfg, tickets, calls, runner, clock, guests=None):
        self.cfg, self.tickets, self.calls, self.runner, self.clock = cfg, tickets, calls, runner, clock
        self.guests = guests
        self.make_reminder = lambda fire, text: create_reminder(cfg, fire, text)         # replaced in tests

    def _call_open(self, call: dict) -> bool:
        """False once the call has ended: a tool request can still arrive just after the hang-up, and what it produces cannot be
        handed over 'in the call' any more."""
        row = self.calls.get(call["id"]) if call.get("id") else call
        return row is None or row.get("ended_at") is None

    def _answer(self, call: dict, row: dict, name: str) -> tuple[int, dict]:
        """What the model is told about a ticket. A finished one counts as handed over only while the call is still open;
        otherwise it stays undelivered and the call-back or Telegram carries it."""
        if row["status"] in ("done", "failed", "lost") and self._call_open(call):
            self.tickets.set_delivery([row["id"]], "in_call")
        if row["status"] == "done":
            return 200, {"status": "done", "agent": name, "answer": row["answer"], "needs_max": bool(row["needs_max"]),
                         "ticket": row["id"]}
        if row["status"] in ("failed", "lost"):
            return 200, {"status": "failed", "agent": name, "ticket": row["id"],
                         "message": f"{name} could not finish that: {row['error'] or 'no reason given'}."}
        return 200, {"status": "pending", "agent": name, "ticket": row["id"],
                     "message": f"{name} is still working on it. Tell {{OWNER}} you will ring him back as soon as there is news."}

    def _work(self, call: dict, kind: str, profile: str, request: str, notify: str, wait: float) -> tuple[int, dict]:
        conversation_id = call.get("conversation_id")
        ticket = self.tickets.find_recent(conversation_id, kind, profile, request, self.clock.time() - DEDUPE_SECS)
        if ticket is None:
            ticket = self.tickets.open(kind, profile, request, notify, conversation_id=conversation_id)
            self.runner.start(ticket["id"])
        row = ticket if ticket["status"] == "done" else self.runner.wait(ticket["id"], wait)
        return self._answer(call, row, DISPLAY[profile])

    def _wait_for(self, args: dict):
        """How long to wait for this request, or the 400 to answer with. 'long' is for jobs that take minutes."""
        patience = str(args.get("patience") or "quick").strip().lower()
        if patience not in PATIENCE:
            return None, (400, {"error": f"patience must be one of {', '.join(PATIENCE)}"})
        return (self.cfg.long_wait_secs if patience == "long" else self.cfg.wait_secs), None

    def ask_agent(self, call: dict, args: dict) -> tuple[int, dict]:
        agent = str(args.get("agent", "")).strip().lower()
        question = str(args.get("question", "")).strip()
        notify = str(args.get("notify") or "when_done")
        if agent not in TEAM:
            return 400, {"error": f"agent must be one of {', '.join(TEAM)}"}
        if not question:
            return 400, {"error": "question is required"}
        if notify not in NOTIFY:
            return 400, {"error": f"notify must be one of {', '.join(NOTIFY)}"}
        wait, refusal = self._wait_for(args)
        if refusal:
            return refusal
        return self._work(call, "ask", AGENTS[agent][0], clip(question, 2000), notify, wait)

    def do_for_max(self, call: dict, args: dict) -> tuple[int, dict]:
        request = str(args.get("request", "")).strip()
        notify = str(args.get("notify") or "when_done")
        if not request:
            return 400, {"error": "request is required"}
        if notify not in NOTIFY:
            return 400, {"error": f"notify must be one of {', '.join(NOTIFY)}"}
        wait, refusal = self._wait_for(args)
        if refusal:
            return refusal
        kind = "do_confirmed" if _truthy(args.get("confirmed")) else "do"
        return self._work(call, kind, "default", clip(request, 2000), notify, wait)

    def set_reminder(self, call: dict, args: dict) -> tuple[int, dict]:
        """A reminder for {{OWNER}} on Telegram, set in about a second by the scheduler itself (no agent run). Mistakes in the time or
        the text come back as status 'failed' with a sentence, not as an HTTP error, so {{CHIEF}} is told why and can ask again."""
        text = clip(" ".join(str(args.get("text", "")).split()), 200)
        if not text:
            return 200, {"status": "failed", "agent": DISPLAY["default"],
                         "message": "There was nothing to be reminded of. Ask {{OWNER}} what the reminder is for."}
        now = self.clock.time()
        try:
            fire = parse_when(args.get("when"), now)
        except ValueError as exc:
            return 200, {"status": "failed", "agent": DISPLAY["default"], "message": str(exc)}
        request = f"Remind {{OWNER}} at {fire.strftime('%Y-%m-%d %H:%M')}: {text}"
        conversation_id = call.get("conversation_id")
        ticket = self.tickets.find_recent(conversation_id, "reminder", "default", request, now - DEDUPE_SECS)
        if ticket is None:
            ticket = self.tickets.open("reminder", "default", request, "when_done", conversation_id=conversation_id)
            done, detail = self.make_reminder(fire, text)
            if done:
                self.tickets.finish(ticket["id"], f"DONE: Reminder set for {when_words(fire, now)}: {text}.")
            else:
                log.warning("reminder not set: %s", detail)
                self.tickets.fail(ticket["id"], detail)
            ticket = self.tickets.get(ticket["id"])
        return self._answer(call, ticket, DISPLAY["default"])

    def call_someone(self, call: dict, args: dict) -> tuple[int, dict]:
        """Ring a person from the contact book for {{OWNER}}, with the guest agent, once {{OWNER}} has said yes. Every rule is in guests.py;
        every problem comes back as status 'failed' with a sentence, never as an HTTP error (ElevenLabs hides those)."""
        if self.guests is None:
            return 200, {"status": "failed", "message": "Guest calls are not set up yet."}
        return self.guests.request(call, args.get("name"), args.get("purpose"), args.get("confirmed"))

    def check_pending(self, call: dict, args: dict) -> tuple[int, dict]:
        if not self._call_open(call):
            return 200, {"finished": [], "still_working": [], "message": "The call has ended."}
        finished = self.tickets.take_finished()
        working = self.tickets.unfinished()
        if not finished and not working:
            return 200, {"finished": [], "still_working": [], "message": "Nothing new."}
        out = []
        for row in finished:
            entry = {"agent": DISPLAY.get(row["agent"], row["agent"]), "asked": clip(row["request"], 100), "ticket": row["id"]}
            if row["status"] == "done":
                entry.update(answer=row["answer"], needs_max=bool(row["needs_max"]))
            else:
                entry.update(failed=row["error"] or "no reason given")
            out.append(entry)
        return 200, {"finished": out,
                     "still_working": [{"agent": DISPLAY.get(r["agent"], r["agent"]), "asked": clip(r["request"], 100)}
                                       for r in working]}
