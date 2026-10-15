"""Bridge tests: a fake Mem0 on a local port, no network, no VM. Run: python3 -m unittest discover -s dashboard/bridge/tests"""
from __future__ import annotations

import http.server
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))      # crewfix
import bridge  # noqa: E402
from crewfix import LOGIN as OWNER  # noqa: E402

UUID_A = "11111111-2222-3333-4444-555555555555"
UUID_B = "66666666-7777-8888-9999-000000000000"
UUID_NEW = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class FakeMem0:
    """Enough of Mem0's REST server; records every call so the tests can prove what was (never) called."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.key_seen: list[str] = []
        self.rows = {
            UUID_A: {"id": UUID_A, "memory": "Goes swimming on Fridays.", "user_id": "sam", "agent_id": "rocky",
                     "metadata": {"source": None}, "created_at": "2026-10-06T19:00:00+01:00", "updated_at": None},
            UUID_B: {"id": UUID_B, "memory": "Someone else's note.", "user_id": "someone-else", "agent_id": "sage",
                     "metadata": {}, "created_at": "2026-10-06T10:00:00Z", "updated_at": "2026-10-06T10:00:00Z"},
        }
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def _do(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n)) if n else None
                fake.calls.append((self.command, self.path, body))
                fake.key_seen.append(self.headers.get("X-API-Key", ""))
                status, out = fake.route(self.command, self.path, body)
                data = json.dumps(out).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = _do

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def route(self, method, path, body):
        if method == "GET" and path.startswith("/memories?"):
            return 200, {"results": [r for r in self.rows.values() if r["user_id"] == "sam"]}
        if method == "GET" and path.startswith("/memories/"):
            row = self.rows.get(path.split("/")[2])
            return (200, row) if row else (404, {"detail": "not found"})
        if method == "POST" and path == "/search":
            return 200, {"results": [{"id": UUID_A, "memory": "Goes swimming on Fridays.", "score": 0.81}]}
        if method == "POST" and path == "/memories":
            self.rows[UUID_NEW] = {"id": UUID_NEW, "memory": body["messages"][0]["content"], "user_id": body["user_id"],
                                   "agent_id": body["agent_id"], "metadata": body["metadata"],
                                   "created_at": "2026-10-07T09:00:00+01:00", "updated_at": None}
            return 200, {"results": [{"id": UUID_NEW, "memory": body["messages"][0]["content"], "event": "ADD"}]}
        if method == "PUT" and path.startswith("/memories/"):
            row = self.rows[path.split("/")[2]]
            row["memory"], row["updated_at"] = body["text"], "2026-10-07T10:00:00+01:00"
            return 200, {"message": "updated"}
        if method == "DELETE" and path.startswith("/memories/"):
            self.rows.pop(path.split("/")[2], None)
            return 200, {"message": "deleted"}
        return 404, {"detail": "no route"}

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.mem0 = FakeMem0()
        self.addCleanup(self.mem0.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dist = Path(tmp.name) / "dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text("<!doctype html><title>Command Center</title>")
        (self.dist / "assets" / "index-abc.js").write_text("console.log(1)")
        (Path(tmp.name) / "secret.txt").write_text("not for the browser")
        self.app = bridge.App(bridge.Mem0(self.mem0.url, "test-key", "sam"), self.dist, [OWNER])

    def call(self, method, path, body=None, login=OWNER, dash=True, ctype="application/json"):
        headers = {}
        if login:
            headers["tailscale-user-login"] = login
        if dash:
            headers["x-hermes-dash"] = "1"
        if body is not None:
            headers["content-type"] = ctype
        raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        status, hdrs, payload = self.app.handle(method, path, headers, raw)
        try:
            data = json.loads(payload)
        except ValueError:
            data = payload
        return status, hdrs, data

    def mem0_paths(self):
        return [f"{m} {p}" for m, p, _ in self.mem0.calls]

    # access
    def test_no_tailscale_identity_is_refused(self):
        status, _, data = self.call("GET", "/api/health", login=None)
        self.assertEqual(status, 401)
        self.assertIn("Tailscale", data["error"])
        self.assertEqual(self.call("GET", "/", login=None)[0], 401)

    def test_login_not_on_allow_list_is_refused(self):
        self.assertEqual(self.call("GET", "/api/memories", login="someone@else")[0], 403)
        self.assertEqual(self.mem0.calls, [])

    def test_login_match_ignores_case(self):
        self.assertEqual(self.call("GET", "/api/health", login="SAM@Example.com")[0], 200)

    def test_write_without_dashboard_header_is_refused(self):
        status, _, _ = self.call("DELETE", f"/api/memories/{UUID_A}", dash=False)
        self.assertEqual(status, 403)
        self.assertIn(UUID_A, self.mem0.rows)

    def test_write_must_be_json(self):
        status, _, _ = self.call("POST", "/api/memories", b"text=hello", ctype="application/x-www-form-urlencoded")
        self.assertEqual(status, 400)
        self.assertNotIn(UUID_NEW, self.mem0.rows)

    # reads
    def test_health(self):
        status, _, data = self.call("GET", "/api/health")
        self.assertEqual((status, data["ok"]), (200, True))

    def test_list_maps_to_the_page_shape_and_asks_for_all(self):
        status, hdrs, data = self.call("GET", "/api/memories")
        self.assertEqual(status, 200)
        self.assertEqual(hdrs["Cache-Control"], "no-store")
        [m] = data["memories"]
        self.assertEqual(m["id"], UUID_A)
        self.assertEqual(m["text"], "Goes swimming on Fridays.")
        self.assertEqual(m["author"], "rocky")
        self.assertEqual(m["createdAt"], 1791309600000)
        self.assertIsNone(m["updatedAt"])
        self.assertIn("GET /memories?user_id=sam&top_k=1000", self.mem0_paths())
        self.assertEqual(set(self.mem0.key_seen), {"test-key"})

    def test_author_mapping(self):
        self.assertEqual(bridge.memory_out({"id": "x", "agent_id": "holographic-import"})["author"], "import")
        self.assertEqual(bridge.memory_out({"id": "x", "agent_id": "Atlas"})["author"], "atlas")
        self.assertEqual(bridge.memory_out({"id": "x", "agent_id": "dashboard"})["author"], "dashboard")
        self.assertEqual(bridge.memory_out({"id": "x", "agent_id": None})["author"], "unknown")
        self.assertEqual(bridge.memory_out({"id": "x", "agent_id": "claude-code"})["author"], "claude-code")      # tools that share the memory
        self.assertEqual(bridge.memory_out({"id": "x", "agent_id": "claude-cloud"})["author"], "claude-cloud")

    def test_search_filters_to_the_owner(self):
        status, _, data = self.call("POST", "/api/memories/search", {"query": "when is swimming", "top_k": 5})
        self.assertEqual(status, 200)
        self.assertEqual(data["results"], [{"id": UUID_A, "score": 0.81}])
        _, _, sent = self.mem0.calls[-1]
        self.assertEqual(sent, {"query": "when is swimming", "filters": {"user_id": "sam"}, "top_k": 5})

    def test_search_needs_a_query(self):
        self.assertEqual(self.call("POST", "/api/memories/search", {"query": "  "})[0], 400)
        self.assertEqual(self.call("POST", "/api/memories/search", {"query": "x" * 501})[0], 400)

    # writes
    def test_add_is_verbatim_under_the_owner_as_dashboard(self):
        status, _, data = self.call("POST", "/api/memories", {"text": "  Prefers oat milk.  "})
        self.assertEqual(status, 200)
        self.assertEqual(data["memory"]["text"], "Prefers oat milk.")
        self.assertEqual(data["memory"]["author"], "dashboard")
        _, _, sent = next(c for c in self.mem0.calls if c[0] == "POST" and c[1] == "/memories")
        self.assertEqual(sent["infer"], False)
        self.assertEqual(sent["user_id"], "sam")
        self.assertEqual(sent["agent_id"], "dashboard")
        self.assertEqual(sent["metadata"], {"source": "dashboard"})

    def test_add_limits_length(self):
        self.assertEqual(self.call("POST", "/api/memories", {"text": "x" * 2001})[0], 400)
        self.assertEqual(self.call("POST", "/api/memories", {"text": 42})[0], 400)

    def test_update(self):
        status, _, data = self.call("PUT", f"/api/memories/{UUID_A}", {"text": "Goes swimming on Saturdays."})
        self.assertEqual(status, 200)
        self.assertEqual(data["memory"]["text"], "Goes swimming on Saturdays.")
        self.assertIsNotNone(data["memory"]["updatedAt"])

    def test_update_and_delete_refuse_another_users_note(self):
        self.assertEqual(self.call("PUT", f"/api/memories/{UUID_B}", {"text": "changed"})[0], 404)
        self.assertEqual(self.call("DELETE", f"/api/memories/{UUID_B}")[0], 404)
        self.assertEqual(self.mem0.rows[UUID_B]["memory"], "Someone else's note.")
        self.assertNotIn(f"DELETE /memories/{UUID_B}", self.mem0_paths())

    def test_delete(self):
        status, _, data = self.call("DELETE", f"/api/memories/{UUID_A}")
        self.assertEqual((status, data), (200, {"ok": True}))
        self.assertNotIn(UUID_A, self.mem0.rows)

    def test_delete_of_missing_note_says_so(self):
        status, _, data = self.call("DELETE", "/api/memories/12345678-1234-1234-1234-123456789abc")
        self.assertEqual(status, 404)
        self.assertIn("No such memory", data["error"])

    def test_ids_must_be_uuids(self):
        for bad in ("..%2Freset", "reset", "x" * 36, "11111111-2222-3333-4444-55555555555g"):
            self.assertEqual(self.call("DELETE", f"/api/memories/{bad}")[0], 400, bad)

    def test_never_reaches_reset_configure_or_delete_all(self):
        for method, path in (("POST", "/api/reset"), ("POST", "/api/configure"), ("GET", "/api/configure"),
                             ("DELETE", "/api/memories"), ("POST", "/api/memories/reset")):
            self.assertEqual(self.call(method, path, {})[0], 404 if path != "/api/memories/reset" else 400, path)
        self.assertFalse(any("/reset" in p or "/configure" in p or p == "DELETE /memories" for p in self.mem0_paths()))

    def test_mem0_down_is_a_plain_502(self):
        self.app.mem0.base = "http://127.0.0.1:9"
        status, _, data = self.call("GET", "/api/memories")
        self.assertEqual(status, 502)
        self.assertEqual(data["error"], "Mem0 is not answering on the VM")

    # static
    def test_serves_the_page_and_assets(self):
        status, hdrs, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Command Center", body)
        self.assertEqual(hdrs["Cache-Control"], "no-cache")
        status, hdrs, _ = self.call("GET", "/assets/index-abc.js")
        self.assertEqual(status, 200)
        self.assertIn("immutable", hdrs["Cache-Control"])
        self.assertIn("javascript", hdrs["Content-Type"])

    def test_path_traversal_gets_the_page_not_the_file(self):
        for path in ("/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt"):
            status, _, body = self.call("GET", path)
            self.assertEqual(status, 200)
            self.assertNotIn(b"not for the browser", body)

    def test_static_is_read_only(self):
        self.assertEqual(self.call("POST", "/", {})[0], 405)


class HttpTest(unittest.TestCase):
    """The real server: security headers on every answer."""

    def test_headers(self):
        mem0 = FakeMem0()
        self.addCleanup(mem0.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "index.html").write_text("ok")
        server = bridge.make_server(bridge.App(bridge.Mem0(mem0.url, "k", "sam"), Path(tmp.name), [OWNER]), port=0)
        threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/api/health",
                                     headers={"Tailscale-User-Login": OWNER})
        with urllib.request.urlopen(req, timeout=5) as res:
            self.assertEqual(res.status, 200)
            self.assertIn("frame-ancestors 'none'", res.headers["Content-Security-Policy"])
            self.assertEqual(res.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(res.headers["Server"], "hermes-dash")


class EnvTest(unittest.TestCase):
    def test_reads_only_the_named_value(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("POSTGRES_PASSWORD=nope\nexport ADMIN_API_KEY='abc123'\nOPENAI_API_KEY=nope\n")
        self.addCleanup(Path(f.name).unlink)
        self.assertEqual(bridge.read_env_value(Path(f.name), "ADMIN_API_KEY"), "abc123")


if __name__ == "__main__":
    unittest.main()
