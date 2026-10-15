"""Read-only feeds for the dashboard's Agent Studio, Runway and Board (shapes: dashboard/src/telemetry/types.ts).

Everything here only reads: /proc, `systemctl show`/`list-timers`, the board's SQLite file (opened mode=ro) and the
agents' config.yaml files. Nothing is written, restarted or sent anywhere. Agent names come from hermes.json (team.py).
"""
from __future__ import annotations

import contextlib
import datetime as dt
import html
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import team

SERVICES = ["hermes-gateway", "mem0-server", "postgresql", "hermes-dash", "tailscaled"]
CLEANABLE = ["/data/.hermes/installs", "/data/.hermes/tools", "/data/backups"]
OWNER = "owner"            # the person the team works for, on the board and in hand-offs (the page shows their name)
DAY = 86_400


@dataclass
class Paths:
    hermes_home: str = "/data/.hermes"
    kanban_db: str = "/data/.hermes/kanban.db"
    gateway_url: str = "http://127.0.0.1:8642"
    proc: str = "/proc"
    root: str = "/"
    # Azure for Students starts at $100; the owner types a dated balance in Settings (there is no API for it).
    credit: dict = field(default_factory=lambda: {"balance": 100, "as_of": "", "burn_per_day": 1.2, "start": 100})
    services: list = field(default_factory=lambda: list(SERVICES))
    cleanable: list = field(default_factory=lambda: list(CLEANABLE))


def _ms(value: Any) -> int | None:
    """Seconds or milliseconds since the epoch (the board stores seconds, some rows floats) -> ms."""
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return int(v if v > 1e12 else v * 1000)


@contextlib.contextmanager
def _ro(path: str) -> Iterator[sqlite3.Connection]:
    """A read-only connection that is really closed afterwards (sqlite3's own `with` only commits)."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _get_json(url: str, timeout: float = 2.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as res:
        return json.loads(res.read() or b"null")


def _agent(profile: Any, known: set[str] | frozenset = frozenset(), hermes_home: str = "/data/.hermes") -> str | None:
    """A profile (or agent id) -> the team's agent id (default -> the chief's id); an agent added later is known by its profile id."""
    p = str(profile or "").lower()
    return team.profile_agent(team.load(hermes_home)).get(p) or (p if p in known else None)


def known_profiles(hermes_home: str) -> list[str]:
    root = Path(hermes_home) / "profiles"
    found = [d.name for d in root.iterdir() if d.is_dir() and re.match(r"^[a-z][a-z0-9]{1,23}$", d.name)] if root.is_dir() else []
    core = [p for p in team.core_profiles(hermes_home) if p != "default"]   # hermes.json's order; later agents after, by name
    return ["default", *[p for p in core if p in found], *sorted(p for p in found if p not in core)]


# -- config.yaml, without a YAML library ------------------------------------------------------------------------------------

def mcp_servers(config_text: str) -> list[dict]:
    """The `mcp_servers:` block's server names and whether each is enabled (missing `enabled` means on)."""
    out: list[dict] = []
    inside = False
    current: dict | None = None
    for line in config_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            inside = line.rstrip().startswith("mcp_servers:")
            current = None
            continue
        if not inside:
            continue
        m = re.match(r"^ {2}([A-Za-z0-9_.-]+):\s*$", line)
        if m:
            current = {"name": m.group(1), "enabled": True}
            out.append(current)
            continue
        m = re.match(r"^ {4}enabled:\s*(\S+)", line)
        if m and current is not None:
            current["enabled"] = m.group(1).strip("'\"").lower() not in ("false", "no", "off", "0")
    return out


def model_default(config_text: str) -> str | None:
    inside = False
    for line in config_text.splitlines():
        if line.startswith("model:"):
            inside = True
            continue
        if inside:
            if line and not line.startswith(" "):
                return None
            m = re.match(r"^ {2}default:\s*(\S+)", line)
            if m:
                return m.group(1).strip("'\"")
    return None


# -- E. the board -------------------------------------------------------------------------------------------------------------

