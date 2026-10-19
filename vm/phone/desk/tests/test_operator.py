import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from desk import agent_config, calls, config, db, eleven, number, push_agent, report, twilio, util  # noqa: E402
from fake_elevenlabs import FakeElevenLabs  # noqa: E402
from helpers import FakeServer  # noqa: E402

VOICE = Path(__file__).resolve().parents[2]
STYLE = (VOICE / "STYLE.md").read_text()
TEMPLATE = (VOICE / "agents" / "chief.prompt.md").read_text()
GUEST_TEMPLATE = (VOICE / "agents" / "chief-guest.prompt.md").read_text()
BASE = "https://desk.example:8443"
TOOL_SECRET = "tool-secret-value"


class PushTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = str(Path(self.tmp.name) / "state")
        Path(self.state).mkdir()
        (Path(self.state) / "secrets.env").write_text(f"DESK_TOOL_SECRET={TOOL_SECRET}\n")
        config.update_config_json(self.state, {"public_base": BASE})
        self.fake = FakeElevenLabs()
        self.fake.server.__enter__()
        self.addCleanup(self.fake.server.__exit__, None, None, None)
        self.said = []

    def pusher(self, apply=True, **kw):
        cfg = config.load(self.state, self.tmp.name)             # as the real script does: secrets come from the files
        client = eleven.Eleven("KEY", base=self.fake.server.url)
        return push_agent.Pusher(client, cfg, kw.pop("template", TEMPLATE), STYLE, apply=apply, say=self.said.append, **kw), cfg

    def test_the_first_push_creates_everything_and_wires_it_together(self):
        pusher, cfg = self.pusher()
        ids = pusher.run()
        self.assertEqual([s["value"] for s in self.fake.secrets.values()], [TOOL_SECRET])
        self.assertEqual(len(self.fake.tools), len(agent_config.TOOL_NAMES))
        for tool in self.fake.tools.values():
            self.assertEqual(tool["api_schema"]["request_headers"]["X-Desk-Secret"], {"secret_id": ids["secret_id"]})
        (agent,) = self.fake.agents.values()
        self.assertEqual(agent["conversation_config"]["agent"]["prompt"]["tool_ids"], [ids["tool_ids"][n] for n in agent_config.TOOL_NAMES])
        self.assertEqual(agent["platform_settings"]["workspace_overrides"]["webhooks"]["post_call_webhook_id"], ids["webhook_id"])
        self.assertEqual(agent["conversation_config"]["agent"]["prompt"]["llm"], agent_config.LLM)
        (hook,) = self.fake.webhooks.values()
        self.assertEqual((hook["url"], hook["auth"]), (BASE + "/postcall", "hmac"))
        saved = config.read_env_file(Path(self.state) / "secrets.env")
        self.assertEqual(saved["ELEVENLABS_WEBHOOK_SECRET"], f"whsec_{ids['webhook_id']}")
        self.assertEqual(json.loads((Path(self.state) / "config.json").read_text())["agent_id"], ids["agent_id"])
        everything = "\n".join(self.said)
        for secret in (TOOL_SECRET, saved["ELEVENLABS_WEBHOOK_SECRET"]):
            self.assertNotIn(secret, everything)

    def test_pushing_again_updates_in_place_without_duplicates(self):
        self.pusher()[0].run()
        before = (len(self.fake.secrets), len(self.fake.webhooks), len(self.fake.tools), len(self.fake.agents))
        self.fake.calls.clear()
        self.pusher(llm="claude-haiku-4-5")[0].run()
        self.assertEqual((len(self.fake.secrets), len(self.fake.webhooks), len(self.fake.tools), len(self.fake.agents)), before)
        self.assertNotIn(("POST", "/v1/workspace/webhooks"), self.fake.calls)        # the webhook, with its secret, was reused
        self.assertEqual(sum(1 for c in self.fake.calls if c[0] == "PATCH" and "/tools/" in c[1]), len(agent_config.TOOL_NAMES))
        (agent,) = self.fake.agents.values()
        self.assertEqual(agent["conversation_config"]["agent"]["prompt"]["llm"], "claude-haiku-4-5")

    def test_a_changed_tool_secret_is_synced_and_a_changed_webhook_address_is_recreated(self):
        self.pusher()[0].run()
        (Path(self.state) / "secrets.env").write_text(
            f"DESK_TOOL_SECRET=new-value\nELEVENLABS_WEBHOOK_SECRET={config.read_env_file(Path(self.state) / 'secrets.env')['ELEVENLABS_WEBHOOK_SECRET']}\n")
        config.update_config_json(self.state, {"public_base": "https://other.example:8443"})
        self.pusher()[0].run()
        self.assertEqual([s["value"] for s in self.fake.secrets.values()], ["new-value"])
        (hook,) = self.fake.webhooks.values()
        self.assertEqual(hook["url"], "https://other.example:8443/postcall")

    def test_a_tester_token_lets_the_dashboard_preview_use_the_tools_until_the_next_push(self):
        cfg = config.load(self.state, self.tmp.name)
        token = push_agent.make_tester_token(cfg)
        database = db.DB(cfg.db_path)
        self.addCleanup(database.close)
        entry = calls.Calls(database, util.Clock(), cfg).by_token(token)
        self.assertEqual(entry["purpose"], "test")
        self.pusher(tester_token=token)[0].run()
        (agent,) = self.fake.agents.values()
        self.assertEqual(agent["conversation_config"]["agent"]["dynamic_variables"]["dynamic_variable_placeholders"]
                         ["secret__desk_token"], token)
        self.assertNotIn(token, "\n".join(self.said))
        self.pusher()[0].run()                                  # the next ordinary push puts the placeholder back
        (agent,) = self.fake.agents.values()
        self.assertEqual(agent["conversation_config"]["agent"]["dynamic_variables"]["dynamic_variable_placeholders"]
                         ["secret__desk_token"], "none")

    def test_check_mode_changes_nothing(self):
        pusher, _ = self.pusher(apply=False)
        pusher.run()
        self.assertEqual((self.fake.secrets, self.fake.webhooks, self.fake.tools, self.fake.agents), ({}, {}, {}, {}))
        self.assertFalse(any(c[0] in ("POST", "PATCH", "DELETE") for c in self.fake.calls))
        self.assertTrue(any("would create" in line for line in self.said))
        self.assertNotIn("agent_id", json.loads((Path(self.state) / "config.json").read_text()))

    def test_an_unavailable_model_is_refused_before_anything_is_created(self):
        pusher, _ = self.pusher(llm="gemini-9-ultra")
        with self.assertRaises(push_agent.PushError) as ctx:
            pusher.run()
        self.assertIn("not available on this account", str(ctx.exception))
        self.assertIn("claude-haiku-4-5", str(ctx.exception))
        self.assertEqual((self.fake.secrets, self.fake.tools, self.fake.agents, self.fake.webhooks), ({}, {}, {}, {}))

    def agents_by_name(self):
        return {agent["name"]: agent for agent in self.fake.agents.values()}

    def test_the_first_push_creates_both_agents_and_saves_the_guest_id(self):
        pusher, cfg = self.pusher(guest_template=GUEST_TEMPLATE)
        ids = pusher.run()
        agents = self.agents_by_name()
        self.assertEqual(set(agents), {"{{CHIEF}} (phone)", "{{CHIEF}} (guest)"})
        guest = agents["{{CHIEF}} (guest)"]
        self.assertEqual(guest["conversation_config"]["agent"]["prompt"]["tool_ids"], [])
        self.assertEqual(guest["platform_settings"]["workspace_overrides"]["webhooks"]["post_call_webhook_id"], ids["webhook_id"])
        self.assertEqual(len(self.fake.webhooks), 1)                                  # both report to the one post-call webhook
        self.assertEqual(len(self.fake.tools), len(agent_config.TOOL_NAMES))          # the guest brings no tools of its own
        saved = json.loads((Path(self.state) / "config.json").read_text())
        self.assertEqual((saved["agent_id"], saved["guest_agent_id"]), (ids["agent_id"], ids["guest_agent_id"]))
        self.assertNotEqual(saved["agent_id"], saved["guest_agent_id"])
        self.assertEqual(guest["conversation_config"]["conversation"]["max_duration_seconds"], cfg.guest_max_call_secs)
        self.assertTrue(any("agent {{CHIEF}} (guest): created" in line for line in self.said))

    def test_pushing_again_updates_both_in_place(self):
        self.pusher(guest_template=GUEST_TEMPLATE)[0].run()
        before = {a["name"]: i for i, a in self.fake.agents.items()}
        self.fake.calls.clear()
        self.pusher(guest_template=GUEST_TEMPLATE)[0].run()
        self.assertEqual({a["name"]: i for i, a in self.fake.agents.items()}, before)
        self.assertNotIn(("POST", "/v1/convai/agents/create"), self.fake.calls)
        self.assertEqual(sum(1 for c in self.fake.calls if c[0] == "PATCH" and "/agents/" in c[1]), 2)
        self.assertTrue(any("agent {{CHIEF}} (guest): updated" in line for line in self.said))

    def test_only_guest_pushes_only_the_guest_agent(self):
        pusher, _ = self.pusher(guest_template=GUEST_TEMPLATE)
        ids = pusher.run(only="guest")
        self.assertEqual(set(self.agents_by_name()), {"{{CHIEF}} (guest)"})
        self.assertEqual((self.fake.secrets, self.fake.tools), ({}, {}))
        self.assertEqual(set(ids), {"webhook_id", "guest_agent_id"})
        saved = json.loads((Path(self.state) / "config.json").read_text())
        self.assertIn("guest_agent_id", saved)
        self.assertNotIn("agent_id", saved)

    def test_only_phone_leaves_the_guest_alone(self):
        pusher, _ = self.pusher(guest_template=GUEST_TEMPLATE)
        pusher.run(only="phone")
        self.assertEqual(set(self.agents_by_name()), {"{{CHIEF}} (phone)"})
        saved = json.loads((Path(self.state) / "config.json").read_text())
        self.assertNotIn("guest_agent_id", saved)

    def test_without_a_guest_prompt_only_the_phone_agent_is_pushed_and_only_guest_is_refused(self):
        self.pusher()[0].run()
        self.assertEqual(set(self.agents_by_name()), {"{{CHIEF}} (phone)"})
        with self.assertRaises(push_agent.PushError):
            self.pusher()[0].run(only="guest")
        with self.assertRaises(push_agent.PushError):
            self.pusher(guest_template=GUEST_TEMPLATE)[0].run(only="everything")

    def test_a_guest_payload_that_fails_its_checks_is_never_sent_and_stops_the_phone_agent_too(self):
        pusher, _ = self.pusher(guest_template=GUEST_TEMPLATE + "\n{{brief}}")
        with self.assertRaises(ValueError) as ctx:
            pusher.run()
        self.assertIn("{{brief}}", str(ctx.exception))
        self.assertEqual((self.fake.agents, self.fake.tools, self.fake.secrets, self.fake.webhooks), ({}, {}, {}, {}))

    def test_check_mode_says_what_it_would_do_for_the_guest_and_changes_nothing(self):
        pusher, _ = self.pusher(apply=False, guest_template=GUEST_TEMPLATE)
        pusher.run()
        self.assertEqual((self.fake.agents, self.fake.tools), ({}, {}))
        self.assertTrue(any("agent {{CHIEF}} (guest): would create" in line for line in self.said))
        self.assertNotIn("guest_agent_id", json.loads((Path(self.state) / "config.json").read_text()))

    def test_refuses_to_push_without_a_secret_or_with_a_bad_prompt(self):
        (Path(self.state) / "secrets.env").write_text("")
        with self.assertRaises(push_agent.PushError):
            self.pusher()[0].run()
        (Path(self.state) / "secrets.env").write_text(f"DESK_TOOL_SECRET={TOOL_SECRET}\n")
        with self.assertRaises(ValueError):
            self.pusher(template="no marker")[0].run()
        self.assertEqual(self.fake.agents, {})
        config.update_config_json(self.state, {"public_base": "http://insecure"})
        with self.assertRaises(push_agent.PushError):
            self.pusher()[0].run()


class NumberTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = str(Path(self.tmp.name) / "state")
        Path(self.state).mkdir()
        config.update_config_json(self.state, {"agent_id": "agent_1", "twilio_number": "+441111111111", "twilio_number_sid": "PN1"})
        self.fake = FakeElevenLabs()
        self.fake.server.__enter__()
        self.addCleanup(self.fake.server.__exit__, None, None, None)
        self.twilio_state = {"voice_url": "https://old.example/voice", "voice_method": "POST"}

        def twilio_handler(method, path, headers, body):
            if method == "POST":
                from urllib.parse import parse_qs
                form = parse_qs(body)
                self.twilio_state.update(voice_url=form["VoiceUrl"][0], voice_method=form["VoiceMethod"][0])
            return 200, dict(self.twilio_state)
        self.twilio_server = FakeServer(twilio_handler)
        self.twilio_server.__enter__()
        self.addCleanup(self.twilio_server.__exit__, None, None, None)
        self.said = []

    def mover(self):
        cfg = config.load(self.state, self.tmp.name)
        cfg.twilio_account_sid = "AC1"
        client = eleven.Eleven("KEY", base=self.fake.server.url)
        return number.LineMover(client, twilio.Twilio("AC1", "AC1", "authtoken", base=self.twilio_server.url), cfg, "authtoken", self.said.append), cfg

    def test_moving_remembers_the_old_address_and_imports_once(self):
        mover, _ = self.mover()
        out = mover.move_to_agent()
        (imported,) = self.fake.numbers.values()
        self.assertEqual((imported["phone_number"], imported["agent_id"], imported["provider"]), ("+441111111111", "agent_1", "twilio"))
        self.assertEqual((imported["sid"], imported["token"], imported["enable_sms"]), ("AC1", "authtoken", False))
        saved = json.loads((Path(self.state) / "line-rollback.json").read_text())
        self.assertEqual(saved["voice_url"], "https://old.example/voice")
        self.assertEqual(json.loads((Path(self.state) / "config.json").read_text())["phone_number_id"], out["phone_number_id"])
        self.twilio_state["voice_url"] = "https://api.elevenlabs.io/twilio/inbound_call"      # what ElevenLabs set
        self.mover()[0].move_to_agent()
        self.assertEqual(len(self.fake.numbers), 1)                                             # no second import
        self.assertEqual(json.loads((Path(self.state) / "line-rollback.json").read_text())["voice_url"], "https://old.example/voice")
        self.assertNotIn("authtoken", "\n".join(self.said))

    def test_importing_uses_the_twilio_login_once_and_stores_none_of_it(self):
        _, cfg = self.mover()
        client = eleven.Eleven("KEY", base=self.fake.server.url)
        said = []
        number_id = number.import_number(client, cfg, "+441111111111", "AC9", "secrettoken", said.append)
        (imported,) = self.fake.numbers.values()
        self.assertEqual((imported["phone_number"], imported["agent_id"], imported["sid"], imported["token"], imported["enable_sms"]),
                         ("+441111111111", "agent_1", "AC9", "secrettoken", False))
        self.assertEqual(json.loads((Path(self.state) / "config.json").read_text())["phone_number_id"], number_id)
        for name in ("config.json", "secrets.env"):                                            # nothing of the login is kept here
            path = Path(self.state) / name
            self.assertNotIn("secrettoken", path.read_text() if path.exists() else "")
        number.import_number(client, cfg, "+441111111111", "AC9", "secrettoken", said.append)    # again: no second import
        self.assertEqual(len(self.fake.numbers), 1)
        self.assertNotIn("secrettoken", "\n".join(said))
        cfg.agent_id = ""
        with self.assertRaises(number.MoveError):
            number.import_number(client, cfg, "+441111111111", "AC9", "t", said.append)

    def test_status_is_read_only_and_says_where_things_stand(self):
        mover, _ = self.mover()
        self.assertEqual(mover.status(), {"voice_url": "https://old.example/voice", "imported": False, "assigned_agent": None,
                                          "rollback_saved": False})
        self.assertEqual((self.fake.numbers, [c for c in self.fake.calls if c[0] != "GET"]), ({}, []))
        mover.move_to_agent()
        self.twilio_state["voice_url"] = "https://api.elevenlabs.io/twilio/inbound_call"
        self.assertEqual(self.mover()[0].status(), {"voice_url": "https://api.elevenlabs.io/twilio/inbound_call", "imported": True,
                                                    "assigned_agent": "agent_1", "rollback_saved": True})

    def test_going_back_restores_the_address_and_removes_the_number_from_elevenlabs(self):
        self.mover()[0].move_to_agent()
        self.twilio_state["voice_url"] = "https://api.elevenlabs.io/twilio/inbound_call"
        mover, _ = self.mover()
        mover.move_back()
        self.assertEqual(self.twilio_state["voice_url"], "https://old.example/voice")
        self.assertEqual(self.fake.numbers, {})
        self.assertEqual(json.loads((Path(self.state) / "config.json").read_text())["phone_number_id"], "")

    def test_refuses_without_what_it_needs(self):
        (Path(self.state) / "config.json").write_text(json.dumps({"twilio_number": "+441111111111", "twilio_number_sid": "PN1"}))
        with self.assertRaises(number.MoveError):
            self.mover()[0].move_to_agent()
        (Path(self.state) / "config.json").write_text(json.dumps({"twilio_number_sid": "PN1"}))
        with self.assertRaises(number.MoveError):
            self.mover()[0].move_back()                     # nothing recorded: nothing to go back to
        self.assertEqual(self.fake.numbers, {})


