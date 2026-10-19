import datetime as dt
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from desk import tools, util  # noqa: E402
from helpers import FakeHermes  # noqa: E402
from rig import Rig  # noqa: E402


class ParseWhenTest(unittest.TestCase):
    NOW = dt.datetime(2026, 10, 5, 16, 56, 30, tzinfo=util.UK).timestamp()

    def fire(self, text):
        return tools.parse_when(text, self.NOW).strftime("%Y-%m-%d %H:%M")

    def test_a_delay_is_rounded_up_to_the_minute(self):
        self.assertEqual(self.fire("10m"), "2026-10-05 17:07")             # 17:06:30 would go off early, at 17:06
        self.assertEqual(self.fire("2 hours"), "2026-10-05 18:57")
        self.assertEqual(self.fire("1d"), "2026-10-06 16:57")
        self.assertEqual(self.fire(" 15 minutes "), "2026-10-05 17:12")

    def test_a_uk_date_and_time_is_taken_as_given(self):
        self.assertEqual(self.fire("2026-10-05 18:30"), "2026-10-05 18:30")
        self.assertEqual(self.fire("2026-10-06T07:00"), "2026-10-06 07:00")

    def test_times_that_make_no_sense_are_refused_with_something_carl_can_say(self):
        for bad, words in (("tomorrow", "when"), ("", "when"), ("0m", "already"), ("2026-10-05 16:00", "already"),
                           ("2028-01-01 09:00", "year"), ("400d", "year")):
            with self.assertRaises(ValueError) as ctx:
                tools.parse_when(bad, self.NOW)
            self.assertIn(words, str(ctx.exception))

    def test_the_scheduler_is_asked_for_a_one_shot_at_an_exact_time(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return type("Done", (), {"returncode": 0, "stdout": "Created job: abc123\n  Name: x\n", "stderr": ""})()
        cfg = type("Cfg", (), {"hermes_bin": "/bin/hermes", "hermes_home": "/home/h"})()
        fire = tools.parse_when("10m", self.NOW)
        self.assertEqual(tools.create_reminder(cfg, fire, "check the oven", run=fake_run), (True, "abc123"))
        cmd, kwargs = calls[0]
        self.assertEqual(cmd[:5], ["/bin/hermes", "cron", "create", "2026-10-05 17:07", cmd[4]])
        self.assertIn("check the oven", cmd[4])
        self.assertEqual(cmd[5:], ["--name", "Reminder: check the oven", "--deliver", "telegram"])    # 'every 10m' would repeat for ever
        self.assertEqual(kwargs["env"]["HERMES_HOME"], "/home/h")

        def refusing(cmd, **kwargs):
            return type("Done", (), {"returncode": 2, "stdout": "", "stderr": "nope"})()
        self.assertEqual(tools.create_reminder(cfg, fire, "x", run=refusing)[0], False)

        def missing(cmd, **kwargs):
            raise FileNotFoundError()
        self.assertEqual(tools.create_reminder(cfg, fire, "x", run=missing)[0], False)


class ToolsTest(unittest.TestCase):
    def rig(self, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rig = Rig(tmp.name, **kw)
        self.addCleanup(rig.close)
        self.call = rig.app.calls.start_inbound("conv_1", "max")
        return rig

    def test_a_quick_answer_comes_back_on_the_call(self):
        rig = self.rig(fake_hermes=FakeHermes(polls=1, output="DONE: Nothing booked, {{sir}}."))
        status, out = rig.app.tools.ask_agent(self.call, {"agent": "assistant", "question": "what is on tomorrow"})
        self.assertEqual((status, out), (200, {"status": "done", "agent": "{{ASSISTANT}}", "answer": "Nothing booked, {{sir}}.",
                                               "needs_max": False, "ticket": 1}))
        sent = rig.hermes.runs["run_1"]
        self.assertEqual(rig.hermes.profiles["run_1"], "assistant")
        self.assertEqual(sent["input"], "{{CHIEF}} asks, for {{OWNER}}: what is on tomorrow")
        self.assertIn("NEEDS MAX:", sent["instructions"])
        ticket = rig.app.tickets.get(1)
        self.assertEqual((ticket["status"], ticket["delivery"], ticket["conversation_id"]), ("done", "in_call", "conv_1"))

    def test_a_slow_job_is_pending_then_found_by_check_pending(self):
        import threading
        gate = threading.Event()
        fake = FakeHermes(polls=0, output="DONE: The essay plan is saved.")
        original = fake.handle

        def slow(method, path, headers, body):
            if method == "GET" and not gate.is_set():
                return 200, {"status": "running"}
            return original(method, path, headers, body)
        fake.server.handler = slow
        rig = self.rig(fake_hermes=fake, wait_secs=0.3)
        rig.app.runner.give_up_secs = 1e9          # the fake clock races ahead while the gate is shut
        status, out = rig.app.tools.do_for_max(self.call, {"request": "draft the essay plan", "confirmed": True})
        self.assertEqual((status, out["status"], out["agent"], out["ticket"]), (200, "pending", "{{CHIEF}}", 1))
        self.assertIn("ring him back", out["message"])
        self.assertEqual(rig.app.tools.check_pending(self.call, {})[1]["still_working"][0]["agent"], "{{CHIEF}}")
        gate.set()
        rig.app.runner.wait(1, 10)
        status, out = rig.app.tools.check_pending(self.call, {})
        self.assertEqual(out["finished"], [{"agent": "{{CHIEF}}", "asked": "draft the essay plan",
                                            "answer": "The essay plan is saved.", "needs_max": False, "ticket": 1}])
        self.assertEqual(out["still_working"], [])
        self.assertEqual(rig.app.tools.check_pending(self.call, {})[1],
                         {"finished": [], "still_working": [], "message": "Nothing new."})

    def test_do_for_max_goes_to_carl_with_the_right_confirmation_wording(self):
        rig = self.rig(fake_hermes=FakeHermes(polls=0, output="DONE: Reminder set for six."))
        rig.app.tools.do_for_max(self.call, {"request": "remind me at six to ring the dentist", "confirmed": "yes"})
        rig.app.tools.do_for_max(self.call, {"request": "book the lab", "confirmed": False})
        first, second = rig.hermes.runs["run_1"], rig.hermes.runs["run_2"]
        self.assertEqual(set(rig.hermes.profiles.values()), {"default"})
        self.assertIn("has just confirmed", first["instructions"])
        self.assertIn("has not confirmed it yet", second["instructions"])
        self.assertEqual([rig.app.tickets.get(i)["kind"] for i in (1, 2)], ["do_confirmed", "do"])

    def test_needs_max_is_flagged_and_failures_are_reported(self):
        rig = self.rig(fake_hermes=FakeHermes(polls=0, output="NEEDS MAX: which room shall I book?"))
        _, out = rig.app.tools.ask_agent(self.call, {"agent": "coach", "question": "book a room"})
        self.assertEqual((out["answer"], out["needs_max"]), ("which room shall I book?", True))
        failing = self.rig(fake_hermes=FakeHermes(polls=0, end="failed"))
        _, out = failing.app.tools.ask_agent(self.call, {"agent": "tutor", "question": "quiz"})
        self.assertEqual((out["status"], out["message"]), ("failed", "{{TUTOR}} could not finish that: the run ended as failed."))

    def test_every_result_carries_its_ticket_number(self):
        rig = self.rig(fake_hermes=FakeHermes(polls=0, output="DONE: Fine."))
        _, done = rig.app.tools.ask_agent(self.call, {"agent": "assistant", "question": "q1"})
        self.assertEqual(done["ticket"], 1)                         # the post-call check finds out which results {{CHIEF}} really heard
        failing = self.rig(fake_hermes=FakeHermes(polls=0, end="failed"))
        _, failed = failing.app.tools.ask_agent(self.call, {"agent": "tutor", "question": "q2"})
        self.assertEqual((failed["status"], failed["ticket"]), ("failed", 1))

    def test_a_repeated_request_in_the_same_call_is_one_job(self):
        rig = self.rig(fake_hermes=FakeHermes(polls=0, output="DONE: Reminder set for six."))
        first = rig.app.tools.do_for_max(self.call, {"request": "remind me at six", "confirmed": True})
        again = rig.app.tools.do_for_max(self.call, {"request": "remind me at six", "confirmed": True})   # abandoned, then retried
        self.assertEqual(first, again)
        self.assertEqual(len(rig.hermes.runs), 1)
        self.assertIsNone(rig.app.tickets.get(2))

    def test_the_same_words_are_a_new_job_when_confirmed_later_or_after_a_failure(self):
        rig = self.rig(fake_hermes=FakeHermes(polls=0, output="DONE: Done."))
        rig.app.tools.do_for_max(self.call, {"request": "book the lab", "confirmed": False})
        rig.app.tools.do_for_max(self.call, {"request": "book the lab", "confirmed": True})       # confirming is a different job
        rig.clock.now += tools.DEDUPE_SECS + 1
        rig.app.tools.do_for_max(self.call, {"request": "book the lab", "confirmed": True})       # long after: a fresh job
        self.assertEqual(len(rig.hermes.runs), 3)
        failing = self.rig(fake_hermes=FakeHermes(polls=0, end="failed"))
        failing.app.tools.ask_agent(self.call, {"agent": "tutor", "question": "quiz"})
        failing.app.tools.ask_agent(self.call, {"agent": "tutor", "question": "quiz"})              # a failure may be retried
        self.assertEqual(len(failing.hermes.runs), 2)

    def reminder_rig(self, ok=True):
        rig = self.rig()
        rig.reminders = []

        def make(fire, text):
            rig.reminders.append((fire.strftime("%Y-%m-%d %H:%M"), text))
            return (True, "job1") if ok else (False, "the scheduler said no")
        rig.app.tools.make_reminder = make
        return rig

    def test_a_reminder_is_set_at_once_without_an_agent_run(self):
        rig = self.reminder_rig()
        status, out = rig.app.tools.set_reminder(self.call, {"when": "10m", "text": "check the oven"})
        due = (util.uk_time(rig.clock.time()) + dt.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M")
        self.assertEqual((status, out["status"], out["agent"]), (200, "done", "{{CHIEF}}"))
        self.assertEqual(rig.reminders, [(due, "check the oven")])
        self.assertIn("check the oven", out["answer"])
        self.assertIn(due[-5:], out["answer"])
        ticket = rig.app.tickets.get(out["ticket"])
        self.assertEqual((ticket["kind"], ticket["status"], ticket["delivery"]), ("reminder", "done", "in_call"))
        self.assertEqual(rig.hermes.runs, {})                                          # no 15-second agent run

    def test_a_repeated_reminder_is_one_reminder(self):
        rig = self.reminder_rig()
        first = rig.app.tools.set_reminder(self.call, {"when": "10m", "text": "check the oven"})
        again = rig.app.tools.set_reminder(self.call, {"when": "10m", "text": "check the oven"})
        self.assertEqual(first, again)
        self.assertEqual(len(rig.reminders), 1)

    def test_a_reminder_that_cannot_be_set_is_reported_not_claimed(self):
        rig = self.reminder_rig(ok=False)
        status, out = rig.app.tools.set_reminder(self.call, {"when": "10m", "text": "check the oven"})
        self.assertEqual((status, out["status"]), (200, "failed"))
        self.assertIn("could not", out["message"])
        self.assertEqual(rig.app.tickets.get(out["ticket"])["status"], "failed")

    def test_a_reminder_with_no_usable_time_or_text_creates_nothing(self):
        rig = self.reminder_rig()
        for args in ({"when": "sometime", "text": "x"}, {"when": "10m", "text": "  "}, {}):
            status, out = rig.app.tools.set_reminder(self.call, args)
            self.assertEqual((status, out["status"]), (200, "failed"))       # a 200, so {{CHIEF}} is told why and can ask again
        self.assertEqual(rig.reminders, [])
        self.assertIsNone(rig.app.tickets.get(1))

    def test_a_long_job_does_not_keep_the_caller_waiting(self):
        gate = threading.Event()
        fake = FakeHermes(polls=0, output="DONE: The plan is ready.")
        original = fake.handle

        def slow(method, path, headers, body):
            if method == "GET" and not gate.is_set():
                return 200, {"status": "running"}
            return original(method, path, headers, body)
        fake.server.handler = slow
        rig = self.rig(fake_hermes=fake, wait_secs=5.0, long_wait_secs=0.2)
        rig.app.runner.give_up_secs = 1e9
        started = time.monotonic()
        status, out = rig.app.tools.ask_agent(self.call, {"agent": "tutor", "question": "draft a plan", "patience": "long"})
        self.assertLess(time.monotonic() - started, 2.0)                   # not the five seconds of a quick lookup
        self.assertEqual((status, out["status"]), (200, "pending"))
        gate.set()
        rig.app.runner.wait(1, 10)

    def test_patience_must_be_quick_or_long(self):
        rig = self.rig()
        self.assertEqual(rig.app.tools.ask_agent(self.call, {"agent": "tutor", "question": "x", "patience": "forever"})[0], 400)
        self.assertEqual(rig.app.tools.do_for_max(self.call, {"request": "x", "patience": "now"})[0], 400)
        self.assertEqual(rig.app.tickets.unfinished(), [])

    def test_a_result_that_finishes_after_the_call_ended_is_not_marked_as_heard(self):
        rig = self.rig(fake_hermes=FakeHermes(polls=0, output="DONE: Fine."))
        rig.app.calls.end("conv_1", 30, 2)                                  # the caller hung up; the tool request still arrives
        _, out = rig.app.tools.ask_agent(self.call, {"agent": "assistant", "question": "late question"})
        self.assertEqual(out["status"], "done")
        self.assertEqual(rig.app.tickets.get(out["ticket"])["delivery"], "none")      # the call-back or Telegram will tell {{OWNER}}

    def test_bad_requests_are_refused_without_creating_tickets(self):
        rig = self.rig()
        for args in ({"agent": "carl", "question": "x"}, {"agent": "nobody", "question": "x"}, {"agent": "assistant", "question": " "},
                     {"agent": "assistant", "question": "x", "notify": "sometimes"}):
            self.assertEqual(rig.app.tools.ask_agent(self.call, args)[0], 400)
        self.assertEqual(rig.app.tools.do_for_max(self.call, {"request": ""})[0], 400)
        self.assertEqual(rig.app.tools.do_for_max(self.call, {"request": "x", "notify": "never"})[0], 400)
        self.assertEqual(rig.app.tickets.unfinished(), [])
        self.assertEqual(rig.hermes.runs, {})

    def test_compose_for_each_kind(self):
        for kind in ("ask", "do", "do_confirmed"):
            text, instructions = tools.compose({"kind": kind, "request": "the thing"})
            self.assertIn("the thing", text)
            self.assertIn("Do not message or phone anyone yourself", instructions)
            self.assertIn("{{CHIEF}} is the only one who rings {{OWNER}}", instructions)        # {{OWNER}}: agents never ring him back, only {{CHIEF}}


if __name__ == "__main__":
    unittest.main()
