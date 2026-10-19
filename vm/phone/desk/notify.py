"""Telegram, from {{CHIEF}}'s own bot, through `hermes send` (the gateway's credentials and its proven connection).

Dry mode records what would have been sent and sends nothing. Every message, sent or not, is kept in the messages
table so the desk can say what it did.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from .util import clip, scrub

log = logging.getLogger("desk.notify")


def run_status(cmd: list[str], timeout: float = 90, env: dict | None = None) -> int:
    """Exit status of a command; -1 when it cannot run or times out."""
    try:
        return subprocess.run(cmd, cwd="/", capture_output=True, timeout=timeout,
                              env={**os.environ, **(env or {})}).returncode
    except (OSError, subprocess.SubprocessError):
        return -1


class Notifier:
    def __init__(self, cfg, db, clock, run=run_status, speak=None):
        self.cfg, self.db, self.clock, self.run, self.speak = cfg, db, clock, run, speak

    def _record(self, kind: str, text: str, voice: bool, sent: bool, error: str = "") -> None:
        self.db.x("INSERT INTO messages(kind, text, voice, mode, sent, error, created_at) VALUES(?,?,?,?,?,?,?)",
                  (kind, text, int(voice), self.cfg.notify_mode, int(sent), error, self.clock.time()))

    def _send(self, body: str) -> bool:
        status = self.run([self.cfg.hermes_bin, "send", "--to", "telegram", "-q", body], 90,
                          {"HERMES_HOME": self.cfg.hermes_home})
        return status == 0

    def text(self, text: str, kind: str) -> bool:
        """A plain message from {{CHIEF}}. True when it went out (or, in dry mode, was recorded)."""
        text = clip(scrub(text), 3500)
        if self.cfg.notify_mode != "live":
            self._record(kind, text, False, False)
            return True
        sent = self._send(text)
        self._record(kind, text, False, sent, "" if sent else "hermes send failed")
        if not sent:
            log.warning("telegram send failed (%s)", kind)
        return sent

    def voice(self, text: str, kind: str, limit: int = 700) -> bool:
        """The same words as a voice note in {{CHIEF}}'s voice. False (nothing sent) if it cannot be made. A fallback note is short; a caller
        with something {{OWNER}} wants in full (a guest call's report) passes a larger `limit`."""
        text = clip(scrub(text), limit)
        if self.cfg.notify_mode != "live":
            self._record(kind, text, True, False)
            return True
        if self.speak is None:
            return False
        path = Path(self.cfg.state_dir) / "tmp" / f"note-{int(self.clock.time())}.ogg"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.speak(text))
            sent = self._send(f"[[audio_as_voice]]\nMEDIA:{path}")
        except Exception as exc:  # noqa: BLE001 - the text message still goes out
            self._record(kind, text, True, False, type(exc).__name__)
            return False
        finally:
            path.unlink(missing_ok=True)
        self._record(kind, text, True, sent, "" if sent else "hermes send failed")
        return sent
