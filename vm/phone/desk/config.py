"""Desk settings: non-secret ones from config.json, secrets from secrets.env and the Hermes .env files.

Secrets are fields with repr=False, are never written back to config.json and never logged.
"""
from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

# What {{OWNER}} says -> (Hermes profile id, display name). {{CHIEF}} is the default profile.
AGENTS = {
    "tutor": ("tutor", "{{TUTOR}}"),
    "assistant": ("assistant", "{{ASSISTANT}}"),
    "coach": ("coach", "{{COACH}}"),
    "chief": ("default", "{{CHIEF}}"),
}
DISPLAY = {profile: name for profile, name in AGENTS.values()}
NAMED_PROFILES = ("tutor", "assistant", "coach")


def read_env_file(path: str | Path) -> dict[str, str]:
    """KEY=VALUE lines of an .env file (quotes stripped, comments ignored); {} when unreadable."""
    values: dict[str, str] = {}
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return values
    for line in lines:
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if match and not line.lstrip().startswith("#"):
            values[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return values


@dataclasses.dataclass
class Config:
    state_dir: str = "/data/.hermes/voice-desk"
    hermes_home: str = "/data/.hermes"
    port: int = 8800
    hermes_base: str = "http://127.0.0.1:8642"
    hermes_bin: str = "/home/hermes/.local/bin/hermes"
    max_number: str = dataclasses.field(default="", repr=False)
    agent_id: str = ""
    phone_number_id: str = ""
    twilio_number: str = dataclasses.field(default="", repr=False)
    twilio_number_sid: str = ""
    public_base: str = ""
    dial_mode: str = "dry"          # dry = record the dial, call nobody; live = place real calls
    notify_mode: str = "dry"        # dry = record the Telegram message, send nothing; live = send
    voice_id: str = "PzmQUpk8aFhvZ60i0HCf"
    wait_secs: float = 20.0         # how long a tool call waits for an agent before answering "pending"
    long_wait_secs: float = 3.0     # ...and for a job {{CHIEF}} has marked long (a draft, a plan, research): no 20 seconds of dead air
    batch_window_secs: float = 120.0
    recent_dial_secs: float = 180.0
    max_dials_per_hour: int = 6
    max_dials_per_day: int = 20
    max_call_secs: int = 900
    included_minutes: int = 275
    minutes_margin: int = 5         # stop 5 minutes before the plan's included minutes, for rounding
    warn_fraction: float = 0.8
    credit_reserve: int = 3000      # ElevenLabs credits kept back: the line closes with this many left (about ten call minutes)
    brief_every_secs: float = 300.0
    guest_agent_id: str = ""                    # the ElevenLabs agent "{{CHIEF}} (guest)", which rings the people in the contact book
    max_guest_calls_per_day: int = 4            # all guests together, in 24 hours
    guest_calls_per_contact_per_day: int = 2
    guest_min_gap_secs: float = 600.0           # the same person is not rung twice within ten minutes
    guest_max_call_secs: int = 300
    moodle_cli: str = "/data/tools/moodle/node_modules/.bin/moodle"
    moodle_url: str = ""                        # from the setup file (hermes.json), when the Moodle add-on is on
    moodle_env: str = ""                        # the tutor's .env, which holds the cookie the Moodle tool needs
    icloud_python: str = "/data/tools/icloud-venv/bin/python"
    icloud_tool: str = "/data/tools/icloud/icloud_cal.py"
    # secrets: filled in by load(), never written back, never printed
    tool_secret: str = dataclasses.field(default="", repr=False)
    webhook_secret: str = dataclasses.field(default="", repr=False)
    eleven_key: str = dataclasses.field(default="", repr=False)
    twilio_account_sid: str = dataclasses.field(default="", repr=False)
    twilio_key_sid: str = dataclasses.field(default="", repr=False)
    twilio_key_secret: str = dataclasses.field(default="", repr=False)
    hermes_keys: dict = dataclasses.field(default_factory=dict, repr=False)
    telegram_chat_id: str = dataclasses.field(default="", repr=False)

    @property
    def limit_minutes(self) -> int:
        return self.included_minutes - self.minutes_margin

    @property
    def db_path(self) -> str:
        return str(Path(self.state_dir) / "desk.db")

    @property
    def contacts_path(self) -> str:
        return str(Path(self.state_dir) / "contacts.json")

    def problems(self) -> list[str]:
        """Names of what is missing for a live run (names only, never values)."""
        missing = []
        for name in ("max_number", "agent_id", "phone_number_id", "public_base"):
            if not getattr(self, name):
                missing.append(name)
        for name in ("tool_secret", "webhook_secret", "eleven_key"):
            if not getattr(self, name):
                missing.append(name)
        for profile in ("default",) + NAMED_PROFILES:
            if not self.hermes_keys.get(profile):
                missing.append(f"hermes key for {profile}")
        return missing


# Settings that may live in config.json (secrets never do).
STORED_FIELDS = {f.name for f in dataclasses.fields(Config) if f.repr} | {"max_number", "twilio_number"}


def load(state_dir: str = "/data/.hermes/voice-desk", hermes_home: str = "/data/.hermes") -> Config:
    cfg = Config(state_dir=state_dir, hermes_home=hermes_home)
    try:
        stored = json.loads((Path(state_dir) / "config.json").read_text())
    except (OSError, ValueError):
        stored = {}
    for name, value in stored.items():
        if name in STORED_FIELDS and name not in ("state_dir", "hermes_home"):
            setattr(cfg, name, value)
    own = read_env_file(Path(state_dir) / "secrets.env")
    cfg.tool_secret = own.get("DESK_TOOL_SECRET", "")
    cfg.webhook_secret = own.get("ELEVENLABS_WEBHOOK_SECRET", "")
    main = read_env_file(Path(hermes_home) / ".env")
    # Twilio REST access: an API key from secrets.env if one is set, else the account SID and auth token already in .env
    cfg.twilio_key_sid = own.get("TWILIO_KEY_SID") or main.get("TWILIO_ACCOUNT_SID", "")
    cfg.twilio_key_secret = own.get("TWILIO_KEY_SECRET") or main.get("TWILIO_AUTH_TOKEN", "")
    cfg.eleven_key = own.get("ELEVENLABS_API_KEY") or main.get("ELEVENLABS_API_KEY", "")
    cfg.twilio_account_sid = main.get("TWILIO_ACCOUNT_SID", "")
    cfg.telegram_chat_id = main.get("TELEGRAM_HOME_CHANNEL", "")
    try:
        setup = json.loads((Path(hermes_home) / "hermes.json").read_text())      # the installer's answers (no secrets)
    except (OSError, ValueError):
        setup = {}
    if (setup.get("features") or {}).get("moodle"):                              # the Moodle add-on is on
        cfg.moodle_url = cfg.moodle_url or setup.get("moodle_url", "")
        cfg.moodle_env = cfg.moodle_env or str(Path(hermes_home) / "profiles" / "tutor" / ".env")
    cfg.twilio_number = cfg.twilio_number or main.get("TWILIO_PHONE_NUMBER", "")
    cfg.twilio_number_sid = cfg.twilio_number_sid or main.get("TWILIO_PHONE_NUMBER_SID", "")
    cfg.hermes_keys = {"default": main.get("API_SERVER_KEY", "")}
    for profile in NAMED_PROFILES:
        env = read_env_file(Path(hermes_home) / "profiles" / profile / ".env")
        cfg.hermes_keys[profile] = env.get("API_SERVER_KEY", "")
    return cfg


def update_config_json(state_dir: str, updates: dict) -> None:
    """Merge non-secret settings into config.json (creates it). Secrets are refused."""
    bad = [name for name in updates if name not in STORED_FIELDS]
    if bad:
        raise ValueError(f"not a stored setting: {bad}")
    path = Path(state_dir) / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = json.loads(path.read_text())
    except (OSError, ValueError):
        current = {}
    current.update(updates)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def set_env_value(path: str | Path, key: str, value: str) -> None:
    """Set KEY=value in an env file (created with mode 0600 if missing); other lines are left alone."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text().splitlines() if path.exists() else []
    out, done = [], False
    for line in lines:
        if re.match(rf"^\s*{re.escape(key)}=", line):
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.touch(mode=0o600)
    tmp.write_text("\n".join(out) + "\n")
    tmp.chmod(0o600)
    tmp.replace(path)
