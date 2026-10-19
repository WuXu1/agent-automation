"""Tickets: every ask or job started from a call.

A ticket is written down BEFORE {{CHIEF}} says "I'll get {{ASSISTANT}} on that", so it survives dropped calls and restarts.
Work status and delivery status are separate. Delivery claims are atomic compare-and-set updates, so a result is
never delivered twice (the rule the old call-back queue learned the hard way).

  status:    new -> running -> done | failed | lost
  delivery:  none -> in_call                       (the answer was handed to {{CHIEF}} during the call)
             none -> dialling -> called -> delivered   ({{CHIEF}} rang {{OWNER}} back)
             none -> telegram                      (could not be delivered by phone, or {{OWNER}} asked not to be rung for it;
                                                    sent as a message instead)
"""
from __future__ import annotations

import re

from .config import DISPLAY
from .util import age_words, clean_for_speech, clip

FINAL = ("done", "failed", "lost")
ANSWER_MAX = 1500
# The agent starts its answer with this when it cannot finish without {{OWNER}}.
_NEEDS = re.compile(r"^[\s*_>#\-]*(?:NEEDS(?:\s+MAX)?|MAX)\s*[:：]\s*", re.I)
_DONE = re.compile(r"^[\s*_>#\-]*DONE(?![A-Za-z])\s*[:：]?\s*[\-–—]?\s*", re.I)
_QUOTES = {('"', '"'), ("“", "”"), ("‘", "’"), ("'", "'")}


def parse_answer(raw: str | None, limit: int = ANSWER_MAX) -> tuple[str, bool]:
    """(what can be said aloud, whether the agent needs {{OWNER}}). `limit` is for a caller with a reason to keep more (a guest call's report)."""
    text = (raw or "").strip()
    needs = bool(_NEEDS.match(text))
    text = _NEEDS.sub("", text, count=1) if needs else _DONE.sub("", text, count=1)
    text = clean_for_speech(text)
    if len(text) > 1 and (text[0], text[-1]) in _QUOTES:
        text = text[1:-1].strip()
    return clip(text, limit), needs


