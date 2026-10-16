"""cy_plan.py - the overlay lines, the sounds and the queue of planned posts, and the rules that keep the page fresh.

Plain code, no AI, no cost. The agents choose and write; this enforces: nothing is reused before it has rested, a line is only used once Reuben approved it,
a planned post can only be changed before he approves it, and "posted" is the only thing that makes a clip, a line or a sound count as used.

  plan [--days N]                 add proposed posts for the days not yet covered (a day every `post_every_days`), the best unused clip for each line
  candidates                      the clips, lines and sounds that are free to use right now, compactly (what the Content Director chooses from)
"""
from __future__ import annotations

import random
import re
from datetime import date, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

import cy_common as cy

TIKTOK_HOSTS = ("tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com", "m.tiktok.com")
ACTIVE = ("proposed", "ready", "approved", "delivered")           # a post in one of these still holds its clip, line and sound


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


# ---------------------------------------------------------------------------------------------------- lines

def add_line(text: str, tags: Optional[list] = None, status: str = "suggested", kind: str = "line", source: str = "agent", note: str = "") -> dict:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not 3 <= len(text) <= 160:
        raise cy.ToolError("bad_line", "a line is 3 to 160 characters")
    if re.search(r"https?://|www\.|@\w", text):
        raise cy.ToolError("bad_line", "an overlay line has no links or @names in it")
    if status not in cy.LINE_STATUSES or kind not in cy.KINDS:
        raise cy.ToolError("bad_line", "unknown status or kind")
    data = cy.load("lines")
    key = norm(text)
    for l in data["lines"].values():
        if norm(l["text"]) == key:
            raise cy.ToolError("duplicate", f"that line is already there (\"{l['text'][:50]}\")")
    lid = cy.new_id("l")
    rec = {"id": lid, "text": text, "kind": kind, "status": status, "tags": [t for t in (norm(x)[:24] for x in (tags or [])) if t][:6], "source": source,
           "added": cy.now_iso(), "uses": [], "last_used": None, "note": (note or "")[:200]}
    data["lines"][lid] = rec
    cy.save("lines", data)
    return rec


def set_line(line_id: str, **fields: Any) -> dict:
    data = cy.load("lines")
    rec = data["lines"].get(line_id)
    if rec is None:
        raise cy.ToolError("unknown_line", f"no line {line_id}")
    if "text" in fields:
        busy = [i["id"] for i in cy.load("queue")["items"] if i.get("line") == line_id and i.get("status") in ACTIVE]
        if busy:
            raise cy.ToolError("in_use", "this line is in a planned post: change that post first")
        add = re.sub(r"\s+", " ", str(fields["text"])).strip()
        if not 3 <= len(add) <= 160 or re.search(r"https?://|www\.|@\w", add):
            raise cy.ToolError("bad_line", "a line is 3 to 160 characters, with no links or @names")
        rec["text"] = add
    if "status" in fields:
        if fields["status"] not in cy.LINE_STATUSES:
            raise cy.ToolError("bad_line", "status is approved, suggested or retired")
        rec["status"] = fields["status"]
    if "tags" in fields:
        rec["tags"] = [t for t in (norm(x)[:24] for x in fields["tags"]) if t][:6]
    if "kind" in fields and fields["kind"] in cy.KINDS:
        rec["kind"] = fields["kind"]
    cy.save("lines", data)
    return rec


def remove_line(line_id: str) -> dict:
    data = cy.load("lines")
    if line_id not in data["lines"]:
        raise cy.ToolError("unknown_line", f"no line {line_id}")
    busy = [i["id"] for i in cy.load("queue")["items"] if i.get("line") == line_id and i.get("status") in ACTIVE]
    if busy:
        raise cy.ToolError("in_use", "this line is in a planned post: change that post first")
    data["lines"].pop(line_id)
    cy.save("lines", data)
    return {"removed": line_id}


# ---------------------------------------------------------------------------------------------------- sounds

def add_sound(url: str, title: str = "", artist: str = "", mood: Optional[list] = None, notes: str = "") -> dict:
    u = urlparse((url or "").strip())
    if u.scheme != "https" or (u.hostname or "").lower() not in TIKTOK_HOSTS:
        raise cy.ToolError("bad_sound", "a sound link is a TikTok link (https://www.tiktok.com/music/... or a vm.tiktok.com share link)")
    data = cy.load("sounds")
    clean = u._replace(query="", fragment="").geturl() if "/music/" in u.path else u.geturl()
    for s in data["sounds"].values():
        if s["url"] == clean:
            raise cy.ToolError("duplicate", f"that sound is already there (\"{s.get('title') or s['url']}\")")
    sid = cy.new_id("s")
    rec = {"id": sid, "url": clean, "title": (title or "").strip()[:80], "artist": (artist or "").strip()[:60], "mood": [t for t in (norm(x)[:24] for x in (mood or [])) if t][:6],
           "notes": (notes or "").strip()[:200], "added": cy.now_iso(), "uses": [], "last_used": None, "disabled": False}
    data["sounds"][sid] = rec
    cy.save("sounds", data)
    return rec


