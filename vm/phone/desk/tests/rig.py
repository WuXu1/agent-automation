"""A whole desk with every outside service faked, for the tests that exercise several parts together."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from desk import config, hermes, server, util  # noqa: E402
from helpers import FakeClock, FakeHermes  # noqa: E402

MAX = "+447700900123"
TOOL_SECRET, WEBHOOK_SECRET = "toolsecret", "whsecret"


def uk(hour, minute=0, day=5):
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=util.UK).timestamp()


class FakeEleven:
    def __init__(self):
        self.sent, self.error, self.n = [], None, 0
        self.rings = []                 # one entry per outgoing call: which agent was rung, which number, with what variables
        self.reset = dt.datetime(2026, 11, 3, 10, 39, tzinfo=dt.timezone.utc).timestamp()
        self.durations = []

    def outbound_call(self, agent_id, phone_number_id, to_number, dynamic_variables, ringing_timeout_secs=45):
        self.sent.append(dynamic_variables)
        self.rings.append({"agent_id": agent_id, "to": to_number, "variables": dynamic_variables})
        if self.error:
            raise self.error
        self.n += 1
        return {"conversation_id": f"conv_out{self.n}", "call_sid": f"CA{self.n}"}

    def subscription(self):
        return {"next_character_count_reset_unix": int(self.reset)}

    def conversations_since(self, start_unix, agent_id=None, max_pages=10):
        return [{"call_duration_secs": d} for d in self.durations]

    def speak(self, text, voice_id, model_id="eleven_v4"):
        return b"OggS-fake"


class FakeTwilio:
    def __init__(self):
        self.url, self.sets = "https://eleven/inbound", []

    def get_number(self, sid):
        return {"voice_url": self.url}

    def set_voice_url(self, sid, url, method="POST"):
        self.url = url
        self.sets.append(url)


class Rig:
    def __init__(self, tmp, fake_hermes=None, **overrides):
        settings = dict(state_dir=str(tmp), hermes_home=str(tmp), max_number=MAX, agent_id="agent_1", guest_agent_id="agent_guest",
                        phone_number_id="phnum_1",
                        public_base="https://desk.example:8443", twilio_number_sid="PN1", tool_secret=TOOL_SECRET,
                        webhook_secret=WEBHOOK_SECRET, eleven_key="k", hermes_keys=dict(FakeHermes.KEYS), dial_mode="live",
                        notify_mode="live", wait_secs=2.0, telegram_chat_id="42")
        settings.update(overrides)
        self.cfg = config.Config(**settings)
        self.clock = FakeClock(now=uk(14))
        self.hermes = fake_hermes or FakeHermes(polls=1)
        self.hermes.server.__enter__()
        self.eleven, self.twilio, self.telegram = FakeEleven(), FakeTwilio(), []

        def notify_run(cmd, timeout=90, env=None):
            self.telegram.append(cmd[5])
            return 0
        self.app = server.App(self.cfg, clock=self.clock, env={}, brief_run=lambda cmd, timeout=25, env=None: "",
                              notify_run=notify_run, eleven_client=self.eleven, twilio_client=self.twilio,
                              hermes_client=hermes.HermesClient(self.hermes.server.url, FakeHermes.KEYS, timeout=5))

    def close(self):
        self.hermes.server.__exit__(None, None, None)
        self.app.db.close()
