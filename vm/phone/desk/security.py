"""Authentication helpers for the desk's public endpoints. Pure functions plus a small rate limiter."""
from __future__ import annotations

import collections
import hashlib
import hmac
import threading


def secrets_equal(given: str | None, expected: str | None) -> bool:
    """Constant-time comparison; an empty or missing secret never matches."""
    if not given or not expected:
        return False
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def verify_eleven_signature(raw_body: bytes, header: str | None, secret: str | None, now: float,
                            tolerance_secs: int = 1800) -> bool:
    """ElevenLabs post-call webhooks: header `ElevenLabs-Signature: t=<unix secs>,v0=<hex>` where the hex is
    HMAC-SHA256(secret, "<t>.<raw body>"). Same scheme and 30-minute tolerance as the official SDK."""
    if not header or not secret:
        return False
    timestamp = signature = None
    for part in header.split(","):
        part = part.strip()
        if part.startswith("t="):
            timestamp = part[2:]
        elif part.startswith("v0="):
            signature = part
    if not timestamp or not signature:
        return False
    try:
        if int(timestamp) < now - tolerance_secs:
            return False
    except ValueError:
        return False
    message = timestamp.encode("utf-8") + b"." + raw_body
    expected = "v0=" + hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def sign_eleven_payload(raw_body: bytes, secret: str, timestamp: int) -> str:
    """The header ElevenLabs would send (used by tests and the local end-to-end check)."""
    digest = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + raw_body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v0={digest}"


class RateLimiter:
    """At most `limit` events per `window` seconds per key (sliding window)."""

    def __init__(self, limit: int, window: float, clock):
        self.limit, self.window, self.clock = limit, window, clock
        self._events: dict[str, collections.deque] = {}
        self._lock = threading.Lock()

    def exhausted(self, key: str = "all") -> bool:
        """Is the limit already used up (without counting a new event)?"""
        now = self.clock.time()
        with self._lock:
            events = self._events.get(key)
            if not events:
                return False
            while events and events[0] <= now - self.window:
                events.popleft()
            return len(events) >= self.limit

    def allow(self, key: str = "all") -> bool:
        now = self.clock.time()
        with self._lock:
            events = self._events.setdefault(key, collections.deque())
            while events and events[0] <= now - self.window:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True
