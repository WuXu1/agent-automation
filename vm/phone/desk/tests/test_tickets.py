import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from desk import db, tickets  # noqa: E402


class FakeClock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ParseAnswerTest(unittest.TestCase):
    def test_plain_answer_is_cleaned_for_speech(self):
        text, needs = tickets.parse_answer("**Lab B** is due Thursday, {{sir}}. See https://x.y/z")
        self.assertEqual((text, needs), ("Lab B is due Thursday, {{sir}}. See", False))

    def test_done_prefix_is_dropped(self):
        self.assertEqual(tickets.parse_answer("DONE: The reminder is set for six.")[0], "The reminder is set for six.")

    def test_needs_max_marker(self):
        text, needs = tickets.parse_answer("NEEDS MAX: which of the two rooms shall I book?")
        self.assertTrue(needs)
        self.assertEqual(text, "which of the two rooms shall I book?")
        self.assertTrue(tickets.parse_answer("**NEEDS MAX:** yes or no")[1])

    def test_wrapping_quotes_are_removed_and_empty_stays_empty(self):
        self.assertEqual(tickets.parse_answer('"Very good, {{sir}}."')[0], "Very good, {{sir}}.")
        self.assertEqual(tickets.parse_answer("   ")[0], "")


class TicketsTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.db = db.DB(":memory:")
        self.addCleanup(self.db.close)
        self.t = tickets.Tickets(self.db, self.clock)

    def open(self, **kw):
        args = dict(kind="ask", agent="assistant", request="what is on tomorrow", conversation_id="conv1")
        args.update(kw)
        return self.t.open(**args)

    def test_a_longer_answer_is_kept_when_the_caller_allows_it(self):
        long = "word " * 600                                                      # 3,000 characters
        self.assertEqual(len(tickets.parse_answer(long)[0]), tickets.ANSWER_MAX)  # colleagues' answers stay at 1,500
        self.assertEqual(len(tickets.parse_answer(long, limit=2000)[0]), 2000)
        row = self.open(kind="guest", agent="default", request="Ring your father: x")
        done = self.t.finish(row["id"], "DONE: " + "He is well. " * 150, limit=2416)    # 1,800 characters: more than a colleague's answer may be
        self.assertGreater(len(done["answer"]), tickets.ANSWER_MAX)
        self.assertTrue(done["answer"].endswith("He is well."))

    def test_a_guest_ticket_waits_for_its_phone_call_not_for_a_run(self):
        row = self.open(kind="guest", agent="default", request="Ring your father: x")
        self.assertEqual(row["status"], "new")
        self.assertTrue(self.t.attach_dial(row["id"], 7))
        got = self.t.get(row["id"])
        self.assertEqual((got["status"], got["dial_id"], got["run_id"], got["delivery"]), ("running", 7, None, "none"))
        self.assertEqual(self.t.by_dial(7, "guest")["id"], row["id"])
        self.assertIsNone(self.t.by_dial(7, "ask"))
        self.assertIsNone(self.t.by_dial(8, "guest"))
        self.t.finish(row["id"], "DONE: ok")
        self.assertFalse(self.t.attach_dial(row["id"], 9))                        # a finished ticket is not attached again
        self.assertEqual(self.t.get(row["id"])["dial_id"], 7)

    def test_lifecycle_and_finish_is_once_only(self):
        row = self.open()
        self.assertEqual((row["status"], row["delivery"]), ("new", "none"))
        self.t.set_running(row["id"], "run_1")
        self.assertEqual(self.t.get(row["id"])["run_id"], "run_1")
        done = self.t.finish(row["id"], "DONE: Nothing booked, {{sir}}.")
        self.assertEqual((done["status"], done["answer"]), ("done", "Nothing booked, {{sir}}."))
        self.assertIsNone(self.t.finish(row["id"], "a second answer"))
        self.assertEqual(self.t.get(row["id"])["answer"], "Nothing booked, {{sir}}.")

    def test_empty_answer_and_errors_fail_the_ticket(self):
        a, b, c = self.open(), self.open(), self.open()
        self.assertEqual(self.t.finish(a["id"], "  ")["status"], "failed")
        self.assertEqual(self.t.fail(b["id"], "interrupted")["status"], "failed")
        self.assertEqual(self.t.fail(c["id"], "gone", lost=True)["status"], "lost")

    def test_in_call_handover_happens_once(self):
        a, b = self.open(), self.open(request="other", conversation_id="conv2")
        self.t.finish(a["id"], "Done.")
        self.t.finish(b["id"], "Done too.")
        first = self.t.take_finished("conv1")
        self.assertEqual([r["id"] for r in first], [a["id"]])
        self.assertEqual(self.t.take_finished("conv1"), [])
        self.assertEqual(self.t.get(a["id"])["delivery"], "in_call")
        self.assertEqual(self.t.get(b["id"])["delivery"], "none")
        self.assertEqual([r["id"] for r in self.t.take_finished()], [b["id"]])      # no conversation named: everything finished

    def test_callback_claim_is_atomic_and_never_twice(self):
        a, b = self.open(), self.open()
        self.t.finish(a["id"], "One.")
        self.t.finish(b["id"], "Two.")
        self.assertEqual(self.t.claim_for_callback([a["id"], b["id"]], dial_id=7), [a["id"], b["id"]])
        self.assertEqual(self.t.claim_for_callback([a["id"], b["id"]], dial_id=8), [])
        self.assertEqual(self.t.candidates(), [])
        self.assertEqual(self.t.settle_dial(7, "delivered"), [a["id"], b["id"]])
        self.assertEqual(self.t.get(a["id"])["delivery"], "delivered")
        self.assertEqual(self.t.settle_dial(7, "telegram"), [])   # already settled: nothing flips again

    def test_unfinished_tickets_cannot_be_claimed(self):
        a = self.open()
        self.assertEqual(self.t.claim_for_callback([a["id"]], dial_id=1), [])

    def test_candidates_are_oldest_finished_first(self):
        a, b = self.open(), self.open()
        self.clock.now += 5
        self.t.finish(b["id"], "B first.")
        self.clock.now += 5
        self.t.finish(a["id"], "A second.")
        self.assertEqual([r["id"] for r in self.t.candidates()], [b["id"], a["id"]])

    def test_pending_lines_describe_work_and_waiting_results(self):
        a, b = self.open(request="check the Lab B marking scheme"), self.open(agent="tutor", request="quiz plan")
        self.t.finish(b["id"], "Plan ready.")
        self.clock.now += 300
        text = self.t.pending_lines()
        self.assertIn("{{ASSISTANT}} is working on: check the Lab B marking scheme (asked 5 min ago)", text)
        self.assertIn("{{TUTOR}} has finished: quiz plan", text)


if __name__ == "__main__":
    unittest.main()
