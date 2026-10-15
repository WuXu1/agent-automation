import json, os, sys, tempfile, threading, unittest, http.client
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import remote_http as rh  # noqa: E402

TOKEN = "t" * 64


class Remote(unittest.TestCase):
    def setUp(self):
        rh.Handler.token = TOKEN
        self.srv = rh.ThreadingHTTPServer(("127.0.0.1", 0), rh.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.srv.shutdown(), self.srv.server_close()))
        self.sleep = mock.patch.object(rh.time, "sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def post(self, path, body):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        c.request("POST", path, body=json.dumps(body) if not isinstance(body, bytes) else body, headers={"Content-Type": "application/json"})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, (json.loads(data) if data else None)

    def test_the_link_is_the_password(self):
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        for bad in ("/mcp/wrong", "/mcp/", "/", "/brain/mcp/" + "x" * 64, "/mcp/" + TOKEN + "a"):
            self.assertEqual(self.post(bad, ping)[0], 404, bad)
        self.assertEqual(self.post("/mcp/" + TOKEN, ping), (200, {"jsonrpc": "2.0", "id": 1, "result": {}}))
        self.assertEqual(self.post("/brain/mcp/" + TOKEN, ping)[0], 200)

    def test_tools_have_no_delete_and_initialize_works(self):
        code, out = self.post("/mcp/" + TOKEN, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(sorted(t["name"] for t in out["result"]["tools"]), ["mem0_add", "mem0_search", "mem0_update"])
        code, out = self.post("/mcp/" + TOKEN, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "mem0_delete", "arguments": {"memory_id": "x"}}})
        self.assertTrue(out["result"]["isError"])
        code, out = self.post("/mcp/" + TOKEN, {"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
        self.assertEqual((out["result"]["protocolVersion"], out["result"]["serverInfo"]["name"]), ("2025-03-26", "second-brain"))

    def test_a_search_reaches_mem0_as_max(self):
        seen = {}

        def fake(method, path, payload=None):
            seen.update(method=method, path=path, payload=payload)
            return True, {"results": [{"id": "m1", "memory": "Max likes tea", "score": 0.9}]}
        with mock.patch.object(rh.core, "call", fake):
            code, out = self.post("/mcp/" + TOKEN, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "mem0_search", "arguments": {"query": "tea"}}})
        self.assertIn("Max likes tea", out["result"]["content"][0]["text"])
        self.assertEqual((seen["path"], seen["payload"]["filters"]), ("/search", {"user_id": rh.core.USER_ID}))

    def test_notifications_get_202_and_bad_bodies_are_refused(self):
        self.assertEqual(self.post("/mcp/" + TOKEN, {"jsonrpc": "2.0", "method": "notifications/initialized"})[0], 202)
        self.assertEqual(self.post("/mcp/" + TOKEN, b"not json")[0], 400)
        self.assertEqual(self.post("/mcp/" + TOKEN, b"x" * (rh.MAX_BODY + 1))[0], 413)

    def test_no_token_file_means_no_server(self):
        with mock.patch.object(rh, "TOKEN_FILE", Path(tempfile.gettempdir()) / "nope-token"):
            self.assertEqual(rh.main(), 1)


if __name__ == "__main__":
    unittest.main()
