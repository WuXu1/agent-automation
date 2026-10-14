"""Jobs that need the internet, which the bridge itself cannot reach (its unit allows localhost only).

The bridge drops a request file in `<state>/jobs/` (`submit`); `hermes-dash-jobs.path` notices it and starts
`hermes-dash-jobs.service`, which runs this file as `hermes` with network access (`main`). The runner does only the kinds
listed in KINDS, each with checked arguments, and writes `<id>.out.json` for the page to poll (`status`).

- enhance: rewrite an agent's "What it does" or SOUL with DeepSeek (the key Hermes already uses; a fraction of a penny each)
- skill-search / skill-inspect / skill-install: skills.sh through Hermes (`hermes -p <profile> skills ... --source skills-sh`)
- memory-tidy: a new memory rewritten as one clear note, with the section it belongs in (or a new one)
- brain-sort: up to 40 unsorted notes put into sections (brain.py), new sections when nothing fits
- brain-review: the weekly check-up of every note (review.py): proposals only, the owner applies each on the page
- balances: the DeepSeek balance, and ElevenLabs' when the voice add-on is on (settings.py)
- integrations: the Integrations Hub's checks (Telegram bots, Gemini key, the add-ons' logins) and the balances
- inbox-list / inbox-read / inbox-summary: Gmail, read only (inbox.py), and an AI summary of the inbox

The AI jobs use the model picked in Settings (deepseek-flash unless the owner changes it).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))   # -I leaves the script's folder off the path

import actions  # noqa: E402
import brain  # noqa: E402
import crew  # noqa: E402
import inbox  # noqa: E402
import review  # noqa: E402
import integrations  # noqa: E402
import settings  # noqa: E402
from actions import ActionError, Env  # noqa: E402

JOB_RE = re.compile(r"^[a-f0-9]{16}$")
IDENT_RE = re.compile(r"^[A-Za-z0-9._@:/+-]{2,200}$")
SKILLS_SH = "skills-sh"
INDEXED_RE = re.compile(r"from ([\w.-]+/[\w.-]+)\s*·\s*([\d,]+) installs")
MAX_PENDING = 6
KEEP_OUT_SECS = 3600


def jobs_dir(env: Env) -> Path:
    return Path(env.state_dir) / "jobs"


# -- the bridge's side -------------------------------------------------------------------------------------------------------

def _check(kind: str, args: dict, profiles: list[str], hermes_home: str = "/data/.hermes") -> dict:
    """Only these kinds, only these arguments: the runner has the network and the bridge's user."""
    def text(key: str, limit: int, required: bool = True) -> str:
        v = args.get(key, "")
        if not isinstance(v, str) or (required and not v.strip()) or len(v) > limit:
            raise ActionError(400, f"{key} is missing or too long")
        return v.replace("\r\n", "\n").strip()

    def profile() -> str:
        p = args.get("profile")
        p = crew.profile_of(hermes_home, p) if isinstance(p, str) else p
        if p not in profiles:
            raise ActionError(404, "No such agent")
        return p

    if kind == "enhance":
        field = args.get("field")
        if field not in ("description", "soul", "skill"):
            raise ActionError(400, "field is description, soul or skill")
        limit = {"description": 600, "soul": 20_000, "skill": 20_000}[field]
        return {"field": field, "text": text("text", limit), "name": text("name", 40, False), "about": text("about", 600, False)}
    if kind == "memory-tidy":
        return {"text": text("text", 2000)}
    if kind == "brain-sort":
        notes = args.get("notes")
        if not isinstance(notes, list) or not 0 < len(notes) <= brain.SORT_BATCH or not all(
                isinstance(n, dict) and isinstance(n.get("id"), str) and re.match(r"^[A-Za-z0-9-]{8,64}$", n["id"])
                and isinstance(n.get("text"), str) for n in notes):
            raise ActionError(400, "Notes to sort: up to 40, each with an id and a text")
        return {"notes": [{"id": n["id"], "text": n["text"][:400]} for n in notes]}
    if kind == "brain-review":
        return review.check_args(args)
    if kind in ("balances", "integrations", "inbox-list", "inbox-summary"):
        return {}
    if kind == "inbox-read":
        folder, uid = args.get("folder"), args.get("uid")
        if folder not in inbox.FOLDERS or not isinstance(uid, str) or not inbox.UID_RE.match(uid):
            raise ActionError(400, "Not a message the inbox knows")
        return {"folder": folder, "uid": uid}
    if kind == "skill-search":
        return {"profile": profile(), "query": text("query", 80)}
    if kind in ("skill-inspect", "skill-install"):
        ident = args.get("identifier")
        if not isinstance(ident, str) or not IDENT_RE.match(ident) or not ident.startswith(SKILLS_SH + "/"):
            raise ActionError(400, "Not a skills.sh skill")            # skills come from skills.sh only
        return {"profile": profile(), "identifier": ident}
    raise ActionError(400, "Unknown job")


