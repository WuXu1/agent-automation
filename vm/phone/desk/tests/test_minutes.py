import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from desk import config, db, eleven, minutes, twilio  # noqa: E402
from helpers import FakeClock  # noqa: E402


def utc(y, m, d, h=0, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=dt.timezone.utc).timestamp()


class FakeEleven:
    def __init__(self):
        self.reset, self.durations, self.error, self.asked_since = utc(2026, 11, 3, 10, 39), [], None, None
        self.credits = None             # (used, limit) of the plan's credits, or None when the account does not say

    def subscription(self):
        if self.error:
            raise self.error
        out = {"next_character_count_reset_unix": int(self.reset)}
        if self.credits:
            out["character_count"], out["character_limit"] = self.credits
        return out

    def conversations_since(self, start_unix, agent_id=None, max_pages=10):
        self.asked_since = start_unix
        return [{"call_duration_secs": d} for d in self.durations]


class FakeTwilio:
    def __init__(self):
        self.url, self.sets, self.fail = "https://eleven/inbound", [], False

    def get_number(self, sid):
        return {"voice_url": self.url}

    def set_voice_url(self, sid, url, method="POST"):
        if self.fail:
            raise twilio.TwilioError("HTTP 500")
        self.url = url
        self.sets.append(url)


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def text(self, text, kind):
        self.messages.append(text)
        return True


class PeriodTest(unittest.TestCase):
    def test_the_period_began_a_calendar_month_before_the_reset(self):
        self.assertEqual(minutes.period_start(utc(2026, 11, 3, 10, 39)), utc(2026, 10, 3, 10, 39))
        self.assertEqual(minutes.period_start(utc(2026, 1, 15)), utc(2025, 12, 15))
        self.assertEqual(minutes.period_start(utc(2026, 3, 31)), utc(2026, 2, 28))

    def test_each_conversation_is_rounded_up_to_whole_minutes(self):
        convs = [{"call_duration_secs": s} for s in (20, 61, 0, 600)]
        self.assertEqual(minutes.billed_minutes(convs), 1 + 2 + 0 + 10)


class MinutesTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(now=utc(2026, 10, 20, 12))
        self.db = db.DB(":memory:")
        self.addCleanup(self.db.close)
        self.cfg = config.Config(twilio_number_sid="PN1", public_base="https://hermes-vm.example:8443")
        self.eleven, self.twilio, self.notifier = FakeEleven(), FakeTwilio(), FakeNotifier()
        self.m = minutes.Minutes(self.cfg, self.db, self.eleven, self.twilio, self.notifier, self.clock)

    def use(self, total_minutes):
        self.eleven.durations = [60 * total_minutes]

    def test_status_and_text(self):
        self.assertFalse(self.m.status()["known"])
        self.assertEqual(self.m.text(), "")
        self.use(100)
        status = self.m.refresh()
        self.assertEqual((status["used"], status["limit"], status["left"]), (100, 270, 170))
        self.assertEqual(self.eleven.asked_since, minutes.period_start(self.eleven.reset))
        self.assertEqual(self.m.text(), "CALL MINUTES: 100 of 270 used this billing period (resets 3 November); 170 left.")
        self.assertEqual(self.notifier.messages, [])

    def test_heads_up_once_at_eighty_percent(self):
        self.use(215)
        self.m.refresh()
        self.assertEqual(self.notifier.messages, [])
        self.use(216)
        self.m.refresh()
        self.m.refresh()
        self.assertEqual(len(self.notifier.messages), 1)
        self.assertIn("216 of this month's 270", self.notifier.messages[0])
        self.assertIn("Running low", self.m.text())

    def test_the_line_closes_at_the_limit_and_dials_stop(self):
        self.use(270)
        self.m.refresh()
        self.assertTrue(self.m.is_closed())
        self.assertEqual(self.twilio.url, "https://hermes-vm.example:8443/twiml/closed")
        self.assertEqual(self.db.kv_get("line_voice_url"), "https://eleven/inbound")
        self.assertEqual(self.m.blocked_reason(), "the line is closed until the minutes reset")
        self.assertEqual(self.m.text(), "THE PHONE LINE IS CLOSED: this month's call minutes are used up.")
        self.m.refresh()
        self.assertEqual(self.twilio.sets, ["https://hermes-vm.example:8443/twiml/closed"])   # switched once
        self.assertEqual(len(self.notifier.messages), 2)                                      # warning, then closing

    def test_the_line_reopens_when_the_period_resets(self):
        self.use(270)
        self.m.refresh()
        self.eleven.reset = utc(2026, 12, 3, 10, 39)
        self.use(3)
        self.m.refresh()
        self.assertFalse(self.m.is_closed())
        self.assertEqual(self.twilio.url, "https://eleven/inbound")
        self.assertIn("open again", self.notifier.messages[-1])
        self.assertIsNone(self.m.blocked_reason())

    def test_it_stays_closed_while_usage_is_still_high_in_the_same_period(self):
        self.use(270)
        self.m.refresh()
        self.use(265)                       # a conversation was removed or recounted, still near the limit
        self.m.refresh()
        self.assertTrue(self.m.is_closed())

    def test_a_failed_twilio_switch_is_retried_on_the_next_refresh(self):
        self.twilio.fail = True
        self.use(270)
        self.m.refresh()
        self.assertTrue(self.m.is_closed())
        self.assertEqual(self.twilio.sets, [])
        self.twilio.fail = False
        self.m.refresh()
        self.assertEqual(self.twilio.sets, ["https://hermes-vm.example:8443/twiml/closed"])

    def test_an_elevenlabs_outage_changes_nothing(self):
        self.use(100)
        self.m.refresh()
        self.eleven.error = eleven.ElevenError("Timeout", None, definite=False)
        self.assertIsNone(self.m.refresh())
        self.assertEqual(self.m.status()["used"], 100)
        self.assertFalse(self.m.is_closed())

    def test_without_twilio_configured_it_still_stops_the_call_backs(self):
        self.cfg.twilio_number_sid = ""
        m = minutes.Minutes(self.cfg, self.db, self.eleven, None, self.notifier, self.clock)
        self.use(270)
        m.refresh()
        self.assertTrue(m.is_closed())