CONVERSATION = {
    "metadata": {"call_duration_secs": 95, "termination_reason": "end_call tool was called", "cost": 1200},
    "transcript": [
        {"role": "agent", "message": "Good evening, {{sir}}.", "conversation_turn_metrics": None},
        {"role": "user", "message": "What am I doing Thursday?"},
        {"role": "agent", "message": "Nothing booked, {{sir}}.", "conversation_turn_metrics": {"metrics": {
            "convai_llm_service_ttfb": {"elapsed_time": 0.42}, "convai_llm_service_ttf_sentence": {"elapsed_time": 0.61}}}},
        {"role": "agent", "message": "", "tool_results": [{"tool_name": "ask_agent", "tool_latency_secs": 6.4, "is_error": False}],
         "conversation_turn_metrics": {"convai_llm_service_ttfb": {"elapsed_time": 0.9}}},
        {"role": "user", "message": "Thanks."},
        {"role": "agent", "message": "Very good, {{sir}}.", "conversation_turn_metrics": {"metrics": {
            "convai_llm_service_ttfb": {"elapsed_time": 0.5}}}},
    ],
}


class ReportTest(unittest.TestCase):
    def test_timings_are_summarised_without_any_content(self):
        s = report.summarise(CONVERSATION)
        self.assertEqual((s["duration_secs"], s["user_turns"], s["agent_turns"]), (95, 2, 3))
        self.assertEqual(s["llm_first_token"]["n"], 3)
        self.assertAlmostEqual(s["llm_first_token"]["median"], 0.5)
        self.assertAlmostEqual(s["llm_first_token"]["max"], 0.9)
        self.assertEqual(s["tools"], [{"tool": "ask_agent", "secs": 6.4, "error": False, "abandoned": False}])
        text = report.render(s)
        self.assertIn("call 95s, 2 turns from {{OWNER}}, 3 from {{CHIEF}}; ended: end_call tool was called; cost 1200", text)
        self.assertIn("model first token: median 0.50s", text)
        self.assertIn("tool ask_agent: 6.4s", text)
        self.assertNotIn("Thursday", text)

    def test_a_tool_cut_off_by_the_caller_is_labelled_as_such(self):
        def turn(error, text):
            return {"role": "agent", "message": "", "tool_results": [
                {"tool_name": "ask_agent", "tool_latency_secs": 0.0, "is_error": error, "result_value": text}]}
        cut = report.render(report.summarise({"metadata": {"call_duration_secs": 9}, "transcript": [
            turn(True, "Tool execution was abandoned due to user input")]}))
        self.assertIn("tool ask_agent: 0.0s (abandoned: the caller spoke while it ran)", cut)
        self.assertNotIn("(ERROR)", cut)
        broken = report.render(report.summarise({"metadata": {"call_duration_secs": 9}, "transcript": [turn(True, "HTTP 500")]}))
        self.assertIn("(ERROR)", broken)

    def test_a_guest_call_is_labelled_as_such_and_the_guest_agents_conversations_are_the_ones_listed(self):
        text = report.render(report.summarise(CONVERSATION), "the person rung")
        self.assertIn("2 turns from the person rung, 3 from {{CHIEF}}", text)
        seen = []
        fake = FakeElevenLabs()
        fake.conversations["conv_g"] = CONVERSATION
        original = fake.handle
        fake.server.handler = lambda method, path, headers, body: (seen.append(path), original(method, path, headers, body))[1]
        with fake.server, tempfile.TemporaryDirectory() as tmp:
            import contextlib
            config.update_config_json(tmp, {"agent_id": "agent_phone", "guest_agent_id": "agent_guest"})
            (Path(tmp) / "secrets.env").write_text("ELEVENLABS_API_KEY=KEY\n")
            original_client = report.Eleven
            report.Eleven = lambda key: eleven.Eleven(key, base=fake.server.url)
            try:
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(report.main(["--latest", "--guest", "--state-dir", tmp, "--hermes-home", tmp]), 0)
                    self.assertEqual(report.main(["--latest", "--state-dir", tmp, "--hermes-home", tmp]), 0)
            finally:
                report.Eleven = original_client
        listings = [path for path in seen if path.startswith("/v1/convai/conversations?")]
        self.assertTrue(listings[0].endswith("agent_id=agent_guest"), listings)
        self.assertTrue(listings[1].endswith("agent_id=agent_phone"), listings)
        self.assertIn("turns from the person rung", out.getvalue())

    def test_a_call_with_no_metrics_still_renders(self):
        text = report.render(report.summarise({"metadata": {"call_duration_secs": 3}, "transcript": []}))
        self.assertIn("model first token: n/a", text)

    def test_latest_reads_the_most_recent_conversation_from_elevenlabs(self):
        fake = FakeElevenLabs()
        fake.conversations["conv_1"] = CONVERSATION
        with fake.server, tempfile.TemporaryDirectory() as tmp:
            import contextlib
            config.update_config_json(tmp, {"agent_id": "agent_1"})
            (Path(tmp) / "secrets.env").write_text("ELEVENLABS_API_KEY=KEY\n")
            original = report.Eleven
            report.Eleven = lambda key: eleven.Eleven(key, base=fake.server.url)
            try:
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    code = report.main(["--latest", "--state-dir", tmp, "--hermes-home", tmp])
            finally:
                report.Eleven = original
        self.assertEqual(code, 0)
        self.assertIn("--- conv_1", out.getvalue())
        self.assertIn("call 95s", out.getvalue())


if __name__ == "__main__":
    unittest.main()
