"""The bridge's writes: manage agent profiles, brief the chief, add and answer board cards, ask for a quiet gateway restart. Each one is a deliberate request from the page (behind its confirm step) and:

- runs Hermes' own CLI with an argument list (never a shell), as the bridge's user `hermes`;
- backs a file up before changing it (`<file>.bak-before-dash-<time>`), writes a temporary copy, has Hermes' Python parse
  it, checks the parsed value is the one asked for, and only then swaps it in;
- is appended to `actions.log` (what, which profile, when, the result; never a SOUL's text or a key);
- never restarts anything itself: a restart is a request file that a root-owned helper picks up (bridge/README.md).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import crew

PROFILE_RE = re.compile(r"^[a-z][a-z0-9]{1,23}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,60}$")
TASK_RE = re.compile(r"^t_[A-Za-z0-9]{4,40}$")
EFFORTS = ("low", "medium", "high")
RESERVED = {"default", "commander", "user", "worker", "owner", "helper", "dashboard", "all", "none", "test"}


def reserved(env: "Env") -> set[str]:
    """Names a new profile may not take: the fixed ones, the crew's agent ids and the owner's Mem0 id (crew.json)."""
    c = crew.load(env.hermes_home)
    return RESERVED | {a["id"] for a in c["agents"]} | {c["owner"]["id"]}
LIMITS = {"name": 40, "description": 600, "soul": 20_000, "brief": 4000, "title": 200, "body": 4000, "answer": 2000}


class ActionError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Env:
    hermes_home: str = "/data/.hermes"
    hermes_bin: str = "/opt/hermes/hermes-agent/venv/bin/hermes"
    hermes_python: str = "/opt/hermes/hermes-agent/venv/bin/python"
    state_dir: str = "/data/.hermes/hermes-dash"
    gateway_url: str = "http://127.0.0.1:8642"
    cli_timeout: float = 90.0
    extra_env: dict = field(default_factory=dict)

    def profile_dir(self, profile: str) -> Path:
        return Path(self.hermes_home) if profile == "default" else Path(self.hermes_home) / "profiles" / profile

    def profiles(self) -> list[str]:
        root = Path(self.hermes_home) / "profiles"
        found = sorted(p.name for p in root.iterdir() if p.is_dir() and PROFILE_RE.match(p.name)) if root.is_dir() else []
        return ["default", *found]


_lock = threading.Lock()   # one write at a time


def stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _clean(value: Any, key: str, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ActionError(400, f"{key} must be text")
    value = value.replace("\r\n", "\n").strip()
    if required and not value:
        raise ActionError(400, f"{key} is empty")
    if len(value) > LIMITS[key]:
        raise ActionError(400, f"{key} is longer than {LIMITS[key]:,} characters")
    return value


def log_action(env: Env, what: str, **details: Any) -> None:
    Path(env.state_dir).mkdir(parents=True, exist_ok=True)
    line = json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "what": what, **details})
    with open(Path(env.state_dir) / "actions.log", "a") as f:
        f.write(line + "\n")


def cli(env: Env, *args: str, stdin: str | None = None) -> str:
    """Hermes' CLI as the bridge's user, no shell. Raises with the CLI's last line on failure."""
    run_env = {"PATH": "/usr/bin:/bin", "HOME": "/home/hermes", "HERMES_HOME": env.hermes_home, "LANG": "C.UTF-8",
               "NO_COLOR": "1", **env.extra_env}
    try:
        # stdin is the text we send, or nothing: a CLI that stops to ask a question must fail, not wait for ever.
        res = subprocess.run([env.hermes_bin, *args], input=stdin if stdin is not None else "", capture_output=True, text=True,
                             timeout=env.cli_timeout, env=run_env, cwd=env.hermes_home)
    except subprocess.TimeoutExpired:
        raise ActionError(504, f"hermes {args[0]} {args[1] if len(args) > 1 else ''} took too long") from None
    except OSError:
        raise ActionError(500, "The hermes command is not available to the bridge") from None
    if res.returncode != 0:
        last = (res.stderr.strip() or res.stdout.strip()).splitlines()[-1:] or ["no output"]
        raise ActionError(502, f"hermes {args[0]} {args[1] if len(args) > 1 else ''} failed: {last[0][:200]}")
    return res.stdout


# -- safe file edits ---------------------------------------------------------------------------------------------------------