def read_board_rows(paths: Paths, now: float) -> tuple[list[dict], list[dict]]:
    """Cards (everything not archived, done ones from the last 14 days) and recent handoff events."""
    if not os.path.exists(paths.kanban_db):
        return [], []
    known = set(known_profiles(paths.hermes_home))
    chief = team.chief(team.load(paths.hermes_home))["id"]

    def ag(profile: Any) -> str | None:
        return _agent(profile, known, paths.hermes_home)

    with _ro(paths.kanban_db) as db:
        tasks = db.execute(
            "SELECT id, title, status, assignee, created_by, priority, created_at, started_at, completed_at FROM tasks "
            "WHERE status != 'archived' AND (status != 'done' OR completed_at > ?) ORDER BY created_at DESC LIMIT 200",
            (now - 14 * DAY,)).fetchall()
        ids = [t["id"] for t in tasks]
        summaries: dict[str, str] = {}
        parents: dict[str, list[str]] = {}
        comments: dict[str, list[dict]] = {}
        if ids:
            marks = ",".join("?" for _ in ids)
            for r in db.execute(f"SELECT task_id, summary FROM task_runs WHERE task_id IN ({marks}) AND summary IS NOT NULL "
                                f"AND summary != '' ORDER BY id", ids):
                summaries[r["task_id"]] = r["summary"]
            for r in db.execute(f"SELECT parent_id, child_id FROM task_links WHERE child_id IN ({marks})", ids):
                parents.setdefault(r["child_id"], []).append(r["parent_id"])
            open_ids = [t["id"] for t in tasks if t["status"] != "done"]
            if open_ids:
                om = ",".join("?" for _ in open_ids)
                for r in db.execute(f"SELECT task_id, author, body, created_at FROM task_comments WHERE task_id IN ({om}) "
                                    f"ORDER BY id DESC", open_ids):
                    lst = comments.setdefault(r["task_id"], [])
                    if len(lst) < 4:   # the question a blocked card is waiting on is usually the last one
                        lst.insert(0, {"author": OWNER if str(r["author"]).lower() == "user" else ag(r["author"]) or str(r["author"]),
                                       "body": html.unescape(str(r["body"] or ""))[:600], "at": _ms(r["created_at"]) or 0})
        events = db.execute(
            "SELECT e.kind, e.created_at, e.payload, t.id, t.title, t.assignee, t.created_by FROM task_events e JOIN tasks t ON t.id = e.task_id "
            "WHERE e.kind IN ('created', 'blocked', 'completed', 'commented') AND e.created_at > ? ORDER BY e.created_at DESC LIMIT 60",
            (now - 7 * DAY,)).fetchall()

    cards = []
    for t in tasks:
        creator = str(t["created_by"] or "").lower()
        summary = summaries.get(t["id"])
        cards.append({
            "id": t["id"],
            "title": html.unescape(str(t["title"] or ""))[:300],   # the board stores some titles HTML-escaped
            "status": t["status"],
            "assignee": ag(t["assignee"]),
            "assigneeProfile": None if ag(t["assignee"]) else (t["assignee"] or None),
            "createdBy": OWNER if creator == "user" else "helper" if creator == "worker" else ag(creator),
            "priority": int(t["priority"] or 0),
            "createdAt": _ms(t["created_at"]) or 0,
            "startedAt": _ms(t["started_at"]),
            "completedAt": _ms(t["completed_at"]),
            "parents": parents.get(t["id"], []),
            "summary": html.unescape(summary)[:600] if summary else None,
            "comments": comments.get(t["id"], []),
        })

    handoffs = []
    for e in events:
        worker = ag(e["assignee"])
        if not worker:
            continue
        creator = str(e["created_by"] or "").lower()
        boss = OWNER if creator == "user" else ag(creator) or chief
        base = {"at": _ms(e["created_at"]) or 0, "title": html.unescape(str(e["title"] or ""))[:200], "cardId": e["id"]}
        # questions and results go back to whoever handed the card down (a team lead, the chief or the owner)
        back = boss if boss != worker else chief
        if e["kind"] == "created" and boss != worker:
            handoffs.append({**base, "from": boss, "to": worker, "kind": "assign"})
        elif e["kind"] == "blocked" and back != worker:
            handoffs.append({**base, "from": worker, "to": back, "kind": "question"})
        elif e["kind"] == "completed" and back != worker:
            handoffs.append({**base, "from": worker, "to": back, "kind": "done"})
        elif e["kind"] == "commented" and back != worker:
            # a comment is a message on the card: from its author to the other side of the hand-off
            try:
                author = str((json.loads(e["payload"] or "{}") or {}).get("author") or "").lower()
            except (ValueError, AttributeError):
                author = ""
            who = OWNER if author == "user" else ag(author)
            if who == worker:
                handoffs.append({**base, "from": worker, "to": back, "kind": "message"})
            elif who:
                handoffs.append({**base, "from": who, "to": worker, "kind": "message"})
    return cards, handoffs[:30]


