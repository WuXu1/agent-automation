"""Content studio: the dashboard's page for the content team (vm/studio/README in the kit; the tools are vm/tools/studio, the agents' manual is the content-studio skill).

The owner keeps clips, overlay lines, TikTok sound links and a queue of planned posts here. The agents (Content Director, Clip Curator, Overlay Copywriter, Video Editor) prepare
posts on the board; the owner approves each one and posts it by hand. This module READS /data/studio and the board, and makes the owner's own writes through the SAME functions
the agents' `cy` command uses (cy_plan / cy_ingest, loaded from the tools folder), so the rules (rest days, "only an approved line", "a post is locked once approved") hold
whoever asks. It never runs ffmpeg or calls Gemini: heavy jobs are request files in /data/studio/requests that the studio worker service picks up.

Rules it keeps:
- Everything stays under one root (default /data/studio). A name from the page is checked, never trusted; files are served only from thumbs/, out/ and clips/, as jpg or mp4.
- An upload streams to a .part file inside originals/ (fsync + page cache dropped as it goes: the bridge has a small memory cap), is refused when the disk would be left under
  RESERVE_BYTES, when it is over MAX_UPLOAD, or when two uploads are already running; the worker then makes the small copy and the AI watches it.
- A card for the Content Director is the only thing here that costs money (pence); everything else is free.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import actions
import feeds
import team

TENANT = "studio"
CREW = [
    ("contentdirector", "Content Director", "Plans the posts and pairs clips, lines and sounds"),
    ("clipcurator", "Clip Curator", "Watches each new clip once and tags it"),
    ("overlaycopywriter", "Overlay Copywriter", "Writes overlay lines for you to approve"),
    ("videoeditor", "Video Editor", "Makes the finished 15-second videos"),
]
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".m2ts"}
FONT_EXT = {".ttf", ".otf"}
MAX_UPLOAD = 2 * 1024 ** 3
MAX_FONT = 8 * 1024 ** 2
RESERVE_BYTES = int(1.5 * 1024 ** 3)           # the server's disk is 30 GB and shared with everything else
CHUNK = 1024 * 1024
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+&'-]{0,118}$")
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,90}$")
ID_RE = re.compile(r"^[a-z]_[0-9a-f]{8}$")
SERVED = {"thumbs": {".jpg": "image/jpeg"}, "out": {".jpg": "image/jpeg", ".mp4": "video/mp4"}, "clips": {".mp4": "video/mp4"}}
VOICE_MAX = 8000
_uploads = threading.Semaphore(2)
_lock = threading.Lock()


def err(status: int, message: str) -> actions.ActionError:
    return actions.ActionError(status, message)


class Store:
    """Where the studio's data and tools are, and the tools' own modules (cy_common, cy_plan, cy_ingest) bound to that data."""

    def __init__(self, paths: feeds.Paths):
        self.root = Path(paths.studio_root)
        self.tools = Path(paths.studio_tools)
        self.paths = paths
        self._mods: dict[str, Any] | None = None

    def mods(self) -> dict[str, Any]:
        if self._mods is None:
            if not (self.tools / "cy_common.py").is_file() or not self.root.is_dir():
                raise err(409, "The content studio is not installed on this server yet (sudo hermes-addon studio)")
            if str(self.tools) not in sys.path:
                sys.path.insert(0, str(self.tools))
            import cy_common, cy_ingest, cy_plan                                  # noqa: E401, PLC0415
            self._mods = {"cy": cy_common, "ingest": cy_ingest, "plan": cy_plan}
        self._mods["cy"].ROOT = self.root                                         # one process may serve one studio; tests switch roots
        return self._mods

    @property
    def installed(self) -> bool:
        return (self.tools / "cy_common.py").is_file() and self.root.is_dir()

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)


def _tool_error(exc: Exception) -> actions.ActionError:
    """A ToolError from the shared tools as the page's error: its own words, and a status the page can act on."""
    code = getattr(exc, "code", "")
    status = {"unknown_clip": 404, "unknown_line": 404, "unknown_sound": 404, "unknown_post": 404, "duplicate": 409, "in_use": 409, "held": 409, "locked": 409}.get(code, 400)
    return err(status, getattr(exc, "message", str(exc)))


