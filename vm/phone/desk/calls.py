"""Calls: one row per conversation, with the secret token that lets that conversation use the tools.

The token is handed to ElevenLabs as a secret dynamic variable (never shown to the model) and comes back as a header on
every tool request. Only a conversation the desk itself started or recognised as {{OWNER}}'s gets a working token, so a stranger
who rings the number can never reach the tools even if they talk the model into trying.
"""
from __future__ import annotations

import sqlite3

from .util import new_token

NO_TOKEN = "none"
SELFCHECK = "selfcheck-"          # conversation ids used by the rehearsal; they never count as real calls
_REAL = "(conversation_id IS NULL OR conversation_id NOT LIKE 'selfcheck-%')"


class Calls:
    def __init__(self, db, clock, cfg):
        self.db, self.clock, self.cfg = db, clock, cfg

    def _insert(self, conversation_id: str | None, direction: str, purpose: str, caller: str = "") -> dict:
        now = self.clock.time()
        cur = self.db.x(
            "INSERT INTO calls(token, conversation_id, direction, purpose, caller, created_at, expires_at) VALUES(?,?,?,?,?,?,?)",
            (new_token(), conversation_id, direction, purpose, caller, now, now + self.cfg.max_call_secs + 600))
        return self.get(cur.lastrowid)

    def get(self, call_id: int) -> dict | None:
        rows = self.db.q("SELECT * FROM calls WHERE id = ?", (call_id,))
        return rows[0] if rows else None

    def start_inbound(self, conversation_id: str, purpose: str, caller: str = "") -> dict:
        """{{OWNER}} rang (purpose 'max') or somebody else did ('stranger', whose number is kept so {{OWNER}} can be told it).
        Idempotent for webhook retries."""
        rows = self.db.q("SELECT * FROM calls WHERE conversation_id = ?", (conversation_id,))
        return rows[0] if rows else self._insert(conversation_id, "inbound", purpose, caller)

    def prepare_outbound(self, purpose: str) -> dict:
        """A token for a call the desk is about to place; the conversation id is attached after the call is made."""
        return self._insert(None, "outbound", purpose)

    def attach_conversation(self, call_id: int, conversation_id: str | None) -> None:
        if not conversation_id:
            return
        try:
            self.db.x("UPDATE calls SET conversation_id = ? WHERE id = ? AND conversation_id IS NULL",
                      (conversation_id, call_id))
        except sqlite3.IntegrityError:      # another row already carries this conversation: never fail a placed call
            pass

    def discard(self, call_id: int) -> None:
        """A call that was never placed (dry run, refused, aborted) leaves nothing behind."""
        self.db.x("DELETE FROM calls WHERE id = ? AND conversation_id IS NULL", (call_id,))

    def by_token(self, token: str | None) -> dict | None:
        """The call this token belongs to, if it is still valid and entitled to use the tools (a stranger's call and a guest call never are)."""
        if not token or token == NO_TOKEN:
            return None
        rows = self.db.q("SELECT * FROM calls WHERE token = ? AND expires_at > ? AND purpose NOT IN ('stranger', 'guest')",
                         (token, self.clock.time()))
        return rows[0] if rows else None

    def by_conversation(self, conversation_id: str) -> dict | None:
        rows = self.db.q("SELECT * FROM calls WHERE conversation_id = ?", (conversation_id,))
        return rows[0] if rows else None

    def end(self, conversation_id: str, duration_secs: int, user_turns: int) -> dict | None:
        self.db.x("UPDATE calls SET ended_at = ?, duration_secs = ?, user_turns = ? WHERE conversation_id = ?",
                  (self.clock.time(), duration_secs, user_turns, conversation_id))
        return self.by_conversation(conversation_id)

    def active(self) -> list[dict]:
        """Calls that have really started and not been reported finished (a lost webhook expires with the token)."""
        return self.db.q("SELECT * FROM calls WHERE ended_at IS NULL AND expires_at > ? AND purpose != 'stranger' "
                         f"AND conversation_id IS NOT NULL AND {_REAL}", (self.clock.time(),))

    def any_active(self) -> bool:
        return bool(self.active())

    def ended_within(self, secs: float) -> bool:
        rows = self.db.q(f"SELECT 1 FROM calls WHERE ended_at > ? AND {_REAL} LIMIT 1", (self.clock.time() - secs,))
        return bool(rows)

    def max_active_recently(self, within_secs: float) -> bool:
        """Has {{OWNER}} been on a call, or has one just ended, within the last `within_secs`? (He is plainly awake.)"""
        cutoff = self.clock.time() - within_secs
        rows = self.db.q("SELECT 1 FROM calls WHERE purpose = 'max' AND (ended_at IS NULL OR ended_at > ?) "
                         f"AND created_at > ? AND {_REAL} LIMIT 1", (cutoff, cutoff - 3600))
        return bool(rows)
