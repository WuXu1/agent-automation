"""The content studio page's server side (studio.py + its routes in bridge.py): status, the owner's writes through the shared rules, uploads and files over real HTTP.
Needs ffmpeg only for the one test that makes a picture. Run: python3 -m unittest discover -s dashboard/bridge/tests"""
from __future__ import annotations

import http.client
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import actions  # noqa: E402
import bridge  # noqa: E402
import feeds  # noqa: E402
import studio  # noqa: E402
from hermesfix import LOGIN, write_setup  # noqa: E402

TOOLS = Path(__file__).resolve().parents[3] / "vm" / "tools" / "studio"
FAKE_HERMES = r'''#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
open(__import__("os").path.join(__import__("os").environ["HERMES_HOME"], "cli.log"), "a").write(json.dumps({"args": args, "stdin": sys.stdin.read()}) + "\n")
if args[:2] == ["kanban", "create"]:
    print(json.dumps({"id": "t_fake1"}))
'''


class StudioTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.home = base / "hermes"
        (self.home / "profiles").mkdir(parents=True)
        write_setup(self.home, studio=True)
        data = json.loads((self.home / "hermes.json").read_text())
        data["studio"] = {"name": "Could you?"}
        (self.home / "hermes.json").write_text(json.dumps(data))
        fake = base / "hermes-cli"
        fake.write_text(FAKE_HERMES.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.root = base / "studio"
        self.root.mkdir()
        paths = feeds.Paths(hermes_home=str(self.home), kanban_db=str(self.home / "none.db"), studio_root=str(self.root), studio_tools=str(TOOLS))
        env = actions.Env(hermes_home=str(self.home), hermes_bin=str(fake), state_dir=str(self.home / "hermes-dash"), extra_env={"PATH": os.environ.get("PATH", "/usr/bin")})
        dist = base / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<title>x</title>")
        self.app = bridge.App(bridge.Mem0("http://127.0.0.1:1", "k", "sam"), dist, [LOGIN], paths, env)
        self.server = bridge.make_server(self.app, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.port = self.server.server_address[1]

    # -- helpers
    def req(self, method, path, body=None, dash=True, raw=None, headers=None):
        h = {"Tailscale-User-Login": LOGIN, **(headers or {})}
        if dash:
            h["X-Hermes-Dash"] = "1"
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        conn.request(method, path, body=data, headers=h)
        res = conn.getresponse()
        payload = res.read()
        conn.close()
        try:
            return res.status, json.loads(payload)
        except ValueError:
            return res.status, payload

    def cy(self):
        mods = self.app.studio.mods()
        return mods["cy"]

    def seed_clip(self, name="Loch", tagged=True):
        cy = self.cy()
        cid = cy.new_id("c")
        lib = cy.load("library")
        lib["clips"][cid] = {"id": cid, "name": name, "duration": 20.0, "added": cy.now_iso(), "proxy": f"clips/{cid}.mp4", "thumb": f"thumbs/{cid}.jpg", "bytes": 5_000_000,
                             "tags": {"summary": "mist over a loch", "mood": ["calm"], "scene": ["loch"], "calm": 8, "quality": 8, "best_start_s": 1.0, "text_zone": "center", "has_people": False} if tagged else None,
                             "uses": [], "last_used": None, "disabled": False}
        cy.save("library", lib)
        return cid

    def cli_calls(self):
        log = self.home / "cli.log"
        return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

    # -- tests
    def test_not_installed_says_so_and_the_page_still_loads(self):
        shutil.rmtree(self.root)
        code, out = self.req("GET", "/api/studio/status")
        self.assertEqual((code, out["installed"], out["name"]), (200, False, "Could you?"))
        self.assertEqual(self.req("POST", "/api/studio/lines", {"text": "could you stay"})[0], 409)

    def test_status_shows_everything_the_page_needs_and_no_secret(self):
        cid = self.seed_clip()
        self.req("POST", "/api/studio/lines", {"texts": ["could you let go of this feeling", "what you want wants you"], "tags": "calm, release"})
        code, st = self.req("GET", "/api/studio/status")
        self.assertEqual(code, 200)
        self.assertEqual((st["installed"], st["name"], len(st["clips"]), len(st["lines"]), st["needs"]["lines_approved_free"], st["needs"]["clips_free"]), (True, "Could you?", 1, 2, 2, 1))
        self.assertEqual(st["clips"][0]["thumb"], f"/api/studio/file/thumbs/{cid}.jpg")
        self.assertEqual([c["id"] for c in st["crew"]], ["contentdirector", "clipcurator", "overlaycopywriter", "videoeditor"])
        self.assertNotIn("sha256", json.dumps(st))
        self.assertEqual(st["settings"]["post_every_days"], 2)

    def test_the_owners_lines_go_in_approved_in_bulk_and_bad_ones_are_reported(self):
        code, out = self.req("POST", "/api/studio/lines", {"texts": ["could you stay a while", "see https://x.co", "could you stay a while"]})
        self.assertEqual((code, len(out["added"]), len(out["skipped"])), (200, 1, 2))
        st = self.req("GET", "/api/studio/status")[1]
        self.assertEqual((st["lines"][0]["status"], st["lines"][0]["source"]), ("approved", "owner"))
        self.assertEqual(self.req("POST", "/api/studio/lines", {"texts": []})[0], 400)
        lid = out["added"][0]
        self.assertEqual(self.req("POST", f"/api/studio/lines/{lid}", {"status": "retired"})[1]["status"], "retired")
        self.assertEqual(self.req("DELETE", f"/api/studio/lines/{lid}")[0], 200)
        self.assertEqual(self.req("POST", "/api/studio/lines/l_00000000", {"status": "retired"})[0], 404)
        self.assertEqual(self.req("POST", "/api/studio/lines/nonsense", {"status": "retired"})[0], 404)

    def test_sounds_must_be_tiktok_links(self):
        code, s = self.req("POST", "/api/studio/sounds", {"url": "https://www.tiktok.com/music/Limerence-7123?_r=1", "title": "Limerence", "artist": "Yves Tumor", "mood": "dreamy, slow"})
        self.assertEqual((code, s["mood"]), (200, ["dreamy", "slow"]))
        self.assertEqual(self.req("POST", "/api/studio/sounds", {"url": "https://youtube.com/watch?v=1"})[0], 400)
        self.assertEqual(self.req("POST", f"/api/studio/sounds/{s['id']}", {"notes": "the slow one", "disabled": True})[1]["disabled"], True)
        self.assertEqual(self.req("DELETE", f"/api/studio/sounds/{s['id']}")[0], 200)

    def test_a_proposed_post_can_be_changed_approved_only_when_made_and_then_locks(self):
        self.seed_clip("Loch")
        self.seed_clip("Hill")
        self.req("POST", "/api/studio/lines", {"texts": ["could you let go of this feeling"]})
        code, out = self.req("POST", "/api/studio/propose", {"days": 0})
        self.assertEqual((code, out["added"]), (200, 1))
        waiting = sorted((self.root / "requests").glob("*.json"))
        self.assertEqual([json.loads(w.read_text())["verb"] for w in waiting], ["render"])      # the worker makes the video; nothing heavy here
        st = self.req("GET", "/api/studio/status")[1]
        post = st["queue"][0]
        self.assertEqual((post["status"], post["making"], post["render"]), ("proposed", True, None))
        self.assertEqual(self.req("POST", f"/api/studio/queue/{post['id']}", {"action": "approve"})[0], 400)     # no finished video yet
        other = next(c["id"] for c in st["clips"] if c["id"] != post["clip"]["id"])
        self.assertEqual(self.req("POST", f"/api/studio/queue/{post['id']}", {"action": "set", "clip": other, "caption": "could you?"})[0], 200)
        self.assertEqual(len(list((self.root / "requests").glob("*.json"))), 2)                  # a new picture: its video is made again
        # pretend the worker finished, then approve
        cy = self.cy()
        q = cy.load("queue")
        q["items"][0]["render"] = {"out": "out/x.mp4", "still": "out/x.jpg", "seconds": 15, "bytes": 1000, "problems": []}
        q["items"][0]["status"] = "ready"
        cy.save("queue", q)
        self.assertEqual(self.req("POST", f"/api/studio/queue/{post['id']}", {"action": "approve"})[1]["status"], "approved")
        self.assertEqual(self.req("POST", f"/api/studio/queue/{post['id']}", {"action": "set", "caption": "nope"})[0], 409)       # locked
        self.assertEqual(self.req("POST", f"/api/studio/queue/{post['id']}", {"action": "posted"})[1]["status"], "posted")
        self.assertEqual(self.req("POST", f"/api/studio/queue/{post['id']}", {"action": "skip"})[0], 409)
        self.assertEqual(self.req("POST", f"/api/studio/queue/{post['id']}", {"action": "dance"})[0], 400)

    def test_a_clip_can_be_switched_off_renamed_and_deleted_unless_a_post_uses_it(self):
        cid = self.seed_clip("Loch")
        self.assertEqual(self.req("POST", f"/api/studio/clips/{cid}", {"action": "disable", "reason": "too dark"})[1]["disabled"], True)
        self.assertEqual(self.req("POST", f"/api/studio/clips/{cid}", {"action": "rename", "name": "Loch Lomond"})[1]["name"], "Loch Lomond")
        self.assertEqual(self.req("POST", f"/api/studio/clips/{cid}", {"action": "enable"})[1]["disabled"], False)
        self.assertEqual(self.req("POST", f"/api/studio/clips/{cid}", {"action": "retag"})[1]["queued"], True)
        self.assertEqual(json.loads(sorted((self.root / "requests").glob("*.json"))[0].read_text()), {"verb": "tag", "clip": cid})
        self.req("POST", "/api/studio/lines", {"texts": ["could you stay a while"]})
        self.req("POST", "/api/studio/propose", {"days": 0})
        self.assertEqual(self.req("DELETE", f"/api/studio/clips/{cid}")[0], 409)                  # a planned post holds it
        self.assertEqual(self.req("POST", f"/api/studio/clips/{cid}", {"action": "explode"})[0], 400)

    def test_plan_makes_one_card_for_the_content_director(self):
        self.assertEqual(self.req("POST", "/api/studio/plan", {})[0], 409)                         # the team is not installed
        (self.home / "profiles" / "contentdirector").mkdir()
        code, out = self.req("POST", "/api/studio/plan", {})
        self.assertEqual((code, out["card"]), (200, "t_fake1"))
        call = next(c for c in self.cli_calls() if c["args"][:2] == ["kanban", "create"])
        self.assertIn("contentdirector", call["args"])
        self.assertIn("studio", call["args"])
        body = json.loads(call["stdin"])
        self.assertEqual((body["task"], body["stage"]), ("plan", "direct"))
        self.assertIn("Sam", body["summary"])
        self.assertEqual(self.req("POST", "/api/studio/plan", {}, dash=False)[0], 403)

    def test_style_and_settings_are_checked_and_a_font_must_be_uploaded_first(self):
        self.app.studio.mods()
        code, st = self.req("POST", "/api/studio/style", {"size_pct": 5.5, "position": "bottom", "shadow": False, "color": "#ffffff"})
        self.assertEqual((code, st["size_pct"], st["position"], st["shadow"]), (200, 5.5, "bottom", False))
        for bad in ({"size_pct": 50}, {"position": "diagonal"}, {"color": "red; rm -rf"}, {"font": "Nope.ttf"}, {"mystery": 1}, {}):
            self.assertEqual(self.req("POST", "/api/studio/style", bad)[0], 400, bad)
        code, s = self.req("POST", "/api/studio/settings", {"post_every_days": 1, "cta_every": 5, "caption_hashtags": "scotland, #calm"})
        self.assertEqual((code, s["post_every_days"], s["cta_every"], s["caption_hashtags"]), (200, 1, 5, ["#scotland", "#calm"]))
        self.assertEqual(self.req("POST", "/api/studio/settings", {"post_every_days": 99})[0], 400)
        self.assertEqual(self.req("POST", "/api/studio/settings", {"page_brief": "x"})[0], 400)
        self.assertEqual(self.req("POST", "/api/studio/settings", {"page_name": "Could you?"})[1]["page_name"], "Could you?")
        self.assertEqual(self.req("POST", "/api/studio/settings", {"page_name": ""})[0], 400)
        self.assertEqual(self.req("POST", "/api/studio/voice", {"text": "# voice\nshort and plain"})[0], 200)
        self.assertEqual(self.req("GET", "/api/studio/voice")[1]["text"], "# voice\nshort and plain")
        self.assertEqual(self.req("POST", "/api/studio/voice", {"text": "x" * 9000})[0], 400)

    def test_a_clip_upload_streams_to_disk_and_asks_the_worker_nothing_runs_inline(self):
        self.app.studio.mods()
        payload = b"\x00" * 3_000_000
        code, out = self.req("PUT", "/api/studio/clips/Loch%20dusk.mp4", raw=payload, headers={"Content-Type": "video/mp4"})
        self.assertEqual((code, out["queued"], out["name"]), (200, True, "Loch dusk.mp4"))
        files = [f for f in (self.root / "originals").iterdir()]
        self.assertEqual((len(files), files[0].stat().st_size, files[0].suffix), (1, 3_000_000, ".mp4"))
        req = json.loads(next((self.root / "requests").glob("*.json")).read_text())
        self.assertEqual((req["verb"], req["name"], req["file"].startswith("originals/")), ("ingest", "Loch dusk", True))
        self.assertEqual(self.req("PUT", "/api/studio/clips/notes.txt", raw=b"hello")[0], 400)
        self.assertEqual(self.req("PUT", "/api/studio/clips/../../etc.mp4", raw=b"hello")[0], 400)
        self.assertEqual(self.req("PUT", "/api/studio/clips/ok.mp4", raw=b"hello", dash=False)[0], 403)
        self.assertEqual(list((self.root / "originals").glob("*.part")), [])

    def test_a_font_upload_must_be_a_real_font(self):
        self.app.studio.mods()
        fake = b"hello world" * 200
        self.assertEqual(self.req("PUT", "/api/studio/fonts/Fake.ttf", raw=fake)[0], 415)
        real = b"\x00\x01\x00\x00" + b"\x00" * 3000
        self.assertEqual(self.req("PUT", "/api/studio/fonts/Real.ttf", raw=real)[1]["name"], "Real.ttf")
        self.assertEqual(self.req("GET", "/api/studio/status")[1]["fonts"], ["Real.ttf"])
        self.assertEqual(self.req("POST", "/api/studio/style", {"font": "Real.ttf"})[1]["font"], "Real.ttf")

    def test_files_are_served_with_ranges_and_only_from_the_three_folders(self):
        self.app.studio.mods()
        (self.root / "out").mkdir(exist_ok=True)
        (self.root / "thumbs").mkdir(exist_ok=True)
        (self.root / "out" / "post.mp4").write_bytes(bytes(range(256)) * 40)
        (self.root / "thumbs" / "c_0123abcd.jpg").write_bytes(b"\xff\xd8jpeg")
        (self.root / "voice.md").write_text("secret-ish")
        code, body = self.req("GET", "/api/studio/file/out/post.mp4", headers={"Range": "bytes=10-19"})
        self.assertEqual((code, body), (206, bytes(range(10, 20))))
        self.assertEqual(self.req("GET", "/api/studio/file/thumbs/c_0123abcd.jpg")[1], b"\xff\xd8jpeg")
        for bad in ("/api/studio/file/out/..%2Fvoice.md", "/api/studio/file/out/voice.md", "/api/studio/file/work/worker.json", "/api/studio/file/out/nothing.mp4", "/api/studio/file/thumbs/a.mp4"):
            self.assertEqual(self.req("GET", bad)[0], 404, bad)
        self.assertEqual(self.req("GET", "/api/studio/file/out/post.mp4", headers={"Tailscale-User-Login": "stranger@example.com"})[0], 403)

    def test_worker_news_reaches_the_page_and_failures_can_be_cleared(self):
        self.app.studio.mods()
        (self.root / "work").mkdir(exist_ok=True)
        (self.root / "work" / "worker.json").write_text(json.dumps({"busy": {"verb": "ingest", "what": "Mist", "since": "x"}, "failures": [{"kind": "tag", "what": "c_1", "message": "missing_gemini_key", "at": "x"}]}))
        w = self.req("GET", "/api/studio/status")[1]["worker"]
        self.assertEqual((w["busy"]["what"], w["failures"][0]["message"]), ("Mist", "missing_gemini_key"))
        self.req("POST", "/api/studio/failures/clear", {})
        self.assertEqual(self.req("GET", "/api/studio/status")[1]["worker"]["failures"], [])


if __name__ == "__main__":
    unittest.main()
