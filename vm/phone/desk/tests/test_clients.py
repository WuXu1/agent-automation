import base64
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from desk import calls, config, db, eleven, notify, twilio  # noqa: E402
from helpers import FakeClock, FakeServer  # noqa: E402


class ElevenTest(unittest.TestCase):
    def test_outbound_call_payload_and_result(self):
        def handler(method, path, headers, body):
            return 200, {"success": True, "message": "ok", "conversation_id": "conv_9", "callSid": "CA9"}
        with FakeServer(handler) as server:
            client = eleven.Eleven("KEY123", base=server.url)
            out = client.outbound_call("agent_1", "phnum_1", "+447700900123", {"greeting": "{{SIR}}."})
        method, path, headers, body = server.requests[0]
        self.assertEqual((method, path), ("POST", "/v1/convai/twilio/outbound-call"))
        self.assertEqual(headers["xi-api-key"], "KEY123")
        self.assertEqual(body["agent_id"], "agent_1")
        self.assertEqual(body["agent_phone_number_id"], "phnum_1")
        self.assertEqual(body["to_number"], "+447700900123")
        self.assertEqual(body["conversation_initiation_client_data"], {"dynamic_variables": {"greeting": "{{SIR}}."}})
        self.assertEqual(body["telephony_call_config"]["twilio_machine_detection"], {"mode": "enable"})
        self.assertEqual(out, {"conversation_id": "conv_9", "call_sid": "CA9"})

    def test_refusals_are_definite_and_outages_are_not_and_the_key_is_hidden(self):
        with FakeServer(lambda *a: (422, {"detail": "bad KEY123 request"})) as server:
            with self.assertRaises(eleven.ElevenError) as ctx:
                eleven.Eleven("KEY123", base=server.url).outbound_call("a", "p", "+44", {})
        self.assertTrue(ctx.exception.definite)
        self.assertNotIn("KEY123", str(ctx.exception))
        with FakeServer(lambda *a: (503, {"error": "down"})) as server:
            with self.assertRaises(eleven.ElevenError) as ctx:
                eleven.Eleven("K", base=server.url).outbound_call("a", "p", "+44", {})
        self.assertFalse(ctx.exception.definite)
        with self.assertRaises(eleven.ElevenError) as ctx:
            eleven.Eleven("K", base="http://127.0.0.1:1", timeout=1).subscription()
        self.assertFalse(ctx.exception.definite)
        with FakeServer(lambda *a: (200, {"success": False, "message": "number not allowed"})) as server:
            with self.assertRaises(eleven.ElevenError) as ctx:
                eleven.Eleven("K", base=server.url).outbound_call("a", "p", "+44", {})
        self.assertTrue(ctx.exception.definite)

    def test_conversations_are_paged(self):
        pages = {"": {"conversations": [{"conversation_id": "a"}], "next_cursor": "c2", "has_more": True},
                 "c2": {"conversations": [{"conversation_id": "b"}], "next_cursor": None, "has_more": False}}

        def handler(method, path, headers, body):
            cursor = path.split("cursor=")[1].split("&")[0] if "cursor=" in path else ""
            return 200, pages[cursor]
        with FakeServer(handler) as server:
            out = eleven.Eleven("K", base=server.url).conversations_since(1000, agent_id="agent_1")
        self.assertEqual([c["conversation_id"] for c in out], ["a", "b"])
        self.assertIn("call_start_after_unix=1000", server.requests[0][1])
        self.assertIn("agent_id=agent_1", server.requests[0][1])

    def test_speak_returns_audio_bytes(self):
        import http.server
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Length", "4")
                self.end_headers()
                self.wfile.write(b"OggS")

            def log_message(self, *a):
                pass
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        try:
            audio = eleven.Eleven("K", base=f"http://127.0.0.1:{httpd.server_address[1]}").speak("Very good, {{sir}}.", "voice1")
        finally:
            httpd.shutdown()
            httpd.server_close()
        self.assertEqual(audio, b"OggS")


