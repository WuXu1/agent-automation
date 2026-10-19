"""The one gate every outgoing call passes through.

The 4 Oct incident on the old line: a test dialled {{OWNER}}'s real phone, left him a voicemail and then rang again to report
the test. His verdict: "You didn't tell me we were testing that. Please fix this." So:

  - a test environment (DESK_TEST set) never dials, whatever the settings say;
  - `place` can only dial {{OWNER}}'s number; calls to other people go through `place_guest`, a separate gate that only dials a person
    in the contact book, with the guest agent, in live mode, and within its own per-person limits (the
    rehearsal contact, which is {{OWNER}}'s own phone, has only the ten-minute gap and the global limits, and its calls are never counted
    against anybody else's allowance);
  - dial_mode 'dry' (the default) records the dial and calls nobody; 'live' places real calls;
  - an announced test call is the one exception to 'dry' ({{OWNER}}'s own number only), and only when the operator sets
    DESK_ALLOW_TEST_DIAL=1; a guest call has no such exception;
  - the dial row is written, and its tickets are claimed, BEFORE the request goes out, so a crash can never ring twice;
  - a dial whose outcome is unknown (timeout, 5xx) is never repeated;
  - at most one dial per recent_dial_secs, max_dials_per_hour and max_dials_per_day.
"""
from __future__ import annotations

import hashlib
import logging
import os

from . import contacts
from .eleven import ElevenError
from .util import hide_numbers, normalise_number

log = logging.getLogger("desk.dialer")
PLACED = ("dialling", "called", "answered", "no_answer", "unknown")
ATTEMPTED = PLACED + ("failed",)


class DialBlocked(Exception):
    """`retry` is True when trying again soon may work (a rate limit); False when the call-back must go another way."""

    def __init__(self, reason: str, retry: bool = True):
        super().__init__(reason)
        self.reason, self.retry = reason, retry


def number_hash(number: str) -> str:
    return hashlib.sha256(normalise_number(number).encode()).hexdigest()[:16]


