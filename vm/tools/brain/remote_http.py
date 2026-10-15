#!/usr/bin/env python3
"""remote_http.py - the shared Mem0 memory as a remote MCP server, for ChatGPT's custom connectors, the Gemini app and anything else that takes a URL (sudo hermes-brain).

Speaks MCP's Streamable HTTP in its simplest form (one JSON answer per POST, no sessions) on 127.0.0.1:8895; Tailscale a Cloudflare tunnel carries it to the internet. The link IS the password: /mcp/<token>, where the token is 64 random characters kept in /data/.hermes/mem0-remote.token (mode 600, hermes only).
A wrong token gets the same blank 404 as any other path. The token is never logged (this server logs nothing but the tool names).

Tools: search, add, update (same code as mem0_mcp.py; notes are tagged with the agent id "chat-app"). **No delete** over the internet: delete from the dashboard or a Mac session.
"""
from __future__ import annotations

import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("MEM0_CODE_AGENT_ID", os.environ.get("MEM0_REMOTE_AGENT", "chat-app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mem0_mcp as core  # noqa: E402

TOKEN_FILE = Path(os.environ.get("MEM0_REMOTE_TOKEN_FILE", "/data/.hermes/mem0-remote.token"))
HOST, PORT = "127.0.0.1", int(os.environ.get("MEM0_REMOTE_PORT", "8895"))
ALLOWED = ("mem0_search", "mem0_add", "mem0_update")
MAX_BODY = 64 * 1024
core.TOOLS = [t for t in core.TOOLS if t["name"] in ALLOWED]
core.HANDLERS = {k: v for k, v in core.HANDLERS.items() if k in ALLOWED}
core.SERVER_INFO = {"name": "second-brain", "version": "1.0.0"}


def read_token() -> str:
    tok = TOKEN_FILE.read_text().strip() if TOKEN_FILE.is_file() else ""
    return tok if len(tok) >= 40 else ""


class Handler(BaseHTTPRequestHandler):
    server_version = "x"
    sys_version = ""
    token = ""

    def log_message(self, *a) -> None:                    # the path holds the token: no default access log
        pass

    def log_request(self, code="-", size="-") -> None:  # also reached by errors for methods we do not know (HEAD, OPTIONS ...): log them without the link
        shown = self.path.split("?", 1)[0]
        shown = shown if "/mcp/" not in shown else shown.split("/mcp/", 1)[0] + "/mcp/<link>"
        print(f"req {self.command} {shown} -> {code} accept={self.headers.get('Accept', '-')[:60]} ua={self.headers.get('User-Agent', '-')[:40]}", file=sys.stderr, flush=True)

    def _send(self, code: int, body: bytes = b"", ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self) -> bool:
        path = self.path.split("?", 1)[0]
        for prefix in ("/brain", ""):                      # Funnel strips the mount path; accept both
            if path.startswith(prefix + "/mcp/"):
                given = path[len(prefix) + 5:].rstrip("/")
                ok = bool(self.token) and hmac.compare_digest(given.encode(), self.token.encode())
                if not ok:
                    time.sleep(1.0)                        # slows any guessing; the token has 380+ bits anyway
                return ok
        return False

    def do_POST(self) -> None:
        if not self._authorised():
            return self._send(404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send(400)
        if n <= 0 or n > MAX_BODY:
            return self._send(413 if n > MAX_BODY else 400)
        try:
            msg = json.loads(self.rfile.read(n))
        except ValueError:
            return self._send(400)
        batch = msg if isinstance(msg, list) else [msg]
        out = []
        for req in batch:
            if not isinstance(req, dict):
                continue
            if req.get("method") == "tools/call":
                print(f"tool {(req.get('params') or {}).get('name')}", file=sys.stderr, flush=True)
            res = core.handle(req)
            if res is not None:
                out.append(res)
        if not out:
            return self._send(202)
        self._send(200, json.dumps(out if isinstance(msg, list) else out[0]).encode())

    def do_GET(self) -> None:                              # no server-initiated stream: say so after the same auth check
        self._send(405 if self._authorised() else 404)

    def do_HEAD(self) -> None:
        self.send_response(405 if self._authorised() else 404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_OPTIONS(self) -> None:                           # a pre-flight: answer it for the link holder only
        if not self._authorised():
            return self._send(404)
        self.send_response(204)
        self.send_header("Allow", "POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_DELETE = do_PUT = do_PATCH = do_GET


def main() -> int:
    tok = read_token()
    if not tok:
        print(f"remote_http: no token in {TOKEN_FILE} (run sudo hermes-brain on)", file=sys.stderr)
        return 1
    Handler.token = tok
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"remote_http: ready on {HOST}:{PORT}, tools {', '.join(ALLOWED)}", file=sys.stderr, flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
