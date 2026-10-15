"""hermes.json drives every name: GET /api/team, the agent ids the page uses, the owner's name, and the add-ons switched on.
Run: python3 -B -m unittest discover -s dashboard/bridge/tests"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))      # hermesfix
import actions  # noqa: E402
import bridge  # noqa: E402
import team  # noqa: E402
import feeds  # noqa: E402
from hermesfix import TEAM, LOGIN, write_setup  # noqa: E402


class TeamTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "hermes"
        (self.home / "profiles" / "tutor").mkdir(parents=True)
        self.file = write_setup(self.home)
        self.paths = feeds.Paths(hermes_home=str(self.home), kanban_db=str(self.home / "none.db"), gateway_url="http://127.0.0.1:9")
        env = actions.Env(hermes_home=str(self.home), state_dir=str(self.home / "hermes-dash"))
        self.app = bridge.App(bridge.Mem0("http://127.0.0.1:9", "k", "sam"), self.home, [LOGIN], self.paths, env)

    def get(self, route):
        status, _, body = self.app.handle("GET", route, {"tailscale-user-login": LOGIN}, b"")
        return status, json.loads(body)

    def rewrite(self, data):
        self.file.write_text(json.dumps(data))
        st = self.file.stat()                                   # make sure the change is seen even within one clock tick
        os.utime(self.file, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    def test_api_team_contract(self):
        status, out = self.get("/api/team")
        self.assertEqual(status, 200)
        self.assertEqual(set(out), {"owner", "timezone", "chief", "agents", "features"})
        self.assertEqual(out["owner"], {"name": "Sam", "pronouns": "they/them"})          # no login, no Mem0 id
        self.assertEqual((out["chief"], out["timezone"]), ("atlas", "Europe/London"))
        self.assertEqual([(a["id"], a["profile"], a["role"], a["name"], a["title"]) for a in out["agents"]], [
            ("atlas", "default", "chief", "Atlas", "Chief of Staff"), ("sage", "tutor", "tutor", "Sage", "Tutor"),
            ("ivy", "assistant", "assistant", "Ivy", "Assistant"), ("rocky", "coach", "coach", "Rocky", "Coach")])
        self.assertEqual(out["features"], {"voice": False, "gmail": False, "moodle": False, "icloud": False, "backup": False})
        self.assertNotIn("sam@example.com", json.dumps(out))
        self.assertEqual(self.app.handle("GET", "/api/team", {}, b"")[0], 401)               # Tailscale identity still needed

    def test_a_renamed_agent_shows_its_new_name(self):
        (self.home / "profiles" / "tutor" / "profile.yaml").write_text("display_name: Professor Sage\n")
        _, out = self.get("/api/team")
        self.assertEqual(next(a["name"] for a in out["agents"] if a["id"] == "sage"), "Professor Sage")

    def test_changes_are_picked_up_without_a_restart(self):
        self.assertEqual(self.get("/api/inbox")[0], 404)                                    # Gmail add-on off: no inbox
        self.assertEqual(self.get("/api/backup")[0], 404)                                   # backup add-on off: no backup button
        data = json.loads(json.dumps(TEAM))
        data["features"].update(gmail=True, backup=True)
        data["owner"]["name"] = "Samantha"
        self.rewrite(data)
        _, out = self.get("/api/team")
        self.assertEqual((out["owner"]["name"], out["features"]["gmail"], out["features"]["backup"]), ("Samantha", True, True))
        self.assertEqual(self.get("/api/inbox")[0], 200)
        self.assertEqual(self.get("/api/backup")[0], 200)

    def test_names_everywhere_come_from_hermes_json(self):
        _, mesh = self.get("/api/agents")
        self.assertEqual([(a["id"], a["name"]) for a in mesh["agents"]], [("atlas", "Atlas"), ("sage", "Sage")])
        self.assertEqual(team.profile_of(self.home, "rocky"), "coach")
        self.assertEqual(team.profile_of(self.home, "coach"), "coach")                    # a profile passes through
        self.assertEqual(team.agent_of(self.home, "default"), "atlas")
        self.assertEqual(team.name_of(self.home, "assistant"), "Ivy")
        self.assertEqual(team.name_of(self.home, "researcher"), "Researcher")              # added later: by its profile id
        self.assertEqual(team.owner_name(self.home), "Sam")
        self.assertIn("atlas", actions.reserved(actions.Env(hermes_home=str(self.home))))
        self.assertEqual(json.loads(Path(self.home / "hermes.json").read_text())["owner"]["id"], "sam")

    def test_bad_or_missing_file_falls_back(self):
        self.file.unlink()
        c = team.load(self.home)
        self.assertEqual((c["owner"]["name"], team.chief(c)["id"], [a["profile"] for a in c["agents"]]),
                         ("Owner", "chief", ["default", "tutor", "assistant", "coach"]))
        self.rewrite({"owner": {"name": "Jo", "id": "Not OK!"}, "agents": [
            {"id": "Bad Id", "profile": "tutor", "name": "X"},                               # not an agent id
            {"id": "zed", "profile": "tutor", "name": "Zed"},
            {"id": "zed", "profile": "coach", "name": "Twice"},                              # the same id again
            {"id": "boss", "profile": "default", "name": "Boss", "title": "Chief of Staff"}],
            "features": {"gmail": "yes", "backup": True, "rockets": True}})
        c = team.load(self.home)
        self.assertEqual(c["owner"], {"name": "Jo", "id": "owner", "pronouns": "they/them", "tailscale_login": ""})
        self.assertEqual([a["id"] for a in c["agents"]], ["boss", "zed"])                  # the chief first
        self.assertEqual(c["features"], {"voice": False, "gmail": False, "moodle": False, "icloud": False, "backup": True})
        self.rewrite({"agents": [{"id": "zed", "profile": "tutor"}]})                      # no chief: the plain team
        self.assertEqual(team.chief(team.load(self.home))["id"], "chief")
        self.file.write_text("{not json")
        self.assertEqual(team.load(self.home)["owner"]["name"], "Owner")


if __name__ == "__main__":
    unittest.main()
