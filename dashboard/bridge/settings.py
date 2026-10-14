"""Dashboard settings: the default model for the dashboard's own AI jobs (AI enhance, tidying and sorting memories),
whether a new memory is tidied by default, the Azure credit snapshot, and the cached balances of the paid services
(DeepSeek, and ElevenLabs with the voice add-on; Gemini has no balance API). Stored in `<state>/settings.json` and
`<state>/balances.json`; no key is ever stored here or sent to the page.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from actions import ActionError, Env, _lock, log_action

# Models the dashboard's jobs can call, by provider; a provider is offered only when its key is in /data/.hermes/.env.
MODELS: dict[str, dict[str, str]] = {
    "deepseek-flash": {"provider": "deepseek", "label": "DeepSeek Flash", "note": "what the agents use; about 0.01p a rewrite"},
    "deepseek-v4-pro": {"provider": "deepseek", "label": "DeepSeek V4 Pro", "note": "stronger, about 4x the price"},
    "gemini-2.5-flash": {"provider": "gemini", "label": "Gemini 2.5 Flash", "note": "your AI Studio key: free tier unless billing is on"},
    "gemini-2.5-flash-lite": {"provider": "gemini", "label": "Gemini 2.5 Flash Lite", "note": "your AI Studio key: free tier unless billing is on"},
}
KEYS = {"deepseek": "DEEPSEEK_API_KEY", "gemini": "GEMINI_API_KEY"}
DEFAULTS: dict[str, Any] = {"model": "deepseek-flash", "tidyMemories": True}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BALANCES_MAX_AGE = 1800


def _path(env: Env) -> Path:
    return Path(env.state_dir) / "settings.json"


def env_keys(env: Env) -> set[str]:
    """Names (never values) of the keys in the shared .env."""
    out = set()
    try:
        for line in (Path(env.hermes_home) / ".env").read_text().splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and v.strip() and not k.startswith("#"):
                out.add(k.removeprefix("export ").strip())
    except OSError:
        pass
    return out


def load(env: Env) -> dict[str, Any]:
    try:
        data = json.loads(_path(env).read_text())
    except (OSError, ValueError):
        data = {}
    out = {**DEFAULTS, **{k: v for k, v in data.items() if k in ("model", "tidyMemories", "credit")}}
    if out["model"] not in MODELS:
        out["model"] = DEFAULTS["model"]
    return out


def view(env: Env) -> dict[str, Any]:
    have = env_keys(env)
    models = [{"id": m, **spec, "available": KEYS[spec["provider"]] in have} for m, spec in MODELS.items()]
    return {**load(env), "models": models}


def save(env: Env, args: dict) -> dict[str, Any]:
    cur = load(env)
    if "model" in args:
        m = args["model"]
        spec = MODELS.get(m) if isinstance(m, str) else None
        if not spec:
            raise ActionError(400, "Not a model the dashboard knows")
        if KEYS[spec["provider"]] not in env_keys(env):
            raise ActionError(400, f"There is no {spec['provider']} key on the VM")
        cur["model"] = m
    if "tidyMemories" in args:
        if not isinstance(args["tidyMemories"], bool):
            raise ActionError(400, "tidyMemories is true or false")
        cur["tidyMemories"] = args["tidyMemories"]
    if "credit" in args:
        c = args["credit"]
        if not isinstance(c, dict) or not isinstance(c.get("balance"), (int, float)) or not 0 <= c["balance"] <= 10_000 \
                or not isinstance(c.get("as_of"), str) or not DATE_RE.match(c["as_of"]):
            raise ActionError(400, "The credit needs a balance and a date (YYYY-MM-DD)")
        old = cur.get("credit") or {}
        burn = c.get("burn_per_day", old.get("burn_per_day", 1.2))
        if not isinstance(burn, (int, float)) or not 0 < burn < 100:
            raise ActionError(400, "Burn per day must be between 0 and 100")
        cur["credit"] = {"balance": round(float(c["balance"]), 2), "as_of": c["as_of"], "burn_per_day": float(burn),
                         "start": old.get("start", 100)}
    with _lock:
        p = _path(env)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(".settings.json.tmp")
        tmp.write_text(json.dumps(cur, indent=2))
        os.replace(tmp, p)
        log_action(env, "settings-saved", changed=sorted(k for k in args if k in ("model", "tidyMemories", "credit")))
    return view(env)


# -- balances (written by the jobs runner, read by the bridge) -------------------------------------------------------------

def balances_path(env: Env) -> Path:
    return Path(env.state_dir) / "balances.json"


def cached_balances(env: Env) -> dict | None:
    try:
        return json.loads(balances_path(env).read_text())
    except (OSError, ValueError):
        return None


def balances_stale(env: Env) -> bool:
    b = cached_balances(env)
    return not b or time.time() - b.get("at", 0) / 1000 > BALANCES_MAX_AGE
