"""Command Center bridge: serves the dashboard and a small /api in front of Mem0 on the VM.

Python standard library only, one process (`hermes-dash.service`, user `hermes`), listening on 127.0.0.1:8890 and published
tailnet-only by `tailscale serve --https=8444`. See README.md in this folder.

Rules it keeps:
- Every request needs the `Tailscale-User-Login` header that `tailscale serve` adds, and the login must be on the allow list.
- Writes also need `X-Hermes-Dash: 1` and a JSON body (a plain cross-site form cannot send either).
- Mem0: list, search, add, update and delete notes of one user only (hermes.json's owner.id). Never /reset, /configure or a delete-all.
- No key ever leaves the VM: the Mem0 key is read from the server's env file and only sent to 127.0.0.1:8888.
"""
from __future__ import annotations

import argparse
import datetime as dt
import http.server
import json
import logging
import mimetypes
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))   # `python3 -I` does not add the script's folder
import actions  # noqa: E402
import feeds  # noqa: E402
import automations  # noqa: E402
import brain  # noqa: E402
import team  # noqa: E402
import inbox  # noqa: E402
import integrations  # noqa: E402
import registry  # noqa: E402
import review  # noqa: E402
import jobs  # noqa: E402
import settings  # noqa: E402
import studio  # noqa: E402
import tools  # noqa: E402
import terminal  # noqa: E402

VERSION = "1.0.0"
log = logging.getLogger("hermes-dash")

MEMORY_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
MAX_BODY = 65_536          # a SOUL can be 20,000 characters
MAX_TEXT = 2_000
MAX_QUERY = 500

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")

Response = tuple[int, dict[str, str], bytes]