def talks(cards: list[dict], chief: str) -> list[dict]:
    """Who is working with whom right now, for the Agent Studio lines: a card being worked on is its lead and the worker in
    conversation (the lead waits on the result); a blocked card is the worker waiting on an answer from whoever handed it down."""
    out = []
    for c in cards:
        worker = c["assignee"]
        boss = c["createdBy"] if c["createdBy"] not in (None, "helper") else chief
        if not worker or boss == worker:
            continue
        if c["status"] == "running":
            out.append({"from": boss, "to": worker, "state": "working", "title": c["title"], "cardId": c["id"], "since": c["startedAt"] or c["createdAt"]})
        elif c["status"] == "blocked":
            out.append({"from": worker, "to": boss, "state": "asking", "title": c["title"], "cardId": c["id"], "since": c["startedAt"] or c["createdAt"]})
    return out[:24]


def board(paths: Paths, now: float | None = None) -> dict:
    now = now or time.time()
    cards, _ = read_board_rows(paths, now)
    return {"at": int(now * 1000), "cards": cards}


# -- B. agents ----------------------------------------------------------------------------------------------------------------

RUN_PILLS = 24
BOARD_STATUS = {"done": "ok", "blocked": "waiting", "review": "waiting", "running": "running", "crashed": "error",
                "timed_out": "error", "failed": "error", "spawn_failed": "error"}
CRON_STATUS = {"completed": "ok", "failed": "error", "running": "running", "claimed": "running"}


def _iso_ms(v: Any) -> int | None:
    if not isinstance(v, str) or not v:
        return None
    try:
        when = dt.datetime.fromisoformat(v)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return int(when.timestamp() * 1000)


