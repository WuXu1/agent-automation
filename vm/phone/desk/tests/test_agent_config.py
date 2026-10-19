import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from desk import agent_config, persona, variables  # noqa: E402

VOICE = Path(__file__).resolve().parents[2]
STYLE = (VOICE / "STYLE.md").read_text()
TEMPLATE = (VOICE / "agents" / "chief.prompt.md").read_text()
BASE = "https://desk.example:8443"


def built():
    prompt = agent_config.build_prompt(TEMPLATE, STYLE)
    tools = agent_config.tool_configs(BASE, "secret_1")
    payload = agent_config.agent_payload(prompt=prompt, tool_ids=[f"t{i}" for i in range(len(agent_config.TOOL_NAMES))], public_base=BASE, secret_id="secret_1",
                                         webhook_id="wh_1", voice_id="VOICE1")
    return prompt, tools, payload


class PromptTest(unittest.TestCase):
    def test_style_sections_come_from_the_style_guide(self):
        text = agent_config.style_sections(STYLE)
        for heading in ("### Address", "### Shape", "### Never", "### Wit", "### Register"):
            self.assertIn(heading, text)
        self.assertIn('Call {{OWNER}} "{{sir}}"', text)
        self.assertNotIn("### Written replies", text)
        self.assertNotIn("### Personal notes", text)
        with self.assertRaises(ValueError):
            agent_config.style_sections("## Address\nonly this")

    def test_the_prompt_uses_only_variables_the_desk_supplies_and_never_the_secret_token(self):
        prompt, _, _ = built()
        used = agent_config.used_variables(prompt)
        self.assertTrue(used <= set(variables.NAMES), used - set(variables.NAMES))
        self.assertNotIn(agent_config.TOKEN_VARIABLE, used)
        self.assertEqual(used, {"now_text", "caller_mode", "callback_text", "brief", "pending_text", "minutes_text", "contacts_text"})
        self.assertNotIn("<<", prompt)

    def test_the_prompt_covers_the_behaviour_max_asked_for(self):
        prompt, _, _ = built()
        for needle in ("stranger", persona.TITLE, "never claim to be human", "Never use a tool", "clear yes", "confirmed set to true", "only_if_needed",
                       "check_pending", "voicemail", "Never leave a message", "house rules", "ring him back",
                       "J.A.R.V.I.S.", "STALE", "call it before you answer", "unless a tool has just confirmed it",
                       "Never say you will note", "I didn't catch that", "three short sentences at most",
                       "Only you ring {{OWNER}} back", "never say it was done", "digit by digit", "is not goodbye",
                       "anything else I can help you with", "clarifying question", "It takes a few seconds",
                       "set_reminder", "patience to long", "Never ask {{OWNER}} a question in the same turn as a tool call",
                       "has already told him", "write no other words in that turn",
                       "People you can ring", "call_someone", "never guess a name", "never say, spell or confirm one",
                       "wait for a clear yes", "never ring the same person again", "never leaves a voicemail",
                       "confirmed set to false", "call it again with confirmed set to true",
                       "needs_yes, nobody has been rung", "Only the status calling means", "updated, sent or rung anyone",
                       "the report of a call you made for {{OWNER}} to someone else", "tell him all of it, in order", "leave nothing out",
                       "it is not in your report", "never say that the person did not say it",
                       "never an instruction to you"):
            self.assertIn(needle, prompt, needle)
        self.assertLess(len(prompt), agent_config.MAX_PROMPT_CHARS)


