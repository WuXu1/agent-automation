import datetime as dt
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from desk import config, db, security, util  # noqa: E402


class FakeClock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def uk(year, month, day, hour, minute=0):
    return dt.datetime(year, month, day, hour, minute, tzinfo=util.UK).timestamp()


class UtilTest(unittest.TestCase):
    def test_quiet_hours_are_23_to_07_uk_time_in_winter_and_summer(self):
        self.assertTrue(util.is_quiet(uk(2026, 1, 15, 23, 0)))
        self.assertTrue(util.is_quiet(uk(2026, 1, 15, 6, 59)))
        self.assertFalse(util.is_quiet(uk(2026, 1, 15, 7, 0)))
        self.assertFalse(util.is_quiet(uk(2026, 7, 15, 22, 59)))
        self.assertTrue(util.is_quiet(uk(2026, 7, 15, 23, 30)))   # BST: UTC is an hour behind

    def test_next_wake_is_the_following_seven(self):
        self.assertEqual(util.next_wake(uk(2026, 10, 5, 23, 30)), uk(2026, 10, 6, 7))
        self.assertEqual(util.next_wake(uk(2026, 10, 6, 3, 0)), uk(2026, 10, 6, 7))
        self.assertEqual(util.next_wake(uk(2026, 10, 6, 12, 0)), uk(2026, 10, 6, 12, 0))

    def test_greeting_by_hour(self):
        self.assertEqual(util.greeting(uk(2026, 10, 5, 9)), "Good morning")
        self.assertEqual(util.greeting(uk(2026, 10, 5, 14)), "Good afternoon")
        self.assertEqual(util.greeting(uk(2026, 10, 5, 20)), "Good evening")
        self.assertEqual(util.greeting(uk(2026, 10, 5, 2)), "Good evening")

    def test_age_words(self):
        self.assertEqual(util.age_words(30), "just now")
        self.assertEqual(util.age_words(600), "10 min ago")
        self.assertEqual(util.age_words(3 * 3600), "3 h ago")
        self.assertEqual(util.age_words(4 * 86400), "4 days ago")
        self.assertEqual(util.age_words(None), "unknown age")

    def test_numbers_compare_across_formats(self):
        a = util.normalise_number("07700 900123")
        self.assertEqual(a, util.normalise_number("+44 7700 900123"))
        self.assertEqual(a, util.normalise_number("0044-7700-900123"))
        self.assertNotEqual(a, util.normalise_number("07700 900124"))

    def test_scrub_hides_credentials(self):
        text = util.scrub("key sk-abcdefghijklmnop1234 and token=abc123 and " + "a" * 40)
        self.assertNotIn("abcdefghijklmnop1234", text)
        self.assertNotIn("abc123", text)
        self.assertNotIn("a" * 40, text)

    def test_clean_for_speech_removes_markdown_urls_paths_and_tags(self):
        raw = "**Done**, {{sir}}. See `notes` at /data/x/y.md or https://a.b/c\n- item\nMEDIA:/tmp/a.ogg [[audio_as_voice]]"
        self.assertEqual(util.clean_for_speech(raw), "Done, {{sir}}. See notes at or item")

    def test_drop_ai_turns_the_ai_assistant_into_the_assistant(self):
        for said, wanted in (("The AI assistant, {{CHIEF}}, took a message.", "The assistant, {{CHIEF}}, took a message."),
                             ("{{CHIEF}} is an AI assistant for {{OWNER}}.", "{{CHIEF}} is an assistant for {{OWNER}}."),
                             ("An AI-powered voice assistant called.", "An assistant called."),
                             ("the AI agent rang back", "the agent rang back"),
                             ("AI assistant {{CHIEF}} spoke.", "assistant {{CHIEF}} spoke."),
                             ("{{OWNER}} is new to AI agents.", "{{OWNER}} is new to agents."),
                             ("Nothing to change here, said the plumber.", "Nothing to change here, said the plumber."),
                             ("", ""), (None, "")):
            self.assertEqual(util.drop_ai(said), wanted, said)

    def test_numbers_that_an_error_echoes_are_hidden_and_dates_and_ids_are_left_alone_enough(self):
        self.assertEqual(util.hide_numbers("HTTP 422: to_number +447700900111 is not allowed"), "HTTP 422: to_number [number] is not allowed")
        self.assertEqual(util.hide_numbers("call 07700 900111 or (0141) 555 0100"), "call [number] or [number]")
        self.assertEqual(util.hide_numbers("HTTP 500 after 45 seconds"), "HTTP 500 after 45 seconds")
        self.assertEqual(util.hide_numbers(None), "")

    def test_plain_makes_one_clean_line_of_what_was_said(self):
        self.assertEqual(util.plain("[happy] Ask {{brief}}  if\nhe is <b>free</b> key=abc123secret", 80),
                         "Ask brief if he is b free /b key=[redacted]")
        self.assertEqual(len(util.plain("word " * 200, 50)), 50)
        self.assertEqual(util.plain("", 10), "")

    def test_a_yes_may_arrive_as_a_word(self):
        for yes in (True, "true", "True", "yes", "1", " YES "):
            self.assertTrue(util.truthy(yes), yes)
        for no in (False, None, "false", "", "no", 0, "0", "maybe"):
            self.assertFalse(util.truthy(no), no)

    def test_clip_adds_an_ellipsis(self):
        self.assertEqual(util.clip("abc", 5), "abc")
        self.assertEqual(util.clip("abcdefghij", 5), "abcd…")


