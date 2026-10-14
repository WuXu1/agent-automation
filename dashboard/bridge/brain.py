"""The Second Brain's sections. Mem0 keeps the notes; which section each note sits in, and which
sections exist, live in `<state>/brain.json` so the brain can grow without touching Mem0:

    {"sections": [{"id", "label", "blurb", "builtin"}], "assign": {memory_id: section_id}, "pending": job_id | null}

A note nobody has sorted yet (one added on Telegram, say) is sorted by the jobs runner with the dashboard's model, which
may also start a new section when nothing fits (`jobs.do_brain_sort`). Until then the page places it by keywords.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from actions import ActionError, Env, _lock, log_action

BUILTIN = [
    {"id": "uni", "label": "Study & courses", "blurb": "Courses, deadlines, exams, study plans"},
    {"id": "admin", "label": "Everyday & admin", "blurb": "Calendar, routines, travel, shopping"},
    {"id": "health", "label": "Health & wellbeing", "blurb": "Conditions, medication, sleep, check-ups"},
    {"id": "fitness", "label": "Fitness & food", "blurb": "Training, sport, meals and goals"},
    {"id": "software", "label": "Projects & tech", "blurb": "Projects, code, the server and its tools"},
    {"id": "people", "label": "People & contacts", "blurb": "Real people in your life, how to reach them"},
    {"id": "rules", "label": "Assistant rules", "blurb": "Safety lines, tone, how to work"},
    {"id": "interests", "label": "Interests & hobbies", "blurb": "Music, games, things outside work and study"},
]
MAX_SECTIONS = 16
SORT_BATCH = 40
SECTION_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")


def _path(env: Env) -> Path:
    return Path(env.state_dir) / "brain.json"


def load(env: Env) -> dict[str, Any]:
    try:
        data = json.loads(_path(env).read_text())
    except (OSError, ValueError):
        data = {}
    sections = data.get("sections") if isinstance(data.get("sections"), list) else [{**s, "builtin": True} for s in BUILTIN]
    ids = {s["id"] for s in sections}
    assign = {k: v for k, v in (data.get("assign") or {}).items() if v in ids}
    return {"sections": sections, "assign": assign, "pending": data.get("pending")}


def save(env: Env, data: dict[str, Any]) -> None:
    p = _path(env)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".brain.json.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, p)


def slug(label: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:28] or "section"
    if not base[0].isalpha():
        base = f"s-{base}"[:28]
    sid, n = base, 2
    while sid in taken:
        sid, n = f"{base}-{n}", n + 1
    return sid


def nice(label: str) -> str:
    """A model sometimes names a section like an id ('health-eye'): make it read like the others ('Health eye')."""
    label = re.sub(r"\s+", " ", label.strip())
    if re.fullmatch(r"[a-z0-9_-]+", label):
        label = label.replace("-", " ").replace("_", " ")
        label = label[:1].upper() + label[1:]
    return label[:32]


def add_section(data: dict[str, Any], label: str, blurb: str = "") -> str:
    label = nice(label)
    if not label:
        raise ActionError(400, "A section needs a name")
    existing = next((s for s in data["sections"] if s["label"].lower() == label.lower()), None)
    if existing:
        return existing["id"]
    if len(data["sections"]) >= MAX_SECTIONS:
        raise ActionError(409, f"The brain has {MAX_SECTIONS} sections already; merge some first")
    sid = slug(label, {s["id"] for s in data["sections"]})
    data["sections"].append({"id": sid, "label": label, "blurb": blurb.strip()[:80], "builtin": False})
    return sid


def view(env: Env, memory_ids: list[str] | None = None) -> dict[str, Any]:
    data = load(env)
    out: dict[str, Any] = {"sections": data["sections"], "assign": data["assign"], "sorting": bool(data["pending"])}
    if memory_ids is not None:
        out["assign"] = {k: v for k, v in data["assign"].items() if k in set(memory_ids)}
        out["unsorted"] = sum(1 for m in memory_ids if m not in data["assign"])
    return out


def unsorted(env: Env, memories: list[dict]) -> list[dict]:
    data = load(env)
    return [{"id": m["id"], "text": m["text"][:400]} for m in memories if m["id"] not in data["assign"]][:SORT_BATCH]


def set_pending(env: Env, job: str | None) -> None:
    with _lock:
        data = load(env)
        data["pending"] = job
        save(env, data)


def assign(env: Env, memory_id: str, section: str | None = None, new_label: str | None = None) -> str:
    """Put one note in a section (or a new one). Returns the section id."""
    with _lock:
        data = load(env)
        if new_label:
            section = add_section(data, new_label)
        if section not in {s["id"] for s in data["sections"]}:
            raise ActionError(400, "No such section")
        data["assign"][memory_id] = section
        save(env, data)
    return section


def forget(env: Env, memory_id: str) -> None:
    with _lock:
        data = load(env)
        if data["assign"].pop(memory_id, None):
            save(env, data)


def rename(env: Env, section: str, args: dict) -> dict:
    label, blurb = args.get("label"), args.get("blurb", "")
    if not isinstance(label, str) or not label.strip() or len(label) > 32 or not isinstance(blurb, str) or len(blurb) > 80:
        raise ActionError(400, "A name up to 32 characters, a line up to 80")
    with _lock:
        data = load(env)
        s = next((x for x in data["sections"] if x["id"] == section), None)
        if not s:
            raise ActionError(404, "No such section")
        s["label"], s["blurb"] = label.strip(), blurb.strip()
        save(env, data)
        log_action(env, "brain-section-renamed", section=section)
    return view(env)


def merge(env: Env, section: str, into: Any) -> dict:
    """Remove a section; its notes move to `into`."""
    with _lock:
        data = load(env)
        ids = {s["id"] for s in data["sections"]}
        if section not in ids or into not in ids or into == section:
            raise ActionError(400, "Pick two different sections")
        data["sections"] = [s for s in data["sections"] if s["id"] != section]
        moved = 0
        for k, v in list(data["assign"].items()):
            if v == section:
                data["assign"][k] = into
                moved += 1
        save(env, data)
        log_action(env, "brain-section-merged", section=section, into=into, moved=moved)
    return view(env)


def resort(env: Env) -> dict:
    """Forget every placement, so the runner sorts all notes again (new sections included)."""
    with _lock:
        data = load(env)
        data["assign"], data["pending"] = {}, None
        save(env, data)
        log_action(env, "brain-resort")
    return view(env)


def apply_sort(env: Env, notes: list[dict], answer: dict) -> dict:
    """The model's answer for a batch: {"assign": {id: section_id_or_label}, "new": [{"label", "blurb"}]}. Checked hard."""
    want = {n["id"] for n in notes}
    with _lock:
        data = load(env)
        made: dict[str, str] = {}
        for s in (answer.get("new") or [])[:4]:
            if isinstance(s, dict) and isinstance(s.get("label"), str) and s["label"].strip():
                try:
                    made[s["label"].strip().lower()] = add_section(data, s["label"], s.get("blurb") if isinstance(s.get("blurb"), str) else "")
                except ActionError:
                    pass
        ids = {s["id"] for s in data["sections"]}
        by_label = {s["label"].lower(): s["id"] for s in data["sections"]}
        placed = 0
        for mid, target in (answer.get("assign") or {}).items():
            if mid not in want or not isinstance(target, str):
                continue
            t = target.strip()
            sid = t if t in ids else made.get(t.lower()) or by_label.get(t.lower())
            if sid:
                data["assign"][mid] = sid
                placed += 1
        # a note the model skipped goes to the catch-all rather than being asked about for ever
        for n in notes:
            data["assign"].setdefault(n["id"], "rules" if "rules" in ids else data["sections"][0]["id"])
        data["pending"] = None
        # sections nobody uses any more (not built in) disappear
        used = set(data["assign"].values())
        data["sections"] = [s for s in data["sections"] if s.get("builtin") or s["id"] in used]
        save(env, data)
    return {"placed": placed, "new": list(made.values())}
