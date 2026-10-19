"""The desk's HTTP server: authentication, routing, and the wiring of every component.

Public (through Tailscale Funnel): /init, /tools/*, /postcall, /twiml/closed, /twiml/unavailable, /health, /status. Everything
except /health and the two /twiml/ messages needs a secret: the shared tool secret (and, for tools, the per-call token), or ElevenLabs' HMAC signature.
"""
from __future__ import annotations

import argparse
import http.server
import json
import logging
import signal
import sys
import threading

from . import brief, callbacks, calls, config, contacts, db, dialer, eleven, guests, hermes, minutes, notify, persona, security
from . import summary, tickets, tools, twilio, util, variables, webhooks

log = logging.getLogger("desk.server")
MAX_BODY = 64 * 1024
MAX_POSTCALL_BODY = 1024 * 1024
TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response><Say language="en-GB">{text}</Say><Hangup/></Response>'


class App:
    def __init__(self, cfg, clock=None, env=None, brief_run=None, notify_run=None, eleven_client=None,
                 twilio_client=None, hermes_client=None):
        self.cfg = cfg
        self.clock = clock or util.Clock()
        self.db = db.DB(cfg.db_path)
        self.tickets = tickets.Tickets(self.db, self.clock)
        self.calls = calls.Calls(self.db, self.clock, cfg)
        self.eleven = eleven_client or eleven.Eleven(cfg.eleven_key)
        self.twilio = twilio_client or (twilio.Twilio(cfg.twilio_account_sid, cfg.twilio_key_sid, cfg.twilio_key_secret)
                                        if cfg.twilio_key_sid and cfg.twilio_key_secret else None)
        self.hermes = hermes_client or hermes.HermesClient(cfg.hermes_base, cfg.hermes_keys)
        self.notifier = notify.Notifier(cfg, self.db, self.clock, run=notify_run or notify.run_status,
                                        speak=lambda text: self.eleven.speak(text, cfg.voice_id))
        self.minutes = minutes.Minutes(cfg, self.db, self.eleven, self.twilio, self.notifier, self.clock)
        self.brief = brief.Brief(cfg, self.clock, run=brief_run or brief.run_cmd, tickets=self.tickets,
                                 minutes_text=self.minutes.text)
        self.contacts = contacts.ContactBook(cfg.contacts_path, cfg.max_number)
        self.variables = variables.Variables(cfg, self.clock, self.brief, self.tickets, self.minutes.text, self.contacts)
        self.dialer = dialer.Dialer(cfg, self.db, self.eleven, self.calls, self.clock, env=env,
                                    blocked=self.minutes.blocked_reason)
        self.callbacks = callbacks.Callbacks(cfg, self.db, self.tickets, self.calls, self.dialer, self.notifier,
                                             self.variables, self.clock)
        self.runner = hermes.Runner(self.tickets, self.hermes, self.clock, tools.compose, on_finish=self.callbacks.poke)
        self.guests = guests.Guests(cfg, self.db, self.tickets, self.calls, self.dialer, self.notifier, self.variables,
                                    self.contacts, self.clock, poke=self.callbacks.poke)
        self.tools = tools.Tools(cfg, self.tickets, self.calls, self.runner, self.clock, guests=self.guests)
        self.summaries = summary.Summaries(cfg, self.tickets, self.hermes, self.notifier, self.clock)
        self.webhooks = webhooks.Webhooks(cfg, self.db, self.calls, self.variables, self.dialer, self.callbacks,
                                          self.summaries, self.minutes, self.tickets, self.guests)
        self.failures = security.RateLimiter(30, 600, self.clock)          # bad attempts, per 10 minutes (see refuse())

    def start(self) -> None:
        resumed = self.runner.resume()
        log.info("desk started (dial=%s, notify=%s); resumed %d ticket(s)", self.cfg.dial_mode, self.cfg.notify_mode, resumed)
        self.brief.start()
        self.callbacks.start()
        self.minutes.start()

    def stop(self) -> None:
        for part in (self.brief, self.callbacks, self.minutes):
            part.stop()

    # -- one request ----------------------------------------------------------------------------------
    @staticmethod
    def _json(status: int, payload: dict) -> tuple[int, str, bytes]:
        return status, "application/json", json.dumps(payload).encode()

    def _closed_twiml(self) -> tuple[int, str, bytes]:
        reset = self.db.kv_get("minutes_reset")
        when = f"until the {util.uk_time(int(reset)).strftime('%-d %B')}" if reset else "until further notice"
        what = "voice credits" if self.minutes.closed_reason() == "credits" else "call minutes"
        text = (f"This is {{CHIEF}}. The phone line is closed {when}, because this month's {what} are used up. "
                "Please send a message on Telegram instead. Goodbye.")
        return 200, "text/xml", TWIML.format(text=text).encode()

    @staticmethod
    def _unavailable_twiml() -> tuple[int, str, bytes]:
        """What the number says when {{CHIEF}}'s agent has been taken off it (a rollback), whatever the reason."""
        text = f"This is {{CHIEF}}, {persona.TITLE}. I am not available at the moment. Please try again a little later. Goodbye."
        return 200, "text/xml", TWIML.format(text=text).encode()

    def _status(self) -> dict:
        counts = {}
        for row in self.db.q("SELECT status, delivery, COUNT(*) AS n FROM tickets GROUP BY status, delivery"):
            counts[f"{row['status']}/{row['delivery']}"] = row["n"]
        return {"dial_mode": self.cfg.dial_mode, "notify_mode": self.cfg.notify_mode, "tickets": counts,
                "active_calls": len(self.calls.active()), "minutes": self.minutes.status(),
                "brief_age_secs": {name: None if age is None else round(age) for name, age in self.brief.ages().items()},
                "failed_messages": self.db.q("SELECT COUNT(*) AS n FROM messages WHERE sent = 0 AND mode = 'live'")[0]["n"],
                "guest_calls": {"agent_set": bool(self.cfg.guest_agent_id), "contacts": len(self.contacts.all())},
                "missing_settings": self.cfg.problems()}

    def handle(self, method: str, path: str, headers: dict, body: bytes) -> tuple[int, str, bytes]:
        """Returns (status, content type, body). `headers` keys are lower-case."""
        route = path.split("?")[0].rstrip("/") or "/"
        if method == "GET" and route == "/health":
            return self._json(200, {"ok": True})
        if route == "/twiml/closed" and method in ("GET", "POST"):
            return self._closed_twiml()
        if route == "/twiml/unavailable" and method in ("GET", "POST"):
            return self._unavailable_twiml()
        if len(body) > (MAX_POSTCALL_BODY if route == "/postcall" else MAX_BODY):
            return self._json(413, {"error": "too large"})

        def refuse(status: int, message: str):
            """Everything that fails authentication ends here. Past 30 bad attempts in ten minutes they are answered with a
            cheap 429, but a caller with the right secret never passes through here, so nobody can lock the line out."""
            if self.failures.exhausted("auth"):
                return self._json(429, {"error": "too many failed attempts"})
            self.failures.allow("auth")
            return self._json(status, {"error": message})

        if route == "/postcall" and method == "POST":
            if not security.verify_eleven_signature(body, headers.get("elevenlabs-signature"), self.cfg.webhook_secret,
                                                    self.clock.time()):
                return refuse(401, "bad signature")
            event = self._parse(body)
            return self._json(400, {"error": "invalid JSON"}) if event is None else self._json(200, self.webhooks.post_call(event))
        if route == "/chat/call_someone":
            if not security.secrets_equal(headers.get("x-desk-secret"), self.cfg.tool_secret):
                return refuse(401, "unauthorised")
            if method != "POST":
                return self._json(405, {"error": "POST only"})
            args = self._parse(body)
            if args is None:
                return self._json(400, {"error": "invalid JSON"})
            status, payload = self.guests.request_from_chat(args.get("name"), args.get("purpose"), args.get("confirmed"))
            return self._json(status, payload)
        if route in ("/init", "/status") or route.startswith("/tools/"):
            if not security.secrets_equal(headers.get("x-desk-secret"), self.cfg.tool_secret):
                return refuse(401, "unauthorised")
            if route == "/status" and method == "GET":
                return self._json(200, self._status())
            if method != "POST":
                return self._json(405, {"error": "POST only"})
            args = self._parse(body)
            if args is None:
                return self._json(400, {"error": "invalid JSON"})
            if route == "/init":
                return self._json(200, self.webhooks.initiation(args))
            call = self.calls.by_token(headers.get("x-desk-token"))
            if call is None:
                return refuse(403, "no valid call token")
            handler = {"ask_agent": self.tools.ask_agent, "do_for_max": self.tools.do_for_max,
                       "set_reminder": self.tools.set_reminder, "call_someone": self.tools.call_someone,
                       "check_pending": self.tools.check_pending}.get(route[len("/tools/"):])
            if handler is None:
                return self._json(404, {"error": "unknown tool"})
            status, payload = handler(call, args)
            return self._json(status, payload)
        return self._json(404, {"error": "not found"})

    @staticmethod
    def _parse(body: bytes):
        try:
            value = json.loads(body or b"{}")
        except ValueError:
            return None
        return value if isinstance(value, dict) else None


