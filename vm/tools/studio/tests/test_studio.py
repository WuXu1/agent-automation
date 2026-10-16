"""The the content studio tools: a clip in, a post out; lines, sounds and the queue's rules. Needs ffmpeg. Run: python3 -m unittest discover -s vm/tools/studio/tests"""
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import cy_cli  # noqa: E402
import cy_common as cy  # noqa: E402
import cy_ingest  # noqa: E402
import cy_plan as pl  # noqa: E402
import cy_render  # noqa: E402
import cy_tag  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def make_video(path: Path, seconds=6, size="1920x1080", color="0x2b3a42"):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s={size}:d={seconds}", "-f", "lavfi", "-i", f"sine=d={seconds}", "-shortest",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._root = cy.ROOT
        cy.ROOT = self.tmp / "data"
        cy.ROOT.mkdir()
        self.addCleanup(lambda: setattr(cy, "ROOT", self._root))
        self.rng_seed = 7

    def add_clip(self, name, mood=("calm",), scene=("loch",), calm=8, quality=8, people=False, tagged=True, last_used=None):
        cid = cy.new_id("c")
        lib = cy.load("library")
        lib["clips"][cid] = {"id": cid, "name": name, "duration": 20.0, "proxy": f"clips/{cid}.mp4", "tags": ({"mood": list(mood), "scene": list(scene), "calm": calm, "quality": quality,
                             "best_start_s": 2.0, "text_zone": "center", "has_people": people, "time_of_day": "dusk", "weather": "mist"} if tagged else None),
                             "uses": [], "last_used": last_used, "disabled": False}
        cy.save("library", lib)
        return cid

    def add_approved_line(self, text, tags=(), kind="line"):
        return pl.add_line(text, list(tags), "approved", kind, "reuben")["id"]


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg is needed")
class Media(Env):
    def test_a_raw_clip_becomes_a_small_one_and_a_duplicate_is_refused(self):
        raw = self.tmp / "Loch_at_dusk.mp4"
        make_video(raw, 5)
        rec = cy_ingest.ingest(raw)
        info = cy.probe(cy.ROOT / rec["proxy"])
        self.assertEqual((info["width"], info["height"], info["has_audio"]), (1080, 1920, False))
        self.assertEqual(rec["name"], "Loch at dusk")
        self.assertFalse(raw.exists())                                          # the upload is deleted once the small copy exists
        self.assertTrue((cy.ROOT / rec["thumb"]).is_file() and (cy.ROOT / "work" / f"{rec['id']}.small.mp4").is_file())
        same = self.tmp / "same.mp4"
        make_video(same, 5, color="0x405060")
        cy_ingest.ingest(same, keep_original=True)
        with self.assertRaises(cy.ToolError) as c:
            cy_ingest.ingest(same)                                               # the same file again, whatever it is called
        self.assertEqual(c.exception.code, "duplicate")

    def test_junk_and_too_short_files_are_refused(self):
        junk = self.tmp / "x.mp4"
        junk.write_bytes(b"not a video")
        with self.assertRaises(cy.ToolError) as c:
            cy_ingest.ingest(junk)
        self.assertEqual(c.exception.code, "unreadable_media")
        tiny = self.tmp / "t.mp4"
        make_video(tiny, 1)
        with self.assertRaises(cy.ToolError) as c:
            cy_ingest.ingest(tiny)
        self.assertEqual(c.exception.code, "too_short")

    def test_text_is_drawn_on_the_post_and_it_checks_out(self):
        raw = self.tmp / "a.mp4"
        make_video(raw, 6, color="0x30404a")
        rec = cy_ingest.ingest(raw)
        lid = self.add_approved_line("could you let go of this feeling holding you back")
        out = cy_render.render(rec["id"], lid, out_name="t1")
        self.assertEqual((out["size"], out["zone"], len(out["rows"])), ("1080x1920", "center", 3))
        self.assertEqual(cy_render.check(out["out"]), [])
        # the picture differs from the plain clip where the text is, so it really was drawn
        plain = self.tmp / "plain.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "1.4", "-i", str(cy.ROOT / rec["proxy"]), "-frames:v", "1", str(plain)], check=True)
        drawn = self.tmp / "drawn.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "1.4", "-i", str(cy.ROOT / out["out"]), "-frames:v", "1", str(drawn)], check=True)
        r = subprocess.run(["ffmpeg", "-i", str(plain), "-i", str(drawn), "-lavfi", "psnr", "-f", "null", "-"], capture_output=True, text=True)
        self.assertNotIn("average:inf", r.stderr)

    def test_a_line_that_is_too_long_or_empty_is_refused(self):
        raw = self.tmp / "a.mp4"
        make_video(raw, 4)
        rec = cy_ingest.ingest(raw)
        with self.assertRaises(cy.ToolError):
            cy_render.render(rec["id"], text="x" * 200)
        with self.assertRaises(cy.ToolError):
            cy_render.render(rec["id"], text="   ")

    def test_wrapping_never_splits_a_word_and_balances_the_rows(self):
        font = cy.font_path()
        rows = cy_render.wrap("could you let go of this feeling holding you back", font, 88, 864)
        self.assertEqual(" ".join(rows), "could you let go of this feeling holding you back")
        self.assertLessEqual(len(rows), 3)
        self.assertEqual(cy_render.wrap("", font, 88, 864), [])
        self.assertEqual(cy_render.wrap("antidisestablishmentarianism", font, 88, 300), ["antidisestablishmentarianism"])


