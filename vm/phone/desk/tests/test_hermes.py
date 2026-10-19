import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from desk import db, hermes, tickets  # noqa: E402
from helpers import FakeClock, FakeHermes, FakeServer  # noqa: E402

KEYS = FakeHermes.KEYS


class ClientTest(unittest.TestCase):
    def test_default_profile_uses_unprefixed_routes_and_named_ones_use_p(self):
        fake = FakeHermes(polls=0)
        with fake.server:
            client = hermes.HermesClient(fake.server.url, KEYS)
            run = client.start_run("default", "hi", "be brief", "phone-t1", "desk-ticket-1")
            client.start_run("assistant", "hi", "be brief", "phone-t2", "desk-ticket-2")
            self.assertEqual(client.get_run("default", run)["status"], "completed")
        paths = [r[1] for r in fake.server.requests]
        self.assertEqual(paths[0], "/v1/runs")
        self.assertEqual(paths[1], "/p/assistant/v1/runs")
        method, path, headers, body = fake.server.requests[0]
        self.assertEqual(headers["idempotency-key"], "desk-ticket-1")
        self.assertEqual(body, {"input": "hi", "instructions": "be brief", "session_id": "phone-t1"})

    def test_errors_are_classified(self):
        fake = FakeHermes()
        with fake.server:
            client = hermes.HermesClient(fake.server.url, KEYS)
            with self.assertRaises(hermes.HermesNotFound):
                client.get_run("default", "run_missing")
            with self.assertRaises(hermes.HermesError) as ctx:
                hermes.HermesClient(fake.server.url, {"default": "wrong"}).start_run("default", "x", "y", "s", "k")
            self.assertFalse(ctx.exception.transient)
            with self.assertRaises(hermes.HermesError) as ctx:
                hermes.HermesClient(fake.server.url, {}).start_run("tutor", "x", "y", "s", "k")
            self.assertIn("no API key", str(ctx.exception))
        with self.assertRaises(hermes.HermesError) as ctx:   # server gone
            hermes.HermesClient("http://127.0.0.1:1", KEYS, timeout=1).get_run("default", "run_1")
        self.assertTrue(ctx.exception.transient)


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.db = db.DB(":memory:")
        self.addCleanup(self.db.close)
        self.tickets = tickets.Tickets(self.db, self.clock)
        self.finished = []

    def runner(self, fake, **kw):
        client = hermes.HermesClient(fake.server.url, KEYS, timeout=5)
        return hermes.Runner(self.tickets, client, self.clock, lambda t: (f"ASK: {t['request']}", "short please"),
                             on_finish=self.finished.append, **kw)

    def test_a_short_ask_finishes_and_the_waiter_gets_the_answer(self):
        fake = FakeHermes(polls=2)
        with fake.server:
            runner = self.runner(fake)
            ticket = self.tickets.open("ask", "assistant", "what is on tomorrow")
            runner.start(ticket["id"])
            done = runner.wait(ticket["id"], timeout=10)
        self.assertEqual((done["status"], done["answer"]), ("done", "Nothing booked, {{sir}}."))
        self.assertEqual(done["run_id"], "run_1")
        self.assertEqual([t["id"] for t in self.finished], [ticket["id"]])
        sent = fake.runs["run_1"]
        self.assertEqual(sent["input"], "ASK: what is on tomorrow")
        self.assertEqual(sent["session_id"], f"phone-t{ticket['id']}")

    def test_wait_times_out_but_the_work_carries_on_and_is_recorded(self):
        gate = threading.Event()
        fake = FakeHermes(polls=0)
        original = fake.handle

        def slow(method, path, headers, body):
            if method == "GET" and not gate.is_set():
                return 200, {"status": "running"}
            return original(method, path, headers, body)
        fake.server.handler = slow
        with fake.server:
            runner = self.runner(fake, give_up_secs=1e9)   # the fake clock races ahead while the gate is shut
            ticket = self.tickets.open("do", "default", "draft the essay plan")
            runner.start(ticket["id"])
            still = runner.wait(ticket["id"], timeout=0.3)
            self.assertIn(still["status"], ("new", "running"))
            gate.set()
            done = runner.wait(ticket["id"], timeout=10)
        self.assertEqual(done["status"], "done")

    def test_failed_and_interrupted_runs_fail_the_ticket(self):
        fake = FakeHermes(polls=1, end="interrupted")
        with fake.server:
            runner = self.runner(fake)
            ticket = self.tickets.open("ask", "tutor", "q")
            runner.start(ticket["id"])
            done = runner.wait(ticket["id"], timeout=10)
        self.assertEqual(done["status"], "failed")
        self.assertIn("interrupted", done["error"])

    def test_unknown_run_after_a_restart_marks_the_ticket_lost(self):
        fake = FakeHermes(polls=0)
        with fake.server:
            runner = self.runner(fake)
            ticket = self.tickets.open("ask", "assistant", "q")
            self.tickets.set_running(ticket["id"], "run_vanished")
            runner.start(ticket["id"])
            done = runner.wait(ticket["id"], timeout=10)
        self.assertEqual(done["status"], "lost")

    def test_transient_outage_is_retried_then_succeeds(self):
        fake = FakeHermes(polls=0)
        original, flips = fake.handle, {"n": 0}

        def flaky(method, path, headers, body):
            if method == "GET" and flips["n"] < 2:
                flips["n"] += 1
                return 503, {"error": "restarting"}
            return original(method, path, headers, body)
        fake.server.handler = flaky
        with fake.server:
            runner = self.runner(fake)
            ticket = self.tickets.open("ask", "assistant", "q")
            runner.start(ticket["id"])
            done = runner.wait(ticket["id"], timeout=10)
        self.assertEqual(done["status"], "done")

    def test_a_bad_key_fails_at_once_and_a_second_start_is_ignored(self):
        fake = FakeHermes()
        with fake.server:
            client = hermes.HermesClient(fake.server.url, {"default": "wrong"}, timeout=5)
            runner = hermes.Runner(self.tickets, client, self.clock, lambda t: ("x", "y"))
            ticket = self.tickets.open("do", "default", "q")
            self.assertTrue(runner.start(ticket["id"]))
            done = runner.wait(ticket["id"], timeout=10)
        self.assertEqual(done["status"], "failed")
        self.assertIn("could not start", done["error"])

    def test_resume_restarts_unfinished_tickets_only(self):
        fake = FakeHermes(polls=0)
        with fake.server:
            runner = self.runner(fake)
            a = self.tickets.open("ask", "assistant", "one")
            b = self.tickets.open("ask", "assistant", "two")
            self.tickets.finish(b["id"], "Already done.")
            self.assertEqual(runner.resume(), 1)
            done = runner.wait(a["id"], timeout=10)
        self.assertEqual(done["status"], "done")
        self.assertEqual(len(fake.runs), 1)


if __name__ == "__main__":
    unittest.main()