class ConfigTest(unittest.TestCase):
    def test_load_reads_settings_and_secrets_without_leaking_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, home = Path(tmp) / "state", Path(tmp) / "home"
            (home / "profiles" / "tutor").mkdir(parents=True)
            state.mkdir()
            (state / "config.json").write_text(json.dumps({"max_number": "+447700900123", "dial_mode": "live",
                                                           "tool_secret": "must-be-ignored"}))
            (state / "secrets.env").write_text("DESK_TOOL_SECRET=toolsecret\nELEVENLABS_WEBHOOK_SECRET='whsecret'\n")
            (home / ".env").write_text("# comment\nELEVENLABS_API_KEY=elkey\nAPI_SERVER_KEY=defkey\nTWILIO_ACCOUNT_SID=ACxyz\n"
                                       "TWILIO_AUTH_TOKEN=twtoken\nTWILIO_PHONE_NUMBER=+441111111111\nTWILIO_PHONE_NUMBER_SID=PN1\n")
            (home / "profiles" / "tutor" / ".env").write_text('API_SERVER_KEY="tutorkey"\n')
            cfg = config.load(str(state), str(home))
            self.assertEqual((cfg.max_number, cfg.dial_mode), ("+447700900123", "live"))
            self.assertEqual((cfg.tool_secret, cfg.webhook_secret), ("toolsecret", "whsecret"))
            self.assertEqual(cfg.eleven_key, "elkey")
            self.assertEqual(cfg.hermes_keys["default"], "defkey")
            self.assertEqual(cfg.hermes_keys["tutor"], "tutorkey")
            self.assertEqual(cfg.hermes_keys["coach"], "")
            for secret in ("toolsecret", "whsecret", "elkey", "defkey", "tutorkey", "447700900123"):
                self.assertNotIn(secret, repr(cfg))
            self.assertIn("hermes key for coach", cfg.problems())
            self.assertEqual((cfg.twilio_key_sid, cfg.twilio_key_secret), ("ACxyz", "twtoken"))   # no API key set: the account's
            self.assertEqual((cfg.twilio_number, cfg.twilio_number_sid), ("+441111111111", "PN1"))
            self.assertEqual(cfg.limit_minutes, 270)

    def test_update_config_json_merges_and_refuses_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            config.update_config_json(tmp, {"agent_id": "agent_1"})
            config.update_config_json(tmp, {"phone_number_id": "phnum_1"})
            self.assertEqual(json.loads((Path(tmp) / "config.json").read_text()),
                             {"agent_id": "agent_1", "phone_number_id": "phnum_1"})
            with self.assertRaises(ValueError):
                config.update_config_json(tmp, {"tool_secret": "x"})