class Dialer:
    def __init__(self, cfg, db, eleven, calls, clock, env=None, blocked=None):
        self.cfg, self.db, self.eleven, self.calls, self.clock = cfg, db, eleven, calls, clock
        self.env = os.environ if env is None else env
        self.blocked = blocked or (lambda: None)       # returns a reason while the line is closed

    def _count(self, statuses: tuple, since: float) -> int:
        marks = ",".join("?" for _ in statuses)
        return self.db.q(f"SELECT COUNT(*) AS n FROM dials WHERE status IN ({marks}) AND created_at > ?",
                         statuses + (since,))[0]["n"]

    def get(self, dial_id: int) -> dict | None:
        rows = self.db.q("SELECT * FROM dials WHERE id = ?", (dial_id,))
        return rows[0] if rows else None

    def _update(self, dial_id: int, **fields) -> None:
        fields["updated_at"] = self.clock.time()
        names = ", ".join(f"{name} = ?" for name in fields)
        self.db.x(f"UPDATE dials SET {names} WHERE id = ?", tuple(fields.values()) + (dial_id,))

    def _count_guest(self, since: float, to_hash: str | None = None, not_to_hash: str | None = None) -> int:
        """Guest calls actually placed since `since` (a refused or aborted dial rang nobody), to one person, to everybody, or to
        everybody except one number."""
        marks = ",".join("?" for _ in PLACED)
        sql = f"SELECT COUNT(*) AS n FROM dials WHERE purpose = 'guest' AND status IN ({marks}) AND created_at > ?"
        params = PLACED + (since,)
        if to_hash:
            sql, params = sql + " AND to_hash = ?", params + (to_hash,)
        if not_to_hash:
            sql, params = sql + " AND to_hash != ?", params + (not_to_hash,)
        return self.db.q(sql, params)[0]["n"]

    def _check_global(self, now: float) -> None:
        if self._count(PLACED, now - self.cfg.recent_dial_secs):
            raise DialBlocked("a call was placed a moment ago")
        if self._count(ATTEMPTED, now - 3600) >= self.cfg.max_dials_per_hour:
            raise DialBlocked("hourly call limit reached")
        if self._count(ATTEMPTED, now - 86400) >= self.cfg.max_dials_per_day:
            raise DialBlocked("daily call limit reached")

    def _send(self, purpose: str, agent_id: str, to: str, variables: dict, call: dict, claim, live: bool, now: float) -> dict:
        """The part every call shares: record the dial, let the caller claim what it carries, only then send the request."""
        cur = self.db.x("INSERT INTO dials(purpose, to_hash, call_id, status, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                        (purpose, number_hash(to), call["id"], "dialling" if live else "dry", now, now))
        dial_id = cur.lastrowid
        if claim is not None and not claim(dial_id):
            self._update(dial_id, status="aborted")
            self.calls.discard(call["id"])
            raise DialBlocked("nothing left to deliver", retry=False)
        if not live:
            log.info("dry dial %s (%s): nobody was called", dial_id, purpose)
            self.calls.discard(call["id"])
            return self.get(dial_id)
        try:
            result = self.eleven.outbound_call(agent_id, self.cfg.phone_number_id, to, variables)
        except ElevenError as exc:
            reason = hide_numbers(str(exc))[:200]               # an API error may echo the number: it is never kept or logged
            self._update(dial_id, status="failed" if exc.definite else "unknown", error=reason)
            log.warning("dial %s %s: %s", dial_id, "failed" if exc.definite else "outcome unknown", reason)
            if exc.definite:
                self.calls.discard(call["id"])        # an unknown outcome keeps its token: the call may exist
            return self.get(dial_id)
        self._update(dial_id, status="called", conversation_id=result.get("conversation_id"),
                     call_sid=result.get("call_sid"))
        self.calls.attach_conversation(call["id"], result.get("conversation_id"))
        return self.get(dial_id)

    def place(self, purpose: str, to: str, variables: dict, call: dict, claim=None, announced_test: bool = False) -> dict:
        """Returns the dial row. Raises DialBlocked when the call must not or cannot be made now.
        `claim(dial_id)` runs after the dial is recorded and before the request; False aborts the dial."""
        if self.env.get("DESK_TEST"):
            raise DialBlocked("a test environment never dials", retry=False)
        if normalise_number(to) != normalise_number(self.cfg.max_number):
            raise DialBlocked("only {{OWNER}}'s number may be dialled", retry=False)
        live = self.cfg.dial_mode == "live" or (announced_test and self.env.get("DESK_ALLOW_TEST_DIAL") == "1")
        reason = self.blocked()
        if reason:
            raise DialBlocked(reason, retry=False)      # a closed line can stay closed for weeks: the news goes by Telegram
        now = self.clock.time()
        if live:
            self._check_global(now)
        return self._send(purpose, self.cfg.agent_id, to, variables, call, claim, live, now)

    def guest_refusal(self, contact) -> DialBlocked | None:
        """Why a guest call to `contact` cannot be made right now, as a DialBlocked that has not been raised, or None. `place_guest`
        enforces it at the moment of dialling; {{CHIEF}}'s tool asks it first, so that {{OWNER}} is never asked for a yes to a call that could
        not go out (the limits and the gap are all known before the read-back)."""
        if self.env.get("DESK_TEST"):
            return DialBlocked("a test environment never dials", retry=False)
        if not self.cfg.guest_agent_id:
            return DialBlocked("there is no guest agent set up", retry=False)
        if self.cfg.dial_mode != "live":
            return DialBlocked("calls to other people are switched off at the moment", retry=False)
        mine = normalise_number(self.cfg.max_number)
        if contact.rehearsal and normalise_number(contact.number) != mine:
            return DialBlocked("the rehearsal contact can only be {{OWNER}}'s own number", retry=False)
        if not contact.rehearsal and normalise_number(contact.number) == mine:
            return DialBlocked("that is {{OWNER}}'s own number: only the rehearsal contact may use it", retry=False)
        now = self.clock.time()
        reason = self.blocked()
        if reason:
            return DialBlocked(reason, retry=False)
        who = number_hash(contact.number)
        if self._count_guest(now - self.cfg.guest_min_gap_secs, who):
            return DialBlocked(f"{contact.display} was rung a few minutes ago")
        if not contact.rehearsal:       # the rehearsal rings {{OWNER}}'s own phone: it is never counted against the people the assistant rings
            if self._count_guest(now - 86400, who) >= self.cfg.guest_calls_per_contact_per_day:
                return DialBlocked(f"that is the limit of calls to {contact.display} for today", retry=False)
            if self._count_guest(now - 86400, not_to_hash=number_hash(self.cfg.max_number)) >= self.cfg.max_guest_calls_per_day:
                return DialBlocked("that is the limit of calls to other people for today", retry=False)
        try:
            self._check_global(now)
        except DialBlocked as exc:
            return exc
        return None

    def place_guest(self, contact, variables: dict, call: dict, claim=None) -> dict:
        """Ring a person in the contact book with the guest agent. Every refusal is a DialBlocked whose reason can be said in
        words; nothing is recorded or sent when one is raised. Only `live` mode rings (there is no dry run and no announced-test
        exception for a guest) and the number is always the one in the book, never one a caller supplied."""
        blocked = self.guest_refusal(contact)
        if blocked is not None:
            raise blocked
        return self._send("guest", self.cfg.guest_agent_id, contact.number, variables, call, claim, True, self.clock.time())

    def settle(self, dial_id: int, status: str) -> None:
        """answered / no_answer, from the post-call webhook."""
        self._update(dial_id, status=status)

    def by_conversation(self, conversation_id: str) -> dict | None:
        rows = self.db.q("SELECT * FROM dials WHERE conversation_id = ?", (conversation_id,))
        return rows[0] if rows else None

    def stuck(self, older_than_secs: float) -> list[dict]:
        """Dials still `called` long after any call could have ended: the post-call webhook never came."""
        return self.db.q("SELECT * FROM dials WHERE status = 'called' AND updated_at < ?",
                         (self.clock.time() - older_than_secs,))
