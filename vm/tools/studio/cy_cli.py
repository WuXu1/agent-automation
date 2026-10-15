#!/usr/bin/env python3
"""cy - the one command the the content studio team types (and the dashboard's own jobs call): /data/tools/studio/cy <command> ...

  status                                   what is in the library, what is free, how far ahead the queue is planned
  ingest FILE [--name N]                   make the small copies of a raw clip (the dashboard does this itself on upload)
  tag CLIP_ID | --pending [--limit N]      the AI watches a clip once and writes down what it saw
  candidates                               the free clips, lines and sounds, compactly (what the Content Director chooses from)
  plan [--days N] [--seed S]               propose posts for the days not covered yet
  queue                                    the planned posts, with the words of each
  set POST_ID [--clip C] [--line L] [--sound S] [--caption TEXT] [--due YYYY-MM-DD] [--note TEXT]
  render POST_ID | --all-proposed          make the finished video(s) for planned posts
  lines add TEXT [--tags a,b] [--kind line|cta] [--status suggested|approved]     (an agent only ever adds "suggested"; Reuben approves)
  lines list [--status S]
  sounds list
  clip disable CLIP --reason TEXT           skip a clip the page cannot use (dark, shaky, readable text, people close up); the owner can switch it back on in the dashboard
  check POST_ID                            is the finished video right (size, length, no sound track)?

Every command prints one JSON line last: {"status": "ok", ...} or {"status": "failed", "error": {"code", "message"}}. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cy_common as cy      # noqa: E402
import cy_ingest            # noqa: E402
import cy_plan as pl        # noqa: E402
import cy_render            # noqa: E402
import cy_tag               # noqa: E402


def emit(obj: dict, code: int = 0) -> int:
    print(json.dumps(obj, ensure_ascii=False))
    return code


def compact_candidates() -> dict:
    cfg = cy.settings()
    q = cy.load("queue")["items"]
    h = pl.held(q)
    clips = [{"id": c["id"], "name": c["name"], "dur": c["duration"], **{k: (c["tags"] or {}).get(k) for k in ("summary", "mood", "scene", "time_of_day", "calm", "quality", "has_people")}}
             for c in pl.free_clips(cfg, h["clip"])]
    lines = [{"id": l["id"], "text": l["text"], "kind": l.get("kind", "line"), "tags": l.get("tags")} for k in ("line", "cta") for l in pl.free_lines(k, cfg, h["line"])]
    sounds = [{"id": s["id"], "title": s.get("title"), "artist": s.get("artist"), "mood": s.get("mood"), "notes": s.get("notes")} for s in pl.free_sounds(cfg, h["sound"])]
    return {"clips": clips, "lines": lines, "sounds": sounds}


def queue_view() -> list[dict]:
    lib, lines, sounds = cy.load("library")["clips"], cy.load("lines")["lines"], cy.load("sounds")["sounds"]
    out = []
    for i in cy.load("queue")["items"]:
        out.append({"id": i["id"], "due": i["due"], "status": i["status"], "kind": i.get("kind"), "text": (lines.get(i.get("line")) or {}).get("text"),
                    "clip": (lib.get(i.get("clip")) or {}).get("name"), "clip_id": i.get("clip"), "line_id": i.get("line"), "sound": (sounds.get(i.get("sound")) or {}).get("title") or i.get("sound"),
                    "sound_id": i.get("sound"), "caption": i.get("caption"), "rendered": bool(i.get("render"))})
    return out


def render_item(item_id: str) -> dict:
    q = cy.load("queue")
    item = pl.find_item(q, item_id)
    if item["status"] not in ("proposed", "ready"):
        raise cy.ToolError("locked", f"this post is {item['status']}")
    res = cy_render.render(item["clip"], item["line"], out_name=f"post-{item['due']}-{item_id}", start=(item.get("window") or {}).get("start"))
    problems = cy_render.check(res["out"])
    pl.attach_render(item_id, {**res, "problems": problems, "at": cy.now_iso()})
    return {"post": item_id, **res, "problems": problems}


def run(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="cy", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    a = sub.add_parser("ingest"); a.add_argument("file"); a.add_argument("--name"); a.add_argument("--keep-original", action="store_true")
    a = sub.add_parser("tag"); a.add_argument("clip", nargs="?"); a.add_argument("--pending", action="store_true"); a.add_argument("--limit", type=int, default=20)
    sub.add_parser("candidates")
    a = sub.add_parser("plan"); a.add_argument("--days", type=int); a.add_argument("--seed", type=int)
    sub.add_parser("queue")
    a = sub.add_parser("set"); a.add_argument("post")
    for f in ("clip", "line", "sound", "caption", "due", "note"):
        a.add_argument(f"--{f}")
    a = sub.add_parser("render"); a.add_argument("post", nargs="?"); a.add_argument("--all-proposed", action="store_true")
    a = sub.add_parser("lines"); a.add_argument("action", choices=["add", "list"]); a.add_argument("text", nargs="?"); a.add_argument("--tags", default="")
    a.add_argument("--kind", default="line"); a.add_argument("--status", default="suggested")
    a = sub.add_parser("sounds"); a.add_argument("action", choices=["list"])
    a = sub.add_parser("clip"); a.add_argument("action", choices=["disable"]); a.add_argument("clip"); a.add_argument("--reason", default="")
    a = sub.add_parser("check"); a.add_argument("post")
    args = p.parse_args(argv)
    try:
        if args.cmd == "status":
            return emit({"status": "ok", "command": "status", **pl.status_report()})
        if args.cmd == "ingest":
            rec = cy_ingest.ingest(Path(args.file), args.name, args.keep_original)
            return emit({"status": "ok", "command": "ingest", "clip": rec["id"], "name": rec["name"], "seconds": rec["duration"], "mb": round(rec["bytes"] / 1e6, 1)})
        if args.cmd == "tag":
            ids = cy_tag.pending()[:args.limit] if args.pending else [args.clip] if args.clip else []
            if not ids:
                return emit({"status": "ok", "command": "tag", "tagged": [], "message": "nothing to watch"})
            done, errors = [], []
            for cid in ids:
                try:
                    r = cy_tag.tag_clip(cid)
                    done.append({"clip": cid, "name": r["name"], "summary": r["tags"]["summary"], "tokens": (r.get("prompt_tokens") or 0) + (r.get("output_tokens") or 0)})
                except cy.ToolError as exc:
                    errors.append({"clip": cid, "code": exc.code, "message": exc.message})
                    if exc.code in ("gemini_auth", "missing_gemini_key", "gemini_rate_limited"):
                        break
            return emit({"status": "ok" if not errors else "partial" if done else "failed", "command": "tag", "tagged": done, "errors": errors}, 0 if done or not errors else 3)
        if args.cmd == "candidates":
            return emit({"status": "ok", "command": "candidates", **compact_candidates()})
        if args.cmd == "plan":
            out = pl.plan(args.days, args.seed)
            return emit({"status": "ok", "command": "plan", "added": [{"id": i["id"], "due": i["due"], "kind": i["kind"], "clip": i["clip"], "line": i["line"], "sound": i["sound"]} for i in out["added"]],
                         "short": out["short"]})
        if args.cmd == "queue":
            return emit({"status": "ok", "command": "queue", "posts": queue_view()})
        if args.cmd == "set":
            fields = {k: getattr(args, k) for k in ("clip", "line", "sound", "caption", "due", "note") if getattr(args, k) is not None}
            if not fields:
                raise cy.ToolError("usage", "nothing to change")
            it = pl.set_item(args.post, **fields)
            return emit({"status": "ok", "command": "set", "post": it["id"], "state": it["status"]})
        if args.cmd == "render":
            ids = [i["id"] for i in cy.load("queue")["items"] if i["status"] == "proposed"] if args.all_proposed else [args.post] if args.post else []
            if not ids:
                return emit({"status": "ok", "command": "render", "rendered": [], "message": "nothing to render"})
            done, errors = [], []
            for pid in ids:
                try:
                    r = render_item(pid)
                    done.append({"post": pid, "out": r["out"], "seconds": r["seconds"], "problems": r["problems"]})
                except cy.ToolError as exc:
                    errors.append({"post": pid, "code": exc.code, "message": exc.message})
            return emit({"status": "ok" if not errors else "partial" if done else "failed", "command": "render", "rendered": done, "errors": errors}, 0 if done or not errors else 3)
        if args.cmd == "lines":
            if args.action == "add":
                if (args.status or "suggested") != "suggested":
                    raise cy.ToolError("refused", "agents add lines as \"suggested\"; Reuben approves them in the dashboard")
                rec = pl.add_line(args.text or "", [t for t in args.tags.split(",") if t.strip()], "suggested", args.kind, "agent")
                return emit({"status": "ok", "command": "lines", "line": rec["id"], "text": rec["text"]})
            ls = [l for l in cy.load("lines")["lines"].values() if not args.status or l["status"] == args.status]
            return emit({"status": "ok", "command": "lines", "lines": [{"id": l["id"], "text": l["text"], "kind": l.get("kind"), "status": l["status"], "tags": l.get("tags"),
                                                                         "last_used": l.get("last_used")} for l in ls]})
        if args.cmd == "sounds":
            return emit({"status": "ok", "command": "sounds", "sounds": [{"id": s["id"], "title": s.get("title"), "artist": s.get("artist"), "mood": s.get("mood"), "notes": s.get("notes"),
                                                                         "last_used": s.get("last_used")} for s in cy.load("sounds")["sounds"].values() if not s.get("disabled")]})
        if args.cmd == "clip":
            if not args.reason.strip():
                raise cy.ToolError("usage", "give a reason (--reason \"...\")")
            return emit({"status": "ok", "command": "clip", **cy_ingest.set_disabled(args.clip, True, args.reason)})
        if args.cmd == "check":
            item = pl.find_item(cy.load("queue"), args.post)
            probs = cy_render.check((item.get("render") or {}).get("out", "")) if item.get("render") else ["no finished video yet"]
            return emit({"status": "ok" if not probs else "failed", "command": "check", "post": args.post, "problems": probs}, 0 if not probs else 3)
    except cy.ToolError as exc:
        return emit({"status": "failed", "error": {"code": exc.code, "message": exc.message}}, 3)
    return 2


if __name__ == "__main__":
    sys.exit(run())
