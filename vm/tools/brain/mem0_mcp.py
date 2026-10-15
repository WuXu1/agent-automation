#!/usr/bin/env python3
"""mem0 MCP server — lets Claude Code share Hermes's memory store.

Speaks the Model Context Protocol over stdin/stdout, and the self-hosted mem0
server's HTTP API over loopback on the far side. Deliberately stdlib-only: it is
launched by Claude Code over SSH on the Hermes box, so nothing has to be
installed on the Mac, and no new port is exposed to reach mem0.

Memory is shared by ``user_id``: Hermes reads and writes as ``user_id: max``, so
whatever Claude Code stores here is recalled by Hermes, and vice versa. Writes
carry ``agent_id: claude-code`` so a memory's origin stays traceable — the
user_id filter is what makes it shared, not the agent_id.

Config comes from the same file Hermes's own mem0 plugin uses:
    /data/.hermes/mem0.json  ->  {host, api_key, user_id, agent_id}

Wire whatever Claude Code gives you on stdout, and log only to stderr: stdout is
the protocol channel and a stray print() corrupts the session.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

CONFIG_PATH = os.environ.get("MEM0_CODE_CONFIG", "/data/.hermes/mem0.json")
AGENT_ID = os.environ.get("MEM0_CODE_AGENT_ID", "claude-code")
DEFAULT_HOST = "http://127.0.0.1:8888"
DEFAULT_USER = "max"
PROTOCOL_FALLBACK = "2024-11-05"
TIMEOUT = float(os.environ.get("MEM0_CODE_TIMEOUT", "60"))
SERVER_INFO = {"name": "mem0", "version": "1.0.0"}


def log(message: str) -> None:
    print(f"mem0-mcp: {message}", file=sys.stderr, flush=True)


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        log(f"cannot read {CONFIG_PATH}: {type(exc).__name__}; using defaults")
        return {}


CFG = load_config()
HOST = str(CFG.get("host") or DEFAULT_HOST).rstrip("/")
API_KEY = str(CFG.get("api_key") or "")
USER_ID = str(CFG.get("user_id") or DEFAULT_USER)


def call(method: str, path: str, payload: dict | None = None) -> tuple[bool, object]:
    """One request to the mem0 server. Returns (ok, data-or-error-text)."""
    url = f"{HOST}{path}"
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read()
        return True, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        return False, f"mem0 returned HTTP {exc.code}: {detail}"
    except Exception as exc:  # noqa: BLE001 - any transport failure is one answer: it did not work
        return False, f"cannot reach mem0 at {HOST}: {type(exc).__name__}"


TOOLS = [
    {
        "name": "mem0_search",
        "description": (
            "Search the shared long-term memory store. This is the same memory Hermes "
            "(Max's assistant) reads and writes, so results can include facts learned in "
            "other conversations, on his phone, or by another agent. Use it before asking "
            "Max something he may have already told the system."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for, in natural language."},
                "top_k": {"type": "integer", "description": "Maximum results (default 10).", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "mem0_add",
        "description": (
            "Store a fact in the shared memory store, verbatim. Use it the moment Max states a "
            "lasting preference, correction, decision or personal detail. Skip transient "
            "chatter. Hermes will recall it from future sessions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The fact to store, as one clear sentence."},
                "infer": {
                    "type": "boolean",
                    "description": "False (default) stores the text as given. True lets mem0 extract and merge facts — slower.",
                    "default": False,
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "mem0_update",
        "description": "Replace the text of an existing memory by id, when a stored fact has changed or was wrong.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string"},
                "text": {"type": "string", "description": "The complete new text for that memory."},
            },
            "required": ["memory_id", "text"],
        },
    },
    {
        "name": "mem0_delete",
        "description": "Delete a memory by id, when it is obsolete or Max asks for it to be forgotten.",
        "inputSchema": {
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
        },
    },
]


def _text(message: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": is_error}


def _rows(results: object) -> list:
    if isinstance(results, dict):
        rows = results.get("results", results.get("memories", []))
        return rows if isinstance(rows, list) else []
    return results if isinstance(results, list) else []


def tool_search(args: dict) -> dict:
    query = str(args.get("query") or "").strip()
    if not query:
        return _text("query is required", True)
    try:
        top_k = max(1, min(50, int(args.get("top_k") or 10)))
    except (TypeError, ValueError):
        top_k = 10
    ok, data = call("POST", "/search", {"query": query, "top_k": top_k, "filters": {"user_id": USER_ID}})
    if not ok:
        return _text(str(data), True)
    rows = _rows(data)
    if not rows:
        return _text(f"No memories match {query!r}.")
    lines = []
    for row in rows:
        if isinstance(row, dict):
            text = str(row.get("memory") or row.get("text") or "").strip()
            ident = str(row.get("id") or "")
            score = row.get("score")
            suffix = f"  (score {score:.3f})" if isinstance(score, (int, float)) else ""
            lines.append(f"- {text}{suffix}\n  id: {ident}")
    return _text(f"{len(rows)} memory match(es) for {query!r}:\n\n" + "\n".join(lines))


def tool_add(args: dict) -> dict:
    text = str(args.get("text") or "").strip()
    if not text:
        return _text("text is required", True)
    payload = {
        "messages": [{"role": "user", "content": text}],
        "user_id": USER_ID,
        "agent_id": AGENT_ID,
        "infer": bool(args.get("infer", False)),
    }
    ok, data = call("POST", "/memories", payload)
    if not ok:
        return _text(str(data), True)
    ids = [str(r.get("id")) for r in _rows(data) if isinstance(r, dict) and r.get("id")]
    if isinstance(data, dict) and data.get("id"):
        ids.append(str(data["id"]))
    return _text("Stored." + (f" id: {', '.join(ids)}" if ids else "") + " Hermes will recall it.")


def tool_update(args: dict) -> dict:
    memory_id, text = str(args.get("memory_id") or "").strip(), str(args.get("text") or "").strip()
    if not memory_id or not text:
        return _text("memory_id and text are both required", True)
    ok, data = call("PUT", f"/memories/{memory_id}", {"text": text})
    return _text("Updated." if ok else str(data), not ok)


def tool_delete(args: dict) -> dict:
    memory_id = str(args.get("memory_id") or "").strip()
    if not memory_id:
        return _text("memory_id is required", True)
    ok, data = call("DELETE", f"/memories/{memory_id}")
    return _text("Deleted." if ok else str(data), not ok)


HANDLERS = {
    "mem0_search": tool_search,
    "mem0_add": tool_add,
    "mem0_update": tool_update,
    "mem0_delete": tool_delete,
}


def handle(request: dict) -> dict | None:
    method = request.get("method")
    params = request.get("params") or {}
    ident = request.get("id")

    if method == "initialize":
        asked = params.get("protocolVersion")
        return {
            "jsonrpc": "2.0",
            "id": ident,
            "result": {
                "protocolVersion": asked if isinstance(asked, str) and asked else PROTOCOL_FALLBACK,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
                "instructions": (
                    "Shared long-term memory. Search it before assuming you don't know something "
                    "about Max, and store lasting facts as he states them."
                ),
            },
        }
    if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return None                      # notifications get no reply, ever
    if method == "ping":
        return {"jsonrpc": "2.0", "id": ident, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": ident, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        handler = HANDLERS.get(str(name))
        if handler is None:
            return {"jsonrpc": "2.0", "id": ident,
                    "result": _text(f"unknown tool: {name}", True)}
        try:
            result = handler(params.get("arguments") or {})
        except Exception as exc:  # noqa: BLE001 - a tool error is a result, not a crash
            log(f"{name} failed: {type(exc).__name__}: {exc}")
            result = _text(f"{name} failed: {type(exc).__name__}", True)
        return {"jsonrpc": "2.0", "id": ident, "result": result}
    if ident is None:
        return None
    return {"jsonrpc": "2.0", "id": ident,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def main() -> int:
    log(f"ready: host={HOST} user={USER_ID} agent={AGENT_ID} key={'set' if API_KEY else 'unset'}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            log("skipped a non-JSON line")
            continue
        if not isinstance(request, dict):
            continue
        response = handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