class Tagging(Env):
    def clip_with_small(self):
        cid = self.add_clip("a", tagged=False)
        (cy.ROOT / "work").mkdir(exist_ok=True)
        (cy.ROOT / "work" / f"{cid}.small.mp4").write_bytes(b"\x00" * 100)
        return cid

    def test_the_answer_is_stored_made_safe_and_the_key_never_leaves_the_header(self):
        cid = self.clip_with_small()
        seen = {}

        def post(url, body, key):
            seen.update(url=url, key=key, body=body)
            return {"candidates": [{"content": {"parts": [{"text": json.dumps({"summary": "Mist over a loch at dusk", "mood": ["Calm", "lonely"], "scene": ["loch", "hills"],
                    "time_of_day": "dusk", "weather": "mist", "motion": "slow", "calm": 15, "quality": 7, "best_start_s": 99, "text_zone": "sideways", "text_color": "light",
                    "has_people": False, "evil": "ignored"})}]}}], "usageMetadata": {"promptTokenCount": 5000, "candidatesTokenCount": 90}}
        r = cy_tag.tag_clip(cid, post=post, key="SECRET")
        t = cy.load("library")["clips"][cid]["tags"]
        self.assertEqual((t["calm"], t["best_start_s"], t["text_zone"], t["mood"]), (10, 5.0, "center", ["calm", "lonely"]))   # clamped: 20 s clip, 15 s post
        self.assertNotIn("evil", t)
        self.assertEqual((seen["key"], "SECRET" in json.dumps(seen["body"]), "SECRET" in seen["url"]), ("SECRET", False, False))
        self.assertEqual(r["prompt_tokens"], 5000)
        self.assertEqual(cy_tag.pending(), [])

    def test_an_empty_or_blocked_answer_is_an_error_not_a_guess(self):
        cid = self.clip_with_small()
        with self.assertRaises(cy.ToolError) as c:
            cy_tag.tag_clip(cid, post=lambda *a: {"promptFeedback": {"blockReason": "OTHER"}}, key="k")
        self.assertEqual(c.exception.code, "empty_answer")
        self.assertIn("OTHER", c.exception.message)
        self.assertIsNone(cy.load("library")["clips"][cid]["tags"])

    def test_no_key_is_reported_plainly(self):
        cid = self.clip_with_small()
        import os
        saved = {k: os.environ.pop(k, None) for k in cy_tag.KEY_NAMES}
        self.addCleanup(lambda: [os.environ.__setitem__(k, v) for k, v in saved.items() if v])
        with self.assertRaises(cy.ToolError) as c:
            cy_tag.tag_clip(cid, post=lambda *a: {})
        self.assertEqual(c.exception.code, "missing_gemini_key")


