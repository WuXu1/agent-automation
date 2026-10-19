import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from desk import brief, calls, config, contacts, db, dialer, eleven, persona, tickets, util, variables  # noqa: E402
from helpers import FakeClock  # noqa: E402

MAX = "+447700900123"
DAD, GRAN, PAL = "+447700900111", "+447700900222", "+447700900333"


def uk(hour, minute=0, day=5):
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=util.UK).timestamp()


class FakeEleven:
    def __init__(self, events):
        self.events, self.error, self.n, self.agent_ids = events, None, 0, []

    def outbound_call(self, agent_id, phone_number_id, to_number, dynamic_variables, ringing_timeout_secs=45):
        self.agent_ids.append(agent_id)
        self.events.append(("api", to_number, dynamic_variables))
        if self.error:
            raise self.error
        self.n += 1
        return {"conversation_id": f"conv_out{self.n}", "call_sid": f"CA{self.n}"}


class DialerTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.db = db.DB(":memory:")
        self.addCleanup(self.db.close)
        self.cfg = config.Config(max_number=MAX, agent_id="agent_1", phone_number_id="phnum_1", dial_mode="live")
        self.calls = calls.Calls(self.db, self.clock, self.cfg)
        self.events = []
        self.eleven = FakeEleven(self.events)
        self.reason = None
        self.dialer = dialer.Dialer(self.cfg, self.db, self.eleven, self.calls, self.clock, env={},
                                    blocked=lambda: self.reason)

    def place(self, to=MAX, claim=None, **kw):
        call = self.calls.prepare_outbound("callback")
        return self.dialer.place("callback", to, {"greeting": "{{SIR}}."}, call, claim=claim or (lambda dial_id: True), **kw)

    def dials(self):
        return self.db.q("SELECT status, error FROM dials ORDER BY id")

    def test_a_test_environment_never_dials_even_when_live(self):
        d = dialer.Dialer(self.cfg, self.db, self.eleven, self.calls, self.clock, env={"DESK_TEST": "1"})
        with self.assertRaises(dialer.DialBlocked) as ctx:
            d.place("callback", MAX, {}, self.calls.prepare_outbound("callback"))
        self.assertFalse(ctx.exception.retry)
        self.assertEqual((self.events, self.dials()), ([], []))

    def test_only_max_can_be_dialled(self):
        with self.assertRaises(dialer.DialBlocked) as ctx:
            self.place(to="+447700900999")
        self.assertFalse(ctx.exception.retry)
        self.assertEqual((self.events, self.dials()), ([], []))
        self.place(to="07700 900123")                                  # the same number written another way
        self.assertEqual(len(self.events), 1)

    def test_dry_mode_records_the_dial_and_calls_nobody(self):
        self.cfg.dial_mode = "dry"
        claimed = []
        row = self.place(claim=lambda dial_id: claimed.append(dial_id) or True)
        self.assertEqual(row["status"], "dry")
        self.assertEqual((self.events, claimed), ([], [row["id"]]))

    def test_the_claim_happens_before_the_request_goes_out(self):
        row = self.place(claim=lambda dial_id: self.events.append(("claim", dial_id)) or True)
        self.assertEqual([e[0] for e in self.events], ["claim", "api"])
        self.assertEqual((row["status"], row["conversation_id"], row["call_sid"]), ("called", "conv_out1", "CA1"))
        self.assertEqual(self.calls.get(row["call_id"])["conversation_id"], "conv_out1")

    def test_an_unclaimable_dial_is_aborted_without_a_request(self):
        with self.assertRaises(dialer.DialBlocked) as ctx:
            self.place(claim=lambda dial_id: False)
        self.assertFalse(ctx.exception.retry)
        self.assertEqual((self.events, [d["status"] for d in self.dials()]), ([], ["aborted"]))

    def test_a_refusal_is_failed_and_an_unknown_outcome_is_never_repeated(self):
        self.eleven.error = eleven.ElevenError("HTTP 422", 422, definite=True)
        with self.assertLogs("desk.dialer", "WARNING"):
            self.assertEqual(self.place()["status"], "failed")
        self.clock.now += 400
        self.eleven.error = eleven.ElevenError("Timeout", None, definite=False)
        with self.assertLogs("desk.dialer", "WARNING"):
            self.assertEqual(self.place()["status"], "unknown")
        with self.assertRaises(dialer.DialBlocked):                    # the unknown dial still blocks the recent window
            self.place()
        self.assertEqual(len(self.events), 2)

    def test_one_dial_per_recent_window(self):
        self.place()
        with self.assertRaises(dialer.DialBlocked) as ctx:
            self.place()
        self.assertTrue(ctx.exception.retry)
        self.clock.now += self.cfg.recent_dial_secs + 1
        self.place()
        self.assertEqual(len(self.events), 2)

    def test_hourly_and_daily_caps(self):
        self.cfg.recent_dial_secs, self.cfg.max_dials_per_hour, self.cfg.max_dials_per_day = 0, 2, 3
        self.place()
        self.place()
        with self.assertRaises(dialer.DialBlocked) as ctx:
            self.place()
        self.assertIn("hourly", ctx.exception.reason)
        self.clock.now += 3601
        self.place()
        self.clock.now += 3601
        with self.assertRaises(dialer.DialBlocked) as ctx:
            self.place()
        self.assertIn("daily", ctx.exception.reason)

    def test_a_closed_line_blocks_dials(self):
        self.reason = "the line is closed until the minutes reset"
        with self.assertRaises(dialer.DialBlocked) as ctx:
            self.place()
        self.assertEqual(ctx.exception.reason, "the line is closed until the minutes reset")
        self.assertFalse(ctx.exception.retry)                                 # no point waiting weeks: Telegram instead
        self.assertEqual((self.events, self.dials()), ([], []))

    def test_an_announced_test_call_needs_the_operator_switch(self):
        self.cfg.dial_mode = "dry"
        self.assertEqual(self.place(announced_test=True)["status"], "dry")
        self.dialer.env = {"DESK_ALLOW_TEST_DIAL": "1"}
        self.clock.now += 400
        self.assertEqual(self.place(announced_test=True)["status"], "called")
        self.clock.now += 400
        self.assertEqual(self.place()["status"], "dry")                # ordinary dials stay dry

    def test_stuck_dials_and_settling(self):
        row = self.place()
        self.assertEqual(self.dialer.stuck(600), [])
        self.clock.now += 3000
        self.assertEqual([d["id"] for d in self.dialer.stuck(600)], [row["id"]])
        self.dialer.settle(row["id"], "answered")
        self.assertEqual(self.dialer.stuck(600), [])
        self.assertEqual(self.dialer.by_conversation("conv_out1")["status"], "answered")

    def test_the_dials_table_stores_a_hash_not_the_number(self):
        self.place()
        stored = self.db.q("SELECT to_hash FROM dials")[0]["to_hash"]
        self.assertNotIn("7700", stored)
        self.assertEqual(stored, dialer.number_hash("07700 900123"))


