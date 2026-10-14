"""Feed tests: fixture SQLite files, a fake /proc, canned systemctl output. Run with the bridge tests."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))      # crewfix
import bridge  # noqa: E402
import feeds  # noqa: E402
from crewfix import write_crew  # noqa: E402

NOW = 1_791_300_000.0          # 2026-10-06 ~11:00 UTC
CONFIG_CHIEF = """\
model:
  default: deepseek-flash
  provider: deepseek
mcp_servers:
  docs:
    url: https://example.invalid
    enabled: true
  moodle:
    command: x
    tools:
      include:
        - get_courses
  maps:
    enabled: false
approvals:
  destructive_slash_confirm: false
"""
CONFIG_COACH = "model:\n  default: deepseek-flash\nmcp_servers:\n  fitness:\n    enabled: true\n  spare:\n    enabled: 'false'\n"


def make_kanban(path: Path) -> None:
    db = sqlite3.connect(path)
    db.execute("pragma journal_mode=wal")
    db.executescript("""
      CREATE TABLE tasks (id TEXT, title TEXT, body TEXT, assignee TEXT, status TEXT, priority INTEGER, created_by TEXT,
                          created_at INTEGER, started_at INTEGER, completed_at INTEGER);
      CREATE TABLE task_runs (id INTEGER PRIMARY KEY, task_id TEXT, summary TEXT);
      CREATE TABLE task_links (parent_id TEXT, child_id TEXT);
      CREATE TABLE task_events (id INTEGER PRIMARY KEY, task_id TEXT, kind TEXT, payload TEXT, created_at INTEGER);
      CREATE TABLE task_comments (id INTEGER PRIMARY KEY, task_id TEXT, author TEXT, body TEXT, created_at INTEGER);
    """)
    rows = [
        ("t_run", "Draft the study plan", "secret body", "tutor", "running", 9, "default", NOW - 3600, NOW - 600, None),
        ("t_blk", "Book the swimming lane", "", "coach", "blocked", 25, "tutor", NOW - 7200, NOW - 7000, None),
        ("t_new", "Grocery list &amp; milk", "", "assistant", "todo", 2, "user", NOW - 100, None, None),
        ("t_done", "Fix the briefing", "", "assistant", "done", 0, "default", NOW - 90000, NOW - 89000, NOW - 80000),
        ("t_old", "Done long ago", "", "assistant", "done", 0, "default", NOW - 40 * 86400, NOW - 40 * 86400, NOW - 39 * 86400),
        ("t_arch", "Archived", "", "assistant", "archived", 0, "default", NOW - 3600, None, None),
        ("t_res", "Look something up", "", "researcher", "todo", 0, "worker", NOW - 50, None, None),
    ]
    db.executemany("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    db.executemany("INSERT INTO task_runs (task_id, summary) VALUES (?,?)", [("t_done", "first"), ("t_done", "Fixed: uses today’s data."), ("t_blk", "")])
    db.execute("INSERT INTO task_links VALUES ('t_run', 't_blk')")
    db.executemany("INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?,?,?,?)", [
        ("t_blk", "coach", f"c{i}", NOW - 600 + i) for i in range(5)] + [("t_blk", "user", "Early &amp; quiet", NOW - 10), ("t_done", "assistant", "x", NOW)])
    db.executemany("INSERT INTO task_events (task_id, kind, created_at) VALUES (?,?,?)", [
        ("t_run", "created", NOW - 3600), ("t_blk", "created", NOW - 7200), ("t_blk", "blocked", NOW - 6000),
        ("t_done", "created", NOW - 90000), ("t_done", "completed", NOW - 80000), ("t_new", "created", NOW - 100),
        ("t_blk", "heartbeat", NOW - 50), ("t_old", "completed", NOW - 39 * 86400),
    ])
    db.executemany("INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?,?,?,?)", [
        ("t_blk", "commented", '{"author": "user", "len": 9}', NOW - 10), ("t_blk", "commented", '{"author": "coach", "len": 4}', NOW - 590)])
    db.commit()
    db.close()


def make_proc(folder: Path) -> None:
    folder.mkdir()
    (folder / "stat").write_text("cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 1 1 1 1\n")
    (folder / "meminfo").write_text("MemTotal:        4000000 kB\nMemFree:          200000 kB\nMemAvailable:    1500000 kB\n")
    (folder / "loadavg").write_text("0.18 0.16 0.12 1/300 4242\n")
    (folder / "uptime").write_text("437000.12 800000.00\n")


SHOW = """MemoryCurrent=756674560
Id=hermes-gateway.service
ActiveState=active
ActiveEnterTimestamp=@1791311401