def submit(env: Env, kind: str, args: dict) -> dict:
    """Queue a job; returns its id for the page to poll."""
    clean = _check(kind, args, env.profiles(), env.hermes_home)
    d = jobs_dir(env)
    d.mkdir(parents=True, exist_ok=True)
    if len(list(d.glob("*.req.json"))) >= MAX_PENDING:
        raise ActionError(429, "Several jobs are still waiting; try again in a minute")
    job = uuid.uuid4().hex[:16]
    tmp = d / f".{job}.tmp"
    tmp.write_text(json.dumps({"id": job, "kind": kind, "args": clean, "at": int(time.time())}))
    os.replace(tmp, d / f"{job}.req.json")      # the path unit only ever sees whole requests
    if kind == "skill-install":
        actions.log_action(env, "skill-install-requested", profile=clean["profile"], identifier=clean["identifier"])
    return {"job": job}


def status(env: Env, job: str) -> dict:
    if not JOB_RE.match(job):
        raise ActionError(404, "No such job")
    d = jobs_dir(env)
    out = d / f"{job}.out.json"
    if out.exists():
        try:
            return {"state": "done", **json.loads(out.read_text())}
        except (OSError, ValueError):
            return {"state": "done", "ok": False, "error": "The job's result could not be read"}
    if (d / f"{job}.req.json").exists() or (d / f"{job}.run.json").exists():
        return {"state": "running"}
    raise ActionError(404, "No such job")


# -- the runner's side -------------------------------------------------------------------------------------------------------

