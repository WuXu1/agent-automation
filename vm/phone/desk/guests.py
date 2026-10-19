"""Guest calls: {{CHIEF}} rings a person from the contact book for {{OWNER}}, and brings back what they said.

Two halves. The request half runs inside {{CHIEF}}'s `call_someone` tool: it finds the person, refuses unless {{OWNER}} has said yes, opens a
ticket of kind `guest` and places the call with the guest agent through the dialer's own gate (`Dialer.place_guest`). The settle
half (further down) runs when ElevenLabs posts the call's transcript.

Nothing a person says on a guest call is ever shown to a Hermes agent (the same rule as for a stranger who rings in): the report
is the guest agent's own one-sentence outcome, cleaned and clipped, and the transcript goes to Telegram as text. A guest ticket is
waiting for a phone call, not for a Hermes run, so the runner never starts one. No answer ever contains the person's number.
"""
from __future__ import annotations

import json
import logging
import re
import threading

from . import summary
from .dialer import DialBlocked
from .util import REQUEST_PREFIX, clip, display_of, drop_ai, plain, request_text, truthy  # noqa: F401 (display_of and request_text are re-exported)

log = logging.getLogger("desk.guests")
DEDUPE_SECS = 90                  # the same request in the same call within this long is the same call
PURPOSE_MAX = 600                 # what the call is for: a question, a message or a chat, with its details
REPORT_MAX = 2400                 # the longest report that is kept: a long chat has a great deal to report, and nothing is cut that a person said
RICH_WORDS = 8                    # a reason this long is the agent's own full report
SHORT_SECS = 15                   # a call that ended sooner than this with nothing said was a hang-up
OPENER_MAX = 330                  # what {{CHIEF}} says the moment {{OWNER}} answers a call-back: the headline; the whole report follows when {{OWNER}} replies
VOICE_MAX = 2000                  # a Telegram voice note carries the whole report (about two minutes of speech)
TRANSCRIPT_PART = 3200            # characters of transcript in one Telegram message: a longer call goes out in several, none of it dropped
VOICE_SENT = "guest-voice:"       # kv key prefix: this guest ticket's news has already gone to Telegram as a voice note
MIN_READBACK_SECS = 3.0           # a yes takes longer than a chain of tool calls in one breath: a call can only follow a read-back
PENDING_SECS = 900                # and the yes is good for fifteen minutes
CHAT = "telegram-chat"            # the conversation id of a request that came from {{OWNER}}'s Telegram chat, not from a phone call


def _failed(message: str) -> tuple[int, dict]:
    return 200, {"status": "failed", "message": message}


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _lead(text: str, limit: int) -> str:
    """The first sentences of `text` that fit in `limit` characters: at least the first, cut at a word if it alone is longer."""
    out = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if out and len(out) + 1 + len(sentence) > limit:
            break
        out = f"{out} {sentence}".strip()
    if len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "."
    return out


def item_for(row: dict, whole: bool = False) -> str:
    """What {{CHIEF}} says to {{OWNER}} about a finished guest ticket, after "{{SIR}}, it's {{CHIEF}}.". The call-back opens with the headline of a long
    report (and says there is more: he then tells {{OWNER}} all of it when he replies); the Telegram voice note that goes out the moment the
    call ends carries `whole` report. A short report is the same in both."""
    if row["status"] == "done":
        answer = (row["answer"] or "").strip()
        if whole or len(answer) <= OPENER_MAX:
            return f"I've made the call you asked for. {answer}"
        return f"I've made the call you asked for. {_lead(answer, OPENER_MAX)} There is more, and I will go through all of it."
    return f"The call you asked me to make did not work out. {row['error'] or ''}".strip()


def end_reason(transcript: list) -> str:
    """The `reason` the guest agent gave when it ended the call: its own one-sentence report to {{OWNER}}, cleaned and clipped."""
    reason = ""
    for turn in transcript:
        for call in turn.get("tool_calls") or []:
            if call.get("tool_name") != "end_call":
                continue
            try:
                params = json.loads(call.get("params_as_json") or "{}")
            except ValueError:
                continue
            if isinstance(params, dict) and isinstance(params.get("reason"), str):
                reason = params["reason"]
    return plain(reason, REPORT_MAX)


def collected(outcome) -> str:
    """ElevenLabs' own extraction of what the person said (see agent_config.GUEST_OUTCOME), cleaned for speech. It is the second source of
    the report, for a call nobody ended with a reason."""
    return plain(drop_ai(outcome if isinstance(outcome, str) else ""), REPORT_MAX)


