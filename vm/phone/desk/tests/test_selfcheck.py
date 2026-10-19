import dataclasses
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from desk import server  # noqa: E402
from helpers import FakeHermes  # noqa: E402
from rig import Rig  # noqa: E402


class SelfCheckTest(unittest.TestCase):
    def serve(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rig = Rig(tmp.name, fake_hermes=FakeHermes(polls=0))
        self.addCleanup(rig.close)
        httpd = server.make_server(rig.app, "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        return rig, f"http://127.0.0.1:{httpd.server_address[1]}"

    def test_a_healthy_desk_passes_every_check(self):
        from desk import selfcheck
        rig, base = self.serve()
        results = selfcheck.run(rig.cfg, base, rig.clock)
        self.assertEqual([name for name, ok, _ in results if not ok], [])
        self.assertGreaterEqual(len(results), 13)
        self.assertIn("the post-call webhook accepts a correctly signed event", [name for name, _, _ in results])

    def test_the_rehearsal_asks_the_ring_tool_about_a_stranger_and_rings_nobody(self):
        from desk import selfcheck
        rig, base = self.serve()
        rig.app.contacts.add("dad", "your father", "Mr Smith", "+447700900111", aliases=("dad",))     # a real book is not empty
        results = {name: ok for name, ok, _ in selfcheck.run(rig.cfg, base, rig.clock)}
        self.assertTrue(results["asking to ring somebody who is not in the contact book is answered in words and rings nobody"])
        self.assertEqual(rig.eleven.rings, [])
        self.assertEqual(rig.app.db.q("SELECT COUNT(*) AS n FROM dials")[0]["n"], 0)
        self.assertEqual(rig.app.db.q("SELECT COUNT(*) AS n FROM tickets WHERE kind = 'guest'")[0]["n"], 0)

    def test_the_rehearsal_never_holds_up_a_call_back(self):
        from desk import selfcheck
        rig, base = self.serve()
        selfcheck.run(rig.cfg, base, rig.clock)
        self.assertFalse(rig.app.calls.any_active())
        self.assertFalse(rig.app.calls.ended_within(30))
        self.assertFalse(rig.app.calls.max_active_recently(1800))
        ticket = rig.app.tickets.open("ask", "assistant", "q")
        rig.app.tickets.finish(ticket["id"], "Done.")
        rig.clock.now += rig.cfg.batch_window_secs
        self.assertEqual(rig.app.callbacks.tick(), "ringing")

    def test_a_second_rehearsal_long_after_the_first_passes_too(self):
        from desk import selfcheck
        rig, base = self.serve()
        first = selfcheck.run(rig.cfg, base, rig.clock)
        self.assertEqual([name for name, ok, _ in first if not ok], [])
        rig.clock.now += rig.cfg.max_call_secs + 601                # the first rehearsal's call token has expired by now
        second = selfcheck.run(rig.cfg, base, rig.clock)            # one fixed conversation id gave this run that dead token (HTTP 403, 5 Oct 2026)
        self.assertEqual([name for name, ok, _ in second if not ok], [])

    def test_wrong_secrets_and_a_missing_webhook_secret_show_up(self):
        from desk import selfcheck
        rig, base = self.serve()
        wrong = dataclasses.replace(rig.cfg, tool_secret="not-the-secret")
        failed = [name for name, ok, _ in selfcheck.run(wrong, base, rig.clock) if not ok]
        self.assertIn("status answers with the secret", failed)
        self.assertIn("{{OWNER}}'s call gets every variable, his brief and a token", failed)
        nosecret = dataclasses.replace(rig.cfg, webhook_secret="")
        results = {name: detail for name, _, detail in selfcheck.run(nosecret, base, rig.clock)}
        self.assertIn("skipped", results["the post-call webhook accepts a correctly signed event"])

    def test_an_unreachable_desk_fails_rather_than_raises(self):
        from desk import config, selfcheck
        results = selfcheck.run(config.Config(max_number="+447700900123", tool_secret="x"), "http://127.0.0.1:1", None)
        self.assertFalse(any(ok for name, ok, _ in results if name == "health answers"))


if __name__ == "__main__":
    unittest.main()
