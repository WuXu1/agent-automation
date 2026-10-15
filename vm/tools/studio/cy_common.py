"""cy_common.py - what every the content studio tool shares: where the data lives, the four JSON files, ids, settings, and small helpers.

The studio's data is plain JSON under /data/studio (STUDIO_ROOT overrides it for tests):
  library.json   the clips Reuben uploaded: a small 1080x1920 copy of each, what the AI saw in it, when it was last used
  lines.json     the overlay texts ("could you let go of this feeling holding you back"): approved ones are used, suggested ones wait for his yes
  sounds.json    TikTok sound links with a note on the mood of each
  queue.json     the posts planned, each: clip + line + sound + caption, and where it is (proposed, ready, approved, delivered, posted, skipped)
  style.json     how the text looks on the video (font, size, place, shadow, fade)
  settings.json  how often to post, how long a clip or a line rests before it is reused, how often the book gets a mention
The dashboard (bridge/studio.py) and the agents' tools (cy) both read and write these, so every write is atomic and every read tolerates a missing file.
Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(os.environ.get("STUDIO_ROOT", "/data/studio"))

DEFAULT_SETTINGS = {
    "post_every_days": 2,        # one post every 1-2 days to start (Reuben)
    "plan_days": 7,              # how far ahead the queue is planned
    "post_seconds": 15,          # the length of a post
    "clip_rest_days": 30,        # a clip is not used again for this long
    "line_rest_days": 60,        # nor an overlay line
    "sound_rest_days": 7,        # nor a sound
    "cta_every": 6,              # every Nth post carries the soft book line (kind "cta"); 0 = never
    "caption_hashtags": [],      # added under every caption, e.g. ["#scotland"]
    "page_name": "Content studio",
    "page_brief": "a calm, meditative short-video page of raw, quiet scenes with a few plain words laid over them",   # what the AI is told the page is
}
DEFAULT_STYLE = {
    "font": "",                  # a font file in /data/studio/fonts, or empty = the first of Inter / DejaVu Sans on the server
    "size_pct": 4.6,             # text height as a share of the video's height
    "color": "white",
    "shadow": True,
    "outline_px": 0,
    "position": "auto",          # auto = where the AI saw calm space in the clip; or top | center | bottom
    "max_width_pct": 80,
    "align": "center",
    "fade_in_s": 0.6,
    "start_s": 0.4,              # the text appears this far into the clip
    "line_spacing_pct": 28,
}
LINE_STATUSES = ("approved", "suggested", "retired")
POST_STATUSES = ("proposed", "ready", "approved", "delivered", "posted", "skipped")
KINDS = ("line", "cta")
FONT_EXT = (".ttf", ".otf")
FALLBACK_FONTS = ("/usr/share/fonts/opentype/inter/Inter-Regular.otf", "/usr/share/fonts/truetype/inter/Inter-Regular.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/freefont/FreeSans.ttf")


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def paths() -> dict[str, Path]:
    return {"root": ROOT, "clips": ROOT / "clips", "thumbs": ROOT / "thumbs", "originals": ROOT / "originals", "out": ROOT / "out", "fonts": ROOT / "fonts",
            "work": ROOT / "work"}


def ensure_dirs() -> None:
    for p in paths().values():
        p.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.part")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def load(name: str) -> dict:
    """library | lines | sounds | queue -> its dict, with the top-level key present."""
    key = {"library": "clips", "lines": "lines", "sounds": "sounds", "queue": "items"}[name]
    data = read_json(ROOT / f"{name}.json", {})
    data = data if isinstance(data, dict) else {}
    data.setdefault(key, [] if name == "queue" else {})
    return data


def save(name: str, data: dict) -> None:
    write_json(ROOT / f"{name}.json", data)


def settings() -> dict:
    s = {**DEFAULT_SETTINGS, **(read_json(ROOT / "settings.json", {}) or {})}
    for k, v in DEFAULT_SETTINGS.items():                       # a hand-edited bad value falls back instead of breaking the planner
        if isinstance(v, int) and not isinstance(s[k], int):
            s[k] = v
    s["page_brief"] = str(s["page_brief"])[:400]
    s["page_name"] = str(s["page_name"])[:40]
    s["post_every_days"] = max(1, min(14, int(s["post_every_days"])))
    s["plan_days"] = max(1, min(30, int(s["plan_days"])))
    s["post_seconds"] = max(5, min(60, int(s["post_seconds"])))
    return s


def style() -> dict:
    return {**DEFAULT_STYLE, **(read_json(ROOT / "style.json", {}) or {})}


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> date:
    return date.today()


def days_since(iso: Optional[str]) -> Optional[float]:
    """Days since an ISO date or time (None when there is none)."""
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400


def slug(text: str, fallback: str = "clip") -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:40] or fallback


def run(cmd: list[str], timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise ToolError("missing_program", f"{cmd[0]} is not installed on this server")
    except subprocess.TimeoutExpired:
        raise ToolError("timeout", f"{cmd[0]} took longer than {timeout:.0f}s")


def probe(path: Path) -> dict:
    """{"duration","width","height","fps","has_audio"} for a media file, or ToolError when ffprobe cannot read it."""
    p = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=60)
    if p.returncode != 0:
        raise ToolError("unreadable_media", f"{path.name} could not be read as a video ({(p.stderr or '').strip()[-160:]})")
    info = json.loads(p.stdout or "{}")
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if v is None:
        raise ToolError("no_video", f"{path.name} has no video in it")
    num, _, den = str(v.get("avg_frame_rate") or "0/1").partition("/")
    try:
        fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    except ValueError:
        fps = 0.0
    try:
        duration = float((info.get("format") or {}).get("duration") or v.get("duration") or 0)
    except ValueError:
        duration = 0.0
    rot = 0
    for sd in v.get("side_data_list") or []:
        rot = int(sd.get("rotation") or rot)
    rot = rot or int((v.get("tags") or {}).get("rotate") or 0)
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    if abs(rot) % 180 == 90:
        w, h = h, w
    return {"duration": round(duration, 2), "width": w, "height": h, "fps": round(fps, 2), "has_audio": any(s.get("codec_type") == "audio" for s in info.get("streams", []))}


def font_path(name: str = "") -> str:
    """The font file the text is drawn with: the one named in the style (uploaded to /data/studio/fonts), else the first server font that exists."""
    if name:
        cand = paths()["fonts"] / Path(name).name
        if cand.is_file():
            return str(cand)
    for f in FALLBACK_FONTS:
        if Path(f).is_file():
            return f
    raise ToolError("no_font", "no usable font on this server (upload one on the Style tab)")


def rest_ok(last_iso: Optional[str], rest_days: int) -> bool:
    d = days_since(last_iso)
    return d is None or d >= rest_days