def backup(path: Path, why: str) -> Path | None:
    if not path.exists():
        return None
    dest = path.with_name(f"{path.name}.bak-before-dash-{why}-{stamp()}")
    shutil.copy2(path, dest)
    return dest


def check_yaml(env: Env, path: Path, expect: dict[str, Any]) -> None:
    """Hermes' own Python parses the file; each dotted key in `expect` must hold the expected value."""
    probe = ("import json, sys, yaml\n"
             "d = yaml.safe_load(open(sys.argv[1]))\n"
             "out = {}\n"
             "for k in json.loads(sys.argv[2]):\n"
             "    v = d\n"
             "    for part in k.split('.'):\n"
             "        v = v.get(part) if isinstance(v, dict) else None\n"
             "    out[k] = v\n"
             "print(json.dumps(out))\n")
    try:
        res = subprocess.run([env.hermes_python, "-I", "-c", probe, str(path), json.dumps(list(expect))],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise ActionError(500, "Could not check the edited config (Hermes' Python did not run)") from None
    if res.returncode != 0:
        raise ActionError(500, "The edited config would not parse, so nothing was changed")
    got = json.loads(res.stdout or "{}")
    for k, want in expect.items():
        if got.get(k) != want:
            raise ActionError(500, f"The edit did not land as expected ({k}), so nothing was changed")


def write_checked(env: Env, path: Path, text: str, why: str, expect: dict[str, Any] | None = None) -> None:
    tmp = path.with_name(f".{path.name}.dash-{uuid.uuid4().hex[:8]}")
    tmp.write_text(text)
    try:
        if path.exists():
            shutil.copymode(path, tmp)
        if expect is not None:
            check_yaml(env, tmp, expect)
        backup(path, why)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def set_block_value(text: str, block: str, key: str, value: str) -> str:
    """Set `  key: value` inside a top-level `block:` (adding the line, or the block, when missing). Keeps comments."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if re.match(rf"^{re.escape(block)}:\s*(#.*)?$", l)), None)
    if start is None:
        return text.rstrip("\n") + f"\n{block}:\n  {key}: {value}\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i].startswith((" ", "#"))), len(lines))
    for i in range(start + 1, end):
        m = re.match(rf"^(  {re.escape(key)}:)\s*[^#\n]*?(\s+#.*)?$", lines[i])
        if m:
            lines[i] = f"{m.group(1)} {value}{m.group(2) or ''}"
            return "\n".join(lines) + "\n"
    lines.insert(start + 1, f"  {key}: {value}")
    return "\n".join(lines) + "\n"


def set_mcp_enabled(text: str, server: str, enabled: bool) -> str:
    """Set `enabled:` of one server under `mcp_servers:`; adds the line when the server has none."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("mcp_servers:")), None)
    if start is None:
        raise ActionError(400, "This profile has no MCP servers")
    end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i].startswith((" ", "#"))), len(lines))
    s = next((i for i in range(start + 1, end) if re.match(rf"^  {re.escape(server)}:\s*$", lines[i])), None)
    if s is None:
        raise ActionError(404, f"No MCP server called {server} on this profile")
    e = next((i for i in range(s + 1, end) if re.match(r"^  \S", lines[i])), end)
    value = "true" if enabled else "false"
    for i in range(s + 1, e):
        if re.match(r"^    enabled:", lines[i]):
            lines[i] = f"    enabled: {value}"
            break
    else:
        lines.insert(s + 1, f"    enabled: {value}")
    return "\n".join(lines) + "\n"


def set_env_value(text: str, key: str, value: str) -> str:
    out, done = [], False
    for line in text.splitlines():
        if line.split("=", 1)[0].removeprefix("export ").strip() == key:
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    return "\n".join(out) + "\n"


def set_display_name(text: str, name: str) -> str:
    quoted = json.dumps(name, ensure_ascii=False)    # a JSON string is a valid YAML scalar
    if re.search(r"(?m)^display_name:", text):
        text = re.sub(r"(?m)^display_name:.*$", f"display_name: {quoted}", text)
    else:
        text = text.rstrip("\n") + f"\ndisplay_name: {quoted}\n"
    return re.sub(r"(?m)^(    title:).*$", rf"\1 {quoted}", text, count=1)


# -- restart bookkeeping -----------------------------------------------------------------------------------------------------

