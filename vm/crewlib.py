"""The installer's Python half: turns /data/.hermes/crew.json (the owner's answers) into each agent's files.

Run with Hermes's own Python (it has PyYAML):  /opt/hermes/hermes-agent/venv/bin/python /opt/agent-automation/vm/crewlib.py <command>
Commands:
  configs        write the four config.yaml files (our settings merged over what is there; nothing else of theirs is lost)
  souls          write each SOUL.md and the seed USER.md, only where none exists yet (yours to edit afterwards)
  skills         copy the kit's skills into the right profiles (ours: replaced on every run)
  workspace      house rules for /data/workspace, the owner's notebook folder
  briefing       print the morning briefing prompt (for `hermes cron create`)
  env-set FILE KEY      set KEY in an .env file to the value read from stdin (never from the command line)
  env-has FILE KEY      exit 0 when KEY has a value in FILE
  check-names    validate crew.json (names, ids) and print what is wrong
Everything here is idempotent: running it twice changes nothing the second time.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - only outside Hermes's venv
    yaml = None

KIT = Path(__file__).resolve().parent
HOME = Path(os.environ.get("HERMES_HOME", "/data/.hermes"))
CREW_JSON = Path(os.environ.get("CREW_JSON", str(HOME / "crew.json")))
WORKSPACE = Path(os.environ.get("CREW_WORKSPACE", "/data/workspace"))
ROLES = ("chief", "tutor", "assistant", "coach")
PROFILE = {"chief": "default", "tutor": "tutor", "assistant": "assistant", "coach": "coach"}
ROLE_SKILL = {"chief": "team-lead", "tutor": "tutor", "assistant": "assistant", "coach": "coach"}
ID_RX = re.compile(r"^[a-z][a-z0-9]{0,23}$")
NAME_RX = re.compile(r"^[A-Za-z][A-Za-z0-9 '\-]{0,23}$")
RESERVED_IDS = {"default", "user", "worker", "dashboard", "all", "none", "test", "helper", "owner",
                "tutor", "assistant", "coach", "chief"}


def load_crew() -> dict:
    return json.loads(CREW_JSON.read_text())


def home_of(profile: str) -> Path:
    return HOME if profile == "default" else HOME / "profiles" / profile


def agent(crew: dict, role: str) -> dict:
    for a in crew.get("agents", []):
        if a.get("role") == role:
            return a
    raise KeyError(f"no agent with role {role} in crew.json")


def placeholders(crew: dict) -> dict:
    o = crew.get("owner", {})
    return {
        "{{OWNER}}": o.get("name", "the owner"),
        "{{PRONOUNS}}": o.get("pronouns", "they/them"),
        "{{CHIEF}}": agent(crew, "chief")["name"],
        "{{TUTOR}}": agent(crew, "tutor")["name"],
        "{{ASSISTANT}}": agent(crew, "assistant")["name"],
        "{{COACH}}": agent(crew, "coach")["name"],
        "{{TIMEZONE}}": crew.get("timezone", "UTC"),
        "{{HOME_PLACE}}": (crew.get("home") or {}).get("name") or "not given",
        "{{STUDIES}}": crew.get("studies") or "not given",
    }


def render(text: str, crew: dict) -> str:
    for k, v in placeholders(crew).items():
        text = text.replace(k, v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", text)
    if left:
        raise ValueError(f"unknown placeholder(s) {sorted(set(left))}")
    return text


def check_names(crew: dict) -> list[str]:
    """What is wrong with crew.json, as sentences ([] = fine)."""
    bad: list[str] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for role in ROLES:
        try:
            a = agent(crew, role)
        except KeyError as e:
            bad.append(str(e))
            continue
        if not NAME_RX.match(a.get("name", "")):
            bad.append(f"{role}: name {a.get('name')!r} must start with a letter and use letters, digits, spaces, ' or - (24 at most)")
        if not ID_RX.match(a.get("id", "")) or a.get("id") in RESERVED_IDS:
            bad.append(f"{role}: id {a.get('id')!r} must be lowercase letters and digits and not a reserved word")
        if a.get("id") in seen_ids:
            bad.append(f"two agents share the id {a.get('id')!r}")
        if a.get("name", "").lower() in seen_names:
            bad.append(f"two agents share the name {a.get('name')!r}")
        seen_ids.add(a.get("id", ""))
        seen_names.add(a.get("name", "").lower())
        if a.get("profile") != PROFILE[role]:
            bad.append(f"{role}: profile must be {PROFILE[role]!r}")
    o = crew.get("owner", {})
    if not NAME_RX.match(o.get("name", "")):
        bad.append("owner name must start with a letter (letters, digits, spaces, ' or -)")
    if not ID_RX.match(o.get("id", "")):
        bad.append("owner id must be lowercase letters and digits")
    if not str(crew.get("telegram_user_id", "")).isdigit():
        bad.append("telegram_user_id is missing")
    return bad


# -- config.yaml ---------------------------------------------------------------------------------------------------------------------

def overlay(crew: dict, role: str) -> dict:
    """The settings this kit owns in one agent's config.yaml (the rest stays Hermes's defaults or the owner's own changes)."""
    owner = crew["owner"]["name"]
    tg = str(crew["telegram_user_id"])
    names = ", ".join([owner] + [agent(crew, r)["name"] for r in ROLES])
    feats = crew.get("features", {})
    plugins = ["live-time"] + (["openalex"] if role == "tutor" else []) + (["crew-voice"] if feats.get("voice") else [])
    o: dict = {
        "model": {"default": "deepseek-flash", "provider": "deepseek", "supports_vision": True},
        "providers": {"deepseek": {"stale_timeout_seconds": 60}},
        "fallback_providers": [{"provider": "gemini", "model": "gemini-3.8-flash"}] if crew.get("has_gemini") else [],
        "model_catalog": {"excluded_providers": ["copilot", "github-copilot", "copilot-acp"]},
        "agent": {"api_max_retries": 1, "reasoning_effort": "medium"},
        "terminal": {"cwd": str(WORKSPACE), "env_passthrough": []},
        "browser": {"backend": "off", "inactivity_timeout": 600},
        "display": {
            "personality": {"chief": "concise", "tutor": "teacher", "assistant": "concise", "coach": "concise"}[role],
            "platforms": {"telegram": {"tool_progress": "off", "show_reasoning": False,
                                       "interim_assistant_messages": False, "cleanup_progress": True}},
        },
        "stt": {"enabled": True, "provider": "local", "language": "en",
                "local": {"model": "small", "language": "en", "initial_prompt": names + ".",
                          "unload_after_idle_seconds": 300}},
        "memory": {"provider": "mem0", "allow_unattended_consolidation": True},
        "delegation": {"max_iterations": 40, "max_concurrent_children": 3, "max_spawn_depth": 1, "orchestrator_enabled": False},
        "skills": {"auto_load": [ROLE_SKILL[role]]},
        "plugins": {"enabled": plugins},
        "cron": {"wrap_response": True, "wrapper_show_job_id": False, "wrapper_footer": "", "wrapper_header": "⏰ Reminder"},
        "telemetry": {"shared_metrics": {"enabled": False, "send": False}},
        "updates": {"check": False},
        "platforms": {"telegram": {"enabled": True,
                                   "home_channel": {"platform": "telegram", "chat_id": tg, "name": owner, "user_id": tg}}},
    }
    if role == "chief":
        o["platform_toolsets"] = {"cli": ["hermes-cli", "kanban"], "telegram": ["hermes-telegram", "kanban"]}
        o["kanban"] = {"max_in_progress": 2, "auto_decompose": False, "max_in_progress_per_profile": 1}
        o["gateway"] = {"multiplex_profiles": True}
    if role in ("tutor", "assistant") and (feats.get("moodle") or crew.get("moodle_url")):
        # Read-only Moodle tools (moodle-cli's MCP server; `submit` is never in the list). The cookie is ${MOODLE_TOKEN} from this
        # profile's own .env, so it never reaches the other agents' shells.
        o["mcp_servers"] = {"moodle": {
            "command": "/data/tools/moodle/node_modules/.bin/moodle", "args": ["--no-cache", "mcp", "serve"],
            "env": {"MOODLE_BASE_URL": crew.get("moodle_url", ""), "MOODLE_NO_UPDATE_CHECK": "1", "HOME": "/data",
                    "MOODLE_TOKEN": "${MOODLE_TOKEN}"},
            "tools": {"include": ["home", "due", "units", "unit", "find", "item", "grades", "news", "thread",
                                  "search_forums", "file", "attempt"]},
            "connect_timeout": 60, "enabled": bool(feats.get("moodle"))}}
        if feats.get("moodle"):
            o["terminal"]["env_passthrough"] = ["MOODLE_TOKEN", "MOODLE_BASE_URL"]
    if feats.get("voice"):
        voice = (crew.get("voices") or {}).get(role, "")
        o["tts"] = {"provider": "crew-voice", "voice": voice, "model": "eleven_v4"}
    return o


