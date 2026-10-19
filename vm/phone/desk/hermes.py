"""Talking to Hermes: start a run on an agent's profile, follow it to the end, record the result on its ticket.

Each profile has its own API key (the default key is rejected on /p/<profile>/ routes). Runs happen inside the warm
gateway, so a short question comes back in about 3 seconds. A run keeps going after the call ends; its ticket
records the result whenever it arrives.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request

log = logging.getLogger("desk.hermes")
BAD_ENDINGS = ("failed", "cancelled", "interrupted")


class HermesError(Exception):
    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


class HermesNotFound(HermesError):
    pass


class HermesClient:
    def __init__(self, base: str, keys: dict[str, str], timeout: float = 15.0):
        self.base, self.keys, self.timeout = base.rstrip("/"), keys, timeout

    def _call(self, method: str, profile: str, tail: str, body: dict | None = None, headers: dict | None = None) -> dict:
        key = self.keys.get(profile)
        if not key:
            raise HermesError(f"no API key for profile {profile}")
        prefix = "" if profile == "default" else f"/p/{profile}"
        request = urllib.request.Request(
            f"{self.base}{prefix}{tail}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code == 404:
                raise HermesNotFound("not found") from None
            raise HermesError(f"HTTP {exc.code}", transient=exc.code >= 500 or exc.code == 429) from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise HermesError(type(exc).__name__, transient=True) from None

    def start_run(self, profile: str, text: str, instructions: str, session_id: str, idempotency_key: str) -> str:
        run = self._call("POST", profile, "/v1/runs",
                         {"input": text, "instructions": instructions, "session_id": session_id},
                         {"Idempotency-Key": idempotency_key})
        if not run.get("run_id"):
            raise HermesError("no run id in the reply")
        return run["run_id"]

    def get_run(self, profile: str, run_id: str) -> dict:
        return self._call("GET", profile, f"/v1/runs/{run_id}")

    def ask(self, profile: str, text: str, instructions: str, session_id: str, idempotency_key: str, clock,
            timeout: float = 40.0, poll: float = 0.5) -> str | None:
        """One run, waited for. The output, or None when it fails or takes longer than `timeout` seconds."""
        try:
            run_id = self.start_run(profile, text, instructions, session_id, idempotency_key)
            started = clock.time()
            while clock.time() - started < timeout:
                run = self.get_run(profile, run_id)
                if run.get("status") == "completed":
                    return run.get("output") or None
                if run.get("status") in BAD_ENDINGS:
                    return None
                clock.sleep(poll)
        except HermesError:
            return None
        return None

    def stop_run(self, profile: str, run_id: str) -> None:
        try:
            self._call("POST", profile, f"/v1/runs/{run_id}/stop", {})
        except HermesError:
            pass


class Runner:
    """Runs each ticket's Hermes run on its own thread and records the outcome. `compose(ticket)` returns the
    (input text, instructions) for the run; `on_finish(ticket)` is told when a ticket reaches a final state."""

    def __init__(self, tickets, hermes, clock, compose, *, on_finish=None, fast_poll: float = 0.5,
                 slow_poll: float = 5.0, retry_secs: float = 5.0, give_up_secs: float = 3600.0):
        self.tickets, self.hermes, self.clock, self.compose = tickets, hermes, clock, compose
        self.on_finish = on_finish
        self.fast_poll, self.slow_poll, self.retry_secs, self.give_up_secs = fast_poll, slow_poll, retry_secs, give_up_secs
        self._events: dict[int, threading.Event] = {}
        self._working: set[int] = set()
        self._lock = threading.Lock()

    def _event(self, tid: int) -> threading.Event:
        with self._lock:
            return self._events.setdefault(tid, threading.Event())

    def start(self, tid: int) -> bool:
        """Begin working on a ticket (once). False when it is already being worked on."""
        with self._lock:
            if tid in self._working:
                return False
            self._working.add(tid)
        threading.Thread(target=self._work, args=(tid,), daemon=True, name=f"ticket-{tid}").start()
        return True

    def wait(self, tid: int, timeout: float) -> dict:
        """Wait up to `timeout` real seconds for the ticket to finish; returns the ticket either way."""
        self._event(tid).wait(timeout)
        return self.tickets.get(tid)

    def resume(self) -> int:
        """After a restart of the desk: carry on with every unfinished ticket that is a Hermes run. (A guest ticket is a phone
        call: its post-call webhook, or the stuck-call sweep, finishes it.)"""
        return sum(1 for row in self.tickets.unfinished() if row["kind"] != "guest" and self.start(row["id"]))

    # -- the worker ---------------------------------------------------------------------------
    def _work(self, tid: int) -> None:
        try:
            self._run(tid)
        except Exception as exc:  # noqa: BLE001 - a worker must never die silently
            log.warning("ticket %s worker crashed: %s", tid, type(exc).__name__)
            self.tickets.fail(tid, f"internal error: {type(exc).__name__}")
        finally:
            final = self.tickets.get(tid)
            with self._lock:
                self._working.discard(tid)
            self._event(tid).set()
            if self.on_finish and final and final["status"] in ("done", "failed", "lost"):
                try:
                    self.on_finish(final)
                except Exception:  # noqa: BLE001
                    log.warning("on_finish failed for ticket %s", tid)

    def _start_run(self, ticket: dict) -> str | None:
        text, instructions = self.compose(ticket)
        for attempt in range(3):
            try:
                return self.hermes.start_run(ticket["agent"], text, instructions, f"phone-t{ticket['id']}",
                                             f"desk-ticket-{ticket['id']}")
            except HermesError as exc:
                if not exc.transient or attempt == 2:
                    self.tickets.fail(ticket["id"], f"could not start the run: {exc}")
                    return None
                self.clock.sleep(2.0)
        return None

    def _run(self, tid: int) -> None:
        ticket = self.tickets.get(tid)
        if ticket is None or ticket["status"] in ("done", "failed", "lost") or ticket["kind"] == "guest":
            return
        run_id = ticket["run_id"]
        if not run_id:
            run_id = self._start_run(ticket)
            if run_id is None:
                return
            self.tickets.set_running(tid, run_id)
        started = self.clock.time()
        while True:
            try:
                run = self.hermes.get_run(ticket["agent"], run_id)
            except HermesNotFound:
                self.tickets.fail(tid, "Hermes no longer knows this run (it may have been restarted)", lost=True)
                return
            except HermesError as exc:
                if not exc.transient or self.clock.time() - started > self.give_up_secs:
                    self.tickets.fail(tid, f"lost contact with Hermes: {exc}")
                    return
                self.clock.sleep(self.retry_secs)
                continue
            status = run.get("status")
            if status == "completed":
                self.tickets.finish(tid, run.get("output"))
                return
            if status in BAD_ENDINGS:
                self.tickets.fail(tid, f"the run ended as {status}")
                return
            if self.clock.time() - started > self.give_up_secs:
                self.hermes.stop_run(ticket["agent"], run_id)
                self.tickets.fail(tid, "gave up waiting for the run")
                return
            self.clock.sleep(self.fast_poll if self.clock.time() - started < 30 else self.slow_poll)