def pending_path(env: Env) -> Path:
    return Path(env.state_dir) / "restart-pending.json"


def need_restart(env: Env, reason: str) -> None:
    p = pending_path(env)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        data = {"reasons": []}
    data["reasons"] = [r for r in data.get("reasons", []) if r.get("text") != reason] + [{"text": reason, "at": int(time.time())}]
    p.write_text(json.dumps(data))


def restart_state(env: Env, gateway_started: int | None) -> dict:
    """Pending reasons not yet covered by a gateway start, and the helper's last report."""
    try:
        reasons = json.loads(pending_path(env).read_text()).get("reasons", [])
    except (OSError, ValueError):
        reasons = []
    if gateway_started:
        reasons = [r for r in reasons if r.get("at", 0) * 1000 > gateway_started]
    try:
        last = json.loads((Path(env.state_dir) / "restart.status").read_text())
    except (OSError, ValueError):
        last = None
    requested = (Path(env.state_dir) / "restart.request").exists()
    return {"needed": [r["text"] for r in reasons], "requested": requested, "last": last}


def request_restart(env: Env) -> dict:
    with _lock:
        Path(env.state_dir).mkdir(parents=True, exist_ok=True)
        (Path(env.state_dir) / "restart.request").write_text(json.dumps({"at": int(time.time()), "by": "dashboard"}))
        log_action(env, "restart-requested")
    return {"ok": True}


# -- backup now (the backup add-on) -------------------------------------------------------------------------------------------------

def backup_state(env: Env, shown: dict | None) -> dict:
    """The nightly backup unit as systemd sees it, and whether the page's request is still waiting for the helper."""
    s = shown or {}
    try:
        last = json.loads((Path(env.state_dir) / "backup.status").read_text())
    except (OSError, ValueError):
        last = None
    return {"active": s.get("ActiveState") in ("activating", "active", "reloading"), "result": s.get("Result"),
            "requested": (Path(env.state_dir) / "backup.request").exists(), "last": last}


def request_backup(env: Env, shown: dict | None) -> dict:
    """A request file; the root-owned helper (hermes-dash-backup.path) starts hermes-backup.service."""
    state = backup_state(env, shown)
    if state["active"]:
        raise ActionError(409, "A backup is running already")
    p = Path(env.state_dir) / "backup.status"
    try:
        last_at = json.loads(p.read_text()).get("at", 0)
    except (OSError, ValueError):
        last_at = 0
    if time.time() - last_at < 600:
        raise ActionError(429, "A backup was started in the last 10 minutes")
    with _lock:
        Path(env.state_dir).mkdir(parents=True, exist_ok=True)
        (Path(env.state_dir) / "backup.request").write_text(json.dumps({"at": int(time.time()), "by": "dashboard"}))
        log_action(env, "backup-requested")
    return {"ok": True}


# -- agents ------------------------------------------------------------------------------------------------------------------

def _read(path: Path) -> str:
    try:
        return path.read_text()
    except OSError:
        return ""


def profile_meta(env: Env, profile: str) -> dict:
    """display_name and description from profile.yaml (two plain keys; quoting handled for the common cases)."""
    text = _read(env.profile_dir(profile) / "profile.yaml")
    meta: dict[str, str] = {}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(display_name|description):\s*(.*)$", line)
        if not m:
            continue
        value = m.group(2)
        j = i + 1
        while j < len(lines) and lines[j].startswith("  ") and not re.match(r"^\S", lines[j]):
            value += " " + lines[j].strip()
            j += 1
        value = value.strip()
        if value[:1] in ("'", '"') and value[-1:] == value[:1]:
            value = value[1:-1].replace("''", "'") if value[0] == "'" else json.loads(value)
        meta[m.group(1)] = value
    return meta


