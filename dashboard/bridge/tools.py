"""Skills and MCP servers per agent, the parts that need no internet. Searching the skills hub and
installing from it are network jobs (jobs.py). Same rules as actions.py: Hermes' own CLI or a checked text edit with a
backup, one write at a time, logged; no secret value ever comes back to the page.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import team
from actions import ActionError, Env, _lock, _read, backup, cli, log_action, need_restart, set_env_value, stamp, write_checked

SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,47}$")
SERVER_RE = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")
ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
COMMAND_RE = re.compile(r"^[A-Za-z0-9._/+-]{1,200}$")
URL_RE = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?(/[^\s]*)?$")
REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
CUSTOM = "custom"


def _profile(env: Env, profile: str) -> str:
    profile = team.profile_of(env.hermes_home, profile)
    if profile not in env.profiles():
        raise ActionError(404, "No such agent")
    return profile


def yaml_get(env: Env, path: Path, *keys: str) -> dict[str, Any]:
    """Dotted keys of a YAML file as JSON, parsed by Hermes' own Python (its PyYAML)."""
    probe = ("import json, sys, yaml\n"
             "try:\n    d = yaml.safe_load(open(sys.argv[1])) or {}\nexcept FileNotFoundError:\n    d = {}\n"
             "out = {}\n"
             "for k in json.loads(sys.argv[2]):\n"
             "    v = d\n"
             "    for part in k.split('.'):\n"
             "        v = v.get(part) if isinstance(v, dict) else None\n"
             "    out[k] = v\n"
             "print(json.dumps(out, default=str))\n")
    try:
        res = subprocess.run([env.hermes_python, "-I", "-c", probe, str(path), json.dumps(list(keys))],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise ActionError(500, "Hermes' Python did not run") from None
    if res.returncode != 0:
        raise ActionError(500, f"{path.name} would not parse")
    return json.loads(res.stdout or "{}")


def _block_bounds(lines: list[str], block: str) -> tuple[int, int] | None:
    start = next((i for i, l in enumerate(lines) if re.match(rf"^{re.escape(block)}:\s*(\{{\s*\}})?\s*(#.*)?$", l)), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i].startswith((" ", "#"))), len(lines))
    return start, end


def set_block_flow(text: str, block: str, key: str, value: Any) -> str:
    """`  key: <value as JSON>` inside a top-level block, replacing the key's old value and any lines nested under it."""
    lines = text.splitlines()
    flow = f"  {key}: {json.dumps(value, ensure_ascii=False)}"
    b = _block_bounds(lines, block)
    if b is None:
        return text.rstrip("\n") + f"\n{block}:\n{flow}\n"
    start, end = b
    lines[start] = f"{block}:"                                 # `block: {}` becomes a real block
    k = next((i for i in range(start + 1, end) if re.match(rf"^  {re.escape(key)}:(\s|$)", lines[i])), None)
    if k is None:
        lines.insert(start + 1, flow)
    else:
        stop = next((i for i in range(k + 1, end) if lines[i].strip() and not lines[i].startswith(("   ", "  -", "\t"))
                     and not lines[i].lstrip().startswith("#")), end)
        lines[k:stop] = [flow]
    return "\n".join(lines) + "\n"


def drop_block_key(text: str, block: str, key: str) -> str:
    lines = text.splitlines()
    b = _block_bounds(lines, block)
    if b is None:
        return text
    start, end = b
    k = next((i for i in range(start + 1, end) if re.match(rf"^  {re.escape(key)}:(\s|$)", lines[i])), None)
    if k is None:
        return text
    stop = next((i for i in range(k + 1, end) if re.match(r"^  \S", lines[i])), end)
    del lines[k:stop]
    return "\n".join(lines) + "\n"


# -- skills ------------------------------------------------------------------------------------------------------------------

def _frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    out: dict[str, str] = {}
    for line in (m.group(1).splitlines() if m else []):
        k, sep, v = line.partition(":")
        if sep and k.strip() in ("name", "description") and not line.startswith(" "):
            out[k.strip()] = v.strip().strip("'\"")
    return out