class GuestDialerTest(unittest.TestCase):
    """A second gate, beside `place`, for calls to the people in the contact book (always with the guest agent)."""

    def setUp(self):
        self.clock = FakeClock(now=uk(14))
        self.db = db.DB(":memory:")
        self.addCleanup(self.db.close)
        self.cfg = config.Config(max_number=MAX, agent_id="agent_1", guest_agent_id="agent_guest", phone_number_id="phnum_1",
                                 dial_mode="live")
        self.calls = calls.Calls(self.db, self.clock, self.cfg)
        self.events = []
        self.eleven = FakeEleven(self.events)
        self.reason = None
        self.dialer = dialer.Dialer(self.cfg, self.db, self.eleven, self.calls, self.clock, env={}, blocked=lambda: self.reason)
        self.dad = contacts.Contact("dad", "your father", "Mr Smith", ("dad",), DAD)
        self.gran = contacts.Contact("gran", "your grandmother", "Mrs Smith", (), GRAN)
        self.pal = contacts.Contact("pal", "your friend", "Sam", (), PAL)

    def place(self, contact=None, claim=None):
        call = self.calls.prepare_outbound("guest")
        return self.dialer.place_guest(contact or self.dad, {"greeting": "Hello"}, call, claim=claim or (lambda dial_id: True))

    def refused(self, contact=None):
        """The reason given when the call is refused; nothing was sent and no dial was recorded."""
        before = self.db.q("SELECT COUNT(*) AS n FROM dials")[0]["n"]
        sent = len(self.events)
        with self.assertRaises(dialer.DialBlocked) as ctx:
            self.place(contact)
        self.assertEqual((len(self.events), self.db.q("SELECT COUNT(*) AS n FROM dials")[0]["n"]), (sent, before))
        return ctx.exception

    def test_a_guest_call_goes_out_with_the_guest_agent_to_the_contacts_number_only(self):
        row = self.place()
        self.assertEqual((row["purpose"], row["status"], row["conversation_id"]), ("guest", "called", "conv_out1"))
        self.assertEqual(self.eleven.agent_ids, ["agent_guest"])                       # never {{CHIEF}}'s phone agent
        self.assertEqual(self.events[0][1:], (DAD, {"greeting": "Hello"}))
        self.assertEqual(row["to_hash"], dialer.number_hash(DAD))
        self.assertNotIn("7700", row["to_hash"])
        self.assertEqual(self.calls.get(row["call_id"])["conversation_id"], "conv_out1")

    def test_a_test_environment_never_rings_a_guest(self):
        self.dialer.env = {"DESK_TEST": "1"}
        self.assertIn("test environment", self.refused().reason)

    def test_without_a_guest_agent_nobody_is_rung(self):
        self.cfg.guest_agent_id = ""
        self.assertIn("guest agent", self.refused().reason)

    def test_guest_calls_are_never_made_in_dry_mode_or_as_an_announced_test(self):
        self.cfg.dial_mode = "dry"
        self.dialer.env = {"DESK_ALLOW_TEST_DIAL": "1"}                               # the one exception for {{OWNER}}'s own test call
        self.assertIn("switched off", self.refused().reason)
        self.cfg.dial_mode = "live"
        self.place()
        self.assertEqual(len(self.events), 1)

    def test_a_rehearsal_contact_must_be_max_s_own_number_and_nobody_else_may_be(self):
        test_dad = contacts.Contact("test-dad", "your test dad", "Test Dad", (), MAX, rehearsal=True)
        self.assertEqual(self.place(test_dad)["status"], "called")
        self.clock.now += 700
        wrong = contacts.Contact("test-dad", "your test dad", "Test Dad", (), DAD, rehearsal=True)
        self.assertIn("rehearsal", self.refused(wrong).reason)
        self.clock.now += 700
        sneaky = contacts.Contact("me", "yourself", "{{OWNER}}", (), "07700 900123")        # {{OWNER}}'s number without the rehearsal flag
        self.assertIn("own number", self.refused(sneaky).reason)
        self.assertEqual(self.eleven.agent_ids, ["agent_guest"])

    def test_guests_may_be_rung_at_any_hour(self):
        # {{OWNER}} decides when {{CHIEF}} rings: the contact's stored hours (a leftover field) are no longer checked
        for day, (hour, minute) in enumerate(((3, 0), (8, 59), (21, 0), (23, 30)), start=6):
            self.clock.now = uk(hour, minute, day=day)                                # a fresh day each time: no limit gets in the way
            self.assertEqual(self.place()["status"], "called", (hour, minute))

    def test_a_closed_line_blocks_guest_calls(self):
        self.reason = "the line is closed until the minutes reset"
        blocked = self.refused()
        self.assertEqual(blocked.reason, "the line is closed until the minutes reset")
        self.assertFalse(blocked.retry)

    def test_the_same_person_is_not_rung_twice_within_ten_minutes(self):
        self.place()
        self.clock.now += 400                                                         # past the global three-minute window
        self.assertIn("a few minutes ago", self.refused().reason)
        self.clock.now += 300
        self.assertEqual(self.place()["status"], "called")

    def test_two_calls_a_day_per_person_and_four_in_all(self):
        self.place(self.dad)
        self.clock.now += 700
        self.place(self.dad)
        self.clock.now += 700
        self.assertIn("your father", self.refused(self.dad).reason)                    # the limit for this person
        self.assertIn("for today", self.refused(self.dad).reason)
        self.place(self.gran)
        self.clock.now += 700
        self.place(self.gran)
        self.clock.now += 700
        reason = self.refused(self.pal).reason                                         # four guests rung today: that is all
        self.assertIn("other people", reason)
        self.assertEqual(len(self.events), 4)
        self.clock.now += 86400                                                        # tomorrow all of it is available again
        self.assertEqual(self.place(self.dad)["status"], "called")

    def test_rehearsal_calls_do_not_use_up_what_the_people_the_assistant_rings_are_allowed(self):
        test_dad = contacts.Contact("test-dad", "your test dad", "Test Dad", (), MAX, rehearsal=True)
        self.place(test_dad)
        self.clock.now += 300
        self.assertIn("a few minutes ago", self.refused(test_dad).reason)                   # the ten-minute gap still protects {{OWNER}}'s phone
        for _ in range(3):                                                                  # but there is no per-day limit for it
            self.clock.now += 700
            self.assertEqual(self.place(test_dad)["status"], "called")
        self.clock.now += 700
        self.place(self.dad)                                                                # and four rehearsals left the guests' four untouched
        self.clock.now += 700
        self.place(self.dad)
        self.clock.now += 700
        self.place(self.gran)
        self.clock.now += 700
        self.place(self.gran)
        self.clock.now += 700
        self.assertIn("other people", self.refused(self.pal).reason)                       # four real guest calls: that is all
        self.assertIn("for today", self.refused(self.dad).reason)

    def test_the_global_dial_limits_still_apply_to_guest_calls(self):
        self.dialer.place("callback", MAX, {}, self.calls.prepare_outbound("callback"))   # {{OWNER}} was rung a minute ago
        self.clock.now += 60
        self.assertIn("a moment ago", self.refused().reason)
        self.clock.now += 400
        self.cfg.max_dials_per_hour = 1
        self.assertIn("hourly", self.refused().reason)
        self.cfg.max_dials_per_hour, self.cfg.max_dials_per_day = 6, 1
        self.assertIn("daily", self.refused().reason)

    def test_the_dial_is_recorded_and_claimed_before_the_request_goes_out(self):
        row = self.place(claim=lambda dial_id: self.events.append(("claim", dial_id)) or True)
        self.assertEqual([e[0] for e in self.events], ["claim", "api"])
        self.assertEqual(self.events[0][1], row["id"])

    def test_an_unclaimable_dial_is_aborted_without_a_request(self):
        with self.assertRaises(dialer.DialBlocked) as ctx:
            self.place(claim=lambda dial_id: False)
        self.assertFalse(ctx.exception.retry)
        self.assertEqual((self.events, [d["status"] for d in self.db.q("SELECT status FROM dials")]), ([], ["aborted"]))
        self.clock.now += 60
        self.assertEqual(self.place()["status"], "called")                              # an aborted dial never counted as a call

    def test_an_unknown_outcome_is_never_redialled_but_a_refusal_costs_the_person_nothing(self):
        self.eleven.error = eleven.ElevenError("HTTP 422", 422, definite=True)
        with self.assertLogs("desk.dialer", "WARNING"):
            self.assertEqual(self.place()["status"], "failed")                          # nothing was dialled
        self.eleven.error = eleven.ElevenError("Timeout", None, definite=False)
        with self.assertLogs("desk.dialer", "WARNING"):
            self.assertEqual(self.place()["status"], "unknown")                         # it may have rung
        self.clock.now += 400
        self.assertIn("a few minutes ago", self.refused().reason)                       # so it is never repeated at once
        self.assertEqual(len(self.events), 2)

    def test_a_guest_call_never_gets_a_working_tool_token(self):
        call = self.calls.prepare_outbound("guest")
        self.assertIsNone(self.calls.by_token(call["token"]))
        other = self.calls.prepare_outbound("callback")
        self.assertEqual(self.calls.by_token(other["token"])["id"], other["id"])        # {{OWNER}}'s own call-backs are unaffected

    def test_a_guest_call_in_progress_holds_back_call_backs(self):
        self.assertFalse(self.calls.any_active())
        row = self.place()
        self.assertTrue(self.calls.any_active())
        self.calls.end(row["conversation_id"], 60, 3)
        self.assertFalse(self.calls.any_active())

    def test_place_still_refuses_every_number_but_max_s(self):
        with self.assertRaises(dialer.DialBlocked):
            self.dialer.place("callback", DAD, {}, self.calls.prepare_outbound("callback"))
        self.assertEqual(self.events, [])


class VariablesTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(now=1_791_190_000.0)       # Monday 5 October 2026, morning, UK
        self.db = db.DB(":memory:")
        self.addCleanup(self.db.close)
        self.tickets = tickets.Tickets(self.db, self.clock)

        class StubBrief:
            def render(self):
                return "BRIEF TEXT"
        self.v = variables.Variables(config.Config(), self.clock, StubBrief(), self.tickets, lambda: "MINUTES: 1 of 270")

    def test_max_gets_the_full_set_with_his_token(self):
        out = self.v.build("max", "tok123")
        self.assertEqual(set(out), set(variables.NAMES))
        self.assertTrue(all(isinstance(value, str) for value in out.values()))
        self.assertEqual((out["greeting"], out["caller_mode"], out["brief"], out["secret__desk_token"]),
                         ("Good morning, {{sir}}. What can I do for you?", "max", "BRIEF TEXT", "tok123"))
        self.assertEqual(out["pending_text"], "Nothing pending.")
        self.assertEqual(out["now_text"], "Monday 05 October 2026, 09:46 UK time")

    def test_a_callback_carries_the_results(self):
        out = self.v.build("callback", "tok9", callback_text="{{ASSISTANT}}: nothing booked.")
        self.assertEqual((out["caller_mode"], out["callback_text"]), ("callback", "{{ASSISTANT}}: nothing booked."))
        self.assertIn("news you were waiting for", out["greeting"])                  # the fallback when no headline is given
        told = self.v.build("callback", "tok9", callback_text="x", opening="{{SIR}}, it's {{CHIEF}}. {{TUTOR}} has finished.")
        self.assertEqual(told["greeting"], variables.ANSWER_PAUSE + "{{SIR}}, it's {{CHIEF}}. {{TUTOR}} has finished.")
        self.assertTrue(out["greeting"].startswith(variables.ANSWER_PAUSE))        # {{OWNER}} answers, then {{CHIEF}} speaks ({{OWNER}}, 5 Oct 2026)
        self.assertGreaterEqual(variables.ANSWER_PAUSE.count("[long pause]"), 2)   # one tag measured at only 0.2 s, two at 1.2 to 1.6 s
        for purpose in ("max", "stranger"):
            self.assertNotIn("[", self.v.build(purpose, "tok")["greeting"])         # callers ringing in are greeted at once

    def test_build_guest_introduces_carl_by_his_title_and_carries_only_the_five_guest_variables(self):
        dad = contacts.Contact("dad", "your father", "Mr Smith", ("dad",), "+447700900111")
        out = self.v.build_guest(dad, "Ask whether he is free for dinner on Sunday.")
        self.assertEqual(set(out), set(variables.GUEST_NAMES))
        self.assertTrue(all(isinstance(value, str) for value in out.values()))
        self.assertEqual(out["greeting"], variables.ANSWER_PAUSE + "Hello, is that Mr Smith? It's {{CHIEF}}, {{OWNER}}'s assistant.")
        self.assertIn(persona.TITLE, out["greeting"])
        self.assertNotRegex(out["greeting"], r"\bAI\b")                                      # {{OWNER}} does not want the word said
        self.assertEqual((out["guest_name"], out["relationship_to_max"]), ("Mr Smith", "{{OWNER}}'s father"))
        self.assertEqual(out["purpose"], "Ask whether he is free for dinner on Sunday.")
        self.assertEqual(out["now_text"], "Monday 05 October 2026, 09:46 UK time")
        self.assertNotIn("7700", str(out))                                         # nothing of the number
        for name in ("brief", "secret__desk_token", "pending_text", "callback_text", "minutes_text", "caller_mode"):
            self.assertNotIn(name, out)                                              # nothing of {{OWNER}}'s

    def test_the_purpose_is_cleaned_and_clipped_before_the_guest_agent_sees_it(self):
        dad = contacts.Contact("dad", "your father", "Mr Smith", (), "+447700900111")
        dirty = "[happy] Ask {{brief}} if he  is\nfree <b>Sunday</b> key=abc123secret " + "and more " * 160
        out = self.v.build_guest(dad, dirty)["purpose"]
        self.assertLessEqual(len(out), 600)                                                # a chat has details: room for them
        for leftover in ("[happy]", "{{", "}}", "<b>", "\n", "  ", "abc123secret"):
            self.assertNotIn(leftover, out)
        self.assertTrue(out.startswith("Ask brief if he is free b Sunday /b key=[redacted]"), out)
        self.assertEqual(self.v.build_guest(dad, "")["purpose"], "")
        other = contacts.Contact("tennis", "Sandra from the club", "Sandra", (), "+447700900222")
        self.assertEqual(self.v.build_guest(other, "x")["relationship_to_max"], "Sandra from the club")
        self.assertEqual(self.v.build_guest(contacts.Contact("t", "Your test dad", "Test Dad", (), "+447700900123", rehearsal=True),
                                            "x")["relationship_to_max"], "{{OWNER}}'s test dad")

    def test_carl_is_told_the_names_but_never_a_number_and_a_stranger_nothing(self):
        self.assertEqual(self.v.build("max", "tok")["contacts_text"], "")                                 # no book, no names
        with tempfile.TemporaryDirectory() as tmp:
            book = contacts.ContactBook(Path(tmp) / "contacts.json", MAX)
            book.add("dad", "your father", "Mr Smith", DAD, aliases=("dad",))
            v = variables.Variables(config.Config(), self.clock, self.v.brief, self.tickets, None, book)
            for purpose in ("max", "callback", "test"):
                out = v.build(purpose, "tok")
                self.assertEqual(out["contacts_text"], "your father (dad)", purpose)
                self.assertNotIn("7700", str(out))
            self.assertEqual(v.build("stranger", "tok")["contacts_text"], "")

    def test_a_stranger_gets_no_brief_and_no_working_token_and_is_told_who_is_speaking(self):
        out = self.v.build("stranger", "tok123")
        self.assertEqual(set(out), set(variables.NAMES))
        self.assertEqual((out["brief"], out["secret__desk_token"], out["caller_mode"]), ("", "none", "stranger"))
        self.assertIn(persona.TITLE, out["greeting"])
        self.assertNotRegex(out["greeting"], r"\bAI\b")
        self.assertNotIn("tok123", str(out))


if __name__ == "__main__":
    unittest.main()
