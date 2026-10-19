"""The few Twilio REST calls the desk makes: read a number's voice URL and change it (the minutes guard's switch)."""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request


class TwilioError(Exception):
    pass


class Twilio:
    def __init__(self, account_sid: str, key_sid: str, key_secret: str, base: str = "https://api.twilio.com",
                 timeout: float = 15.0):
        self.account_sid, self.base, self.timeout = account_sid, base.rstrip("/"), timeout
        self._auth = "Basic " + base64.b64encode(f"{key_sid}:{key_secret}".encode()).decode()
        self._secrets = [key_secret, key_sid]

    def _call(self, method: str, path: str, form: dict | None = None) -> dict:
        request = urllib.request.Request(
            f"{self.base}/2010-04-01/Accounts/{self.account_sid}{path}", method=method,
            data=urllib.parse.urlencode(form).encode() if form is not None else None,
            headers={"Authorization": self._auth, "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            exc.close()
            raise TwilioError(f"HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise TwilioError(type(exc).__name__) from None

    def get_number(self, number_sid: str) -> dict:
        return self._call("GET", f"/IncomingPhoneNumbers/{number_sid}.json")

    def set_voice_url(self, number_sid: str, url: str, method: str = "POST") -> dict:
        return self._call("POST", f"/IncomingPhoneNumbers/{number_sid}.json", {"VoiceUrl": url, "VoiceMethod": method})
