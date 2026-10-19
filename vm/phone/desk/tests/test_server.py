import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from desk import persona, security, server  # noqa: E402
from helpers import FakeHermes  # noqa: E402
from rig import MAX, TOOL_SECRET, WEBHOOK_SECRET, Rig  # noqa: E402

AUTH = {"x-desk-secret": TOOL_SECRET}


def post(rig, path, payload, headers=None, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    status, ctype, data = rig.app.handle("POST", path, {k.lower(): v for k, v in (headers or {}).items()}, body)
    return status, (json.loads(data) if ctype == "application/json" else data.decode())


class ServerTest(unittest.TestCase):
    def rig(self, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rig = Rig(tmp.name, fake_hermes=kw.pop("fake_hermes", FakeHermes(polls=0, output="DONE: Nothing booked, {{sir}}.")), **kw)
        self.addCleanup(rig.close)
        return rig

    def init(self, rig, caller=MAX, conversation_id="conv_in"):
        status, out = post(rig, "/init", {"caller_id": caller, "conversation_id": conversation_id}, AUTH)
        self.assertEqual(status, 200)
        return out["dynamic_variables"]

    def test_health_and_unknown_routes(self):
        rig = self.rig()
        self.assertEqual(rig.app.handle("GET", "/health", {}, b""), (200, "application/json", b'{"ok": true}'))
        self.assertEqual(post(rig, "/nothing", {}, AUTH)[0], 404)

    def test_every_secret_route_refuses_a_missing_or_wrong_secret(self):
        rig = self.rig()
        for path in ("/init", "/tools/ask_agent", "/tools/do_for_max", "/tools/set_reminder", "/tools/check_pending",
                     "/tools/call_someone"):
            self.assertEqual(post(rig, path, {})[0], 401, path)
            self.assertEqual(post(rig, path, {}, {"x-desk-secret": "wrong"})[0], 401, path)
        self.assertEqual(rig.app.handle("GET", "/status", {}, b"")[0], 401)
        self.assertEqual(rig.hermes.runs, {})

    def test_tools_need_the_secret_and_a_valid_call_token(self):
        rig = self.rig()
        values = self.init(rig)
        body = {"agent": "assistant", "question": "what is on tomorrow"}
        self.assertEqual(post(rig, "/tools/ask_agent", body, AUTH)[0], 403)                                   # no token
        self.assertEqual(post(rig, "/tools/ask_agent", body, {**AUTH, "x-desk-token": "guess"})[0], 403)
        status, out = post(rig, "/tools/ask_agent", body, {**AUTH, "x-desk-token": values["secret__desk_token"]})
        self.assertEqual((status, out["status"], out["answer"]), (200, "done", "Nothing booked, {{sir}}."))
        status, out = post(rig, "/tools/check_pending", {}, {**AUTH, "x-desk-token": values["secret__desk_token"]})
        self.assertEqual(status, 200)
        self.assertEqual(post(rig, "/tools/launch_missiles", {}, {**AUTH, "x-desk-token": values["secret__desk_token"]})[0], 404)

    def test_a_stranger_can_never_use_the_tools_even_with_the_shared_secret(self):
        rig = self.rig()
        values = self.init(rig, caller="+441234567890", conversation_id="conv_s")
        self.assertEqual(values["secret__desk_token"], "none")
        self.assertEqual(post(rig, "/tools/ask_agent", {"agent": "assistant", "question": "x"},
                              {**AUTH, "x-desk-token": values["secret__desk_token"]})[0], 403)
        stolen = rig.app.calls.by_conversation("conv_s")["token"]
        self.assertEqual(post(rig, "/tools/ask_agent", {"agent": "assistant", "question": "x"}, {**AUTH, "x-desk-token": stolen})[0], 403)
        self.assertEqual(rig.hermes.runs, {})

    def test_the_guest_tool_works_only_with_max_s_token_and_never_rings_without_a_yes(self):
        rig = self.rig()
        rig.app.contacts.add("dad", "your father", "Mr Smith", "+447700900111", aliases=("dad",))
        values = self.init(rig)
        headers = {**AUTH, "x-desk-token": values["secret__desk_token"]}
        self.assertEqual(values["contacts_text"], "your father (dad)")                                      # {{CHIEF}} is told names only
        self.assertNotIn("7700", json.dumps(values))
        body = {"name": "dad", "purpose": "Ask whether he is free for dinner on Sunday."}
        self.assertEqual(post(rig, "/tools/call_someone", body, AUTH)[0], 403)                              # no token
        status, out = post(rig, "/tools/call_someone", body, headers)
        self.assertEqual((status, out["status"]), (200, "needs_yes"))
        self.assertEqual(rig.eleven.rings, [])
        rig.clock.now += 5                                                                                  # {{CHIEF}} reads it back, {{OWNER}} says yes
        status, out = post(rig, "/tools/call_someone", {**body, "confirmed": True}, headers)
        self.assertEqual((status, out["status"], out["contact"]), (200, "calling", "your father"))
        self.assertEqual([ring["agent_id"] for ring in rig.eleven.rings], ["agent_guest"])
        guest_token = rig.app.calls.by_conversation("conv_out1")["token"]
        self.assertEqual(post(rig, "/tools/ask_agent", {"agent": "assistant", "question": "x"},
                              {**AUTH, "x-desk-token": guest_token})[0], 403)                               # the guest call's own token opens nothing

    def test_a_stranger_can_never_ring_anyone_either(self):
        rig = self.rig()
        rig.app.contacts.add("dad", "your father", "Mr Smith", "+447700900111")
        values = self.init(rig, caller="+441234567890", conversation_id="conv_s")
        self.assertEqual(values["contacts_text"], "")                                                       # not even the names
        body = {"name": "dad", "purpose": "Say hello.", "confirmed": True}
        self.assertEqual(post(rig, "/tools/call_someone", body, {**AUTH, "x-desk-token": values["secret__desk_token"]})[0], 403)
        stolen = rig.app.calls.by_conversation("conv_s")["token"]
        self.assertEqual(post(rig, "/tools/call_someone", body, {**AUTH, "x-desk-token": stolen})[0], 403)
        self.assertEqual(rig.eleven.rings, [])

    def test_postcall_needs_a_valid_fresh_signature(self):
        rig = self.rig()
        body = json.dumps({"type": "post_call_transcription", "data": {"conversation_id": "c1"}}).encode()
        now = int(rig.clock.time())
        good = {"elevenlabs-signature": security.sign_eleven_payload(body, WEBHOOK_SECRET, now)}
        self.assertEqual(post(rig, "/postcall", None, good, raw=body)[0], 200)
        self.assertEqual(post(rig, "/postcall", None, {}, raw=body)[0], 401)
        wrong = {"elevenlabs-signature": security.sign_eleven_payload(body, "other", now)}
        self.assertEqual(post(rig, "/postcall", None, wrong, raw=body)[0], 401)
        old = {"elevenlabs-signature": security.sign_eleven_payload(body, WEBHOOK_SECRET, now - 4000)}
        self.assertEqual(post(rig, "/postcall", None, old, raw=body)[0], 401)
        tampered = {"elevenlabs-signature": security.sign_eleven_payload(body, WEBHOOK_SECRET, now)}
        self.assertEqual(post(rig, "/postcall", None, tampered, raw=body + b" ")[0], 401)

    def test_a_flood_of_bad_attempts_is_answered_cheaply_and_never_locks_out_a_caller_with_the_right_secret(self):
        rig = self.rig()
        statuses = [post(rig, "/init", {}, {"x-desk-secret": "wrong"})[0] for _ in range(40)]
        self.assertEqual((statuses[0], statuses[29], statuses[30]), (401, 401, 429))
        self.assertEqual(post(rig, "/init", {"caller_id": MAX, "conversation_id": "c1"}, AUTH)[0], 200)   # the right secret still works
        values = rig.app.calls.by_conversation("c1")
        self.assertEqual(post(rig, "/tools/check_pending", {}, {**AUTH, "x-desk-token": values["token"]})[0], 200)
        self.assertEqual(rig.app.handle("GET", "/health", {}, b"")[0], 200)
        self.assertEqual(post(rig, "/init", {}, {"x-desk-secret": "wrong"})[0], 429)
        rig.clock.now += 601
        self.assertEqual(post(rig, "/init", {}, {"x-desk-secret": "wrong"})[0], 401)

    def test_size_limits_and_bad_json(self):
        rig = self.rig()
        self.assertEqual(post(rig, "/init", None, AUTH, raw=b"x" * (server.MAX_BODY + 1))[0], 413)
        self.assertEqual(post(rig, "/init", None, AUTH, raw=b"{not json")[0], 400)
        self.assertEqual(post(rig, "/init", None, AUTH, raw=b"[1, 2]")[0], 400)
        big = json.dumps({"type": "post_call_audio", "data": {"conversation_id": "c", "full_audio": "A" * 200_000}}).encode()
        headers = {"elevenlabs-signature": security.sign_eleven_payload(big, WEBHOOK_SECRET, int(rig.clock.time()))}
        self.assertEqual(post(rig, "/postcall", None, headers, raw=big)[0], 200)      # post-call bodies may be large

    def test_the_closed_message_is_public_and_names_the_reset_date(self):
        rig = self.rig()
        status, text = rig.app.handle("POST", "/twiml/closed", {}, b"")[0], rig.app.handle("GET", "/twiml/closed", {}, b"")[2].decode()
        self.assertEqual(status, 200)
        self.assertIn("<Response>", text)
        self.assertIn("until further notice", text)
        rig.app.db.kv_set("minutes_reset", str(int(rig.eleven.reset)))
        self.assertIn("until the 3 November", rig.app.handle("GET", "/twiml/closed", {}, b"")[2].decode())
        self.assertIn("call minutes are used up", rig.app.handle("GET", "/twiml/closed", {}, b"")[2].decode())
        rig.app.db.kv_set("closed_reason", "credits")
        text = rig.app.handle("GET", "/twiml/closed", {}, b"")[2].decode()
        self.assertIn("voice credits are used up", text)
        self.assertNotIn("minutes", text)

    def test_the_unavailable_message_is_public_and_does_not_blame_minutes(self):
        rig = self.rig()
        status, kind, body = rig.app.handle("POST", "/twiml/unavailable", {}, b"")
        self.assertEqual((status, kind), (200, "text/xml"))
        text = body.decode()
        self.assertIn("<Response>", text)
        self.assertIn("not available", text)
        self.assertIn(f"This is {{CHIEF}}, {persona.TITLE}.", text)
        self.assertNotRegex(text, r"\bAI\b")
        self.assertNotIn("minutes", text)                               # the closed message blames used-up minutes; this one must not
        self.assertEqual(rig.app.handle("GET", "/twiml/unavailable", {}, b"")[0], 200)

    def test_a_caller_that_hung_up_mid_request_is_logged_quietly(self):
        rig = self.rig()
        httpd = server.make_server(rig.app, "127.0.0.1", 0)
        self.addCleanup(httpd.server_close)
        for gone in (BrokenPipeError(), ConnectionResetError()):
            try:
                raise gone
            except OSError:
                with self.assertLogs("desk.server", "INFO") as logs, contextlib.redirect_stderr(io.StringIO()) as err:
                    httpd.handle_error(None, ("127.0.0.1", 1))
            self.assertEqual(err.getvalue(), "")                                   # no traceback for a call that simply ended
            self.assertIn("went away", logs.output[0])

    def test_status_shows_modes_and_counts_but_no_secrets_or_content(self):
        rig = self.rig()
        values = self.init(rig)
        post(rig, "/tools/ask_agent", {"agent": "assistant", "question": "private question text"},
             {**AUTH, "x-desk-token": values["secret__desk_token"]})
        status, out = rig.app.handle("GET", "/status", AUTH, b"")[0], json.loads(rig.app.handle("GET", "/status", AUTH, b"")[2])
        self.assertEqual(status, 200)
        self.assertEqual((out["dial_mode"], out["notify_mode"], out["active_calls"]), ("live", "live", 1))
        self.assertEqual(out["tickets"], {"done/in_call": 1})
        self.assertEqual(out["guest_calls"], {"agent_set": True, "contacts": 0})                      # counts only: no names, no numbers
        dump = json.dumps(out)
        for secret in (TOOL_SECRET, WEBHOOK_SECRET, values["secret__desk_token"], "private question text", "7700"):
            self.assertNotIn(secret, dump)

    def test_status_counts_only_messages_that_really_failed_to_send(self):
        rig = self.rig()
        add = "INSERT INTO messages(kind, text, voice, mode, sent, error, created_at) VALUES('x', 't', 0, ?, 0, '', 0)"
        rig.app.db.x(add, ("dry",))                              # a dry-mode record is not a failure
        self.assertEqual(json.loads(rig.app.handle("GET", "/status", AUTH, b"")[2])["failed_messages"], 0)
        rig.app.db.x(add, ("live",))
        self.assertEqual(json.loads(rig.app.handle("GET", "/status", AUTH, b"")[2])["failed_messages"], 1)

    def test_a_real_http_round_trip(self):
        rig = self.rig()
        httpd = server.make_server(rig.app, "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        with urllib.request.urlopen(base + "/health", timeout=5) as response:
            self.assertEqual(json.load(response), {"ok": True})
        request = urllib.request.Request(base + "/init", data=json.dumps({"caller_id": MAX, "conversation_id": "conv_http"}).encode(),
                                         headers={"x-desk-secret": TOOL_SECRET, "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(json.load(response)["dynamic_variables"]["caller_mode"], "max")
        bad = urllib.request.Request(base + "/init", data=b"{}", headers={"x-desk-secret": "wrong"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(bad, timeout=5)
        self.assertEqual(ctx.exception.code, 401)
        ctx.exception.close()


if __name__ == "__main__":
    unittest.main()
