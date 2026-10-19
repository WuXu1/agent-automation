"""The ElevenLabs REST calls the desk makes: place an outbound call, list conversations (for the minutes guard),
read the billing period, speak a note. The API key never appears in an error message."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class ElevenError(Exception):
    """`definite` means ElevenLabs refused the request, so nothing happened. A timeout or a 5xx is not definite:
    the call may have been placed anyway, so such a dial is never repeated."""

    def __init__(self, message: str, status: int | None = None, definite: bool = True):
        super().__init__(message)
        self.status, self.definite = status, definite


class Eleven:
    def __init__(self, key: str, base: str = "https://api.elevenlabs.io", timeout: float = 20.0):
        self.key, self.base, self.timeout = key, base.rstrip("/"), timeout

    def _call(self, method: str, path: str, body: dict | None = None, raw: bool = False):
        request = urllib.request.Request(
            self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
            headers={"xi-api-key": self.key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:200].decode("utf-8", "replace").replace(self.key, "***")
            exc.close()
            raise ElevenError(f"HTTP {exc.code}: {detail}", exc.code, definite=exc.code < 500) from None
        except (urllib.error.URLError, OSError) as exc:
            raise ElevenError(type(exc).__name__, None, definite=False) from None
        return data if raw else json.loads(data or b"{}")

    def request(self, method: str, path: str, body: dict | None = None):
        """Any other ElevenLabs call (used by the operator scripts that set the agent up)."""
        return self._call(method, path, body)

    def outbound_call(self, agent_id: str, phone_number_id: str, to_number: str, dynamic_variables: dict,
                      ringing_timeout_secs: int = 45) -> dict:
        """Returns {'conversation_id': ..., 'call_sid': ...}. Voicemail is detected on the line and the agent hangs up."""
        reply = self._call("POST", "/v1/convai/twilio/outbound-call", {
            "agent_id": agent_id,
            "agent_phone_number_id": phone_number_id,
            "to_number": to_number,
            "conversation_initiation_client_data": {"dynamic_variables": dynamic_variables},
            "telephony_call_config": {"ringing_timeout_secs": ringing_timeout_secs,
                                      "twilio_machine_detection": {"mode": "enable"}},
        })
        if not reply.get("success", True):
            raise ElevenError(f"refused: {reply.get('message', '')[:120]}", None, definite=True)
        return {"conversation_id": reply.get("conversation_id"), "call_sid": reply.get("callSid")}

    def conversations_since(self, start_unix: int, agent_id: str | None = None, max_pages: int = 10) -> list[dict]:
        """Every conversation that started at or after `start_unix` (all agents unless one is named)."""
        out, cursor = [], None
        for _ in range(max_pages):
            query = {"call_start_after_unix": int(start_unix), "page_size": 100}
            if agent_id:
                query["agent_id"] = agent_id
            if cursor:
                query["cursor"] = cursor
            page = self._call("GET", "/v1/convai/conversations?" + urllib.parse.urlencode(query))
            out.extend(page.get("conversations", []))
            cursor = page.get("next_cursor")
            if not page.get("has_more") or not cursor:
                break
        return out

    def subscription(self) -> dict:
        return self._call("GET", "/v1/user/subscription")

    def speak(self, text: str, voice_id: str, model_id: str = "eleven_v4") -> bytes:
        """Ogg Opus audio of `text` (the format Telegram voice notes use)."""
        return self._call("POST", f"/v1/text-to-speech/{voice_id}?output_format=opus_48000_64",
                          {"text": text, "model_id": model_id}, raw=True)
