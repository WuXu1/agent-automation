"""A made-up team for the tests (hermes.json as the kit's installer writes it). Nobody here is a real person."""
from __future__ import annotations

import json
from pathlib import Path

TEAM = {
    "version": 1,
    "owner": {"name": "Sam", "id": "sam", "pronouns": "they/them", "tailscale_login": "sam@example.com"},
    "timezone": "Europe/London",
    "agents": [
        {"id": "atlas", "profile": "default", "role": "chief", "name": "Atlas", "title": "Chief of Staff"},
        {"id": "sage", "profile": "tutor", "role": "tutor", "name": "Sage", "title": "Tutor"},
        {"id": "ivy", "profile": "assistant", "role": "assistant", "name": "Ivy", "title": "Assistant"},
        {"id": "rocky", "profile": "coach", "role": "coach", "name": "Rocky", "title": "Coach"},
    ],
    "features": {"voice": False, "gmail": False, "moodle": False, "icloud": False, "backup": False},
}
LOGIN = "sam@example.com"


def write_setup(home: str | Path, **features: bool) -> Path:
    """hermes.json in a test's Hermes home, with any features switched on."""
    data = json.loads(json.dumps(TEAM))
    data["features"].update(features)
    path = Path(home) / "hermes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path