def agent_detail(env: Env, profile: str) -> dict:
    if profile not in env.profiles():
        raise ActionError(404, "No such agent")
    d = env.profile_dir(profile)
    config = _read(d / "config.yaml")
    meta = profile_meta(env, profile)
    effort = None
    m = re.search(r"(?m)^agent:\s*\n(?:(?:  .*|\s*)\n)*?  reasoning_effort:\s*(\S+)", config)
    if m:
        effort = m.group(1).strip("'\"")
    model = None
    m = re.search(r"(?m)^model:\s*\n(?:(?:  .*|\s*)\n)*?  default:\s*(\S+)", config)
    if m:
        model = m.group(1).strip("'\"")
    env_text = _read(d / ".env")
    return {
        "profile": profile,
        "name": meta.get("display_name") or profile.capitalize(),
        "description": meta.get("description", ""),
        "soul": _read(d / "SOUL.md"),
        "model": model,
        "effort": effort,
        "telegram": bool(re.search(r"(?m)^TELEGRAM_BOT_TOKEN=\S", env_text)),
        "core": profile in crew.core_profiles(env.hermes_home),
        "reportsTo": manager_of(load_org(env), env.profiles(), profile),
    }


def create_agent(env: Env, args: dict) -> dict:
    profile = _clean(args.get("profile"), "name").lower()
    if not PROFILE_RE.match(profile) or profile in reserved(env):
        raise ActionError(400, "The profile id must be 2 to 24 lowercase letters or digits, starting with a letter")
    name = _clean(args.get("name"), "name")
    description = _clean(args.get("description"), "description")
    soul = _clean(args.get("soul"), "soul", required=False)
    source = args.get("from") or "assistant"
    model = args.get("model")
    effort = args.get("effort")
    with _lock:
        if profile in env.profiles():
            raise ActionError(409, f"There is already an agent called {profile}")
        if source == "default" or source not in env.profiles():
            # The chief's profile is the Hermes home itself (the shared .env): new agents start from a specialist.
            raise ActionError(400, "Start a new agent from one of the specialists")
        _validate_model_effort(model, effort)
        boss = args.get("reportsTo") or "default"
        if boss not in env.profiles():
            raise ActionError(400, "Pick an existing agent as the lead")
        cli(env, "profile", "create", "--clone-from", source, "--no-alias", "--description", description, "--", profile)
        d = env.profile_dir(profile)
        if not d.is_dir():
            raise ActionError(502, "hermes profile create ran but the profile folder is missing")
        # Its own API key and memory name: a clone otherwise carries the source's (CONFIG.md: one key per profile).
        env_path = d / ".env"
        text = _read(env_path)
        text = set_env_value(text, "API_SERVER_KEY", secrets.token_urlsafe(32))
        if re.search(r"(?m)^MEM0_AGENT_ID=", text):
            text = set_env_value(text, "MEM0_AGENT_ID", profile)
        write_checked(env, env_path, text, "create")
        os.chmod(env_path, 0o600)
        pf = d / "profile.yaml"
        write_checked(env, pf, set_display_name(_read(pf), name), "create", {"display_name": name})
        if soul:
            write_checked(env, d / "SOUL.md", soul + "\n", "create")
        _apply_model_effort(env, profile, model, effort)
        org = set_manager(env, profile, args.get("reportsTo") or "default")
        save_org(env, org)
        synced = sync_team_skills(env, org)
        save_org(env, org)
        need_restart(env, f"new agent {name} ({profile})")
        log_action(env, "agent-created", profile=profile, source=source, reports_to=args.get("reportsTo") or "default", skills=synced)
    return agent_detail(env, profile)


def _validate_model_effort(model: Any, effort: Any) -> None:
    if model is not None and (not isinstance(model, str) or not MODEL_RE.match(model)):
        raise ActionError(400, "That is not a model name")
    if effort is not None and effort not in EFFORTS:
        raise ActionError(400, "Reasoning effort is low, medium or high")


def _apply_model_effort(env: Env, profile: str, model: str | None, effort: str | None) -> list[str]:
    changed = []
    path = env.profile_dir(profile) / "config.yaml"
    text = _read(path)
    expect: dict[str, Any] = {}
    if model:
        text, expect["model.default"] = set_block_value(text, "model", "default", model), model
        changed.append("model")
    if effort:
        text, expect["agent.reasoning_effort"] = set_block_value(text, "agent", "reasoning_effort", effort), effort
        changed.append("effort")
    if expect:
        write_checked(env, path, text, "model", expect)
    return changed