def list_skills(env: Env, profile: str) -> dict:
    profile = _profile(env, profile)
    root = env.profile_dir(profile) / "skills"
    try:
        hub = json.loads(_read(root / ".hub" / "lock.json") or "{}").get("installed", {})
    except ValueError:
        hub = {}
    bundled = {l.split(":", 1)[0] for l in _read(root / ".bundled_manifest").splitlines() if l.strip()}
    disabled = set(yaml_get(env, env.profile_dir(profile) / "config.yaml", "skills.disabled").get("skills.disabled") or [])
    out, seen = [], set()
    for path in sorted(root.glob("*/SKILL.md")) + sorted(root.glob("*/*/SKILL.md")):
        rel = path.parent.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if len(rel.parts) > 1 and (root / rel.parts[0] / "SKILL.md").exists():
            continue                                       # a file inside another skill's folder, not a skill of its own
        text = _read(path)
        fm = _frontmatter(text)
        name = fm.get("name") or path.parent.name
        if name in seen:
            continue
        seen.add(name)
        h = hub.get(name) or {}
        source = ("dashboard" if "<!-- generated by the Hermes Command dashboard" in text else
                  "hub" if name in hub and h.get("source") not in ("official", "builtin") else
                  "builtin" if name in bundled or h.get("source") in ("official", "builtin") else "local")
        out.append({"name": name, "category": rel.parts[0] if len(rel.parts) > 1 else "", "description": fm.get("description", "")[:300],
                    "source": source, "identifier": h.get("identifier"), "enabled": name not in disabled})
    return {"profile": profile, "skills": out}


def set_skill_enabled(env: Env, profile: str, name: str, on: bool) -> dict:
    profile = _profile(env, profile)
    if not SKILL_RE.match(name):
        raise ActionError(400, "Not a skill name")
    path = env.profile_dir(profile) / "config.yaml"
    with _lock:
        disabled = set(yaml_get(env, path, "skills.disabled").get("skills.disabled") or [])
        disabled = disabled - {name} if on else disabled | {name}
        want = sorted(disabled)
        write_checked(env, path, set_block_flow(_read(path), "skills", "disabled", want), "skills", {"skills.disabled": want})
        log_action(env, "skill-enabled" if on else "skill-disabled", profile=profile, skill=name)
    return list_skills(env, profile)


def remove_skill(env: Env, profile: str, name: str) -> dict:
    """A hub skill goes through `hermes skills uninstall`; one written here or by hand is archived, then removed.
    Hermes' own (bundled) skills are switched off instead: an update would put them back."""
    profile = _profile(env, profile)
    found = next((s for s in list_skills(env, profile)["skills"] if s["name"] == name), None)
    if not found:
        raise ActionError(404, "No such skill on this agent")
    if found["source"] in ("builtin", "dashboard"):
        raise ActionError(400, "Switch it off instead (Hermes' own skills come back with updates; the team list is managed)")
    with _lock:
        if found["source"] == "hub":
            cli(env, *([] if profile == "default" else ["-p", profile]), "skills", "uninstall", "--yes", "--", name)
        else:
            src = env.profile_dir(profile) / "skills" / found["category"] / name if found["category"] else env.profile_dir(profile) / "skills" / name
            dest = Path(env.state_dir) / "archive" / "skills" / f"{profile}-{name}-{stamp()}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dest)
            shutil.rmtree(src)
        log_action(env, "skill-removed", profile=profile, skill=name, source=found["source"])
    return list_skills(env, profile)


def create_skill(env: Env, profile: str, args: dict) -> dict:
    """A skill the owner writes: skills/custom/<name>/SKILL.md. Hermes picks it up in new chats."""
    profile = _profile(env, profile)
    name = args.get("name")
    desc = args.get("description")
    body = args.get("body")
    if not isinstance(name, str) or not SKILL_RE.match(name):
        raise ActionError(400, "Name: lower case letters, digits and dashes")
    if not isinstance(desc, str) or not desc.strip() or len(desc) > 300 or "\n" in desc.strip():
        raise ActionError(400, "Describe when to use it in one line (up to 300 characters)")
    if not isinstance(body, str) or not body.strip() or len(body) > 20_000:
        raise ActionError(400, "Write the steps (up to 20,000 characters)")
    if any(s["name"] == name for s in list_skills(env, profile)["skills"]):
        raise ActionError(409, "This agent already has a skill with that name")
    d = env.profile_dir(profile) / "skills" / CUSTOM / name
    with _lock:
        d.mkdir(parents=True, exist_ok=False)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {json.dumps(desc.strip(), ensure_ascii=False)}\n---\n\n"
                                    f"{body.strip()}\n")
        log_action(env, "skill-created", profile=profile, skill=name)
    return list_skills(env, profile)


# -- MCP servers -------------------------------------------------------------------------------------------------------------

def _servers(env: Env, profile: str) -> dict[str, dict]:
    got = yaml_get(env, env.profile_dir(profile) / "config.yaml", "mcp_servers").get("mcp_servers")
    return got if isinstance(got, dict) else {}