def _call(fn: Callable[..., Any], *a: Any, **k: Any) -> Any:
    try:
        return fn(*a, **k)
    except actions.ActionError:
        raise
    except Exception as exc:                                                      # noqa: BLE001 - ToolError, by name (its class lives in the tools' module)
        if exc.__class__.__name__ == "ToolError":
            raise _tool_error(exc) from None
        raise


# --------------------------------------------------------------------------------------------- reading

def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def board_cards(paths: feeds.Paths, limit: int = 12) -> list[dict]:
    """The board's cards of the studio tenant, newest first (what the team did lately). Empty when the board cannot be read."""
    if not os.path.exists(paths.kanban_db):
        return []
    try:
        with feeds._ro(paths.kanban_db) as db:
            rows = db.execute("SELECT id, title, status, assignee, created_at, started_at, completed_at FROM tasks WHERE tenant = ? AND status != 'archived' "
                              "ORDER BY created_at DESC LIMIT ?", (TENANT, limit)).fetchall()
            return [{"id": r["id"], "title": str(r["title"] or ""), "status": r["status"], "assignee": r["assignee"],
                     "at": feeds._ms(r["completed_at"]) or feeds._ms(r["started_at"]) or feeds._ms(r["created_at"]) or 0} for r in rows]
    except Exception:  # noqa: BLE001 - a board that cannot be read must not break the page
        return []


def crew(store: Store) -> list[dict]:
    home = Path(store.paths.hermes_home) / "profiles"
    return [{"id": p, "name": n, "role": r, "installed": (home / p).is_dir()} for p, n, r in CREW]


def _clip_view(c: dict) -> dict:
    t = c.get("tags") or {}
    return {"id": c["id"], "name": c.get("name"), "duration": c.get("duration"), "added": c.get("added"), "bytes": c.get("bytes"), "tagged": bool(t),
            "tags": {k: t.get(k) for k in ("summary", "mood", "scene", "time_of_day", "weather", "calm", "quality", "text_zone", "has_people", "problems")} if t else None,
            "disabled": bool(c.get("disabled")), "disabledReason": c.get("disabled_reason") or "", "lastUsed": c.get("last_used"), "uses": len(c.get("uses") or []),
            "thumb": f"/api/studio/file/thumbs/{c['id']}.jpg"}


def _post_view(i: dict, clips: dict, lines: dict, sounds: dict, waiting: set) -> dict:
    c, l, s = clips.get(i.get("clip")) or {}, lines.get(i.get("line")) or {}, sounds.get(i.get("sound")) or {}
    r = i.get("render")
    out = None
    if r and r.get("out"):
        out = {"video": f"/api/studio/file/out/{Path(r['out']).name}", "still": f"/api/studio/file/out/{Path(r['still']).name}" if r.get("still") else None,
               "seconds": r.get("seconds"), "bytes": r.get("bytes"), "problems": r.get("problems") or [], "rows": r.get("rows") or [], "at": r.get("at")}
    return {"id": i["id"], "due": i.get("due"), "status": i.get("status"), "kind": i.get("kind") or "line", "caption": i.get("caption") or "", "note": i.get("note") or "",
            "line": {"id": i.get("line"), "text": l.get("text")} if l else None, "clip": {"id": i.get("clip"), "name": c.get("name"), "thumb": f"/api/studio/file/thumbs/{i['clip']}.jpg"} if c else None,
            "sound": {"id": i.get("sound"), "title": s.get("title") or s.get("url"), "artist": s.get("artist"), "url": s.get("url")} if s else None,
            "render": out, "making": i["id"] in waiting, "approvedAt": i.get("approved_at"), "postedAt": i.get("posted_at"), "created": i.get("created")}


