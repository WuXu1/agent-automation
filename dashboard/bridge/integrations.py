"""The Integrations Hub: every outside service the agents sign in to, whether it still works, and the balances of the
paid ones. Optional add-ons (Gmail, Moodle, iCloud, voice replies, backups) show as "off" until hermes.json switches them on.

Two halves:
- local facts the bridge reads itself (files' ages, the Moodle keep-alive job's last result, the backup unit's result);
- network checks the jobs runner makes at most once an hour (`check_all`): a Gmail IMAP login, an iCloud CalDAV
  PROPFIND, each Telegram bot's getMe, a Gemini key check, plus the balances (jobs.do_balances).
No secret value is ever read into an answer: only the path of the file that holds it, and whether the check passed.
"""
from __future__ import annotations

import base64
import datetime as dt
import imaplib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import team
import registry
from actions import Env, _read

CHECK_MAX_AGE = 3600


def secrets_dir(env: Env) -> Path:
    """The owner's secret files (the add-ons' app passwords and cookies)."""
    return Path(env.hermes_home) / "owner" / ".secrets"


def _path(env: Env) -> Path:
    return Path(env.state_dir) / "integrations.json"


def cached(env: Env) -> dict | None:
    try:
        return json.loads(_path(env).read_text())
    except (OSError, ValueError):
        return None


def stale(env: Env) -> bool:
    c = cached(env)
    return not c or time.time() - c.get("at", 0) / 1000 > CHECK_MAX_AGE


def _env_file(path: Path) -> dict[str, str]:
    out = {}
    for line in _read(path).splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and not k.startswith("#"):
            out[k.removeprefix("export ").strip()] = v.strip().strip("'\"")
    return out


def _mtime(path: Path) -> int | None:
    try:
        return int(path.stat().st_mtime * 1000)
    except OSError:
        return None


# -- the network checks (jobs runner) ----------------------------------------------------------------------------------------

def check_gmail(env: Env) -> dict:
    if not team.feature(env.hermes_home, "gmail"):
        return {"ok": None, "error": "add-on not switched on"}
    vals = _env_file(secrets_dir(env) / "gmail.env")
    if not vals.get("GMAIL_ADDRESS") or not vals.get("GMAIL_APP_PASSWORD"):
        return {"ok": False, "error": "no app password on the VM"}
    try:
        m = imaplib.IMAP4_SSL("imap.gmail.com", timeout=20)
        m.login(vals["GMAIL_ADDRESS"], vals["GMAIL_APP_PASSWORD"].replace(" ", ""))
        m.logout()
        return {"ok": True}
    except imaplib.IMAP4.error:
        return {"ok": False, "error": "Gmail refused the app password (revoked?)"}
    except OSError as exc:
        return {"ok": None, "error": f"Gmail could not be reached ({type(exc).__name__})"}