class Tickets:
    def __init__(self, db, clock):
        self.db, self.clock = db, clock

    # -- creating and working ------------------------------------------------------------
    def open(self, kind: str, agent: str, request: str, notify: str = "when_done",
             conversation_id: str | None = None) -> dict:
        cur = self.db.x(
            "INSERT INTO tickets(kind, agent, request, notify, conversation_id, created_at) VALUES(?,?,?,?,?,?)",
            (kind, agent, clip(request, 2000), notify, conversation_id, self.clock.time()))
        return self.get(cur.lastrowid)

    def find_recent(self, conversation_id: str | None, kind: str, agent: str, request: str, since: float) -> dict | None:
        """The same request, in the same call, opened since `since` and not failed: a caller who repeats themselves, or a tool
        call that was abandoned and retried, must not start the job twice."""
        if not conversation_id:
            return None
        rows = self.db.q("SELECT * FROM tickets WHERE conversation_id = ? AND kind = ? AND agent = ? AND request = ? "
                         "AND created_at >= ? AND status IN ('new','running','done') ORDER BY id DESC LIMIT 1",
                         (conversation_id, kind, agent, clip(request, 2000), since))
        return rows[0] if rows else None

    def release_unheard(self, since: float, until: float, heard: set[int]) -> list[int]:
        """Tickets handed over 'in the call' between `since` and `until` whose result {{CHIEF}} never received (the tool call was
        abandoned or the caller hung up first): back to undelivered, so the call-back or Telegram carries them."""
        released = []
        with self.db.tx():
            for row in self.db.q("SELECT id FROM tickets WHERE delivery = 'in_call' AND delivered_at >= ? AND delivered_at <= ?",
                                 (since, until)):
                if row["id"] not in heard:
                    self.db.x("UPDATE tickets SET delivery='none', delivered_at=NULL WHERE id=? AND delivery='in_call'", (row["id"],))
                    released.append(row["id"])
        return released

    def get(self, tid: int) -> dict | None:
        rows = self.db.q("SELECT * FROM tickets WHERE id = ?", (tid,))
        return rows[0] if rows else None

    def set_running(self, tid: int, run_id: str) -> None:
        self.db.x("UPDATE tickets SET status='running', run_id=? WHERE id=? AND status IN ('new','running')",
                  (run_id, tid))

    def attach_dial(self, tid: int, dial_id: int) -> bool:
        """A guest ticket's call is recorded: the ticket now waits for that phone call (there is no Hermes run behind it)."""
        cur = self.db.x("UPDATE tickets SET status='running', dial_id=? WHERE id=? AND status IN ('new','running')", (dial_id, tid))
        return bool(cur.rowcount)

    def by_dial(self, dial_id: int, kind: str) -> dict | None:
        rows = self.db.q("SELECT * FROM tickets WHERE dial_id = ? AND kind = ? ORDER BY id DESC LIMIT 1", (dial_id, kind))
        return rows[0] if rows else None

    def finish(self, tid: int, raw_answer: str | None, limit: int = ANSWER_MAX) -> dict | None:
        text, needs = parse_answer(raw_answer, limit)
        if not text:
            return self.fail(tid, "the agent returned an empty answer")
        cur = self.db.x("UPDATE tickets SET status='done', answer=?, needs_max=?, finished_at=? "
                        "WHERE id=? AND status IN ('new','running')", (text, int(needs), self.clock.time(), tid))
        return self.get(tid) if cur.rowcount else None

    def fail(self, tid: int, error: str, lost: bool = False) -> dict | None:
        cur = self.db.x("UPDATE tickets SET status=?, error=?, finished_at=? WHERE id=? AND status IN ('new','running')",
                        ("lost" if lost else "failed", clip(error, 300), self.clock.time(), tid))
        return self.get(tid) if cur.rowcount else None

    def unfinished(self) -> list[dict]:
        return self.db.q("SELECT * FROM tickets WHERE status IN ('new','running') ORDER BY id")

    def for_conversation(self, conversation_id: str) -> list[dict]:
        return self.db.q("SELECT * FROM tickets WHERE conversation_id = ? ORDER BY id", (conversation_id,))

    # -- delivery -------------------------------------------------------------------------
    def take_finished(self, conversation_id: str | None = None) -> list[dict]:
        """Finished tickets not yet handed to {{OWNER}} (of one call, or of all calls), marked in_call so each is handed over once."""
        with self.db.tx():
            if conversation_id is None:
                rows = self.db.q("SELECT * FROM tickets WHERE delivery = 'none' AND status IN ('done','failed','lost') "
                                 "ORDER BY id")
            else:
                rows = self.db.q("SELECT * FROM tickets WHERE conversation_id = ? AND delivery = 'none' "
                                 "AND status IN ('done','failed','lost') ORDER BY id", (conversation_id,))
            for row in rows:
                self.db.x("UPDATE tickets SET delivery='in_call', delivered_at=? WHERE id=?", (self.clock.time(), row["id"]))
        return rows

    def candidates(self) -> list[dict]:
        """Finished and not delivered anywhere yet, oldest first."""
        return self.db.q("SELECT * FROM tickets WHERE status IN ('done','failed','lost') AND delivery = 'none' "
                         "ORDER BY finished_at, id")

    def claim_for_callback(self, ids: list[int], dial_id: int) -> list[int]:
        """Atomically move tickets none -> dialling for this dial. Returns the ids actually claimed."""
        claimed = []
        with self.db.tx():
            for tid in ids:
                cur = self.db.x("UPDATE tickets SET delivery='dialling', dial_id=? WHERE id=? AND delivery='none' "
                                "AND status IN ('done','failed','lost')", (dial_id, tid))
                if cur.rowcount:
                    claimed.append(tid)
        return claimed

    def set_delivery(self, ids: list[int], delivery: str, only_from: tuple = ("none",)) -> list[int]:
        changed = []
        marks = ",".join("?" for _ in only_from)
        with self.db.tx():
            for tid in ids:
                cur = self.db.x(f"UPDATE tickets SET delivery=?, delivered_at=? WHERE id=? AND delivery IN ({marks})",
                                (delivery, self.clock.time(), tid) + tuple(only_from))
                if cur.rowcount:
                    changed.append(tid)
        return changed

    def settle_dial(self, dial_id: int, delivery: str) -> list[int]:
        """The call for this dial finished: its tickets become `delivered` or fall back to `telegram`."""
        rows = self.db.q("SELECT id FROM tickets WHERE dial_id = ? AND delivery IN ('dialling','called')", (dial_id,))
        return self.set_delivery([r["id"] for r in rows], delivery, only_from=("dialling", "called"))

    # -- text for the brief and the tools -------------------------------------------------
    def pending_lines(self) -> str:
        now = self.clock.time()
        lines = []
        for row in self.db.q("SELECT * FROM tickets WHERE status IN ('new','running') ORDER BY id"):
            lines.append(f"- {DISPLAY.get(row['agent'], row['agent'])} is working on: {clip(row['request'], 90)} "
                         f"(asked {age_words(now - row['created_at'])})")
        for row in self.db.q("SELECT * FROM tickets WHERE status IN ('done','failed','lost') AND delivery = 'none' "
                             "ORDER BY finished_at"):
            lines.append(f"- {DISPLAY.get(row['agent'], row['agent'])} has finished: {clip(row['request'], 90)} "
                         f"(not passed on to {{OWNER}} yet)")
        return "\n".join(lines)