def _describe(name: str, cfg: dict) -> dict:
    """What the page may see of a server: its kind and address, the names (never values) of its env vars and headers."""
    url = cfg.get("url")
    return {"name": name, "enabled": cfg.get("enabled", True) is not False,
            "transport": "http" if url else "stdio",
            "address": (re.sub(r"[?#].*$", "", str(url)) if url else f"{cfg.get('command', '')} {' '.join(map(str, (cfg.get('args') or [])[:3]))}".strip())[:160],
            "auth": cfg.get("auth") or ("headers" if cfg.get("headers") else None),
            "env": sorted((cfg.get("env") or {}).keys()) if isinstance(cfg.get("env"), dict) else [],
            "tools": len(((cfg.get("tools") or {}).get("include") or [])) if isinstance(cfg.get("tools"), dict) else 0}


def list_servers(env: Env) -> dict:
    """Every server any agent has, and who has it: the matrix in Agent Studio."""
    out: dict[str, dict] = {}
    for p in env.profiles():
        for name, cfg in _servers(env, p).items():
            if not isinstance(cfg, dict):
                continue
            row = out.setdefault(name, {**_describe(name, cfg), "agents": {}})
            row["agents"][p] = cfg.get("enabled", True) is not False
    return {"servers": sorted(out.values(), key=lambda r: r["name"])}


CATALOG_PROBE = """
import json, sys
sys.path.insert(0, sys.argv[1])
from hermes_cli import mcp_catalog as c
out = []
for e in c.list_catalog():
    try:
        cfg = None if e.install else c._build_server_config(e, None)
    except Exception:
        cfg = None
    out.append({"name": e.name, "description": e.description, "transport": e.transport.type, "auth": e.auth.type,
                "url": e.transport.url, "needsInstall": bool(e.install), "postInstall": (e.post_install or "").strip()[:600],
                "env": [{"name": v.name, "prompt": v.prompt, "secret": v.secret, "required": v.required} for v in e.auth.env],
                "config": cfg})
print(json.dumps(out))
"""
_catalog: dict[str, Any] = {"at": 0.0, "data": None}


def catalog(env: Env) -> list[dict]:
    """Hermes' catalog of Nous-approved MCP servers (shipped with the pinned release, so no network)."""
    if _catalog["data"] is not None and time.time() - _catalog["at"] < 3600:
        return _catalog["data"]
    try:
        repo = str(Path(env.hermes_python).parent.parent.parent)      # /opt/hermes/hermes-agent
        res = subprocess.run([env.hermes_python, "-I", "-c", CATALOG_PROBE, repo], capture_output=True, text=True, timeout=60,
                             cwd=repo, env={"HERMES_HOME": env.hermes_home, "HOME": "/home/hermes", "PATH": "/usr/bin:/bin"})
        data = json.loads(res.stdout) if res.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired, ValueError):
        data = []
    _catalog.update(at=time.time(), data=data)
    return data


def _env_var_for(server: str, key: str) -> str:
    return re.sub(r"[^A-Z0-9_]", "_", f"MCP_{server.upper()}_{key.upper()}")[:64]


def _custom_config(args: dict, secrets: dict[str, str]) -> dict:
    name = args["name"]
    kind = args.get("transport")
    cfg: dict[str, Any] = {}
    if kind == "http":
        url = args.get("url")
        if not isinstance(url, str) or not URL_RE.match(url) or len(url) > 400:
            raise ActionError(400, "The address must be an http(s) URL")
        cfg["url"] = url
        headers = {}
        for h in args.get("headers") or []:
            k, v = h.get("name"), h.get("value")
            if not isinstance(k, str) or not re.match(r"^[A-Za-z0-9-]{1,60}$", k) or not isinstance(v, str) or not v or len(v) > 2000:
                raise ActionError(400, "Each header needs a name and a value")
            if h.get("secret"):
                var = _env_var_for(name, k)
                secrets[var] = v
                headers[k] = f"${{{var}}}"
            else:
                headers[k] = v
        if headers:
            cfg["headers"] = headers
        if args.get("oauth"):
            cfg["auth"] = "oauth"
    elif kind == "stdio":
        command = args.get("command")
        if not isinstance(command, str) or not COMMAND_RE.match(command):
            raise ActionError(400, "The command is one program name or path (arguments go below)")
        cfg["command"] = command
        a = args.get("args") or []
        if not isinstance(a, list) or len(a) > 30 or not all(isinstance(x, str) and len(x) <= 300 for x in a):
            raise ActionError(400, "Arguments: up to 30, each up to 300 characters")
        if a:
            cfg["args"] = a
        envs = {}
        for e in args.get("env") or []:
            k, v = e.get("name"), e.get("value")
            if not isinstance(k, str) or not ENV_KEY_RE.match(k) or not isinstance(v, str) or len(v) > 2000:
                raise ActionError(400, "Each variable needs an UPPER_CASE name and a value")
            if e.get("secret"):
                var = _env_var_for(name, k)
                secrets[var] = v
                envs[k] = f"${{{var}}}"
            else:
                envs[k] = v
        if envs:
            cfg["env"] = envs
    else:
        raise ActionError(400, "Pick a web address (http) or a program (stdio)")
    return cfg


