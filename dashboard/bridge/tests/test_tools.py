"""Skills, MCP servers, network jobs and backup-now: same fixture Hermes home and fake CLI as test_actions. No network."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import actions  # noqa: E402
import jobs  # noqa: E402
import tools  # noqa: E402
import test_actions as fixture  # noqa: E402  (the module, so its tests are not collected twice)


class ToolsTest(fixture.ActionsTest):
    # reuse ActionsTest's fixture, not its tests (they run once, in test_actions)
    locals().update({n: None for n in dir(fixture.ActionsTest) if n.startswith("test_")})

    def setUp(self):
        super().setUp()
        sk = self.home / "profiles" / "coach" / "skills"
        (sk / "productivity" / "deadline-reminders").mkdir(parents=True)
        (sk / "productivity" / "deadline-reminders" / "SKILL.md").write_text("---\nname: deadline-reminders\ndescription: Reminders.\n---\nBody\n")
        (sk / "creative" / "p5js").mkdir(parents=True)
        (sk / "creative" / "p5js" / "SKILL.md").write_text("---\nname: p5js\ndescription: Sketches.\n---\nBody\n")
        (sk / ".hub").mkdir()
        (sk / ".bundled_manifest").write_text("p5js:abc\n")
        tools._catalog.update(at=0.0, data=None)

    # skills
    def test_list_and_switch_skills(self):
        out = tools.list_skills(self.env, "coach")
        by = {s["name"]: s for s in out["skills"]}
        self.assertEqual((by["p5js"]["source"], by["deadline-reminders"]["source"]), ("builtin", "local"))
        self.assertTrue(all(s["enabled"] for s in out["skills"]))
        tools.set_skill_enabled(self.env, "coach", "p5js", False)
        cfg = self.env.profile_dir("coach") / "config.yaml"
        self.assertEqual(tools.yaml_get(self.env, cfg, "skills.disabled")["skills.disabled"], ["p5js"])
        self.assertIn("default: deepseek-flash   # chosen 1 Oct", cfg.read_text())     # the rest of the file as it was
        out = tools.set_skill_enabled(self.env, "coach", "deadline-reminders", False)
        self.assertEqual(sorted(s["name"] for s in out["skills"] if not s["enabled"]), ["deadline-reminders", "p5js"])
        tools.set_skill_enabled(self.env, "coach", "p5js", True)
        self.assertEqual(tools.yaml_get(self.env, cfg, "skills.disabled")["skills.disabled"], ["deadline-reminders"])
        self.assertTrue(list(cfg.parent.glob("config.yaml.bak-before-dash-skills-*")))

    def test_disabled_list_written_as_a_block_list_is_replaced(self):
        cfg = self.env.profile_dir("coach") / "config.yaml"
        cfg.write_text(cfg.read_text() + "skills:\n  disabled:\n    - p5js\n    - old\n  creation_nudge_interval: 15\n")
        tools.set_skill_enabled(self.env, "coach", "old", True)
        got = tools.yaml_get(self.env, cfg, "skills.disabled", "skills.creation_nudge_interval")
        self.assertEqual((got["skills.disabled"], got["skills.creation_nudge_interval"]), (["p5js"], 15))

    def test_create_and_remove_own_skill(self):
        tools.create_skill(self.env, "coach", {"name": "rain-plan", "description": "When rain stops a run.", "body": "1. Check the forecast."})
        path = self.env.profile_dir("coach") / "skills" / "custom" / "rain-plan" / "SKILL.md"
        self.assertIn('description: "When rain stops a run."', path.read_text())
        with self.assertRaises(actions.ActionError):
            tools.create_skill(self.env, "coach", {"name": "rain-plan", "description": "x", "body": "y"})
        with self.assertRaises(actions.ActionError):
            tools.create_skill(self.env, "coach", {"name": "../x", "description": "x", "body": "y"})
        tools.remove_skill(self.env, "coach", "rain-plan")
        self.assertFalse(path.exists())
        self.assertTrue(list((Path(self.env.state_dir) / "archive" / "skills").glob("coach-rain-plan-*")))
        with self.assertRaises(actions.ActionError):
            tools.remove_skill(self.env, "coach", "p5js")      # Hermes' own: switch off instead

    def test_hub_install_through_a_job_then_uninstall(self):
        job = jobs.submit(self.env, "skill-install", {"profile": "coach", "identifier": "skills-sh/anthropics/skills/pdf"})["job"]
        self.assertEqual(jobs.status(self.env, job), {"state": "running"})
        self.assertEqual(jobs.run_once(self.env), 1)
        done = jobs.status(self.env, job)
        self.assertTrue(done["ok"], done)
        hub_dir = self.env.profile_dir("coach") / "skills" / "hub" / "pdf"
        (hub_dir / "forms").mkdir()
        (hub_dir / "forms" / "SKILL.md").write_text("---\nname: pdf\n---\nA file inside the skill, not a skill.\n")
        listed = tools.list_skills(self.env, "coach")["skills"]
        self.assertEqual([s["name"] for s in listed].count("pdf"), 1)
        by = {s["name"]: s for s in listed}
        self.assertEqual((by["pdf"]["source"], by["pdf"]["identifier"]), ("hub", "skills-sh/anthropics/skills/pdf"))
        install = [c["args"] for c in self.cli_calls() if "install" in c["args"]][0]
        self.assertEqual(install, ["-p", "coach", "skills", "install", "--yes", "--", "skills-sh/anthropics/skills/pdf"])   # never --force
        tools.remove_skill(self.env, "coach", "pdf")
        self.assertNotIn("pdf", {s["name"] for s in tools.list_skills(self.env, "coach")["skills"]})

    def test_search_job_and_bad_jobs(self):
        job = jobs.submit(self.env, "skill-search", {"profile": "atlas", "query": "pdf files"})["job"]
        jobs.run_once(self.env)
        out = jobs.status(self.env, job)
        self.assertEqual(out["results"][0]["identifier"], "skills-sh/anthropics/skills/pdf")
        self.assertEqual([c["args"] for c in self.cli_calls()][-1], ["skills", "search", "--source", "skills-sh", "--json", "--limit", "25", "--", "pdf files"])
        self.assertEqual((out["results"][0]["repo"], out["results"][0]["installs"]), ("anthropics/skills", 206133))
        for kind, args in [("skill-install", {"profile": "coach", "identifier": "--force"}), ("rm", {}),
                           ("skill-install", {"profile": "coach", "identifier": "clawhub/someone/pdf"}),          # skills.sh only
                           ("skill-search", {"profile": "nobody", "query": "x"}), ("enhance", {"field": "bio", "text": "x"})]:
            with self.assertRaises(actions.ActionError, msg=kind):
                jobs.submit(self.env, kind, args)
        # a request dropped in the folder by hand is checked again by the runner
        d = jobs.jobs_dir(self.env)
        (d / "0123456789abcdef.req.json").write_text(json.dumps({"kind": "skill-install", "args": {"profile": "coach", "identifier": "-x"}}))
        jobs.run_once(self.env)
        self.assertFalse(jobs.status(self.env, "0123456789abcdef")["ok"])
        with self.assertRaises(actions.ActionError):
            jobs.status(self.env, "../../etc/passwd")

    def test_enhance(self):
        seen = {}

        def llm(env_file, system, user, max_tokens, **kw):
            seen.update(system=system, user=user, tokens=max_tokens, env=env_file)
            return "```\nNora: research and reading.\n```"
        a = jobs._check("enhance", {"field": "description", "text": "does reading", "name": "Nora"}, self.env.profiles())
        self.assertEqual(jobs.do_enhance(self.env, a, llm)["text"], "Nora: research and reading.")
        self.assertIn("Agent: Nora.", seen["user"])
        self.assertEqual(seen["tokens"], 300)
        self.assertIn("Sam's personal assistant team", seen["system"])                 # the owner's name from hermes.json
        self.assertIn("Sam's draft:", seen["user"])
        with self.assertRaises(actions.ActionError):
            jobs.submit(self.env, "transcript", {"conversation_id": "conv_abc123", "call_id": 7})   # no phone line in the kit

    # MCP servers
    def test_add_custom_copy_and_remove_servers(self):
        out = tools.add_server(self.env, {"source": "custom", "name": "weather", "profiles": ["coach"], "transport": "http",
                                          "url": "https://mcp.example.invalid/mcp",
                                          "headers": [{"name": "Authorization", "value": "Bearer s3cret", "secret": True}]})
        self.assertEqual(out["added"], ["coach"])
        coach = self.env.profile_dir("coach")
        got = tools.yaml_get(self.env, coach / "config.yaml", "mcp_servers.weather", "mcp_servers.moodle.tools.include")
        self.assertEqual(got["mcp_servers.weather"], {"url": "https://mcp.example.invalid/mcp", "enabled": True,
                                                      "headers": {"Authorization": "${MCP_WEATHER_AUTHORIZATION}"}})
        self.assertEqual(got["mcp_servers.moodle.tools.include"], ["get_courses"])         # neighbours untouched
        self.assertIn("MCP_WEATHER_AUTHORIZATION=Bearer s3cret", (coach / ".env").read_text())
        self.assertNotIn("s3cret", json.dumps(out))                                         # never back to the page
        self.assertNotIn("s3cret", (Path(self.env.state_dir) / "actions.log").read_text())
        row = next(r for r in out["servers"] if r["name"] == "weather")
        self.assertEqual((row["agents"], row["transport"], row["auth"]), ({"coach": True}, "http", "headers"))
        # copy onto the chief (by team id): the secret value goes across on the VM
        out = tools.add_server(self.env, {"source": "copy", "name": "weather", "from": "coach", "profiles": ["atlas", "coach"]})
        self.assertEqual((out["added"], out["skipped"]), (["default"], ["coach"]))
        self.assertIn("MCP_WEATHER_AUTHORIZATION=Bearer s3cret", (self.home / ".env").read_text())
        self.assertIn("weather", actions.restart_state(self.env, None)["needed"][-1])
        tools.remove_server(self.env, "coach", "weather")
        self.assertIsNone(tools.yaml_get(self.env, coach / "config.yaml", "mcp_servers.weather")["mcp_servers.weather"])
        self.assertEqual(next(r for r in tools.list_servers(self.env)["servers"] if r["name"] == "weather")["agents"], {"default": True})

    def test_server_checks(self):
        bad = [{"source": "custom", "name": "Bad Name", "profiles": ["coach"], "transport": "http", "url": "https://x.invalid"},
               {"source": "custom", "name": "ok", "profiles": [], "transport": "http", "url": "https://x.invalid"},
               {"source": "custom", "name": "ok", "profiles": ["coach"], "transport": "http", "url": "file:///etc/passwd"},
               {"source": "custom", "name": "ok", "profiles": ["coach"], "transport": "stdio", "command": "sh -c 'rm -rf /'"},
               {"source": "copy", "name": "nothere", "from": "coach", "profiles": ["atlas"]},
               {"source": "catalog", "name": "x", "entry": "nope", "profiles": ["coach"]}]
        for args in bad:
            with self.assertRaises(actions.ActionError, msg=json.dumps(args)):
                tools.add_server(self.env, args)
        out = tools.add_server(self.env, {"source": "custom", "name": "files", "profiles": ["coach"], "transport": "stdio",
                                          "command": "npx", "args": ["-y", "@example/files"],
                                          "env": [{"name": "ROOT", "value": "/data"}, {"name": "TOKEN", "value": "t0k", "secret": True}]})
        got = tools.yaml_get(self.env, self.env.profile_dir("coach") / "config.yaml", "mcp_servers.files")["mcp_servers.files"]
        self.assertEqual(got["env"], {"ROOT": "/data", "TOKEN": "${MCP_FILES_TOKEN}"})
        self.assertEqual(next(r for r in out["servers"] if r["name"] == "files")["env"], ["ROOT", "TOKEN"])

    def test_catalog_entry(self):
        tools._catalog.update(at=9e18, data=[
            {"name": "deepwiki", "description": "Repo wiki", "transport": "http", "auth": "none", "url": "https://mcp.deepwiki.invalid/mcp",
             "needsInstall": False, "postInstall": "No account needed.", "env": [], "config": {"url": "https://mcp.deepwiki.invalid/mcp"}},
            {"name": "keyed", "description": "", "transport": "http", "auth": "api_key", "url": "https://k.invalid", "needsInstall": False,
             "postInstall": "", "env": [{"name": "KEYED_API_KEY", "prompt": "Keyed API key", "secret": True, "required": True}],
             "config": {"url": "https://k.invalid", "headers": {"Authorization": "Bearer ${KEYED_API_KEY}"}}},
            {"name": "gitty", "description": "", "transport": "stdio", "auth": "none", "url": None, "needsInstall": True,
             "postInstall": "", "env": [], "config": None}])
        out = tools.add_server(self.env, {"source": "catalog", "name": "deepwiki", "entry": "deepwiki", "profiles": ["coach"]})
        self.assertEqual(out["note"], "No account needed.")
        with self.assertRaises(actions.ActionError):
            tools.add_server(self.env, {"source": "catalog", "name": "keyed", "entry": "keyed", "profiles": ["coach"]})   # key missing
        tools.add_server(self.env, {"source": "catalog", "name": "keyed", "entry": "keyed", "profiles": ["coach"], "secrets": {"KEYED_API_KEY": "abc"}})
        self.assertIn("KEYED_API_KEY=abc", (self.env.profile_dir("coach") / ".env").read_text())
        with self.assertRaises(actions.ActionError):
            tools.add_server(self.env, {"source": "catalog", "name": "gitty", "entry": "gitty", "profiles": ["coach"]})

    # backup now
    def test_backup_request(self):
        self.assertEqual(actions.backup_state(self.env, {"ActiveState": "inactive", "Result": "success"})["active"], False)
        actions.request_backup(self.env, {"ActiveState": "inactive"})
        self.assertTrue(actions.backup_state(self.env, {})["requested"])
        with self.assertRaises(actions.ActionError):
            actions.request_backup(self.env, {"ActiveState": "activating"})
        (Path(self.env.state_dir) / "backup.status").write_text(json.dumps({"at": __import__("time").time(), "state": "started"}))
        with self.assertRaises(actions.ActionError):
            actions.request_backup(self.env, {"ActiveState": "inactive"})


if __name__ == "__main__":
    unittest.main()
