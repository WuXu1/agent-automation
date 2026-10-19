"""Builds the ElevenLabs definitions of {{CHIEF}}'s phone agent and his five tools, and of the guest agent that rings other people
for {{OWNER}}, from files in this repo.

Nothing here talks to ElevenLabs (push_agent.py does). Keeping the builders pure means every setting is reviewable, and the tests
can check, for example, that the prompt only uses variables the desk really supplies and that the secret token never reaches the
model, and that the guest agent has no brief and no tools.
"""
from __future__ import annotations

import re

from . import persona
from .variables import GUEST_NAMES, NAMES

AGENT_NAME = "{{CHIEF}} (phone)"
GUEST_AGENT_NAME = "{{CHIEF}} (guest)"
# Chosen 5 Oct 2026 ({{OWNER}}'s pick, the same family as the agents): the cheapest capable model ($0.020 a call minute against $0.050 for
# gemini-3.5-flash) and the fastest to start speaking: first words in 0.37 s with its thinking off, 0.70 s with it on, 0.95 s for
# gemini-3.5-flash (text-only chats, eight turns each). On 19 scripted checks of {{CHIEF}}'s rules it was within one of the best models.
# Switch with push_agent.py --llm ...
LLM = "deepseek-v41-flash"
REASONING = {"deepseek-v41-flash": "none"}          # a model that thinks before it answers is slow to start speaking
TTS_MODEL = "eleven_v4_turbo"
# a breath or an 'um' must not make {{CHIEF}} stop mid-sentence and start again ({{OWNER}}, 5 Oct 2026); 'yes' is left out so an answer gets through
IGNORE_TERMS = ["um", "uh", "er", "erm", "hmm", "mm", "mhm", "mm-hmm", "uh-huh", "ah", "oh"]
STYLE_SECTIONS = ("Address", "Shape", "Never", "Wit", "Register")
TOOL_NAMES = ("ask_agent", "do_for_max", "set_reminder", "check_pending", "call_someone")
SECRET_HEADER, TOKEN_HEADER, TOKEN_VARIABLE = "X-Desk-Secret", "X-Desk-Token", "secret__desk_token"
MAX_PROMPT_CHARS = 13000
PLACEHOLDERS = {                      # what the dashboard tester uses; real calls always supply every variable
    "greeting": "Good evening, {{sir}}.",
    "caller_mode": "max",
    "now_text": "a test, with no clock",
    "brief": "(no notes in the test window)",
    "pending_text": "Nothing pending.",
    "minutes_text": "",
    "callback_text": "",
    "contacts_text": "your father (dad)",
    TOKEN_VARIABLE: "none",
}


def style_sections(style_md: str, names: tuple = STYLE_SECTIONS) -> str:
    """The chosen '## Heading' sections of STYLE.md."""
    parts = re.split(r"(?m)^## ", style_md)
    chosen = [part.strip() for part in parts[1:] if part.split("\n", 1)[0].strip() in names]
    if len(chosen) != len(names):
        raise ValueError(f"STYLE.md is missing some of {names}")
    return "\n\n".join(f"### {part}" for part in chosen)


def build_prompt(template: str, style_md: str) -> str:
    """The phone prompt: the register guide goes in at <<STYLE>>, and {{CHIEF}}'s title for strangers at <<TITLE>>."""
    if "<<STYLE>>" not in template:
        raise ValueError("the prompt template has no <<STYLE>> marker")
    return template.replace("<<STYLE>>", style_sections(style_md)).replace("<<TITLE>>", persona.TITLE)


def build_guest_prompt(template: str) -> str:
    """The guest prompt: {{CHIEF}}'s title goes in at <<TITLE>>."""
    if "<<TITLE>>" not in template:
        raise ValueError("the guest prompt template has no <<TITLE>> marker")
    return template.replace("<<TITLE>>", persona.TITLE)