class Mem0Error(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# -- Mem0 -------------------------------------------------------------------------------------------------------------------

class Mem0:
    """The few Mem0 REST calls the dashboard needs, always for one user."""

    def __init__(self, base: str, key: str, user: str, timeout: float = 8.0):
        self.base = base.rstrip("/")
        self.key = key
        self.user = user
        self.timeout = timeout

    def _call(self, method: str, path: str, body: dict | None = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"X-API-Key": self.key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                raw = res.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise Mem0Error(404, "No such memory (it may have been deleted)") from None
            raise Mem0Error(502, f"Mem0 answered HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise Mem0Error(502, "Mem0 is not answering on the VM") from None
        try:
            return json.loads(raw or b"null")
        except ValueError:
            raise Mem0Error(502, "Mem0 sent something that is not JSON") from None

    @staticmethod
    def _rows(payload: Any) -> list[dict]:
        rows = payload.get("results", []) if isinstance(payload, dict) else payload
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []

    def list(self) -> list[dict]:
        # Mem0's per-user listing returns only 20 unless asked; 1,000 is its ceiling.
        return self._rows(self._call("GET", f"/memories?user_id={self.user}&top_k=1000"))

    def get(self, memory_id: str) -> dict:
        row = self._call("GET", f"/memories/{memory_id}")
        if not isinstance(row, dict) or row.get("user_id") not in (None, self.user):
            raise Mem0Error(404, "No such memory")
        return row

    def search(self, query: str, top_k: int) -> list[dict]:
        return self._rows(self._call("POST", "/search", {"query": query, "filters": {"user_id": self.user}, "top_k": top_k}))

    def add(self, text: str) -> str | None:
        rows = self._rows(self._call("POST", "/memories", {
            "messages": [{"role": "user", "content": text}], "user_id": self.user, "agent_id": "dashboard",
            "infer": False, "metadata": {"source": "dashboard"}}))
        return next((str(r["id"]) for r in rows if r.get("id")), None)

    def update(self, memory_id: str, text: str) -> None:
        self._call("PUT", f"/memories/{memory_id}", {"text": text})

    def delete(self, memory_id: str) -> None:
        self._call("DELETE", f"/memories/{memory_id}")


def _ms(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        when = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return int(when.timestamp() * 1000)


def memory_out(row: dict) -> dict:
    """Mem0's row in the page's shape (dashboard/src/telemetry/types.ts: Memory)."""
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    agent = str(row.get("agent_id") or "").lower()
    author = ("import" if agent == "holographic-import" else "dashboard" if agent == "dashboard"
              else agent if re.match(r"^[a-z][a-z0-9-]{0,23}$", agent) else "unknown")   # the agents, and tools like claude-code
    source = meta.get("source")
    category = meta.get("category")
    created = _ms(row.get("created_at")) or 0
    updated = _ms(row.get("updated_at"))
    return {
        "id": str(row.get("id")),
        "text": str(row.get("memory") or row.get("data") or ""),
        "author": author,
        "source": source if isinstance(source, str) else None,
        "category": category if isinstance(category, str) else None,
        "createdAt": created,
        "updatedAt": updated if updated and updated != created else None,
        "metadata": {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool)) or v is None},
    }


# -- the app ----------------------------------------------------------------------------------------------------------------

FEEDS: dict[str, Callable[..., dict]] = {
    "/agents": feeds.agents, "/infra": feeds.infra, "/board": feeds.board,
}


class App:
    def __init__(self, mem0: Mem0, static_dir: Path, allowed_logins: list[str], paths: feeds.Paths | None = None,
                 env: actions.Env | None = None):
        self.mem0 = mem0
        self.static_dir = static_dir.resolve()
        self.allowed = {a.lower() for a in allowed_logins}
        self.paths = paths or feeds.Paths()
        self.env = env or actions.Env(hermes_home=self.paths.hermes_home, gateway_url=self.paths.gateway_url)
        self.studio = studio.Store(self.paths)
        self.registry_file: Path | None = None          # tests point these at fixtures
        self.systemd_dir: Path | None = None

    def registry(self) -> dict:
        return registry.load(self.registry_file)

    # helpers
    @staticmethod
    def _json(status: int, payload: Any, extra: dict[str, str] | None = None) -> Response:
        headers = {"Content-Type": "application/json", "Cache-Control": "no-store", **(extra or {})}
        return status, headers, json.dumps(payload).encode()

    def _error(self, status: int, message: str) -> Response:
        return self._json(status, {"error": message})

    def _who(self, headers: dict[str, str]) -> str | None:
        login = (headers.get("tailscale-user-login") or "").strip().lower()
        if not login:
            return None
        return login if not self.allowed or login in self.allowed else ""

    @staticmethod
    def _body(body: bytes, headers: dict[str, str]) -> dict | None:
        if "application/json" not in headers.get("content-type", ""):
            return None
        try:
            value = json.loads(body or b"{}")
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _text(args: dict, key: str, limit: int) -> str | None:
        value = args.get(key)
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value if 0 < len(value) <= limit else None

    # one request
    def handle(self, method: str, path: str, headers: dict[str, str], body: bytes) -> Response:
        route, _, query = path.partition("?")
        who = self._who(headers)
        if who is None:
            return self._error(401, "Open the dashboard through its Tailscale address (no Tailscale identity on this request)")
        if who == "":
            return self._error(403, "This Tailscale login is not on the bridge's allow list")
        if route.startswith("/api/"):
            try:
                return self._api(method, route[4:], headers, body, query)
            except (Mem0Error, actions.ActionError) as exc:
                return self._error(exc.status, str(exc))
        if method not in ("GET", "HEAD"):
            return self._error(405, "GET only")
        return self._static(route)

    def _api(self, method: str, route: str, headers: dict[str, str], body: bytes, query: str = "") -> Response:
        if route == "/health" and method == "GET":
            return self._json(200, {"ok": True, "version": VERSION})
        if route == "/team" and method == "GET":
            # names, titles and switched-on add-ons for the page (team.py); a renamed agent shows its new name
            home = self.paths.hermes_home
            return self._json(200, team.public(home, lambda p: actions.profile_meta(actions.Env(hermes_home=home), p).get("display_name")))
        if method in ("POST", "PUT", "DELETE"):
            if headers.get("x-hermes-dash") != "1":
                return self._error(403, "Writes come only from the dashboard page")
            if len(body) > MAX_BODY:
                return self._error(413, "Too large")

        if route.startswith("/studio/"):
            return self._studio(method, route, headers, body)

        m = re.fullmatch(r"/agents/([a-z][a-z0-9]{0,23})/terminal", route)
        if m and method == "GET":
            # Agent Studio's terminal window: the agent's own session database, read only (terminal.py)
            profile = team.profile_of(self.paths.hermes_home, m.group(1))
            if profile not in feeds.known_profiles(self.paths.hermes_home):
                return self._error(404, "No such agent")
            q = urllib.parse.parse_qs(query)
            session = (q.get("session") or [""])[0]
            after = (q.get("after") or ["0"])[0]
            if session and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", session):
                return self._error(400, "Bad session id")
            try:
                return self._json(200, terminal.view(self.paths, profile, session or None, int(after) if after.isdigit() else 0))
            except sqlite3.Error as exc:
                log.warning("terminal %s failed: %s", profile, type(exc).__name__)
                return self._error(502, "Could not read that agent's log right now")

        if route == "/infra" and method == "GET":
            credit = settings.load(self.env).get("credit")
            if credit:
                self.paths.credit = credit                  # the snapshot typed in Settings beats config.json's
        if route in FEEDS and method == "GET":
            try:
                if route == "/infra":
                    return self._json(200, FEEDS[route](self.paths, service_rows=registry.service_list(self.registry(), self.systemd_dir)))
                return self._json(200, FEEDS[route](self.paths))
            except Exception as exc:  # noqa: BLE001 - say which view failed, never the details
                log.warning("feed %s failed: %s", route, type(exc).__name__)
                return self._error(502, f"Could not read {route[1:]} on the VM ({type(exc).__name__})")

        write = self._writes(method, route, headers, body)
        if write is not None:
            return write

        if route == "/memories" and method == "GET":
            return self._json(200, {"memories": [memory_out(r) for r in self.mem0.list()]})

        if route == "/memories/search" and method == "POST":
            args = self._body(body, headers)
            query = self._text(args or {}, "query", MAX_QUERY)
            if query is None:
                return self._error(400, "Send a search of 1 to 500 characters")
            top_k = args.get("top_k", 12) if args else 12
            top_k = top_k if isinstance(top_k, int) and 1 <= top_k <= 50 else 12
            hits = [{"id": str(r.get("id")), "score": float(r.get("score") or 0)} for r in self.mem0.search(query, top_k) if r.get("id")]
            return self._json(200, {"results": hits})

        if route == "/memories" and method == "POST":
            text = self._text(self._body(body, headers) or {}, "text", MAX_TEXT)
            if text is None:
                return self._error(400, "Send the note as text of 1 to 2,000 characters")
            args = self._body(body, headers) or {}
            new_id = self.mem0.add(text)
            if not new_id:
                return self._error(502, "Mem0 did not store the note (it may already exist word for word)")
            log.info("memory added %s", new_id)
            section, label = args.get("section"), args.get("newSection")
            if isinstance(label, str) and label.strip() or isinstance(section, str) and section:
                try:
                    brain.assign(self.env, new_id, section if isinstance(section, str) else None,
                                 label.strip() if isinstance(label, str) and label.strip() else None)
                except actions.ActionError:
                    pass                                        # the runner sorts it with the rest
            return self._json(200, {"memory": memory_out(self.mem0.get(new_id))})

        match = re.fullmatch(r"/memories/([^/]+)/pin", route)
        if match and method == "PUT":
            if not MEMORY_ID.match(match.group(1)):
                return self._error(400, "That is not a Mem0 id")
            args = self._body(body, headers) or {}
            if not isinstance(args.get("pinned"), bool):
                return self._error(400, "Send {pinned: true or false}")
            self.mem0.get(match.group(1))                      # refuses notes of any other user
            out = review.set_pin(self.env, match.group(1), args["pinned"])
            return self._json(200, {"pins": out["pins"]})
        match = re.fullmatch(r"/memories/([^/]+)", route)
        if match:
            memory_id = match.group(1)
            if not MEMORY_ID.match(memory_id):
                return self._error(400, "That is not a Mem0 id")
            if method == "PUT":
                text = self._text(self._body(body, headers) or {}, "text", MAX_TEXT)
                if text is None:
                    return self._error(400, "Send the note as text of 1 to 2,000 characters")
                self.mem0.get(memory_id)                       # refuses notes of any other user
                self.mem0.update(memory_id, text)
                log.info("memory updated %s", memory_id)
                return self._json(200, {"memory": memory_out(self.mem0.get(memory_id))})
            if method == "DELETE":
                self.mem0.get(memory_id)
                self.mem0.delete(memory_id)
                brain.forget(self.env, memory_id)
                review.forget(self.env, memory_id)
                log.info("memory deleted %s", memory_id)
                return self._json(200, {"ok": True})
        return self._error(404, "Not found")

    def _writes(self, method: str, route: str, headers: dict[str, str], body: bytes) -> Response | None:
        """Agent profiles, the restart request, briefing the chief, the board (actions.py has the rules)."""
        env = self.env
        args = (self._body(body, headers) or {}) if method in ("POST", "PUT", "DELETE") else {}
        if method in ("POST", "PUT") and self._body(body, headers) is None:
            return self._error(400, "Send JSON")
        m = re.fullmatch(r"/agents/([a-z][a-z0-9]{0,23})", route)
        if m:
            profile = team.profile_of(env.hermes_home, m.group(1))
            if method == "GET":
                return self._json(200, actions.agent_detail(env, profile))
            if method == "PUT":
                if "reportsTo" in args:   # agents are added and moved only through Claude, never from the dashboard
                    return self._error(405, "Agents are moved through Claude, not the dashboard")
                return self._json(200, actions.update_agent(env, profile, args))
            if method == "DELETE":
                return self._json(200, actions.delete_agent(env, profile, args))
            return self._error(405, "GET, PUT or DELETE")
        if route == "/agents" and method == "POST":
            return self._error(405, "Agents are added through Claude, not the dashboard")
        if route == "/restart":
            if method == "POST":
                return self._json(200, actions.request_restart(env))
            if method == "GET":
                shown = feeds.parse_show(feeds._systemctl("show", "hermes-gateway.service", "-p", "ActiveEnterTimestamp", "--timestamp=unix"))
                started = feeds._unix((shown or [{}])[0].get("ActiveEnterTimestamp"))
                return self._json(200, actions.restart_state(env, started))
        if route == "/chief/brief" and method == "POST":
            return self._json(200, actions.brief_chief(env, args))
        m = re.fullmatch(r"/chief/runs/([A-Za-z0-9_-]{4,80})", route)
        if m and method == "GET":
            return self._json(200, actions.chief_run(env, m.group(1)))
        if route == "/board/cards" and method == "POST":
            return self._json(200, actions.create_card(env, args))
        m = re.fullmatch(r"/board/cards/([^/]+)/answer", route)
        if m and method == "POST":
            return self._json(200, actions.answer_card(env, m.group(1), args))
        return self._tools(method, route, args)

    def _tools(self, method: str, route: str, args: dict) -> Response | None:
        """Skills and MCP servers per agent, AI enhance, the hub, the inbox, the brain, backup now (tools.py, jobs.py)."""
        env = self.env
        m = re.fullmatch(r"/jobs/([a-f0-9]{16})", route)
        if m and method == "GET":
            return self._json(200, jobs.status(env, m.group(1)))
        if route == "/enhance" and method == "POST":
            return self._json(202, jobs.submit(env, "enhance", args))
        m = re.fullmatch(r"/agents/([a-z][a-z0-9]{0,23})/skills(?:/(search|inspect|install)|/([a-z0-9][a-z0-9_-]{1,47}))?", route)
        if m:
            profile, verb, name = team.profile_of(env.hermes_home, m.group(1)), m.group(2), m.group(3)
            if verb and method == "POST":
                return self._json(202, jobs.submit(env, f"skill-{verb}", {**args, "profile": profile}))
            if name and method == "PUT":
                if not isinstance(args.get("enabled"), bool):
                    return self._error(400, "enabled is true or false")
                return self._json(200, tools.set_skill_enabled(env, profile, name, args["enabled"]))
            if name and method == "DELETE":
                return self._json(200, tools.remove_skill(env, profile, name))
            if not verb and not name and method == "GET":
                return self._json(200, tools.list_skills(env, profile))
            if not verb and not name and method == "POST":
                return self._json(200, tools.create_skill(env, profile, args))
            return self._error(405, "Not here")
        if route == "/mcp":
            if method == "GET":
                return self._json(200, tools.list_servers(env))
            if method == "POST":
                return self._json(200, tools.add_server(env, args))
        if route == "/mcp/catalog" and method == "GET":
            return self._json(200, {"entries": [{k: v for k, v in e.items() if k != "config"} for e in tools.catalog(env)]})
        m = re.fullmatch(r"/mcp/([a-z][a-z0-9_-]{1,39})/([a-z][a-z0-9]{0,23})", route)
        if m and method == "DELETE":
            return self._json(200, tools.remove_server(env, team.profile_of(env.hermes_home, m.group(2)), m.group(1)))
        if route in ("/integrations", "/integrations/refresh") and method in ("GET", "POST"):
            job = self._single("integrations") if route.endswith("refresh") or integrations.stale(env) else None
            reg = self.registry()
            try:
                servers = tools.list_servers(env)["servers"]
            except actions.ActionError:
                servers = []                                # a config Hermes' Python cannot read: the hub still shows the rest
            hub = integrations.hub(env, automations.list_all(env)["jobs"], feeds.backup_state(), reg=reg,
                                   servers=servers, keys=registry.key_names(env), catalog=tools.catalog(env),
                                   units=feeds.unit_states(sorted({i["service"] for i in reg["integrations"] if i.get("service")})))
            return self._json(200, {**hub, "job": job})
        if route.startswith("/inbox") and not team.feature(env.hermes_home, "gmail"):
            return self._error(404, "The Gmail add-on is not switched on")
        if route in ("/inbox", "/inbox/refresh") and method in ("GET", "POST"):
            job = self._single("inbox-list") if route.endswith("refresh") or inbox.list_stale(env) else None
            return self._json(200, {"list": inbox.cached_list(env), "summary": inbox.cached_summary(env), "job": job})
        if route == "/inbox/summary" and method == "POST":
            return self._json(202, {"job": self._single("inbox-summary")})
        m = re.fullmatch(r"/inbox/(inbox|drafts)/(\d{1,12})", route)
        if m and method == "GET":
            return self._json(202, jobs.submit(env, "inbox-read", {"folder": m.group(1), "uid": m.group(2)}))
        if route == "/settings":
            if method == "GET":
                return self._json(200, settings.view(env))
            if method == "PUT":
                return self._json(200, settings.save(env, args))
        if route == "/balances" and method in ("GET", "POST"):
            cached = settings.cached_balances(env)
            refreshing = None
            if method == "POST" or settings.balances_stale(env):
                pending = getattr(self, "_balances_job", None)
                if pending and not self._job_gone(pending):
                    refreshing = pending                        # one refresh at a time
                else:
                    try:
                        refreshing = jobs.submit(env, "balances", {})["job"]
                        self._balances_job = refreshing
                    except actions.ActionError:
                        refreshing = None
            return self._json(200, {"balances": cached, "job": refreshing})
        if route == "/brain" and method == "GET":
            memories = [memory_out(r) for r in self.mem0.list()]
            data = brain.load(env)
            todo = brain.unsorted(env, memories)
            stuck = data["pending"] and self._job_gone(data["pending"])
            if todo and (not data["pending"] or stuck):
                try:
                    brain.set_pending(env, jobs.submit(env, "brain-sort", {"notes": todo})["job"])
                except actions.ActionError:
                    pass
            # the weekly check-up starts by itself when the page is open and the last one is a week old
            r = review.load(env)
            if review.due(env) or (r["pending"] and self._job_gone(r["pending"])):
                try:
                    review.set_pending(env, jobs.submit(env, "brain-review", review.job_args(env, memories))["job"])
                except actions.ActionError:
                    pass
            rv = review.view(env)
            return self._json(200, {**brain.view(env, [m["id"] for m in memories]), "pins": rv["pins"],
                                    "review": {"open": len(rv["items"]), "running": rv["running"], "at": rv["at"], "nextAt": rv["nextAt"]}})
        if route == "/brain/review" and method == "GET":
            return self._json(200, review.view(env))
        if route == "/brain/review" and method == "POST":
            if review.load(env)["pending"] and not self._job_gone(review.load(env)["pending"]):
                return self._json(202, {"job": review.load(env)["pending"]})
            memories = [memory_out(r) for r in self.mem0.list()]
            if not memories:
                return self._error(400, "There are no notes to check")
            job = jobs.submit(env, "brain-review", review.job_args(env, memories))["job"]
            review.set_pending(env, job)
            return self._json(202, {"job": job})
        m = re.fullmatch(r"/brain/review/([a-f0-9]{12})/(apply|dismiss)", route)
        if m and method == "POST":
            if m.group(2) == "dismiss":
                return self._json(200, review.dismiss(env, m.group(1)))
            out = review.apply(env, self.mem0, m.group(1))
            log.info("brain review applied %s", m.group(1))
            return self._json(200, out)
        m = re.fullmatch(r"/brain/sections/([a-z][a-z0-9-]{1,31})", route)
        if m and method == "PUT":
            return self._json(200, brain.rename(env, m.group(1), args))
        if m and method == "DELETE":
            return self._json(200, brain.merge(env, m.group(1), args.get("into")))
        if route == "/brain/resort" and method == "POST":
            return self._json(200, brain.resort(env))
        if route == "/memories/tidy" and method == "POST":
            return self._json(202, jobs.submit(env, "memory-tidy", args))
        if route == "/registry" and method == "GET":
            reg = self.registry()
            view = registry.page_view(reg, team.load(env.hermes_home))
            view["services"] = {r["unit"]: {"label": r["label"], "port": r["port"], "described": r["described"]}
                                for r in registry.service_list(reg, self.systemd_dir)}
            return self._json(200, view)
        if route == "/automations":
            if method == "GET":
                rows = registry.timer_list(self.registry(), self.systemd_dir)
                state = feeds.timers([r["unit"] for r in rows])
                return self._json(200, {**automations.list_all(env), "timers": [{**r, **state.get(r["unit"], {"nextAt": None, "lastAt": None})} for r in rows]})
            if method == "POST":
                return self._json(200, automations.create(env, args))
        m = re.fullmatch(r"/automations/([a-z][a-z0-9]{0,23})/([a-f0-9]{8,32})(?:/(pause|resume|run))?", route)
        if m:
            profile, job, verb = team.profile_of(env.hermes_home, m.group(1)), m.group(2), m.group(3)
            if verb and method == "POST":
                return self._json(200, automations.act(env, profile, job, verb))
            if not verb and method == "PUT":
                return self._json(200, automations.edit(env, profile, job, args))
            if not verb and method == "DELETE":
                return self._json(200, automations.remove(env, profile, job))
            return self._error(405, "Not here")
        if route == "/backup":
            if not team.feature(env.hermes_home, "backup"):
                return self._error(404, "The backup add-on is not switched on")
            shown = (feeds.parse_show(feeds._systemctl("show", "hermes-backup.service", "-p", "ActiveState,Result")) or [{}])[0]
            if method == "GET":
                return self._json(200, actions.backup_state(env, shown))
            if method == "POST":
                return self._json(200, actions.request_backup(env, shown))
        return None

    def _single(self, kind: str) -> str | None:
        """One job of this kind at a time: the one already waiting, or a new one."""
        pending = getattr(self, "_pending", None)
        if pending is None:
            pending = self._pending = {}
        cur = pending.get(kind)
        if cur and not self._job_gone(cur):
            return cur
        try:
            pending[kind] = jobs.submit(self.env, kind, {})["job"]
        except actions.ActionError:
            return None
        return pending[kind]

    def _job_gone(self, job: str) -> bool:
        """A sort job that finished without clearing itself, or vanished: start a new one."""
        try:
            return jobs.status(self.env, job).get("state") == "done"
        except actions.ActionError:
            return True

    def _studio(self, method: str, route: str, headers: dict[str, str], body: bytes) -> Response:
        """The content studio page (studio.py): clips, overlay lines, sounds, the queue and the style. Uploads and file downloads are streamed by stream()."""
        st, env = self.studio, self.env
        args = (self._body(body, headers) or {}) if method in ("POST", "PUT", "DELETE") else {}
        if method in ("POST", "PUT") and self._body(body, headers) is None:
            return self._error(400, "Send JSON")
        if route == "/studio/status" and method == "GET":
            return self._json(200, studio.status(st, env))
        if route == "/studio/voice" and method == "GET":
            return self._json(200, studio.get_voice(st))
        post = {"/studio/plan": lambda: studio.plan_now(st, env), "/studio/propose": lambda: studio.propose(st, env, args), "/studio/style": lambda: studio.set_style(st, env, args),
                "/studio/settings": lambda: studio.set_settings(st, env, args), "/studio/voice": lambda: studio.set_voice(st, env, args), "/studio/lines": lambda: studio.add_lines(st, env, args),
                "/studio/sounds": lambda: studio.add_sound(st, env, args), "/studio/failures/clear": lambda: studio.clear_failures(st, env)}
        if method == "POST" and route in post:
            return self._json(200, post[route]())
        m = re.fullmatch(r"/studio/(lines|sounds|clips|queue)/([a-z]_[0-9a-f]{8})", route)
        if m:
            kind, ident = m.groups()
            if method == "POST":
                fn = {"lines": studio.set_line, "sounds": studio.set_sound, "clips": studio.clip_action, "queue": studio.post_action}[kind]
                return self._json(200, fn(st, env, ident, args))
            if method == "DELETE" and kind in ("lines", "sounds", "clips"):
                fn = {"lines": studio.delete_line, "sounds": studio.delete_sound, "clips": studio.delete_clip}[kind]
                return self._json(200, fn(st, env, ident))
        return self._error(404, "Not found")

    def stream(self, h: Any) -> bool:
        """Clip and font uploads and the studio's files (stills, videos), which do not fit handle()'s bytes-in, bytes-out shape: a clip can be gigabytes. True when this request was one of them."""
        path, _, query = h.path.partition("?")
        if not path.startswith("/api/studio/"):
            return False
        put = h.command == "PUT"
        up = re.fullmatch(r"/api/studio/(clips|fonts)/([^/]+)", path) if put else None
        get = re.fullmatch(r"/api/studio/file/(thumbs|out|clips)/([^/]+)", path) if h.command in ("GET", "HEAD") else None
        if not (up or get):
            return False
        headers = {k.lower(): v for k, v in h.headers.items()}
        who = self._who(headers)
        total = int(headers.get("content-length") or 0) if up else 0
        got = [0]

        def read(n: int) -> bytes:
            chunk = h.rfile.read(n)
            got[0] += len(chunk)
            return chunk

        def drain() -> None:
            """A refusal before the whole body arrived: take a small rest of it off the wire first, or the browser sees a reset instead of the reason."""
            left = total - got[0]
            while 0 < left <= 64 * 1024 * 1024:
                try:
                    chunk = h.rfile.read(min(1024 * 1024, left))
                except OSError:
                    return
                if not chunk:
                    return
                left -= len(chunk)

        def reply(status: int, hdrs: dict[str, str], payload: bytes) -> None:
            try:
                send(h, status, hdrs, payload)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):          # the browser went away; nothing to tell it
                h.close_connection = True

        try:
            if who is None:
                raise actions.ActionError(401, "Open the dashboard through its Tailscale address (no Tailscale identity on this request)")
            if who == "":
                raise actions.ActionError(403, "This Tailscale login is not on the bridge's allow list")
            if up:
                if headers.get("x-hermes-dash") != "1":
                    raise actions.ActionError(403, "Writes come only from the dashboard page")
                name = urllib.parse.unquote(up.group(2))
                if up.group(1) == "clips":
                    result = studio.accept_clip(self.studio, self.env, name, total, read)
                else:
                    result = studio.accept_font(self.studio, self.env, name, total, read)
                reply(*self._json(200, result))
                return True
            media, ctype = studio.served_file(self.studio, get.group(1), urllib.parse.unquote(get.group(2)))
            send_file(h, media, ctype, "private, max-age=300" if media.suffix == ".jpg" else "no-store", download=("download" in urllib.parse.parse_qs(query)))
        except actions.ActionError as exc:
            drain()
            reply(*self._error(exc.status, str(exc)))
        except (ValueError, TypeError):
            drain()
            reply(*self._error(400, "That request is not valid"))
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError) as exc:
            log.info("studio stream ended early: %s", type(exc).__name__)
            h.close_connection = True
        return True

    def _static(self, route: str) -> Response:
        rel = route.lstrip("/") or "index.html"
        target = (self.static_dir / rel).resolve()
        if not target.is_relative_to(self.static_dir) or not target.is_file():
            # The page routes by #hash, so an unknown path is a typo or a probe: give it the page, not a listing.
            target = self.static_dir / "index.html"
            if not target.is_file():
                return self._error(503, "The dashboard is not built on this machine (dist/ is missing)")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        cache = "public, max-age=31536000, immutable" if "/assets/" in f"/{rel}" and target.name != "index.html" else "no-cache"
        return 200, {"Content-Type": ctype, "Cache-Control": cache}, target.read_bytes()


SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def send(h: Any, status: int, headers: dict[str, str], payload: bytes) -> None:
    h.send_response(status)
    for k, v in {**SECURITY_HEADERS, **headers}.items():
        h.send_header(k, v)
    h.send_header("Content-Length", str(len(payload)))
    h.end_headers()
    if h.command != "HEAD":
        h.wfile.write(payload)


def send_file(h: Any, path: Path, ctype: str, cache: str, download: bool = False) -> None:
    """A file from disk with Range support (a preview must play and seek in the browser), read in 1 MB pieces."""
    size = path.stat().st_size
    rng = studio.parse_range(h.headers.get("Range"), size)
    if rng is False:
        h.send_response(416)
        h.send_header("Content-Range", f"bytes */{size}")
        h.send_header("Content-Length", "0")
        h.end_headers()
        return
    start, end = rng if rng else (0, size - 1)
    h.send_response(206 if rng else 200)
    for k, v in SECURITY_HEADERS.items():
        h.send_header(k, v)
    h.send_header("Content-Type", ctype)
    h.send_header("Accept-Ranges", "bytes")
    h.send_header("Cache-Control", cache)
    h.send_header("Content-Length", str(max(0, end - start + 1)) if size else "0")
    if rng:
        h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    if download:
        h.send_header("Content-Disposition", 'attachment; filename="' + re.sub(r"[^A-Za-z0-9._ -]", "_", path.name) + '"')
    h.end_headers()
    if h.command == "HEAD" or not size:
        return
    with open(path, "rb") as f:
        f.seek(start)
        left = end - start + 1
        while left > 0:
            chunk = f.read(min(1024 * 1024, left))
            if not chunk:
                break
            h.wfile.write(chunk)
            left -= len(chunk)