def waiting_requests(store: Store) -> list[dict]:
    out = []
    for f in sorted(store.path("requests").glob("*.json")) if store.path("requests").is_dir() else []:
        req = _read(f, {})
        if isinstance(req, dict) and req.get("verb"):
            out.append({k: req.get(k) for k in ("verb", "name", "clip", "post")})
    return out


def status(store: Store, env: actions.Env) -> dict:
    team_view = team.load(env.hermes_home)
    out: dict[str, Any] = {"at": int(time.time() * 1000), "installed": store.installed, "name": team_view.get("studio", {}).get("name", "Content studio"), "crew": crew(store),
                           "activity": board_cards(store.paths)}
    if not store.installed:
        return out
    m = store.mods()
    cy, pl = m["cy"], m["plan"]
    lib, lines, sounds, queue = cy.load("library")["clips"], cy.load("lines")["lines"], cy.load("sounds")["sounds"], cy.load("queue")["items"]
    wait = waiting_requests(store)
    worker = _read(store.path("work", "worker.json"), {})
    try:
        free = shutil.disk_usage(store.root).free
    except OSError:
        free = 0
    out.update(settings=cy.settings(), style=cy.style(), needs=pl.status_report(), disk={"freeGB": round(free / 1024 ** 3, 1)},
               worker={"busy": worker.get("busy"), "last": worker.get("last"), "failures": (worker.get("failures") or [])[-10:], "waiting": wait},
               clips=sorted((_clip_view(c) for c in lib.values()), key=lambda c: c["added"] or "", reverse=True),
               lines=sorted(lines.values(), key=lambda l: l.get("added") or "", reverse=True),
               sounds=sorted(sounds.values(), key=lambda s: s.get("added") or "", reverse=True),
               queue=[_post_view(i, lib, lines, sounds, {r["post"] for r in wait if r.get("verb") == "render"}) for i in queue],
               fonts=sorted(f.name for f in store.path("fonts").glob("*") if f.suffix.lower() in FONT_EXT) if store.path("fonts").is_dir() else [])
    return out


# --------------------------------------------------------------------------------------------- the owner's writes

def _request(store: Store, req: dict) -> None:
    d = store.path("requests")
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{uuid.uuid4().hex}.part"
    tmp.write_text(json.dumps(req))
    os.chmod(tmp, 0o644)
    os.replace(tmp, d / f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}.json")


def _id(raw: Any) -> str:
    s = str(raw or "")
    if not ID_RE.match(s):
        raise err(400, "That is not a valid id")
    return s