class TwilioTest(unittest.TestCase):
    def test_voice_url_is_read_and_changed_with_api_key_auth(self):
        with FakeServer(lambda *a: (200, {"sid": "PN1", "voice_url": "https://x/voice"})) as server:
            client = twilio.Twilio("ACacc", "SKkey", "secret", base=server.url)
            self.assertEqual(client.get_number("PN1")["voice_url"], "https://x/voice")
            client.set_voice_url("PN1", "https://desk/twiml/closed")
        get, post = server.requests
        self.assertEqual(get[1], "/2010-04-01/Accounts/ACacc/IncomingPhoneNumbers/PN1.json")
        self.assertEqual(get[2]["authorization"], "Basic " + base64.b64encode(b"SKkey:secret").decode())
        self.assertEqual(post[0], "POST")
        self.assertIn("VoiceUrl=https%3A%2F%2Fdesk%2Ftwiml%2Fclosed", post[3])

    def test_errors_do_not_carry_credentials(self):
        with FakeServer(lambda *a: (401, {"message": "bad"})) as server:
            with self.assertRaises(twilio.TwilioError) as ctx:
                twilio.Twilio("ACacc", "SKkey", "secret", base=server.url).get_number("PN1")
        self.assertNotIn("secret", str(ctx.exception))


class NotifierTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = db.DB(":memory:")
        self.addCleanup(self.db.close)
        self.cfg = config.Config(state_dir=self.tmp.name, hermes_bin="/bin/hermes", hermes_home="/h")
        self.ran = []

        def run(cmd, timeout=90, env=None):
            self.ran.append((cmd, env))
            return self.status
        self.status = 0
        self.speak_calls = []

        def speak(text):
            self.speak_calls.append(text)
            return b"OggS-audio"
        self.n = notify.Notifier(self.cfg, self.db, FakeClock(), run=run, speak=speak)

    def rows(self):
        return self.db.q("SELECT kind, text, voice, mode, sent, error FROM messages ORDER BY id")

    def test_dry_mode_records_and_sends_nothing(self):
        self.assertTrue(self.n.text("Hello {{sir}}", "summary"))
        self.assertTrue(self.n.voice("Hello {{sir}}", "fallback"))
        self.assertEqual(self.ran, [])
        self.assertEqual([(r["mode"], r["sent"], r["voice"]) for r in self.rows()], [("dry", 0, 0), ("dry", 0, 1)])

    def test_live_text_goes_through_hermes_send_scrubbed(self):
        self.cfg.notify_mode = "live"
        self.assertTrue(self.n.text("The key=hunter2 is set", "summary"))
        cmd, env = self.ran[0]
        self.assertEqual(cmd[:5], ["/bin/hermes", "send", "--to", "telegram", "-q"])
        self.assertEqual(cmd[5], "The key=[redacted] is set")
        self.assertEqual(env, {"HERMES_HOME": "/h"})
        self.assertEqual(self.rows()[0]["sent"], 1)

    def test_a_failed_send_is_recorded_and_reported(self):
        self.cfg.notify_mode = "live"
        self.status = 1
        with self.assertLogs("desk.notify", "WARNING"):
            self.assertFalse(self.n.text("x", "summary"))
        self.assertEqual((self.rows()[0]["sent"], self.rows()[0]["error"]), (0, "hermes send failed"))

    def test_voice_note_is_sent_as_a_voice_bubble_and_the_file_is_removed(self):
        self.cfg.notify_mode = "live"
        self.assertTrue(self.n.voice("{{SIR}}, {{ASSISTANT}} has the answer.", "fallback"))
        body = self.ran[0][0][5]
        self.assertTrue(body.startswith("[[audio_as_voice]]\nMEDIA:"))
        path = Path(body.split("MEDIA:")[1])
        self.assertFalse(path.exists())
        self.assertEqual(self.speak_calls, ["{{SIR}}, {{ASSISTANT}} has the answer."])

    def test_a_voice_note_is_short_unless_the_caller_asks_for_more(self):
        self.cfg.notify_mode = "live"
        long = "He said something kind. " * 100                                  # 2,400 characters
        self.assertTrue(self.n.voice(long, "fallback"))
        self.assertLessEqual(len(self.speak_calls[-1]), 700)                      # a fallback note stays short
        self.assertTrue(self.n.voice(long, "guest-voice", limit=2000))
        self.assertEqual(len(self.speak_calls[-1]), 2000)                         # a guest report is spoken in full (up to its limit)
        self.assertTrue(self.n.voice("A short one.", "guest-voice", limit=2000))
        self.assertEqual(self.speak_calls[-1], "A short one.")

    def test_voice_failure_returns_false_without_raising(self):
        self.cfg.notify_mode = "live"
        self.n.speak = lambda text: (_ for _ in ()).throw(RuntimeError("tts down"))
        self.assertFalse(self.n.voice("x", "fallback"))
        self.assertEqual(self.ran, [])
        self.assertEqual(self.rows()[0]["error"], "RuntimeError")


class CallsTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.db = db.DB(":memory:")
        self.addCleanup(self.db.close)
        self.calls = calls.Calls(self.db, self.clock, config.Config())

    def test_a_max_call_gets_a_working_token_and_a_stranger_does_not(self):
        mine = self.calls.start_inbound("conv_1", "max")
        stranger = self.calls.start_inbound("conv_2", "stranger")
        self.assertEqual(self.calls.by_token(mine["token"])["conversation_id"], "conv_1")
        self.assertIsNone(self.calls.by_token(stranger["token"]))
        self.assertIsNone(self.calls.by_token("none"))
        self.assertIsNone(self.calls.by_token(""))
        self.assertIsNone(self.calls.by_token("guess"))

    def test_inbound_is_idempotent_and_tokens_expire(self):
        a = self.calls.start_inbound("conv_1", "max")
        self.assertEqual(self.calls.start_inbound("conv_1", "max")["token"], a["token"])
        self.clock.now += config.Config().max_call_secs + 601
        self.assertIsNone(self.calls.by_token(a["token"]))

    def test_outbound_gets_its_conversation_attached_later(self):
        out = self.calls.prepare_outbound("callback")
        self.assertIsNone(out["conversation_id"])
        self.calls.attach_conversation(out["id"], "conv_7")
        self.assertEqual(self.calls.by_conversation("conv_7")["token"], out["token"])

    def test_an_unplaced_call_leaves_nothing_behind_and_is_never_active(self):
        out = self.calls.prepare_outbound("callback")
        self.assertFalse(self.calls.any_active())          # no conversation yet: nothing is really in progress
        self.calls.discard(out["id"])
        self.assertIsNone(self.calls.get(out["id"]))
        placed = self.calls.prepare_outbound("callback")
        self.calls.attach_conversation(placed["id"], "conv_1")
        self.calls.discard(placed["id"])                   # a placed call is never discarded
        self.assertIsNotNone(self.calls.get(placed["id"]))
        self.assertTrue(self.calls.any_active())

    def test_active_calls_and_recent_activity(self):
        self.assertFalse(self.calls.any_active())
        a = self.calls.start_inbound("conv_1", "max")
        self.assertTrue(self.calls.any_active())
        self.assertTrue(self.calls.max_active_recently(1800))
        self.calls.end("conv_1", 60, 3)
        self.assertFalse(self.calls.any_active())
        self.assertTrue(self.calls.max_active_recently(1800))
        self.clock.now += 3600
        self.assertFalse(self.calls.max_active_recently(1800))
        self.assertEqual(self.calls.get(a["id"])["user_turns"], 3)


if __name__ == "__main__":
    unittest.main()