def make_server(app: App, host: str = "127.0.0.1", port: int = 8890) -> http.server.ThreadingHTTPServer:
    class Handler(http.server.BaseHTTPRequestHandler):
        timeout = 30
        def version_string(self) -> str:
            return "hermes-dash"

        def _serve(self) -> None:
            if app.stream(self):                                           # uploads and files that can be large are streamed, not read whole
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                status, headers, payload = App._json(413, {"error": "Too large"})
            else:
                raw = self.rfile.read(length) if length else b""
                lower = {k.lower(): v for k, v in self.headers.items()}
                try:
                    status, headers, payload = app.handle(self.command, self.path, lower, raw)
                except Exception as exc:  # noqa: BLE001 - never leak details to the browser
                    log.warning("request failed: %s", type(exc).__name__)
                    status, headers, payload = App._json(500, {"error": "Internal error"})
            if self.path.startswith("/api/"):
                log.info("%s %s -> %d", self.command, self.path.split("?")[0], status)
            self.send_response(status)
            for k, v in {**SECURITY_HEADERS, **headers}.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = _serve

        def log_message(self, *args: Any) -> None:
            pass

    return http.server.ThreadingHTTPServer((host, port), Handler)


def read_env_value(path: Path, name: str) -> str:
    """One value from a KEY=value env file, without loading the rest (the file also holds other secrets)."""
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key.removeprefix("export ").strip() == name:
            return value.strip().strip("'\"")
    raise SystemExit(f"{name} not found in {path}")


