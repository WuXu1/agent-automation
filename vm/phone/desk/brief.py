"""The brief: what {{CHIEF}} already knows when the phone rings, kept warm in the background.

Sources (all read-only): a calendar tool when the server has one (about 8 s to fetch, so refreshed in the background), the Moodle
deadlines (the Moodle tool, when the Moodle add-on is on), the task list, the task board, the last Telegram messages with
{{OWNER}}, and the desk's own pending tickets and minutes. A source the server does not have is simply left out. Every section
carries its age, and {{CHIEF}} is told when something is stale so he says so.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import logging
import os
import re
import sqlite3
import subprocess
import threading
from pathlib import Path

from . import config as desk_config
from .config import DISPLAY
from .util import age_words, clip, scrub, uk_time

log = logging.getLogger("desk.brief")
MAX_CHARS = 6000
STALE_SECS = {"calendar": 20 * 60, "deadlines": 36 * 3600, "tasks": 7 * 24 * 3600, "board": 15 * 60, "chat": 15 * 60}
DAY_RE = re.compile(r"^(\w{3} \d{2} \w{3})\s*(.*)$")
ROUTINE_RE = re.compile(r"^[\d:-]*:?\s*(snack|meal \d|stretch program|morning priming|rise & hydrate)", re.I)
BOARD_RE = re.compile(r"^\s*(\S+)\s+(t_[0-9a-f]{6,})\s+(\w+)\s+(\S+)\s+(.+?)\s*$")


def run_cmd(cmd: list[str], timeout: float = 25, env: dict | None = None) -> str:
    """stdout of a command, or "" when it fails or takes too long."""
    try:
        done = subprocess.run(cmd, cwd="/", capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, **(env or {})})
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def parse_moodle_due(text: str, limit: int = 14) -> str:
    """The Moodle tool's `due --json` -> 'Tue 20 Oct 16:30  COMPSCI2024 - Assessed Exercise 1', soonest first; "" when unreadable."""
    try:
        rows = json.loads(text).get("due") or []
    except (ValueError, AttributeError):
        return ""
    lines = []
    for row in sorted((r for r in rows if isinstance(r, dict) and r.get("due_at")), key=lambda r: r["due_at"])[:limit]:
        lines.append(f"{uk_time(row['due_at']).strftime('%a %d %b %H:%M')}  {html.unescape(str(row.get('name') or '')).strip()}")
    return "\n".join(lines)


def by_day(items: list[str], routine: bool = False) -> dict[str, list[str]]:
    """{'Thu 08 Oct': ['10:00-11:00: Operations Management', ...]}; meals, snacks and stretches dropped by default."""
    days: dict[str, list[str]] = {}
    for item in items:
        match = DAY_RE.match(item)
        if not match:
            continue
        day, rest = match.groups()
        if not routine and ROUTINE_RE.match(rest):
            continue
        rest = re.sub(r"\s+\b[A-Z]{2}\d{2}\b", "", rest)            # timetable codes such as LC01
        rest = re.sub(r"(@ [^:;]+):\S[^;]*$", r"\1", rest)            # the room after the building
        days.setdefault(day, []).append(rest)
    return days


def parse_calendar(out: str) -> list[str]:
    """icloud_cal agenda lines -> 'Thu 08 Oct 12:00-17:00 Work (Waterstones)'."""
    items: list[str] = []
    for line in out.splitlines():
        if line.startswith("- "):
            items.append(re.sub(r"\s*\[[^\]]+\]\s*$", "", line[2:]).strip())
        elif items and line.strip() and line.startswith((" ", "\t")):
            extra = re.sub(r"^(?:@|location:|where:)\s*", "", line.strip(), flags=re.I)
            if extra and len(items[-1]) < 140:
                items[-1] += f" ({extra[:50]})"
    return items


def parse_tasks(text: str) -> list[str]:
    return [line[6:].split(" | ")[0].strip()[:110] for line in text.splitlines() if line.startswith("- [ ]")]


def parse_board(out: str, done_limit: int = 4) -> list[str]:
    """`hermes kanban list` -> one line per live card (anything not done) plus the first few finished ones."""
    live, done = [], []
    for line in out.splitlines():
        match = BOARD_RE.match(line)
        if not match:
            continue
        _, _, status, assignee, title = match.groups()
        entry = f"{DISPLAY.get(assignee, assignee)}: {status}: {clip(title, 70)}"
        if status in ("done", "archived"):
            done.append(entry)
        else:
            live.append(entry)
    return live + done[:done_limit]


def recent_chat(db_path: str, chat_id: str, limit: int = 6) -> list[str]:
    """The last few messages in {{OWNER}}'s main Telegram chat, oldest first (read-only database access)."""
    if not chat_id:
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        rows = conn.execute(
            "select m.role, m.content from messages m join sessions s on s.id = m.session_id "
            "where s.chat_id = ? and m.role in ('user','assistant') and m.content is not null "
            "and length(trim(m.content)) > 0 order by m.timestamp desc limit ?", (chat_id, limit)).fetchall()
        conn.close()
    except sqlite3.Error:
        return []
    out = []
    for role, content in reversed(rows):
        text = re.sub(r"\s+", " ", str(content)).strip()
        if len(text) >= 3 and not text.startswith("[kanban]"):
            out.append(f"{'{{OWNER}}' if role == 'user' else '{{CHIEF}}'}: {scrub(text)[:160]}")
    return out


def _mtime_age(path: Path, now: float) -> float | None:
    try:
        return now - path.stat().st_mtime
    except OSError:
        return None


