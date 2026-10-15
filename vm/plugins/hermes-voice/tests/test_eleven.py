import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jv_eleven as e  # noqa: E402


class Resp:
    def __init__(self, status, content=b"", text=""):
        self.status_code, self.content, self.text = status, content, text


class FakeClient:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class SynthesizeTest(unittest.TestCase):
    def test_posts_voice_model_and_format(self):
        c = FakeClient(Resp(200, b"AUDIO"))
        out = e.synthesize("Hello.", voice_id="V1", model_id="eleven_v4", api_key="k",
                           output_format="opus_48000_64", client=c)
        self.assertEqual(out, b"AUDIO")
        call = c.calls[0]
        self.assertTrue(call["url"].endswith("/v1/text-to-speech/V1?output_format=opus_48000_64"))
        self.assertEqual(call["json"], {"text": "Hello.", "model_id": "eleven_v4"})
        self.assertEqual(call["headers"]["xi-api-key"], "k")

    def test_retries_a_server_error_once(self):
        c = FakeClient(Resp(503, text="busy"), Resp(200, b"OK"))
        self.assertEqual(e.synthesize("x", voice_id="V", model_id="m", api_key="k",
                                      output_format="mp3_44100_128", client=c), b"OK")
        self.assertEqual(len(c.calls), 2)

    def test_client_error_is_not_retried_and_hides_the_key(self):
        c = FakeClient(Resp(401, text="invalid key"), Resp(200, b"never"))
        with self.assertRaises(RuntimeError) as ctx:
            e.synthesize("x", voice_id="V", model_id="m", api_key="SECRETKEY",
                         output_format="mp3_44100_128", client=c)
        self.assertIn("401", str(ctx.exception))
        self.assertNotIn("SECRETKEY", str(ctx.exception))
        self.assertEqual(len(c.calls), 1)

    def test_transport_errors_retry_then_raise(self):
        c = FakeClient(OSError("reset"), OSError("reset"))
        with self.assertRaises(RuntimeError):
            e.synthesize("x", voice_id="V", model_id="m", api_key="k",
                         output_format="mp3_44100_128", client=c)
        self.assertEqual(len(c.calls), 2)

    def test_format_follows_the_file_extension(self):
        self.assertEqual(e.output_format_for("/tmp/a.ogg"), "opus_48000_64")
        self.assertEqual(e.output_format_for("/tmp/a.OPUS"), "opus_48000_64")
        self.assertEqual(e.output_format_for("/tmp/a.mp3"), "mp3_44100_128")


if __name__ == "__main__":
    unittest.main()