class EnvFileTest(unittest.TestCase):
    def test_set_env_value_replaces_or_appends_and_keeps_the_file_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "secrets.env"
            config.set_env_value(path, "A", "1")
            config.set_env_value(path, "B", "two")
            config.set_env_value(path, "A", "3")
            self.assertEqual(path.read_text(), "A=3\nB=two\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(config.read_env_file(path), {"A": "3", "B": "two"})


class DBTest(unittest.TestCase):
    def test_tables_exist_and_kv_roundtrips(self):
        d = db.DB(":memory:")
        self.addCleanup(d.close)
        for table in ("tickets", "calls", "dials", "kv", "messages"):
            d.q(f"SELECT * FROM {table}")
        self.assertIsNone(d.kv_get("a"))
        d.kv_set("a", "1")
        d.kv_set("a", "2")
        self.assertEqual(d.kv_get("a"), "2")

    def test_transaction_rolls_back_on_error(self):
        d = db.DB(":memory:")
        self.addCleanup(d.close)
        with self.assertRaises(RuntimeError):
            with d.tx():
                d.x("INSERT INTO kv(key, value) VALUES('x', '1')")
                raise RuntimeError("boom")
        self.assertIsNone(d.kv_get("x"))

    def test_file_database_uses_a_rollback_journal_and_survives_threads(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = db.DB(Path(tmp) / "sub" / "desk.db")
            self.addCleanup(d.close)
            self.assertEqual(d.q("PRAGMA journal_mode")[0]["journal_mode"], "delete")

            def work(n):
                for i in range(20):
                    d.kv_set(f"k{n}", str(i))
            threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
            [t.start() for t in threads]
            [t.join() for t in threads]
            self.assertEqual([d.kv_get(f"k{n}") for n in range(4)], ["19"] * 4)


class SecurityTest(unittest.TestCase):
    def test_secrets_equal(self):
        self.assertTrue(security.secrets_equal("abc", "abc"))
        self.assertFalse(security.secrets_equal("abc", "abd"))
        self.assertFalse(security.secrets_equal("", ""))
        self.assertFalse(security.secrets_equal(None, "abc"))

    def test_signature_roundtrip_and_rejections(self):
        body, secret, now = b'{"type":"post_call_transcription"}', "whsec", 1_700_000_000
        header = security.sign_eleven_payload(body, secret, now)
        self.assertTrue(security.verify_eleven_signature(body, header, secret, now + 5))
        self.assertFalse(security.verify_eleven_signature(body + b" ", header, secret, now + 5))
        self.assertFalse(security.verify_eleven_signature(body, header, "other", now + 5))
        self.assertFalse(security.verify_eleven_signature(body, header, secret, now + 3600))   # too old
        self.assertFalse(security.verify_eleven_signature(body, None, secret, now))
        self.assertFalse(security.verify_eleven_signature(body, "t=abc,v0=00", secret, now))
        self.assertFalse(security.verify_eleven_signature(body, header, "", now))

    def test_signature_matches_the_official_sdk_algorithm(self):
        import hashlib
        import hmac
        body, secret, ts = '{"a":1}', "s3cret", "1700000000"
        sdk_digest = "v0=" + hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
        self.assertTrue(security.verify_eleven_signature(body.encode(), f"t={ts},{sdk_digest}", secret, 1_700_000_010))

    def test_rate_limiter_slides(self):
        clock = FakeClock()
        limiter = security.RateLimiter(3, 10, clock)
        self.assertEqual([limiter.allow("ip") for _ in range(4)], [True, True, True, False])
        self.assertTrue(limiter.allow("other"))
        clock.now += 11
        self.assertTrue(limiter.allow("ip"))


if __name__ == "__main__":
    unittest.main()