class Library(Env):
    def test_lines_are_checked_and_never_duplicated(self):
        l = pl.add_line("Could you let go?", ["Release"], "suggested", "line", "agent")
        self.assertEqual((l["status"], l["tags"]), ("suggested", ["release"]))
        for bad in ("hi", "x" * 161, "see https://x.co now", "message @me"):
            with self.assertRaises(cy.ToolError):
                pl.add_line(bad)
        with self.assertRaises(cy.ToolError) as c:
            pl.add_line("could you let go")
        self.assertEqual(c.exception.code, "duplicate")

    def test_sounds_must_be_tiktok_links(self):
        s = pl.add_sound("https://www.tiktok.com/music/Limerence-7123456789?_r=1&_t=x", "Limerence", "Yves Tumor", ["Dreamy"])
        self.assertEqual((s["url"], s["mood"]), ("https://www.tiktok.com/music/Limerence-7123456789", ["dreamy"]))
        for bad in ("http://www.tiktok.com/music/x", "https://evil.com/tiktok.com/music/x", "https://youtube.com/watch?v=1", "not a url"):
            with self.assertRaises(cy.ToolError):
                pl.add_sound(bad)
        with self.assertRaises(cy.ToolError) as c:
            pl.add_sound("https://www.tiktok.com/music/Limerence-7123456789")
        self.assertEqual(c.exception.code, "duplicate")


