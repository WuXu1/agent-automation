#!/usr/bin/env python3
"""cy_worker.py - does the heavy jobs the dashboard asks for, one at a time, in its own service (its own memory, niced), never inside the dashboard.

The dashboard (bridge/studio.py) and the agents drop small request files into /data/studio/requests; a systemd path unit starts this when the folder is not empty:
  {"verb": "ingest", "file": "originals/<name>", "name": "<shown name>"}   make the small copies of an uploaded clip, then have the AI watch it
  {"verb": "tag", "clip": "<clip id>"}                                     have the AI watch a clip (again)
  {"verb": "render", "post": "<post id>"}                                  make the finished video of a planned post
What happened is written to work/worker.json (busy, last, failures) for the dashboard to show. Failures never stop the queue. Standard library only.
"""
from __future__ import annotations

import fcntl
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cy_common as cy      # noqa: E402
import cy_ingest            # noqa: E402
import cy_render            # noqa: E402
import cy_tag               # noqa: E402
import cy_plan as pl        # noqa: E402

KEEP_FAILURES = 30


def requests_dir() -> Path:
    return cy.ROOT / "requests"


def state_path() -> Path:
    return cy.ROOT / "work" / "worker.json"


def read_state() -> dict:
    s = cy.read_json(state_path(), {})
    return s if isinstance(s, dict) else {}


def write_state(**changes: Any) -> None:
    s = read_state()
    s.update(changes)
    cy.write_json(state_path(), s)


def fail(kind: str, what: str, message: str) -> None:
    s = read_state()
    rows = [f for f in s.get("failures", []) if isinstance(f, dict)]
    rows.append({"kind": kind, "what": what, "message": message[:300], "at": cy.now_iso()})
    write_state(failures=rows[-KEEP_FAILURES:])


def tag_quietly(clip_id: str) -> Optional[str]:
    """Watch a clip; a failure (no key, rate limit) leaves it untagged and is only reported, because the Clip Curator tries again on the next plan."""
    try:
        cy_tag.tag_clip(clip_id)
        return None
    except cy.ToolError as exc:
        fail("tag", clip_id, f"{exc.code}: {exc.message}")
        return exc.code


def do_ingest(req: dict) -> dict:
    rel = str(req.get("file") or "")
    src = (cy.ROOT / rel).resolve()
    if not str(src).startswith(str((cy.ROOT / "originals").resolve()) + os.sep) or not src.is_file():
        raise cy.ToolError("bad_request", "the uploaded file is not there")
    try:
        rec = cy_ingest.ingest(src, req.get("name"))
    except cy.ToolError as exc:
        src.unlink(missing_ok=True)                                  # a file that cannot be used is not kept (the reason goes to the page)
        raise
    code = tag_quietly(rec["id"])
    return {"clip": rec["id"], "name": rec["name"], "tag_error": code}


def do_tag(req: dict) -> dict:
    cid = str(req.get("clip") or "")
    cy_tag.tag_clip(cid)
    return {"clip": cid}


def do_render(req: dict) -> dict:
    import cy_cli                                                    # noqa: PLC0415 - heavy imports only when a render is asked for
    return cy_cli.render_item(str(req.get("post") or ""))


VERBS: dict[str, Callable[[dict], dict]] = {"ingest": do_ingest, "tag": do_tag, "render": do_render}


def process_one(path: Path) -> None:
    try:
        req = json.loads(path.read_text())
        verb = req.get("verb") if isinstance(req, dict) else None
        if verb not in VERBS:
            raise cy.ToolError("bad_request", f"unknown request {verb!r}")
    except (OSError, ValueError, cy.ToolError) as exc:
        path.unlink(missing_ok=True)
        fail("request", path.name, str(exc))
        return
    what = req.get("name") or req.get("clip") or req.get("post") or verb
    write_state(busy={"verb": verb, "what": str(what)[:80], "since": cy.now_iso()})
    try:
        result = VERBS[verb](req)
        write_state(last={"verb": verb, "what": str(what)[:80], "ok": True, "at": cy.now_iso(), "result": result})
    except cy.ToolError as exc:
        fail(verb, str(what), f"{exc.code}: {exc.message}")
        write_state(last={"verb": verb, "what": str(what)[:80], "ok": False, "at": cy.now_iso(), "error": exc.code})
    except Exception as exc:                                         # noqa: BLE001 - one bad request must not stop the rest
        fail(verb, str(what), f"{type(exc).__name__}: {str(exc)[:200]}")
        write_state(last={"verb": verb, "what": str(what)[:80], "ok": False, "at": cy.now_iso(), "error": "crashed"})
        traceback.print_exc(file=sys.stderr)
    finally:
        write_state(busy=None)
        path.unlink(missing_ok=True)


def run(max_seconds: float = 3300) -> int:
    cy.ensure_dirs()
    requests_dir().mkdir(parents=True, exist_ok=True)
    with open(cy.ROOT / "work" / "worker.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0                                                 # another worker is running; it will take the new files too
        started = time.monotonic()
        done = 0
        while time.monotonic() - started < max_seconds:
            files = sorted(requests_dir().glob("*.json"))
            if not files:
                break
            process_one(files[0])
            done += 1
        print(json.dumps({"status": "ok", "command": "worker", "done": done}))
    return 0


if __name__ == "__main__":
    sys.exit(run())
