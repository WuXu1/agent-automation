"""A rehearsal of the desk's public surface, the way ElevenLabs will use it: no phone rings, no real conversation is touched.

  python3 -m desk.admin self-check [--url https://maxs-hermes-vm.tail2186d3.ts.net:8443]

Run on the server (it needs the desk's secrets). Conversation ids start with "selfcheck-", which the desk never counts as a
real call, so a rehearsal can never hold up a call-back.
"""
from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.request

from . import security, variables
from .calls import SELFCHECK


def _call(base: str, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
    request = urllib.request.Request(base.rstrip("/") + path, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        data = exc.read()
        exc.close()
        return exc.code, data
    except (urllib.error.URLError, OSError) as exc:
        return 0, type(exc).__name__.encode()


def run(cfg, base_url: str, clock) -> list[tuple[str, bool, str]]:
    """[(what was checked, passed, detail)]. Never raises on a failed check."""
    results: list[tuple[str, bool, str]] = []
    run_id = f"{SELFCHECK}{secrets.token_hex(4)}-"      # new every run: the desk answers a repeated conversation id with the first run's token, long expired

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))

    auth = {"x-desk-secret": cfg.tool_secret, "Content-Type": "application/json"}

    def post(path: str, payload: dict | None = None, headers: dict | None = None, raw: bytes | None = None):
        body = raw if raw is not None else json.dumps(payload or {}).encode()
        return _call(base_url, "POST", path, body, headers if headers is not None else auth)

    def parsed(data: bytes) -> dict:
        try:
            value = json.loads(data)
            return value if isinstance(value, dict) else {}
        except ValueError:
            return {}

    status, data = _call(base_url, "GET", "/health")
    check("health answers", status == 200 and parsed(data).get("ok") is True, f"HTTP {status}")
    status, _ = _call(base_url, "GET", "/status")
    check("status refuses a caller with no secret", status == 401, f"HTTP {status}")
    status, data = _call(base_url, "GET", "/status", headers={"x-desk-secret": cfg.tool_secret})
    check("status answers with the secret", status == 200 and "dial_mode" in parsed(data), f"HTTP {status}")

    status, data = post("/init", {"caller_id": cfg.max_number, "conversation_id": f"{run_id}max"})
    values = parsed(data).get("dynamic_variables", {})
    check("{{OWNER}}'s call gets every variable, his brief and a token",
          status == 200 and set(values) == set(variables.NAMES) and values.get("caller_mode") == "max"
          and values.get("secret__desk_token") not in (None, "", "none") and bool(values.get("brief")), f"HTTP {status}")
    token = values.get("secret__desk_token", "")
    status, data = post("/tools/check_pending", {}, {**auth, "x-desk-token": token})
    check("the tools work with that token", status == 200 and "finished" in parsed(data), f"HTTP {status}")
    # the ring-somebody tool, asked about a name that is in nobody's contact book and never confirmed: it must answer in words (HTTP 200,
    # status failed) and ring nobody; there is no way for this check to place a call
    status, data = post("/tools/call_someone", {"name": "selfcheck nobody", "purpose": "Say hello.", "confirmed": False},
                        {**auth, "x-desk-token": token})
    check("asking to ring somebody who is not in the contact book is answered in words and rings nobody",
          status == 200 and parsed(data).get("status") == "failed" and bool(parsed(data).get("message")), f"HTTP {status}")
    status, _ = post("/tools/check_pending", {})
    check("the tools refuse a missing token", status == 403, f"HTTP {status}")
    status, _ = post("/tools/check_pending", {}, {"x-desk-token": token, "Content-Type": "application/json"})
    check("the tools refuse a missing secret", status == 401, f"HTTP {status}")

    status, data = post("/init", {"caller_id": "+440000000000", "conversation_id": f"{run_id}stranger"})
    values = parsed(data).get("dynamic_variables", {})
    check("a stranger gets message-taking, no brief and no token",
          status == 200 and values.get("caller_mode") == "stranger" and values.get("brief") == ""
          and values.get("secret__desk_token") == "none", f"HTTP {status}")

    event = json.dumps({"type": "post_call_transcription", "data": {
        "conversation_id": f"{run_id}max", "transcript": [{"role": "agent", "message": "Good evening, {{sir}}."}],
        "metadata": {"call_duration_secs": 1}}}).encode()
    status, _ = post("/postcall", raw=event, headers={"Content-Type": "application/json"})
    check("the post-call webhook refuses an unsigned event", status == 401, f"HTTP {status}")
    if cfg.webhook_secret:
        signature = security.sign_eleven_payload(event, cfg.webhook_secret, int(clock.time()))
        status, _ = post("/postcall", raw=event, headers={"Content-Type": "application/json", "ElevenLabs-Signature": signature})
        check("the post-call webhook accepts a correctly signed event", status == 200, f"HTTP {status}")
    else:
        check("the post-call webhook accepts a correctly signed event", True, "skipped: no webhook secret yet")

    status, data = _call(base_url, "GET", "/twiml/closed")
    check("the closed message is served", status == 200 and b"<Response>" in data, f"HTTP {status}")
    leaked = cfg.tool_secret.encode() in data
    check("nothing public contains the secret", not leaked)
    return results
