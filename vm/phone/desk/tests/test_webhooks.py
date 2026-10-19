import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from desk import calls as calls_module, persona  # noqa: E402
from helpers import FakeHermes  # noqa: E402
from rig import MAX, Rig  # noqa: E402


def transcription(conversation_id, duration=65, user=True, voicemail=False, gist="They spoke."):
    transcript = [{"role": "agent", "message": "{{SIR}}, it's {{CHIEF}}. I have the news you were waiting for."}]
    if user:
        transcript.append({"role": "user", "message": "Thank you, {{CHIEF}}."})
    if voicemail:
        transcript.append({"role": "agent", "message": "", "tool_calls": [{"tool_name": "voicemail_detection"}]})
    return {"type": "post_call_transcription", "event_timestamp": 1,
            "data": {"conversation_id": conversation_id, "transcript": transcript,
                     "metadata": {"call_duration_secs": duration, "termination_reason": ""},
                     "analysis": {"transcript_summary": gist}}}


def with_tool_results(event, *results):
    """Add an agent turn that called tools; each result is (is_error, text the tool returned)."""
    event["data"]["transcript"].append({
        "role": "agent", "message": "", "tool_calls": [{"tool_name": "do_for_max"} for _ in results],
        "tool_results": [{"tool_name": "do_for_max", "is_error": error, "result_value": value} for error, value in results]})
    return event


ABANDONED = "Tool execution was abandoned due to user input"


def with_ring_results(event, *statuses, contact="your test dad"):
    """Add one agent turn per call_someone result; each is the status the desk answered with (an error is ('error', text))."""
    for status in statuses:
        payload = {"status": status, "contact": contact, "message": "..."}               # a refusal in words names the person too
        event["data"]["transcript"].append({
            "role": "agent", "message": "", "tool_calls": [{"tool_name": "call_someone"}],
            "tool_results": [{"tool_name": "call_someone", "is_error": False, "result_value": json.dumps(payload)}]})
    return event