def merge(base: dict, ours: dict) -> dict:
    """Deep-merge `ours` over `base`: our keys win, theirs stay. Lists are ours, except plugins.enabled which keeps theirs too."""
    out = copy.deepcopy(base)
    for k, v in ours.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def write_config(crew: dict, role: str) -> bool:
    path = home_of(PROFILE[role]) / "config.yaml"
    old = yaml.safe_load(path.read_text()) if path.exists() else {}
    old = old or {}
    ours = overlay(crew, role)
    theirs_plugins = [p for p in ((old.get("plugins") or {}).get("enabled") or []) if p not in ours["plugins"]["enabled"]]
    if not crew.get("features", {}).get("voice"):
        theirs_plugins = [p for p in theirs_plugins if p != "crew-voice"]
        if (old.get("tts") or {}).get("provider") == "crew-voice":
            old.pop("tts", None)
    new = merge(old, ours)
    new["plugins"]["enabled"] = ours["plugins"]["enabled"] + theirs_plugins
    if not new.get("fallback_providers"):
        new.pop("fallback_providers", None)
    new.setdefault("_config_version", old.get("_config_version", 46))
    if new == old:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name("config.yaml.bak-before-crew"))
    tmp = path.with_name(".config.yaml.new")
    tmp.write_text("# Written by agent-automation (vm/crewlib.py). Your own changes to other settings are kept on updates.\n"
                   + yaml.safe_dump(new, sort_keys=False, allow_unicode=True))
    os.replace(tmp, path)
    return True


