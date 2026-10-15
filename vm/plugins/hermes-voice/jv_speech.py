"""Turn an agent's written reply into what the agent says in a voice note. Pure text; no I/O."""
import re

VERBATIM_MAX_CHARS = 280
SPOKEN_MAX_CHARS = 420

_URL = re.compile(r"https?://\S+")
_PATH = re.compile(r"(?<![\w.])(?:~|/)[\w.\-]+(?:/[\w.\-]+)+")
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+", re.M)
_MARKS = re.compile(r"[*_`#>|]+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def clean(text: str) -> str:
    out = _URL.sub("", text or "")
    out = _PATH.sub("", out)
    out = _BULLET.sub("", out)
    out = _MARKS.sub("", out)
    return re.sub(r"\s+", " ", out).strip()


def needs_rewrite(text: str) -> bool:
    raw = (text or "").strip()
    return (len(raw) > VERBATIM_MAX_CHARS or "\n" in raw
            or bool(_URL.search(raw) or _PATH.search(raw) or _MARKS.search(raw)))


def first_sentences(text: str, limit: int = SPOKEN_MAX_CHARS) -> str:
    out = ""
    for sentence in _SENTENCE_END.split(clean(text)):
        if not sentence:
            continue
        candidate = f"{out} {sentence}".strip()
        if out and len(candidate) > limit:
            break
        out = candidate
    if len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return out


def build_messages(text: str, *, persona: str, style: str, owner: str = "the owner") -> list:
    system = (
        f"You are {persona}, speaking to {owner} in a voice note.\n\n{style}\n\n"
        "Rewrite the written reply you are given as what you would say out loud: one to three "
        f"short sentences, under {SPOKEN_MAX_CHARS} characters, the news first. No lists, symbols, "
        "file paths, URLs or ids. Do not add anything that is not in the reply. "
        "Answer with the spoken words only.")
    return [{"role": "system", "content": system}, {"role": "user", "content": text}]


def spoken_version(text: str, *, persona: str, style: str, llm, owner: str = "the owner") -> str:
    if not needs_rewrite(text):
        return clean(text)
    try:
        spoken = clean(llm(build_messages(text, persona=persona, style=style, owner=owner)))
    except Exception:  # any model failure: a trimmed version beats no voice note
        spoken = ""
    return first_sentences(spoken or text)
