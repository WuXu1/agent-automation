"""The content studio add-on's kit side: hermeslib fills the four profiles and the chief's hand-off skill from hermes.json. Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vm"))
sys.path.insert(0, str(ROOT / "tests"))
import hermeslib as hl  # noqa: E402
from test_hermeslib import TEAM  # noqa: E402

PROFILES = hl.STUDIO_PROFILES


class StudioAddon(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._home = hl.HOME
        hl.HOME = self.tmp
        self.addCleanup(lambda: setattr(hl, "HOME", self._home))
        self.team = json.loads(json.dumps(TEAM))
        self.team["studio"] = {"name": "Could you?"}
        for p in ("default", *PROFILES):
            d = hl.home_of(p)
            d.mkdir(parents=True, exist_ok=True)
            (d / "config.yaml").write_text("model:\n  default: something-else\nmemory:\n  provider: mem0\n")

    def test_nothing_happens_while_the_feature_is_off(self):
        self.assertEqual(hl.write_studio(self.team), [])
        self.assertFalse((hl.home_of("videoeditor") / "SOUL.md").exists())
        self.assertNotIn("studio-handoff", hl.overlay(self.team, "chief")["skills"]["auto_load"])

    def test_the_four_profiles_get_their_settings_soul_and_manual(self):
        self.team["features"]["studio"] = True
        done = hl.write_studio(self.team)
        self.assertGreaterEqual(len(done), 8)
        for p in PROFILES:
            home = hl.home_of(p)
            cfg = hl.yaml.safe_load((home / "config.yaml").read_text())
            self.assertEqual((cfg["model"]["default"], cfg["skills"]["auto_load"], cfg["memory"]["memory_enabled"], cfg["terminal"]["cwd"]), ("deepseek-flash", ["content-studio"], False, "/data/studio"))
            self.assertEqual(cfg["memory"]["provider"], "")
            soul = (home / "SOUL.md").read_text()
            self.assertIn(self.team["owner"]["name"], soul)
            self.assertIn("Could you?", soul)
            self.assertNotIn("{{", soul)
            manual = (home / "skills" / "creative" / "content-studio" / "SKILL.md").read_text()
            self.assertIn("/data/tools/studio/cy", manual)
            self.assertNotIn("{{", manual)
        curator = hl.yaml.safe_load((hl.home_of("clipcurator") / "config.yaml").read_text())
        self.assertEqual(curator["terminal"]["env_passthrough"], ["STUDIO_GEMINI_KEY"])
        self.assertEqual(hl.yaml.safe_load((hl.home_of("videoeditor") / "config.yaml").read_text())["terminal"]["env_passthrough"], [])
        self.assertEqual(hl.write_studio(self.team), [])                                       # a second run changes nothing

    def test_a_profile_that_was_not_created_yet_is_skipped(self):
        self.team["features"]["studio"] = True
        (hl.home_of("videoeditor") / "config.yaml").unlink()
        done = hl.write_studio(self.team)
        self.assertFalse(any("videoeditor" in d for d in done))

    def test_the_chief_gets_the_handoff_skill_only_while_the_feature_is_on(self):
        self.team["features"]["studio"] = True
        self.assertEqual(hl.overlay(self.team, "chief")["skills"]["auto_load"], ["team-lead", "studio-handoff"])
        self.assertEqual(hl.overlay(self.team, "tutor")["skills"]["auto_load"], ["tutor"])
        hl.write_skills(self.team)
        skill = hl.home_of("default") / "skills" / "creative" / "studio-handoff" / "SKILL.md"
        text = skill.read_text()
        self.assertIn("contentdirector", text)
        self.assertNotIn("{{", text)
        self.team["features"]["studio"] = False
        hl.write_skills(self.team)
        self.assertFalse(skill.exists())

    def test_every_template_resolves_its_placeholders(self):
        for f in list((ROOT / "vm" / "studio").rglob("*.md")):
            hl.render(f.read_text(), self.team)

    def test_the_overlays_are_valid_board_worker_settings(self):
        for p in PROFILES:
            o = hl.yaml.safe_load((ROOT / "vm" / "studio" / "profiles" / p / "config.overlay.yaml").read_text())
            self.assertEqual(o["platform_toolsets"]["cli"], ["terminal", "file", "skills"])
            self.assertFalse(o["memory"]["memory_enabled"])
            self.assertNotIn("telegram", json.dumps(o).lower())                                # board workers never chat


if __name__ == "__main__":
    unittest.main()