def agent_runs(paths: Paths, profile: str, now: float) -> dict:
    """The agent's recent AI runs, oldest first, for its heatmap strip: board cards it worked (task_runs) and its cron jobs
    (cron/executions.db; watchdog scripts that run without the AI are left out). Each run:
    status ok | waiting | error | running, trigger, title, length, time. Reliability = ok / (ok + error), last 30 days."""
    home = Path(paths.hermes_home)
    runs: list[dict] = []
    try:
        with _ro(paths.kanban_db) as db:
            for r in db.execute("SELECT r.status, r.started_at, r.ended_at, r.error, t.title FROM task_runs r "
                                "LEFT JOIN tasks t ON t.id = r.task_id WHERE r.profile = ? ORDER BY r.id DESC LIMIT 200", (profile,)):
                st = BOARD_STATUS.get(r["status"])
                if st:
                    start, end = _ms(r["started_at"]), _ms(r["ended_at"])
                    runs.append({"status": st, "trigger": "board", "title": html.unescape(str(r["title"] or "a card"))[:120],
                                 "at": start, "secs": (end - start) // 1000 if start and end else None})
    except (sqlite3.Error, OSError):
        pass
    cron_dir = home / "cron" if profile == "default" else home / "profiles" / profile / "cron"
    try:
        jobs = {str(j.get("id")): j for j in json.loads((cron_dir / "jobs.json").read_text()).get("jobs", []) if isinstance(j, dict)}
    except (OSError, ValueError):
        jobs = {}
    if (cron_dir / "executions.db").exists():
        try:
            with _ro(str(cron_dir / "executions.db")) as db:
                for r in db.execute("SELECT job_id, status, started_at, finished_at, error FROM executions "
                                    "ORDER BY COALESCE(started_at, claimed_at) DESC LIMIT 400"):
                    job = jobs.get(str(r["job_id"]))
                    if job is not None and job.get("no_agent"):
                        continue                                    # a watchdog script, not the agent at work
                    st = CRON_STATUS.get(r["status"])
                    if not st:
                        continue
                    start, end = _iso_ms(r["started_at"]), _iso_ms(r["finished_at"])
                    runs.append({"status": st, "trigger": "cron", "title": str((job or {}).get("name") or "a scheduled job")[:120],
                                 "at": start, "secs": (end - start) // 1000 if start and end else None})
        except (sqlite3.Error, OSError):
            pass
    runs = [r for r in runs if r["at"]]
    runs.sort(key=lambda r: r["at"])
    month = (now - 30 * DAY) * 1000
    recent = [r for r in runs if r["at"] >= month]
    ok = sum(r["status"] == "ok" for r in recent)
    bad = sum(r["status"] == "error" for r in recent)
    return {"runs": runs[-RUN_PILLS:], "reliability": {"ok": ok, "errors": bad, "total": len(recent),
                                                        "pct": round(100 * ok / (ok + bad), 1) if ok + bad else None}}

def agents(paths: Paths, now: float | None = None) -> dict:
    now = now or time.time()
    cards, handoffs = read_board_rows(paths, now)
    try:
        h = _get_json(f"{paths.gateway_url}/health")
        gateway = {"ok": isinstance(h, dict) and h.get("status") == "ok", "version": (h or {}).get("version")}
    except Exception:  # noqa: BLE001 - down is an answer
        gateway = {"ok": False, "version": None}
    import actions  # profile.yaml reading and the org live with the writes
    week = (now - 7 * DAY) * 1000
    out = []
    profiles = known_profiles(paths.hermes_home)
    org = actions.load_org(actions.Env(hermes_home=paths.hermes_home, state_dir=str(Path(paths.hermes_home) / "hermes-dash")))
    c = team.load(paths.hermes_home)
    to_agent = team.profile_agent(c)
    core = set(team.core_profiles(paths.hermes_home))
    for profile in profiles:
        agent = to_agent.get(profile) or profile
        cfg = Path(paths.hermes_home) / ("config.yaml" if profile == "default" else f"profiles/{profile}/config.yaml")
        try:
            text = cfg.read_text()
        except OSError:
            text = ""
        meta = actions.profile_meta(actions.Env(hermes_home=paths.hermes_home), profile)
        effort = re.search(r"(?m)^agent:\s*\n(?:(?:  .*|\s*)\n)*?  reasoning_effort:\s*(\S+)", text)
        mine = [c for c in cards if c["assignee"] == agent]
        last = max([c["completedAt"] or c["startedAt"] or 0 for c in mine] or [0])
        out.append({
            "id": agent, "profile": profile, "name": meta.get("display_name") or team.name_of(paths.hermes_home, profile),
            "description": meta.get("description", "")[:600], "core": profile in core,
            "reportsTo": (lambda b: None if b is None else to_agent.get(b) or b)(actions.manager_of(org, profiles, profile)),
            "model": model_default(text), "effort": effort.group(1).strip("'\"") if effort else None, "mcp": mcp_servers(text),
            "running": sum(c["status"] == "running" for c in mine),
            "queued": sum(c["status"] in ("triage", "todo", "ready", "scheduled") for c in mine),
            "blocked": sum(c["status"] in ("blocked", "review") for c in mine),
            "done7d": sum(c["status"] == "done" and (c["completedAt"] or 0) > week for c in mine),
            "lastActive": last or None,
            **agent_runs(paths, profile, now),
        })
    return {"at": int(now * 1000), "gateway": gateway, "agents": out, "handoffs": handoffs, "talks": talks(cards, team.chief(c)["id"])}


# -- C. infra -----------------------------------------------------------------------------------------------------------------

class Cpu:
    """CPU use between two looks at /proc/stat (the first look samples 0.2 s)."""

    def __init__(self) -> None:
        self.last: tuple[int, int] | None = None
        self.lock = threading.Lock()

    @staticmethod
    def _read(proc: str) -> tuple[int, int]:
        with open(f"{proc}/stat") as f:
            parts = [int(x) for x in f.readline().split()[1:]]
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
        return sum(parts), idle

    def percent(self, proc: str) -> float:
        with self.lock:
            if self.last is None:
                self.last = self._read(proc)
                time.sleep(0.2)
            total, idle = self._read(proc)
            dt, di = total - self.last[0], idle - self.last[1]
            self.last = (total, idle)
        return round(100.0 * (1 - di / dt), 1) if dt > 0 else 0.0


_cpu = Cpu()
_du_cache: dict[str, tuple[float, int | None]] = {}


def _du(path: str, now: float) -> int | None:
    hit = _du_cache.get(path)
    if hit and now - hit[0] < 3600:
        return hit[1]
    try:
        res = subprocess.run(["du", "-sb", path], capture_output=True, text=True, timeout=30)
        # du exits 1 when one subfolder is unreadable but still prints the total of what it could read.
        size = int(res.stdout.split()[0]) if res.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        size = None
    _du_cache[path] = (now, size)
    return size


def _systemctl(*args: str) -> str:
    try:
        return subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def parse_show(text: str) -> list[dict[str, str]]:
    blocks, cur = [], {}
    for line in text.splitlines():
        if not line.strip():
            if cur:
                blocks.append(cur)
                cur = {}
            continue
        k, _, v = line.partition("=")
        cur[k] = v
    if cur:
        blocks.append(cur)
    return blocks


def _unix(v: str | None) -> int | None:
    return int(v[1:]) * 1000 if v and v.startswith("@") and v[1:].isdigit() else None


def unit_states(units: list[str]) -> dict[str, str]:
    """unit -> ActiveState, for a few units at once (no -p ...MemoryCurrent: cheap enough for every request)."""
    if not units:
        return {}
    return {b.get("Id", "").rsplit(".", 1)[0]: b.get("ActiveState", "unknown")
            for b in parse_show(_systemctl("show", *[u if "." in u else f"{u}.service" for u in units], "-p", "Id,ActiveState"))}


def timers(units: list[str]) -> dict[str, dict]:
    """unit -> {nextAt, lastAt} from systemctl list-timers (times in microseconds)."""
    if not units:
        return {}
    try:
        rows = json.loads(_systemctl("list-timers", *[f"{u}.timer" for u in units], "--all", "--output=json") or "[]")
    except ValueError:
        return {}
    out = {}
    for r in rows if isinstance(rows, list) else []:
        u = str(r.get("unit", "")).removesuffix(".timer")
        out[u] = {"nextAt": int(r["next"] / 1000) if isinstance(r.get("next"), (int, float)) and r["next"] > 0 else None,
                  "lastAt": int(r["last"] / 1000) if isinstance(r.get("last"), (int, float)) and r["last"] > 0 else None}
    return out


def infra(paths: Paths, now: float | None = None, service_rows: list[dict] | None = None) -> dict:
    """service_rows: the registry's services plus any installed one it does not describe (registry.service_list)."""
    now = now or time.time()
    mem = {}
    with open(f"{paths.proc}/meminfo") as f:
        for line in f:
            k, _, v = line.partition(":")
            mem[k] = int(v.split()[0]) * 1024
    st = os.statvfs(paths.root)
    with open(f"{paths.proc}/loadavg") as f:
        load = [float(x) for x in f.read().split()[:3]]
    with open(f"{paths.proc}/uptime") as f:
        uptime = float(f.read().split()[0])

    rows = {r["unit"]: r for r in service_rows or []}
    names = list(rows) or list(paths.services)
    units = [f"{u}.service" for u in names]
    shown = {b.get("Id", "").removesuffix(".service"): b for b in parse_show(
        _systemctl("show", *units, "-p", "Id,ActiveState,ActiveEnterTimestamp,MemoryCurrent", "--timestamp=unix"))}
    services = []
    for u in names:
        b = shown.get(u, {})
        state = b.get("ActiveState", "unknown")
        mem_now = b.get("MemoryCurrent", "")
        services.append({"unit": u, "state": state if state in ("active", "inactive", "failed", "activating") else "unknown",
                         "since": _unix(b.get("ActiveEnterTimestamp")) if state == "active" else None,
                         "memBytes": int(mem_now) if mem_now.isdigit() else None,
                         "label": (rows.get(u) or {}).get("label") or "", "port": (rows.get(u) or {}).get("port"),
                         "described": (rows.get(u) or {}).get("described", True)})

    svc = (parse_show(_systemctl("show", "hermes-backup.service", "-p", "Result,ExecMainExitTimestamp", "--timestamp=unix")) or [{}])[0]
    try:
        timer = (json.loads(_systemctl("list-timers", "hermes-backup.timer", "--all", "--output=json") or "[]") or [{}])[0]
    except ValueError:
        timer = {}
    last_run = _unix(svc.get("ExecMainExitTimestamp"))
    nxt = timer.get("next")
    credit = paths.credit
    return {
        "at": int(now * 1000),
        "vm": {"cpuPct": _cpu.percent(paths.proc), "memUsed": mem.get("MemTotal", 0) - mem.get("MemAvailable", 0),
               "memTotal": mem.get("MemTotal", 0), "diskUsed": (st.f_blocks - st.f_bfree) * st.f_frsize,
               "diskTotal": st.f_blocks * st.f_frsize, "load": load, "uptimeSecs": int(uptime)},
        "services": services,
        "backup": {"lastRunAt": last_run, "ok": None if last_run is None else svc.get("Result") == "success",
                   "nextRunAt": int(nxt / 1000) if isinstance(nxt, (int, float)) and nxt > 0 else None},
        "credit": {"balance": float(credit.get("balance", 0)), "asOf": str(credit.get("as_of", "")),
                   "burnPerDay": float(credit.get("burn_per_day", 1)), "start": float(credit.get("start", 100))},
        "cleanable": [{"path": p, "bytes": _du(p, now)} for p in paths.cleanable],
    }


def backup_state() -> dict:
    """The nightly backup unit's last result and when it ended (for the Integrations Hub's Drive card)."""
    svc = (parse_show(_systemctl("show", "hermes-backup.service", "-p", "Result,ExecMainExitTimestamp", "--timestamp=unix")) or [{}])[0]
    return {"result": svc.get("Result") or None, "lastRunAt": _unix(svc.get("ExecMainExitTimestamp"))}
