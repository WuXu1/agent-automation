"""cy_tag.py - the AI watches each clip once and writes down what it saw, so words can be matched to footage without anyone watching it again.

  tag <clip id> | --pending [--limit N]     watch the clip's small copy (Gemini Flash, one request; about a cent for a minute of video) and store tags in library.json

What it records: a one-line summary, the mood, the scene, time of day and weather, how much moves, how calm it is, where in the clip the best 15 seconds start,
and where on screen there is calm space for words. Plain web request (no extra software on the server). The key is read from STUDIO_GEMINI_KEY (the
Content team's shells get it) or GEMINI_API_KEY, or from the files named in STUDIO_ENV_FILES; it is never printed.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

import cy_common as cy

MODEL = os.environ.get("STUDIO_GEMINI_MODEL", "gemini-3.8-flash")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_INLINE_MB = 18
KEY_NAMES = ("STUDIO_GEMINI_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")

SYSTEM = ("You look at one short video clip for {brief}. Describe the clip for someone choosing which words and which sound suit it. Be literal and brief. "
          "Never invent what you cannot see. Answer only with the JSON asked for.")
PROMPT = ("Watch this clip and fill in the JSON. best_start_s is where the strongest {n} seconds begin (0 if the whole clip is equally good). "
          "text_zone is where plain white text would sit best without covering the subject: top, center or bottom (pick the calmest, emptiest part of the frame "
          "for most of the clip). text_color is light if the text area is dark or mid-tone, dark if it is bright.")
SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"}, "mood": {"type": "array", "items": {"type": "string"}}, "scene": {"type": "array", "items": {"type": "string"}},
    "time_of_day": {"type": "string", "enum": ["dawn", "morning", "day", "golden hour", "dusk", "night", "unclear"]},
    "weather": {"type": "string"}, "motion": {"type": "string", "enum": ["still", "slow", "moderate", "fast"]},
    "calm": {"type": "integer"}, "quality": {"type": "integer"}, "best_start_s": {"type": "number"},
    "text_zone": {"type": "string", "enum": ["top", "center", "bottom"]}, "text_color": {"type": "string", "enum": ["light", "dark"]},
    "has_people": {"type": "boolean"}, "has_readable_text": {"type": "boolean"}, "problems": {"type": "array", "items": {"type": "string"}}},
    "required": ["summary", "mood", "scene", "time_of_day", "motion", "calm", "quality", "best_start_s", "text_zone", "text_color", "has_people"]}

Post = Callable[[str, dict, str], dict]


def find_key() -> str:
    for name in KEY_NAMES:
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    for f in os.environ.get("STUDIO_ENV_FILES", "").split(os.pathsep):
        if f and Path(f).is_file():
            for line in Path(f).read_text(errors="replace").splitlines():
                m = re.match(r"\s*(?:export\s+)?(STUDIO_GEMINI_KEY|GEMINI_API_KEY|GOOGLE_API_KEY)\s*=\s*(.*)$", line)
                if m and m.group(2).strip().strip("\"'"):
                    return m.group(2).strip().strip("\"'")
    raise cy.ToolError("missing_gemini_key", "no Gemini key for this tool (STUDIO_GEMINI_KEY in the profile's .env and its terminal passthrough)")


def live_post(url: str, body: dict, key: str) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = (json.loads(exc.read()).get("error") or {}).get("message", "")
        except (ValueError, OSError):
            pass
        code = {401: "gemini_auth", 403: "gemini_auth", 404: "gemini_model_not_found", 429: "gemini_rate_limited"}.get(exc.code, "gemini_failed")
        raise cy.ToolError(code, f"Gemini answered HTTP {exc.code}: {detail[:160]}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise cy.ToolError("gemini_unreachable", f"could not reach Gemini ({str(getattr(exc, 'reason', exc))[:120]})")


def clamp_tags(raw: Any, duration: float, post_seconds: int) -> dict:
    """The AI's answer, made safe: known fields only, numbers in range, the best window inside the clip."""
    if not isinstance(raw, dict):
        raise cy.ToolError("unreadable_answer", "Gemini's answer was not a JSON object")

    def words(v: Any, n: int) -> list[str]:
        return [str(x).strip().lower()[:30] for x in (v if isinstance(v, list) else []) if str(x).strip()][:n]

    def num(v: Any, lo: float, hi: float, default: float) -> float:
        try:
            return max(lo, min(hi, float(v)))
        except (TypeError, ValueError):
            return default

    latest = max(0.0, duration - post_seconds)
    zone = raw.get("text_zone") if raw.get("text_zone") in ("top", "center", "bottom") else "center"
    return {"summary": str(raw.get("summary") or "").strip()[:160], "mood": words(raw.get("mood"), 5), "scene": words(raw.get("scene"), 6),
            "time_of_day": str(raw.get("time_of_day") or "unclear")[:20], "weather": str(raw.get("weather") or "")[:40], "motion": str(raw.get("motion") or "slow")[:10],
            "calm": int(num(raw.get("calm"), 1, 10, 5)), "quality": int(num(raw.get("quality"), 1, 10, 5)), "best_start_s": round(num(raw.get("best_start_s"), 0, latest, 0), 1),
            "text_zone": zone, "text_color": "dark" if raw.get("text_color") == "dark" else "light", "has_people": bool(raw.get("has_people")),
            "has_readable_text": bool(raw.get("has_readable_text")), "problems": words(raw.get("problems"), 4)}