def update_agent(env: Env, profile: str, args: dict) -> dict:
    if profile not in env.profiles():
        raise ActionError(404, "No such agent")
    d = env.profile_dir(profile)
    changed: list[str] = []
    with _lock:
        model, effort = args.get("model"), args.get("effort")
        _validate_model_effort(model, effort)
        if "name" in args:
            name = _clean(args["name"], "name")
            pf = d / "profile.yaml"
            write_checked(env, pf, set_display_name(_read(pf), name), "rename", {"display_name": name})
            changed.append("name")
        if "description" in args:
            cli(env, "profile", "describe", "--text", _clean(args["description"], "description"), "--", profile)
            changed.append("description")
        if "soul" in args:
            soul = _clean(args["soul"], "soul")
            write_checked(env, d / "SOUL.md", soul + "\n", "soul")
            changed.append("soul")
        changed += _apply_model_effort(env, profile, model, effort)
        mcp = args.get("mcp") or {}
        if not isinstance(mcp, dict):
            raise ActionError(400, "mcp must map server names to on or off")
        if mcp:
            path = d / "config.yaml"
            text = _read(path)
            expect = {}
            for server, on in mcp.items():
                if not isinstance(server, str) or not re.match(r"^[A-Za-z0-9_.-]{1,40}$", server) or not isinstance(on, bool):
                    raise ActionError(400, "mcp must map server names to on or off")
                text = set_mcp_enabled(text, server, on)
                expect[f"mcp_servers.{server}.enabled"] = on
            write_checked(env, path, text, "mcp", expect)
            changed.append("mcp")
            need_restart(env, f"MCP servers changed on {profile}")
        if "reportsTo" in args:
            org = set_manager(env, profile, args["reportsTo"])
            save_org(env, org)
            synced = sync_team_skills(env, org)
            save_org(env, org)
            changed.append("lead")
            log_action(env, "agent-moved", profile=profile, reports_to=args["reportsTo"], skills=synced)
        elif "name" in changed or "description" in changed:
            org = load_org(env)                            # the lead's team list shows names and descriptions
            sync_team_skills(env, org)
            save_org(env, org)
        if not changed:
            raise ActionError(400, "Nothing to change")
        log_action(env, "agent-updated", profile=profile, changed=changed,
                   mcp={k: v for k, v in mcp.items()} if mcp else None)
    out = agent_detail(env, profile)
    out["changed"] = changed
    return out


def delete_agent(env: Env, profile: str, args: dict) -> dict:
    if profile not in env.profiles():
        raise ActionError(404, "No such agent")
    if profile == "default":
        raise ActionError(403, f"{crew.name_of(env.hermes_home, 'default')} (the chief) cannot be deleted")
    if args.get("confirm") != profile:
        raise ActionError(400, "Type the agent's profile id to confirm")
    with _lock:
        archive_dir = Path(env.state_dir) / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive = archive_dir / f"{profile}-{stamp()}.tar.gz"
        cli(env, "profile", "export", "-o", str(archive), "--", profile)
        if not archive.exists() or archive.stat().st_size == 0:
            raise ActionError(502, "The export did not produce an archive, so the agent was not deleted")
        os.chmod(archive, 0o600)
        org = load_org(env)
        profiles = env.profiles()
        boss = manager_of(org, profiles, profile) or "default"
        moved = reports_of(org, profiles, profile)
        cli(env, "profile", "delete", "-y", "--", profile)
        for p in moved:                                    # its team moves up to its own lead
            if boss == "default":
                org["reports_to"].pop(p, None)
            else:
                org["reports_to"][p] = boss
        org["reports_to"].pop(profile, None)
        if profile in org["chat_board_added"]:
            org["chat_board_added"].remove(profile)
        if profile in org["pinned"]:
            org["pinned"].remove(profile)
        sync_team_skills(env, org)
        save_org(env, org)
        need_restart(env, f"agent {profile} deleted")
        log_action(env, "agent-deleted", profile=profile, archive=archive.name, team_moved_to=boss, moved=moved)
    return {"ok": True, "archive": str(archive), "movedTo": boss, "moved": moved}


# -- the chief, the board ----------------------------------------------------------------------------------------------------

def brief_instructions(owner: str) -> str:
    return (f"This message is from {owner}, typed in the Crew Command dashboard rather than Telegram. Treat it exactly as a "
            f"message from {owner}. Your reply is shown on the dashboard only: keep it to a few sentences, and if {owner} should "
            "also get something on Telegram, send it there yourself. Hand work to the team through the board as usual.")


