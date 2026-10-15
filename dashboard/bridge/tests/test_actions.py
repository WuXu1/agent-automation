"""Write-side tests: a fake `hermes` CLI and a fake gateway over a fixture Hermes home. No network, no VM."""
from __future__ import annotations

import http.server
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))      # hermesfix
import actions  # noqa: E402
import bridge  # noqa: E402
from hermesfix import write_setup  # noqa: E402

FAKE_HERMES = r'''#!/usr/bin/env python3
"""Just enough of the hermes CLI for the bridge's actions. Records every call in $HERMES_HOME/cli.log."""
import json, os, shutil, sys, tarfile
home = os.environ["HERMES_HOME"]
args = sys.argv[1:]
with open(os.path.join(home, "cli.log"), "a") as f:
    f.write(json.dumps({"args": args, "stdin": sys.stdin.read() or None}) + "\n")
prof = home
if args[:1] == ["-p"]:
    prof = os.path.join(home, "profiles", args[1])
    args = args[2:]
def opt(name):
    return args[args.index(name) + 1] if name in args else None
pos = args[args.index("--") + 1:] if "--" in args else []
if args[:2] == ["profile", "create"]:
    src, name = os.path.join(home, "profiles", opt("--clone-from")), os.path.join(home, "profiles", pos[0])
    shutil.copytree(src, name)
    with open(os.path.join(name, "profile.yaml"), "w") as f:
        f.write("description: " + json.dumps(opt("--description")) + "\ndescription_auto: false\ndisplay_name: Clone\n")
elif args[:2] == ["profile", "describe"]:
    path = os.path.join(home, "profiles", pos[0], "profile.yaml")
    text = open(path).read().splitlines()
    open(path, "w").write("\n".join([l for l in text if not l.startswith("description:")] + ["description: " + json.dumps(opt("--text"))]) + "\n")
elif args[:2] == ["profile", "export"]:
    with tarfile.open(opt("-o"), "w:gz") as t:
        t.add(os.path.join(home, "profiles", pos[0]), arcname=pos[0])
elif args[:2] == ["profile", "delete"]:
    shutil.rmtree(os.path.join(home, "profiles", pos[0]))
elif args[:2] == ["kanban", "create"]:
    print(json.dumps({"id": "t_new12345", "title": pos[0]}))
elif args[:2] in (["curator", "pin"], ["curator", "unpin"]):
    pass
elif args[:2] == ["skills", "search"]:
    print("Searching...\n" + json.dumps([{"name": "pdf", "identifier": "skills-sh/anthropics/skills/pdf", "source": "skills.sh",
                                          "trust_level": "trusted", "description": "Indexed by skills.sh from anthropics/skills · 206,133 installs, PDFs for " + pos[0]}]))
elif args[:2] == ["skills", "inspect"]:
    print("--- preview of " + pos[0])
elif args[:2] == ["skills", "install"]:
    name = pos[0].rsplit("/", 1)[-1]
    d = os.path.join(prof, "skills", "hub", name)
    os.makedirs(d)
    open(os.path.join(d, "SKILL.md"), "w").write("---\nname: " + name + "\ndescription: From the hub.\n---\nSteps.\n")
    lock = os.path.join(prof, "skills", ".hub", "lock.json")
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    data = json.load(open(lock)) if os.path.exists(lock) else {"version": 1, "installed": {}}
    data["installed"][name] = {"source": "skills.sh", "identifier": pos[0], "install_path": "hub/" + name}
    json.dump(data, open(lock, "w"))
    print("Installed " + name)
elif args[:2] == ["skills", "uninstall"]:
    lock = os.path.join(prof, "skills", ".hub", "lock.json")
    data = json.load(open(lock))
    shutil.rmtree(os.path.join(prof, "skills", data["installed"].pop(pos[0])["install_path"]))
    json.dump(data, open(lock, "w"))
elif args[:1] == ["cron"] and args[1:2] and args[1] in ("pause", "resume", "run", "remove", "edit", "create"):
    path = os.path.join(prof, "cron", "jobs.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = json.load(open(path)) if os.path.exists(path) else {"jobs": []}
    flags = dict(a.split("=", 1) for a in args[2:args.index("--")] if a.startswith("--") and "=" in a)
    if args[1] == "create":
        data["jobs"].append({"id": "abcdef012345", "name": flags.get("--name", ""), "schedule": {"kind": "cron", "expr": pos[0], "display": pos[0]},
                             "prompt": pos[1], "deliver": flags.get("--deliver"), "state": "scheduled", "enabled": True})
    else:
        job = next(j for j in data["jobs"] if j["id"] == pos[0])
        if args[1] == "pause":
            job.update(state="paused", enabled=False, paused_at="2026-10-07T01:00:00+01:00")
        elif args[1] == "resume":
            job.update(state="scheduled", enabled=True, paused_at=None)
        elif args[1] == "remove":
            data["jobs"].remove(job)
        elif args[1] == "edit":
            if "--name" in flags: job["name"] = flags["--name"]
            if "--prompt" in flags: job["prompt"] = flags["--prompt"]
            if "--schedule" in flags: job["schedule"] = {"kind": "cron", "expr": flags["--schedule"], "display": flags["--schedule"]}
    json.dump(data, open(path, "w"))
elif args[:2] == ["kanban", "unblock"]:
    if pos[0] == "t_missing0":
        print("no such task", file=sys.stderr); sys.exit(3)
else:
    print("unknown command", file=sys.stderr); sys.exit(2)
'''

