import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from desk import brief, config, db, tickets  # noqa: E402
from helpers import FakeClock  # noqa: E402

CALENDAR = """- Thu 08 Oct 10:00-11:00: Operations Management lecture LC01 @ Boyd Orr:G12 Room 1  [abc]
- Thu 08 Oct 12:00-17:00: Work (Waterstones)  [def]
- Thu 08 Oct 08:00-08:15: Morning priming [x1]
  @ home
- Fri 09 Oct 15:00: Quiz B due [ghi]
"""
KANBAN = """✓ t_3d1a6182  done      tutor                 {{OWNER}}: reassurance + tonight's plan
● t_aaaa1111  running   coach                 Phone line: rebuild the desk
✓ t_bbbb2222  done      coach                 Voice notes: old gate fix
! t_cccc3333  blocked   assistant             Book the dentist
"""


class ParserTest(unittest.TestCase):
    def test_calendar_is_grouped_by_day_without_routine_blocks_or_codes(self):
        days = brief.by_day(brief.parse_calendar(CALENDAR))
        self.assertEqual(list(days), ["Thu 08 Oct", "Fri 09 Oct"])
        self.assertEqual(days["Thu 08 Oct"], ["10:00-11:00: Operations Management lecture @ Boyd Orr", "12:00-17:00: Work (Waterstones)"])
        everything = brief.by_day(brief.parse_calendar(CALENDAR), routine=True)
        self.assertEqual(len(everything["Thu 08 Oct"]), 3)

    def test_tasks_only_open_items(self):
        text = "- [x] done thing\n- [ ] Lab B marking | due Thu\n- [ ] Book dentist\nnotes"
        self.assertEqual(brief.parse_tasks(text), ["Lab B marking", "Book dentist"])

    def test_board_lists_live_cards_first_and_names_the_agents(self):
        lines = brief.parse_board(KANBAN, done_limit=1)
        self.assertEqual(lines[0], "{{COACH}}: running: Phone line: rebuild the desk")
        self.assertEqual(lines[1], "{{ASSISTANT}}: blocked: Book the dentist")
        self.assertEqual(lines[2], "{{TUTOR}}: done: {{OWNER}}: reassurance + tonight's plan")
        self.assertEqual(len(lines), 3)

    def test_recent_chat_is_oldest_first_scrubbed_and_skips_board_pings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.db"
            conn = sqlite3.connect(path)
            conn.executescript("create table sessions(id integer primary key, chat_id text);"
                               "create table messages(id integer primary key, session_id integer, role text, content text, timestamp real);")
            conn.execute("insert into sessions values (1, '42'), (2, '99')")
            rows = [(1, "user", "what is on tomorrow", 1), (1, "assistant", "Nothing booked, {{sir}}. key=abc123", 2),
                    (1, "user", "[kanban] Task t_1 completed", 3), (2, "user", "someone else", 4)]
            conn.executemany("insert into messages(session_id, role, content, timestamp) values (?,?,?,?)", rows)
            conn.commit()
            conn.close()
            out = brief.recent_chat(str(path), "42")
            self.assertEqual(out, ["{{OWNER}}: what is on tomorrow", "{{CHIEF}}: Nothing booked, {{sir}}. key=[redacted]"])
            self.assertEqual(brief.recent_chat(str(path), ""), [])
            self.assertEqual(brief.recent_chat(str(Path(tmp) / "missing.db"), "42"), [])


class BriefTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name)
        (home / "owner").mkdir()
        (home / "owner" / "tasks.md").write_text("- [ ] Lab B marking | due Thu\n")
        os.utime(home / "owner" / "tasks.md", (1_791_190_000.0, 1_791_190_000.0))      # file ages are measured against the fake clock
        (home / "moodle-cli").write_text("")
        (home / "tutor.env").write_text("MOODLE_TOKEN=cookie123\n")
        self.cfg = config.Config(hermes_home=str(home), state_dir=str(home / "state"), telegram_chat_id="42",
                                 moodle_cli=str(home / "moodle-cli"), moodle_url="https://moodle.example", moodle_env=str(home / "tutor.env"))
        self.clock = FakeClock(now=1_791_190_000.0)       # 5 Oct 2026, mid morning UK
        self.db = db.DB(":memory:")
        self.addCleanup(self.db.close)
        self.tickets = tickets.Tickets(self.db, self.clock)
        self.calls = []

        def run(cmd, timeout=25, env=None):
            self.calls.append(cmd)
            if "agenda" in cmd:
                return CALENDAR
            if "kanban" in cmd:
                return KANBAN
            if "due" in cmd:
                self.moodle_env = env
                return json.dumps({"due": [{"name": "Quiz B", "due_at": 1_791_450_000}]})
            return ""
        self.brief = brief.Brief(self.cfg, self.clock, run=run, tickets=self.tickets,
                                 minutes_text=lambda: "MINUTES: 20 of 270 used.")

    def test_before_the_first_refresh_it_says_the_calendar_is_missing(self):
        text = self.brief.render()
        self.assertIn("CALENDAR: not loaded yet", text)
        self.assertIn("MINUTES: 20 of 270 used.", text)

    def test_render_has_every_section_with_ages(self):
        self.brief.refresh_all()
        self.tickets.open("ask", "assistant", "check the marking scheme")
        text = self.brief.render()
        self.assertIn("Now: Monday 05 October 2026", text)
        self.assertIn("CALENDAR, next 10 days", text)
        self.assertIn("Thu 08 Oct: 10:00-11:00: Operations Management lecture @ Boyd Orr; 12:00-17:00: Work (Waterstones)", text)
        self.assertIn("- Lab B marking", text)
        self.assertIn("MOODLE DEADLINES", text)
        self.assertIn("Quiz B", text)
        self.assertEqual(self.moodle_env["MOODLE_TOKEN"], "cookie123")          # the cookie is read from the tutor's .env
        self.assertIn("- {{COACH}}: running: Phone line: rebuild the desk", text)
        self.assertIn("{{ASSISTANT}} is working on: check the marking scheme", text)
        self.assertIn("updated just now", text)
        self.assertNotIn("STALE", text)

    def test_old_data_is_marked_stale(self):
        self.brief.refresh_all()
        self.clock.now += 3600
        text = self.brief.render()
        self.assertIn("STALE - say so if you rely on it", text)

    def test_a_failing_source_keeps_the_last_good_calendar(self):
        self.brief.refresh_all()
        self.brief.run = lambda cmd, timeout=25, env=None: ""
        self.brief.refresh_all()
        self.assertIn("Operations Management", self.brief.render())

    def test_the_brief_never_exceeds_its_budget_and_keeps_the_important_blocks(self):
        self.brief.refresh_all()
        self.brief.data["chat"] = {"value": ["{{OWNER}}: " + "x" * 150] * 6 + ["y" * 5000], "at": self.clock.now, "file": None}
        self.brief.data["deadlines"] = {"value": "d" * 900, "at": self.clock.now, "file": None}
        self.brief.data["tasks"] = {"value": ["t" * 100] * 12, "at": self.clock.now, "file": None}
        text = self.brief.render()
        self.assertLessEqual(len(text), brief.MAX_CHARS)
        self.assertIn("THE TASK BOARD", text)
        self.assertIn("MINUTES:", text)

    def test_secrets_never_reach_the_brief(self):
        self.brief.refresh_all()
        self.brief.data["chat"] = {"value": ["{{OWNER}}: my token=hunter2 is here"], "at": self.clock.now, "file": None}
        self.assertNotIn("hunter2", self.brief.render())


if __name__ == "__main__":
    unittest.main()


class MoodleDueTest(unittest.TestCase):
    def test_the_moodle_tools_json_becomes_short_lines_soonest_first(self):
        text = json.dumps({"due": [
            {"name": "B &amp; C - Quiz", "due_at": 1793118600, "unit_code": "X"},
            {"name": "A - Essay", "due_at": 1792510200, "unit_code": "Y"},
            {"name": "no date", "due_at": 0}]})
        self.assertEqual(brief.parse_moodle_due(text),
                         "Tue 20 Oct 16:30  A - Essay\nTue 27 Oct 16:30  B & C - Quiz")
        for bad in ("", "not json", "[]", json.dumps({"due": None})):
            self.assertEqual(brief.parse_moodle_due(bad), "")