def set_sound(sound_id: str, **fields: Any) -> dict:
    data = cy.load("sounds")
    rec = data["sounds"].get(sound_id)
    if rec is None:
        raise cy.ToolError("unknown_sound", f"no sound {sound_id}")
    for k, n in (("title", 80), ("artist", 60), ("notes", 200)):
        if k in fields:
            rec[k] = str(fields[k]).strip()[:n]
    if "mood" in fields:
        rec["mood"] = [t for t in (norm(x)[:24] for x in fields["mood"]) if t][:6]
    if "disabled" in fields:
        rec["disabled"] = bool(fields["disabled"])
    cy.save("sounds", data)
    return rec


def remove_sound(sound_id: str) -> dict:
    data = cy.load("sounds")
    if sound_id not in data["sounds"]:
        raise cy.ToolError("unknown_sound", f"no sound {sound_id}")
    busy = [i["id"] for i in cy.load("queue")["items"] if i.get("sound") == sound_id and i.get("status") in ACTIVE]
    if busy:
        raise cy.ToolError("in_use", "this sound is in a planned post: change that post first")
    data["sounds"].pop(sound_id)
    cy.save("sounds", data)
    return {"removed": sound_id}


# ---------------------------------------------------------------------------------------------------- what is free

def held(queue_items: list[dict]) -> dict[str, set]:
    """Ids of the clips, lines and sounds that planned (not yet posted) posts already hold."""
    h: dict[str, set] = {"clip": set(), "line": set(), "sound": set()}
    for i in queue_items:
        if i.get("status") in ACTIVE:
            for k in h:
                if i.get(k):
                    h[k].add(i[k])
    return h


def free_clips(cfg: Optional[dict] = None, skip: Optional[set] = None) -> list[dict]:
    cfg = cfg or cy.settings()
    return [c for c in cy.load("library")["clips"].values()
            if c.get("tags") and not c.get("disabled") and c["id"] not in (skip or set()) and cy.rest_ok(c.get("last_used"), cfg["clip_rest_days"])]


def free_lines(kind: str = "line", cfg: Optional[dict] = None, skip: Optional[set] = None) -> list[dict]:
    cfg = cfg or cy.settings()
    return [l for l in cy.load("lines")["lines"].values()
            if l["status"] == "approved" and l.get("kind", "line") == kind and l["id"] not in (skip or set()) and cy.rest_ok(l.get("last_used"), cfg["line_rest_days"])]


def free_sounds(cfg: Optional[dict] = None, skip: Optional[set] = None) -> list[dict]:
    cfg = cfg or cy.settings()
    return [s for s in cy.load("sounds")["sounds"].values()
            if not s.get("disabled") and s["id"] not in (skip or set()) and cy.rest_ok(s.get("last_used"), cfg["sound_rest_days"])]


def overlap(a: list, b: list) -> int:
    return len({norm(x) for x in a} & {norm(x) for x in b})


def clip_words(c: dict) -> list:
    t = c.get("tags") or {}
    return list(t.get("mood") or []) + list(t.get("scene") or []) + [t.get("time_of_day", ""), t.get("weather", "")]


def best_clip(line: dict, clips: list[dict], rng: random.Random) -> Optional[dict]:
    """The free clip that suits the line best: shared words first, then calm and quality, a little chance to break ties."""
    if not clips:
        return None

    def score(c: dict) -> float:
        t = c.get("tags") or {}
        return overlap(line.get("tags") or [], clip_words(c)) * 3 + (t.get("calm", 5) + t.get("quality", 5)) / 10 + rng.random() * 0.5 - (2 if t.get("has_people") else 0)
    return max(clips, key=score)


def best_sound(clip: dict, line: dict, sounds: list[dict], rng: random.Random) -> Optional[dict]:
    if not sounds:
        return None
    words = clip_words(clip) + list(line.get("tags") or [])
    return max(sounds, key=lambda s: overlap(s.get("mood") or [], words) * 3 + rng.random())


# ---------------------------------------------------------------------------------------------------- the queue