CONFIG = """\
model:
  default: deepseek-flash   # chosen 1 Oct
  provider: deepseek
agent:
  max_turns: 500
  reasoning_effort: medium
mcp_servers:
  docs:
    url: https://example.invalid
    enabled: false
  moodle:
    command: x
    tools:
      include:
        - get_courses
platform_toolsets:
  cli:
    - hermes-cli
  telegram:
    - hermes-telegram
approvals:
  destructive_slash_confirm: false
"""


class Gateway:
    def __init__(self, key: str):
        self.seen: list[tuple[str, str, dict | None]] = []
        gw = self

        class H(http.server.BaseHTTPRequestHandler):
            def _do(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n)) if n else None
                gw.seen.append((self.command, self.path, body))
                if self.headers.get("Authorization") != f"Bearer {key}":
                    code, out = 401, {"error": "bad key"}
                elif self.command == "POST" and self.path == "/v1/runs":
                    code, out = 200, {"run_id": "run_abc1"}
                elif self.path == "/v1/runs/run_abc1":
                    code, out = 200, {"status": "completed", "output": "On it, Sam."}
                else:
                    code, out = 404, {}
                data = json.dumps(out).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _do

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class ActionsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "hermes"
        coach = self.home / "profiles" / "coach"
        coach.mkdir(parents=True)
        write_setup(self.home)
        (self.home / ".env").write_text("API_SERVER_KEY=chief-key\nOTHER=x\n")
        (self.home / "config.yaml").write_text(CONFIG)
        (coach / "config.yaml").write_text(CONFIG)
        (coach / ".env").write_text("API_SERVER_KEY=coach-key\nMEM0_AGENT_ID=rocky\nMEM0_API_KEY=m\n")
        (coach / "SOUL.md").write_text("You are Rocky.\n")
        (coach / "profile.yaml").write_text("description: 'Training and\n  swimming.'\ndescription_auto: false\ndisplay_name: Rocky\nui_meta:\n  hermes-bots:\n    title: Rocky\n")
        fake = Path(tmp.name) / "hermes-cli"
        fake.write_text(FAKE_HERMES.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.gw = Gateway("chief-key")
        self.addCleanup(self.gw.close)
        self.env = actions.Env(hermes_home=str(self.home), hermes_bin=str(fake), hermes_python=sys.executable,
                               state_dir=str(self.home / "hermes-dash"), gateway_url=self.gw.url,
                               extra_env={"PATH": os.environ.get("PATH", "/usr/bin")})

    def cli_calls(self) -> list[dict]:
        log = self.home / "cli.log"
        return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

    def actions_log(self) -> list[dict]:
        log = self.home / "hermes-dash" / "actions.log"
        return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

    def backups(self, folder: Path) -> list[str]:
        return sorted(p.name for p in folder.iterdir() if ".bak-before-dash-" in p.name)

    # text edits
    def test_set_block_value_keeps_comments_and_adds_missing_keys(self):
        out = actions.set_block_value(CONFIG, "model", "default", "deepseek-chat")
        self.assertIn("  default: deepseek-chat   # chosen 1 Oct", out)
        out = actions.set_block_value(out, "agent", "reasoning_effort", "high")
        self.assertIn("  reasoning_effort: high", out)
        self.assertEqual(out.count("reasoning_effort"), 1)
        self.assertIn("  temperature: 1", actions.set_block_value("model:\n  default: x\n", "model", "temperature", "1"))
        self.assertIn("newblock:\n  k: v", actions.set_block_value("a: 1\n", "newblock", "k", "v"))

    def test_set_mcp_enabled(self):
        out = actions.set_mcp_enabled(CONFIG, "docs", True)
        self.assertIn("  docs:\n    url: https://example.invalid\n    enabled: true", out)
        out = actions.set_mcp_enabled(out, "moodle", False)             # no enabled line yet: added under the server
        self.assertIn("  moodle:\n    enabled: false\n    command: x", out)
        with self.assertRaises(actions.ActionError):
            actions.set_mcp_enabled(CONFIG, "nothing", True)

    # create
    def test_create_agent(self):
        out = actions.create_agent(self.env, {"profile": "nora", "name": "Nora", "description": "Research and reading.",
                                              "soul": "You are Nora, Sam's researcher.", "from": "coach", "model": "deepseek-chat", "effort": "high"})
        d = self.home / "profiles" / "nora"
        self.assertEqual((out["profile"], out["name"], out["model"], out["effort"]), ("nora", "Nora", "deepseek-chat", "high"))
        self.assertEqual(out["description"], "Research and reading.")
        self.assertEqual((d / "SOUL.md").read_text(), "You are Nora, Sam's researcher.\n")
        env_text = (d / ".env").read_text()
        self.assertNotIn("coach-key", env_text)                         # its own API key
        self.assertIn("MEM0_AGENT_ID=nora", env_text)
        self.assertEqual(stat.S_IMODE((d / ".env").stat().st_mode), 0o600)
        create = self.cli_calls()[0]["args"]
        self.assertEqual(create[:2], ["profile", "create"])
        self.assertEqual(create[-2:], ["--", "nora"])
        self.assertIn("--no-alias", create)
        self.assertEqual(actions.restart_state(self.env, None)["needed"], ["new agent Nora (nora)"])
        [entry] = self.actions_log()
        self.assertEqual(entry["what"], "agent-created")
        self.assertNotIn("researcher", json.dumps(entry))               # a SOUL's text is never logged

    def test_create_refuses(self):
        for args, why in (({"profile": "Nora!", "name": "N", "description": "d"}, "id"),
                          ({"profile": "default", "name": "N", "description": "d"}, "reserved"),
                          ({"profile": "atlas", "name": "N", "description": "d", "from": "coach"}, "a team id from hermes.json"),
                          ({"profile": "sam", "name": "N", "description": "d", "from": "coach"}, "the owner's Mem0 id"),
                          ({"profile": "coach", "name": "N", "description": "d", "from": "coach"}, "exists"),
                          ({"profile": "nora", "name": "N", "description": "d", "from": "default"}, "the chief as source"),
                          ({"profile": "nora", "name": "N", "description": "", "from": "coach"}, "no description"),
                          ({"profile": "nora", "name": "N", "description": "d", "from": "coach", "model": "x; rm -rf /"}, "model")):
            with self.assertRaises(actions.ActionError, msg=why):
                actions.create_agent(self.env, args)
        self.assertFalse((self.home / "profiles" / "nora").exists())

    # update
    def test_update_model_effort_soul_description_name(self):
        out = actions.update_agent(self.env, "coach", {"model": "deepseek-chat", "effort": "low", "soul": "New soul.",
                                                       "description": "Swimming coach.", "name": "Coach Rocky"})
        self.assertEqual(set(out["changed"]), {"model", "effort", "soul", "description", "name"})
        self.assertEqual((out["model"], out["effort"], out["name"], out["description"]), ("deepseek-chat", "low", "Coach Rocky", "Swimming coach."))
        coach = self.home / "profiles" / "coach"
        self.assertIn("    title: \"Coach Rocky\"", (coach / "profile.yaml").read_text())
        self.assertTrue(any(b.startswith("config.yaml.") for b in self.backups(coach)))
        self.assertTrue(any(b.startswith("SOUL.md.") for b in self.backups(coach)))
        self.assertEqual(actions.restart_state(self.env, None)["needed"], [])   # these apply without a restart

    def test_update_mcp_marks_restart(self):
        out = actions.update_agent(self.env, "coach", {"mcp": {"docs": True, "moodle": False}})
        self.assertEqual(out["changed"], ["mcp"])
        text = (self.home / "profiles" / "coach" / "config.yaml").read_text()
        self.assertIn("  docs:\n    url: https://example.invalid\n    enabled: true", text)
        self.assertEqual(actions.restart_state(self.env, None)["needed"], ["MCP servers changed on coach"])
        self.assertEqual(actions.restart_state(self.env, 4_102_444_800_000)["needed"], [])   # a gateway start after it clears it

    def test_a_failed_check_changes_nothing(self):
        coach = self.home / "profiles" / "coach"
        before = (coach / "config.yaml").read_text()
        with mock.patch.object(actions, "check_yaml", side_effect=actions.ActionError(500, "would not parse")):
            with self.assertRaises(actions.ActionError):
                actions.update_agent(self.env, "coach", {"model": "deepseek-chat"})
        self.assertEqual((coach / "config.yaml").read_text(), before)
        self.assertEqual(self.backups(coach), [])
        self.assertEqual([p.name for p in coach.iterdir() if p.name.startswith(".config.yaml.dash")], [])

    def test_check_yaml_really_parses(self):
        bad = self.home / "bad.yaml"
        bad.write_text("model:\n  default: [unclosed\n")
        with self.assertRaises(actions.ActionError):
            actions.check_yaml(self.env, bad, {"model.default": "x"})
        good = self.home / "good.yaml"
        good.write_text(CONFIG)
        actions.check_yaml(self.env, good, {"model.default": "deepseek-flash", "mcp_servers.docs.enabled": False})

    def test_update_refuses(self):
        for args in ({"effort": "extreme"}, {"mcp": {"docs": "yes"}}, {"mcp": {"../x": True}}, {}, {"soul": ""}):
            with self.assertRaises(actions.ActionError, msg=str(args)):
                actions.update_agent(self.env, "coach", args)
        with self.assertRaises(actions.ActionError):
            actions.update_agent(self.env, "nobody", {"effort": "low"})

    # delete
    def test_delete_archives_first(self):
        with self.assertRaises(actions.ActionError):
            actions.delete_agent(self.env, "coach", {"confirm": "rocky"})
        with self.assertRaises(actions.ActionError):
            actions.delete_agent(self.env, "default", {"confirm": "default"})
        out = actions.delete_agent(self.env, "coach", {"confirm": "coach"})
        self.assertTrue(Path(out["archive"]).exists())
        self.assertFalse((self.home / "profiles" / "coach").exists())
        self.assertEqual([c["args"][:2] for c in self.cli_calls()], [["profile", "export"], ["profile", "delete"]])

    # the chief and the board
    def test_brief_chief(self):
        out = actions.brief_chief(self.env, {"text": "Book the lane for Friday."})
        self.assertEqual(out, {"runId": "run_abc1"})
        _, path, body = self.gw.seen[0]
        self.assertEqual((path, body["input"], body["session_id"]), ("/v1/runs", "Book the lane for Friday.", "hermes-dash"))
        self.assertIn("This message is from Sam", body["instructions"])       # the owner's name from hermes.json
        self.assertEqual(actions.chief_run(self.env, "run_abc1"), {"status": "completed", "output": "On it, Sam."})
        with self.assertRaises(actions.ActionError):
            actions.chief_run(self.env, "../../x")
        with self.assertRaises(actions.ActionError):
            actions.brief_chief(self.env, {"text": "  "})

    def test_create_card(self):
        out = actions.create_card(self.env, {"title": "--triage is not a flag here", "body": "Line one\n--assignee x", "assignee": "coach", "priority": 9})
        self.assertEqual(out, {"id": "t_new12345"})
        call = self.cli_calls()[0]
        self.assertEqual(call["args"][-2:], ["--", "--triage is not a flag here"])   # a title can never become an option
        self.assertIn("--assignee", call["args"])
        self.assertEqual(call["stdin"], "Line one\n--assignee x")
        actions.create_card(self.env, {"title": "Sort this"})
        self.assertIn("--triage", self.cli_calls()[1]["args"])
        for bad in ({"title": "x", "assignee": "nobody"}, {"title": "x", "priority": 500}, {"title": ""}):
            with self.assertRaises(actions.ActionError):
                actions.create_card(self.env, bad)

    def test_answer_card(self):
        actions.answer_card(self.env, "t_abc12345", {"text": "Yes, the early lane."})
        self.assertEqual(self.cli_calls()[0]["args"], ["kanban", "unblock", "--reason=Sam (dashboard): Yes, the early lane.", "--", "t_abc12345"])
        with self.assertRaises(actions.ActionError):
            actions.answer_card(self.env, "t_missing0", {"text": "x"})
        with self.assertRaises(actions.ActionError):
            actions.answer_card(self.env, "; rm", {"text": "x"})

    def test_restart_request(self):
        actions.request_restart(self.env)
        self.assertTrue(actions.restart_state(self.env, None)["requested"])

    # the org: several levels
    def _new(self, profile, boss=None):
        args = {"profile": profile, "name": profile.capitalize(), "description": f"{profile.capitalize()}: does {profile} things.", "from": "coach"}
        if boss:
            args["reportsTo"] = boss
        return actions.create_agent(self.env, args)

    def team(self, profile):
        path = self.env.profile_dir(profile) / actions.TEAM_SKILL
        return path.read_text() if path.exists() else None

    def test_three_levels_wire_up_the_leads(self):
        self._new("nora")                                          # under the chief
        self._new("lena", boss="nora")                             # under Nora
        self._new("ivo", boss="lena")                              # under Lena: three levels below the chief
        org = actions.load_org(self.env)
        profiles = self.env.profiles()
        self.assertEqual([actions.manager_of(org, profiles, p) for p in ("nora", "lena", "ivo", "coach", "default")],
                         ["default", "nora", "lena", "default", None])
        chief, nora, lena = self.team("default"), self.team("nora"), self.team("lena")
        self.assertIn("`nora`", chief)
        self.assertIn("`coach`", chief)                            # the chief's list has everyone directly under it
        self.assertNotIn("`lena`", chief)
        self.assertIn("You are Atlas (`default`)", chief)          # names from hermes.json
        self.assertIn("You report to Sam.", chief)
        self.assertIn("still needs Sam's yes", chief)
        self.assertIn("`lena`", nora)
        self.assertIn("leads 1", nora)                             # Lena has her own team
        self.assertIn("You report to Atlas", nora)
        self.assertIn("You report to Nora (`nora`)", lena)
        self.assertIsNone(self.team("ivo"))                        # nobody under Ivo
        cfg = (self.env.profile_dir("nora") / "config.yaml").read_text()
        self.assertEqual(actions.toolset_items(cfg, "telegram"), ["hermes-telegram", "kanban"])
        self.assertEqual(actions.toolset_items(cfg, "cli"), ["hermes-cli", "kanban"])
        self.assertNotIn("kanban", (self.env.profile_dir("ivo") / "config.yaml").read_text().split("platform_toolsets:")[1])
        self.assertEqual(actions.agent_detail(self.env, "lena")["reportsTo"], "nora")
        pins = [c["args"] for c in self.cli_calls() if "curator" in c["args"]]
        self.assertIn(["-p", "nora", "curator", "pin", "my-team"], pins)       # the curator never touches a generated list
        self.assertIn(["curator", "pin", "my-team"], pins)                      # the chief's (default profile, no -p)
        self.assertEqual(len(pins), len(set(map(tuple, pins))))                  # each pinned once

    def test_moves_and_loops(self):
        self._new("nora")
        self._new("lena", boss="nora")
        with self.assertRaises(actions.ActionError):
            actions.update_agent(self.env, "nora", {"reportsTo": "lena"})        # under her own report
        with self.assertRaises(actions.ActionError):
            actions.update_agent(self.env, "nora", {"reportsTo": "nora"})
        with self.assertRaises(actions.ActionError):
            actions.update_agent(self.env, "default", {"reportsTo": "nora"})     # the chief reports to the owner
        with self.assertRaises(actions.ActionError):
            actions.update_agent(self.env, "lena", {"reportsTo": "nobody"})
        out = actions.update_agent(self.env, "lena", {"reportsTo": "default"})   # back under the chief
        self.assertEqual(out["changed"], ["lead"])
        self.assertIsNone(self.team("nora"))                                      # Nora has nobody now
        cfg = (self.env.profile_dir("nora") / "config.yaml").read_text()
        self.assertEqual(actions.toolset_items(cfg, "telegram"), ["hermes-telegram"])   # and loses the board tools we gave her
        self.assertIn("`lena`", self.team("default"))

    def test_deleting_a_lead_moves_its_team_up(self):
        self._new("nora")
        self._new("lena", boss="nora")
        self._new("ivo", boss="lena")
        out = actions.delete_agent(self.env, "lena", {"confirm": "lena"})
        self.assertEqual((out["movedTo"], out["moved"]), ("nora", ["ivo"]))
        org = actions.load_org(self.env)
        self.assertEqual(actions.manager_of(org, self.env.profiles(), "ivo"), "nora")
        self.assertIn("`ivo`", self.team("nora"))

    def test_a_hand_written_my_team_is_left_alone(self):
        path = self.env.profile_dir("coach") / actions.TEAM_SKILL
        path.parent.mkdir(parents=True)
        path.write_text("---\nname: my-team\n---\nWritten by hand.\n")
        self._new("nora", boss="coach")
        self.assertEqual(path.read_text(), "---\nname: my-team\n---\nWritten by hand.\n")

    def test_feed_reports_the_org(self):
        import feeds
        self._new("nora")
        self._new("lena", boss="nora")
        out = feeds.agents(feeds.Paths(hermes_home=str(self.home), kanban_db="/nonexistent", gateway_url="http://127.0.0.1:9"))
        by = {a["id"]: a["reportsTo"] for a in out["agents"]}
        self.assertEqual(by, {"atlas": None, "rocky": "atlas", "nora": "atlas", "lena": "nora"})

    # through the bridge
    def test_routes_need_the_page_header_and_json(self):
        app = bridge.App(bridge.Mem0("http://127.0.0.1:9", "k", "sam"), self.home, ["sam@x"], bridge.feeds.Paths(hermes_home=str(self.home)), env=self.env)
        h = {"tailscale-user-login": "sam@x", "content-type": "application/json"}
        body = json.dumps({"effort": "low"}).encode()
        self.assertEqual(app.handle("PUT", "/api/agents/coach", h, body)[0], 403)              # no X-Hermes-Dash
        ok = {**h, "x-hermes-dash": "1"}
        self.assertEqual(app.handle("PUT", "/api/agents/coach", {**ok, "content-type": "text/plain"}, body)[0], 400)
        status, _, out = app.handle("PUT", "/api/agents/coach", ok, body)
        self.assertEqual((status, json.loads(out)["effort"]), (200, "low"))
        status, _, out = app.handle("GET", "/api/agents/coach", ok, b"")
        self.assertEqual(json.loads(out)["soul"], "You are Rocky.\n")
        status, _, out = app.handle("GET", "/api/agents/rocky", ok, b"")              # the page may use the team's agent id
        self.assertEqual((status, json.loads(out)["profile"]), (200, "coach"))
        self.assertEqual(app.handle("GET", "/api/agents/nobody", ok, b"")[0], 404)
        self.assertEqual(app.handle("DELETE", "/api/agents/atlas", ok, json.dumps({"confirm": "default"}).encode())[0], 403)
        self.assertEqual(app.handle("POST", "/api/restart", ok, b"{}")[0], 200)
        # agents are added and moved only through Claude
        new = json.dumps({"profile": "nora", "name": "Nora", "description": "x", "from": "coach"}).encode()
        self.assertEqual(app.handle("POST", "/api/agents", ok, new)[0], 405)
        self.assertEqual(app.handle("PUT", "/api/agents/coach", ok, json.dumps({"reportsTo": "default"}).encode())[0], 405)
        self.assertFalse((self.home / "profiles" / "nora").exists())


if __name__ == "__main__":
    unittest.main()
