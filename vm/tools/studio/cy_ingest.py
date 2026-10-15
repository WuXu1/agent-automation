"""cy_ingest.py - a raw clip in, a small clip out. Reuben's phone footage is big; the server keeps one 1080x1920 copy (about 8 MB for 15 seconds),
a still, and a tiny copy for the AI to watch. The upload itself is deleted once the copy is made (the original stays on his phone), unless asked otherwise.

  ingest <file> [--name N] [--keep-original]    make the copies, add the clip to library.json
  remove <clip id>                              delete a clip's files and its entry (refused while a planned post uses it)
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import cy_common as cy

MAX_SECONDS = 180
MIN_SECONDS = 2


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def clean_name(raw: str) -> str:
    stem = Path(raw or "clip").stem
    name = " ".join(stem.replace("_", " ").replace("-", " ").split())
    return name[:60] or "clip"


def make_proxy(src: Path, dst: Path, seconds: float) -> None:
    """1080x1920 (the video fills the frame, cropped from the middle), 30 fps, H.264, no sound: the sound is chosen in TikTok."""
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,format=yuv420p"
    p = cy.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-t", f"{min(seconds, MAX_SECONDS):.2f}", "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "21", "-movflags", "+faststart", str(dst)], timeout=1800)
    if p.returncode != 0 or not dst.is_file():
        raise cy.ToolError("transcode_failed", f"ffmpeg could not make the small copy ({(p.stderr or '').strip()[-200:]})")


def make_small(proxy: Path, dst: Path) -> None:
    """The copy the AI watches: 360x640, 12 fps, heavily compressed (a minute of it is a few MB), so one look costs almost nothing."""
    p = cy.run(["ffmpeg", "-y", "-v", "error", "-i", str(proxy), "-vf", "scale=360:640,fps=12", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
                "-movflags", "+faststart", str(dst)], timeout=900)
    if p.returncode != 0 or not dst.is_file():
        raise cy.ToolError("transcode_failed", f"ffmpeg could not make the small viewing copy ({(p.stderr or '').strip()[-200:]})")


def make_thumb(proxy: Path, dst: Path, at: float) -> None:
    p = cy.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(proxy), "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "4", str(dst)], timeout=120)
    if p.returncode != 0 or not dst.is_file():
        raise cy.ToolError("thumb_failed", f"ffmpeg could not make a still ({(p.stderr or '').strip()[-160:]})")


def ingest(src: Path, name: Optional[str] = None, keep_original: bool = False) -> dict:
    cy.ensure_dirs()
    P = cy.paths()
    info = cy.probe(src)
    if info["duration"] < MIN_SECONDS:
        raise cy.ToolError("too_short", f"{src.name} is {info['duration']} seconds: too short to make a post from")
    digest = sha256_file(src)
    lib = cy.load("library")
    for c in lib["clips"].values():
        if c.get("sha256") == digest:
            raise cy.ToolError("duplicate", f"{src.name} is already in the library as \"{c.get('name')}\"")
    cid = cy.new_id("c")
    proxy, small, thumb = P["clips"] / f"{cid}.mp4", P["work"] / f"{cid}.small.mp4", P["thumbs"] / f"{cid}.jpg"
    try:
        make_proxy(src, proxy, info["duration"])
        make_small(proxy, small)
        shown = cy.probe(proxy)
        make_thumb(proxy, thumb, min(1.0, shown["duration"] / 2))
    except Exception:
        for f in (proxy, small, thumb):
            f.unlink(missing_ok=True)
        raise
    rec = {"id": cid, "name": name.strip()[:60] if name and name.strip() else clean_name(src.name), "added": cy.now_iso(), "duration": shown["duration"],
           "source_seconds": info["duration"], "source_size": f"{info['width']}x{info['height']}", "sha256": digest, "proxy": f"clips/{cid}.mp4",
           "thumb": f"thumbs/{cid}.jpg", "bytes": proxy.stat().st_size, "tags": None, "tagged_at": None, "uses": [], "last_used": None, "disabled": False}
    lib = cy.load("library")                                        # re-read: another ingest may have finished meanwhile
    lib["clips"][cid] = rec
    cy.save("library", lib)
    if not keep_original:
        src.unlink(missing_ok=True)
    return rec


def uses_in_queue(clip_id: str) -> list[str]:
    return [i["id"] for i in cy.load("queue")["items"] if i.get("clip") == clip_id and i.get("status") in ("proposed", "ready", "approved", "delivered")]


def remove(clip_id: str) -> dict:
    lib = cy.load("library")
    rec = lib["clips"].get(clip_id)
    if rec is None:
        raise cy.ToolError("unknown_clip", f"no clip {clip_id}")
    busy = uses_in_queue(clip_id)
    if busy:
        raise cy.ToolError("in_use", f"this clip is part of {len(busy)} planned post(s): skip or change those first")
    P = cy.paths()
    for f in (P["root"] / rec.get("proxy", ""), P["work"] / f"{clip_id}.small.mp4", P["root"] / rec.get("thumb", "")):
        if f.is_file():
            f.unlink()
    lib["clips"].pop(clip_id)
    cy.save("library", lib)
    return {"removed": clip_id, "name": rec.get("name"), "freed_mb": round((rec.get("bytes") or 0) / 1e6, 1)}


def set_disabled(clip_id: str, disabled: bool, reason: str = "") -> dict:
    """Switch a clip off (the planner skips it) or back on. An agent only ever switches one off, with a reason; Reuben can switch it back on."""
    lib = cy.load("library")
    rec = lib["clips"].get(clip_id)
    if rec is None:
        raise cy.ToolError("unknown_clip", f"no clip {clip_id}")
    if disabled:
        busy = uses_in_queue(clip_id)
        if busy:
            raise cy.ToolError("in_use", f"this clip is part of {len(busy)} planned post(s): change those first")
    rec["disabled"] = bool(disabled)
    rec["disabled_reason"] = reason.strip()[:160] if disabled else ""
    cy.save("library", lib)
    return {"clip": clip_id, "name": rec.get("name"), "disabled": rec["disabled"]}