def due_dates(items: list[dict], cfg: dict, today: Optional[date] = None, days: Optional[int] = None) -> list[date]:
    """The days still to fill: every post_every_days after the last planned post (or from today), up to `days` ahead."""
    today = today or cy.today()
    horizon = today + timedelta(days=days if days is not None else cfg["plan_days"])
    live = [date.fromisoformat(i["due"]) for i in items if i.get("status") != "skipped" and i.get("due")]
    nxt = max(live) + timedelta(days=cfg["post_every_days"]) if live else today
    out = []
    while nxt <= horizon:
        out.append(max(nxt, today))
        nxt += timedelta(days=cfg["post_every_days"])
    return out


def count_since_cta(items: list[dict]) -> int:
    n = 0
    for i in sorted((i for i in items if i.get("status") != "skipped"), key=lambda i: i.get("due", ""), reverse=True):
        if i.get("kind") == "cta":
            break
        n += 1
    return n


def plan(days: Optional[int] = None, seed: Optional[int] = None, today: Optional[date] = None) -> dict:
    """Proposes posts for the days not covered yet. Returns {"added": [...], "short": {...}} where short says what ran out (more clips, lines or sounds)."""
    cfg = cy.settings()
    rng = random.Random(seed)
    q = cy.load("queue")
    items = q["items"]
    added, short = [], {}
    for due in due_dates(items, cfg, today, days):
        h = held(items)
        kind = "cta" if cfg["cta_every"] and count_since_cta(items) + 1 >= cfg["cta_every"] and free_lines("cta", cfg, h["line"]) else "line"
        lines = free_lines(kind, cfg, h["line"])
        if not lines and kind == "cta":
            kind, lines = "line", free_lines("line", cfg, h["line"])
        if not lines:
            short["lines"] = True
            break
        line = min(lines, key=lambda l: (l.get("last_used") or "", rng.random()))
        clip = best_clip(line, free_clips(cfg, h["clip"]), rng)
        if clip is None:
            short["clips"] = True
            break
        sound = best_sound(clip, line, free_sounds(cfg, h["sound"]), rng)
        if sound is None:
            short["sounds"] = True                                             # a post can wait for its sound: it is chosen on the day if need be
        tags = clip.get("tags") or {}
        item = {"id": cy.new_id("p"), "due": due.isoformat(), "status": "proposed", "kind": kind, "clip": clip["id"], "line": line["id"], "sound": sound["id"] if sound else None,
                "caption": line["text"], "window": {"start": tags.get("best_start_s", 0), "seconds": cfg["post_seconds"]}, "render": None, "created": cy.now_iso(),
                "approved_at": None, "delivered_at": None, "posted_at": None, "note": ""}
        items.append(item)
        added.append(item)
    items.sort(key=lambda i: i.get("due", ""))
    cy.save("queue", q)
    return {"added": added, "short": short}


def find_item(q: dict, item_id: str) -> dict:
    item = next((i for i in q["items"] if i["id"] == item_id), None)
    if item is None:
        raise cy.ToolError("unknown_post", f"no planned post {item_id}")
    return item


def set_item(item_id: str, **fields: Any) -> dict:
    """Changes a planned post before it is approved: its clip, line, sound, caption or day. Changing the picture or the words clears its render."""
    q = cy.load("queue")
    item = find_item(q, item_id)
    if item["status"] in ("approved", "delivered", "posted"):
        raise cy.ToolError("locked", f"this post is {item['status']}: un-approve it first" if item["status"] == "approved" else f"this post is already {item['status']}")
    others = held([i for i in q["items"] if i["id"] != item_id])
    redo = False
    if "clip" in fields:
        c = cy.load("library")["clips"].get(fields["clip"])
        if c is None or not c.get("tags") or c.get("disabled"):
            raise cy.ToolError("bad_clip", "that clip does not exist, is switched off, or has not been watched yet")
        if c["id"] in others["clip"]:
            raise cy.ToolError("held", "another planned post already uses that clip")
        item["clip"], redo = c["id"], True
        item["window"] = {"start": (c["tags"] or {}).get("best_start_s", 0), "seconds": cy.settings()["post_seconds"]}
    if "line" in fields:
        l = cy.load("lines")["lines"].get(fields["line"])
        if l is None or l["status"] != "approved":
            raise cy.ToolError("bad_line", "only an approved line can go in a post")
        if l["id"] in others["line"]:
            raise cy.ToolError("held", "another planned post already uses that line")
        item["line"], item["kind"], redo = l["id"], l.get("kind", "line"), True
        if "caption" not in fields:
            item["caption"] = l["text"]
    if "sound" in fields:
        if fields["sound"] in (None, ""):
            item["sound"] = None
        else:
            s = cy.load("sounds")["sounds"].get(fields["sound"])
            if s is None or s.get("disabled"):
                raise cy.ToolError("bad_sound", "that sound does not exist or is switched off")
            item["sound"] = s["id"]
    if "caption" in fields:
        item["caption"] = re.sub(r"[ \t]+", " ", str(fields["caption"])).strip()[:400]
    if "due" in fields:
        try:
            date.fromisoformat(str(fields["due"]))
        except ValueError:
            raise cy.ToolError("bad_date", "a day looks like 2026-10-21")
        item["due"] = str(fields["due"])
    if "note" in fields:
        item["note"] = str(fields["note"])[:200]
    if redo:
        item["render"], item["status"] = None, "proposed"
    q["items"].sort(key=lambda i: i.get("due", ""))
    cy.save("queue", q)
    return item