def _tags(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = re.split(r"[,\n]", raw)
    return [str(t).strip() for t in raw if str(t).strip()][:6] if isinstance(raw, list) else []


def add_lines(store: Store, env: actions.Env, args: dict) -> dict:
    """The owner's own lines go in approved: he wrote them. One or many (one per row of the box)."""
    m = store.mods()
    texts = args.get("texts") if isinstance(args.get("texts"), list) else [args.get("text")]
    texts = [str(t).strip() for t in texts if isinstance(t, str) and t.strip()][:60]
    if not texts:
        raise err(400, "Type at least one line")
    kind = "cta" if args.get("kind") == "cta" else "line"
    added, skipped = [], []
    for t in texts:
        try:
            added.append(m["plan"].add_line(t, _tags(args.get("tags")), "approved", kind, "owner")["id"])
        except Exception as exc:                                                  # noqa: BLE001 - one bad line must not stop the others
            if exc.__class__.__name__ != "ToolError":
                raise
            skipped.append({"text": t[:60], "why": getattr(exc, "message", str(exc))})
    if not added:
        raise err(400, skipped[0]["why"] if skipped else "Nothing to add")
    actions.log_action(env, "studio-lines-added", count=len(added), skipped=len(skipped))
    return {"added": added, "skipped": skipped}


def set_line(store: Store, env: actions.Env, line_id: str, args: dict) -> dict:
    m = store.mods()
    fields = {k: args[k] for k in ("text", "status", "tags", "kind") if k in args}
    if "tags" in fields:
        fields["tags"] = _tags(fields["tags"])
    rec = _call(m["plan"].set_line, _id_of(line_id, "l"), **fields)
    actions.log_action(env, "studio-line-changed", line=rec["id"], status=rec["status"])
    return rec


def _id_of(raw: Any, prefix: str) -> str:
    s = _id(raw)
    if not s.startswith(prefix + "_"):
        raise err(400, "That is not a valid id")
    return s


def delete_line(store: Store, env: actions.Env, line_id: str) -> dict:
    out = _call(store.mods()["plan"].remove_line, _id_of(line_id, "l"))
    actions.log_action(env, "studio-line-deleted", line=line_id)
    return out


def add_sound(store: Store, env: actions.Env, args: dict) -> dict:
    rec = _call(store.mods()["plan"].add_sound, str(args.get("url") or ""), str(args.get("title") or ""), str(args.get("artist") or ""), _tags(args.get("mood")), str(args.get("notes") or ""))
    actions.log_action(env, "studio-sound-added", sound=rec["id"])
    return rec


def set_sound(store: Store, env: actions.Env, sound_id: str, args: dict) -> dict:
    fields = {k: args[k] for k in ("title", "artist", "notes", "mood", "disabled") if k in args}
    if "mood" in fields:
        fields["mood"] = _tags(fields["mood"])
    rec = _call(store.mods()["plan"].set_sound, _id_of(sound_id, "s"), **fields)
    actions.log_action(env, "studio-sound-changed", sound=rec["id"])
    return rec


def delete_sound(store: Store, env: actions.Env, sound_id: str) -> dict:
    out = _call(store.mods()["plan"].remove_sound, _id_of(sound_id, "s"))
    actions.log_action(env, "studio-sound-deleted", sound=sound_id)
    return out


def clip_action(store: Store, env: actions.Env, clip_id: str, args: dict) -> dict:
    m = store.mods()
    cid = _id_of(clip_id, "c")
    act = args.get("action")
    if act in ("disable", "enable"):
        out = _call(m["ingest"].set_disabled, cid, act == "disable", str(args.get("reason") or "switched off by you"))
    elif act == "retag":
        if cid not in m["cy"].load("library")["clips"]:
            raise err(404, "No such clip")
        _request(store, {"verb": "tag", "clip": cid})
        out = {"queued": True}
    elif act == "rename":
        name = str(args.get("name") or "").strip()[:60]
        if not name:
            raise err(400, "Give it a name")
        lib = m["cy"].load("library")
        if cid not in lib["clips"]:
            raise err(404, "No such clip")
        lib["clips"][cid]["name"] = name
        m["cy"].save("library", lib)
        out = {"clip": cid, "name": name}
    else:
        raise err(400, "action must be disable, enable, retag or rename")
    actions.log_action(env, "studio-clip", clip=cid, action=act)
    return out


def delete_clip(store: Store, env: actions.Env, clip_id: str) -> dict:
    out = _call(store.mods()["ingest"].remove, _id_of(clip_id, "c"))
    actions.log_action(env, "studio-clip-deleted", clip=clip_id)
    return out


def post_action(store: Store, env: actions.Env, post_id: str, args: dict) -> dict:
    """The owner's moves on a planned post. Approve needs the finished video; once approved the post is locked until he marks it posted or un-approves it."""
    m = store.mods()
    pl = m["plan"]
    pid = _id_of(post_id, "p")
    act = args.get("action")
    if act == "approve":
        item = _call(pl.approve, pid, True)
    elif act == "unapprove":
        item = _call(pl.approve, pid, False)
    elif act == "skip":
        item = _call(pl.skip, pid)
    elif act == "unskip":
        item = _call(pl.unskip, pid)
    elif act == "posted":
        item = _call(pl.mark, pid, "posted")
    elif act == "render":
        q = m["cy"].load("queue")["items"]
        it = next((i for i in q if i["id"] == pid), None)
        if it is None:
            raise err(404, "No such post")
        if it["status"] not in ("proposed", "ready"):
            raise err(409, f"This post is {it['status']}")
        _request(store, {"verb": "render", "post": pid})
        item = it
    elif act == "set":
        fields = {k: args[k] for k in ("clip", "line", "sound", "caption", "due", "note") if k in args}
        if not fields:
            raise err(400, "Nothing to change")
        item = _call(pl.set_item, pid, **fields)
        if "clip" in fields or "line" in fields:                              # a new picture or new words: the old video is gone, so make the new one now
            _request(store, {"verb": "render", "post": pid})
    else:
        raise err(400, "action must be approve, unapprove, skip, unskip, posted, render or set")
    actions.log_action(env, "studio-post", post=pid, action=act)
    return {"post": pid, "status": item["status"]}


def propose(store: Store, env: actions.Env, args: dict) -> dict:
    """Free and instant: the planner's own rules choose, no agent and no AI; each proposed post gets its video made by the worker. (The Plan button asks the Content Director instead, who also checks the pairings.)"""
    m = store.mods()
    days = args.get("days")
    out = _call(m["plan"].plan, int(days) if isinstance(days, int) and 0 <= days <= 30 else None)
    for item in out["added"]:
        _request(store, {"verb": "render", "post": item["id"]})
    actions.log_action(env, "studio-proposed", added=len(out["added"]), short=sorted(out["short"]))
    return {"added": len(out["added"]), "short": out["short"]}


def _card(env: actions.Env, title: str, body: dict, key: str) -> str | None:
    cmd = ["kanban", "create", "--created-by", "user", "--priority", "10", "--json", "--assignee", "contentdirector", "--workspace", "dir:/data/studio", "--tenant", TENANT,
           "--idempotency-key", key, "--max-runtime", "5400", "--body-file", "-"]
    with actions._lock:
        out = actions.cli(env, *cmd, "--", title, stdin=json.dumps(body))
        try:
            card = json.loads(out).get("id")
        except ValueError:
            mm = re.search(r"\bt_[A-Za-z0-9]+", out)
            card = mm.group(0) if mm else None
        actions.log_action(env, "studio-card", card=card, task=body.get("task"))
    return card


def plan_now(store: Store, env: actions.Env) -> dict:
    """The Plan button: one card for the Content Director (it has the clips watched, new lines written if needed, the pairings checked and the videos made)."""
    if not (Path(env.hermes_home) / "profiles" / "contentdirector").is_dir():
        raise err(409, "The content team is not installed on this server yet (sudo hermes-addon studio)")
    owner = team.owner_name(env.hermes_home)
    card = _card(env, "Plan the next posts", {"schema": "xo.card/1", "stage": "direct", "task": "plan", "summary": f"{owner} pressed Plan in the dashboard", "args": []},
                 f"plan-{int(time.time() // 60)}")
    return {"card": card}


# --- style, settings, voice ---

STYLE_RULES: dict[str, Callable[[Any], Any]] = {}


def _num(lo: float, hi: float, integer: bool = False) -> Callable[[Any], Any]:
    def check(v: Any) -> Any:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError
        if not lo <= v <= hi:
            raise ValueError
        return int(v) if integer else float(v)
    return check


def _enum(*values: str) -> Callable[[Any], Any]:
    def check(v: Any) -> Any:
        if v not in values:
            raise ValueError
        return v
    return check


def _bool(v: Any) -> bool:
    if not isinstance(v, bool):
        raise ValueError
    return v


def _color(v: Any) -> str:
    if not isinstance(v, str) or not re.fullmatch(r"auto|white|black|yellow|#[0-9a-fA-F]{6}|[a-z]{3,12}", v):
        raise ValueError
    return v


STYLE_RULES.update({"size_pct": _num(2, 9), "color": _color, "shadow": _bool, "outline_px": _num(0, 8, True), "position": _enum("auto", "top", "center", "bottom"),
                    "max_width_pct": _num(40, 94, True), "align": _enum("center", "left"), "fade_in_s": _num(0, 3), "start_s": _num(0, 5), "line_spacing_pct": _num(0, 60, True)})
SETTING_RULES: dict[str, Callable[[Any], Any]] = {"post_every_days": _num(1, 14, True), "plan_days": _num(1, 30, True), "post_seconds": _num(5, 60, True), "clip_rest_days": _num(0, 365, True),
                                                  "line_rest_days": _num(0, 365, True), "sound_rest_days": _num(0, 365, True), "cta_every": _num(0, 50, True)}


def _apply(store: Store, name: str, args: dict, rules: dict, current: dict, extra: Callable[[str, Any], Any] | None = None) -> dict:
    changes = {}
    for k, v in args.items():
        if k in rules:
            try:
                changes[k] = rules[k](v)
            except ValueError:
                raise err(400, f"{k} is not a valid value") from None
        elif extra and (r := extra(k, v)) is not None:
            changes[k] = r
        else:
            raise err(400, f"{k} cannot be changed here")
    if not changes:
        raise err(400, "Nothing to change")
    data = {**(_read(store.path(f"{name}.json"), {}) or {}), **changes}
    store.mods()["cy"].write_json(store.path(f"{name}.json"), data)
    return data


def set_style(store: Store, env: actions.Env, args: dict) -> dict:
    def extra(k: str, v: Any) -> Any:
        if k == "font":
            if v == "":
                return ""
            if not isinstance(v, str) or not (store.path("fonts") / Path(v).name).is_file():
                raise err(400, "That font is not uploaded")
            return Path(v).name
        return None
    store.mods()
    data = _apply(store, "style", args, STYLE_RULES, {}, extra)
    actions.log_action(env, "studio-style", keys=sorted(args))
    return {**store.mods()["cy"].style(), **data}


def set_settings(store: Store, env: actions.Env, args: dict) -> dict:
    def extra(k: str, v: Any) -> Any:
        if k == "caption_hashtags":
            tags = [t if t.startswith("#") else "#" + t for t in (str(x).strip() for x in (v if isinstance(v, list) else re.split(r"[,\s]+", str(v)))) if t]
            if any(not re.fullmatch(r"#[A-Za-z0-9_]{1,40}", t) for t in tags) or len(tags) > 10:
                raise err(400, "Hashtags are letters, digits and _ (up to ten)")
            return tags
        if k == "page_brief":
            text = str(v).strip()
            if not 10 <= len(text) <= 400:
                raise err(400, "Describe the page in 10 to 400 characters")
            return text
        return None
    store.mods()
    _apply(store, "settings", args, SETTING_RULES, {}, extra)
    actions.log_action(env, "studio-settings", keys=sorted(args))
    return store.mods()["cy"].settings()


def get_voice(store: Store) -> dict:
    try:
        return {"text": store.path("voice.md").read_text(encoding="utf-8")[:VOICE_MAX]}
    except OSError:
        return {"text": ""}


def set_voice(store: Store, env: actions.Env, args: dict) -> dict:
    text = args.get("text")
    if not isinstance(text, str) or len(text) > VOICE_MAX:
        raise err(400, f"The voice guide is text of up to {VOICE_MAX} characters")
    store.mods()
    p = store.path("voice.md")
    tmp = p.with_name("voice.md.part")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, p)
    actions.log_action(env, "studio-voice", chars=len(text))
    return {"ok": True}