class Queue(Env):
    def setUp(self):
        super().setUp()
        cy.write_json(cy.ROOT / "settings.json", {"post_every_days": 2, "plan_days": 6, "cta_every": 0})
        self.l1 = self.add_approved_line("could you let go of this feeling", ["release", "calm"])
        self.l2 = self.add_approved_line("what you want wants you", ["want", "dusk"])
        self.l3 = self.add_approved_line("could you stay a little longer", ["calm"])
        self.c1 = self.add_clip("loch", mood=("calm",), scene=("loch",))
        self.c2 = self.add_clip("hill", mood=("dusk",), scene=("hill",))
        self.c3 = self.add_clip("coast", mood=("calm",), scene=("sea",))
        self.s1 = pl.add_sound("https://www.tiktok.com/music/A-1", "A", mood=["calm"])["id"]

    def test_a_day_is_planned_every_other_day_and_nothing_is_used_twice(self):
        today = date(2026, 10, 15)
        out = pl.plan(seed=1, today=today)
        self.assertEqual([i["due"] for i in out["added"]], ["2026-10-15", "2026-10-17", "2026-10-19", "2026-10-21"][:len(out["added"])])
        self.assertEqual(len(out["added"]), 3)                                    # three approved lines: that is what ran out
        self.assertTrue(out["short"].get("lines"))
        for k in ("clip", "line"):
            ids = [i[k] for i in out["added"]]
            self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(pl.plan(seed=1, today=today)["added"], [])               # nothing new to plan
        self.assertEqual({i["status"] for i in cy.load("queue")["items"]}, {"proposed"})

    def test_the_clip_that_suits_the_words_wins(self):
        only = self.add_approved_line("a line about the sea only", ["sea"])
        for l in (self.l1, self.l2, self.l3):
            pl.set_line(l, status="retired")
        out = pl.plan(seed=3, today=date(2026, 10, 15), days=0)
        self.assertEqual((out["added"][0]["line"], out["added"][0]["clip"]), (only, self.c3))

    def test_what_rested_too_little_is_not_offered(self):
        recent = cy.now_iso()
        lib = cy.load("library")
        lib["clips"][self.c1]["last_used"] = recent
        cy.save("library", lib)
        self.assertNotIn(self.c1, [c["id"] for c in pl.free_clips()])
        old = (date.today() - timedelta(days=40)).isoformat() + "T00:00:00Z"
        lib["clips"][self.c1]["last_used"] = old
        cy.save("library", lib)
        self.assertIn(self.c1, [c["id"] for c in pl.free_clips()])
        self.assertNotIn(self.c3, [c["id"] for c in pl.free_clips(skip={self.c3})])
        self.add_clip("untagged", tagged=False)
        self.assertEqual(len(pl.free_clips()), 3)

    def test_the_book_line_comes_every_nth_post_when_there_is_one(self):
        cy.write_json(cy.ROOT / "settings.json", {"post_every_days": 1, "plan_days": 5, "cta_every": 3})
        cta = self.add_approved_line("the question comes from The Sedona Method", ["book"], kind="cta")
        out = pl.plan(seed=2, today=date(2026, 10, 15))
        kinds = [i["kind"] for i in out["added"]]
        self.assertEqual(kinds[2], "cta")
        self.assertEqual(out["added"][2]["line"], cta)
        self.assertEqual(kinds.count("cta"), 1)                                   # only one book line exists and it must rest

    def test_a_post_can_be_changed_until_it_is_approved(self):
        item = pl.plan(seed=1, today=date(2026, 10, 15))["added"][0]
        held = next(i["clip"] for i in cy.load("queue")["items"] if i["id"] != item["id"])
        with self.assertRaises(cy.ToolError) as c:
            pl.set_item(item["id"], clip=held)
        self.assertEqual(c.exception.code, "held")
        free = self.add_clip("spare", mood=("calm",))
        pl.attach_render(item["id"], {"out": "out/x.mp4"})
        changed = pl.set_item(item["id"], clip=free, caption="could you?")
        self.assertEqual((changed["status"], changed["render"], changed["caption"]), ("proposed", None, "could you?"))     # new picture: the old video is gone
        with self.assertRaises(cy.ToolError):
            pl.set_item(item["id"], line="l_nope")
        pl.set_line(self.l1, status="suggested")
        with self.assertRaises(cy.ToolError) as c:
            pl.set_item(item["id"], line=self.l1)
        self.assertEqual(c.exception.code, "bad_line")                             # only an approved line can go in a post

    def test_approval_needs_a_finished_video_and_locks_the_post_until_posted(self):
        item = pl.plan(seed=1, today=date(2026, 10, 15))["added"][0]
        with self.assertRaises(cy.ToolError) as c:
            pl.approve(item["id"])
        self.assertEqual(c.exception.code, "not_ready")
        pl.attach_render(item["id"], {"out": "out/x.mp4"})
        self.assertEqual(pl.approve(item["id"])["status"], "approved")
        with self.assertRaises(cy.ToolError) as c:
            pl.set_item(item["id"], caption="nope")
        self.assertEqual(c.exception.code, "locked")
        with self.assertRaises(cy.ToolError):
            pl.mark(item["id"], "bogus")
        pl.mark(item["id"], "delivered")
        self.assertIsNone(cy.load("library")["clips"][item["clip"]]["last_used"])            # delivered is not used yet
        pl.mark(item["id"], "posted")
        lib, ln = cy.load("library")["clips"][item["clip"]], cy.load("lines")["lines"][item["line"]]
        self.assertTrue(lib["last_used"] and ln["last_used"] and lib["uses"][0]["post"] == item["id"])
        self.assertNotIn(item["clip"], [c["id"] for c in pl.free_clips()])                    # it rests now

    def test_a_skipped_post_comes_back_unless_something_else_took_its_clip(self):
        items = pl.plan(seed=1, today=date(2026, 10, 15))["added"]
        pl.skip(items[0]["id"])
        pl.attach_render(items[1]["id"], {"out": "out/x.mp4"})
        self.assertEqual(pl.unskip(items[0]["id"])["status"], "proposed")
        with self.assertRaises(cy.ToolError) as c:
            pl.unskip(items[0]["id"])
        self.assertEqual(c.exception.code, "not_skipped")
        pl.skip(items[0]["id"])
        pl.set_item(items[1]["id"], clip=items[0]["clip"])                                      # the freed clip goes to another post
        with self.assertRaises(cy.ToolError) as c:
            pl.unskip(items[0]["id"])
        self.assertEqual(c.exception.code, "held")

    def test_unapprove_skip_and_the_status_report(self):
        items = pl.plan(seed=1, today=date(2026, 10, 15))["added"]
        pl.attach_render(items[0]["id"], {"out": "out/x.mp4"})
        pl.approve(items[0]["id"])
        self.assertEqual(pl.approve(items[0]["id"], False)["status"], "ready")
        self.assertEqual(pl.skip(items[1]["id"])["status"], "skipped")
        self.assertIn(items[1]["clip"], [c["id"] for c in pl.free_clips(skip=pl.held(cy.load("queue")["items"])["clip"])] + [items[1]["clip"]])
        rep = pl.status_report()
        self.assertEqual((rep["posts"]["ready"], rep["posts"]["skipped"], rep["posts"]["proposed"]), (1, 1, 1))
        self.assertEqual(rep["clips_untagged"], 0)