def _chief_key(env: Env) -> str:
    for line in _read(Path(env.hermes_home) / ".env").splitlines():
        k, sep, v = line.partition("=")
        if sep and k.removeprefix("export ").strip() == "API_SERVER_KEY":
            return v.strip().strip("'\"")
    raise ActionError(500, "The chief's API key (API_SERVER_KEY in /data/.hermes/.env) is not set")


def _gateway(env: Env, method: str, path: str, body: dict | None = None, headers: dict | None = None) -> dict:
    req = urllib.request.Request(env.gateway_url + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {_chief_key(env)}", "Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise ActionError(502, f"The gateway answered HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ActionError(502, "The gateway is not answering") from None


def brief_chief(env: Env, args: dict) -> dict:
    text = _clean(args.get("text"), "brief")
    run = _gateway(env, "POST", "/v1/runs", {"input": text, "instructions": brief_instructions(crew.owner_name(env.hermes_home)),
                                             "session_id": "hermes-dash"},
                   {"Idempotency-Key": uuid.uuid4().hex})
    run_id = run.get("run_id")
    if not run_id:
        raise ActionError(502, "The gateway did not start a run")
    log_action(env, "chief-briefed", run=run_id, chars=len(text))
    return {"runId": run_id}


def chief_run(env: Env, run_id: str) -> dict:
    if not re.match(r"^[A-Za-z0-9_-]{4,80}$", run_id):
        raise ActionError(400, "That is not a run id")
    run = _gateway(env, "GET", f"/v1/runs/{run_id}")
    output = run.get("output") if run.get("status") == "completed" else None
    return {"status": run.get("status") or "unknown", "output": output}


def create_card(env: Env, args: dict) -> dict:
    title = _clean(args.get("title"), "title")
    body = _clean(args.get("body"), "body", required=False)
    assignee = args.get("assignee")
    priority = args.get("priority", 0)
    if not isinstance(priority, int) or not 0 <= priority <= 100:
        raise ActionError(400, "Priority is a whole number from 0 to 100")
    cmd = ["kanban", "create", "--created-by", "user", "--priority", str(priority), "--json"]
    if assignee:
        if assignee not in env.profiles():
            raise ActionError(400, "No such agent to give the card to")
        cmd += ["--assignee", assignee]
    else:
        cmd += ["--triage"]                              # the chief sorts it on the next look
    if body:
        cmd += ["--body-file", "-"]
    with _lock:
        out = cli(env, *cmd, "--", title, stdin=body or None)
        try:
            card_id = json.loads(out).get("id")
        except ValueError:
            m = re.search(r"\bt_[A-Za-z0-9]+", out)
            card_id = m.group(0) if m else None
        log_action(env, "card-created", card=card_id, assignee=assignee, priority=priority)
    return {"id": card_id}


def answer_card(env: Env, card_id: str, args: dict) -> dict:
    if not TASK_RE.match(card_id):
        raise ActionError(400, "That is not a card id")
    text = _clean(args.get("text"), "answer")
    with _lock:
        cli(env, "kanban", "unblock", f"--reason={crew.owner_name(env.hermes_home)} (dashboard): {text}", "--", card_id)
        log_action(env, "card-answered", card=card_id, chars=len(text))
    return {"ok": True}


# -- the org: who reports to whom (the chief over the specialists; a lead may have its own team) ----------------------------
#
# Kept by the dashboard in org.json (inside /data/.hermes, so a backup has it). Hermes itself has no such idea:
# what makes a lead a lead is (1) a generated `my-team` skill in its profile naming its reports and how to hand them cards,
# and (2) the board tools in its chats (`kanban` in platform_toolsets, which the chief already has). Both are written here,
# whenever the org changes, and taken away again when an agent has nobody left under it.

TEAM_SKILL = Path("skills") / "roles" / "my-team" / "SKILL.md"
GENERATED = "<!-- generated by the Crew Command dashboard"


def org_path(env: Env) -> Path:
    return Path(env.state_dir) / "org.json"


def load_org(env: Env) -> dict:
    try:
        data = json.loads(org_path(env).read_text())
    except (OSError, ValueError):
        data = {}
    return {"reports_to": dict(data.get("reports_to", {})), "chat_board_added": list(data.get("chat_board_added", [])),
            "pinned": list(data.get("pinned", []))}


def save_org(env: Env, org: dict) -> None:
    p = org_path(env)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        shutil.copy2(p, p.with_name("org.json.prev"))
    tmp = p.with_name(".org.json.tmp")
    tmp.write_text(json.dumps({"version": 1, **org}, indent=2))
    os.replace(tmp, p)


def manager_of(org: dict, profiles: list[str], profile: str) -> str | None:
    """The chief ('default') has nobody above; anyone not in the file reports to the chief; a lead that no longer exists means the chief."""
    if profile == "default":
        return None
    boss = org["reports_to"].get(profile, "default")
    return boss if boss in profiles and boss != profile else "default"


def reports_of(org: dict, profiles: list[str], profile: str) -> list[str]:
    return [p for p in profiles if manager_of(org, profiles, p) == profile]


def would_loop(org: dict, profiles: list[str], profile: str, boss: str) -> bool:
    seen = set()
    cur: str | None = boss
    while cur and cur not in seen:
        if cur == profile:
            return True
        seen.add(cur)
        cur = manager_of(org, profiles, cur)
    return False


def set_toolset(text: str, platform: str, toolset: str, on: bool) -> str:
    """Add or remove `toolset` in the block list `platform_toolsets.<platform>` (left alone when that platform is absent)."""
    lines = text.splitlines()
    top = next((i for i, l in enumerate(lines) if l.startswith("platform_toolsets:")), None)
    if top is None:
        return text
    end = next((i for i in range(top + 1, len(lines)) if lines[i] and not lines[i].startswith((" ", "#"))), len(lines))
    head = next((i for i in range(top + 1, end) if re.match(rf"^  {re.escape(platform)}:\s*$", lines[i])), None)
    if head is None:
        return text
    stop = next((i for i in range(head + 1, end) if not re.match(r"^    - ", lines[i])), end)
    items = [lines[i][6:].strip() for i in range(head + 1, stop)]
    if on and toolset not in items:
        lines.insert(stop, f"    - {toolset}")
    elif not on and toolset in items:
        lines = [l for i, l in enumerate(lines) if not (head < i < stop and l[6:].strip() == toolset)]
    return "\n".join(lines) + "\n"


def toolset_items(text: str, platform: str) -> list[str] | None:
    lines = text.splitlines()
    top = next((i for i, l in enumerate(lines) if l.startswith("platform_toolsets:")), None)
    if top is None:
        return None
    head = next((i for i in range(top + 1, len(lines)) if re.match(rf"^  {re.escape(platform)}:\s*$", lines[i])), None)
    if head is None:
        return None
    out = []
    for l in lines[head + 1:]:
        if not re.match(r"^    - ", l):
            break
        out.append(l[6:].strip())
    return out


def _chat_board(env: Env, org: dict, profile: str, on: bool) -> None:
    """A lead gets the board tools in its chats (Telegram, the CLI), as the chief has; taken away only if we added them."""
    if profile == "default":
        return
    path = env.profile_dir(profile) / "config.yaml"
    text = _read(path)
    added = profile in org["chat_board_added"]
    if on and not added:
        new, expect = text, {}
        for platform in ("telegram", "cli"):
            if toolset_items(text, platform) is not None:
                new = set_toolset(new, platform, "kanban", True)
                expect[f"platform_toolsets.{platform}"] = toolset_items(new, platform)
        if new != text:
            write_checked(env, path, new, "lead", expect)
            org["chat_board_added"].append(profile)
    elif not on and added:
        new, expect = text, {}
        for platform in ("telegram", "cli"):
            if toolset_items(text, platform) is not None:
                new = set_toolset(new, platform, "kanban", False)
                expect[f"platform_toolsets.{platform}"] = toolset_items(new, platform)
        if new != text:
            write_checked(env, path, new, "not-lead", expect)
        org["chat_board_added"].remove(profile)


def team_skill(env: Env, org: dict, profiles: list[str], lead: str) -> str:
    me = profile_meta(env, lead)
    owner = crew.owner_name(env.hermes_home)
    name = me.get("display_name") or crew.name_of(env.hermes_home, lead)
    boss = manager_of(org, profiles, lead)
    boss_name = (profile_meta(env, boss).get("display_name") or crew.name_of(env.hermes_home, boss)) if boss else None
    rows = []
    for p in reports_of(org, profiles, lead):
        meta = profile_meta(env, p)
        sub = reports_of(org, profiles, p)
        desc = re.sub(r"\s+", " ", meta.get("description", "")).replace("|", "/")[:300] or "(no description yet)"
        rows.append(f"| {meta.get('display_name') or p} | `{p}` | {desc} | {f'leads {len(sub)}' if sub else '—'} |")
    up = (f" You report to {boss_name} (`{boss}`): send finished work and questions you cannot answer up to them."
          if boss else f" You report to {owner}.")
    when = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""---
name: my-team
description: "The agents who report to you, kept current by the Crew Command dashboard, and how to hand them work on the board. Load before handing off work, before a job with several parts, or when unsure who should do something."
version: 1.0.0
author: Crew Command dashboard
metadata:
  hermes:
    tags: [Roles, Team, Kanban, Delegation]
---
{GENERATED} on {when}; edits here are overwritten. The team is changed through the dashboard. -->

# Your team

You are {name} (`{lead}`) and you lead {len(rows)} agent{'s' if len(rows) != 1 else ''}.{up} This list is the current one: where
another skill names a different team, this one wins.

| Agent | Profile id | What they do | Their own team |
|---|---|---|---|
{chr(10).join(rows)}

## Handing them work

1. Call `kanban_create` with `assignee` set to their profile id. They start with a blank conversation and see only the
   card, so write the body as a full brief: **Goal** (one or two lines), **Facts** (only what the job needs), **Output**
   (what to return, how long), **Limits** (anything {owner} ruled out, and "stop before any submit, booking or message").
2. A job with several parts: one card per agent; if one part needs another's result, pass `parents` so it waits.
3. A blocked card carries a question. Answer it yourself if you can (`kanban_comment`, then `kanban_unblock`); if only
   {owner} or your own lead can answer, block your own card with the question so it goes up.
4. Check each result (spot-check facts, prices, links) and report the combined answer, not the raw parts.
5. Anything that sends, buys, books, submits or deletes still needs {owner}'s yes first.
"""


def sync_team_skills(env: Env, org: dict) -> list[str]:
    """Write `my-team` for every agent with reports (the chief included); remove ours from agents with none. Returns who changed."""
    profiles = env.profiles()
    changed = []
    for p in profiles:
        path = env.profile_dir(p) / TEAM_SKILL
        reports = reports_of(org, profiles, p)
        ours = path.exists() and GENERATED in _read(path)
        if reports:
            if path.exists() and not ours:
                continue                                   # a hand-written my-team: never overwrite it
            text = team_skill(env, org, profiles, p)
            old = _read(path)
            # compare without the timestamp line, so an unchanged team does not churn the skill snapshot
            if re.sub(r"(?m)^<!-- generated.*$", "", old) != re.sub(r"(?m)^<!-- generated.*$", "", text):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                changed.append(p)
            if p not in org["pinned"]:
                # Hermes' background skill curator must not merge or archive a generated list (CONFIG.md: role skills pinned).
                try:
                    cli(env, *([] if p == "default" else ["-p", p]), "curator", "pin", "my-team")
                    org["pinned"].append(p)
                except ActionError as exc:
                    log_action(env, "pin-failed", profile=p, error=str(exc)[:200])
            _chat_board(env, org, p, True)
        else:
            if ours:
                if p in org["pinned"]:
                    try:
                        cli(env, *([] if p == "default" else ["-p", p]), "curator", "unpin", "my-team")
                    except ActionError:
                        pass
                    org["pinned"].remove(p)
                path.unlink()
                try:
                    path.parent.rmdir()
                except OSError:
                    pass
                changed.append(p)
            _chat_board(env, org, p, False)
    return changed


def set_manager(env: Env, profile: str, boss: Any, org: dict | None = None) -> dict:
    """Move `profile` under `boss`. Refuses the chief, unknown agents and loops."""
    profiles = env.profiles()
    if profile == "default":
        raise ActionError(400, f"The chief leads everyone and reports to {crew.owner_name(env.hermes_home)}")
    if not isinstance(boss, str) or boss not in profiles:
        raise ActionError(400, "Pick an existing agent as the lead")
    org = org or load_org(env)
    if boss == profile or would_loop(org, profiles, profile, boss):
        raise ActionError(400, "That would put an agent under one of its own team")
    if boss == "default":
        org["reports_to"].pop(profile, None)
    else:
        org["reports_to"][profile] = boss
    return org