MemoryCurrent=[not set]
Id=postgresql.service
ActiveState=failed
ActiveEnterTimestamp=@1791249190
"""


def fake_systemctl(*args: str) -> str:
    if args[0] == "show" and "hermes-backup.service" in args:
        return "Result=success\nExecMainExitTimestamp=@1791305267\n"
    if args[0] == "show":
        return SHOW
    if args[0] == "list-timers":
        return json.dumps([{"next": 1791343611742311, "last": 1791257025704731, "unit": "hermes-backup.timer"}])
    return ""


class FeedsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "profiles" / "coach").mkdir(parents=True)
        (root / "config.yaml").write_text(CONFIG_CHIEF)
        (root / "profiles" / "coach" / "config.yaml").write_text(CONFIG_COACH)
        (root / "profiles" / "coach" / "profile.yaml").write_text("description: 'Training and\n  swimming.'\ndescription_auto: false\ndisplay_name: Rocky\n")
        write_crew(root)
        make_kanban(root / "kanban.db")
        make_proc(root / "proc")
        (root / "big").mkdir()
        (root / "big" / "f").write_bytes(b"x" * 5000)
        self.paths = feeds.Paths(hermes_home=str(root), kanban_db=str(root / "kanban.db"), gateway_url="http://127.0.0.1:9",
                                 proc=str(root / "proc"), root=str(root), services=["hermes-gateway", "postgresql", "mem0-server"],
                                 cleanable=[str(root / "big"), str(root / "missing")])
        feeds._du_cache.clear()
        feeds._cpu.last = None

    # config.yaml
    def test_mcp_servers_and_model(self):
        self.assertEqual(feeds.mcp_servers(CONFIG_CHIEF), [
            {"name": "docs", "enabled": True}, {"name": "moodle", "enabled": True}, {"name": "maps", "enabled": False}])
        self.assertEqual(feeds.mcp_servers(CONFIG_COACH), [{"name": "fitness", "enabled": True}, {"name": "spare", "enabled": False}])
        self.assertEqual(feeds.model_default(CONFIG_CHIEF), "deepseek-flash")
        self.assertEqual(feeds.mcp_servers("model:\n  default: x\n"), [])

    # E
    def test_board_cards(self):
        out = feeds.board(self.paths, NOW)
        by = {c["id"]: c for c in out["cards"]}
        self.assertNotIn("t_arch", by)
        self.assertNotIn("t_old", by)                    # done more than 14 days ago
        self.assertEqual(by["t_run"]["assignee"], "sage")             # crew.json: profile tutor is Sage
        self.assertEqual(by["t_run"]["startedAt"], int((NOW - 600) * 1000))
        self.assertEqual(by["t_new"]["createdBy"], "owner")
        self.assertEqual(by["t_new"]["title"], "Grocery list & milk")
        self.assertEqual(by["t_res"]["assignee"], None)
        self.assertEqual(by["t_res"]["assigneeProfile"], "researcher")
        self.assertEqual(by["t_res"]["createdBy"], "helper")
        self.assertEqual(by["t_done"]["summary"], "Fixed: uses today’s data.")   # the latest run's summary
        self.assertIsNone(by["t_blk"]["summary"])
        self.assertEqual(by["t_blk"]["parents"], ["t_run"])
        self.assertEqual([(c["author"], c["body"]) for c in by["t_blk"]["comments"]], [("rocky", "c2"), ("rocky", "c3"), ("rocky", "c4"), ("owner", "Early & quiet")])
        self.assertEqual(by["t_done"]["comments"], [])
        self.assertNotIn("body", by["t_run"])
        self.assertNotIn("runs", out)                    # no coding-job log in the generic kit

    # B
    def test_agents(self):
        out = feeds.agents(self.paths, NOW)
        self.assertEqual(out["gateway"], {"ok": False, "version": None})
        by = {a["id"]: a for a in out["agents"]}
        self.assertEqual(list(by), ["atlas", "rocky"])    # the profiles that exist: the chief's home and profiles/coach
        self.assertEqual(by["atlas"]["name"], "Atlas")    # no profile.yaml: the name comes from crew.json
        self.assertEqual([m["name"] for m in by["atlas"]["mcp"]], ["docs", "moodle", "maps"])
        self.assertEqual((by["rocky"]["blocked"], by["rocky"]["name"], by["rocky"]["core"]), (1, "Rocky", True))
        self.assertEqual(by["rocky"]["description"], "Training and swimming.")
        kinds = {(h["cardId"], h["kind"], h["from"], h["to"]) for h in out["handoffs"]}
        self.assertIn(("t_blk", "assign", "sage", "rocky"), kinds)            # a team lead handed it down...
        self.assertIn(("t_blk", "question", "rocky", "sage"), kinds)          # ...so the question goes back to them
        self.assertIn(("t_done", "done", "ivy", "atlas"), kinds)
        self.assertIn(("t_new", "assign", "owner", "ivy"), kinds)
        self.assertIn(("t_run", "assign", "atlas", "sage"), kinds)
        self.assertFalse(any(h["cardId"] == "t_old" for h in out["handoffs"]))
        self.assertIn(("t_blk", "message", "owner", "rocky"), kinds)          # the owner answered on the card
        self.assertIn(("t_blk", "message", "rocky", "sage"), kinds)           # the worker's comment goes back to its lead
        # right now: Sage is working on Atlas's card, Rocky waits on Sage for an answer; nothing else is live
        self.assertEqual({(t["cardId"], t["state"], t["from"], t["to"]) for t in out["talks"]},
                         {("t_run", "working", "atlas", "sage"), ("t_blk", "asking", "rocky", "sage")})

    # C
    def test_infra(self):
        with mock.patch.object(feeds, "_systemctl", fake_systemctl):
            out = feeds.infra(self.paths, NOW)
        vm = out["vm"]
        self.assertEqual(vm["memTotal"], 4_000_000 * 1024)
        self.assertEqual(vm["memUsed"], 2_500_000 * 1024)
        self.assertEqual(vm["load"], [0.18, 0.16, 0.12])
        self.assertEqual(vm["uptimeSecs"], 437000)
        self.assertGreater(vm["diskTotal"], 0)
        svc = {s["unit"]: s for s in out["services"]}
        self.assertEqual((svc["hermes-gateway"]["state"], svc["hermes-gateway"]["since"], svc["hermes-gateway"]["memBytes"]),
                         ("active", 1791311401000, 756674560))
        self.assertEqual((svc["postgresql"]["state"], svc["postgresql"]["since"], svc["postgresql"]["memBytes"]), ("failed", None, None))
        self.assertEqual(svc["mem0-server"]["state"], "unknown")
        self.assertEqual(out["backup"], {"lastRunAt": 1791305267000, "ok": True, "nextRunAt": 1791343611742})
        self.assertEqual(out["credit"]["balance"], 100.0)
        sizes = {Path(c["path"]).name: c["bytes"] for c in out["cleanable"]}
        self.assertGreaterEqual(sizes["big"], 5000)
        self.assertIsNone(sizes["missing"])

    def test_no_card_body_or_server_address_leaves(self):
        with mock.patch.object(feeds, "_systemctl", fake_systemctl):
            text = json.dumps([feeds.agents(self.paths, NOW), feeds.board(self.paths, NOW), feeds.infra(self.paths, NOW)])
        for leak in ("secret body", "example.invalid"):
            self.assertNotIn(leak, text, leak)

    def test_missing_files_are_empty_not_errors(self):
        empty = feeds.Paths(hermes_home="/nonexistent", kanban_db="/nonexistent/k.db", gateway_url="http://127.0.0.1:9")
        self.assertEqual(feeds.board(empty, NOW)["cards"], [])
        self.assertEqual([a["id"] for a in feeds.agents(empty, NOW)["agents"]], ["chief"])   # no crew.json: the plain fallback

    def test_bridge_routes(self):
        app = bridge.App(bridge.Mem0("http://127.0.0.1:9", "k", "sam"), Path(self.paths.hermes_home), ["sam@x"], self.paths)
        with mock.patch.object(feeds, "_systemctl", fake_systemctl):
            for route in ("/api/agents", "/api/infra", "/api/board"):
                status, _, body = app.handle("GET", route, {"tailscale-user-login": "sam@x"}, b"")
                self.assertEqual(status, 200, route)
                self.assertIn('"at"', body.decode())
        self.assertEqual(app.handle("GET", "/api/board", {}, b"")[0], 401)
        for gone in ("/api/voice", "/api/video/library", "/api/contacts"):
            self.assertEqual(app.handle("GET", gone, {"tailscale-user-login": "sam@x"}, b"")[0], 404, gone)

    def test_a_failing_feed_says_which(self):
        app = bridge.App(bridge.Mem0("http://127.0.0.1:9", "k", "sam"), Path(self.paths.hermes_home), ["sam@x"], self.paths)
        with mock.patch.dict(bridge.FEEDS, {"/infra": mock.Mock(side_effect=PermissionError("/data/x"))}):
            status, _, body = app.handle("GET", "/api/infra", {"tailscale-user-login": "sam@x"}, b"")
        self.assertEqual(status, 502)
        self.assertIn("Could not read infra", json.loads(body)["error"])
        self.assertNotIn("/data/x", body.decode())


if __name__ == "__main__":
    unittest.main()
