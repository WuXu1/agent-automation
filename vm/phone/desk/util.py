"""Small shared helpers: clock, UK time and quiet hours, speech cleaning, secret scrubbing, phone numbers."""
from __future__ import annotations

import datetime as dt
import re
import secrets
import time
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
QUIET_START, WAKE_HOUR = 23, 7


class Clock:
    """The real clock. Tests pass a FakeClock with the same two methods."""

    def time(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def uk_time(ts: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts, UK)


def is_quiet(ts: float) -> bool:
    """Quiet hours are 23:00 to 07:00 UK time."""
    hour = uk_time(ts).hour
    return hour >= QUIET_START or hour < WAKE_HOUR


def next_wake(ts: float) -> float:
    """ts itself when it is not quiet, else the next 07:00 UK."""
    if not is_quiet(ts):
        return ts
    local = uk_time(ts)
    day = local.date() if local.hour < WAKE_HOUR else local.date() + dt.timedelta(days=1)
    return dt.datetime.combine(day, dt.time(WAKE_HOUR), UK).timestamp()


def greeting(ts: float) -> str:
    hour = uk_time(ts).hour
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 18:
        return "Good afternoon"
    return "Good evening"


def age_words(seconds: float | None) -> str:
    if seconds is None:
        return "unknown age"
    minutes = int(seconds // 60)
    if minutes < 2:
        return "just now"
    if minutes < 90:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 36:
        return f"{hours} h ago"
    return f"{hours // 24} days ago"


def new_token() -> str:
    return secrets.token_urlsafe(24)


def clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


REQUEST_PREFIX = "Ring "


def request_text(display: str, purpose: str) -> str:
    """The request text of a guest ticket: who is to be rung and what for."""
    return f"{REQUEST_PREFIX}{display}: {purpose}"


def display_of(request: str) -> str:
    """Who a guest ticket's request was about ('Ring your father: ask ...' -> 'your father')."""
    text = request[len(REQUEST_PREFIX):] if request.startswith(REQUEST_PREFIX) else request
    return text.split(":", 1)[0].strip() or "them"


_BRACKETED = re.compile(r"\[[^\]]{0,40}\]")


def plain(text: str, limit: int) -> str:
    """One line of plain words: audio tags such as [long pause], braces and angle brackets out, secrets scrubbed, whitespace
    collapsed, clipped to `limit`. For anything a person or a model said that is about to be passed on."""
    text = scrub(_BRACKETED.sub(" ", text or ""))
    return clip(re.sub(r"\s+", " ", re.sub(r"[{}<>]", " ", text)).strip(), limit)


_AI_NOUN = re.compile(r"\b(an?\s+|the\s+)?AI(?:[- ](?:powered|based|driven))?(?:[- ]voice)?[- ](assistants?|agents?|chatbots?|bots?)\b", re.I)


def drop_ai(text: str) -> str:
    """ElevenLabs' own call summaries call {{CHIEF}} 'the AI assistant'; {{OWNER}} does not want AI said or shown for {{CHIEF}}, so the notes made
    from those summaries say 'the assistant' ('an AI assistant' becomes 'an assistant')."""
    return _AI_NOUN.sub(lambda m: (m.group(1) or "") + m.group(2).lower(), text or "")


_PHONE = re.compile(r"\+?\(?\d[\d ().-]{7,}\d")


def hide_numbers(text: str) -> str:
    """Anything that looks like a phone number becomes '[number]': for text that may echo one back, such as an API error."""
    return _PHONE.sub("[number]", text or "")


def truthy(value) -> bool:
    """A yes from a tool call: a real boolean, or the word a model may send in its place."""
    return value is True or str(value).strip().lower() in ("true", "yes", "1")


def normalise_number(number: str) -> str:
    """'07700 900123' and '+44 7700 900123' compare equal (UK numbers; no other country is ever dialled)."""
    digits = re.sub(r"[^\d+]", "", number or "")
    if digits.startswith("00"):
        return "+" + digits[2:]
    if digits.startswith("0"):
        return "+44" + digits[1:]
    if digits and not digits.startswith("+"):
        return "+" + digits
    return digits


# Nothing credential-shaped is ever logged, sent to Telegram, or put in a brief.
_SCRUBS = [
    (re.compile(r"\b(sk|rk|pk)[_-][A-Za-z0-9_\-]{12,}"), "[key redacted]"),
    (re.compile(r"\b(ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{12,}"), "[key redacted]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "[key redacted]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"), "[key redacted]"),
    (re.compile(r"\bey[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{6,}"), "[key redacted]"),
    (re.compile(r"(?i)\b(token|authtoken|key|password|secret)=[^\s&]+"), r"\1=[redacted]"),
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "[redacted]"),
    (re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"), "[redacted]"),
]


def scrub(text: str) -> str:
    for pattern, repl in _SCRUBS:
        text = pattern.sub(repl, text or "")
    return text


_URL = re.compile(r"https?://\S+")
_PATH = re.compile(r"(?<![\w.])(?:~|/)[\w.\-]+(?:/[\w.\-]+)+")
_TAGS = re.compile(r"MEDIA:\S+|\[\[[a-z_]+\]\]")
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+", re.M)
_MARKS = re.compile(r"[*_`#>|]+")


def clean_for_speech(text: str) -> str:
    """Markdown, URLs, file paths and tool tags out; whitespace collapsed. What is left can be said aloud."""
    out = _TAGS.sub("", _URL.sub("", text or ""))
    out = _BULLET.sub("", _PATH.sub("", out))
    return re.sub(r"\s+", " ", _MARKS.sub("", out)).strip()
