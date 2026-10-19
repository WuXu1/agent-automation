"""The minutes guard: {{OWNER}}'s phone budget is the plan's included agent minutes, nothing more.

Usage is the sum of every ElevenLabs conversation (calls, call-backs, tests) since the billing period began, each rounded up
to whole minutes, which errs on the safe side. At 80% {{OWNER}} gets a Telegram heads-up. At the limit (the included minutes minus a
small margin) the Twilio number is switched to a short "closed" message served by the desk, call-backs go to Telegram, and
everything is put back when the period resets.

The plan's ElevenLabs credits (shared by calls and every voice note) can run out before the minutes do. Then ElevenLabs cannot
answer the number at all, so the same switch happens when only `credit_reserve` credits are left (a heads-up first, at 80%), and
the line stays closed until enough credits are back. Voice notes need nothing here: when ElevenLabs refuses, they go out as text.
"""
from __future__ import annotations

import calendar
import datetime as dt
import logging
import math
import threading

from .eleven import ElevenError
from .twilio import TwilioError
from .util import uk_time

log = logging.getLogger("desk.minutes")
REFRESH_SECS = 600
REOPEN_BELOW = 0.95


def period_start(reset_unix: float) -> float:
    """The billing period began one calendar month before it resets."""
    reset = dt.datetime.fromtimestamp(reset_unix, dt.timezone.utc)
    year, month = (reset.year, reset.month - 1) if reset.month > 1 else (reset.year - 1, 12)
    day = min(reset.day, calendar.monthrange(year, month)[1])
    return reset.replace(year=year, month=month, day=day).timestamp()


def billed_minutes(conversations: list[dict]) -> int:
    return sum(math.ceil(c.get("call_duration_secs", 0) / 60) for c in conversations if c.get("call_duration_secs", 0) > 0)