def clear_failures(store: Store, env: actions.Env) -> dict:
    p = store.path("work", "worker.json")
    data = _read(p, {})
    data["failures"] = []
    store.mods()["cy"].write_json(p, data)
    return {"ok": True}


# --------------------------------------------------------------------------------------------- uploads and files (streamed by the HTTP handler)

def clean_upload_name(raw: str, exts: set[str]) -> str:
    name = Path(raw.replace("\\", "/")).name.strip()
    if not NAME_RE.match(name) or Path(name).suffix.lower() not in exts:
        raise err(400, f"Use a file name of letters and digits ending in {', '.join(sorted(exts))}")
    return name


def check_clip_upload(store: Store, raw_name: str, length: int) -> str:
    if not store.installed:
        raise err(409, "The content studio is not installed on this server yet (sudo hermes-addon studio)")
    name = clean_upload_name(raw_name, VIDEO_EXT)
    if length <= 0:
        raise err(411, "Send the file's size (Content-Length)")
    if length > MAX_UPLOAD:
        raise err(413, f"That file is {length / 1024 ** 3:.1f} GB; the studio takes up to {MAX_UPLOAD // 1024 ** 3} GB")
    free = shutil.disk_usage(store.root).free
    if length > free - RESERVE_BYTES:
        raise err(507, f"Not enough room on the server: {free / 1024 ** 3:.1f} GB free, and {RESERVE_BYTES / 1024 ** 3:.1f} GB must stay free. Delete a clip first")
    return name