def main(argv: list[str] | None = None, serve: Callable[[http.server.HTTPServer], None] = lambda s: s.serve_forever()) -> None:
    parser = argparse.ArgumentParser(description="Command Center bridge")
    parser.add_argument("--config", default="/data/.hermes/hermes-dash/config.json")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    cfg = json.loads(Path(args.config).read_text())
    key = read_env_value(Path(cfg.get("mem0_env", "/data/.hermes/mem0-server/server.env")), "ADMIN_API_KEY")
    paths = feeds.Paths(**{k: v for k, v in cfg.get("feeds", {}).items() if k in feeds.Paths.__dataclass_fields__})
    if "credit" in cfg:
        paths.credit = cfg["credit"]
    env = actions.Env(hermes_home=paths.hermes_home, gateway_url=paths.gateway_url,
                      **{k: v for k, v in cfg.get("actions", {}).items() if k in actions.Env.__dataclass_fields__})
    # the Mem0 user: config.json's (written from hermes.json at install), else hermes.json's owner.id now
    user = cfg.get("mem0_user") or team.load(paths.hermes_home)["owner"]["id"]
    app = App(Mem0(cfg.get("mem0_url", "http://127.0.0.1:8888"), key, user),
              Path(cfg.get("static_dir", "/data/tools/hermes-dash/dist")), list(cfg.get("allowed_logins", [])), paths, env)
    if not app.allowed:
        log.warning("allowed_logins is empty: any tailnet user may use the dashboard")
    server = make_server(app, "127.0.0.1", int(cfg.get("port", 8890)))
    log.info("hermes-dash %s on 127.0.0.1:%d", VERSION, server.server_address[1])
    serve(server)


if __name__ == "__main__":
    main()