class CreditsTest(unittest.TestCase):
    """ElevenLabs credits (shared by calls and voice notes) can run out before the minutes do: the line then closes the same way."""

    setUp = MinutesTest.setUp
    use = MinutesTest.use

    def test_status_shows_the_credits_and_the_brief_text_is_unchanged(self):
        self.use(10)
        self.eleven.credits = (42514, 131000)
        status = self.m.refresh()
        self.assertEqual(status["credits"], {"used": 42514, "limit": 131000, "left": 88486})
        self.assertEqual(self.m.text(), "CALL MINUTES: 10 of 270 used this billing period (resets 3 November); 260 left.")
        self.assertEqual(self.notifier.messages, [])

    def test_no_credit_figures_never_close_the_line(self):
        self.use(10)
        self.m.refresh()
        self.assertNotIn("credits", self.m.status())
        self.assertFalse(self.m.is_closed())

    def test_heads_up_once_at_eighty_percent_of_the_credits(self):
        self.use(10)
        self.eleven.credits = (104799, 131000)
        self.m.refresh()
        self.assertEqual(self.notifier.messages, [])
        self.eleven.credits = (104800, 131000)
        self.m.refresh()
        self.m.refresh()
        self.assertEqual(len(self.notifier.messages), 1)
        self.assertIn("104800 of this month's 131000 ElevenLabs credits", self.notifier.messages[0])
        self.assertIn("as text", self.notifier.messages[0])
        self.assertFalse(self.m.is_closed())

    def test_the_line_closes_when_the_credits_are_nearly_gone(self):
        self.use(10)
        self.eleven.credits = (131000 - self.cfg.credit_reserve, 131000)
        self.m.refresh()
        self.assertTrue(self.m.is_closed())
        self.assertEqual(self.twilio.url, "https://hermes-vm.example:8443/twiml/closed")
        self.assertEqual(self.m.closed_reason(), "credits")
        self.assertEqual(self.m.blocked_reason(), "the line is closed until the voice credits reset")
        self.assertEqual(self.m.text(), "THE PHONE LINE IS CLOSED: this month's voice credits are used up.")
        self.assertIn("credits are nearly used up", self.notifier.messages[-1])
        self.assertIn("as text", self.notifier.messages[-1])

    def test_it_stays_closed_for_credits_although_the_minutes_are_low(self):
        self.use(10)
        self.eleven.credits = (130000, 131000)
        self.m.refresh()
        self.m.refresh()
        self.assertTrue(self.m.is_closed())
        self.assertEqual(self.twilio.sets, ["https://hermes-vm.example:8443/twiml/closed"])

    def test_it_reopens_when_the_credits_reset(self):
        self.use(10)
        self.eleven.credits = (130000, 131000)
        self.m.refresh()
        self.eleven.reset = utc(2026, 12, 3, 10, 39)
        self.eleven.credits = (0, 131000)
        self.use(0)
        self.m.refresh()
        self.assertFalse(self.m.is_closed())
        self.assertEqual(self.twilio.url, "https://eleven/inbound")
        self.assertIsNone(self.m.blocked_reason())

    def test_closed_for_minutes_then_short_of_credits_after_the_reset_says_credits(self):
        self.use(270)
        self.eleven.credits = (60000, 131000)
        self.m.refresh()
        self.assertEqual(self.m.closed_reason(), "minutes")
        self.eleven.reset = utc(2026, 12, 3, 10, 39)
        self.eleven.credits = (9000, 10000)
        self.use(0)
        self.m.refresh()
        self.assertTrue(self.m.is_closed())
        self.assertEqual(self.m.closed_reason(), "credits")

    def test_a_smaller_plan_after_the_reset_keeps_it_closed_if_still_too_little(self):
        self.use(10)
        self.eleven.credits = (130000, 131000)
        self.m.refresh()
        self.eleven.reset = utc(2026, 12, 3, 10, 39)
        self.eleven.credits = (9000, 10000)          # a free plan, already used up by voice notes
        self.m.refresh()
        self.assertTrue(self.m.is_closed())


if __name__ == "__main__":
    unittest.main()
