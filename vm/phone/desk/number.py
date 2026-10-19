"""Moving the Twilio number onto the new line, and back.

  python3 -m desk.number move      point the number at {{CHIEF}}'s ElevenLabs agent (remembers where it pointed before)
  python3 -m desk.number back      point it where it pointed before and remove it from ElevenLabs (the rollback)
  python3 -m desk.number status    where the number points, whether ElevenLabs has it, and whether a rollback is saved
  python3 -m desk.number import NUMBER
                                   import the number into ElevenLabs and give it to the chief's agent. The Twilio account SID and auth
                                   token are read from stdin (two lines), used once to make ElevenLabs set the number's voice
                                   webhook, and never stored here: no Twilio login is needed on this server afterwards

Importing a number makes ElevenLabs set the number's voice webhook itself. The previous voice URL is written to
line-rollback.json first and is never overwritten, so the rollback always has the original.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import config, util
from .eleven import Eleven, ElevenError
from .twilio import Twilio, TwilioError

ROLLBACK_FILE = "line-rollback.json"


class MoveError(Exception):
    pass


class LineMover:
    def __init__(self, eleven, twilio, cfg, auth_token: str, say=print):
        self.eleven, self.twilio, self.cfg, self.auth_token, self.say = eleven, twilio, cfg, auth_token, say
        self.rollback_path = Path(cfg.state_dir) / ROLLBACK_FILE

    def _need(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self.cfg, n)]
        if missing:
            raise MoveError(f"missing settings: {', '.join(missing)}")

    def _numbers(self) -> list[dict]:
        found = self.eleven.request("GET", "/v1/convai/phone-numbers")
        return found if isinstance(found, list) else found.get("phone_numbers", [])

    def status(self) -> dict:
        """Read-only: where the number points now, whether it is imported, which agent answers it, whether a rollback exists."""
        current = self.twilio.get_number(self.cfg.twilio_number_sid) if self.cfg.twilio_number_sid else {}
        existing = next((n for n in self._numbers() if n.get("phone_number") == self.cfg.twilio_number), None)
        return {"voice_url": current.get("voice_url"), "imported": bool(existing),
                "assigned_agent": ((existing or {}).get("assigned_agent") or {}).get("agent_id"),
                "rollback_saved": self.rollback_path.exists()}

    def move_to_agent(self) -> dict:
        self._need("agent_id", "twilio_number", "twilio_number_sid", "twilio_account_sid")
        if not self.auth_token:
            raise MoveError("the Twilio auth token is not available")
        if not self.rollback_path.exists():
            current = self.twilio.get_number(self.cfg.twilio_number_sid)
            self.rollback_path.write_text(json.dumps({"voice_url": current.get("voice_url"),
                                                      "voice_method": current.get("voice_method") or "POST",
                                                      "saved_at": int(time.time())}, indent=2) + "\n")
            self.say("remembered where the number pointed before (line-rollback.json)")
        existing = next((n for n in self._numbers() if n.get("phone_number") == self.cfg.twilio_number), None)
        if existing:
            number_id = existing["phone_number_id"]
            self.eleven.request("PATCH", f"/v1/convai/phone-numbers/{number_id}", {"agent_id": self.cfg.agent_id})
            self.say("the number was already imported; {{CHIEF}}'s agent is now assigned to it")
        else:
            number_id = self.eleven.request("POST", "/v1/convai/phone-numbers", {
                "phone_number": self.cfg.twilio_number, "label": "{{CHIEF}}'s line", "provider": "twilio",
                "sid": self.cfg.twilio_account_sid, "token": self.auth_token, "agent_id": self.cfg.agent_id,
                "supports_inbound": True, "supports_outbound": True, "enable_sms": False})["phone_number_id"]
            self.say("imported into ElevenLabs and assigned to {{CHIEF}}'s agent")
        config.update_config_json(self.cfg.state_dir, {"phone_number_id": number_id})
        now = self.twilio.get_number(self.cfg.twilio_number_sid)
        self.say(f"the number now points at: {now.get('voice_url')}")
        return {"phone_number_id": number_id, "voice_url": now.get("voice_url")}

    def move_back(self) -> dict:
        self._need("twilio_number_sid")
        if not self.rollback_path.exists():
            raise MoveError("there is no line-rollback.json: nothing to go back to")
        saved = json.loads(self.rollback_path.read_text())
        if not saved.get("voice_url"):
            raise MoveError("the saved record has no voice URL")
        self.twilio.set_voice_url(self.cfg.twilio_number_sid, saved["voice_url"], saved.get("voice_method") or "POST")
        self.say("the number points at its previous address again")
        existing = next((n for n in self._numbers() if n.get("phone_number") == self.cfg.twilio_number), None)
        if existing:
            self.eleven.request("DELETE", f"/v1/convai/phone-numbers/{existing['phone_number_id']}")
            self.say("removed from ElevenLabs")
        config.update_config_json(self.cfg.state_dir, {"phone_number_id": ""})
        return {"voice_url": saved["voice_url"]}


def import_number(eleven, cfg, number: str, account_sid: str, token: str, say=print) -> str:
    """Import a Twilio number into ElevenLabs for the chief's phone agent and remember its id. Safe to repeat."""
    if not cfg.agent_id:
        raise MoveError("the phone agent does not exist yet: run the push first (python3 -m desk.push_agent)")
    found = eleven.request("GET", "/v1/convai/phone-numbers")
    found = found if isinstance(found, list) else found.get("phone_numbers", [])
    existing = next((n for n in found if n.get("phone_number") == number), None)
    if existing:
        number_id = existing["phone_number_id"]
        eleven.request("PATCH", f"/v1/convai/phone-numbers/{number_id}", {"agent_id": cfg.agent_id})
        say("the number was already in ElevenLabs; the chief's agent is now assigned to it")
    else:
        number_id = eleven.request("POST", "/v1/convai/phone-numbers", {
            "phone_number": number, "label": "Phone line", "provider": "twilio", "sid": account_sid, "token": token,
            "agent_id": cfg.agent_id, "supports_inbound": True, "supports_outbound": True, "enable_sms": False})["phone_number_id"]
        say("imported into ElevenLabs and assigned to the chief's agent")
    config.update_config_json(cfg.state_dir, {"phone_number_id": number_id})
    return number_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="desk.number")
    parser.add_argument("command", choices=("move", "back", "status", "import"))
    parser.add_argument("number", nargs="?", default="")
    parser.add_argument("--state-dir", default="/data/.hermes/voice-desk")
    parser.add_argument("--hermes-home", default="/data/.hermes")
    args = parser.parse_args(argv)
    cfg = config.load(args.state_dir, args.hermes_home)
    if args.command == "import":
        sid, token = (sys.stdin.readline().strip(), sys.stdin.readline().strip())
        if not (args.number and sid and token):
            print("failed: a number, then the Twilio account SID and auth token on two lines of stdin", file=sys.stderr)
            return 1
        try:
            import_number(Eleven(cfg.eleven_key), cfg, util.normalise_number(args.number), sid, token)
        except (MoveError, ElevenError) as exc:
            print(f"failed: {exc}", file=sys.stderr)
            return 1
        return 0
    token = config.read_env_file(Path(args.hermes_home) / ".env").get("TWILIO_AUTH_TOKEN", "")
    mover = LineMover(Eleven(cfg.eleven_key), Twilio(cfg.twilio_account_sid, cfg.twilio_key_sid, cfg.twilio_key_secret), cfg, token)
    try:
        if args.command == "status":
            print(json.dumps(mover.status(), indent=2))
        else:
            mover.move_to_agent() if args.command == "move" else mover.move_back()
    except (MoveError, ElevenError, TwilioError) as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
