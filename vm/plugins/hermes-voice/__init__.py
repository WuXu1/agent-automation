"""hermes-voice: Hermes TTS provider for voice-note replies in each agent's own ElevenLabs voice.

The gateway hands this provider whatever it wants spoken (an auto voice reply, or a
text_to_speech call). Long or written-style text is rewritten into one to three spoken sentences
with Hermes's own auxiliary LLM; then ElevenLabs speaks it in the profile's voice
(tts.voice in that profile's config.yaml). Who each voice belongs to and the owner's name: voices.json beside this
file, written by `sudo hermes-voice`. Style rules: STYLE.md beside this file.
"""
import json
import logging
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import jv_eleven  # noqa: E402
import jv_speech  # noqa: E402

try:
    from agent.tts_provider import TTSProvider
except ImportError:  # unit tests outside Hermes
    class TTSProvider:  # type: ignore[no-redef]
        pass

_VOICES = _HERE / "voices.json"
SETTINGS = json.loads(_VOICES.read_text()) if _VOICES.exists() else {"default_voice": "", "default_model": "eleven_v4", "owner": "the owner", "personas": {}}
_STYLE_FILE = _HERE / "STYLE.md"
STYLE = _STYLE_FILE.read_text() if _STYLE_FILE.exists() else ""
logger = logging.getLogger("hermes_plugins.hermes_voice")


def _hermes_secret(name):
    # The resolver Hermes's own voice providers use: the profile's secret scope first, then the launch profile's
    # environment. agent.secret_scope.get_secret on its own raises for the primary profile on the shared gateway
    # (no scope is installed around its auto-TTS check), which would leave the chief's voice notes silently text-only.
    from tools.tool_backend_helpers import resolve_provider_secret
    return resolve_provider_secret(name, "elevenlabs")


def _hermes_llm(messages):
    from agent.auxiliary_client import call_llm
    response = call_llm(task="voice_summary", messages=messages, temperature=0.4,
                        max_tokens=220, timeout=20.0)
    content = getattr(response, "content", None)
    if content is None:
        choices = getattr(response, "choices", None) or []
        content = getattr(choices[0].message, "content", "") if choices else ""
    if isinstance(content, list):
        content = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content or "")


class HermesVoiceProvider(TTSProvider):
    def __init__(self, llm=None, secret=None, synth=None):
        self._llm = llm or _hermes_llm
        self._secret = secret or _hermes_secret
        self._synth = synth or jv_eleven.synthesize

    @property
    def name(self) -> str:
        return "hermes-voice"

    @property
    def display_name(self) -> str:
        return "Hermes voice (ElevenLabs v4, spoken rewrite)"

    @property
    def voice_compatible(self) -> bool:
        return True

    def is_available(self) -> bool:
        try:
            return bool(self._secret("ELEVENLABS_API_KEY"))
        except Exception as exc:
            logger.warning("hermes-voice unavailable: could not read the ElevenLabs key (%s)", type(exc).__name__)
            return False

    def synthesize(self, text, output_path, *, voice=None, model=None, speed=None,
                   format="mp3", **extra) -> str:
        voice_id = voice or SETTINGS["default_voice"]
        model_id = model or SETTINGS["default_model"]
        persona = SETTINGS["personas"].get(voice_id, "an assistant")

        def llm(messages):
            try:
                return self._llm(messages)
            except Exception as exc:  # spoken_version then falls back to the trimmed reply; say why
                logger.warning("hermes-voice: spoken rewrite failed (%s); using the trimmed reply", type(exc).__name__)
                raise

        spoken = jv_speech.spoken_version(text, persona=persona, owner=SETTINGS.get("owner", "the owner"), style=STYLE, llm=llm)
        audio = self._synth(spoken, voice_id=voice_id, model_id=model_id,
                            api_key=self._secret("ELEVENLABS_API_KEY") or "",
                            output_format=jv_eleven.output_format_for(str(output_path)))
        Path(output_path).write_bytes(audio)
        logger.info("hermes-voice: voice=%s model=%s chars_in=%d chars_out=%d",
                    voice_id, model_id, len(text), len(spoken))
        return str(output_path)


def register(ctx):
    ctx.register_tts_provider(HermesVoiceProvider())