def attach_render(item_id: str, render: dict) -> dict:
    q = cy.load("queue")
    item = find_item(q, item_id)
    if item["status"] not in ("proposed", "ready"):
        raise cy.ToolError("locked", f"this post is {item['status']}")
    item["render"], item["status"] = render, "ready"
    cy.save("queue", q)
    return item


def approve(item_id: str, yes: bool = True) -> dict:
    q = cy.load("queue")
    item = find_item(q, item_id)
    if yes:
        if item["status"] != "ready" or not item.get("render"):
            raise cy.ToolError("not_ready", "only a post with a finished video can be approved")
        item["status"], item["approved_at"] = "approved", cy.now_iso()
    else:
        if item["status"] != "approved":
            raise cy.ToolError("not_approved", "this post is not approved")
        item["status"], item["approved_at"] = "ready", None
    cy.save("queue", q)
    return item


def skip(item_id: str) -> dict:
    q = cy.load("queue")
    item = find_item(q, item_id)
    if item["status"] == "posted":
        raise cy.ToolError("locked", "this post is already posted")
    item["status"] = "skipped"
    cy.save("queue", q)
    return item


def unskip(item_id: str) -> dict:
    """Takes a skipped post back: ready if its video is still there, else proposed (its clip, line and sound must still be free)."""
    q = cy.load("queue")
    item = find_item(q, item_id)
    if item["status"] != "skipped":
        raise cy.ToolError("not_skipped", "this post is not skipped")
    h = held([i for i in q["items"] if i["id"] != item_id])
    for k in ("clip", "line", "sound"):
        if item.get(k) and item[k] in h[k]:
            raise cy.ToolError("held", f"another planned post now uses this post's {k}: change it first")
    item["status"] = "ready" if item.get("render") else "proposed"
    cy.save("queue", q)
    return item


def mark(item_id: str, status: str) -> dict:
    """delivered (sent to Reuben) or posted (he posted it). Posted is what makes the clip, line and sound count as used."""
    if status not in ("delivered", "posted"):
        raise cy.ToolError("bad_status", "mark delivered or posted")
    q = cy.load("queue")
    item = find_item(q, item_id)
    if item["status"] not in ("approved", "delivered"):
        raise cy.ToolError("not_approved", "only an approved post can be delivered or posted")
    now = cy.now_iso()
    item["status"] = status
    item[f"{status}_at"] = now
    if status == "posted":
        for name, key, coll in (("library", "clip", "clips"), ("lines", "line", "lines"), ("sounds", "sound", "sounds")):
            if not item.get(key):
                continue
            data = cy.load(name)
            rec = data[coll].get(item[key])
            if rec is not None:
                rec.setdefault("uses", []).append({"post": item_id, "at": now})
                rec["last_used"] = now
                cy.save(name, data)
    cy.save("queue", q)
    return item


def status_report() -> dict:
    cfg = cy.settings()
    q = cy.load("queue")["items"]
    h = held(q)
    lib = cy.load("library")["clips"]
    upcoming = [i for i in q if i.get("status") in ACTIVE]
    return {"clips": len(lib), "clips_untagged": len([c for c in lib.values() if not c.get("tags") and not c.get("disabled")]), "clips_free": len(free_clips(cfg, h["clip"])),
            "lines_approved_free": len(free_lines("line", cfg, h["line"])), "cta_lines_free": len(free_lines("cta", cfg, h["line"])),
            "lines_suggested": len([l for l in cy.load("lines")["lines"].values() if l["status"] == "suggested"]), "sounds_free": len(free_sounds(cfg, h["sound"])),
            "posts": {s: len([i for i in q if i.get("status") == s]) for s in cy.POST_STATUSES}, "days_planned_ahead": (max((date.fromisoformat(i["due"]) for i in upcoming), default=cy.today()) - cy.today()).days,
            "settings": cfg}