class Brief:
    def __init__(self, cfg, clock, run=run_cmd, tickets=None, minutes_text=None):
        self.cfg, self.clock, self.run = cfg, clock, run
        self.tickets, self.minutes_text = tickets, minutes_text
        self.owner_dir = Path(cfg.hermes_home) / "owner"
        self.data: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _set(self, name: str, value, age_from_file: Path | None = None) -> None:
        with self._lock:
            self.data[name] = {"value": value, "at": self.clock.time(), "file": age_from_file}

    # -- refreshing -------------------------------------------------------------------------------
    def refresh_calendar(self) -> None:
        items = parse_calendar(self.run([self.cfg.icloud_python, self.cfg.icloud_tool, "agenda", "--days", "10"], 40))
        if items:
            self._set("calendar", items)

    def refresh_deadlines(self) -> None:
        """Moodle deadlines for the next 30 days, from the Moodle tool with the cookie the tutor uses (read fresh each time, so a
        renewed cookie is picked up without a restart). Nothing is recorded when the add-on is off or the session has ended."""
        cfg = self.cfg
        token = desk_config.read_env_file(cfg.moodle_env).get("MOODLE_TOKEN", "") if cfg.moodle_env else ""
        if not (cfg.moodle_cli and cfg.moodle_url and token and os.path.exists(cfg.moodle_cli)):
            return
        out = self.run([cfg.moodle_cli, "due", "--days", "30", "--json"], 40,
                       env={"MOODLE_TOKEN": token, "MOODLE_BASE_URL": cfg.moodle_url, "MOODLE_NO_UPDATE_CHECK": "1",
                            "HOME": str(Path(cfg.hermes_home).parent)})
        text = parse_moodle_due(out)
        if text:
            self._set("deadlines", text[:900])

    def refresh_fast(self) -> None:
        self.refresh_deadlines()
        try:
            tasks = parse_tasks((self.owner_dir / "tasks.md").read_text())
        except OSError:
            tasks = []
        self._set("tasks", tasks, self.owner_dir / "tasks.md")
        board = self.run([self.cfg.hermes_bin, "kanban", "list"], 20, env={"HERMES_HOME": self.cfg.hermes_home})
        self._set("board", parse_board(board))
        self._set("chat", recent_chat(str(Path(self.cfg.hermes_home) / "state.db"), self.cfg.telegram_chat_id))

    def refresh_all(self) -> None:
        for step in (self.refresh_fast, self.refresh_calendar):
            try:
                step()
            except Exception as exc:  # noqa: BLE001 - the refresher must never die
                log.warning("brief refresh step failed: %s", type(exc).__name__)

    def start(self) -> None:
        if self._thread:
            return

        def loop():
            while not self._stop.is_set():
                self.refresh_all()
                self._stop.wait(self.cfg.brief_every_secs)
        self._thread = threading.Thread(target=loop, daemon=True, name="brief")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # -- rendering --------------------------------------------------------------------------------
    def age(self, name: str) -> float | None:
        entry = self.data.get(name)
        if not entry:
            return None
        if entry["file"] is not None:
            return _mtime_age(entry["file"], self.clock.time())
        return self.clock.time() - entry["at"]

    def ages(self) -> dict[str, float | None]:
        """Seconds since each section was last refreshed, None if it never loaded. Names and numbers only: safe to show."""
        return {name: self.age(name) for name in STALE_SECS}

    def _stamp(self, name: str) -> str:
        age = self.age(name)
        stale = age is None or age > STALE_SECS[name]
        return f"updated {age_words(age)}" + (", STALE - say so if you rely on it" if stale else "")

    def render(self) -> str:
        now = self.clock.time()
        blocks: list[tuple[int, str]] = []          # (priority, text), in reading order
        local = uk_time(now)
        blocks.append((0, f"Now: {local.strftime('%A %d %B %Y, %H:%M')} (UK)."))
        calendar = (self.data.get("calendar") or {}).get("value")
        if calendar:
            days = by_day(calendar)
            blocks.append((3, f"CALENDAR, next 10 days, meals and stretches left out ({self._stamp('calendar')}):\n"
                              + "\n".join(f"{d}: " + "; ".join(v) for d, v in days.items())))
        else:
            blocks.append((3, "CALENDAR: not loaded yet - ask {{ASSISTANT}}, or say you cannot see it."))
        tasks = (self.data.get("tasks") or {}).get("value")
        if tasks:
            blocks.append((4, f"OPEN TASKS from his task list ({self._stamp('tasks')}):\n" + "\n".join(f"- {t}" for t in tasks[:12])))
        deadlines = (self.data.get("deadlines") or {}).get("value")
        if deadlines:
            blocks.append((5, f"MOODLE DEADLINES, next 30 days ({self._stamp('deadlines')}):\n{deadlines}"))
        board = (self.data.get("board") or {}).get("value")
        if board:
            blocks.append((1, f"THE TASK BOARD ({self._stamp('board')}):\n" + "\n".join(f"- {b}" for b in board)))
        pending = self.tickets.pending_lines() if self.tickets else ""
        if pending:
            blocks.append((0, "ASKED ON EARLIER CALLS, NOT PASSED ON YET:\n" + pending))
        minutes = self.minutes_text() if self.minutes_text else ""
        if minutes:
            blocks.append((0, minutes))
        chat = (self.data.get("chat") or {}).get("value")
        if chat:
            blocks.append((6, "MOST RECENT TELEGRAM CHAT (oldest first):\n" + "\n".join(chat)))
        # Keep the most important blocks when the brief has to fit: lowest priority number first.
        keep, used = set(), 0
        for index, (priority, text) in sorted(enumerate(blocks), key=lambda item: item[1][0]):
            if used + len(text) + 2 <= MAX_CHARS:
                keep.add(index)
                used += len(text) + 2
        return scrub("\n\n".join(text for index, (_, text) in enumerate(blocks) if index in keep))[:MAX_CHARS]