def outcome_line(display: str, transcript: list, duration_secs: float, voicemail: bool, termination: str = "", outcome="") -> str:
    """The report {{OWNER}} is told about a guest call. It is made, in order of preference, from the guest agent's own end_call reason (when it
    is a full account), from ElevenLabs' extraction of the outcome (when the call ended without one: the person hung up during the
    goodbye), from a short reason, or from what the call looked like. Never by asking an agent to read the call."""
    if voicemail:
        return f"The call to {display} went to voicemail, so I left no message."
    if not summary.user_turns(transcript):
        return f"{_cap(display)} did not answer."
    reason, said = end_reason(transcript), collected(outcome)
    if len(reason.split()) >= RICH_WORDS:
        return reason
    if len(said.split()) >= 3:
        return said
    if len(reason.split()) >= 2:
        return reason
    if not reason and duration_secs < SHORT_SECS:
        return f"{_cap(display)} picked up and ended the call before I could ask."
    ended = "hung up" if "remote party" in (termination or "").lower() else "ended the call"
    return f"{_cap(display)} spoke with me for {int(duration_secs)} seconds and then {ended} before I could report: the transcript is on Telegram."


class Guests:
    def __init__(self, cfg, db, tickets, calls, dialer, notifier, variables, contacts, clock, poke=None):
        self.cfg, self.db, self.tickets, self.calls, self.dialer = cfg, db, tickets, calls, dialer
        self.notifier, self.variables, self.contacts, self.clock = notifier, variables, contacts, clock
        self.poke = poke or (lambda *_args: None)       # wakes the call-back scheduler when a guest ticket finishes
        self._lock = threading.Lock()                   # two copies of one tool call must never place two calls
        self._pending: dict[int, dict] = {}             # per call: who {{CHIEF}} is to read back, and what, waiting for {{OWNER}}'s yes
        self.last_thread: threading.Thread | None = None      # the transcript text goes out on its own thread (tests join it)

    # -- from Telegram: the same tool, the same gates -----------------------------------------------------------------------
    def chat_call(self) -> dict:
        """The stand-in for a phone call when {{OWNER}} asks {{CHIEF}} in the Telegram chat. One permanent identity, so the read-back and the yes
        that follows it belong together, exactly as they do within one call (and expire after the same fifteen minutes)."""
        return {"id": CHAT, "purpose": "chat", "conversation_id": CHAT}

    def request_from_chat(self, name, purpose, confirmed) -> tuple[int, dict]:
        return self.request(self.chat_call(), name, purpose, confirmed)

    # -- the request half: {{CHIEF}}'s tool ------------------------------------------------------------------------------------
    def request(self, call: dict, name, purpose, confirmed) -> tuple[int, dict]:
        """(HTTP status, payload). Always status 200: ElevenLabs hides the error text of a webhook tool that answers with an
        error status, so every problem is a payload of status 'failed' with a sentence {{CHIEF}} can say."""
        if call.get("purpose") not in ("max", "callback", "chat"):
            return _failed("Calls to other people are not made from a test. Tell {{OWNER}} it will work on a real call.")
        if not self.cfg.guest_agent_id:
            return _failed("Guest calls are not set up yet.")
        if not self.contacts.all():
            return _failed("I have nobody I may ring yet.")
        name = " ".join(str(name or "").split())
        if not name:
            return _failed("Who should I ring? Ask {{OWNER}}.")
        contact = self.contacts.find(name)
        if contact is None:
            return _failed(f"I have no contact called {name}. The people I may ring are: {self.contacts.names_text()}.")
        purpose = plain(str(purpose or ""), PURPOSE_MAX)
        if not purpose:
            return _failed(f"What should I say to {contact.display}? Ask {{OWNER}}.")
        with self._lock:
            earlier = self._earlier(call, contact, purpose)
            if earlier is not None:                     # a retried tool call, with the same words, is the same call
                return earlier
            refusal = self.dialer.guest_refusal(contact)
            if refusal is not None:                     # too late, too soon, too many: said now, before {{OWNER}} is asked for a yes
                status, payload = _failed(f"I cannot ring {contact.display} now: {refusal.reason}.")
                return status, {**payload, "contact": contact.display}
            now = self.clock.time()
            self._pending = {key: p for key, p in self._pending.items() if now - p["at"] <= PENDING_SECS}
            waiting = self._pending.get(call.get("id"))
            ready = (truthy(confirmed) and waiting is not None and waiting["key"] == contact.key
                     and now - waiting["at"] >= MIN_READBACK_SECS)
            if not ready:
                # {{CHIEF}} must read the call back to {{OWNER}} and wait for his yes first: whatever is asked now is only recorded as what
                # he is to read back (and every early or unconfirmed request restarts the clock, so a chain of calls in one
                # breath can never add up to a confirmation)
                self._pending[call.get("id")] = {"key": contact.key, "purpose": purpose, "at": now}
                return 200, {"status": "needs_yes", "contact": contact.display,
                             "message": f"NOBODY HAS BEEN RUNG YET. Read this back to {{OWNER}} in one sentence and wait for his clear yes; only "
                                        f"then call this again with confirmed true: ring {contact.display} and say: {purpose}"}
            purpose = self._pending.pop(call.get("id"))["purpose"]      # {{OWNER}} said yes to what was read back, so that is what is said
            return self._ring(call, contact, purpose)

    def _ring(self, call: dict, contact, purpose: str) -> tuple[int, dict]:
        request = request_text(contact.display, purpose)
        earlier = self._earlier(call, contact, purpose)
        if earlier is not None:                         # the words {{OWNER}} said yes to were already acted on a moment ago
            return earlier
        ticket = self.tickets.open("guest", "default", request, "when_done", conversation_id=call.get("conversation_id"))
        placed = self.calls.prepare_outbound("guest")
        values = self.variables.build_guest(contact, purpose)
        try:
            dial = self.dialer.place_guest(contact, values, placed,
                                           claim=lambda dial_id: self.tickets.attach_dial(ticket["id"], dial_id))
        except DialBlocked as exc:
            self.calls.discard(placed["id"])
            return self._fail(ticket, f"I cannot ring {contact.display} now: {exc.reason}.", contact)
        except Exception as exc:  # noqa: BLE001 - a ticket must never be left waiting for a call that was not placed
            log.warning("guest call failed before it was placed: %s", type(exc).__name__)
            self.calls.discard(placed["id"])
            return self._fail(ticket, "Something went wrong placing that call, and I will not try again by myself.", contact)
        if dial["status"] == "called":
            log.info("guest call %s placed for ticket %s", dial["id"], ticket["id"])
            return self._calling(self.tickets.get(ticket["id"]), contact)
        if dial["status"] == "failed":
            return self._fail(ticket, "The call could not be placed.", contact)
        return self._fail(ticket, "I could not confirm that the call went out, and I will not try again by myself.", contact)

    def _earlier(self, call: dict, contact, purpose: str):
        """The answer for the same request in the same call within DEDUPE_SECS (a retried tool call must not ring twice), or None."""
        ticket = self.tickets.find_recent(call.get("conversation_id"), "guest", "default", request_text(contact.display, purpose),
                                          self.clock.time() - DEDUPE_SECS)
        if ticket is None:
            return None
        if ticket["status"] == "done":
            self.tickets.set_delivery([ticket["id"]], "in_call")
            return 200, {"status": "done", "agent": "{{CHIEF}}", "contact": contact.display, "answer": ticket["answer"],
                         "needs_max": False, "ticket": ticket["id"]}
        return self._calling(ticket, contact)

    def _calling(self, ticket: dict, contact) -> tuple[int, dict]:
        return 200, {"status": "calling", "agent": "{{CHIEF}}", "contact": contact.display, "ticket": ticket["id"],
                     "message": f"Ringing {contact.display} now. Tell {{OWNER}} you will ring him back with what they say."}

    def _fail(self, ticket: dict, message: str, contact=None) -> tuple[int, dict]:
        """The call was not made: the ticket fails, and since {{CHIEF}} says so on the call it is never delivered again. The answer names
        the person, so that the post-call check knows this request ended in words and not still waiting for a yes."""
        self.tickets.fail(ticket["id"], message)
        self.tickets.set_delivery([ticket["id"]], "in_call")
        status, payload = _failed(message)
        return status, {**payload, **({"contact": contact.display} if contact is not None else {})}

    # -- the settle half: ElevenLabs reports the call ---------------------------------------------------------------------
    def finish(self, dial: dict | None, conversation_id: str, duration_secs: int, transcript: list, termination: str = "",
               outcome: str = "") -> None:
        """The post-call transcript of a guest call. The ticket finishes with a sentence; the scheduler (callbacks.py) carries it
        to {{OWNER}} by a call-back or, failing that, Telegram. Nothing here asks an agent to read what the person said. (`dial` is None
        for a call by the guest agent that matches no dial the desk recorded: it still goes nowhere near an agent.)"""
        ticket = self.tickets.by_dial(dial["id"], "guest") if dial else None
        display = display_of(ticket["request"]) if ticket else "them"
        voicemail = summary.had_voicemail(transcript, termination)
        spoke = summary.user_turns(transcript) > 0 and not voicemail
        if dial:
            self.dialer.settle(dial["id"], "answered" if spoke else "no_answer")
        self._report(ticket, outcome_line(display, transcript, duration_secs, voicemail, termination, outcome))
        self._announce_later(ticket, display, duration_secs, transcript, spoke)

    def failed(self, dial: dict | None, reason: str = "") -> None:
        """The call never connected (nobody answered, the line was busy, or it could not be placed)."""
        ticket = self.tickets.by_dial(dial["id"], "guest") if dial else None
        display = display_of(ticket["request"]) if ticket else "them"
        if dial:
            self.dialer.settle(dial["id"], "no_answer")
        reason = (reason or "").lower()
        if "no-answer" in reason or "no answer" in reason:
            self._report(ticket, f"{_cap(display)} did not answer.")
        elif "busy" in reason:
            self._report(ticket, f"{_cap(display)}'s line was busy.")
        elif ticket is not None:
            self.tickets.fail(ticket["id"], f"The call to {display} did not connect.")
            self.poke()
        self._announce_later(ticket, display, 0, [], False)

    def _report(self, ticket: dict | None, line: str) -> None:
        if ticket is not None and ticket["status"] in ("new", "running"):
            self.tickets.finish(ticket["id"], "DONE: " + line, limit=REPORT_MAX + 16)      # the whole report, not a colleague's 1,500
            self.poke()

    def _announce_later(self, ticket: dict | None, display: str, duration_secs: int, transcript: list, spoke: bool) -> None:
        if ticket is None and not spoke:
            return
        self.last_thread = threading.Thread(target=self._announce, args=(ticket["id"] if ticket else None, display, duration_secs,
                                                                         transcript, spoke), daemon=True, name="guest-announce")
        self.last_thread.start()

    def _announce(self, ticket_id: int | None, display: str, duration_secs: int, transcript: list, spoke: bool) -> None:
        """On its own thread (speech and Telegram take seconds): the news as a Telegram voice note in {{CHIEF}}'s voice, in the words he will
        use when he rings {{OWNER}}, then, if the person spoke, what was said as plain text. Neither goes near an agent. If the voice note
        cannot be made, no flag is set and the call-back's own Telegram fallback still carries the news."""
        try:
            row = self.tickets.get(ticket_id) if ticket_id else None
            if row is not None and row["status"] in ("done", "failed", "lost"):
                if self.notifier.voice(clip(f"{{SIR}}, it's {{CHIEF}}. {item_for(row, whole=True)}", VOICE_MAX), "guest-voice", limit=VOICE_MAX):
                    self.db.kv_set(f"{VOICE_SENT}{ticket_id}", "1")
        except Exception as exc:  # noqa: BLE001 - the report itself has already been made
            log.warning("guest voice note failed: %s", type(exc).__name__)
        if spoke:
            self._send_transcript(display, duration_secs, transcript)

    def _send_transcript(self, display: str, duration_secs: int, transcript: list) -> None:
        """What was said, as plain text to {{OWNER}} (never to an agent). A long call goes out in several messages, in order, none dropped."""
        try:
            minutes, seconds = divmod(int(duration_secs), 60)
            parts, current = [], ""
            for line in summary.transcript_lines(transcript, user_label=_cap(display)):
                line = clip(line, TRANSCRIPT_PART)
                if current and len(current) + 1 + len(line) > TRANSCRIPT_PART:
                    parts.append(current)
                    current = line
                else:
                    current = f"{current}\n{line}" if current else line
            if current:
                parts.append(current)
            for number, part in enumerate(parts, 1):
                where = f", part {number} of {len(parts)}" if len(parts) > 1 else ""
                self.notifier.text(f"Call with {display} ({minutes}:{seconds:02d}{where})\n{part}", "guest-call")
        except Exception as exc:  # noqa: BLE001 - the report itself has already been made
            log.warning("guest transcript note failed: %s", type(exc).__name__)
