import importlib.util
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_plugin():
    spec = importlib.util.spec_from_file_location(
        "crew_voice_under_test", PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ProviderTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_plugin()
        self.mod.SETTINGS = {"default_voice": "VOICE_CHIEF", "default_model": "eleven_v4", "owner": "Sam",
                             "personas": {"VOICE_CHIEF": "Atlas, Sam's chief of staff", "VOICE_ASSIST": "Ivy, Sam's assistant"}}
        self.synth_calls = []

        def synth(text, **kw):
            self.synth_calls.append({"text": text, **kw})
            return b"OGGDATA"
        self.secrets = {"ELEVENLABS_API_KEY": "el-key"}
        self.provider = self.mod.CrewVoiceProvider(
            llm=lambda messages: "The essay is in.", secret=self.secrets.get, synth=synth)

    def test_identity(self):
        self.assertEqual(self.provider.name, "crew-voice")
        self.assertTrue(self.provider.voice_compatible)
        self.assertTrue(self.provider.is_available())

    def test_unavailable_without_elevenlabs_key(self):
        p = self.mod.CrewVoiceProvider(llm=None, secret=lambda _n: None, synth=None)
        self.assertFalse(p.is_available())

    def test_synthesize_rewrites_long_text_in_the_profiles_voice(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "reply.ogg"
            path = self.provider.synthesize("x" * 400 + ". More.", str(out),
                                            voice="VOICE_TUTOR", model=None)
            self.assertEqual(path, str(out))
            self.assertEqual(out.read_bytes(), b"OGGDATA")
        call = self.synth_calls[0]
        self.assertEqual(call["text"], "The essay is in.")
        self.assertEqual(call["voice_id"], "VOICE_TUTOR")
        self.assertEqual(call["model_id"], "eleven_v4")
        self.assertEqual(call["output_format"], "opus_48000_64")
        self.assertEqual(call["api_key"], "el-key")

    def test_defaults_to_the_chiefs_voice_and_mp3_for_mp3_paths(self):
        with tempfile.TemporaryDirectory() as d:
            self.provider.synthesize("Very good.", str(Path(d) / "a.mp3"))
        call = self.synth_calls[0]
        self.assertEqual(call["voice_id"], "VOICE_CHIEF")
        self.assertEqual(call["text"], "Very good.")
        self.assertEqual(call["output_format"], "mp3_44100_128")

    def test_persona_comes_from_the_voice(self):
        seen = {}

        def llm(messages):
            seen["system"] = messages[0]["content"]
            return "Done."
        p = self.mod.CrewVoiceProvider(llm=llm, secret=self.secrets.get,
                                         synth=lambda text, **kw: b"A")
        with tempfile.TemporaryDirectory() as d:
            p.synthesize("y" * 400, str(Path(d) / "a.ogg"), voice="VOICE_ASSIST")
        self.assertIn("Ivy", seen["system"])
        self.assertIn("speaking to Sam", seen["system"])


    def test_default_secret_lookup_uses_hermes_voice_key_resolver(self):
        # The primary profile on the shared gateway has no secret scope, and agent.secret_scope.get_secret raises
        # there, which made the chief's voice notes silently text-only. Hermes's own voice providers go through this
        # resolver instead (profile scope first, then the launch profile's environment).
        import sys
        import types
        from unittest import mock

        calls = []
        helpers = types.ModuleType("tools.tool_backend_helpers")
        helpers.resolve_provider_secret = (
            lambda env_var, provider_id, *a, **k: calls.append((env_var, provider_id)) or "el-key")
        with mock.patch.dict(sys.modules, {"tools": types.ModuleType("tools"),
                                           "tools.tool_backend_helpers": helpers}):
            self.assertEqual(self.mod._hermes_secret("ELEVENLABS_API_KEY"), "el-key")
        self.assertEqual(calls, [("ELEVENLABS_API_KEY", "elevenlabs")])

    def test_availability_check_says_why_when_the_key_cannot_be_read(self):
        def boom(_name):
            raise RuntimeError("no scope")
        p = self.mod.CrewVoiceProvider(llm=None, secret=boom, synth=None)
        with self.assertLogs("hermes_plugins.crew_voice", level="WARNING") as logs:
            self.assertFalse(p.is_available())
        self.assertIn("RuntimeError", logs.output[0])

    def test_rewrite_failure_is_logged_and_the_note_still_goes_out(self):
        def llm(_messages):
            raise TimeoutError("slow")
        p = self.mod.CrewVoiceProvider(
            llm=llm, secret=self.secrets.get,
            synth=lambda text, **kw: (self.synth_calls.append({"text": text, **kw}), b"A")[1])
        with tempfile.TemporaryDirectory() as d, \
                self.assertLogs("hermes_plugins.crew_voice", level="WARNING") as logs:
            p.synthesize("z" * 400 + ". More.", str(Path(d) / "a.ogg"))
        self.assertIn("TimeoutError", logs.output[0])
        self.assertEqual(len(self.synth_calls), 1)


if __name__ == "__main__":
    unittest.main()