# -- files ---------------------------------------------------------------------------------------------------------------------------

def write_souls(crew: dict) -> list[str]:
    done = []
    for role in ROLES:
        h = home_of(PROFILE[role])
        soul = h / "SOUL.md"
        text = render((KIT / "agents" / "souls" / f"{role}.md").read_text(), crew)
        marker = h / ".crew-soul-template"
        # Replace Hermes's stock SOUL.md, or ours if it was never edited; never an owner's own edits.
        if not soul.exists() or not marker.exists() or soul.read_text() == marker.read_text():
            if not soul.exists() or soul.read_text() != text:
                soul.write_text(text)
                done.append(str(soul))
            marker.write_text(text)
        user_md = h / "memories" / "USER.md"
        if not user_md.exists() or not user_md.read_text().strip():
            user_md.parent.mkdir(parents=True, exist_ok=True)
            user_md.write_text(render((KIT / "agents" / "USER.md").read_text(), crew))
            done.append(str(user_md))
    return done


def copy_tree(src: Path, dst: Path, crew: dict) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for f in src.rglob("*"):
        if f.is_dir():
            continue
        t = dst / f.relative_to(src)
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(render(f.read_text(), crew)) if f.suffix == ".md" else shutil.copy2(f, t)


def write_skills(crew: dict) -> list[str]:
    s = KIT / "agents" / "skills"
    feats = crew.get("features", {})
    done = []
    for role in ROLES:
        h = home_of(PROFILE[role]) / "skills"
        copy_tree(s / "roles" / ROLE_SKILL[role], h / "roles" / ROLE_SKILL[role], crew)
        done.append(f"{PROFILE[role]}: {ROLE_SKILL[role]}")
        if role in ("chief", "assistant", "coach"):
            copy_tree(s / "productivity" / "weather-forecast", h / "productivity" / "weather-forecast", crew)
        gmail = h / "email" / "gmail-reader"
        if role in ("chief", "assistant") and feats.get("gmail"):
            copy_tree(s / "email" / "gmail-reader", gmail, crew)
        elif gmail.exists():
            shutil.rmtree(gmail)
    return done


def write_workspace(crew: dict) -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "AGENTS.md").write_text(render((KIT / "agents" / "AGENTS.md").read_text(), crew))
    for d in (HOME / "owner", HOME / "owner" / "study", HOME / "owner" / ".secrets"):
        d.mkdir(parents=True, exist_ok=True)
    os.chmod(HOME / "owner" / ".secrets", 0o700)
    for name in ("tasks.md", "admin.md", "health.md", "timetable.md"):
        f = HOME / "owner" / name
        if not f.exists():
            f.write_text(f"# {name[:-3].title()}\n")


# -- .env ----------------------------------------------------------------------------------------------------------------------------

def env_set(path: Path, key: str, value: str) -> None:
    """Set KEY=value in an .env file (mode 600), replacing any old line, through a temp file. The value is never printed."""
    if not re.match(r"^[A-Z][A-Z0-9_]*$", key):
        raise ValueError("bad key name")
    if "\n" in value or "\r" in value:
        raise ValueError("the value has a line break")
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [l for l in lines if not re.match(rf"^\s*(export\s+)?{key}=", l)]
    lines.append(f"{key}={value}")
    tmp = path.with_name(f".{path.name}.new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def env_has(path: Path, key: str) -> bool:
    if not path.exists():
        return False
    for l in path.read_text().splitlines():
        m = re.match(rf"^\s*(export\s+)?{key}=(.*)$", l)
        if m and m.group(2).strip().strip("'\""):
            return True
    return False


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "env-set":
        env_set(Path(argv[1]), argv[2], sys.stdin.readline().rstrip("\n"))
        return 0
    if cmd == "env-has":
        return 0 if env_has(Path(argv[1]), argv[2]) else 1
    crew = load_crew()
    if cmd == "check-names":
        bad = check_names(crew)
        print("\n".join(bad))
        return 1 if bad else 0
    if cmd == "configs":
        for role in ROLES:
            print(f"{PROFILE[role]}: {'updated' if write_config(crew, role) else 'unchanged'}")
    elif cmd == "souls":
        for f in write_souls(crew):
            print("wrote", f)
    elif cmd == "skills":
        for f in write_skills(crew):
            print("skills", f)
    elif cmd == "workspace":
        write_workspace(crew)
    elif cmd == "briefing":
        print(render((KIT / "agents" / "morning-briefing.md").read_text(), crew).strip())
    else:
        print(f"unknown command {cmd}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