class WebhooksTest(unittest.TestCase):
    def rig(self, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rig = Rig(tmp.name, fake_hermes=kw.pop("fake_hermes", FakeHermes(polls=0, output="{{SIR}}, all done.")), **kw)
        self.addCleanup(rig.close)
        self.summarised = threading.Event()
        original = rig.app.summaries.send

        def send(*args, **kwargs):
            result = original(*args, **kwargs)
            self.summarised.set()
            return result
        rig.app.summaries.send = send
        return rig

    def not_rung_notes(self, rig):
        return [t for t in rig.telegram if "did not ring" in t]

    def test_a_ring_that_still_needed_a_yes_when_the_call_ended_is_told_to_max_whatever_carl_said(self):
        # 5 Oct 2026, 23:08: {{CHIEF}} asked the tool with confirmed true and no read-back, got needs_yes, and still told {{OWNER}} he was ringing
        rig = self.rig()
        rig.app.calls.start_inbound("conv_ring", "max")
        event = with_ring_results(transcription("conv_ring"), "needs_yes")
        rig.app.webhooks.post_call(event)
        self.assertTrue(self.summarised.wait(5))
        self.assertEqual(self.not_rung_notes(rig),
                         ["{{SIR}}, I did not ring your test dad after all: the call ended before I had your yes. Ask me again whenever you like."])
        sent = rig.hermes.runs["run_1"]["input"]                                         # the note writer is told it did not happen
        self.assertIn("NOT DONE", sent)
        self.assertIn("The call to your test dad was never placed: it still needed {{OWNER}}'s yes.", sent)
        self.assertIn("NOT DONE", rig.hermes.runs["run_1"]["instructions"])

    def test_no_such_note_when_the_ring_went_out_failed_in_words_or_was_never_asked_for(self):
        for statuses in (("needs_yes", "calling"), ("calling",), ("failed",), ("needs_yes", "failed"), ()):
            rig = self.rig()
            rig.app.calls.start_inbound("conv_ring", "max")
            rig.app.webhooks.post_call(with_ring_results(transcription("conv_ring"), *statuses))
            self.assertTrue(self.summarised.wait(5))
            self.assertEqual(self.not_rung_notes(rig), [], statuses)
            self.assertNotIn("NOT DONE", rig.hermes.runs["run_1"]["input"], statuses)

    def test_two_people_asked_about_and_only_one_rung_is_told_for_the_other(self):
        rig = self.rig()
        rig.app.calls.start_inbound("conv_ring", "max")
        event = with_ring_results(transcription("conv_ring"), "needs_yes", "calling", contact="your father")
        event = with_ring_results(event, "needs_yes", contact="your grandmother")
        rig.app.webhooks.post_call(event)
        self.assertTrue(self.summarised.wait(5))
        notes = self.not_rung_notes(rig)
        self.assertEqual(len(notes), 1)
        self.assertIn("your grandmother", notes[0])
        self.assertNotIn("your father", notes[0])

    def test_a_ring_tool_error_or_an_odd_result_is_ignored_not_a_crash(self):
        rig = self.rig()
        rig.app.calls.start_inbound("conv_ring", "max")
        event = transcription("conv_ring")
        event["data"]["transcript"].append({"role": "agent", "message": "", "tool_calls": [{"tool_name": "call_someone"}], "tool_results": [
            {"tool_name": "call_someone", "is_error": True, "result_value": ABANDONED},
            {"tool_name": "call_someone", "is_error": False, "result_value": "not json"},
            {"tool_name": "call_someone", "is_error": False, "result_value": json.dumps([1, 2])},
            {"tool_name": "call_someone", "is_error": False, "result_value": None}]})
        self.assertEqual(rig.app.webhooks.post_call(event), {"ok": True})
        self.assertTrue(self.summarised.wait(5))
        self.assertEqual(self.not_rung_notes(rig), [])

    def ring_back(self, rig):
        """A finished ticket, a call-back placed for it: returns (ticket id, dial id)."""
        ticket = rig.app.tickets.open("ask", "assistant", "what is on tomorrow", conversation_id="conv_old")
        rig.app.tickets.finish(ticket["id"], "Nothing booked, {{sir}}.")
        rig.clock.now += rig.cfg.batch_window_secs
        self.assertEqual(rig.app.callbacks.tick(), "ringing")
        return ticket["id"], rig.app.dialer.by_conversation("conv_out1")["id"]

    def test_max_ringing_in_gets_the_brief_and_a_working_token(self):
        rig = self.rig()
        body = {"caller_id": "+44 7700 900123", "agent_id": "agent_1", "called_number": "+44000", "call_sid": "CA1",
                "conversation_id": "conv_in"}
        out = rig.app.webhooks.initiation(body)
        values = out["dynamic_variables"]
        self.assertEqual(out["type"], "conversation_initiation_client_data")
        self.assertEqual((values["caller_mode"], values["greeting"]), ("max", "Good afternoon, {{sir}}. What can I do for you?"))
        self.assertEqual(rig.app.calls.by_token(values["secret__desk_token"])["conversation_id"], "conv_in")
        self.assertEqual(rig.app.webhooks.initiation(body)["dynamic_variables"]["secret__desk_token"], values["secret__desk_token"])

    def test_a_stranger_gets_message_taking_with_no_brief_and_no_token(self):
        rig = self.rig()
        out = rig.app.webhooks.initiation({"caller_id": "+441234567890", "conversation_id": "conv_x"})
        values = out["dynamic_variables"]
        self.assertEqual((values["caller_mode"], values["brief"], values["secret__desk_token"]), ("stranger", "", "none"))
        self.assertIn(persona.TITLE, values["greeting"])
        self.assertNotRegex(values["greeting"], r"\bAI\b")
        self.assertIsNone(rig.app.calls.by_token(rig.app.calls.by_conversation("conv_x")["token"]))

    def test_a_strangers_message_reaches_max_with_their_number_and_no_agent_sees_it(self):
        rig = self.rig()
        rig.app.webhooks.initiation({"caller_id": "01234 567890", "conversation_id": "conv_x"})
        self.assertEqual(rig.app.calls.by_conversation("conv_x")["caller"], "+441234567890")
        rig.app.webhooks.post_call(transcription("conv_x", duration=50))
        self.assertTrue(self.summarised.wait(5))
        for _ in range(50):
            if rig.telegram:
                break
            time.sleep(0.05)
        self.assertEqual(len(rig.telegram), 1)
        self.assertTrue(rig.telegram[0].startswith("Someone else rang (0:50) and {{CHIEF}} took a message.\nFrom +441234567890."))
        self.assertEqual(rig.hermes.runs, {})
        rig.app.webhooks.initiation({"caller_id": MAX, "conversation_id": "conv_max"})
        self.assertEqual(rig.app.calls.by_conversation("conv_max")["caller"], "")       # {{OWNER}}'s own number is not kept

    def test_an_answered_callback_is_delivered_and_summarised(self):
        rig = self.rig()
        ticket_id, dial_id = self.ring_back(rig)
        out = rig.app.webhooks.post_call(transcription("conv_out1"))
        self.assertEqual(out, {"ok": True})
        self.assertTrue(self.summarised.wait(5))
        self.assertEqual(rig.app.tickets.get(ticket_id)["delivery"], "delivered")
        self.assertEqual(rig.app.dialer.get(dial_id)["status"], "answered")
        self.assertEqual(rig.app.calls.by_conversation("conv_out1")["duration_secs"], 65)
        for _ in range(50):
            if rig.telegram:
                break
            time.sleep(0.05)
        self.assertEqual(rig.telegram, ["Call summary (1:05)\n{{SIR}}, all done."])

    def test_an_unanswered_callback_reaches_telegram_as_a_voice_note_and_text(self):
        rig = self.rig()
        ticket_id, _ = self.ring_back(rig)
        rig.app.webhooks.post_call(transcription("conv_out1", duration=40, user=False))
        self.assertEqual(rig.app.tickets.get(ticket_id)["delivery"], "telegram")
        self.assertTrue(rig.telegram[0].startswith("[[audio_as_voice]]"))
        self.assertIn("Nothing booked, {{sir}}.", rig.telegram[1])
        self.assertEqual(len(rig.telegram), 2)                           # and no call summary for a call nobody answered
        self.assertFalse(self.summarised.is_set())

    def test_a_voicemail_counts_as_unanswered_and_gets_no_summary(self):
        rig = self.rig()
        ticket_id, _ = self.ring_back(rig)
        rig.app.webhooks.post_call(transcription("conv_out1", voicemail=True))
        self.assertEqual(rig.app.tickets.get(ticket_id)["delivery"], "telegram")
        self.assertFalse(self.summarised.is_set())

    def test_call_initiation_failure_falls_back_to_telegram(self):
        rig = self.rig()
        ticket_id, _ = self.ring_back(rig)
        out = rig.app.webhooks.post_call({"type": "call_initiation_failure",
                                          "data": {"conversation_id": "conv_out1", "failure_reason": "no-answer"}})
        self.assertEqual(out, {"ok": True})
        self.assertEqual(rig.app.tickets.get(ticket_id)["delivery"], "telegram")
        self.assertEqual(rig.app.dialer.by_conversation("conv_out1")["status"], "no_answer")

    def test_webhook_retries_are_handled_once(self):
        rig = self.rig()
        self.ring_back(rig)
        event = transcription("conv_out1", user=False)
        rig.app.webhooks.post_call(event)
        count = len(rig.telegram)
        self.assertEqual(rig.app.webhooks.post_call(event), {"ok": True, "duplicate": True})
        self.assertEqual(len(rig.telegram), count)

    def test_an_event_that_failed_to_process_is_handled_when_elevenlabs_retries(self):
        rig = self.rig()
        ticket_id, dial_id = self.ring_back(rig)
        real = rig.app.callbacks.on_call_settled
        rig.app.callbacks.on_call_settled = lambda *a: (_ for _ in ()).throw(RuntimeError("database busy"))
        with self.assertRaises(RuntimeError):
            rig.app.webhooks.post_call(transcription("conv_out1", user=False))
        rig.app.callbacks.on_call_settled = real
        self.assertEqual(rig.app.webhooks.post_call(transcription("conv_out1", user=False)), {"ok": True})
        self.assertEqual(rig.app.tickets.get(ticket_id)["delivery"], "telegram")

    def test_events_without_a_conversation_and_other_types_are_ignored(self):
        rig = self.rig()
        self.assertEqual(rig.app.webhooks.post_call({"type": "post_call_transcription", "data": {}})["ignored"],
                         "no conversation id")
        self.assertEqual(rig.app.webhooks.post_call({"type": "post_call_audio", "data": {"conversation_id": "c"}}), {"ok": True})

    def test_an_ordinary_inbound_call_just_ends_and_is_summarised(self):
        rig = self.rig()
        rig.app.webhooks.initiation({"caller_id": MAX, "conversation_id": "conv_in"})
        self.assertTrue(rig.app.calls.any_active())
        rig.app.webhooks.post_call(transcription("conv_in", duration=90))
        self.assertTrue(self.summarised.wait(5))
        self.assertFalse(rig.app.calls.any_active())
        self.assertEqual(rig.app.calls.by_conversation("conv_in")["user_turns"], 1)

    def heard_call(self, rig):
        """An inbound call of {{OWNER}}'s with one finished ticket handed over 'in the call': (rig, ticket id)."""
        rig.app.webhooks.initiation({"caller_id": MAX, "conversation_id": "conv_in"})
        ticket = rig.app.tickets.open("do_confirmed", "default", "set a reminder", conversation_id="conv_in")
        rig.app.tickets.finish(ticket["id"], "DONE: It is set.")
        rig.app.tickets.set_delivery([ticket["id"]], "in_call")
        rig.clock.now += 20
        return ticket["id"]

    def test_a_result_that_never_reached_carl_goes_out_after_the_call(self):
        rig = self.rig()
        tid = self.heard_call(rig)
        rig.app.webhooks.post_call(with_tool_results(transcription("conv_in", duration=90), (True, ABANDONED)))
        ticket = rig.app.tickets.get(tid)
        self.assertEqual((ticket["delivery"], ticket["delivered_at"]), ("none", None))   # the call-back or Telegram will tell {{OWNER}}
        self.assertEqual([c["id"] for c in rig.app.tickets.candidates()], [tid])

    def test_a_result_carl_did_hear_is_not_sent_again(self):
        import json
        rig = self.rig()
        tid = self.heard_call(rig)
        heard = json.dumps({"status": "done", "agent": "{{CHIEF}}", "answer": "It is set.", "needs_max": False, "ticket": tid})
        rig.app.webhooks.post_call(with_tool_results(transcription("conv_in", duration=90), (True, ABANDONED), (False, heard)))
        self.assertEqual(rig.app.tickets.get(tid)["delivery"], "in_call")
        rig.app.tickets.set_delivery([tid], "none", only_from=("in_call",))
        rig.app.tickets.set_delivery([tid], "in_call")
        listed = json.dumps({"finished": [{"agent": "{{CHIEF}}", "asked": "x", "answer": "y", "needs_max": False, "ticket": tid}],
                             "still_working": []})
        rig.app.webhooks.post_call(with_tool_results(transcription("conv_in2", duration=90), (False, listed)))
        self.assertEqual(rig.app.tickets.get(tid)["delivery"], "in_call")                 # a result listed by check_pending counts too

    def test_nothing_is_released_when_the_transcript_shows_no_tool_calls(self):
        rig = self.rig()
        tid = self.heard_call(rig)
        rig.app.webhooks.post_call(transcription("conv_in", duration=90))                 # no tool data at all: do not guess
        self.assertEqual(rig.app.tickets.get(tid)["delivery"], "in_call")


if __name__ == "__main__":
    unittest.main()
