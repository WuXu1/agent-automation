"""Operator commands, run on the server as the hermes user:

  python3 -m desk.admin init --public-base URL  first-time setup of the state folder: a private secrets file with a fresh tool
                                                secret (never shown) and a config.json in dry mode
  python3 -m desk.admin set-owner-number
                                                store {{OWNER}}'s number (typed silently)
  python3 -m desk.admin status                  what the running desk is doing (its own GET /status; the database alone if
                                                the service does not answer)
  python3 -m desk.admin dial-mode live|dry      whether call-backs are really placed (restart the desk afterwards)
  python3 -m desk.admin notify-mode live|dry    whether Telegram messages are really sent (restart afterwards)
  python3 -m desk.admin self-check [--url URL]  rehearse the desk's public surface (health, auth, tokens, signatures)
  python3 -m desk.admin ask AGENT QUESTION...   one real question to tutor|assistant|coach through the desk's own tool code
                                                (no phone, no ElevenLabs): proves the Hermes keys and the run/ticket path
  python3 -m desk.admin ring NAME "WHAT TO SAY" [--yes]
                                                what {{CHIEF}} runs when {{OWNER}} asks, in the Telegram chat, for somebody to be rung: first without
                                                --yes (the desk answers with the words to read back), then with --yes after {{OWNER}}'s yes
  python3 -m desk.admin notify-test [--voice]   one message to {{OWNER}} on Telegram (and one voice note in {{CHIEF}}'s voice) to prove
                                                both paths work; refuses while notify-mode is dry
  python3 -m desk.admin test-call               announce on Telegram, wait, then ring {{OWNER}} ONCE with the live agent (needs
                                                DESK_ALLOW_TEST_DIAL=1 in the environment, as a deliberate act, and Telegram
                                                messages switched on: it refuses to ring if the announcement cannot go out)
  python3 -m desk.admin contact add KEY --display "your father" --address-as "Mr Smith" [--alias dad ...] [--hours 09:00-21:00]
                                                add a person {{CHIEF}} may ring. The number is typed twice at a hidden prompt: it is
                                                never taken from the command line and never shown (at most its last two digits)
  python3 -m desk.admin contact add-rehearsal [--hours ...]
                                                the test contact "Test Dad": {{OWNER}}'s own number, so {{OWNER}} can play the person
  python3 -m desk.admin contact edit KEY [--display ...] [--address-as ...] [--alias ... | --no-aliases] [--hours ...]
                                                correct names or hours; the number is never asked for, shown or changed
  python3 -m desk.admin contact list            who may be rung (numbers masked)
  python3 -m desk.admin contact remove KEY
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

from . import config, contacts, selfcheck, server, util

ANNOUNCEMENT = ("{{SIR}}, a test call is coming in about {secs} seconds: it is the new phone line being tried, one call, "
                "no voicemail will be left.")


def test_call(app, wait_secs: float = 30.0, sleep=time.sleep) -> dict:
    """One test call to {{OWNER}}. Without the operator switch (DESK_ALLOW_TEST_DIAL=1, or dial-mode live) nothing rings: the dial is
    only recorded, and nothing is announced. With it, the call goes out only after the announcement really reached Telegram."""
    if app.cfg.dial_mode == "live" or app.dialer.env.get("DESK_ALLOW_TEST_DIAL") == "1":
        if app.cfg.notify_mode != "live":
            raise SystemExit("refused: Telegram messages are off (notify-mode dry), so {{OWNER}} would not be warned about the call")
        if not app.notifier.text(ANNOUNCEMENT.format(secs=int(wait_secs)), "test-call"):
            raise SystemExit("refused: the announcement could not be sent to Telegram, so no call was placed")
        sleep(wait_secs)
    call = app.calls.prepare_outbound("test")
    values = app.variables.build("test", call["token"])
    return app.dialer.place("test", app.cfg.max_number, values, call, announced_test=True)


def live_status(cfg, base: str | None = None) -> dict | None:
    """The running service's own /status (so the brief's ages are the real ones), or None when it does not answer."""
    code, data = selfcheck._call(base or f"http://127.0.0.1:{cfg.port}", "GET", "/status", headers={"x-desk-secret": cfg.tool_secret})
    try:
        return json.loads(data) if code == 200 else None
    except ValueError:
        return None


def ring(cfg, name: str, purpose: str, yes: bool) -> tuple[int, str]:
    """{{CHIEF}}'s way to ring somebody for {{OWNER}} from the Telegram chat: the running desk's own guest-call tool, with the same gates as on a
    phone call (the contact book, a read-back first and {{OWNER}}'s yes after it, the limits and the hours). Prints one sentence for {{CHIEF}} and
    never anything secret."""
    code, data = selfcheck._call(f"http://127.0.0.1:{cfg.port}", "POST", "/chat/call_someone",
                                 headers={"x-desk-secret": cfg.tool_secret, "content-type": "application/json"},
                                 body=json.dumps({"name": name, "purpose": purpose, "confirmed": yes}).encode())
    try:
        out = json.loads(data)
    except (TypeError, ValueError):
        return 1, "The phone desk did not answer, so nobody was rung."
    if code != 200 or not isinstance(out, dict):
        return 1, "The phone desk refused that, so nobody was rung."
    status = out.get("status")
    line = out.get("message") or out.get("answer") or ""
    if status == "calling":
        line = f"{out.get('contact', 'They')} is being rung now. The result will come to this chat when the call ends (a voice note, then what was said)."
    line = line.replace("only then call this again with confirmed true", "only then run this command again with --yes and the same words")
    return (0 if status in ("needs_yes", "calling", "done") else 1), f"{(status or 'failed').upper()}: {line}".strip()


def ask(app, agent: str, question: str) -> dict:
    """One real question to an agent, through the same code a phone call's tool uses. Nothing rings."""
    call = app.calls.prepare_outbound("test")
    status, payload = app.tools.ask_agent(call, {"agent": agent, "question": question})
    app.calls.discard(call["id"])
    return {"http": status, **payload}


def notify_test(app, voice: bool = False) -> bool:
    """One message to {{OWNER}} on Telegram, and with `voice` one voice note too: the two paths the desk's fallbacks depend on."""
    if app.cfg.notify_mode != "live":
        raise SystemExit("refused: Telegram messages are off (notify-mode dry)")
    text = "{{SIR}}, the phone desk is switched on and can reach you here."
    sent = app.notifier.text(text, "notify-test")
    return (app.notifier.voice(text, "notify-test") and sent) if voice else sent


def init_state(state_dir: str, public_base: str, port: int = 8800) -> dict:
    """Idempotent first-time setup. Existing settings and secrets are never replaced."""
    folder = Path(state_dir)
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    secrets_file = folder / "secrets.env"
    made_secret = not config.read_env_file(secrets_file).get("DESK_TOOL_SECRET")
    if made_secret:
        config.set_env_value(secrets_file, "DESK_TOOL_SECRET", secrets.token_urlsafe(32))
    try:
        current = json.loads((folder / "config.json").read_text())
    except (OSError, ValueError):
        current = {}
    wanted = {"public_base": public_base, "port": port, "dial_mode": "dry", "notify_mode": "dry"}
    config.update_config_json(state_dir, {k: v for k, v in wanted.items() if k not in current})
    return {"created_secret": made_secret}


def contact_command(args, cfg) -> int:
    """The contact book. Numbers are typed at a hidden prompt and shown at most as their last two digits; every refusal is a
    sentence that never contains one."""
    book = contacts.ContactBook(cfg.contacts_path, cfg.max_number)
    try:
        if args.action == "add":
            number = getpass.getpass(f"Number for {args.key} (typed silently): ")
            if getpass.getpass("Type it again to confirm: ") != number:
                raise SystemExit("refused: the two entries did not match, nothing was saved")
            contact = book.add(args.key, args.display, args.address_as, number, tuple(args.alias), args.hours)
            print(f"contact saved: {contact.key} (number ending {book.masked(contact)})")
        elif args.action == "add-rehearsal":
            contact = book.add_rehearsal(args.hours)
            print(f"contact saved: {contact.key} ({book.masked(contact)}, so {{OWNER}} can play the person)")
        elif args.action == "edit":
            if args.no_aliases and args.alias:
                raise SystemExit("refused: use either --alias or --no-aliases, not both")
            aliases = () if args.no_aliases else (tuple(args.alias) if args.alias else None)
            if args.display is None and args.address_as is None and args.hours is None and aliases is None:
                raise SystemExit("refused: nothing to change (use --display, --address-as, --alias, --no-aliases or --hours)")
            contact = book.update(args.key, args.display, args.address_as, aliases, args.hours)
            print(f"contact updated: {contact.key}")
        elif args.action == "remove":
            if not book.remove(args.key):
                raise SystemExit(f"refused: there is no contact with the key {args.key}")
            print(f"contact removed: {args.key}")
        else:
            people = book.all()
            if not people:
                print("no contacts")
            for person in people:
                shown = f"number ending {book.masked(person)}" if not person.rehearsal else f"{book.masked(person)} (rehearsal)"
                print(f"{person.key} | {person.display} | greets as {person.address_as} | {person.hours} | {shown}")
    except ValueError as exc:
        raise SystemExit(f"refused: {exc}") from None
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="desk.admin")
    parser.add_argument("--state-dir", default="/data/.hermes/voice-desk")
    parser.add_argument("--hermes-home", default="/data/.hermes")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("test-call")
    ask_parser = sub.add_parser("ask")
    ask_parser.add_argument("agent", choices=("tutor", "assistant", "coach"))
    ask_parser.add_argument("question", nargs="+")
    ring_parser = sub.add_parser("ring")
    ring_parser.add_argument("name")
    ring_parser.add_argument("purpose")
    ring_parser.add_argument("--yes", action="store_true", help="{{OWNER}} has said yes to the read-back: ring now")
    sub.add_parser("notify-test").add_argument("--voice", action="store_true")
    sub.add_parser("self-check").add_argument("--url")
    sub.add_parser("init").add_argument("--public-base", required=True)
    sub.add_parser("set-owner-number")
    for name in ("dial-mode", "notify-mode"):
        sub.add_parser(name).add_argument("mode", choices=("live", "dry"))
    sub.add_parser("call-summaries").add_argument("state", choices=("on", "off"),
                                                  help="the written note sent after a call {{OWNER}} has with an agent")
    actions = sub.add_parser("contact").add_subparsers(dest="action", required=True)
    add = actions.add_parser("add")
    add.add_argument("key")
    add.add_argument("--display", required=True)
    add.add_argument("--address-as", required=True)
    add.add_argument("--alias", action="append", default=[])
    add.add_argument("--hours", default=contacts.DEFAULT_HOURS)
    actions.add_parser("add-rehearsal").add_argument("--hours", default=contacts.DEFAULT_HOURS)
    edit = actions.add_parser("edit")
    edit.add_argument("key")
    edit.add_argument("--display")
    edit.add_argument("--address-as")
    edit.add_argument("--alias", action="append")
    edit.add_argument("--no-aliases", action="store_true")
    edit.add_argument("--hours")
    actions.add_parser("list")
    actions.add_parser("remove").add_argument("key")
    args = parser.parse_args(argv)
    if args.command == "init":
        made = init_state(args.state_dir, args.public_base.rstrip("/"))
        print("state folder ready" + ("; a new tool secret was generated (not shown)" if made["created_secret"] else ""))
        return 0
    if args.command == "set-owner-number":
        number = util.normalise_number(getpass.getpass("{{OWNER}}'s number: "))
        config.update_config_json(args.state_dir, {"max_number": number})
        print("{{OWNER}}'s number saved")
        return 0
    if args.command == "self-check":
        cfg = config.load(args.state_dir, args.hermes_home)
        results = selfcheck.run(cfg, args.url or f"http://127.0.0.1:{cfg.port}", util.Clock())
        for name, ok, detail in results:
            print(("PASS  " if ok else "FAIL  ") + name + (f" ({detail})" if detail and not ok else ""))
        return 0 if all(ok for _, ok, _ in results) else 1
    if args.command in ("dial-mode", "notify-mode"):
        config.update_config_json(args.state_dir, {args.command.replace("-", "_"): args.mode})
        print(f"{args.command} set to {args.mode}; restart voice-desk for it to take effect")
        return 0
    if args.command == "call-summaries":
        config.update_config_json(args.state_dir, {"call_summaries": args.state == "on"})
        print(f"call summaries {args.state}; restart voice-desk for it to take effect")
        return 0
    cfg = config.load(args.state_dir, args.hermes_home)
    if args.command == "contact":
        return contact_command(args, cfg)
    if args.command == "status":
        status = live_status(cfg)
        if status is None:
            print("the service did not answer: showing the database and settings only", file=sys.stderr)
            status = server.App(cfg)._status()
        print(json.dumps(status, indent=2))
        return 0
    if args.command == "ring":
        code, line = ring(cfg, args.name, args.purpose, args.yes)
        print(line)
        return code
    app = server.App(cfg)
    if args.command == "ask":
        result = ask(app, args.agent, " ".join(args.question))
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") == "done" else 1
    if args.command == "notify-test":
        sent = notify_test(app, args.voice)
        print("sent" if sent else "not sent")
        return 0 if sent else 1
    dial = test_call(app)
    print(f"test call: {dial['status']}" + (f" ({dial['error']})" if dial.get("error") else ""))
    return 0 if dial["status"] in ("called", "dry") else 1


if __name__ == "__main__":
    sys.exit(main())