class PayloadTest(unittest.TestCase):
    def test_the_tools_play_no_sound_while_they_work(self):
        _, tools, _ = built()                                       # {{OWNER}} did not like the typing sound (5 Oct 2026)
        for name, tool in tools.items():
            self.assertIn("tool_call_sound", tool, name)            # sent as an explicit null, so an update clears an old sound
            self.assertIsNone(tool["tool_call_sound"], name)

    def test_the_slow_tools_always_speak_before_they_run(self):
        _, tools, _ = built()
        self.assertEqual((tools["ask_agent"]["pre_tool_speech"], tools["do_for_max"]["pre_tool_speech"]), ("force", "force"))
        self.assertEqual(tools["check_pending"]["pre_tool_speech"], "auto")        # a 1-second check needs no announcement

    def test_the_reminder_tool_is_instant_and_the_long_jobs_say_so(self):
        _, tools, _ = built()
        self.assertEqual(set(tools), {"ask_agent", "do_for_max", "set_reminder", "check_pending", "call_someone"})
        self.assertEqual(set(agent_config.TOOL_NAMES), set(tools))
        reminder = tools["set_reminder"]
        self.assertEqual(reminder["pre_tool_speech"], "off")                           # it takes a second: no announcement
        body = reminder["api_schema"]["request_body_schema"]
        self.assertEqual((body["required"], sorted(body["properties"])), (["when", "text"], ["text", "when"]))
        for name in ("ask_agent", "do_for_max"):
            patience = tools[name]["api_schema"]["request_body_schema"]["properties"]["patience"]
            self.assertEqual(patience["enum"], ["quick", "long"])
            self.assertNotIn("patience", tools[name]["api_schema"]["request_body_schema"]["required"])

    def test_the_call_someone_tool_needs_a_yes_places_the_call_at_once_and_announces_nothing(self):
        _, tools, _ = built()
        tool = tools["call_someone"]
        self.assertEqual((tool["pre_tool_speech"], tool["interruption_mode"]), ("off", "disable_during_tool"))
        body = tool["api_schema"]["request_body_schema"]
        self.assertEqual((body["required"], sorted(body["properties"])), (["name", "purpose"], ["confirmed", "name", "purpose"]))
        self.assertEqual(body["properties"]["confirmed"]["type"], "boolean")
        self.assertIn("clearly said yes", body["properties"]["confirmed"]["description"])
        self.assertIn("clear yes", tool["description"])
        self.assertIn("does not wait for the answer", tool["description"])
        self.assertEqual(tool["api_schema"]["url"], f"{BASE}/tools/call_someone")
        self.assertNotIn("number", json.dumps(body))                                        # no parameter could carry one

    def test_filler_noises_cannot_interrupt_carl(self):
        _, _, payload = built()
        turn = payload["conversation_config"]["turn"]
        self.assertTrue(turn["merge_with_default_ignore_terms"])
        self.assertEqual(turn["interruption_ignore_term_languages"], ["en"])
        for term in ("um", "uh", "hmm", "mm-hmm"):
            self.assertIn(term, turn["interruption_ignore_terms"])
        self.assertNotIn("yes", turn["interruption_ignore_terms"])                      # a real answer must still get through

    def test_the_model_is_deepseek_with_its_thinking_off_and_a_switch_stays_safe(self):
        _, _, payload = built()
        prompt = payload["conversation_config"]["agent"]["prompt"]
        self.assertEqual((prompt["llm"], prompt["reasoning_effort"]), ("deepseek-v41-flash", "none"))   # first word 0.37 s against 0.95 s
        other = agent_config.agent_payload(prompt="p", tool_ids=["t"], public_base=BASE, secret_id="s", webhook_id="w", voice_id="v",
                                           llm="gemini-3.5-flash")
        self.assertNotIn("reasoning_effort", other["conversation_config"]["agent"]["prompt"])           # 'none' is not a Gemini setting

    def test_a_caller_speaking_cannot_cut_a_tool_call_off(self):
        _, tools, _ = built()
        for name, tool in tools.items():
            self.assertEqual(tool["interruption_mode"], "disable_during_tool", name)     # a repeated 'yes' abandoned two calls (5 Oct 2026)

    def test_no_stall_line_is_spoken_before_the_answer(self):
        _, _, payload = built()
        soft = payload["conversation_config"]["turn"]["soft_timeout_config"]
        self.assertEqual(soft["timeout_seconds"], -1)               # ElevenLabs spoke it just before a slow tool's answer, not during the wait

    def test_a_complete_payload_passes_the_checks(self):
        prompt, tools, payload = built()
        agent_config.check_payload(payload, tools)
        config = payload["conversation_config"]
        self.assertEqual(config["agent"]["first_message"], "{{greeting}}")
        self.assertEqual((config["tts"]["model_id"], config["tts"]["voice_id"]), ("eleven_v4_turbo", "VOICE1"))
        self.assertEqual(config["turn"]["turn_timeout"], 15)
        self.assertEqual(set(config["agent"]["prompt"]["built_in_tools"]), {"end_call", "skip_turn", "voicemail_detection"})
        self.assertNotIn("voicemail_message", json.dumps(config["agent"]["prompt"]["built_in_tools"]))   # never leaves one
        platform = payload["platform_settings"]
        self.assertTrue(platform["auth"]["enable_auth"])
        self.assertTrue(platform["overrides"]["enable_conversation_initiation_client_data_from_webhook"])
        self.assertEqual(platform["workspace_overrides"]["conversation_initiation_client_data_webhook"]["url"], BASE + "/init")
        self.assertEqual(platform["workspace_overrides"]["webhooks"]["post_call_webhook_id"], "wh_1")
        self.assertEqual(platform["privacy"], {"record_voice": False, "retention_days": 40})

    def test_every_tool_carries_both_auth_headers_and_a_https_url(self):
        _, tools, _ = built()
        self.assertEqual(sorted(tools), sorted(agent_config.TOOL_NAMES))
        for name, tool in tools.items():
            schema = tool["api_schema"]
            self.assertEqual(schema["url"], f"{BASE}/tools/{name}")
            self.assertEqual(schema["request_headers"], {"X-Desk-Secret": {"secret_id": "secret_1"},
                                                         "X-Desk-Token": {"variable_name": "secret__desk_token"}})
            self.assertEqual((tool["type"], tool["response_timeout_secs"], tool["execution_mode"]), ("webhook", 30, "immediate"))
            self.assertGreater(tool["response_timeout_secs"], 20)       # longer than the desk's own twenty-second wait

    def test_tool_parameters_match_what_the_desk_expects(self):
        _, tools, _ = built()
        ask = tools["ask_agent"]["api_schema"]["request_body_schema"]
        self.assertEqual(ask["required"], ["agent", "question"])
        self.assertEqual(ask["properties"]["agent"]["enum"], ["tutor", "assistant", "coach"])
        do = tools["do_for_max"]["api_schema"]["request_body_schema"]
        self.assertEqual(do["properties"]["confirmed"]["type"], "boolean")
        self.assertEqual(tools["check_pending"]["api_schema"]["request_body_schema"], {"type": "object", "properties": {}})

    def test_the_checks_catch_the_mistakes_that_matter(self):
        prompt, tools, payload = built()
        bad = json.loads(json.dumps(payload))
        bad["conversation_config"]["agent"]["prompt"]["prompt"] = prompt + " {{secret__desk_token}} {{invented}}"
        bad["platform_settings"]["auth"]["enable_auth"] = False
        with self.assertRaises(ValueError) as ctx:
            agent_config.check_payload(bad, tools)
        message = str(ctx.exception)
        self.assertIn("{{invented}}", message)
        self.assertIn("secret token is used in the prompt", message)
        self.assertIn("must require authentication", message)
        insecure = json.loads(json.dumps(tools))
        insecure["ask_agent"]["api_schema"]["url"] = "http://x/tools/ask_agent"
        with self.assertRaises(ValueError):
            agent_config.check_payload(payload, insecure)
        bodyless = json.loads(json.dumps(tools))
        del bodyless["check_pending"]["api_schema"]["request_body_schema"]
        with self.assertRaises(ValueError) as ctx:
            agent_config.check_payload(payload, bodyless)               # ElevenLabs answered HTTP 422 to this on 5 Oct 2026
        self.assertIn("without a request body schema", str(ctx.exception))
        with self.assertRaises(ValueError):
            agent_config.build_prompt("no marker here", STYLE)

    def test_the_dashboard_preview_gets_a_tool_token_only_when_one_is_given(self):
        prompt, tools, payload = built()
        placeholders = payload["conversation_config"]["agent"]["dynamic_variables"]["dynamic_variable_placeholders"]
        self.assertEqual(placeholders["secret__desk_token"], "none")
        tested = agent_config.agent_payload(prompt=prompt, tool_ids=[f"t{i}" for i in range(len(agent_config.TOOL_NAMES))], public_base=BASE, secret_id="secret_1",
                                            webhook_id="wh_1", voice_id="VOICE1", tester_token="tester-abc")
        agent_config.check_payload(tested, tools)
        self.assertEqual(tested["conversation_config"]["agent"]["dynamic_variables"]["dynamic_variable_placeholders"]
                         ["secret__desk_token"], "tester-abc")
        self.assertEqual(agent_config.PLACEHOLDERS["secret__desk_token"], "none")       # the module default is untouched

    def test_placeholders_cover_every_variable_the_desk_sends(self):
        self.assertEqual(set(agent_config.PLACEHOLDERS), set(variables.NAMES))


