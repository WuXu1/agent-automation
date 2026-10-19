"""The contact book: the people {{CHIEF}} may ring for {{OWNER}}.

It lives in the desk's private state folder as contacts.json (mode 0600) and is changed only by `desk.admin contact ...`, with the
number typed at a hidden prompt. A phone number is never shown in chat, never logged, never put in a note, a prompt or a file an
agent can read: {{CHIEF}} is told the names, and the dialer looks the number up here at the moment of the call. The file is read afresh
every time, so a change made by the admin command is seen by the running desk at once, and a record that is incomplete or invalid
(say, a hand edit) is skipped rather than dialled.
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import json
import logging
import os
import re
from pathlib import Path

from . import util

log = logging.getLogger("desk.contacts")

DEFAULT_HOURS = "09:00-21:00"
MAX_CONTACTS = 50
REHEARSAL_KEY = "test-dad"
_KEY = re.compile(r"[a-z]+(?:-[a-z]+)*")
_WORDS = re.compile(r"[^\W\d_](?:[^\W\d_]|[ .,'’-]){0,59}")        # letters, spaces and a little punctuation: no digits, no markup
_NUMBER = re.compile(r"\+\d{10,15}")
_TYPED = re.compile(r"\+?[\d ().-]+")                              # what may be typed: digits, spaces, brackets, dots, hyphens
_CLOCK = re.compile(r"(\d{1,2}):(\d{2})")


def normalise_name(spoken) -> str:
    """'My Dad!' -> 'dad'; 'the Test-Dad' -> 'test dad'. A leading my/the/your is dropped when something follows it."""
    text = re.sub(r"[\W_]+", " ", (spoken or "").lower().replace("'", "").replace("’", ""))
    words = text.split()
    if len(words) > 1 and words[0] in ("my", "the", "your"):
        words = words[1:]
    return " ".join(words)


def parse_hours(text: str) -> tuple[dt.time, dt.time]:
    """'09:00-21:00' -> (09:00, 21:00). ValueError for anything else, and for an end that is not after the start."""
    parts = [part.strip() for part in (text or "").split("-")]
    if len(parts) != 2:
        raise ValueError("the hours look like 09:00-21:00")
    clocks = []
    for part in parts:
        match = _CLOCK.fullmatch(part)
        if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
            raise ValueError("the hours look like 09:00-21:00")
        clocks.append(dt.time(int(match.group(1)), int(match.group(2))))
    if clocks[0] >= clocks[1]:
        raise ValueError("the end of the hours must be after the start")
    return clocks[0], clocks[1]


@dataclasses.dataclass(frozen=True)
class Contact:
    key: str                          # what the operator types: 'dad'
    display: str                      # how {{CHIEF}} speaks of them to {{OWNER}}: 'your father'
    address_as: str                   # how the guest agent greets them: 'Mr Smith'
    aliases: tuple = ()               # other things {{OWNER}} may say: 'dad', 'father'
    number: str = dataclasses.field(default="", repr=False)
    hours: str = DEFAULT_HOURS        # UK time: the only hours {{CHIEF}} may ring
    rehearsal: bool = False           # the test contact: {{OWNER}}'s own number, so {{OWNER}} can play the person

    def names(self) -> tuple:
        """Every spoken name this contact answers to, normalised, without repeats."""
        seen: list[str] = []
        for name in (self.key, self.display) + tuple(self.aliases):
            name = normalise_name(name)
            if name and name not in seen:
                seen.append(name)
        return tuple(seen)


def in_hours(contact: Contact, ts: float) -> bool:
    """UK time, the start inclusive and the end exclusive. Hours that cannot be read mean 'never'."""
    try:
        start, end = parse_hours(contact.hours)
    except ValueError:
        return False
    return start <= util.uk_time(ts).time() < end


class ContactBook:
    def __init__(self, path, max_number: str = ""):
        self.path = Path(path)
        self.max_number = util.normalise_number(max_number) if max_number else ""

    # -- reading -----------------------------------------------------------------------------------------------------------

    def _build(self, key, display, address_as, number, aliases=(), hours=DEFAULT_HOURS, rehearsal=False) -> Contact:
        """A checked Contact, or ValueError. The messages never contain the number."""
        if not isinstance(key, str) or len(key) > 30 or not _KEY.fullmatch(key):
            raise ValueError("a key is lower-case letters, with hyphens between words")
        for label, text in (("display name", display), ("address-as name", address_as)) + tuple(("alias", a) for a in aliases):
            if not isinstance(text, str) or not _WORDS.fullmatch(text) or not normalise_name(text):
                raise ValueError(f"the {label} must be plain words: letters and spaces, no digits")
        start, end = parse_hours(hours)
        typed = number.strip() if isinstance(number, str) else ""
        number = util.normalise_number(typed) if _TYPED.fullmatch(typed) else ""        # a stray letter is a typo, never silently dropped
        if not _NUMBER.fullmatch(number):
            raise ValueError("that is not a valid phone number (international form, 10 to 15 digits)")
        if rehearsal and number != self.max_number:
            raise ValueError("the rehearsal contact can only be {{OWNER}}'s own number")
        if not rehearsal and self.max_number and number == self.max_number:
            raise ValueError("that is {{OWNER}}'s own number: use add-rehearsal for the test contact")
        return Contact(key, display.strip(), address_as.strip(), tuple(a.strip() for a in aliases), number,
                       f"{start:%H:%M}-{end:%H:%M}", bool(rehearsal))

    def _read(self, strict: bool = False) -> list[Contact]:
        """Every valid contact. strict (before a write): damage anywhere in the file is an error, so that a write can never
        quietly throw away what a hand edit left behind."""
        try:
            raw = json.loads(self.path.read_text())
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            if strict:
                raise ValueError("the contact file cannot be read: fix or move it by hand first") from None
            log.warning("the contact file cannot be read (%s)", type(exc).__name__)
            return []
        records = raw.get("contacts") if isinstance(raw, dict) else None
        if not isinstance(records, list):
            if strict:
                raise ValueError("the contact file is not in the expected form: fix or move it by hand first")
            return []
        found = []
        for record in records:
            try:
                found.append(self._build(record["key"], record["display"], record["address_as"], record["number"],
                                         tuple(record.get("aliases") or ()), record.get("hours", DEFAULT_HOURS),
                                         record.get("rehearsal", False)))
            except (KeyError, TypeError, AttributeError, ValueError):
                if strict:
                    raise ValueError("a record in the contact file is not valid: fix it by hand first") from None
                log.warning("a contact record was skipped: it is incomplete or invalid")      # never what it contained
        return found

    def all(self) -> list[Contact]:
        return self._read()

    def find(self, spoken) -> Contact | None:
        name = normalise_name(spoken)
        if not name:
            return None
        for contact in self._read():
            if name in contact.names():
                return contact
        return None

    def names_text(self) -> str:
        """What {{CHIEF}} is told: who he may ring and what they may be called. Names only; no number is ever in here."""
        parts = []
        for contact in self._read():
            shown = normalise_name(contact.display)
            others = [name for name in contact.names() if name != shown]
            parts.append(contact.display + (f" ({', '.join(others)})" if others else ""))
        return "; ".join(parts)

    @staticmethod
    def masked(contact: Contact) -> str:
        """The most that is ever shown of a number: its last two digits (and nothing at all for the rehearsal contact)."""
        return "{{OWNER}}'s own number" if contact.rehearsal else "••" + contact.number[-2:]

    # -- writing -----------------------------------------------------------------------------------------------------------

    def _write(self, items: list[Contact]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(json.dumps({"contacts": [dataclasses.asdict(item) for item in items]}, indent=2) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise

    def _insert(self, contact: Contact, replacing: str | None = None) -> Contact:
        current = [item for item in self._read(strict=True) if item.key != replacing]
        if len(current) >= MAX_CONTACTS:
            raise ValueError("that is as many contacts as the book holds")
        for other in current:
            if other.key == contact.key:
                raise ValueError(f"there is already a contact with the key {contact.key}")
            clash = set(other.names()) & set(contact.names())
            if clash:
                raise ValueError(f"'{sorted(clash)[0]}' already belongs to {other.key}")
        self._write(current + [contact])
        return contact

    def add(self, key, display, address_as, number, aliases=(), hours=DEFAULT_HOURS, rehearsal=False) -> Contact:
        return self._insert(self._build(key, display, address_as, number, tuple(aliases), hours, rehearsal))

    def add_rehearsal(self, hours: str = DEFAULT_HOURS) -> Contact:
        """The test contact, 'Test Dad': {{OWNER}}'s own number, so {{OWNER}} can play the person and hear {{CHIEF}}'s whole call. Replaces itself."""
        if not self.max_number:
            raise ValueError("{{OWNER}}'s number is not set yet")
        contact = self._build(REHEARSAL_KEY, "your test dad", "Test Dad", self.max_number, ("rehearsal", "test father"), hours, True)
        return self._insert(contact, replacing=REHEARSAL_KEY)

    def update(self, key: str, display=None, address_as=None, aliases=None, hours=None) -> Contact:
        """Correct a contact's display name, greeting name, aliases (an empty list clears them) or hours; None leaves a field alone.
        The number is never touched, asked for or shown, and a rehearsal contact stays {{OWNER}}'s own number."""
        current = self._read(strict=True)
        old = next((item for item in current if item.key == key), None)
        if old is None:
            raise ValueError(f"there is no contact with the key {key}")
        new = self._build(old.key, old.display if display is None else display,
                          old.address_as if address_as is None else address_as, old.number,
                          old.aliases if aliases is None else tuple(aliases), old.hours if hours is None else hours, old.rehearsal)
        for other in current:
            clash = set(other.names()) & set(new.names())
            if other.key != key and clash:
                raise ValueError(f"'{sorted(clash)[0]}' already belongs to {other.key}")
        self._write([new if item.key == key else item for item in current])
        return new

    def remove(self, key: str) -> bool:
        current = self._read(strict=True)
        kept = [item for item in current if item.key != key]
        if len(kept) == len(current):
            return False
        self._write(kept)
        return True