class Minutes:
    def __init__(self, cfg, db, eleven, twilio, notifier, clock):
        self.cfg, self.db, self.eleven, self.twilio, self.notifier, self.clock = cfg, db, eleven, twilio, notifier, clock
        self._wake, self._stop = threading.Event(), threading.Event()
        self._thread: threading.Thread | None = None

    # -- state ------------------------------------------------------------------------------------
    def is_closed(self) -> bool:
        return self.db.kv_get("closed") == "1"

    def closed_reason(self) -> str:
        """'credits' when the line closed because the voice credits ran low, else 'minutes'."""
        return self.db.kv_get("closed_reason") or "minutes"

    def blocked_reason(self) -> str | None:
        if not self.is_closed():
            return None
        return f"the line is closed until the {'voice credits' if self.closed_reason() == 'credits' else 'minutes'} reset"

    def _credits(self) -> dict | None:
        used, limit = self.db.kv_get("credits_used"), self.db.kv_get("credits_limit")
        if used is None or limit is None:
            return None
        return {"used": int(used), "limit": int(limit), "left": max(0, int(limit) - int(used))}

    def status(self) -> dict:
        used = self.db.kv_get("minutes_used")
        reset = self.db.kv_get("minutes_reset")
        limit = self.cfg.limit_minutes
        if used is None:
            return {"known": False, "limit": limit, "closed": self.is_closed()}
        used = int(used)
        out = {"known": True, "used": used, "limit": limit, "left": max(0, limit - used), "fraction": used / limit,
               "reset": int(reset), "closed": self.is_closed()}
        credits = self._credits()
        if credits:
            out["credits"] = credits
        return out

    def text(self) -> str:
        s = self.status()
        if s["closed"]:
            what = "voice credits" if self.closed_reason() == "credits" else "call minutes"
            return f"THE PHONE LINE IS CLOSED: this month's {what} are used up."
        if not s["known"]:
            return ""
        resets = uk_time(s["reset"]).strftime("%-d %B")
        low = " Running low: keep calls short." if s["fraction"] >= self.cfg.warn_fraction else ""
        return (f"CALL MINUTES: {s['used']} of {s['limit']} used this billing period (resets {resets}); "
                f"{s['left']} left.{low}")

    # -- refreshing -----------------------------------------------------------------------------------
    def refresh(self) -> dict | None:
        try:
            sub = self.eleven.subscription()
            reset = int(sub["next_character_count_reset_unix"])
            conversations = self.eleven.conversations_since(int(period_start(reset)))
        except (ElevenError, KeyError, ValueError, TypeError) as exc:
            log.warning("could not read call minutes: %s", type(exc).__name__)
            return None
        used = billed_minutes(conversations)
        self.db.kv_set("minutes_used", str(used))
        self.db.kv_set("minutes_reset", str(reset))
        try:
            self.db.kv_set("credits_used", str(int(sub["character_count"])))
            self.db.kv_set("credits_limit", str(int(sub["character_limit"])))
        except (KeyError, ValueError, TypeError):
            pass                                    # the account did not say: the credits are simply not watched
        self._apply(used, str(reset))
        return self.status()

    def _apply(self, used: int, period_key: str) -> None:
        limit = self.cfg.limit_minutes
        credits = self._credits()
        if used >= limit * self.cfg.warn_fraction and self.db.kv_get("warned") != period_key:
            self.db.kv_set("warned", period_key)
            self.notifier.text(f"{{SIR}}, {used} of this month's {limit} call minutes are used. I will close the line at {limit}.",
                               "minutes")
        if credits and credits["used"] >= credits["limit"] * self.cfg.warn_fraction \
                and self.db.kv_get("credits_warned") != period_key:
            self.db.kv_set("credits_warned", period_key)
            self.notifier.text(f"{{SIR}}, {credits['used']} of this month's {credits['limit']} ElevenLabs credits are used (calls and voice "
                               f"notes share them). With {self.cfg.credit_reserve} left I will close the phone line; when they run out, "
                               "voice replies come as text.", "minutes")
        out_of_minutes = used >= limit
        out_of_credits = bool(credits) and credits["left"] <= self.cfg.credit_reserve
        if (out_of_minutes or out_of_credits) and not self.is_closed():
            self.db.kv_set("closed", "1")
            self.db.kv_set("closed_period", period_key)
            self.db.kv_set("closed_reason", "minutes" if out_of_minutes else "credits")
            self.db.kv_set("line_switched", "0")
            if out_of_minutes:
                self.notifier.text("{{SIR}}, this month's call minutes are used up, so the phone line is closed until they reset. "
                                   "Message me on Telegram in the meantime.", "minutes")
            else:
                self.notifier.text("{{SIR}}, this month's ElevenLabs credits are nearly used up, so the phone line is closed until they "
                                   "reset. Message me on Telegram in the meantime; voice replies will come as text once they run out.",
                                   "minutes")
        if self.is_closed() and (out_of_minutes or out_of_credits):     # keep the reason true if it changes while closed
            self.db.kv_set("closed_reason", "minutes" if out_of_minutes else "credits")
        # reopening needs room on both counts: a fresh period (or minutes well under the limit) and credits well above the reserve
        credits_ok = not credits or credits["left"] > 2 * self.cfg.credit_reserve
        minutes_ok = self.db.kv_get("closed_period") != period_key or used < limit * REOPEN_BELOW
        if self.is_closed() and self.db.kv_get("line_switched") != "1":
            self._switch_line(closed=True)
        elif self.is_closed() and minutes_ok and credits_ok and not out_of_minutes:
            if self._switch_line(closed=False):
                self.db.kv_set("closed", "0")
                self.db.kv_set("closed_reason", "")
                self.notifier.text("{{SIR}}, the phone line is open again.", "minutes")

    def _switch_line(self, closed: bool) -> bool:
        """Point the Twilio number at the closed message, or back at the agent. True when it is done."""
        sid = self.cfg.twilio_number_sid
        if self.twilio is None or not sid:
            if closed:
                self.db.kv_set("line_switched", "1")
            return True
        closed_url = f"{self.cfg.public_base}/twiml/closed"
        try:
            if closed:
                current = self.twilio.get_number(sid).get("voice_url") or ""
                if current and current != closed_url:
                    self.db.kv_set("line_voice_url", current)
                self.twilio.set_voice_url(sid, closed_url)
                self.db.kv_set("line_switched", "1")
            else:
                original = self.db.kv_get("line_voice_url")
                if original:
                    self.twilio.set_voice_url(sid, original)
                self.db.kv_set("line_switched", "0")
        except TwilioError as exc:
            log.warning("could not switch the phone line (%s); will retry", exc)
            return False
        return True

    # -- the loop -----------------------------------------------------------------------------------------
    def poke(self) -> None:
        self._wake.set()

    def start(self) -> None:
        if self._thread:
            return

        def loop():
            while not self._stop.is_set():
                try:
                    self.refresh()
                except Exception as exc:  # noqa: BLE001
                    log.warning("minutes refresh failed: %s", type(exc).__name__)
                self._wake.wait(REFRESH_SECS)
                self._wake.clear()
        self._thread = threading.Thread(target=loop, daemon=True, name="minutes")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
