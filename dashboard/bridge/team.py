"""Who this install is for: the owner, the four agents and the switched-on add-ons, read from `<hermes home>/hermes.json`.

The kit's installer writes hermes.json (readable by user hermes); its add-on commands switch features on later. Nothing in
the bridge hard-codes a name: every agent name, the owner's name and the Mem0 user come from here. The file is re-read
whenever it changes on disk (a stat per call), so switching an add-on on needs no restart.

    {"version": 1,
     "owner": {"name": "Sam", "id": "sam", "pronouns": "they/them", "tailscale_login": "sam@example.com"},
     "timezone": "Europe/London",
     "agents": [{"id": "atlas", "profile": "default", "role": "chief", "name": "Atlas", "title": "Chief of Staff"}, ...],
     "features": {"voice": false, "gmail": false, "moodle": false, "icloud": false, "backup": false}}

A missing or broken file falls back to a plain team (Chief of Staff, Tutor, Assistant, Coach) so the page still works.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable

FILE = "hermes.json"
AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9]{0,23}$")
OWNER_ID_RE = re.compile(r"^[a-z0-9]{1,32}$")
PROFILE_RE = re.compile(r"^[a-z][a-z0-9]{0,23}$")
FEATURES = ("voice", "gmail", "moodle", "icloud", "backup", "studio")
ROLES = ("chief", "tutor", "assistant", "coach")

FALLBACK: dict[str, Any] = {
    "version": 1,
    "owner": {"name": "Owner", "id": "owner", "pronouns": "they/them", "tailscale_login": ""},
    "timezone": "Europe/London",
    "agents": [
        {"id": "chief", "profile": "default", "role": "chief", "name": "Chief", "title": "Chief of Staff"},
        {"id": "tutor", "profile": "tutor", "role": "tutor", "name": "Tutor", "title": "Tutor"},
        {"id": "assistant", "profile": "assistant", "role": "assistant", "name": "Assistant", "title": "Assistant"},
        {"id": "coach", "profile": "coach", "role": "coach", "name": "Coach", "title": "Coach"},
    ],
    "features": {f: False for f in FEATURES},
}

_cache: dict[str, tuple[tuple[int, int], dict]] = {}
_lock = threading.Lock()


def _text(value: Any, limit: int, default: str = "") -> str:
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else default


def normalise(raw: Any) -> dict[str, Any]:
    """Any JSON value -> a team with every field present and checked. Bad agents are dropped; a team needs a chief."""
    raw = raw if isinstance(raw, dict) else {}
    o = raw.get("owner") if isinstance(raw.get("owner"), dict) else {}
    oid = _text(o.get("id"), 32).lower()
    owner = {"name": _text(o.get("name"), 40, FALLBACK["owner"]["name"]),
             "id": oid if OWNER_ID_RE.match(oid) else FALLBACK["owner"]["id"],
             "pronouns": _text(o.get("pronouns"), 24, "they/them"),
             "tailscale_login": _text(o.get("tailscale_login"), 200).lower()}
    agents, ids, profiles = [], set(), set()
    for a in raw.get("agents") if isinstance(raw.get("agents"), list) else []:
        if not isinstance(a, dict):
            continue
        aid, profile = _text(a.get("id"), 24).lower(), _text(a.get("profile"), 24).lower()
        if not AGENT_ID_RE.match(aid) or not PROFILE_RE.match(profile) or aid in ids or profile in profiles:
            continue
        role = _text(a.get("role"), 24).lower() or profile
        title = _text(a.get("title"), 40, role.capitalize())
        agents.append({"id": aid, "profile": profile, "role": role, "name": _text(a.get("name"), 40, aid.capitalize()), "title": title})
        ids.add(aid)
        profiles.add(profile)
    if not any(a["profile"] == "default" for a in agents):
        agents = [dict(a) for a in FALLBACK["agents"]]
    agents.sort(key=lambda a: a["profile"] != "default")           # the chief first, the rest in the file's order
    f = raw.get("features") if isinstance(raw.get("features"), dict) else {}
    return {"version": 1, "owner": owner, "timezone": _text(raw.get("timezone"), 64, "Europe/London"), "agents": agents,
            "features": {k: f.get(k) is True for k in FEATURES}, "studio": {"name": _text((raw.get("studio") or {}).get("name") if isinstance(raw.get("studio"), dict) else None, 40, "Content studio")}}


def load(hermes_home: str | Path = "/data/.hermes") -> dict[str, Any]:
    """The team, re-read when the file changes (mtime and size), else from memory."""
    path = Path(hermes_home) / FILE
    try:
        st = path.stat()
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        return normalise(FALLBACK)
    key = str(path)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == sig:
            return hit[1]
    try:
        data = normalise(json.loads(path.read_text()))
    except (OSError, ValueError):
        data = normalise(FALLBACK)
    with _lock:
        _cache[key] = (sig, data)
    return data


# -- lookups the bridge uses everywhere --------------------------------------------------------------------------------------

def chief(c: dict) -> dict:
    return next(a for a in c["agents"] if a["profile"] == "default")


def profile_agent(c: dict) -> dict[str, str]:
    """profile -> agent id, plus each id to itself (the board stores profiles; the page speaks ids)."""
    out = {a["profile"]: a["id"] for a in c["agents"]}
    out.update({a["id"]: a["id"] for a in c["agents"]})
    return out


def agent_profile(c: dict) -> dict[str, str]:
    return {a["id"]: a["profile"] for a in c["agents"]}


def profile_of(hermes_home: str | Path, ident: str) -> str:
    """An agent id from the page (or a profile) -> the Hermes profile."""
    return agent_profile(load(hermes_home)).get(ident, ident)


def agent_of(hermes_home: str | Path, profile: str) -> str:
    return profile_agent(load(hermes_home)).get(profile, profile)


def name_of(hermes_home: str | Path, profile: str) -> str:
    """The team's name for a profile (or agent id); an agent added later is called by its profile id."""
    c = load(hermes_home)
    a = next((x for x in c["agents"] if profile in (x["profile"], x["id"])), None)
    return a["name"] if a else profile.capitalize()


def owner_name(hermes_home: str | Path) -> str:
    return load(hermes_home)["owner"]["name"]


def feature(hermes_home: str | Path, name: str) -> bool:
    return bool(load(hermes_home)["features"].get(name))


def core_profiles(hermes_home: str | Path) -> list[str]:
    return [a["profile"] for a in load(hermes_home)["agents"]]


def public(hermes_home: str | Path, display: Callable[[str], str | None] | None = None) -> dict[str, Any]:
    """GET /api/team: what the page may know. No login, no Mem0 id. `display` gives a profile's renamed display name."""
    c = load(hermes_home)
    agents = []
    for a in c["agents"]:
        shown = display(a["profile"]) if display else None
        agents.append({**a, "name": shown or a["name"]})
    return {"owner": {"name": c["owner"]["name"], "pronouns": c["owner"]["pronouns"]}, "timezone": c["timezone"],
            "chief": chief(c)["id"], "agents": agents, "features": dict(c["features"]), "studio": dict(c["studio"])}