def tag_clip(clip_id: str, post: Post = live_post, key: Optional[str] = None) -> dict:
    lib = cy.load("library")
    rec = lib["clips"].get(clip_id)
    if rec is None:
        raise cy.ToolError("unknown_clip", f"no clip {clip_id}")
    small = cy.paths()["work"] / f"{clip_id}.small.mp4"
    if not small.is_file():
        raise cy.ToolError("no_viewing_copy", f"the small viewing copy of {rec.get('name')} is missing; remove the clip and upload it again")
    if small.stat().st_size > MAX_INLINE_MB * 1_000_000:
        raise cy.ToolError("too_big_to_watch", f"{rec.get('name')} is too long to watch in one go ({small.stat().st_size // 1_000_000} MB); upload a shorter clip")
    cfg = cy.settings()
    secs = cfg["post_seconds"]
    body = {"systemInstruction": {"parts": [{"text": SYSTEM.format(brief=cfg["page_brief"])}]},
            "contents": [{"role": "user", "parts": [{"inline_data": {"mime_type": "video/mp4", "data": base64.b64encode(small.read_bytes()).decode()}},
                                                    {"text": PROMPT.format(n=secs)}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA, "temperature": 0.3}}
    answer = post(ENDPOINT.format(model=MODEL), body, key or find_key())
    try:
        text = answer["candidates"][0]["content"]["parts"][0]["text"]
        raw = json.loads(re.sub(r"^```[a-z]*\s*|\s*```$", "", text.strip()))
    except (KeyError, IndexError, TypeError, ValueError):
        reason = (answer.get("promptFeedback") or {}).get("blockReason") if isinstance(answer, dict) else None
        raise cy.ToolError("empty_answer", "Gemini gave no usable answer" + (f" (blocked: {reason})" if reason else ""))
    tags = clamp_tags(raw, float(rec.get("duration") or 0), secs)
    usage = answer.get("usageMetadata") or {}
    lib = cy.load("library")
    cur = lib["clips"].get(clip_id)
    if cur is not None:
        cur["tags"], cur["tagged_at"] = tags, cy.now_iso()
        cy.save("library", lib)
    return {"clip": clip_id, "name": rec.get("name"), "tags": tags, "prompt_tokens": usage.get("promptTokenCount"), "output_tokens": usage.get("candidatesTokenCount")}


def pending() -> list[str]:
    return [c["id"] for c in cy.load("library")["clips"].values() if not c.get("tags") and not c.get("disabled")]