def accept_clip(store: Store, env: actions.Env, raw_name: str, length: int, read: Callable[[int], bytes]) -> dict:
    """Write `length` bytes from `read` into originals/ and ask the worker to make the small copy. Raises ActionError with the reason; leaves nothing behind on failure."""
    name = check_clip_upload(store, raw_name, length)
    if not _uploads.acquire(blocking=False):
        raise err(429, "Two uploads are already running; wait for one to finish")
    folder = store.path("originals")
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{uuid.uuid4().hex[:10]}{Path(name).suffix.lower()}"
    part = dest.with_name(dest.name + ".part")
    try:
        left, since_sync = length, 0
        with open(part, "wb") as f:
            while left > 0:
                chunk = read(min(CHUNK, left))
                if not chunk:
                    raise err(400, "The upload stopped before the whole file arrived")
                f.write(chunk)
                left -= len(chunk)
                since_sync += len(chunk)
                if since_sync >= 32 * CHUNK:                                       # the service has a small memory cap: do not let written file pile up as cache
                    f.flush()
                    os.fsync(f.fileno())
                    if hasattr(os, "posix_fadvise"):
                        os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
                    since_sync = 0
        os.chmod(part, 0o644)
        os.replace(part, dest)
    except OSError as exc:
        raise err(507 if getattr(exc, "errno", 0) == 28 else 500, "The server could not write the file (disk full?)") from None
    finally:
        _uploads.release()
        part.unlink(missing_ok=True)
    _request(store, {"verb": "ingest", "file": f"originals/{dest.name}", "name": Path(name).stem.replace("_", " ").replace("-", " ").strip()[:60] or "clip"})
    actions.log_action(env, "studio-upload", name=name, bytes=length)
    return {"ok": True, "queued": True, "name": name}


