"""A stateful stand-in for the parts of the ElevenLabs API the operator scripts use."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import FakeServer  # noqa: E402

KEY = "KEY"


class FakeElevenLabs:
    def __init__(self):
        self.secrets, self.webhooks, self.tools, self.agents, self.numbers, self.conversations = {}, {}, {}, {}, {}, {}
        self.calls, self.n = [], 0
        self.llms = ["gemini-3.5-flash", "claude-haiku-4-5", "deepseek-v41-flash"]
        self.server = FakeServer(self.handle)

    def new_id(self, prefix):
        self.n += 1
        return f"{prefix}_{self.n}"

    def handle(self, method, path, headers, body):
        route = path.split("?")[0]
        self.calls.append((method, route))
        if headers.get("xi-api-key") != KEY:
            return 401, {"detail": "bad key"}
        page = {"next_cursor": None, "has_more": False}
        if route == "/v1/convai/secrets":
            if method == "GET":
                return 200, {"secrets": [{"type": "stored", "secret_id": i, "name": s["name"], "used_by": {}}
                                         for i, s in self.secrets.items()], **page}
            sid = self.new_id("sec")
            self.secrets[sid] = {"name": body["name"], "value": body["value"]}
            return 200, {"type": "stored", "secret_id": sid, "name": body["name"]}
        match = re.match(r"^/v1/convai/secrets/([^/]+)$", route)
        if match and method == "PATCH":
            self.secrets[match.group(1)].update(name=body["name"], value=body["value"])
            return 200, {"type": "stored", "secret_id": match.group(1), "name": body["name"]}
        if route == "/v1/workspace/webhooks":
            if method == "GET":
                return 200, {"webhooks": [{"name": w["name"], "webhook_id": i, "webhook_url": w["url"], "is_disabled": False,
                                           "is_auto_disabled": False, "created_at_unix": 1, "auth_type": "hmac"}
                                          for i, w in self.webhooks.items()]}
            wid = self.new_id("wh")
            settings = body["settings"]
            self.webhooks[wid] = {"name": settings["name"], "url": settings["webhook_url"], "auth": settings["auth_type"]}
            return 200, {"webhook_id": wid, "webhook_secret": f"whsec_{wid}"}
        match = re.match(r"^/v1/workspace/webhooks/([^/]+)$", route)
        if match and method == "DELETE":
            self.webhooks.pop(match.group(1), None)
            return 200, {}
        if route == "/v1/convai/tools":
            if method == "GET":
                return 200, {"tools": [{"id": i, "tool_config": t} for i, t in self.tools.items()], **page}
            tid = self.new_id("tool")
            self.tools[tid] = body["tool_config"]
            return 200, {"id": tid, "tool_config": body["tool_config"]}
        match = re.match(r"^/v1/convai/tools/([^/]+)$", route)
        if match and method == "PATCH":
            self.tools[match.group(1)] = body["tool_config"]
            return 200, {"id": match.group(1), "tool_config": body["tool_config"]}
        if route == "/v1/convai/agents":
            return 200, {"agents": [{"agent_id": i, "name": a["name"]} for i, a in self.agents.items()], **page}
        if route == "/v1/convai/agents/create":
            aid = self.new_id("agent")
            self.agents[aid] = body
            return 200, {"agent_id": aid}
        match = re.match(r"^/v1/convai/agents/([^/]+)$", route)
        if match and method == "PATCH":
            self.agents[match.group(1)] = body
            return 200, {"agent_id": match.group(1)}
        if route == "/v1/convai/phone-numbers":
            if method == "GET":
                return 200, [{"phone_number": n["phone_number"], "phone_number_id": i, "label": n["label"],
                              "assigned_agent": {"agent_id": n["agent_id"], "agent_name": "{{CHIEF}} (phone)"} if n.get("agent_id") else None}
                             for i, n in self.numbers.items()]
            nid = self.new_id("phnum")
            self.numbers[nid] = body
            return 200, {"phone_number_id": nid}
        match = re.match(r"^/v1/convai/phone-numbers/([^/]+)$", route)
        if match and method == "PATCH":
            self.numbers[match.group(1)]["agent_id"] = body["agent_id"]
            return 200, {}
        if match and method == "DELETE":
            self.numbers.pop(match.group(1), None)
            return 200, {}
        if route == "/v1/convai/llm/list":
            return 200, {"llms": [{"llm": name} for name in self.llms]}
        if route == "/v1/convai/conversations":
            return 200, {"conversations": [{"conversation_id": c} for c in self.conversations], **page}
        match = re.match(r"^/v1/convai/conversations/([^/]+)$", route)
        if match:
            return 200, self.conversations[match.group(1)]
        return 404, {"detail": f"no route {method} {route}"}
