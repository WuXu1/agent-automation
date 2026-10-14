"""A made-up crew for the tests (crew.json as the kit's installer writes it). Nobody here is a real person."""
from __future__ import annotations

import json
from pathlib import Path

CREW = {
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


def write_crew(home: str | Path, **features: bool) -> Path:
    """crew.json in a test's Hermes home, with any features switched on."""
    data = json.loads(json.dumps(CREW))
    data["features"].update(features)
    path = Path(home) / "crew.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path
