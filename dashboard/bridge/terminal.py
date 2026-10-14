"""Agent Studio's terminal window: what one agent is doing on the VM, step by step, as it happens.

Hermes writes every step of a run to the agent's own session database (`state.db`: the chief's in /data/.hermes, the others' in profiles/<name>/) as it goes: the
message it was given, each tool call (a terminal command, a file it opened, a board action), the tool's answer and its replies. This module only READS that
file (sqlite `mode=ro`: no lock that could slow an agent down, nothing written) and turns a run into lines for a terminal: `$ command` with the first lines of
its output, `open file`, `board: complete`, the agent's words. Anything shaped like a key, token, password or phone number is blanked before it leaves.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import feeds

OUTPUT_LINES = 14
OUTPUT_CHARS = 1600
TEXT_CHARS = 1800
MAX_STEPS = 400
LIVE_SECONDS = 90

# Secrets: blanked wherever they appear (commands, outputs, messages). A name stays readable (TOKEN=••••••), the value never.
NAMED = re.compile(r"\b([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|HASH|SESSION|SESSION_STRING|COOKIE|CREDENTIALS?)[A-Z0-9_]*)(\s*[=:]\s*['\"]?)[^\s'\",}]{4,}")
JSON_KEY = re.compile(r'(?i)("[a-z_]*(?:api_?key|token|secret|password|passwd|session_string|cookie|authorization)[a-z_]*"\s*:\s*")[^"]{4,}"')
AUTH = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}")
PLAIN = [
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\b[MN][A-Za-z\d]{23,25}\.[\w-]{6}\.[\w-]{27,}"),                # Discord bot tokens
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),                                  # Telegram bot tokens
    re.compile(r"[A-Za-z0-9+/_-]{120,}={0,2}"),                                       # long opaque blobs (session strings, keys)
]
PHONE = re.compile(r"(?<![\w.:/-])(?:\+|00)\d[\d \-]{8,16}\d(?![\w.])|(?<![\w.:/-])0\d{3}[ -]?\d{3}[ -]?\d{3,4}(?![\w.])")
MASK = "••••••"


def redact(text: str) -> str:
    if not text:
        return text
    out = NAMED.sub(lambda m: m.group(1) + m.group(2) + MASK, text)
    out = JSON_KEY.sub(lambda m: m.group(1) + MASK + '"', out)
    out = AUTH.sub(lambda m: m.group(1) + " " + MASK, out)
    for rx in PLAIN:
        out = rx.sub(MASK, out)
    return PHONE.sub(lambda m: "•••• " + re.sub(r"\D", "", m.group(0))[-3:], out)


def db_path(hermes_home: str, profile: str) -> Path:
    return Path(hermes_home) / ("state.db" if profile == "default" else f"profiles/{profile}/state.db")


def _short(text: str, lines: int = OUTPUT_LINES, chars: int = OUTPUT_CHARS) -> tuple[str, bool]:
    text = (text or "").replace("\r", "")
    cut = "\n".join(text.split("\n")[:lines])
    cut = cut[:chars]
    return cut, len(cut) < len(text.rstrip())


def _args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw or "{}")
        return val if isinstance(val, dict) else {}
    except (TypeError, ValueError):
        return {}


def _call_line(name: str, args: dict) -> dict:
    """One tool call -> a terminal line: a command, a file, a board action or a named tool."""
    if name == "terminal":
        return {"kind": "cmd", "text": str(args.get("command") or "").strip()}
    if name in ("read_file", "view_file", "search_files", "list_directory"):
        return {"kind": "read", "text": str(args.get("path") or args.get("pattern") or args.get("query") or "")}
    if name in ("write_file", "patch", "edit_file", "create_file"):
        return {"kind": "write", "text": str(args.get("path") or "")}
    if name.startswith("kanban_"):
        brief = args.get("task_id") or args.get("title") or (str(args.get("summary"))[:160] if args.get("summary") else "") or args.get("assignee") or ""
        return {"kind": "board", "text": f"{name.removeprefix('kanban_')} {brief}".strip()}
    shown = {k: v for k, v in args.items() if not isinstance(v, (dict, list)) or len(json.dumps(v)) < 120}
    return {"kind": "tool", "text": f"{name} {json.dumps(shown, ensure_ascii=False)[:240] if shown else ''}".strip()}


def _result(content: str) -> tuple[str, int | None]:
    """A tool's answer -> (what to print, exit code if it had one). Terminal answers are JSON with output and exit_code."""
    data = None
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        pass
    if isinstance(data, dict):
        if "output" in data:
            code = data.get("exit_code", data.get("returncode"))
            return str(data.get("output") or ""), code if isinstance(code, int) else None
        if "content" in data and isinstance(data["content"], str):
            return data["content"], None
        if "error" in data:
            return f"error: {data['error']}", None
        return json.dumps(data, ensure_ascii=False), None
    return str(content or ""), None