def make_server(app: App, host: str = "127.0.0.1", port: int = 8800) -> http.server.ThreadingHTTPServer:
    class Handler(http.server.BaseHTTPRequestHandler):
        timeout = 30

        def _serve(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_POSTCALL_BODY:
                status, ctype, payload = App._json(413, {"error": "too large"})
            else:
                raw = self.rfile.read(length) if length else b""
                headers = {k.lower(): v for k, v in self.headers.items()}
                try:
                    status, ctype, payload = app.handle(self.command, self.path, headers, raw)
                except Exception as exc:  # noqa: BLE001 - never leak details to the caller
                    log.warning("request failed: %s", type(exc).__name__)
                    status, ctype, payload = App._json(500, {"error": "internal error"})
            log.info("%s %s -> %d", self.command, self.path.split("?")[0], status)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve

        def log_message(self, *args):
            pass

    class DeskServer(http.server.ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
                log.info("the caller went away before the reply could be sent")          # a call that simply ended
                return
            super().handle_error(request, client_address)

    return DeskServer((host, port), Handler)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="{{CHIEF}}'s voice desk")
    parser.add_argument("--state-dir", default="/data/.hermes/voice-desk")
    parser.add_argument("--hermes-home", default="/data/.hermes")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config.load(args.state_dir, args.hermes_home)
    missing = cfg.problems()
    if missing:
        log.warning("not fully configured yet (missing: %s)", ", ".join(missing))
    app = App(cfg)
    app.start()
    server = make_server(app, "127.0.0.1", cfg.port)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    log.info("listening on 127.0.0.1:%d", cfg.port)
    try:
        server.serve_forever()
    finally:
        app.stop()
        server.server_close()


if __name__ == "__main__":
    main()
