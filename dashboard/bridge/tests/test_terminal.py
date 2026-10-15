"""Agent Studio's terminal window (bridge/terminal.py): one agent's run as terminal lines, read only, with secrets blanked.
Run: python3 -m unittest discover -s dashboard/bridge/tests"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))      # hermesfix
import bridge  # noqa: E402
import feeds  # noqa: E402
import terminal  # noqa: E402
from hermesfix import LOGIN, write_setup  # noqa: E402

SCHEMA = """
CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT, model TEXT, started_at REAL NOT NULL, ended_at REAL, end_reason TEXT,
                       message_count INTEGER DEFAULT 0, tool_call_count INTEGER DEFAULT 0, last_activity_at REAL, hidden INTEGER NOT NULL DEFAULT 0);
CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT, tool_call_id TEXT, tool_calls TEXT,
                       tool_name TEXT, timestamp REAL NOT NULL);
"""


def call(cid, name, **args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class TerminalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "hermes"
        (self.home / "profiles" / "tutor").mkdir(parents=True)
        write_setup(self.home)
        self.db = self.home / "profiles" / "tutor" / "state.db"
        self.now = time.time()
        con = sqlite3.connect(self.db)
        con.executescript(SCHEMA)
        t = self.now - 30
        con.execute("INSERT INTO sessions VALUES ('old', 'cli', 'Yesterday', 'deepseek-flash', ?, ?, 'done', 3, 1, ?, 0)", (t - 86400, t - 86000, t - 86000))
        con.execute("INSERT INTO sessions VALUES ('s1', 'cli', 'Check every note', 'deepseek-flash', ?, NULL, NULL, 6, 3, ?, 0)", (t, t + 20))
        rows = [
            ("old", "user", "an old task", None, None, None, t - 86400),
            ("s1", "user", "work kanban task t_1", None, None, None, t),
            ("s1", "assistant", "", None, json.dumps([call("c1", "terminal", command="/data/tools/notes/notes check --dir /data/notes/site")]), None, t + 2),
            ("s1", "tool", json.dumps({"output": "\n".join(f"line {i}" for i in range(40)) + "\nNOTES_API_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz1234", "exit_code": 0}),
             "c1", None, "terminal", t + 3),
            ("s1", "assistant", "", None, json.dumps([call("c2", "read_file", path="/data/notes/state/last_check.json"),
                                                     call("c3", "kanban_complete", summary='{"status":"ok"}')]), None, t + 5),
            ("s1", "tool", json.dumps({"content": "1|{\"status\": \"ok\"}"}), "c2", None, "read_file", t + 6),
            ("s1", "assistant", "Done. Ring Sam on +44 7700 900123 if it breaks.", None, None, None, t + 20),
        ]
        con.executemany("INSERT INTO messages (session_id, role, content, tool_call_id, tool_calls, tool_name, timestamp) VALUES (?,?,?,?,?,?,?)",
                        [(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows])
        con.commit()
        con.close()
        self.paths = feeds.Paths(hermes_home=str(self.home), kanban_db=str(self.home / "none.db"))

    def test_a_run_as_terminal_lines(self):
        v = terminal.view(self.paths, "tutor", now=self.now)
        self.assertEqual(v["session"]["id"], "s1")                          # the newest run first
        self.assertEqual([s["id"] for s in v["sessions"]], ["s1", "old"])
        kinds = [s["kind"] for s in v["steps"]]
        self.assertEqual(kinds, ["in", "cmd", "out", "read", "board", "out", "say"])
        cmd = v["steps"][1]
        self.assertEqual(cmd["text"], "/data/tools/notes/notes check --dir /data/notes/site")
        out = v["steps"][2]
        self.assertEqual((out["callId"], out["exit"], out["more"]), ("c1", 0, True))
        self.assertEqual(len(out["text"].split("\n")), terminal.OUTPUT_LINES)     # long output is cut to its first lines
        self.assertTrue(v["live"])                                               # a step in the last 90 s

    def test_secrets_and_phone_numbers_never_leave(self):
        con = sqlite3.connect(self.db)
        con.execute("UPDATE messages SET content = ? WHERE tool_name = 'terminal'", (json.dumps({"output": "NOTES_API_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz1234", "exit_code": 0}),))
        con.commit()
        con.close()
        text = json.dumps(terminal.view(self.paths, "tutor", now=self.now), ensure_ascii=False)
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz1234", text)
        self.assertIn("NOTES_API_TOKEN=", text)                          # the name stays readable
        self.assertNotIn("900123", text)
        self.assertIn("•••• 123", text)

    def test_only_new_steps_after_a_cursor_and_older_runs(self):
        v = terminal.view(self.paths, "tutor", now=self.now)
        again = terminal.view(self.paths, "tutor", "s1", v["cursor"], now=self.now)
        self.assertEqual((again["steps"], again["cursor"]), ([], v["cursor"]))
        old = terminal.view(self.paths, "tutor", "old", now=self.now)
        self.assertEqual(([s["text"] for s in old["steps"]], old["live"]), (["an old task"], False))
        quiet = terminal.view(self.paths, "tutor", now=self.now + 3600)
        self.assertFalse(quiet["live"])

    def test_the_file_is_never_changed(self):
        before = self.db.read_bytes()
        terminal.view(self.paths, "tutor", now=self.now)
        self.assertEqual(self.db.read_bytes(), before)

    def test_through_the_bridge(self):
        dist = Path(tempfile.mkdtemp())
        (dist / "index.html").write_text("x")
        app = bridge.App(bridge.Mem0("http://127.0.0.1:1", "k", "sam"), dist, [LOGIN], self.paths)
        h = {"tailscale-user-login": LOGIN}
        status, _, body = app.handle("GET", "/api/agents/tutor/terminal", h, b"")
        self.assertEqual((status, json.loads(body)["session"]["id"]), (200, "s1"))
        status, _, body = app.handle("GET", "/api/agents/tutor/terminal?session=old&after=0", h, b"")
        self.assertEqual(json.loads(body)["session"]["id"], "old")
        self.assertEqual(app.handle("GET", "/api/agents/nobody/terminal", h, b"")[0], 404)
        self.assertEqual(app.handle("GET", "/api/agents/tutor/terminal?session=../../x", h, b"")[0], 400)
        status, _, body = app.handle("GET", "/api/agents/sage/terminal", h, b"")           # the team id works too (sage = tutor)
        self.assertEqual((status, json.loads(body)["profile"]), (200, "tutor"))
        status, _, body = app.handle("GET", "/api/agents/atlas/terminal", h, b"")          # the chief's database does not exist here: empty, not an error
        self.assertEqual((status, json.loads(body)["steps"], json.loads(body)["profile"]), (200, [], "default"))


if __name__ == "__main__":
    unittest.main()