def steps_of(conn: sqlite3.Connection, session_id: str, after: int = 0) -> list[dict]:
    rows = conn.execute("SELECT id, role, content, tool_call_id, tool_calls, tool_name, timestamp FROM messages WHERE session_id = ? AND id > ? ORDER BY id LIMIT ?",
                        (session_id, after, MAX_STEPS)).fetchall()
    out: list[dict] = []
    for r in rows:
        at = int(float(r["timestamp"] or 0) * 1000)
        role = r["role"]
        if role == "user":
            text, cut = _short(redact(str(r["content"] or "")), 30, TEXT_CHARS)
            out.append({"id": r["id"], "at": at, "kind": "in", "text": text, "more": cut})
        elif role == "assistant":
            calls = []
            try:
                calls = json.loads(r["tool_calls"] or "[]") or []
            except ValueError:
                calls = []
            said = str(r["content"] or "").strip()
            if said:
                text, cut = _short(redact(said), 40, TEXT_CHARS)
                out.append({"id": r["id"], "at": at, "kind": "say", "text": text, "more": cut})
            for c in calls if isinstance(calls, list) else []:
                fn = (c or {}).get("function") or {}
                line = _call_line(str(fn.get("name") or "tool"), _args(fn.get("arguments")))
                line["text"] = redact(line["text"])[:600]
                out.append({"id": r["id"], "at": at, "callId": (c or {}).get("id"), **line})
        elif role == "tool":
            body, code = _result(str(r["content"] or ""))
            text, cut = _short(redact(body))
            out.append({"id": r["id"], "at": at, "kind": "out", "callId": r["tool_call_id"], "tool": r["tool_name"], "text": text, "more": cut, "exit": code})
    return out


def sessions_of(conn: sqlite3.Connection, limit: int = 12) -> list[dict]:
    rows = conn.execute("SELECT id, source, title, model, started_at, ended_at, end_reason, message_count, tool_call_count, last_activity_at FROM sessions "
                        "WHERE COALESCE(hidden, 0) = 0 ORDER BY COALESCE(last_activity_at, started_at) DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        last = conn.execute("SELECT MAX(timestamp), COUNT(*) FROM messages WHERE session_id = ?", (r["id"],)).fetchone()
        out.append({"id": r["id"], "source": r["source"], "title": redact(str(r["title"] or ""))[:120] or None, "model": r["model"],
                    "startedAt": int(float(r["started_at"] or 0) * 1000), "endedAt": int(float(r["ended_at"]) * 1000) if r["ended_at"] else None,
                    "lastAt": int(float(last[0]) * 1000) if last and last[0] else None, "steps": int(last[1] or 0) if last else 0,
                    "tools": int(r["tool_call_count"] or 0)})
    return out


def running_card(paths: feeds.Paths, profile: str) -> dict | None:
    """The board card this agent is working on right now, if any."""
    try:
        with feeds._ro(paths.kanban_db) as db:
            r = db.execute("SELECT id, title, started_at FROM tasks WHERE assignee = ? AND status = 'running' ORDER BY started_at DESC LIMIT 1", (profile,)).fetchone()
    except sqlite3.Error:
        return None
    return {"id": r["id"], "title": redact(str(r["title"] or ""))[:200], "startedAt": feeds._ms(r["started_at"])} if r else None


def view(paths: feeds.Paths, profile: str, session: str | None = None, after: int = 0, now: float | None = None) -> dict:
    now = now or time.time()
    path = db_path(paths.hermes_home, profile)
    card = running_card(paths, profile)
    if not path.exists():
        return {"profile": profile, "sessions": [], "session": None, "steps": [], "live": False, "card": card, "cursor": 0}
    with feeds._ro(str(path)) as conn:
        sessions = sessions_of(conn)
        pick = next((s for s in sessions if s["id"] == session), None) if session else (sessions[0] if sessions else None)
        if session and pick is None:
            row = conn.execute("SELECT id FROM sessions WHERE id = ?", (session,)).fetchone()
            pick = {"id": row["id"]} if row else None
        steps = steps_of(conn, pick["id"], after) if pick else []
    last_at = (pick or {}).get("lastAt") or 0
    live = bool(pick) and (pick is (sessions[0] if sessions else None)) and (now * 1000 - last_at < LIVE_SECONDS * 1000 or bool(card))
    return {"profile": profile, "sessions": sessions, "session": pick, "steps": steps, "live": live, "card": card,
            "cursor": max([s["id"] for s in steps], default=after)}
