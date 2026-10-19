import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from desk import admin, config, server, variables  # noqa: E402
from helpers import FakeHermes  # noqa: E402
from rig import Rig  # noqa: E402


class AdminTest(unittest.TestCase):
    def rig(self, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rig = Rig(tmp.name, **kw)
        self.addCleanup(rig.close)
        return rig

    def test_without_the_operator_switch_nothing_is_announced_and_nobody_is_called(self):
        rig = self.rig(dial_mode="dry")
        order = []
        rig.app.notifier.text = lambda text, kind: order.append(("announce", text)) or True
        dial = admin.test_call(rig.app, wait_secs=5, sleep=lambda secs: order.append(("wait", secs)))
        self.assertEqual(order, [])
        self.assertEqual((dial["status"], dial["purpose"], rig.eleven.sent), ("dry", "test", []))

    def test_with_the_operator_switch_it_is_announced_first_then_exactly_one_call_goes_out_even_in_dry_mode(self):
        rig = self.rig(dial_mode="dry")
        rig.app.dialer.env = {"DESK_ALLOW_TEST_DIAL": "1"}
        order = []
        rig.app.notifier.text = lambda text, kind: order.append(("announce", text)) or True
        dial = admin.test_call(rig.app, wait_secs=5, sleep=lambda secs: order.append(("wait", secs)))
        self.assertEqual([step[0] for step in order], ["announce", "wait"])
        self.assertIn("test call is coming in about 5 seconds", order[0][1])
        self.assertEqual(dial["status"], "called")
        values = rig.eleven.sent[0]
        self.assertEqual((values["caller_mode"], values["greeting"]), ("max", variables.ANSWER_PAUSE + "{{SIR}}, this is the test call I announced on Telegram."))
        self.assertTrue(rig.app.calls.by_token(values["secret__desk_token"]))        # the tools work on the test call
        with self.assertRaises(Exception):                                            # a second one straight away is refused
            admin.test_call(rig.app, wait_secs=0, sleep=lambda secs: None)

    def test_it_refuses_to_ring_when_the_announcement_cannot_reach_telegram(self):
        for settings, announce in ((dict(notify_mode="dry"), lambda text, kind: True), (dict(notify_mode="live"), lambda text, kind: False)):
            rig = self.rig(dial_mode="dry", **settings)
            rig.app.dialer.env = {"DESK_ALLOW_TEST_DIAL": "1"}
            rig.app.notifier.text = announce
            with self.assertRaises(SystemExit) as refused:
                admin.test_call(rig.app, wait_secs=0, sleep=lambda secs: None)
            self.assertIn("refused", str(refused.exception))
            self.assertEqual(rig.eleven.sent, [])
            self.assertEqual(rig.app.db.q("SELECT COUNT(*) AS n FROM dials")[0]["n"], 0)

    def test_ask_puts_a_real_question_through_the_tool_code_and_leaves_nothing_ringing(self):
        rig = self.rig(fake_hermes=FakeHermes(polls=0, output="Ready."))
        result = admin.ask(rig.app, "tutor", "Reply with the single word ready.")
        self.assertEqual(result, {"http": 200, "status": "done", "agent": "{{TUTOR}}", "answer": "Ready.", "needs_max": False,
                                  "ticket": 1})
        self.assertEqual(rig.hermes.profiles["run_1"], "tutor")
        self.assertEqual(rig.app.calls.active(), [])
        self.assertEqual(rig.app.db.q("SELECT COUNT(*) AS n FROM calls")[0]["n"], 0)       # the throwaway token is removed
        self.assertEqual(admin.ask(rig.app, "carl", "hello")["http"], 400)

    def test_notify_test_sends_the_text_and_optionally_a_voice_note_and_refuses_while_dry(self):
        rig = self.rig()
        self.assertTrue(admin.notify_test(rig.app))
        self.assertEqual(len(rig.telegram), 1)
        self.assertIn("can reach you here", rig.telegram[0])
        self.assertTrue(admin.notify_test(rig.app, voice=True))
        self.assertEqual(len(rig.telegram), 3)
        self.assertTrue(rig.telegram[2].startswith("[[audio_as_voice]]"))
        dry = self.rig(notify_mode="dry")
        with self.assertRaises(SystemExit):
            admin.notify_test(dry.app)
        self.assertEqual(dry.telegram, [])

    def test_status_comes_from_the_running_service_and_falls_back_to_none_when_it_is_down(self):
        rig = self.rig()
        httpd = server.make_server(rig.app, "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        status = admin.live_status(rig.cfg, f"http://127.0.0.1:{httpd.server_address[1]}")
        self.assertEqual((status["dial_mode"], status["notify_mode"]), ("live", "live"))
        self.assertEqual(set(status["brief_age_secs"]), {"calendar", "deadlines", "tasks", "board", "chat"})
        self.assertEqual(set(status["brief_age_secs"].values()), {None})            # nothing has been refreshed in this rig
        self.assertIsNone(admin.live_status(rig.cfg, "http://127.0.0.1:1"))

    def test_init_creates_a_private_folder_a_secret_and_a_dry_config_and_never_replaces_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = str(Path(tmp) / "voice-desk")
            self.assertTrue(admin.init_state(state, "https://desk.example:8443")["created_secret"])
            secret = config.read_env_file(Path(state) / "secrets.env")["DESK_TOOL_SECRET"]
            self.assertGreater(len(secret), 30)
            self.assertEqual(Path(state).stat().st_mode & 0o777, 0o700)
            self.assertEqual(json.loads((Path(state) / "config.json").read_text()),
                             {"dial_mode": "dry", "notify_mode": "dry", "port": 8800, "public_base": "https://desk.example:8443"})
            config.update_config_json(state, {"dial_mode": "live"})
            self.assertFalse(admin.init_state(state, "https://other.example")["created_secret"])
            self.assertEqual(config.read_env_file(Path(state) / "secrets.env")["DESK_TOOL_SECRET"], secret)
            stored = json.loads((Path(state) / "config.json").read_text())
            self.assertEqual((stored["dial_mode"], stored["public_base"]), ("live", "https://desk.example:8443"))

    def test_set_max_number_stores_it_and_never_prints_it(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            original = admin.getpass.getpass
            admin.getpass.getpass = lambda prompt="": "07700 900123"
            try:
                self.assertEqual(admin.main(["--state-dir", tmp, "set-owner-number"]), 0)
            finally:
                admin.getpass.getpass = original
            self.assertEqual(json.loads((Path(tmp) / "config.json").read_text())["max_number"], "+447700900123")
            self.assertNotIn("7700", out.getvalue())

    def test_mode_switches_edit_the_config_file(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(admin.main(["--state-dir", tmp, "dial-mode", "live"]), 0)
            self.assertEqual(admin.main(["--state-dir", tmp, "notify-mode", "dry"]), 0)
            self.assertIn("restart voice-desk", out.getvalue())
            self.assertEqual(json.loads((Path(tmp) / "config.json").read_text()), {"dial_mode": "live", "notify_mode": "dry"})

    def contact_cli(self, tmp, *argv, number=None):
        """Run `admin contact ...` with the hidden prompts answered by `number` (typed twice, or a list of answers); returns
        (exit code or refusal message, all output, the prompts shown)."""
        out, err = io.StringIO(), io.StringIO()
        asked = []
        answers = [number, number] if isinstance(number, str) else list(number or [])

        def fake_getpass(prompt=""):
            asked.append(prompt)
            if not answers:
                raise AssertionError("the command asked for more than it should")
            return answers.pop(0)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(admin.getpass, "getpass", fake_getpass):
            try:
                result = admin.main(["--state-dir", tmp, "--hermes-home", tmp, "contact", *argv])
            except SystemExit as exc:
                result = str(exc)
        return result, out.getvalue() + err.getvalue(), asked

    def test_contact_add_asks_for_the_number_twice_without_showing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, shown, asked = self.contact_cli(tmp, "add", "dad", "--display", "your father", "--address-as", "Mr Smith",
                                                    "--alias", "dad", "--alias", "father", number="07700 900111")
            self.assertEqual(result, 0)
            self.assertEqual(len(asked), 2)                                         # the number, and again to confirm it
            self.assertNotIn("7700", shown + "".join(asked))
            self.assertNotIn("900111", shown + "".join(asked))
            self.assertIn("contact saved: dad", shown)
            self.assertIn("ending", shown)
            saved = json.loads((Path(tmp) / "contacts.json").read_text())["contacts"][0]
            self.assertEqual((saved["number"], saved["aliases"], saved["hours"]), ("+447700900111", ["dad", "father"], "09:00-21:00"))
            self.assertEqual((Path(tmp) / "contacts.json").stat().st_mode & 0o777, 0o600)
            self.assertNotIn("7700", (Path(tmp) / "config.json").read_text() if (Path(tmp) / "config.json").exists() else "")

    def test_contact_add_refuses_a_bad_number_or_name_and_never_echoes_what_was_typed(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, shown, _ = self.contact_cli(tmp, "add", "dad", "--display", "your father", "--address-as", "Mr Smith", number="077009")
            self.assertTrue(str(result).startswith("refused"), result)
            self.assertNotIn("077009", shown + str(result))
            result, shown, _ = self.contact_cli(tmp, "add", "dad", "--display", "your father", "--address-as", "Mr Smith",
                                                "--hours", "9-21", number="07700 900111")
            self.assertTrue(str(result).startswith("refused"), result)
            self.assertNotIn("900111", shown + str(result))
            self.assertFalse((Path(tmp) / "contacts.json").exists())

    def test_two_different_entries_of_the_number_save_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, shown, asked = self.contact_cli(tmp, "add", "dad", "--display", "your father", "--address-as", "Mr Smith",
                                                    number=["07700 900111", "07700 900112"])
            self.assertTrue(str(result).startswith("refused"), result)
            self.assertIn("did not match", str(result))
            self.assertNotIn("90011", shown + str(result))
            self.assertFalse((Path(tmp) / "contacts.json").exists())

    def test_contact_list_masks_numbers_and_says_who_is_the_rehearsal(self):
        with tempfile.TemporaryDirectory() as tmp:
            config.update_config_json(tmp, {"max_number": "+447700900123"})
            self.assertEqual(self.contact_cli(tmp, "list")[:2], (0, "no contacts\n"))
            self.contact_cli(tmp, "add", "dad", "--display", "your father", "--address-as", "Mr Smith", number="07700 900111")
            self.contact_cli(tmp, "add-rehearsal")
            result, shown, asked = self.contact_cli(tmp, "list")
            self.assertEqual((result, asked), (0, []))
            self.assertIn("dad", shown)
            self.assertIn("your father", shown)
            self.assertIn("Mr Smith", shown)
            self.assertIn("09:00-21:00", shown)
            self.assertIn("test-dad", shown)
            self.assertIn("rehearsal", shown)
            for leak in ("7700", "900111", "900123", "+44"):
                self.assertNotIn(leak, shown)

    def test_contact_add_rehearsal_needs_no_number_and_uses_max_s_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, shown, asked = self.contact_cli(tmp, "add-rehearsal")
            self.assertTrue(str(result).startswith("refused"), result)                 # {{OWNER}}'s number is not set yet
            config.update_config_json(tmp, {"max_number": "+447700900123"})
            result, shown, asked = self.contact_cli(tmp, "add-rehearsal")
            self.assertEqual((result, asked), (0, []))
            self.assertIn("contact saved: test-dad", shown)
            for leak in ("7700", "900123"):
                self.assertNotIn(leak, shown)
            saved = json.loads((Path(tmp) / "contacts.json").read_text())["contacts"][0]
            self.assertEqual((saved["number"], saved["rehearsal"]), ("+447700900123", True))

    def test_contact_edit_corrects_names_and_hours_and_never_asks_for_or_shows_the_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.contact_cli(tmp, "add", "dad", "--display", "your tfather", "--address-as", "Mr Smith", "--alias", "dad",
                             "--hours", "09:00-23:00", number="07700 900111")
            before = (Path(tmp) / "contacts.json").read_text()
            result, shown, asked = self.contact_cli(tmp, "edit", "dad", "--display", "your father", "--hours", "09:00-21:00")
            self.assertEqual((result, shown, asked), (0, "contact updated: dad\n", []))
            saved = json.loads((Path(tmp) / "contacts.json").read_text())["contacts"][0]
            self.assertEqual((saved["display"], saved["hours"], saved["address_as"], saved["aliases"], saved["number"]),
                             ("your father", "09:00-21:00", "Mr Smith", ["dad"], "+447700900111"))
            self.assertNotEqual((Path(tmp) / "contacts.json").read_text(), before)
            self.assertEqual(self.contact_cli(tmp, "edit", "dad", "--alias", "pops", "--alias", "father")[0], 0)
            self.assertEqual(json.loads((Path(tmp) / "contacts.json").read_text())["contacts"][0]["aliases"], ["pops", "father"])
            self.assertEqual(self.contact_cli(tmp, "edit", "dad", "--no-aliases")[0], 0)
            self.assertEqual(json.loads((Path(tmp) / "contacts.json").read_text())["contacts"][0]["aliases"], [])
            for argv in (["edit", "dad"], ["edit", "nobody", "--display", "x"], ["edit", "dad", "--hours", "9-21"],
                         ["edit", "dad", "--display", "your father 2"]):
                result, shown, _ = self.contact_cli(tmp, *argv)
                self.assertTrue(str(result).startswith("refused"), (argv, result))
                self.assertNotIn("7700", shown + str(result))
            self.assertEqual(json.loads((Path(tmp) / "contacts.json").read_text())["contacts"][0]["display"], "your father")

    def test_contact_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.contact_cli(tmp, "add", "dad", "--display", "your father", "--address-as", "Mr Smith", number="07700 900111")
            self.assertEqual(self.contact_cli(tmp, "remove", "dad")[:2], (0, "contact removed: dad\n"))
            result, shown, _ = self.contact_cli(tmp, "remove", "dad")
            self.assertTrue(str(result).startswith("refused"), result)
            self.assertEqual(json.loads((Path(tmp) / "contacts.json").read_text())["contacts"], [])


if __name__ == "__main__":
    unittest.main()
