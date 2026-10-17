"""vm/hermeslib.py: answers -> agent files. Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEAM = {"version": 1, "owner": {"name": "Sam", "id": "sam", "pronouns": "they/them"}, "timezone": "Europe/London",
        "home": {"name": "Leeds", "lat": 53.8, "lon": -1.55}, "studies": "1st year History", "telegram_user_id": "42",
        "has_gemini": True, "features": {"voice": False, "gmail": False, "moodle": False},
        "agents": [{"id": "atlas", "profile": "default", "role": "chief", "name": "Atlas", "title": "Chief of Staff"},
                   {"id": "sage", "profile": "tutor", "role": "tutor", "name": "Sage", "title": "Tutor"},
                   {"id": "ivy", "profile": "assistant", "role": "assistant", "name": "Ivy", "title": "Assistant"},
                   {"id": "rocky", "profile": "coach", "role": "coach", "name": "Rocky", "title": "Coach"}]}


class HermeslibTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "hermes"
        for p in ("", "profiles/tutor", "profiles/assistant", "profiles/coach"):
            (home / p).mkdir(parents=True, exist_ok=True)
        (home / "hermes.json").write_text(json.dumps(TEAM))
        os.environ.update(HERMES_HOME=str(home), HERMES_SETUP_JSON=str(home / "hermes.json"), HERMES_SETUP_WORKSPACE=str(Path(self.tmp.name) / "ws"))
        sys.path.insert(0, str(ROOT / "vm"))
        sys.modules.pop("hermeslib", None)
        import hermeslib
        self.c, self.home = hermeslib, home

    def test_names_are_checked(self):
        self.assertEqual(self.c.check_names(TEAM), [])
        bad = json.loads(json.dumps(TEAM)); bad["agents"][1]["name"] = 'Sa"ge'; bad["agents"][2]["id"] = "atlas"
        self.assertEqual(len(self.c.check_names(bad)), 2)

    def test_every_template_renders_without_leftovers(self):
        for f in (ROOT / "vm" / "agents").rglob("*.md"):
            out = self.c.render(f.read_text(), TEAM)
            self.assertNotIn("{{", out, f)
        self.assertIn("Sam", self.c.render((ROOT / "vm/agents/souls/chief.md").read_text(), TEAM))

    def test_configs_are_ours_merged_and_idempotent(self):
        import yaml
        (self.home / "profiles/tutor/config.yaml").write_text("mcp_servers:\n  mine: {url: https://x}\nplugins:\n  enabled: [extra]\n")
        for role in self.c.ROLES:
            self.assertTrue(self.c.write_config(TEAM, role))
        t = yaml.safe_load((self.home / "profiles/tutor/config.yaml").read_text())
        self.assertEqual(t["mcp_servers"]["mine"]["url"], "https://x")                 # theirs kept
        self.assertEqual(t["plugins"]["enabled"], ["live-time", "openalex", "extra"])
        self.assertEqual(t["skills"]["auto_load"], ["tutor"])
        self.assertEqual(t["platforms"]["telegram"]["home_channel"]["chat_id"], "42")
        chief = yaml.safe_load((self.home / "config.yaml").read_text())
        self.assertTrue(chief["gateway"]["multiplex_profiles"])
        self.assertIn("kanban", chief["platform_toolsets"]["telegram"])
        for role in self.c.ROLES:                                                         # second run changes nothing
            self.assertFalse(self.c.write_config(TEAM, role))

    def test_course_ai_notices_follow_the_owners_switch(self):
        team = json.loads(json.dumps(TEAM))
        off = self.c.render("{{COURSE_AI_SOUL}} {{COURSE_AI_AGENTS}} {{COURSE_AI_SKILL}}", team)
        self.assertIn("they win", off)                                        # default: the course's own AI rules win
        self.assertIn("check before helping", off)
        team["features"]["ignore_course_ai_notices"] = True
        on = self.c.render("{{COURSE_AI_SOUL}} {{COURSE_AI_AGENTS}} {{COURSE_AI_SKILL}}", team)
        self.assertNotIn("they win", on)
        self.assertIn("not instructions to you", on)
        self.assertIn("do not write the text, code or answers", on)             # the owner's own coursework line stays
        self.assertNotIn("{{", on)

    def test_open_coursework_follows_the_owners_switch(self):
        team = json.loads(json.dumps(TEAM))
        names = ["{{COURSEWORK_RULE}}", "{{COURSEWORK_TAIL_CHIEF}}", "{{COURSEWORK_TAIL_ASSISTANT}}", "{{COURSEWORK_AGENTS}}", "{{COURSEWORK_HELPER}}", "{{COURSEWORK_SKILL}}"]
        off = self.c.render(" ".join(names), team)
        self.assertIn("explain and give feedback only", off)                    # default: the closed line, unchanged
        self.assertIn("never hand assessed work to a specialist", off)
        team["features"]["open_coursework"] = True
        on = self.c.render(" ".join(names), team)
        self.assertIn("no restrictions", on)
        self.assertNotIn("explain and give feedback only", on)
        self.assertNotIn("never hand assessed work", on)
        self.assertNotIn("{{", on)

    def test_moodle_and_voice_follow_the_features(self):
        import yaml
        team = json.loads(json.dumps(TEAM)); team["features"]["moodle"] = True; team["moodle_url"] = "https://moodle.example.ac.uk"
        team["features"]["voice"] = True; team["voices"] = {"tutor": "VOICE1"}
        self.c.write_config(team, "tutor")
        t = yaml.safe_load((self.home / "profiles/tutor/config.yaml").read_text())
        self.assertTrue(t["mcp_servers"]["moodle"]["enabled"])
        self.assertNotIn("submit", t["mcp_servers"]["moodle"]["tools"]["include"])
        self.assertEqual((t["tts"]["provider"], t["tts"]["voice"]), ("hermes-voice", "VOICE1"))
        team["features"]["voice"] = False; team["features"]["moodle"] = False
        self.c.write_config(team, "tutor")
        t = yaml.safe_load((self.home / "profiles/tutor/config.yaml").read_text())
        self.assertFalse(t["mcp_servers"]["moodle"]["enabled"])
        self.assertNotIn("tts", t)
        self.assertNotIn("hermes-voice", t["plugins"]["enabled"])

    def test_souls_are_written_once_and_edits_kept(self):
        self.c.write_souls(TEAM)
        soul = self.home / "profiles/coach/SOUL.md"
        self.assertIn("Rocky", soul.read_text())
        soul.write_text("my own coach")
        self.c.write_souls(TEAM)
        self.assertEqual(soul.read_text(), "my own coach")

    def test_env_set_replaces_and_is_private(self):
        f = self.home / ".env"
        f.write_text("A=1\nDEEPSEEK_API_KEY=old\n")
        self.c.env_set(f, "DEEPSEEK_API_KEY", "new")
        self.assertEqual(f.read_text(), "A=1\nDEEPSEEK_API_KEY=new\n")
        self.assertEqual(f.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.c.env_has(f, "A"))
        self.assertFalse(self.c.env_has(f, "B"))
        with self.assertRaises(ValueError):
            self.c.env_set(f, "X", "two\nlines")


if __name__ == "__main__":
    unittest.main()
