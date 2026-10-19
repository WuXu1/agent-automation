"""The two webhooks ElevenLabs calls: conversation initiation (someone is ringing) and post-call (a call ended).
Authentication happens in server.py; these handlers take parsed, already-authenticated input."""
from __future__ import annotations

import json
import logging
import threading

from . import summary
from .util import normalise_number

log = logging.getLogger("desk.webhooks")


def heard_tickets(transcript: list) -> set[int]:
    """Ticket numbers inside the tool results {{CHIEF}} actually received. An error result (such as 'abandoned due to user input')
    is one he did not, and a result listed by check_pending counts like any other."""
    heard: set[int] = set()
    for turn in transcript:
        for result in turn.get("tool_results") or []:
            if result.get("is_error"):
                continue
            value = result.get("result_value")
            try:
                data = json.loads(value) if isinstance(value, str) else value
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            for entry in [data] + [e for e in data.get("finished") or [] if isinstance(e, dict)]:
                if isinstance(entry.get("ticket"), int):
                    heard.add(entry["ticket"])
    return heard


def unplaced_rings(transcript: list) -> list[str]:
    """Who {{CHIEF}} was asked to ring on this call but never actually rang: the last thing `call_someone` said about them was needs_yes
    (the desk still needed {{OWNER}}'s yes when the call ended). {{CHIEF}} may nevertheless have told {{OWNER}} he was ringing: on 5 Oct 2026 at 23:08
    he asked the tool with no read-back before it, was refused, and said "Ringing your test dad now". {{OWNER}} is told what is true."""
    last: dict[str, str] = {}
    for turn in transcript:
        for result in turn.get("tool_results") or []:
            if result.get("tool_name") != "call_someone" or result.get("is_error"):
                continue
            value = result.get("result_value")
            try:
                data = json.loads(value) if isinstance(value, str) else value
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("contact") and data.get("status"):
                last[str(data["contact"])] = str(data["status"])
    return [who for who, status in last.items() if status == "needs_yes"]


class Webhooks:
    def __init__(self, cfg, db, calls, variables, dialer, callbacks, summaries, minutes, tickets, guests=None):
        self.cfg, self.db, self.calls, self.variables = cfg, db, calls, variables
        self.dialer, self.callbacks, self.summaries, self.minutes = dialer, callbacks, summaries, minutes
        self.tickets, self.guests = tickets, guests

    def initiation(self, body: dict) -> dict:
        """Someone rang the number. {{OWNER}} gets the full brief and a working tool token; anybody else gets message-taking."""
        caller = str(body.get("caller_id", ""))
        conversation_id = str(body.get("conversation_id", "")) or None
        is_max = bool(self.cfg.max_number) and normalise_number(caller) == normalise_number(self.cfg.max_number)
        purpose = "max" if is_max else "stranger"
        call = self.calls.start_inbound(conversation_id, purpose, "" if is_max else normalise_number(caller))
        log.info("incoming call from %s", "{{OWNER}}" if is_max else "someone else")
        return {"type": "conversation_initiation_client_data",
                "dynamic_variables": self.variables.build(purpose, call["token"])}

    def post_call(self, event: dict) -> dict:
        etype = event.get("type")
        data = event.get("data") or {}
        conversation_id = data.get("conversation_id")
        if not conversation_id:
            return {"ok": True, "ignored": "no conversation id"}
        seen = f"seen:{etype}:{conversation_id}"
        if self.db.kv_get(seen):                        # ElevenLabs retries; handle each event once
            return {"ok": True, "duplicate": True}
        dial = self.dialer.by_conversation(conversation_id)
        # Anything the guest agent said is a guest call, even if no dial matches it: it must never reach an agent that reads it
        by_agent = bool(self.cfg.guest_agent_id) and data.get("agent_id") == self.cfg.guest_agent_id
        guest = self.guests is not None and ((dial is not None and dial["purpose"] == "guest") or by_agent)
        if etype == "post_call_transcription" and guest:
            # a call to somebody else: the report is built from the guest agent's own words, and no agent reads the call
            transcript = data.get("transcript") or []
            meta = data.get("metadata") or {}
            duration = int(meta.get("call_duration_secs") or 0)
            self.calls.end(conversation_id, duration, summary.user_turns(transcript))
            found = ((data.get("analysis") or {}).get("data_collection_results") or {}).get("outcome")
            outcome = found.get("value") if isinstance(found, dict) else ""
            self.guests.finish(dial, conversation_id, duration, transcript, meta.get("termination_reason", ""), outcome)
            self.minutes.poke()
        elif etype == "call_initiation_failure" and guest:
            self.calls.end(conversation_id, 0, 0)
            self.guests.failed(dial, str(data.get("failure_reason") or ""))
            self.minutes.poke()
        elif etype == "post_call_transcription":
            transcript = data.get("transcript") or []
            meta = data.get("metadata") or {}
            duration = int(meta.get("call_duration_secs") or 0)
            turns = summary.user_turns(transcript)
            call = self.calls.end(conversation_id, duration, turns)
            self._release_unheard(call, transcript)
            answered = turns >= 1 and not summary.had_voicemail(transcript, meta.get("termination_reason", ""))
            if dial:
                self.callbacks.on_call_settled(dial["id"], answered)
            self.minutes.poke()
            if answered:                                # a voicemail greeting or a greeting-only call is not worth a note
                gist = ((data.get("analysis") or {}).get("transcript_summary") or "")
                call = self.calls.by_conversation(conversation_id)
                stranger = None if call is None or call["purpose"] != "stranger" else (call["caller"] or "")
                undone = unplaced_rings(transcript) if stranger is None else []
                threading.Thread(target=self._summarise, args=(conversation_id, duration, transcript, gist, stranger, undone),
                                 daemon=True, name="summary").start()
        elif etype == "call_initiation_failure":
            self.calls.end(conversation_id, 0, 0)
            if dial:
                self.callbacks.on_call_settled(dial["id"], False)
        self.db.kv_set(seen, "1")                       # only after it worked: a failure makes ElevenLabs retry
        return {"ok": True}

    def _release_unheard(self, call: dict | None, transcript: list) -> None:
        """A result handed over 'in the call' that {{CHIEF}} never received (his tool call was abandoned when the caller spoke, or the
        caller hung up first) must not be lost: it goes back to be passed on by a call-back or Telegram. (One call at a time in
        practice, so everything handed over between the call's start and end belongs to it.)"""
        if call is None or not any(turn.get("tool_calls") for turn in transcript):
            return                                      # no tool data to judge by: leave everything as it is
        released = self.tickets.release_unheard(call["created_at"], call["ended_at"], heard_tickets(transcript))
        if released:
            log.info("%d result(s) never reached the caller; they will be passed on", len(released))

    def _summarise(self, conversation_id, duration, transcript, gist, stranger=None, undone=()) -> None:
        try:
            if undone:                                  # said by the desk itself, from the tool's own answers, whatever {{CHIEF}} told {{OWNER}}
                who = " and ".join(undone)
                self.summaries.notifier.text(f"{{SIR}}, I did not ring {who} after all: the call ended before I had your yes. "
                                             "Ask me again whenever you like.", "call-not-rung")
            self.summaries.send(conversation_id, duration, transcript, gist, stranger_number=stranger, undone=undone)
        except Exception as exc:  # noqa: BLE001
            log.warning("call summary failed: %s", type(exc).__name__)
