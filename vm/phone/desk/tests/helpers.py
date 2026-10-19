"""Shared test helpers: a fake clock and a throwaway local HTTP server."""
import http.server
import json
import logging
import threading

logging.getLogger("desk").addHandler(logging.NullHandler())   # expected warnings stay out of the test output


class FakeClock:
    """Time that only moves when told to (sleep() moves it)."""

    def __init__(self, now=1_000_000.0):
        self.now = now

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeServer:
    """A local HTTP server for tests. `handler(method, path, headers, body)` returns (status, json-able body).
    Every request is kept in `.requests` as (method, path, headers, body)."""

    def __init__(self, handler):
        self.handler = handler
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _serve(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = raw.decode("utf-8", "replace")
                headers = {k.lower(): v for k, v in self.headers.items()}
                outer.requests.append((self.command, self.path, headers, body))
                status, payload = outer.handler(self.command, self.path, headers, body)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class FakeHermes:
    """Scripted Hermes API. Each run takes `polls` GETs before it ends as `end` with `output`; all profiles share it.
    Keys: default 'defkey', assistant 'annakey', tutor 'tomkey', coach 'connerkey'."""

    KEYS = {"default": "defkey", "assistant": "annakey", "tutor": "tomkey", "coach": "connerkey"}

    def __init__(self, polls=2, end="completed", output="Nothing booked, {{sir}}."):
        self.polls, self.end, self.output = polls, end, output
        self.runs, self.counts, self.profiles = {}, {}, {}
        self.server = FakeServer(self.handle)

    def handle(self, method, path, headers, body):
        route = path.split("/v1/runs")
        profile = "default" if not route[0] else route[0].split("/")[2]
        if headers.get("authorization") != f"Bearer {self.KEYS[profile]}":
            return 401, {"error": "bad key"}
        if method == "POST" and route[1] == "":
            run_id = f"run_{len(self.runs) + 1}"
            self.runs[run_id], self.profiles[run_id] = body, profile
            return 202, {"run_id": run_id, "status": "started"}
        run_id = route[1].strip("/")
        if run_id not in self.runs:
            return 404, {"error": "unknown run"}
        self.counts[run_id] = self.counts.get(run_id, 0) + 1
        if self.counts[run_id] <= self.polls:
            return 200, {"run_id": run_id, "status": "running"}
        output = self.output(self.runs[run_id], self.profiles[run_id]) if callable(self.output) else self.output
        return 200, {"run_id": run_id, "status": self.end, "output": output}