def add_server(env: Env, args: dict) -> dict:
    """One server onto one or more agents: from Hermes' catalog, typed in, or copied from an agent that has it."""
    name = args.get("name")
    if not isinstance(name, str) or not SERVER_RE.match(name):
        raise ActionError(400, "Name: lower case letters, digits, - and _")
    targets = args.get("profiles")
    if not isinstance(targets, list) or not targets or len(targets) > 50:
        raise ActionError(400, "Pick at least one agent")
    targets = [_profile(env, str(t)) for t in targets]
    secrets: dict[str, str] = {}
    copy_env: dict[str, str] = {}
    source = args.get("source")
    if source == "catalog":
        entry = next((e for e in catalog(env) if e["name"] == args.get("entry")), None)
        if not entry:
            raise ActionError(404, "Not in Hermes' catalog")
        if entry["needsInstall"] or not entry["config"]:
            raise ActionError(400, f"{entry['name']} has to be installed on the VM: hermes -p <agent> mcp install {entry['name']}")
        cfg = dict(entry["config"])
        given = args.get("secrets") or {}
        for spec in entry["env"]:
            v = given.get(spec["name"]) if isinstance(given, dict) else None
            if isinstance(v, str) and v.strip():
                if len(v) > 2000:
                    raise ActionError(400, f"{spec['name']} is too long")
                secrets[spec["name"]] = v.strip()
            elif spec["required"]:
                raise ActionError(400, f"{spec['prompt'] or spec['name']} is needed")
    elif source == "custom":
        cfg = _custom_config({**args, "name": name}, secrets)
    elif source == "copy":
        frm = _profile(env, str(args.get("from") or ""))
        cfg = _servers(env, frm).get(args.get("entry") or name)
        if not isinstance(cfg, dict):
            raise ActionError(404, "That agent does not have this server")
        cfg = {k: v for k, v in cfg.items() if k != "enabled"}
        src_env = {**_env_pairs(_read(Path(env.hermes_home) / ".env")), **_env_pairs(_read(env.profile_dir(frm) / ".env"))}
        for var in set(REF_RE.findall(json.dumps(cfg))):
            if var in src_env:
                copy_env[var] = src_env[var]          # copied server-side; the value never reaches the page
    else:
        raise ActionError(400, "From the catalog, typed in, or copied from another agent")
    cfg["enabled"] = True
    done = []
    with _lock:
        for p in targets:
            if name in _servers(env, p):
                continue
            d = env.profile_dir(p)
            cpath = d / "config.yaml"
            values = {**copy_env, **secrets}
            if values:
                epath = d / ".env"
                text = _read(epath)
                have = _env_pairs(text)
                for k, v in values.items():
                    if have.get(k) != v:
                        text = set_env_value(text, k, v)
                backup(epath, f"mcp-{name}")
                epath.write_text(text)
                epath.chmod(0o600)
            write_checked(env, cpath, set_block_flow(_read(cpath), "mcp_servers", name, cfg), f"mcp-{name}", {f"mcp_servers.{name}": cfg})
            done.append(p)
        if done:
            need_restart(env, f"MCP server {name} added to {', '.join(done)}")
        log_action(env, "mcp-added", server=name, source=source, profiles=done, secrets=sorted(secrets))
    note = None
    if cfg.get("auth") == "oauth":
        note = f"{name} signs in with your account once: on the VM, hermes -p <agent> mcp login {name} (after the restart)."
    elif source == "catalog":
        note = next((e["postInstall"] for e in catalog(env) if e["name"] == name), None) or None
    return {"added": done, "skipped": [p for p in targets if p not in done], "note": note, **list_servers(env)}


def _env_pairs(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and not k.startswith("#"):
            out[k.removeprefix("export ").strip()] = v.strip()
    return out


def remove_server(env: Env, profile: str, name: str) -> dict:
    profile = _profile(env, profile)
    if not SERVER_RE.match(name or ""):
        raise ActionError(400, "Not a server name")
    path = env.profile_dir(profile) / "config.yaml"
    with _lock:
        if name not in _servers(env, profile):
            raise ActionError(404, "This agent does not have that server")
        write_checked(env, path, drop_block_key(_read(path), "mcp_servers", name), f"mcp-remove-{name}", {f"mcp_servers.{name}": None})
        need_restart(env, f"MCP server {name} removed from {profile}")
        log_action(env, "mcp-removed", profile=profile, server=name)
    return list_servers(env)
