"""The agents' automations: Hermes cron jobs, read from each profile's `cron/jobs.json`, changed only
through `hermes [-p <profile>] cron ...` (pause, resume, run, edit, create, remove). Each change is logged.

`hermes cron resume` runs a job at once when its next time has already passed, so the page says so first.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

import crew
from actions import ActionError, Env, _lock, _read, cli, log_action

JOB_RE = re.compile(r"^[a-f0-9]{8,32}$")
SCHEDULE_RE = re.compile(r"^[A-Za-z0-9 */,:.-]{2,60}$")
DELIVER_RE = re.compile(r"^(origin|local|telegram|bot-chat(:[a-z][a-z0-9]{1,23})?)$")
NUMBER = re.compile(r"\+?\d[\d\s().-]{7,}\d")
LIMITS = {"name": 80, "prompt": 4000}


def _p(profile: str) -> list[str]:
    return [] if profile == "default" else ["-p", profile]


def _iso_ms(v: Any) -> int | None:
    if not isinstance(v, str) or not v:
        return None
    try:
        return int(dt.datetime.fromisoformat(v).timestamp() * 1000)
    except ValueError:
        return None


def _jobs(env: Env, profile: str) -> list[dict]:
    try:
        data = json.loads(_read(env.profile_dir(profile) / "cron" / "jobs.json") or "{}")
    except ValueError:
        return []
    jobs = data.get("jobs", []) if isinstance(data, dict) else data
    return [j for j in jobs if isinstance(j, dict)] if isinstance(jobs, list) else []


def job_out(profile: str, j: dict) -> dict:
    sched = j.get("schedule") if isinstance(j.get("schedule"), dict) else {}
    rep = j.get("repeat") if isinstance(j.get("repeat"), dict) else {}
    done = j.get("state") == "completed"         # a one-off reminder that has fired (Hermes keeps it, switched off)
    paused = not done and (bool(j.get("paused_at")) or j.get("state") == "paused" or j.get("enabled") is False)
    err = j.get("last_error")
    return {
        "id": str(j.get("id")), "profile": profile, "name": str(j.get("name") or "")[:120],
        "schedule": str(j.get("schedule_display") or sched.get("display") or sched.get("expr") or "")[:80],
        "expr": str(sched.get("expr") or "")[:80],
        "state": "completed" if done else "paused" if paused else str(j.get("state") or "scheduled"),
        "nextAt": _iso_ms(j.get("next_run_at")), "lastAt": _iso_ms(j.get("last_run_at")),
        "lastStatus": j.get("last_status") if isinstance(j.get("last_status"), str) else None,
        "lastError": NUMBER.sub("[number]", str(err))[:300] if err else None,
        "failures": int(j.get("failure_streak") or 0),
        "deliver": str(j.get("deliver") or "")[:40],
        "mode": "script" if j.get("no_agent") else "agent",
        "script": str(j.get("script") or "")[:120] or None,
        "prompt": NUMBER.sub("[number]", str(j.get("prompt") or ""))[:1200],
        "repeat": {"times": rep.get("times"), "done": rep.get("completed")} if rep.get("times") else None,
        "skills": [str(s) for s in (j.get("skills") or [])][:10] if isinstance(j.get("skills"), list) else [],
        "model": str(j.get("model") or "")[:60] or None,
    }


def list_all(env: Env) -> dict:
    out = []
    for p in env.profiles():
        out += [job_out(p, j) for j in _jobs(env, p)]
    return {"jobs": out}


def _profile(env: Env, profile: str) -> str:
    profile = crew.profile_of(env.hermes_home, profile)
    if profile not in env.profiles():
        raise ActionError(404, "No such agent")
    return profile


def _known(env: Env, profile: str, job: str) -> dict:
    if not JOB_RE.match(job or ""):
        raise ActionError(404, "No such automation")
    found = next((j for j in _jobs(env, profile) if str(j.get("id")) == job), None)
    if not found:
        raise ActionError(404, "No such automation on this agent")
    return found


def _text(args: dict, key: str, required: bool) -> str | None:
    v = args.get(key)
    if v is None and not required:
        return None
    if not isinstance(v, str) or (required and not v.strip()) or len(v) > LIMITS[key]:
        raise ActionError(400, f"{key} is missing or too long")
    return v.replace("\r\n", "\n").strip()


def _schedule(args: dict, required: bool) -> str | None:
    v = args.get("schedule")
    if v is None and not required:
        return None
    if not isinstance(v, str) or not SCHEDULE_RE.match(v.strip()):
        raise ActionError(400, "A schedule like 'every 2h', '30m' or '0 9 * * *'")
    return v.strip()


def _deliver(args: dict, required: bool) -> str | None:
    v = args.get("deliver")
    if v is None and not required:
        return None
    if not isinstance(v, str) or not DELIVER_RE.match(v):
        raise ActionError(400, "Deliver to telegram, origin or local")
    return v


def act(env: Env, profile: str, job: str, verb: str) -> dict:
    profile = _profile(env, profile)
    with _lock:
        _known(env, profile, job)
        if verb == "pause":
            cli(env, *_p(profile), "cron", "pause", "--", job)
        elif verb == "resume":
            cli(env, *_p(profile), "cron", "resume", "--", job)
        elif verb == "run":
            cli(env, *_p(profile), "cron", "run", "--", job)
        else:
            raise ActionError(400, "pause, resume or run")
        log_action(env, f"cron-{verb}", profile=profile, job=job)
    return list_all(env)


def remove(env: Env, profile: str, job: str) -> dict:
    profile = _profile(env, profile)
    with _lock:
        _known(env, profile, job)
        cli(env, *_p(profile), "cron", "remove", "--", job)
        log_action(env, "cron-removed", profile=profile, job=job)
    return list_all(env)


def edit(env: Env, profile: str, job: str, args: dict) -> dict:
    profile = _profile(env, profile)
    flags: list[str] = []
    for key, flag, value in (("name", "--name", _text(args, "name", False)), ("schedule", "--schedule", _schedule(args, False)),
                             ("prompt", "--prompt", _text(args, "prompt", False)), ("deliver", "--deliver", _deliver(args, False))):
        if value is not None:
            flags += [f"{flag}={value}"]          # = keeps a value that starts with a dash from looking like an option
    if not flags:
        raise ActionError(400, "Nothing to change")
    with _lock:
        _known(env, profile, job)
        cli(env, *_p(profile), "cron", "edit", *flags, "--", job)
        log_action(env, "cron-edited", profile=profile, job=job, changed=[f.split("=")[0] for f in flags])
    return list_all(env)


def create(env: Env, args: dict) -> dict:
    profile = _profile(env, str(args.get("profile") or ""))
    schedule = _schedule(args, True)
    prompt = _text(args, "prompt", True)
    name = _text(args, "name", False)
    deliver = _deliver(args, False) or "telegram"
    flags = [f"--deliver={deliver}"] + ([f"--name={name}"] if name else [])
    with _lock:
        cli(env, *_p(profile), "cron", "create", *flags, "--", schedule, prompt)
        log_action(env, "cron-created", profile=profile, schedule=schedule)
    return list_all(env)