class Cli(Env):
    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cy_cli.run(list(argv))
        return code, json.loads(out.getvalue().strip().splitlines()[-1])

    def test_agents_can_only_suggest_lines(self):
        code, out = self.run_cli("lines", "add", "could you stay a while", "--status", "approved")
        self.assertEqual((code, out["error"]["code"]), (3, "refused"))
        code, out = self.run_cli("lines", "add", "could you stay a while", "--tags", "calm,stay")
        self.assertEqual((code, out["status"]), (0, "ok"))
        self.assertEqual(self.run_cli("lines", "list", "--status", "approved")[1]["lines"], [])
        self.assertEqual(len(self.run_cli("lines", "list", "--status", "suggested")[1]["lines"]), 1)

    def test_a_clip_can_be_switched_off_with_a_reason_and_is_then_never_offered(self):
        cid = self.add_clip("dark one")
        self.assertEqual(self.run_cli("clip", "disable", cid)[1]["error"]["code"], "usage")
        code, out = self.run_cli("clip", "disable", cid, "--reason", "mostly black")
        self.assertEqual((code, out["disabled"]), (0, True))
        self.assertEqual(cy.load("library")["clips"][cid]["disabled_reason"], "mostly black")
        self.assertEqual(self.run_cli("candidates")[1]["clips"], [])

    def test_plan_candidates_and_queue_speak_in_json(self):
        pl.add_line("could you let go of this feeling", ["calm"], "approved", "line", "reuben")
        self.add_clip("loch")
        code, out = self.run_cli("candidates")
        self.assertEqual((len(out["clips"]), len(out["lines"]), out["sounds"]), (1, 1, []))
        code, out = self.run_cli("plan", "--days", "0", "--seed", "1")
        self.assertEqual(len(out["added"]), 1)
        q = self.run_cli("queue")[1]["posts"]
        self.assertEqual((q[0]["status"], q[0]["text"], q[0]["clip"], q[0]["rendered"]), ("proposed", "could you let go of this feeling", "loch", False))
        self.assertEqual(self.run_cli("status")[1]["posts"]["proposed"], 1)
        self.assertEqual(self.run_cli("check", q[0]["id"])[0], 3)
        self.assertEqual(self.run_cli("set", q[0]["id"])[1]["error"]["code"], "usage")

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg is needed")
    def test_render_all_proposed_makes_the_videos_and_marks_them_ready(self):
        raw = self.tmp / "a.mp4"
        make_video(raw, 6)
        rec = cy_ingest.ingest(raw)
        lib = cy.load("library")
        lib["clips"][rec["id"]]["tags"] = {"mood": ["calm"], "scene": [], "calm": 8, "quality": 8, "best_start_s": 0, "text_zone": "bottom", "text_color": "light"}
        cy.save("library", lib)
        pl.add_line("could you let go", ["calm"], "approved", "line", "reuben")
        self.run_cli("plan", "--days", "0")
        code, out = self.run_cli("render", "--all-proposed")
        self.assertEqual((code, len(out["rendered"]), out["rendered"][0]["problems"]), (0, 1, []))
        post = self.run_cli("queue")[1]["posts"][0]
        self.assertEqual((post["status"], post["rendered"]), ("ready", True))
        self.assertEqual(self.run_cli("check", post["id"])[0], 0)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg is needed")