def check_icloud(env: Env) -> dict:
    if not team.feature(env.hermes_home, "icloud"):
        return {"ok": None, "error": "add-on not switched on"}
    vals = {**_env_file(Path(env.hermes_home) / ".env"), **_env_file(secrets_dir(env) / "icloud.env")}
    user, pw = vals.get("ICLOUD_APPLE_ID"), vals.get("ICLOUD_APP_PASSWORD")
    if not user or not pw:
        return {"ok": False, "error": "no app-specific password on the VM"}
    auth = base64.b64encode(f"{user}:{pw}".encode()).decode()
    req = urllib.request.Request("https://caldav.icloud.com/", method="PROPFIND", data=b"",
                                 headers={"Authorization": f"Basic {auth}", "Depth": "0", "Content-Type": "application/xml"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return {"ok": r.status in (200, 207)}
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code in (401, 403):
            return {"ok": False, "error": "iCloud refused the app-specific password"}
        if exc.code == 207:
            return {"ok": True}
        return {"ok": None, "error": f"iCloud said HTTP {exc.code}"}
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": None, "error": f"iCloud could not be reached ({type(exc).__name__})"}


def _get(url: str, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "hermes-dash", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code, {}


def check_telegram(env: Env) -> dict:
    """Each agent's bot: Telegram's getMe (free, changes nothing). The token goes only to api.telegram.org."""
    bots, seen = [], set()
    for where, path in registry.env_files(env):
        if not where.endswith(".env") or where.startswith("owner/"):
            continue
        token = _env_file(path).get("TELEGRAM_BOT_TOKEN")
        if not token or token in seen:
            continue
        seen.add(token)
        name = team.name_of(env.hermes_home, "default" if where == "shared .env" else where.split()[0])
        try:
            code, body = _get(f"https://api.telegram.org/bot{token}/getMe")
        except (urllib.error.URLError, OSError) as exc:
            bots.append({"where": name, "ok": None, "error": type(exc).__name__})
            continue
        bots.append({"where": name, "ok": code == 200 and bool(body.get("ok")), "username": (body.get("result") or {}).get("username"),
                     "error": None if code == 200 else "token refused" if code in (401, 404) else f"HTTP {code}"})
    if not bots:
        return {"ok": False, "error": "no bot tokens on the VM", "bots": []}
    oks = [b["ok"] for b in bots]
    return {"ok": False if False in oks else None if None in oks else True, "bots": bots}


def check_gemini(env: Env) -> dict:
    key = _env_file(Path(env.hermes_home) / ".env").get("GEMINI_API_KEY")
    if not key:
        return {"ok": False, "error": "no key on the VM"}
    try:
        code, _ = _get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1", {"x-goog-api-key": key})
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": None, "error": f"Google could not be reached ({type(exc).__name__})"}
    return {"ok": True} if code == 200 else {"ok": False, "error": "Google refused the key" if code in (400, 401, 403) else f"Google said HTTP {code}"}


CHECKS: dict[str, Callable[[Env], dict]] = {"gmail": check_gmail, "icloud": check_icloud, "telegram": check_telegram,
                                            "gemini": check_gemini}


def check_all(env: Env, balances: Callable[[Env], dict], checks: dict[str, Callable[[Env], dict]] | None = None) -> dict:
    out: dict[str, Any] = {"at": int(time.time() * 1000)}
    for name, fn in (checks or CHECKS).items():
        try:
            out[name] = fn(env)
        except Exception as exc:  # noqa: BLE001 - one broken check must not hide the others
            out[name] = {"ok": None, "error": type(exc).__name__}
    out["balances"] = balances(env)
    p = _path(env)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(".integrations.json.tmp")
    tmp.write_text(json.dumps(out))
    os.replace(tmp, p)
    return out


# -- the hub (the bridge) ----------------------------------------------------------------------------------------------------

UNI_LOGIN_DIR = Path("/var/lib/uni-login")          # `uni-login` keeps a one-line, secret-free status here (docs/UNI-LOGIN.md)


def _uni_login() -> dict:
    """Whether the university sign-in helper is set up and how its last sign-in went (never any secret)."""
    parts = []
    try:
        parts = (UNI_LOGIN_DIR / "status").read_text().split()
    except OSError:
        pass
    at = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return {"configured": (UNI_LOGIN_DIR / "configured").exists(), "result": parts[0] if parts and at else "never",
            "at": at, "reason": parts[2] if len(parts) > 2 else ""}


def _status(ok: bool | None, warn: bool = False) -> str:
    return "unknown" if ok is None else "attention" if not ok else "expiring" if warn else "connected"


def _builtin(env: Env, c: dict, cron_jobs: list[dict], backup: dict, now: int) -> dict[str, dict]:
    """Status and facts for the services the bridge knows how to check itself (registry `check: builtin`)."""
    b = c.get("balances") or {}
    out: dict[str, dict] = {}

    keep = next((j for j in cron_jobs if "moodle" in (j.get("name") or "").lower()), None)      # the kit runs it on the tutor
    uni = _uni_login()
    renewed = (uni["at"] * 1000 if uni["result"] == "ok" else None) or _mtime(secrets_dir(env) / "moodle.env") \
        or _mtime(env.profile_dir("tutor") / ".env")
    out["moodle"] = {"status": _status(None if not keep else keep.get("lastStatus") == "ok"),
                     "facts": [f"cookie renewed {_days(renewed, now)}" if renewed else "cookie file not found",
                               f"keep-alive {keep.get('lastStatus')} {_ago(keep.get('lastAt'), now)}" if keep else "no keep-alive job"]}

    out["uni-login"] = {"status": {"ok": "connected", "failed": "attention"}.get(uni["result"], "unknown"),
                        "facts": [{"ok": f"last sign-in worked {_ago(uni['at'] * 1000, now)}",
                                   "failed": f"last sign-in failed ({uni['reason'] or 'unknown'}) {_ago(uni['at'] * 1000, now)}",
                                   "running": "signing in now"}.get(uni["result"],
                                  "set up, no sign-in yet" if uni["configured"] else "not set up: sudo hermes-addon moodle-login"),
                                  "renews the Moodle cookie by itself when the session ends" if uni["configured"] else ""]}

    g = c.get("gmail") or {}
    out["gmail"] = {"status": _status(g.get("ok")) if g else "unknown",
                    "facts": [g.get("error") or ("login works" if g.get("ok") else "not checked yet"), "read and draft only: no sending, deleting or marking read"]}

    i = c.get("icloud") or {}
    out["icloud"] = {"status": _status(i.get("ok")) if i else "unknown",
                     "facts": [i.get("error") or ("signed in" if i.get("ok") else "not checked yet"),
                               f"{team.name_of(env.hermes_home, 'tutor')} reads, {team.name_of(env.hermes_home, 'assistant')} writes"]}

    ok = backup.get("result") == "success" if backup.get("result") else None
    late = bool(backup.get("lastRunAt") and now - backup["lastRunAt"] > 30 * 3_600_000)
    out["drive"] = {"status": _status(ok, late),
                    "facts": [f"last backup {backup.get('result') or 'unknown'} {_ago(backup.get('lastRunAt'), now)}", "encrypted archive to Google Drive"]}

    tg = c.get("telegram") or {}
    bots = tg.get("bots") or []
    good = [x for x in bots if x.get("ok")]
    out["telegram"] = {"status": _status(tg.get("ok")) if tg else "unknown",
                       "facts": [f"{len(good)} of {len(bots)} bots answering" if bots else tg.get("error") or "not checked yet",
                                 ", ".join("@" + x["username"] for x in good if x.get("username"))[:160],
                                 ", ".join(f"{x['where']}: {x.get('error')}" for x in bots if not x.get("ok"))[:160]]}

    gm = c.get("gemini") or {}
    out["gemini"] = {"status": _status(gm.get("ok")) if gm else "unknown",
                     "facts": [gm.get("error") or ("key works" if gm.get("ok") else "not checked yet")]}

    e = b.get("elevenlabs") or {}
    left = (e.get("limit") or 0) - (e.get("used") or 0) if e.get("limit") else None
    out["elevenlabs"] = {"status": "attention" if e.get("error") or (left is not None and left < 3000) else "expiring" if left is not None and left / e["limit"] < 0.2 else "connected" if left is not None else "unknown",
                         "facts": [f"resets {_until(e.get('resetAt'), now)}" if e.get("resetAt") else e.get("error") or "",
                                   f"{e.get('tier')} plan" if e.get("tier") else ""],
                         "balance": {"value": left, "limit": e.get("limit"), "resetAt": e.get("resetAt")} if left is not None else None}

    d = b.get("deepseek") or {}
    dv = d.get("balance")
    out["deepseek"] = {"status": "attention" if d.get("error") or (dv is not None and dv < 2) else "expiring" if dv is not None and dv < 5 else "connected" if dv is not None else "unknown",
                       "facts": [d.get("error") or "" if dv is None else "the agents' model, pay as you go"],
                       "balance": {"value": dv, "currency": d.get("currency", "USD")} if dv is not None else None}
    return out


def hub(env: Env, cron_jobs: list[dict], backup: dict, now_ms: int | None = None, *,
        reg: dict | None = None, servers: list[dict] | None = None, units: dict[str, str] | None = None,
        keys: dict[str, list[str]] | None = None, catalog: list[dict] | None = None) -> dict:
    """One card per integration in the registry (same shape for all), one for each MCP server nobody described, the secret
    names the registry does not explain, and suggestions from Hermes' catalog that no agent has yet."""
    reg = reg or registry.load()
    servers, units, keys = servers or [], units or {}, keys or {}
    now = now_ms or int(time.time() * 1000)
    c = cached(env) or {}
    built = _builtin(env, c, cron_jobs, backup, now)
    setup = team.load(env.hermes_home)
    to_agent = team.profile_agent(setup)

    def _agent(profile: str) -> str:
        return to_agent.get(profile, profile)

    def _name(profile: str) -> str:
        return team.name_of(env.hermes_home, profile)

    by_server = {s["name"].lower(): s for s in servers}           # Hermes keeps the case it was typed in
    cards, claimed = [], set()
    for item in reg["integrations"]:
        claimed |= {m.lower() for m in item.get("mcp") or []}
        card = {k: item.get(k) for k in ("id", "name", "kind", "secret", "fix")}
        card.update(usedBy=[_agent(p) for p in item.get("usedBy") or []], described=True, balance=None, facts=[])
        addon = item.get("feature")
        card["addon"] = addon or None
        stored = sorted({w for k in item.get("keys") or [] for w in keys.get(k, [])})
        mine = [by_server[m.lower()] for m in item.get("mcp") or [] if m.lower() in by_server]
        check = item.get("check", "none")
        if addon and not setup["features"].get(addon):
            card["status"] = "off"
            card["facts"] = ["optional add-on, not switched on", item.get("enable") or "switch it on with the kit's add-on command"]
        elif item.get("inUse") is False:
            card["status"] = "off"
            card["facts"] = [item.get("note") or "not in use", f"still stored in {', '.join(stored)}" if stored else "nothing stored"]
        elif check == "builtin":
            card.update(built.get(item["id"], {"status": "unknown", "facts": []}))
        elif check == "service":
            state = units.get(item.get("service", ""), "unknown")
            card["status"] = "connected" if state == "active" else "attention" if state in ("failed", "inactive") else "unknown"
            card["facts"] = [f"{item.get('service')} {'running' if state == 'active' else state}"]
        elif check in ("mcp", "azure"):
            on = [p for s in mine for p, enabled in s["agents"].items() if enabled]
            card["status"] = "connected" if on else "attention" if mine else "unknown"
            card["facts"] = [f"on for {', '.join(_name(p) for p in on)}" if on else "switched off" if mine else "not set up on any agent"]
            if item.get("service"):
                state = units.get(item["service"], "unknown")
                card["facts"].append(f"{item['service']} {'running' if state == 'active' else state}")
                if state in ("failed", "inactive") and card["status"] == "connected":
                    card["status"] = "attention"
        elif check == "free":                            # a free service with no key: nothing to sign in to
            card["status"] = "connected"
            card["facts"] = ["no key needed"]
        elif check == "plugin":                          # a Hermes plugin folder in the profile (OpenAlex is one)
            has = [pr for pr in env.profiles() if (env.profile_dir(pr) / "plugins" / str(item.get("plugin"))).is_dir()]
            card["status"] = "connected" if has else "attention"
            card["facts"] = [f"plugin installed for {', '.join(_name(pr) for pr in has)}" if has else "plugin not installed"]
            if has:
                card["usedBy"] = [_agent(pr) for pr in has]
        else:
            card["status"] = "unknown"
        live = {_agent(p) for srv in mine for p, enabled in srv["agents"].items() if enabled}
        if live:                                         # who really has its MCP server switched on wins over the registry's guess
            card["usedBy"] = [a for a in card["usedBy"] if a in live] + sorted(live - set(card["usedBy"]))
        if item.get("note") and item.get("inUse") is not False and card["status"] != "off":
            card["facts"].append(item["note"])
        card["facts"] = [f for f in card["facts"] if f][:3]
        card["inUse"] = item.get("inUse") is not False and card["status"] != "off"
        cards.append(card)
    picked = {str(sg.get("catalog")).lower(): sg for sg in reg["suggestions"]}
    for s in servers:
        if s["name"].lower() in claimed:
            continue
        on = [p for p, enabled in s["agents"].items() if enabled]
        sg = picked.get(s["name"].lower())                       # added from a suggestion: its name and reason describe it
        cards.append({"id": f"mcp:{s['name']}", "name": sg.get("name", s["name"]) if sg else s["name"],
                      "kind": "MCP server from Hermes' catalog" if sg else f"MCP server ({s['transport']})", "described": bool(sg), "inUse": True,
                      "status": "connected" if on else "attention", "usedBy": [_agent(p) for p in s["agents"]], "balance": None,
                      "facts": [f"on for {', '.join(_name(p) for p in on)}" if on else "switched off everywhere",
                                sg.get("why", "") if sg else s.get("address") or ""],
                      "secret": f"env: {', '.join(s['env'])}" if s.get("env") else "no secret" if sg and s.get("auth") != "oauth" else "Hermes' OAuth token store" if s.get("auth") == "oauth" else "no env vars",
                      "fix": "Agent Studio → MCP" if sg else "describe it in dashboard/bridge/registry.json"})
    installed = set(by_server)
    by_catalog = {e["name"]: e for e in catalog or []}
    suggestions = []
    for sg in reg["suggestions"]:
        e = by_catalog.get(sg.get("catalog"))
        if catalog is not None and not e:
            continue                                    # no longer in this Hermes release's catalog
        if str(sg.get("catalog")).lower() in installed:
            continue
        suggestions.append({"catalog": sg["catalog"], "name": sg.get("name") or sg["catalog"], "for": sg.get("for") or [],
                            "agents": [_agent(p) for p in sg.get("for") or []], "why": sg.get("why", ""), "cost": sg.get("cost", ""),
                            "description": (e or {}).get("description", ""), "auth": (e or {}).get("auth"),
                            "oneClick": bool(e) and not e.get("needsInstall") and not any(v.get("required") for v in e.get("env") or [])})
    return {"checkedAt": c.get("at"), "cards": cards, "found": registry.undescribed_keys(reg, keys), "suggestions": suggestions}


def _ago(ms: Any, now: int) -> str:
    if not isinstance(ms, (int, float)) or not ms:
        return ""
    m = max(0, int((now - ms) / 60_000))
    return "just now" if m < 1 else f"{m} min ago" if m < 60 else f"{m // 60} h ago" if m < 2880 else f"{m // 1440} days ago"


def _days(ms: int | None, now: int) -> str:
    if not ms:
        return ""
    d = int((now - ms) / 86_400_000)
    return "today" if d < 1 else "yesterday" if d < 2 else f"{d} days ago"


def _until(ms: Any, now: int) -> str:
    if not isinstance(ms, (int, float)) or not ms:
        return ""
    d = int((ms - now) / 86_400_000)
    return "already" if d < 0 else "today" if d < 1 else f"in {d} days"
