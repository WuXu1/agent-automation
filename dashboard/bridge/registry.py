"""What the dashboard knows about the setup that it cannot read from the VM, so that a new integration, agent or service
added later still shows up.

Two halves:
- `registry.json` beside this file: the names, who uses what, where secrets live, ports. It is the one hand-written
  list; describe anything you add there (bridge/README.md says how).
- discovery: what the VM actually has, read on every request, so a thing nobody described still shows up as "found, not
  described yet": secret names in the `.env` files (names only, never values), MCP servers in any profile, services and
  timers installed under /etc/systemd/system. Agents, skills and Hermes cron jobs need no list: they are read live.
"""
from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Any

from actions import Env, _read

HERE = Path(__file__).resolve().parent
SYSTEMD = Path("/etc/systemd/system")
KEY_RE = re.compile(r"^(?:export\s+)?([A-Z][A-Z0-9_]{1,63})\s*=")


def load(path: Path | None = None) -> dict[str, Any]:
    try:
        data = json.loads((path or HERE / "registry.json").read_text())
    except (OSError, ValueError):
        data = {}
    for k in ("integrations", "tools", "services", "timers", "suggestions", "ignoreKeys", "ignoreUnits", "teams"):
        data.setdefault(k, [])
    for k in ("mcp", "roles"):
        data.setdefault(k, {})
    return data


def page_view(reg: dict, team: dict | None = None) -> dict:
    """What the page needs to label things (the Tools grid, roles, services). The registry names agents by profile; with
    `team` (team.load) they become the team's agent ids, and each team agent's title is its role."""
    to_agent: dict[str, str] = {}
    roles: dict[str, str] = {}
    if team:
        to_agent = {a["profile"]: a["id"] for a in team["agents"]}
        roles = {a["id"]: a["title"] for a in team["agents"]}
    ids = lambda xs: [to_agent.get(x, x) for x in xs if isinstance(x, str)]   # noqa: E731
    return {"tools": [{**t, "who": ids(t.get("who", []))} for t in reg["tools"] if isinstance(t, dict)], "mcp": reg["mcp"],
            "roles": {**{to_agent.get(k, k): v for k, v in reg["roles"].items()}, **roles},
            "teams": [{"id": t.get("id", ""), "label": t.get("label", ""), "members": ids(t.get("members", [])), "note": t.get("note", ""),
                       "planned": [p for p in t.get("planned", []) if isinstance(p, dict)]} for t in reg["teams"] if isinstance(t, dict)],
            "services": {s["unit"]: {"label": s.get("label", ""), "port": s.get("port")} for s in reg["services"]}}


# -- secret names ---------------------------------------------------------------------------------------------------------

def env_files(env: Env) -> list[tuple[str, Path]]:
    """(where, path) of every .env the agents read, for naming where a key lives."""
    home = Path(env.hermes_home)
    out = [("shared .env", home / ".env")]
    out += [(f"{p} .env", env.profile_dir(p) / ".env") for p in env.profiles() if p != "default"]
    secrets = home / "owner" / ".secrets"
    try:
        out += [(f"owner/.secrets/{f.name}", f) for f in sorted(secrets.glob("*.env")) if f.is_file()]
    except OSError:
        pass
    return out


def key_names(env: Env) -> dict[str, list[str]]:
    """Key -> where it is set. Only the part before '=' is kept; values are never read into anything."""
    found: dict[str, list[str]] = {}
    for where, path in env_files(env):
        for line in _read(path).splitlines():
            m = KEY_RE.match(line.strip())
            if m:
                found.setdefault(m.group(1), [])
                if where not in found[m.group(1)]:
                    found[m.group(1)].append(where)
    return found


def undescribed_keys(reg: dict, names: dict[str, list[str]]) -> list[dict]:
    claimed = {k for i in reg["integrations"] for k in i.get("keys", [])}
    ignore = reg["ignoreKeys"]
    return [{"key": k, "where": names[k]} for k in sorted(names)
            if k not in claimed and not any(fnmatch.fnmatchcase(k, pat) for pat in ignore)]


# -- systemd ---------------------------------------------------------------------------------------------------------------

def _description(path: Path) -> str:
    m = re.search(r"(?m)^Description=(.+)$", _read(path))
    return m.group(1).strip()[:120] if m else ""


def custom_units(reg: dict, kind: str = "service", root: Path | None = None) -> list[dict]:
    """Units someone installed under /etc/systemd/system (not the distro's), enabled ones only for services."""
    root = root or SYSTEMD
    out = []
    try:
        files = sorted(f for f in root.glob(f"*.{kind}") if f.is_file() and not f.is_symlink())
    except OSError:
        return []
    wants = set()
    if kind == "service":
        try:
            for d in root.glob("*.wants"):
                wants |= {f.name for f in d.iterdir()}
        except OSError:
            pass
    for f in files:
        unit = f.name.removesuffix(f".{kind}")
        if any(fnmatch.fnmatchcase(unit, pat) for pat in reg["ignoreUnits"]):
            continue
        if kind == "service" and f.name not in wants:
            continue                                    # oneshots started by a timer or a path unit
        out.append({"unit": unit, "description": _description(f)})
    return out


def service_list(reg: dict, root: Path | None = None) -> list[dict]:
    """The services the Runway shows: the described ones in their order, then any other installed one."""
    known = {s["unit"] for s in reg["services"]}
    rows = [{"unit": s["unit"], "label": s.get("label", ""), "port": s.get("port"), "described": True} for s in reg["services"]]
    rows += [{"unit": u["unit"], "label": u["description"], "port": None, "described": False}
             for u in custom_units(reg, "service", root) if u["unit"] not in known]
    return rows


def timer_list(reg: dict, root: Path | None = None) -> list[dict]:
    labels = {t["unit"]: t.get("label", "") for t in reg["timers"]}
    rows = []
    for u in custom_units(reg, "timer", root):
        text = _read((root or SYSTEMD) / f"{u['unit']}.timer")
        cal = re.findall(r"(?m)^On(?:Calendar|BootSec|UnitActiveSec)=(.+)$", text)
        rows.append({"unit": u["unit"], "label": labels.get(u["unit"]) or u["description"], "schedule": ", ".join(c.strip() for c in cal)[:80],
                     "described": u["unit"] in labels})
    return rows
