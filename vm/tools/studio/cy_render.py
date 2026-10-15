"""cy_render.py - a clip and a line in, a finished post out: the best seconds of the clip, 1080x1920, the words laid over it in Reuben's style.

  render --clip C --line L [--sound S] [--out NAME] [--start SECONDS]    -> out/NAME.mp4 and out/NAME.jpg (a still with the words on, for the dashboard)

Plain ffmpeg, no AI, nothing paid. The picture has no sound: the sound is added in TikTok (its library cannot be attached from outside the app).
The text is wrapped to the style's width, drawn with the style's font and size, fades in a moment after the start, and sits where the AI saw calm space
(or where the style says). Wrapping measures with Pillow when the server has it and with a fair estimate otherwise.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import cy_common as cy

H = 1920
W = 1080


def text_width(text: str, font: str, px: int) -> float:
    try:
        from PIL import ImageFont                                              # noqa: PLC0415 - optional; an estimate is used without it
        return float(ImageFont.truetype(font, px).getlength(text))
    except Exception:                                                          # noqa: BLE001
        return len(text) * px * 0.54


def wrap(text: str, font: str, px: int, max_px: float) -> list[str]:
    """Breaks the line into as few, evenly filled rows as fit the width; never splits a word."""
    words = re.sub(r"\s+", " ", text.strip()).split(" ")
    if not words or words == [""]:
        return []
    rows: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if cur and text_width(trial, font, px) > max_px:
            rows.append(cur)
            cur = w
        else:
            cur = trial
    rows.append(cur)
    if len(rows) > 1:                                                          # even out: try the same rows count with a narrower limit so the last row is not one word
        n = len(rows)
        lo, hi = max_px * 0.5, max_px
        for _ in range(12):
            mid = (lo + hi) / 2
            test, c = [], ""
            for w in words:
                t = f"{c} {w}".strip()
                if c and text_width(t, font, px) > mid:
                    test.append(c)
                    c = w
                else:
                    c = t
            test.append(c)
            if len(test) > n:
                lo = mid
            else:
                hi = mid
        best, c = [], ""
        for w in words:
            t = f"{c} {w}".strip()
            if c and text_width(t, font, px) > hi:
                best.append(c)
                c = w
            else:
                c = t
        best.append(c)
        if len(best) == n:
            rows = best
    return rows


def block_top(zone: str, block_h: int) -> int:
    """The y of the first row: the block sits in the top, middle or bottom of the frame."""
    return {"top": int(H * 0.14), "bottom": int(H - block_h - H * 0.17)}.get(zone, int((H - block_h) / 2))


def build_filter(row_files: list[Path], font: str, px: int, st: dict, zone: str, color: str) -> str:
    """One drawtext per row, each centred on its own: the same on every ffmpeg version, whatever it knows about text alignment."""
    shadow = ":shadowcolor=black@0.55:shadowx=3:shadowy=3" if st.get("shadow", True) else ""
    outline = f":borderw={int(st['outline_px'])}:bordercolor=black@0.6" if int(st.get("outline_px") or 0) > 0 else ""
    start, fade = float(st.get("start_s", 0.4)), max(0.05, float(st.get("fade_in_s", 0.6)))
    spacing = int(px * float(st.get("line_spacing_pct", 28)) / 100)
    alpha = f"if(lt(t\\,{start})\\,0\\,min(1\\,(t-{start})/{fade}))"
    step = px + spacing
    top = block_top(zone, len(row_files) * step - spacing)
    left = st.get("align") == "left"
    parts = []
    for i, f in enumerate(row_files):
        x = f"{int(W * (100 - float(st.get('max_width_pct', 80))) / 200)}" if left else "(w-text_w)/2"
        parts.append(f"drawtext=fontfile='{font}':textfile='{f}':fontsize={px}:fontcolor={color}:x={x}:y={top + i * step}{shadow}{outline}:alpha='{alpha}'")
    return ",".join(parts)


def render(clip_id: str, line_id: Optional[str] = None, text: Optional[str] = None, out_name: Optional[str] = None, start: Optional[float] = None) -> dict:
    cy.ensure_dirs()
    P = cy.paths()
    lib = cy.load("library")
    clip = lib["clips"].get(clip_id)
    if clip is None:
        raise cy.ToolError("unknown_clip", f"no clip {clip_id}")
    if text is None:
        line = cy.load("lines")["lines"].get(line_id or "")
        if line is None:
            raise cy.ToolError("unknown_line", f"no line {line_id}")
        text = line["text"]
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise cy.ToolError("empty_line", "the line has no words")
    if len(text) > 160:
        raise cy.ToolError("line_too_long", "an overlay line is at most 160 characters")
    src = P["root"] / clip["proxy"]
    if not src.is_file():
        raise cy.ToolError("missing_clip", f"the small copy of {clip.get('name')} is missing")
    st, cfg = cy.style(), cy.settings()
    tags = clip.get("tags") or {}
    seconds = min(float(cfg["post_seconds"]), float(clip["duration"]))
    s0 = float(start if start is not None else tags.get("best_start_s", 0) or 0)
    s0 = max(0.0, min(s0, float(clip["duration"]) - seconds))
    font = cy.font_path(st.get("font", ""))
    px = int(round(H * float(st.get("size_pct", 4.6)) / 100))
    rows = wrap(text, font, px, W * float(st.get("max_width_pct", 80)) / 100)
    zone = tags.get("text_zone", "center") if st.get("position", "auto") == "auto" else st["position"]
    color = ("black" if tags.get("text_color") == "dark" else "white") if st.get("color") == "auto" else (st.get("color") or "white")
    if not re.fullmatch(r"[A-Za-z0-9#@.]{1,20}", str(color)):
        color = "white"
    name = cy.slug(out_name or f"post-{clip_id}", "post")
    out, still = P["out"] / f"{name}.mp4", P["out"] / f"{name}.jpg"
    row_files = [P["work"] / f"{name}.r{i}.txt" for i in range(len(rows))]
    for f, row in zip(row_files, rows):
        f.write_text(row, encoding="utf-8")
    try:
        vf = build_filter(row_files, font, px, st, zone, color)
        p = cy.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s0:.2f}", "-t", f"{seconds:.2f}", "-i", str(src), "-vf", vf, "-an", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], timeout=900)
        if p.returncode != 0 or not out.is_file():
            raise cy.ToolError("render_failed", f"ffmpeg could not draw the text ({(p.stderr or '').strip()[-240:]})")
        at = min(seconds - 0.1, float(st.get("start_s", 0.4)) + float(st.get("fade_in_s", 0.6)) + 0.4)
        q = cy.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, at):.2f}", "-i", str(out), "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "4", str(still)], timeout=120)
        if q.returncode != 0:
            still.unlink(missing_ok=True)
    finally:
        for f in row_files:
            f.unlink(missing_ok=True)
    info = cy.probe(out)
    return {"out": f"out/{name}.mp4", "still": f"out/{name}.jpg" if still.is_file() else None, "seconds": info["duration"], "bytes": out.stat().st_size,
            "size": f"{info['width']}x{info['height']}", "rows": rows, "zone": zone, "start": round(s0, 2)}


def check(rel_out: str) -> list[str]:
    """What is wrong with a rendered post (an empty list = fine): size, length, sound, file size."""
    p = cy.paths()["root"] / rel_out
    if not p.is_file():
        return [f"{rel_out} is missing"]
    bad = []
    info = cy.probe(p)
    if (info["width"], info["height"]) != (W, H):
        bad.append(f"the picture is {info['width']}x{info['height']}, not {W}x{H}")
    if info["duration"] < 3:
        bad.append("the video is under 3 seconds")
    if info["has_audio"]:
        bad.append("the video has a sound track (the sound is added in TikTok)")
    if p.stat().st_size > 60_000_000:
        bad.append("the file is over 60 MB")
    return bad
