"""ElevenLabs text-to-speech over HTTP. The API key never appears in errors or logs."""
import os

API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format={fmt}"
_OPUS_EXTS = {".ogg", ".opus", ".oga"}


def output_format_for(path: str) -> str:
    return "opus_48000_64" if os.path.splitext(path)[1].lower() in _OPUS_EXTS else "mp3_44100_128"


def synthesize(text, *, voice_id, model_id, api_key, output_format, client=None, retries=1,
               timeout=60.0):
    own = client is None
    if own:
        import httpx  # imported here so unit tests run without httpx installed
        client = httpx.Client()
    url = API_URL.format(voice=voice_id, fmt=output_format)
    body = {"text": text, "model_id": model_id}
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    last = "no attempt"
    try:
        for _ in range(retries + 1):
            try:
                resp = client.post(url, headers=headers, json=body, timeout=timeout)
            except Exception as exc:  # network/transport: retry
                last = type(exc).__name__
                continue
            if resp.status_code == 200 and resp.content:
                return resp.content
            last = f"HTTP {resp.status_code}: {str(resp.text)[:200]}"
            if resp.status_code < 500 and resp.status_code != 429:
                break
    finally:
        if own:
            client.close()
    raise RuntimeError(f"ElevenLabs synthesis failed ({last})".replace(api_key or "\0", "***"))
