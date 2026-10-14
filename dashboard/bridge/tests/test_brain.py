"""Brain sections, settings and balances, memory tidying and sorting, automations. Fixture home + fake CLI; no network."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import actions  # noqa: E402
import automations  # noqa: E402
import brain  # noqa: E402
import jobs  # noqa: E402
import settings  # noqa: E402
import test_actions as fixture  # noqa: E402  (the module, so its tests are not collected twice)
from crewfix import write_crew  # noqa: E402

JOBS = {"jobs": [
    {"id": "cd1678c688ca", "name": "Eye ointment", "schedule": {"kind": "cron", "expr": "45 7 * * *", "display": "every day at 7:45am"},
     "schedule_display": "every day at 7:45am", "repeat": {"times": 6, "completed": 3}, "enabled": True, "state": "scheduled",
     "next_run_at": "2026-10-07T07:45:00+01:00", "last_run_at": "2026-10-06T07:45:33+01:00", "last_status": "ok",
     "deliver": "origin", "prompt": "Remind Sam: ointment. Ring 07700 900123 if they forget.", "no_agent": False},
    {"id": "0a1b2c3d4e5f", "name": "Lab due-day reminder", "schedule": {"kind": "once", "display": "once"}, "repeat": {"times": 1, "completed": 1},
     "enabled": False, "state": "completed", "prompt": "Lab due today."},
]}


class BrainTest(fixture.ActionsTest):
    locals().update({n: None for n in dir(fixture.ActionsTest) if n.startswith("test_")})

    def setUp(self):
        super().setUp()
        cron = self.home / "profiles" / "coach" / "cron"
        cron.mkdir()
        (cron / "jobs.json").write_text(json.dumps(JOBS))

    # sections
    def test_sort_answer_with_a_new_section(self):
        notes = [{"id": f"id-{i:08d}", "text": t} for i, t in enumerate(["Swimming Tuesday", "Saving for a car", "Car insurance due May", "Odd note"])]
        out = brain.apply_sort(self.env, notes, {"assign": {"id-00000000": "fitness", "id-00000001": "Money & savings",
                                                            "id-00000002": "money & savings", "id-99999999": "uni", "id-00000003": 7},
                                                 "new": [{"label": "Money & savings", "blurb": "Budget, saving, insurance"}]})
        data = brain.load(self.env)
        self.assertEqual(out["new"], ["money-savings"])
        self.assertEqual({k: data["assign"][k] for k in ("id-00000000", "id-00000001", "id-00000002")},
                         {"id-00000000": "fitness", "id-00000001": "money-savings", "id-00000002": "money-savings"})
        self.assertEqual(data["assign"]["id-00000003"], "rules")          # the one it skipped goes to the catch-all
        self.assertNotIn("id-99999999", data["assign"])                     # not in the batch: ignored
        self.assertEqual(len(data["sections"]), 9)                          # the eight built in + the new one
        self.assertIn("health", {x["id"] for x in data["sections"]})
        view = brain.view(self.env, ["id-00000000", "id-00000001", "id-00000002", "id-00000003", "id-new-0001"])
        self.assertEqual(view["unsorted"], 1)
        # merging a made-up section back removes it and moves its notes
        brain.merge(self.env, "money-savings", "admin")
        data = brain.load(self.env)
        self.assertEqual(data["assign"]["id-00000001"], "admin")
        self.assertNotIn("money-savings", {s["id"] for s in data["sections"]})
        brain.rename(self.env, "admin", {"label": "Life admin", "blurb": "Bills, calendar"})
        self.assertEqual(next(s for s in brain.load(self.env)["sections"] if s["id"] == "admin")["label"], "Life admin")
        brain.resort(self.env)
        self.assertEqual(brain.load(self.env)["assign"], {})

    def test_assign_on_add_and_forget(self):
        sid = brain.assign(self.env, "mem-00000001", new_label="Car")
        self.assertEqual(sid, "car")
        brain.assign(self.env, "mem-00000004", new_label="health-eye")
        self.assertIn("Health eye", [x["label"] for x in brain.load(self.env)["sections"]])     # an id-like name reads like the rest
        self.assertEqual(brain.assign(self.env, "mem-00000002", new_label="car"), "car")     # same label: same section
        brain.forget(self.env, "mem-00000001")
        self.assertNotIn("mem-00000001", brain.load(self.env)["assign"])
        with self.assertRaises(actions.ActionError):
            brain.assign(self.env, "mem-00000003", section="nope")

    def test_tidy_and_sort_jobs(self):
        def llm(env_file, system, user, max_tokens, **kw):
            self.assertTrue(kw.get("json_mode"))
            if "Sam's note" in user:
                self.assertIn("third person ('Sam ...')", system)
                return '```json\n{"text": "Sam swims on Tuesdays at 6.", "section": "fitness"}\n```'
            self.assertIn("never the assistants (Atlas, Sage, Ivy, Rocky)", system)
            return json.dumps({"assign": {"id-00000001": "Travel plans"}, "new": [{"label": "Travel plans", "blurb": "Trips"}]})
        out = jobs.do_memory_tidy(self.env, {"text": "swim tuesdays 6pm"}, llm)
        self.assertEqual((out["text"], out["section"], out["new"]), ("Sam swims on Tuesdays at 6.", "fitness", None))
        out = jobs.do_brain_sort(self.env, {"notes": [{"id": "id-00000001", "text": "Flight to Rome in May"}]}, llm)
        self.assertEqual(out["new"], ["travel-plans"])
        with self.assertRaises(actions.ActionError):
            jobs.submit(self.env, "brain-sort", {"notes": [{"id": "../x", "text": "y"}]})

    # settings and balances
    def test_settings(self):
        self.assertEqual(settings.view(self.env)["model"], "deepseek-flash")
        with self.assertRaises(actions.ActionError):
            settings.save(self.env, {"model": "deepseek-flash"})              # no DeepSeek key in the fixture .env
        (self.home / ".env").write_text("API_SERVER_KEY=chief-key\nDEEPSEEK_API_KEY=k\nGEMINI_API_KEY=g\n")
        out = settings.save(self.env, {"model": "gemini-2.5-flash", "tidyMemories": False})
        self.assertEqual((out["model"], out["tidyMemories"]), ("gemini-2.5-flash", False))
        self.assertTrue(all(m["available"] for m in out["models"]))
        self.assertNotIn("g", json.dumps([m for m in out["models"]]).split('"'))  # key values never in the answer
        with self.assertRaises(actions.ActionError):
            settings.save(self.env, {"model": "gpt-9"})
        settings.save(self.env, {"credit": {"balance": 80.5, "as_of": "2026-10-20"}})
        self.assertEqual(settings.load(self.env)["credit"]["balance"], 80.5)
        with self.assertRaises(actions.ActionError):
            settings.save(self.env, {"credit": {"balance": 80, "as_of": "20 Oct"}})

    def test_balances_job(self):
        def get(url, headers):
            if "deepseek" in url:
                return {"is_available": True, "balance_infos": [{"currency": "USD", "total_balance": "14.48"}]}
            raise OSError("down")
        (self.home / ".env").write_text("DEEPSEEK_API_KEY=k\nELEVENLABS_API_KEY=e\n")
        out = jobs.do_balances(self.env, {}, get)
        self.assertEqual(out["deepseek"], {"balance": 14.48, "currency": "USD", "ok": True})
        self.assertNotIn("elevenlabs", out)                                   # the voice add-on is off
        self.assertNotIn("twilio", out)
        write_crew(self.home, voice=True)
        out = jobs.do_balances(self.env, {}, get)
        self.assertIn("error", out["elevenlabs"])                             # one failing does not stop the others
        self.assertEqual(out["deepseek"]["balance"], 14.48)
        self.assertEqual(settings.cached_balances(self.env)["deepseek"]["balance"], 14.48)
        self.assertFalse(settings.balances_stale(self.env))

    # automations
    def test_automations(self):
        out = automations.list_all(self.env)["jobs"]
        self.assertEqual([x["state"] for x in out], ["scheduled", "completed"])    # a fired one-off is finished, not paused
        j = out[0]
        self.assertEqual((j["profile"], j["schedule"], j["state"], j["repeat"]), ("coach", "every day at 7:45am", "scheduled", {"times": 6, "done": 3}))
        self.assertNotIn("900123", j["prompt"])                               # numbers scrubbed
        out = automations.act(self.env, "coach", "cd1678c688ca", "pause")["jobs"]
        self.assertEqual(out[0]["state"], "paused")
        self.assertEqual([c["args"] for c in self.cli_calls()][-1], ["-p", "coach", "cron", "pause", "--", "cd1678c688ca"])
        automations.act(self.env, "coach", "cd1678c688ca", "resume")
        out = automations.edit(self.env, "coach", "cd1678c688ca", {"name": "Eye drops", "schedule": "0 8 * * *"})["jobs"]
        self.assertEqual((out[0]["name"], out[0]["expr"]), ("Eye drops", "0 8 * * *"))
        out = automations.create(self.env, {"profile": "atlas", "schedule": "every 2h", "prompt": "Check the board.", "name": "Board sweep"})["jobs"]
        self.assertEqual([(x["profile"], x["name"]) for x in out if x["profile"] == "default"], [("default", "Board sweep")])
        self.assertEqual([c["args"] for c in self.cli_calls()][-1][:3], ["cron", "create", "--deliver=telegram"])
        automations.remove(self.env, "coach", "cd1678c688ca")
        self.assertEqual(sorted(x["profile"] for x in automations.list_all(self.env)["jobs"]), ["coach", "default"])
        for bad in [lambda: automations.act(self.env, "coach", "nothere00000", "run"),
                    lambda: automations.act(self.env, "coach", "../../x", "run"),
                    lambda: automations.create(self.env, {"profile": "coach", "schedule": "$(rm -rf /)", "prompt": "x"}),
                    lambda: automations.create(self.env, {"profile": "coach", "schedule": "1h", "prompt": "x", "deliver": "email:x"}),
                    lambda: automations.create(self.env, {"profile": "coach", "schedule": "1h", "prompt": "x", "deliver": "signal"})]:
            with self.assertRaises(actions.ActionError):
                bad()


if __name__ == "__main__":
    unittest.main()