def accept_font(store: Store, env: actions.Env, raw_name: str, length: int, read: Callable[[int], bytes]) -> dict:
    name = clean_upload_name(raw_name, FONT_EXT)
    if not 1000 < length <= MAX_FONT:
        raise err(413, f"A font file is up to {MAX_FONT // 1024 ** 2} MB")
    store.mods()
    folder = store.path("fonts")
    folder.mkdir(parents=True, exist_ok=True)
    data = b""
    while len(data) < length:
        chunk = read(min(CHUNK, length - len(data)))
        if not chunk:
            raise err(400, "The upload stopped before the whole file arrived")
        data += chunk
    if data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf"):
        raise err(415, "That does not look like a TrueType or OpenType font")
    part = folder / (name + ".part")
    part.write_bytes(data)
    os.chmod(part, 0o644)
    os.replace(part, folder / name)
    actions.log_action(env, "studio-font", name=name)
    return {"ok": True, "name": name}


def served_file(store: Store, kind: str, name: str) -> tuple[Path, str]:
    ext = Path(name).suffix.lower()
    if kind not in SERVED or ext not in SERVED[kind] or not FILE_RE.match(name):
        raise err(404, "No such file")
    path = store.path(kind, name)
    if not path.is_file():
        raise err(404, "That file is not there")
    return path, SERVED[kind][ext]


def parse_range(header: str | None, size: int) -> tuple[int, int] | None | bool:
    """(start, end) inclusive for a single byte range; None for no Range header; False for one that cannot be satisfied."""
    if not header:
        return None
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return None
    if m.group(1) == "":
        n = int(m.group(2))
        return (max(0, size - n), size - 1) if n > 0 else False
    start = int(m.group(1))
    end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
    return (start, end) if start < size and start <= end else False