def used_variables(text: str) -> set[str]:
    return set(re.findall(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", text))


def _headers(secret_id: str) -> dict:
    return {SECRET_HEADER: {"secret_id": secret_id}, TOKEN_HEADER: {"variable_name": TOKEN_VARIABLE}}


def tool_configs(public_base: str, secret_id: str) -> dict[str, dict]:
    """The five webhook tools, keyed by name. Each carries the shared secret and the per-call token as headers."""
    common = {"type": "webhook", "response_timeout_secs": 30, "pre_tool_speech": "auto",
              "tool_call_sound": None,          # silence while a colleague works ({{OWNER}} dislikes the typing sound); an explicit null so an update clears it
              "tool_call_sound_behavior": "auto", "tool_error_handling_mode": "auto", "execution_mode": "immediate",
              "interruption_mode": "disable_during_tool"}      # a repeated "yes" while a tool ran abandoned it twice (5 Oct 2026)

    def schema(name: str, **extra) -> dict:
        return {"url": f"{public_base}/tools/{name}", "method": "POST", "request_headers": _headers(secret_id),
                "content_type": "application/json", **extra}
    return {
        "ask_agent": {**common, "pre_tool_speech": "force", "name": "ask_agent", "api_schema": schema("ask_agent", request_body_schema={
            "type": "object", "required": ["agent", "question"], "properties": {
                "agent": {"type": "string", "enum": ["tutor", "assistant", "coach"],
                          "description": "Which colleague to ask: tutor ({{TUTOR}}: study, university, Moodle), assistant ({{ASSISTANT}}: research, planning, "
                                         "admin, calendar, browsing), coach ({{COACH}}: health, fitness, sport, nutrition)."},
                "question": {"type": "string", "description": "The question or small job, in plain words, with every detail the "
                                                              "colleague needs. They cannot hear the call."},
                "notify": {"type": "string", "enum": ["when_done", "only_if_needed"],
                           "description": "Normally leave this out. Use only_if_needed when {{OWNER}} says to ring him only if the "
                                          "colleague needs him."},
                "patience": {"type": "string", "enum": ["quick", "long"],
                             "description": "Leave this out for a question answered in seconds (what is on, what is due). Use "
                                            "long for a job that takes minutes: drafting, planning, researching, writing, "
                                            "booking, anything {{OWNER}} wants a call back about. A long job answers at once with "
                                            "pending and you ring {{OWNER}} back with the result."}}}),
                      "description": "Ask one of your colleagues a question, or hand them a small job, and wait for the answer. "
                                     "Waits up to about twenty seconds (a long job answers at once). Returns status done with the "
                                     "answer, or pending if the colleague is still working (then you will ring {{OWNER}} back with the "
                                     "result), or failed."},
        "do_for_max": {**common, "pre_tool_speech": "force", "name": "do_for_max", "api_schema": schema("do_for_max", request_body_schema={
            "type": "object", "required": ["request"], "properties": {
                "request": {"type": "string", "description": "What {{OWNER}} wants done, in plain words with every detail."},
                "confirmed": {"type": "boolean", "description": "True only after {{OWNER}} has clearly said yes to the exact action "
                                                                "you read back to him. Otherwise false."},
                "notify": {"type": "string", "enum": ["when_done", "only_if_needed"],
                           "description": "Normally leave this out. Use only_if_needed when {{OWNER}} says to ring him only if "
                                          "something is needed."},
                "patience": {"type": "string", "enum": ["quick", "long"],
                             "description": "Leave this out for a question answered in seconds (what is on, what is due). Use "
                                            "long for a job that takes minutes: drafting, planning, researching, writing, "
                                            "booking, anything {{OWNER}} wants a call back about. A long job answers at once with "
                                            "pending and you ring {{OWNER}} back with the result."}}}),
                       "description": "Do something else {{OWNER}} could ask you to do on Telegram that changes something (a "
                                      "calendar change, a note, a task, a draft; not a reminder, use set_reminder). You, {{CHIEF}}, "
                                      "carry it out. Read the action back and get a clear yes first, then call this with "
                                      "confirmed true. Waits up to about twenty seconds (a long job answers at once)."},
        "set_reminder": {**common, "pre_tool_speech": "off", "name": "set_reminder", "api_schema": schema("set_reminder", request_body_schema={
            "type": "object", "required": ["when", "text"], "properties": {
                "when": {"type": "string", "description": "When it should go off: a delay such as 10m, 2h or 1d, or a UK date "
                                                          "and time such as 2026-10-05 18:30."},
                "text": {"type": "string", "description": "What to remind {{OWNER}} of, in a few plain words, such as: check the oven."}}}),
                         "description": "Set a reminder for {{OWNER}} that reaches him on Telegram at the time he wants. Read it back "
                                        "and get a clear yes first. It takes about a second, so no announcement is needed."},
        "call_someone": {**common, "pre_tool_speech": "off", "name": "call_someone", "api_schema": schema("call_someone", request_body_schema={
            "type": "object", "required": ["name", "purpose"], "properties": {
                "name": {"type": "string", "description": "Who to ring, as {{OWNER}} said it (for example dad). Must be one of the people "
                                                          "on your list of people you can ring."},
                "purpose": {"type": "string", "description": "What the call is for, in plain words and exactly as {{OWNER}} asked it: a question "
                                                             "to put, a message to give, or a chat to have (for example, to introduce "
                                                             "yourself and ask how they are). Include every detail the other assistant "
                                                             "needs, and add nothing {{OWNER}} did not ask."},
                "confirmed": {"type": "boolean", "description": "False the first time, to be told what to read back to {{OWNER}}. True "
                                                                "only after {{OWNER}} has clearly said yes to the exact call you read "
                                                                "back to him."}}}),
                         "description": "Ring one of the people on your list for {{OWNER}}. A separate assistant rings them, says it is "
                                        f"{{CHIEF}}, {persona.TITLE}, does what {{OWNER}} asked (a question, a message or a chat) and tells you nothing back until the call "
                                        "ends. Call it first with confirmed false: it returns what to read back. Read that back to "
                                        "{{OWNER}}, get a clear yes, then call it again with confirmed true. It places the call at once "
                                        "and does not wait for the answer: you ring {{OWNER}} back with what they say."},
        "check_pending": {**common, "name": "check_pending",
                          # ElevenLabs refuses a POST tool without a body schema, even one that takes nothing
                          "api_schema": schema("check_pending", request_body_schema={"type": "object", "properties": {}}),
                          "description": "Check what your colleagues have finished since you asked. Returns the finished answers "
                                         "and what is still being worked on. Use it at natural pauses, when {{OWNER}} asks for news, "
                                         "and before ending a call if anything was left pending."},
    }


def _system(name: str, description: str) -> dict:
    return {"type": "system", "name": name, "description": description, "params": {"system_tool_type": name}}


def agent_payload(*, prompt: str, tool_ids: list[str], public_base: str, secret_id: str, webhook_id: str, voice_id: str,
                  llm: str = LLM, name: str = AGENT_NAME, tester_token: str = "") -> dict:
    """The body for creating (or updating) the phone agent. The dashboard preview never gets a real call token, so for a
    test session `tester_token` stands in for it; real calls always bring their own."""
    placeholders = {**PLACEHOLDERS, **({TOKEN_VARIABLE: tester_token} if tester_token else {})}
    return {
        "name": name,
        "conversation_config": {
            "agent": {
                "first_message": "{{greeting}}",
                "language": "en",
                "dynamic_variables": {"dynamic_variable_placeholders": placeholders},
                "max_conversation_duration_message": "{{SIR}}, I must end the call here. Ring me again whenever you like.",
                "prompt": {
                    "prompt": prompt, "llm": llm, "temperature": 0.4, "max_tokens": 400, "tool_ids": list(tool_ids),
                    **({"reasoning_effort": REASONING[llm]} if llm in REASONING else {}),
                    "built_in_tools": {
                        "end_call": _system("end_call", "End the call after a short sign-off, when {{OWNER}} says goodbye or has "
                                                        "clearly finished."),
                        "skip_turn": _system("skip_turn", "Stay silent and keep listening when {{OWNER}} says he needs a moment, "
                                                          "or asks you to hold on."),
                        "voicemail_detection": _system("voicemail_detection", "Use when a voicemail or answering machine "
                                                                              "answers. Leave no message."),
                    },
                    "timezone": "Europe/London", "ignore_default_personality": True,
                    "backup_llm_config": {"preference": "default"}, "cascade_timeout_seconds": 4.0,
                },
            },
            "tts": {"model_id": TTS_MODEL, "voice_id": voice_id},
            "asr": {"keywords": ["{{CHIEF}}", "{{ASSISTANT}}", "{{TUTOR}}", "{{COACH}}", "Moodle", "Hermes", "Tailscale"]},
            "turn": {"turn_timeout": 15, "silence_end_call_timeout": 40, "turn_eagerness": "normal", "turn_model": "turn_v3",
                     "interruption_ignore_term_languages": ["en"], "merge_with_default_ignore_terms": True,
                     "interruption_ignore_terms": list(IGNORE_TERMS),
                     # no stall line: ElevenLabs speaks it just before a slow tool's answer, not during the wait (5 Oct 2026)
                     "soft_timeout_config": {"timeout_seconds": -1}},
            "conversation": {"max_duration_seconds": 900},
        },
        "platform_settings": {
            "auth": {"enable_auth": True},
            "overrides": {"enable_conversation_initiation_client_data_from_webhook": True},
            "workspace_overrides": {
                "conversation_initiation_client_data_webhook": {"url": f"{public_base}/init",
                                                                "request_headers": {SECRET_HEADER: {"secret_id": secret_id}}},
                "webhooks": {"post_call_webhook_id": webhook_id, "events": ["transcript", "call_initiation_failure"]},
            },
            "call_limits": {"agent_concurrency_limit": 2, "daily_limit": 30, "bursting_enabled": False},
            "privacy": {"record_voice": False, "retention_days": 40},
        },
    }


def check_payload(payload: dict, tools: dict[str, dict]) -> None:
    """Raises ValueError listing everything wrong. Run before anything is pushed."""
    problems = []
    config = payload["conversation_config"]
    prompt = config["agent"]["prompt"]["prompt"]
    first = config["agent"]["first_message"]
    used = used_variables(prompt) | used_variables(first)
    for name in sorted(used - set(NAMES)):
        problems.append(f"the prompt uses {{{{{name}}}}}, which the desk never supplies")
    for name in sorted(set(NAMES) - set(PLACEHOLDERS)):
        problems.append(f"no placeholder for {name}")
    if TOKEN_VARIABLE in used:
        problems.append("the secret token is used in the prompt, where the model could read it")
    if "<<" in prompt or ">>" in prompt:
        problems.append("a template marker is left in the prompt")
    if persona.TITLE not in prompt:
        problems.append(f"the prompt never says how {{CHIEF}} introduces himself to a stranger ({persona.TITLE})")
    if len(prompt) > MAX_PROMPT_CHARS:
        problems.append(f"the prompt is {len(prompt)} characters (limit {MAX_PROMPT_CHARS})")
    if sorted(tools) != sorted(TOOL_NAMES):
        problems.append(f"tools must be {TOOL_NAMES}")
    for name, tool in tools.items():
        url = tool["api_schema"]["url"]
        if not url.startswith("https://"):
            problems.append(f"{name} does not use https")
        headers = tool["api_schema"]["request_headers"]
        if TOKEN_HEADER not in headers or SECRET_HEADER not in headers:
            problems.append(f"{name} is missing its auth headers")
        if tool["api_schema"].get("method") == "POST" and "request_body_schema" not in tool["api_schema"]:
            problems.append(f"{name} is a POST tool without a request body schema, which ElevenLabs refuses")
    if len(config["agent"]["prompt"]["tool_ids"]) != len(TOOL_NAMES):
        problems.append("the agent must reference every tool")
    if not payload["platform_settings"]["auth"]["enable_auth"]:
        problems.append("the agent must require authentication (otherwise anyone with its id can start a conversation)")
    if problems:
        raise ValueError("; ".join(problems))


# --- the guest agent: rings the people in the contact book for {{OWNER}} -----------------------------------------------------------
GUEST_PLACEHOLDERS = {                # what the dashboard tester uses; real calls always supply every variable
    "greeting": f"Hello, is that Mr Smith? It's {{CHIEF}}, {persona.TITLE}.",
    "guest_name": "Mr Smith",
    "relationship_to_max": "{{OWNER}}'s father",
    "purpose": "Say hello, introduce yourself and ask how he is doing.",
    "now_text": "a test, with no clock",
}
GUEST_BUILT_IN = ("end_call", "skip_turn", "voicemail_detection")
# What ElevenLabs extracts from every guest call once it has ended, whether or not the agent got to call end_call (a person who hangs up
# during the goodbye leaves no reason): the backup for the spoken report. Second person, so that it can be read to {{OWNER}} as it stands.
GUEST_OUTCOME = ("In two to four plain sentences addressed to {{OWNER}} in the second person (\"Your father says ...\"), say what the person on the "
                 "call said: how they are, what they answered or asked, what they mentioned (their news, plans, feelings) and anything they "
                 "want passed on to {{OWNER}}, in their own terms. Only what was said: no opinions, no guesses, no phone numbers or links. If they "
                 "said nothing useful, say so in one sentence.")
GUEST_MAX_CALL_SECS = 300             # no guest call may be allowed longer than this, whatever the setting says


def guest_payload(*, prompt: str, webhook_id: str, voice_id: str, llm: str = LLM, name: str = GUEST_AGENT_NAME,
                  max_call_secs: int = 300) -> dict:
    """The body for creating (or updating) the guest agent: no brief, no webhook tools, no initiation webhook. It can only end the
    call (and that call's `reason` is the report {{OWNER}} hears), keep quiet while somebody fetches something, and detect voicemail."""
    return {
        "name": name,
        "conversation_config": {
            "agent": {
                "first_message": "{{greeting}}",
                "language": "en",
                "dynamic_variables": {"dynamic_variable_placeholders": dict(GUEST_PLACEHOLDERS)},
                "max_conversation_duration_message": "I'm sorry, I have to end the call there. {{OWNER}} will be in touch. Goodbye.",
                "prompt": {
                    "prompt": prompt, "llm": llm, "temperature": 0.4, "max_tokens": 300, "tool_ids": [],
                    **({"reasoning_effort": REASONING[llm]} if llm in REASONING else {}),
                    "built_in_tools": {
                        "end_call": _system("end_call", "End the call after a short goodbye, once you have the answer or the person "
                                                        "cannot help. The reason is the report {{OWNER}} will hear: one plain sentence to "
                                                        "{{OWNER}}, in the second person, saying what the person answered."),
                        "skip_turn": _system("skip_turn", "Stay silent and keep listening when the person asks you to hold on or "
                                                          "needs a moment."),
                        "voicemail_detection": _system("voicemail_detection", "Use when a voicemail or answering machine answers. "
                                                                              "Say nothing and leave no message."),
                    },
                    "timezone": "Europe/London", "ignore_default_personality": True,
                    "backup_llm_config": {"preference": "default"}, "cascade_timeout_seconds": 4.0,
                },
            },
            "tts": {"model_id": TTS_MODEL, "voice_id": voice_id},
            "asr": {"keywords": ["{{CHIEF}}", "{{OWNER}}"]},
            "turn": {"turn_timeout": 15, "silence_end_call_timeout": 25, "turn_eagerness": "normal", "turn_model": "turn_v3",
                     "interruption_ignore_term_languages": ["en"], "merge_with_default_ignore_terms": True,
                     "interruption_ignore_terms": list(IGNORE_TERMS), "soft_timeout_config": {"timeout_seconds": -1}},
            "conversation": {"max_duration_seconds": int(max_call_secs)},
        },
        "platform_settings": {
            "auth": {"enable_auth": True},
            "workspace_overrides": {"webhooks": {"post_call_webhook_id": webhook_id,
                                                 "events": ["transcript", "call_initiation_failure"]}},
            "call_limits": {"agent_concurrency_limit": 1, "daily_limit": 6, "bursting_enabled": False},
            "privacy": {"record_voice": False, "retention_days": 40},
            "data_collection": {"outcome": {"type": "string", "description": GUEST_OUTCOME}},
        },
    }


def check_guest_payload(payload: dict) -> None:
    """Raises ValueError listing everything wrong. The guest agent talks to strangers, so these rules are strict."""
    problems = []
    config = payload["conversation_config"]
    prompt_config = config["agent"]["prompt"]
    prompt, first = prompt_config["prompt"], config["agent"]["first_message"]
    used = used_variables(prompt) | used_variables(first)
    for name in sorted(used - set(GUEST_NAMES)):
        problems.append(f"the prompt uses {{{{{name}}}}}, which the guest agent is never given")
    if set(config["agent"]["dynamic_variables"]["dynamic_variable_placeholders"]) != set(GUEST_NAMES):
        problems.append("the placeholders must be exactly the guest variables")
    if prompt_config["tool_ids"]:
        problems.append("the guest agent must have no tools")
    if set(prompt_config["built_in_tools"]) != set(GUEST_BUILT_IN):
        problems.append(f"the guest agent's only system tools are {GUEST_BUILT_IN}")
    if "voicemail_message" in str(prompt_config["built_in_tools"]):
        problems.append("the guest agent must never leave a voicemail")
    if persona.TITLE not in prompt:
        problems.append(f"the prompt must say how the agent introduces itself ({persona.TITLE})")
    if "never claim to be human" not in prompt.lower():
        problems.append("the prompt must say the agent never claims to be human (it answers truthfully if asked)")
    if re.search(r"\bAI\b", prompt):
        problems.append("the prompt must not use the word AI ({{OWNER}} does not want it said on a call)")
    if "<<" in prompt or ">>" in prompt:
        problems.append("a template marker is left in the prompt")
    if len(prompt) > MAX_PROMPT_CHARS:
        problems.append(f"the prompt is {len(prompt)} characters (limit {MAX_PROMPT_CHARS})")
    if first != "{{greeting}}":
        problems.append("the first message must be the greeting the desk builds")
    if config["conversation"]["max_duration_seconds"] > GUEST_MAX_CALL_SECS:
        problems.append(f"a guest call may not be allowed longer than {GUEST_MAX_CALL_SECS} seconds")
    platform = payload["platform_settings"]
    if not platform["auth"]["enable_auth"]:
        problems.append("the agent must require authentication (otherwise anyone with its id can start a conversation)")
    if "conversation_initiation_client_data_webhook" in platform.get("workspace_overrides", {}):
        problems.append("the guest agent must not ask the desk for a brief")
    if platform["privacy"]["record_voice"]:
        problems.append("the guest agent must not record audio")
    if platform["call_limits"]["agent_concurrency_limit"] != 1:
        problems.append("only one guest call at a time")
    if set(platform.get("data_collection") or {}) != {"outcome"}:
        problems.append("the guest agent must collect the call's outcome (the report when nobody ends the call)")
    if problems:
        raise ValueError("; ".join(problems))