def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                out[key.removeprefix("export ").strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return out


PROMPTS = {
    "description": (
        "You tidy the one-paragraph job description of an AI agent in {owner}'s personal assistant team (Hermes). Its lead agent "
        "reads it to decide which cards to hand over, so it must say plainly what the agent does and does not do. Keep every "
        "fact {owner} wrote, invent nothing, plain English, start with the agent's name and a colon, at most 400 characters. "
        "Reply with the paragraph only."),
    "soul": (
        "You improve the SOUL (system prompt) of an AI agent in {owner}'s personal assistant team (Hermes). Keep every rule, fact "
        "and limit {owner} wrote, and keep the safety lines (never send, buy, submit or delete without {owner}'s yes). Make it "
        "clear, well ordered and in the second person ('You are ...'), with short sections. Plain words, plain English, no "
        "invented facts about {owner}. Reply with the SOUL text only, no preamble, no code fences."),
    "skill": (
        "You improve a Hermes agent skill (a SKILL.md body: when to use it and the steps to follow). Keep every step and "
        "rule {owner} wrote, make it clear and ordered, plain words, plain English, invent nothing. Reply with the body only."),
}


PROVIDERS = {
    "deepseek": ("https://api.deepseek.com/v1/chat/completions", "DEEPSEEK_API_KEY", "DeepSeek"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "GEMINI_API_KEY", "Gemini"),
}


def deepseek(env_file: Path, system: str, user: str, max_tokens: int, model: str = "deepseek-flash",
             timeout: float = 90.0, json_mode: bool = False) -> str:
    """One chat completion with the model picked in Settings (DeepSeek or Gemini, both OpenAI-style)."""
    provider = settings.MODELS.get(model, settings.MODELS["deepseek-flash"])["provider"]
    url, key_name, label = PROVIDERS[provider]
    key = read_env_file(env_file).get(key_name, "")
    if not key:
        raise ActionError(500, f"No {label} key on the VM")
    body: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "temperature": 0.4,
                            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    # these models think by default and can spend the whole budget on it; a rewrite or a sort needs no thinking
    # (Hermes' own DeepSeek profile sends the same switch)
    if provider == "deepseek":
        body["thinking"] = {"type": "disabled"}
    else:
        body["reasoning_effort"] = "none"
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ActionError(502, f"{label} said HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ActionError(502, f"{label} could not be reached") from None
    text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if not text:
        raise ActionError(502, f"{label} sent back nothing")
    return text


def do_enhance(env: Env, a: dict, llm: Callable[..., str] = deepseek) -> dict:
    who = f"Agent: {a['name']}.\n" if a["name"] else ""
    about = f"What it does: {a['about']}\n" if a["about"] and a["field"] != "description" else ""
    tokens = {"description": 300, "soul": 4000, "skill": 4000}[a["field"]]
    owner = crew.owner_name(env.hermes_home)
    text = llm(Path(env.hermes_home) / ".env", PROMPTS[a["field"]].format(owner=owner), f"{who}{about}\n{owner}'s draft:\n{a['text']}", tokens,
               model=settings.load(env)["model"])
    text = re.sub(r"^```\w*\n|\n?```$", "", text.strip()).strip()        # models like to wrap it in a code fence
    limit = {"description": 600, "soul": 20_000, "skill": 20_000}[a["field"]]
    return {"text": text[:limit]}


def _p(profile: str) -> list[str]:
    return [] if profile == "default" else ["-p", profile]


def do_skill_search(env: Env, a: dict) -> dict:
    """skills.sh only: the most installed first, with the repo each one comes from."""
    raw = actions.cli(env, *_p(a["profile"]), "skills", "search", "--source", SKILLS_SH, "--json", "--limit", "25", "--", a["query"])
    try:
        found = json.loads(raw[raw.index("["):]) if "[" in raw else []
    except ValueError:
        raise ActionError(502, "skills.sh answered in an unexpected way") from None
    out = []
    for r in found:
        if not isinstance(r, dict) or not str(r.get("identifier") or "").startswith(SKILLS_SH + "/"):
            continue
        row = {k: str(r.get(k) or "")[:400] for k in ("name", "identifier", "source", "trust_level", "description")}
        m = INDEXED_RE.search(row["description"])
        row["repo"] = m.group(1) if m else "/".join(row["identifier"].split("/")[1:3])
        row["installs"] = int(m.group(2).replace(",", "")) if m else None
        out.append(row)
    out.sort(key=lambda r: -(r["installs"] or 0))
    return {"results": out}


def do_skill_inspect(env: Env, a: dict) -> dict:
    return {"text": actions.cli(env, *_p(a["profile"]), "skills", "inspect", "--", a["identifier"])[-6000:]}


def do_skill_install(env: Env, a: dict) -> dict:
    # never --force: a skill the hub's scanner blocks stays out
    out = actions.cli(env, *_p(a["profile"]), "skills", "install", "--yes", "--", a["identifier"])
    actions.log_action(env, "skill-installed", profile=a["profile"], identifier=a["identifier"])
    return {"text": out.strip()[-1500:]}


def _json_answer(text: str) -> dict:
    text = re.sub(r"^```\w*\n|\n?```$", "", text.strip()).strip()
    try:
        out = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except ValueError:
        raise ActionError(502, "The model's answer was not the JSON asked for") from None
    if not isinstance(out, dict):
        raise ActionError(502, "The model's answer was not the JSON asked for")
    return out


def _sections_prompt(env: Env) -> str:
    return "\n".join(f"- {s['id']}: {s['label']} ({s['blurb']})" for s in brain.load(env)["sections"])


TIDY = (
    "You file notes into the shared memory of {owner}'s personal assistant team. Rewrite {owner}'s "
    "note as ONE short, clear note an agent can read at a glance: third person ('{owner} ...'), present tense, every fact kept, "
    "nothing invented, plain English, under 200 characters when possible. Then pick the section it belongs in from the "
    "list, or, only when none fits, name a new section for a broad topic (2 to 4 words written like the others, e.g. "
    "'Money & savings') with a one-line description. Reply with JSON only: "
    '{{"text": "...", "section": "<id from the list>"}} or {{"text": "...", "new": {{"label": "...", "blurb": "..."}}}}')
SORT = (
    "You sort notes from the shared memory of {owner}'s personal assistant team into sections. Sort by what a note is ABOUT, not "
    "by which assistant wrote it or is mentioned in it. A section's blurb is a guide, not a limit. In particular: 'Health & "
    "wellbeing' holds every health matter (conditions, medication, sleep, check-ups: one condition is an item inside it, never "
    "a section of its own); 'Fitness & food' is training, sport, food plans and goals; 'People & contacts' is ONLY real people "
    "in {owner}'s life and how to reach them, never the assistants ({agents}) and never messages in general; 'Assistant rules' "
    "is how the assistants should behave and {owner}'s standing instructions to them; 'Projects & tech' is code, projects, "
    "the server and its tools. Start a new "
    "section only when five or more notes share a broad area of life that no section covers: a label of 2 to 4 words naming "
    "that area like the others (e.g. 'Money & savings'), never one condition, event, person or app, with a one-line "
    "description, used as the section for those notes; at most one new section. Reply with JSON only: "
    '{{"assign": {{"<note id>": "<section id or new label>"}}, "new": [{{"label": "...", "blurb": "..."}}]}}')


def _team(env: Env) -> dict[str, str]:
    c = crew.load(env.hermes_home)
    return {"owner": c["owner"]["name"], "agents": ", ".join(a["name"] for a in c["agents"])}


def do_memory_tidy(env: Env, a: dict, llm: Callable[..., str] = deepseek) -> dict:
    t = _team(env)
    out = _json_answer(llm(Path(env.hermes_home) / ".env", TIDY.format(**t), f"Sections:\n{_sections_prompt(env)}\n\n{t['owner']}'s note:\n{a['text']}",
                           400, model=settings.load(env)["model"], json_mode=True))
    text = str(out.get("text") or "").strip()[:2000] or a["text"]
    ids = {s["id"] for s in brain.load(env)["sections"]}
    new = out.get("new") if isinstance(out.get("new"), dict) else None
    section = out.get("section") if out.get("section") in ids else None
    return {"text": text, "section": section,
            "new": {"label": str(new.get("label") or "")[:32], "blurb": str(new.get("blurb") or "")[:80]} if new and not section else None}


def do_brain_sort(env: Env, a: dict, llm: Callable[..., str] = deepseek) -> dict:
    notes = a["notes"]
    listing = "\n".join(f"{n['id']}: {n['text']}" for n in notes)
    try:
        answer = _json_answer(llm(Path(env.hermes_home) / ".env", SORT.format(**_team(env)), f"Sections:\n{_sections_prompt(env)}\n\nNotes:\n{listing}",
                                  2500, model=settings.load(env)["model"], json_mode=True))
    except ActionError:
        brain.set_pending(env, None)
        raise
    return brain.apply_sort(env, notes, answer)


def do_brain_review(env: Env, a: dict, llm: Callable[..., str] = deepseek) -> dict:
    model = settings.load(env)["model"]
    return review.run(env, a, lambda system, user: llm(Path(env.hermes_home) / ".env", system, user, 3500, model=model, json_mode=True))


def do_balances(env: Env, a: dict, get: Callable[[str, dict], Any] | None = None) -> dict:
    """What is left on each paid service. One failing does not stop the others."""
    def fetch(url: str, headers: dict) -> Any:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
            return json.loads(r.read())
    get = get or fetch
    main = read_env_file(Path(env.hermes_home) / ".env")
    out: dict[str, Any] = {"at": int(time.time() * 1000)}
    try:
        d = get("https://api.deepseek.com/user/balance", {"Authorization": f"Bearer {main.get('DEEPSEEK_API_KEY', '')}", "Accept": "application/json"})
        info = (d.get("balance_infos") or [{}])[0]
        out["deepseek"] = {"balance": float(info.get("total_balance") or 0), "currency": info.get("currency") or "USD", "ok": bool(d.get("is_available"))}
    except Exception as exc:  # noqa: BLE001
        out["deepseek"] = {"error": type(exc).__name__}
    if crew.feature(env.hermes_home, "voice") and main.get("ELEVENLABS_API_KEY"):
        try:
            d = get("https://api.elevenlabs.io/v1/user/subscription", {"xi-api-key": main["ELEVENLABS_API_KEY"]})
            out["elevenlabs"] = {"used": int(d.get("character_count") or 0), "limit": int(d.get("character_limit") or 0),
                                 "tier": d.get("tier"), "resetAt": int(d.get("next_character_count_reset_unix") or 0) * 1000 or None}
        except Exception as exc:  # noqa: BLE001
            out["elevenlabs"] = {"error": type(exc).__name__}
    p = settings.balances_path(env)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(".balances.json.tmp")
    tmp.write_text(json.dumps(out))
    os.replace(tmp, p)
    return out


def do_integrations(env: Env, a: dict) -> dict:
    return integrations.check_all(env, lambda e: do_balances(e, {}))


def do_inbox_summary(env: Env, a: dict) -> dict:
    return inbox.do_summary(env, a, deepseek, settings.load(env)["model"])


KINDS: dict[str, Callable[[Env, dict], dict]] = {
    "integrations": do_integrations, "inbox-list": inbox.do_list, "inbox-read": inbox.do_read, "inbox-summary": do_inbox_summary,
    "memory-tidy": do_memory_tidy, "brain-sort": do_brain_sort, "brain-review": do_brain_review, "balances": do_balances,
    "enhance": do_enhance, "skill-search": do_skill_search,
    "skill-inspect": do_skill_inspect, "skill-install": do_skill_install,
}


def run_once(env: Env) -> int:
    """Every waiting request, oldest first. Returns how many ran."""
    d = jobs_dir(env)
    if not d.is_dir():
        return 0
    n = 0
    now = time.time()
    for old in d.glob("*.out.json"):
        if now - old.stat().st_mtime > KEEP_OUT_SECS:
            old.unlink(missing_ok=True)
    for req in sorted(d.glob("*.req.json"), key=lambda p: p.stat().st_mtime):
        job = req.name.split(".")[0]
        running = d / f"{job}.run.json"
        try:
            os.replace(req, running)
        except OSError:
            continue
        try:
            spec = json.loads(running.read_text())
            kind = spec.get("kind")
            # checked again here: the runner trusts nothing in the folder, even the bridge's own files
            clean = _check(kind, spec.get("args") or {}, env.profiles(), env.hermes_home)
            result: dict[str, Any] = {"ok": True, **KINDS[kind](env, clean)}
        except ActionError as exc:
            result = {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - one bad job must not stop the others
            result = {"ok": False, "error": f"The job failed ({type(exc).__name__})"}
        tmp = d / f".{job}.out.tmp"
        tmp.write_text(json.dumps(result))
        os.replace(tmp, d / f"{job}.out.json")
        running.unlink(missing_ok=True)
        n += 1
    return n


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Crew Command: the dashboard's network jobs")
    parser.add_argument("--config", default="/data/.hermes/hermes-dash/config.json")
    args = parser.parse_args(argv)
    cfg = json.loads(Path(args.config).read_text())
    feeds_cfg = cfg.get("feeds", {})
    env = Env(hermes_home=feeds_cfg.get("hermes_home", "/data/.hermes"),
              **{k: v for k, v in cfg.get("actions", {}).items() if k in Env.__dataclass_fields__})
    # requests that arrive while we run are picked up in the same start
    while run_once(env):
        pass


if __name__ == "__main__":
    main()