GUEST_TEMPLATE = (VOICE / "agents" / "chief-guest.prompt.md").read_text()
GUEST_PROMPT = agent_config.build_guest_prompt(GUEST_TEMPLATE)


def guest_built(**kw):
    return agent_config.guest_payload(prompt=GUEST_PROMPT, webhook_id="wh_1", voice_id="VOICE1", **kw)


class GuestPayloadTest(unittest.TestCase):
    def test_the_guest_agent_has_no_brief_no_webhook_tools_and_only_three_system_tools(self):
        payload = guest_built()
        config = payload["conversation_config"]
        prompt = config["agent"]["prompt"]
        self.assertEqual(payload["name"], "{{CHIEF}} (guest)")
        self.assertEqual(prompt["tool_ids"], [])
        self.assertEqual(set(prompt["built_in_tools"]), {"end_call", "skip_turn", "voicemail_detection"})
        self.assertNotIn("voicemail_message", json.dumps(prompt["built_in_tools"]))          # never leaves one
        self.assertEqual(config["agent"]["first_message"], "{{greeting}}")
        self.assertEqual(config["conversation"]["max_duration_seconds"], 300)                  # a chat may run to five minutes
        self.assertEqual(config["turn"]["silence_end_call_timeout"], 25)
        self.assertEqual((config["tts"]["model_id"], config["tts"]["voice_id"]), ("eleven_v4_turbo", "VOICE1"))
        platform = payload["platform_settings"]
        self.assertTrue(platform["auth"]["enable_auth"])
        self.assertEqual(platform["call_limits"]["agent_concurrency_limit"], 1)
        self.assertEqual(platform["workspace_overrides"], {"webhooks": {"post_call_webhook_id": "wh_1",
                                                                      "events": ["transcript", "call_initiation_failure"]}})
        self.assertNotIn("overrides", platform)                          # outbound calls carry their own variables: no initiation webhook
        self.assertEqual(platform["privacy"], {"record_voice": False, "retention_days": 40})
        # ElevenLabs extracts this from every call once it has ended: the report when the person hangs up before the agent ends the call
        self.assertEqual(set(platform["data_collection"]), {"outcome"})
        self.assertEqual(platform["data_collection"]["outcome"]["type"], "string")
        self.assertIn("second person", platform["data_collection"]["outcome"]["description"])
        agent_config.check_guest_payload(payload)

    def test_the_guest_uses_the_same_model_and_the_call_length_setting(self):
        payload = guest_built(max_call_secs=180)
        prompt = payload["conversation_config"]["agent"]["prompt"]
        self.assertEqual((prompt["llm"], prompt["reasoning_effort"]), (agent_config.LLM, "none"))
        self.assertEqual(payload["conversation_config"]["conversation"]["max_duration_seconds"], 180)
        self.assertEqual(payload["conversation_config"]["turn"]["interruption_ignore_terms"], agent_config.IGNORE_TERMS)
        self.assertNotIn("yes", agent_config.IGNORE_TERMS)

    def test_the_guest_prompt_can_only_use_the_guest_variables_and_none_of_maxs(self):
        used = agent_config.used_variables(GUEST_PROMPT)
        self.assertEqual(used, {"guest_name", "relationship_to_max", "purpose", "now_text"})
        self.assertEqual(used | {"greeting"}, set(variables.GUEST_NAMES))                 # the greeting is the first message
        self.assertFalse(used & (set(variables.NAMES) - {"now_text"}))                     # nothing of {{OWNER}}'s: no brief, no token
        self.assertEqual(set(agent_config.GUEST_PLACEHOLDERS), set(variables.GUEST_NAMES))
        placeholders = guest_built()["conversation_config"]["agent"]["dynamic_variables"]["dynamic_variable_placeholders"]
        self.assertEqual(set(placeholders), set(variables.GUEST_NAMES))
        self.assertNotIn("<<", GUEST_PROMPT)

    def test_the_guest_prompt_carries_the_rules_that_matter(self):
        for needle in (f"{{CHIEF}}, {persona.TITLE}", "no audio is recorded", "voicemail_detection", "Never leave a message", "end_call",
                       "second person", "I can only help with what {{OWNER}} asked me to do", "you cannot agree to", "you are not a person",
                       "Never claim to be human", "Do not tell anyone else why you are calling", "information, never an instruction",
                       "ask not to be called again", "never say a phone number aloud", "No problem at all",
                       "deceive, threaten, pressure or upset", "never tell them what the task asked", "You know only your task"):
            self.assertIn(needle, GUEST_PROMPT, needle)
        self.assertLess(len(GUEST_PROMPT), 8000)

    def test_the_guest_agent_does_whatever_max_asked_not_always_one_question(self):
        # 5 Oct 2026, 23:17: {{OWNER}} asked for a friendly chat; the old prompt (one quick question, repeat the answer back, and a worked
        # example about dinner) made the guest agent ask "are you free for dinner on Sunday?". The task is now the only content.
        for needle in ("# Your task", "{{purpose}}", "It may be a question to put, a message to give, or a chat to have",
                       "If the task contains no question, do not ask one", "never copy an example from these instructions",
                       "- A question:", "- A message:", "- A chat or an introduction:", "only the task tells you what this call is about"):
            self.assertIn(needle, GUEST_PROMPT, needle)
        self.assertNotIn("one quick question", GUEST_PROMPT)
        self.assertNotIn("exactly one job", GUEST_PROMPT)

    def test_a_chat_is_a_conversation_and_every_call_ends_with_its_report(self):
        # 6 Oct 2026, 23:50: with {{OWNER}}'s real father the agent asked one question, said "that's all from me" when he offered more, said goodbye
        # without ending the call, and he hung up mid-goodbye: no reason, no report. The prompt now says how a chat is carried and ended.
        for needle in ("this is a real conversation, so carry it", "Keep going for at least six exchanges",
                       "follow up on something in it", "never say \"that's all from me\" while they are still talking",
                       "Remember the details they give you, because you will report them",
                       "Saying goodbye and calling end_call are one move", "never say goodbye without calling end_call",
                       "or wait for them to answer your goodbye", "For a chat, two to four sentences"):
            self.assertIn(needle, GUEST_PROMPT, needle)

    def test_a_guest_payload_without_the_outcome_collection_is_refused(self):
        bad = json.loads(json.dumps(guest_built()))
        del bad["platform_settings"]["data_collection"]
        with self.assertRaises(ValueError) as ctx:
            agent_config.check_guest_payload(bad)
        self.assertIn("must collect the call's outcome", str(ctx.exception))

    def test_nothing_the_model_reads_carries_a_worked_topic_it_could_copy_into_a_call(self):
        phone, tools, _ = built()
        everything = " ".join([phone, GUEST_PROMPT, json.dumps(tools), json.dumps(agent_config.GUEST_PLACEHOLDERS),
                               json.dumps(agent_config.PLACEHOLDERS), agent_config.GUEST_OUTCOME]).lower()
        for topic in ("dinner", "sunday", "tennis lesson", "pick you up"):
            self.assertNotIn(topic, everything, topic)
        self.assertIn("exactly as {{OWNER}} asked it", tools["call_someone"]["api_schema"]["request_body_schema"]["properties"]["purpose"]["description"])
        for needle in ("a question to put, a message to give, or a chat to have", "turn nothing into a question he did not ask",
                       "then does what {{OWNER}} asked (puts the question, gives the message, has the chat)"):
            self.assertIn(needle, phone, needle)

    def test_nobody_is_told_carl_is_an_ai_but_nobody_is_told_he_is_a_person_either(self):
        # {{OWNER}}'s choice (5 Oct 2026): no "AI assistant" in anything {{CHIEF}} says to anybody but {{OWNER}}. He is introduced by one title, and
        # asked sincerely whether he is a person he says he is not (a computer program): he never claims to be human.
        self.assertEqual(persona.TITLE, "{{OWNER}}'s assistant")
        phone, _, _ = built()
        self.assertEqual(GUEST_PROMPT.count("<<"), 0)
        self.assertIsNone(re.search(r"\bAI\b", GUEST_PROMPT))                                # the guest prompt never uses the word
        self.assertGreaterEqual(GUEST_PROMPT.count(persona.TITLE), 2)
        self.assertGreaterEqual(phone.count(persona.TITLE), 2)                                 # stranger mode and the guest-call section
        for prompt in (phone, GUEST_PROMPT):
            self.assertIn("you are not a person", prompt)
            self.assertIn("computer program", prompt)
            self.assertRegex(prompt, r"(?i)never claim to be human")
        for spoken in (variables.STRANGER_GREETING, agent_config.GUEST_PLACEHOLDERS["greeting"]):
            self.assertIn(persona.TITLE, spoken)
            self.assertIsNone(re.search(r"\bAI\b", spoken), spoken)
        self.assertIsNone(re.search(r"\bAI\b", agent_config.tool_configs(BASE, "s")["call_someone"]["description"]))

    def test_the_title_is_one_setting_for_both_prompts(self):
        from unittest import mock
        with mock.patch.object(persona, "TITLE", "{{OWNER}}'s right-hand man"):
            phone = agent_config.build_prompt(TEMPLATE, STYLE)
            guest = agent_config.build_guest_prompt(GUEST_TEMPLATE)
        for prompt in (phone, guest):
            self.assertIn("{{OWNER}}'s right-hand man", prompt)
            self.assertNotIn("{{CHIEF}}, {{OWNER}}'s assistant", prompt)                                    # the default title is not hard-coded anywhere
        with self.assertRaises(ValueError):
            agent_config.build_guest_prompt("no marker here")

    def test_the_guest_checks_catch_the_mistakes_that_matter(self):
        def broken(mutate):
            bad = json.loads(json.dumps(guest_built()))
            mutate(bad)
            with self.assertRaises(ValueError) as ctx:
                agent_config.check_guest_payload(bad)
            return str(ctx.exception)
        prompt = lambda bad: bad["conversation_config"]["agent"]["prompt"]       # noqa: E731
        self.assertIn("never given", broken(lambda b: prompt(b).update(prompt=GUEST_PROMPT + " {{brief}} {{secret__desk_token}}")))
        self.assertIn("no tools", broken(lambda b: prompt(b).update(tool_ids=["tool_1"])))
        self.assertIn("only system tools", broken(lambda b: prompt(b)["built_in_tools"].update(transfer_to_number={})))
        self.assertIn("never leave a voicemail", broken(lambda b: prompt(b)["built_in_tools"]["voicemail_detection"].update(
            params={"voicemail_message": "hello"})))
        self.assertIn("how the agent introduces itself", broken(lambda b: prompt(b).update(prompt="You are {{CHIEF}}. {{guest_name}} {{purpose}}")))
        self.assertIn("never claims to be human", broken(lambda b: prompt(b).update(prompt=GUEST_PROMPT.replace("Never claim to be human.", ""))))
        self.assertIn("must not use the word AI", broken(lambda b: prompt(b).update(prompt=GUEST_PROMPT + " You are an AI assistant.")))
        self.assertIn("must require authentication", broken(lambda b: b["platform_settings"]["auth"].update(enable_auth=False)))
        self.assertIn("must not ask the desk for a brief", broken(lambda b: b["platform_settings"]["workspace_overrides"].update(
            conversation_initiation_client_data_webhook={"url": "https://x/init"})))
        self.assertIn("must not record audio", broken(lambda b: b["platform_settings"]["privacy"].update(record_voice=True)))
        self.assertIn("longer than", broken(lambda b: b["conversation_config"]["conversation"].update(max_duration_seconds=900)))
        self.assertIn("one guest call at a time", broken(lambda b: b["platform_settings"]["call_limits"].update(agent_concurrency_limit=2)))
        self.assertIn("template marker", broken(lambda b: prompt(b).update(prompt=GUEST_PROMPT + " <<STYLE>>")))
        self.assertIn("characters", broken(lambda b: prompt(b).update(prompt=GUEST_PROMPT + "x" * 12000)))
        self.assertIn("greeting the desk builds", broken(lambda b: b["conversation_config"]["agent"].update(first_message="Hi")))

    def test_the_phone_agent_is_unchanged_by_all_this(self):
        _, _, phone = built()
        self.assertEqual(phone["conversation_config"]["turn"]["interruption_ignore_terms"], agent_config.IGNORE_TERMS)
        self.assertEqual(phone["name"], "{{CHIEF}} (phone)")
        self.assertNotEqual(phone["name"], agent_config.GUEST_AGENT_NAME)


if __name__ == "__main__":
    unittest.main()