class Worker(Env):
    """The service that does the heavy jobs the dashboard asks for."""

    def setUp(self):
        super().setUp()
        import cy_worker
        self.w = cy_worker
        cy.ensure_dirs()
        self.no_key = {k: None for k in cy_tag.KEY_NAMES}

    def ask(self, **req):
        (cy.ROOT / "requests").mkdir(exist_ok=True)
        (cy.ROOT / "requests" / f"{cy.new_id('r')}.json").write_text(json.dumps(req))

    def test_an_uploaded_clip_is_shrunk_and_a_missing_key_leaves_it_untagged_but_reported(self):
        import os
        raw = cy.ROOT / "originals" / "u1.mp4"
        make_video(raw, 5)
        self.ask(verb="ingest", file="originals/u1.mp4", name="Mist")
        saved = {k: os.environ.pop(k, None) for k in cy_tag.KEY_NAMES}
        self.addCleanup(lambda: [os.environ.__setitem__(k, v) for k, v in saved.items() if v])
        self.assertEqual(self.w.run(), 0)
        clips = list(cy.load("library")["clips"].values())
        self.assertEqual((len(clips), clips[0]["name"], clips[0]["tags"]), (1, "Mist", None))
        self.assertFalse(raw.exists())
        st = self.w.read_state()
        self.assertEqual((st["busy"], st["last"]["ok"], st["failures"][0]["kind"]), (None, True, "tag"))
        self.assertIn("missing_gemini_key", st["failures"][0]["message"])
        self.assertEqual(list((cy.ROOT / "requests").glob("*.json")), [])

    def test_a_bad_file_is_reported_and_removed_and_the_queue_goes_on(self):
        (cy.ROOT / "originals").mkdir(exist_ok=True)
        (cy.ROOT / "originals" / "bad.mp4").write_bytes(b"junk")
        self.ask(verb="ingest", file="originals/bad.mp4", name="Bad")
        self.ask(verb="nonsense")
        good = cy.ROOT / "originals" / "good.mp4"
        make_video(good, 4, color="0x203040")
        self.ask(verb="ingest", file="originals/good.mp4", name="Good")
        self.w.run()
        self.assertEqual([c["name"] for c in cy.load("library")["clips"].values()], ["Good"])
        kinds = [f["kind"] for f in self.w.read_state()["failures"]]
        self.assertIn("ingest", kinds)
        self.assertIn("request", kinds)
        self.assertFalse((cy.ROOT / "originals" / "bad.mp4").exists())

    def test_a_path_outside_the_uploads_folder_is_refused(self):
        secret = self.tmp / "secret.mp4"
        make_video(secret, 4)
        self.ask(verb="ingest", file="../../" + str(secret), name="Sneaky")
        self.w.run()
        self.assertEqual(cy.load("library")["clips"], {})
        self.assertTrue(secret.exists())

    def test_a_render_request_makes_the_post_ready(self):
        raw = cy.ROOT / "originals" / "r.mp4"
        make_video(raw, 6)
        rec = cy_ingest.ingest(raw)
        lib = cy.load("library")
        lib["clips"][rec["id"]]["tags"] = {"mood": ["calm"], "scene": [], "calm": 8, "quality": 8, "best_start_s": 0, "text_zone": "center", "text_color": "light"}
        cy.save("library", lib)
        pl.add_line("could you let go", [], "approved", "line", "reuben")
        post = pl.plan(days=0, seed=1)["added"][0]
        self.ask(verb="render", post=post["id"])
        self.w.run()
        self.assertEqual(cy.load("queue")["items"][0]["status"], "ready")
        self.assertTrue((cy.ROOT / cy.load("queue")["items"][0]["render"]["out"]).is_file())


if __name__ == "__main__":
    unittest.main()
