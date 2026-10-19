"""Pushes {{CHIEF}}'s agents to ElevenLabs: the shared secret, the post-call webhook, the tools and the phone agent, and the guest agent
that rings other people for {{OWNER}} (it has no tools, only the webhook that reports its calls).

Idempotent: each thing is found by name and updated, so running it again after changing the prompt or a setting is safe.
Run on the server as the hermes user (it needs the ElevenLabs key and the desk's secrets):

    python3 -m desk.push_agent [--check] [--only phone|guest] [--tester] [--llm MODEL] [--agents-dir DIR] [--style PATH]

--check shows what would be created or updated and changes nothing. --only pushes one of the two agents (the phone agent also
brings its secret and tools along). --tester also gives the dashboard's test window a tool token (valid for the same 25 minutes
as any call's), because a preview never receives a real one: push again without it afterwards. Secrets are never printed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import agent_config, calls, config, db, util
from .eleven import Eleven, ElevenError

SECRET_NAME = "desk_tool_secret"
WEBHOOK_NAME = "phone-desk-postcall"


class PushError(Exception):
    pass


def make_tester_token(cfg) -> str:
    """A tool token for the dashboard tester. It expires like any call's, and is useless without the shared secret."""
    database = db.DB(cfg.db_path)
    try:
        return calls.Calls(database, util.Clock(), cfg).prepare_outbound("test")["token"]
    finally:
        database.close()


class Pusher:
    def __init__(self, eleven, cfg, template: str, style_md: str, llm: str = agent_config.LLM, apply: bool = True,
                 say=print, tester_token: str = "", guest_template: str | None = None):
        self.eleven, self.cfg, self.template, self.style_md = eleven, cfg, template, style_md
        self.llm, self.apply, self.say, self.tester_token = llm, apply, say, tester_token
        self.guest_template = guest_template            # the guest agent is pushed only when its prompt is given

    def _all(self, path: str, key: str) -> list[dict]:
        out, cursor = [], None
        for _ in range(20):
            page = self.eleven.request("GET", f"{path}?page_size=100" + (f"&cursor={cursor}" if cursor else ""))
            out.extend(page.get(key, []))
            cursor = page.get("next_cursor")
            if not page.get("has_more") or not cursor:
                break
        return out

    def check_llm(self) -> None:
        """The chosen model must be one this account can use; say which ones it can if not."""
        available = sorted(item["llm"] for item in self.eleven.request("GET", "/v1/convai/llm/list").get("llms", []))
        if self.llm not in available:
            raise PushError(f"{self.llm} is not available on this account (available: {', '.join(available)})")

    def ensure_secret(self) -> str:
        if not self.cfg.tool_secret:
            raise PushError("DESK_TOOL_SECRET is not set in secrets.env")
        found = next((s for s in self._all("/v1/convai/secrets", "secrets") if s["name"] == SECRET_NAME), None)
        if found:
            if self.apply:
                self.eleven.request("PATCH", f"/v1/convai/secrets/{found['secret_id']}",
                                    {"type": "update", "name": SECRET_NAME, "value": self.cfg.tool_secret})
            self.say(f"secret {SECRET_NAME}: {'value synced' if self.apply else 'exists'}")
            return found["secret_id"]
        if not self.apply:
            self.say(f"secret {SECRET_NAME}: would create")
            return "secret_pending"
        made = self.eleven.request("POST", "/v1/convai/secrets",
                                   {"type": "new", "name": SECRET_NAME, "value": self.cfg.tool_secret})
        self.say(f"secret {SECRET_NAME}: created")
        return made["secret_id"]

    def ensure_webhook(self) -> str:
        url = f"{self.cfg.public_base}/postcall"
        rows = self.eleven.request("GET", "/v1/workspace/webhooks").get("webhooks", [])
        found = next((w for w in rows if w["name"] == WEBHOOK_NAME), None)
        if found and found["webhook_url"] == url and not found.get("is_disabled") and self.cfg.webhook_secret:
            self.say(f"webhook {WEBHOOK_NAME}: exists")
            return found["webhook_id"]
        if not self.apply:
            self.say(f"webhook {WEBHOOK_NAME}: would (re)create")
            return "webhook_pending"
        if found:                                   # its secret can no longer be read, so make a fresh one
            self.eleven.request("DELETE", f"/v1/workspace/webhooks/{found['webhook_id']}")
        made = self.eleven.request("POST", "/v1/workspace/webhooks",
                                   {"settings": {"auth_type": "hmac", "name": WEBHOOK_NAME, "webhook_url": url}})
        secret = made.get("webhook_secret")
        if not secret:
            raise PushError("ElevenLabs did not return the webhook secret")
        config.set_env_value(Path(self.cfg.state_dir) / "secrets.env", "ELEVENLABS_WEBHOOK_SECRET", secret)
        self.cfg.webhook_secret = secret
        self.say(f"webhook {WEBHOOK_NAME}: created (its secret is saved in secrets.env, not shown)")
        return made["webhook_id"]

    def ensure_tools(self, secret_id: str) -> dict[str, str]:
        wanted = agent_config.tool_configs(self.cfg.public_base, secret_id)
        existing = {t["tool_config"]["name"]: t["id"] for t in self._all("/v1/convai/tools", "tools")
                    if t.get("tool_config", {}).get("name") in wanted}
        ids = {}
        for name, tool in wanted.items():
            if name in existing:
                ids[name] = existing[name]
                if self.apply:
                    self.eleven.request("PATCH", f"/v1/convai/tools/{existing[name]}", {"tool_config": tool})
                self.say(f"tool {name}: {'updated' if self.apply else 'exists'}")
            elif self.apply:
                ids[name] = self.eleven.request("POST", "/v1/convai/tools", {"tool_config": tool})["id"]
                self.say(f"tool {name}: created")
            else:
                ids[name] = f"{name}_pending"
                self.say(f"tool {name}: would create")
        return ids

    def ensure_agent(self, tool_ids: dict[str, str], secret_id: str, webhook_id: str) -> str:
        prompt = agent_config.build_prompt(self.template, self.style_md)
        payload = agent_config.agent_payload(prompt=prompt, tool_ids=[tool_ids[n] for n in agent_config.TOOL_NAMES],
                                             public_base=self.cfg.public_base, secret_id=secret_id, webhook_id=webhook_id,
                                             voice_id=self.cfg.voice_id, llm=self.llm, tester_token=self.tester_token)
        agent_config.check_payload(payload, agent_config.tool_configs(self.cfg.public_base, secret_id))
        agents = self._all("/v1/convai/agents", "agents")
        found = next((a for a in agents if a["agent_id"] == self.cfg.agent_id), None) or \
            next((a for a in agents if a["name"] == agent_config.AGENT_NAME), None)
        if found:
            if self.apply:
                self.eleven.request("PATCH", f"/v1/convai/agents/{found['agent_id']}", payload)
            self.say(f"agent {agent_config.AGENT_NAME}: {'updated' if self.apply else 'exists'} ({found['agent_id']}), "
                     f"model {self.llm}, prompt {len(prompt)} characters")
            return found["agent_id"]
        if not self.apply:
            self.say(f"agent {agent_config.AGENT_NAME}: would create (model {self.llm}, prompt {len(prompt)} characters)")
            return "agent_pending"
        agent_id = self.eleven.request("POST", "/v1/convai/agents/create", payload)["agent_id"]
        self.say(f"agent {agent_config.AGENT_NAME}: created ({agent_id})")
        return agent_id

    def _guest_payload(self, webhook_id: str) -> dict:
        payload = agent_config.guest_payload(prompt=agent_config.build_guest_prompt(self.guest_template), webhook_id=webhook_id,
                                             voice_id=self.cfg.voice_id,
                                             llm=self.llm, max_call_secs=self.cfg.guest_max_call_secs)
        agent_config.check_guest_payload(payload)
        return payload

    def ensure_guest_agent(self, webhook_id: str) -> str:
        payload = self._guest_payload(webhook_id)
        name = agent_config.GUEST_AGENT_NAME
        agents = self._all("/v1/convai/agents", "agents")
        found = (next((a for a in agents if self.cfg.guest_agent_id and a["agent_id"] == self.cfg.guest_agent_id), None) or
                 next((a for a in agents if a["name"] == name), None))
        prompt_len = len(payload["conversation_config"]["agent"]["prompt"]["prompt"])
        if found:
            if self.apply:
                self.eleven.request("PATCH", f"/v1/convai/agents/{found['agent_id']}", payload)
            self.say(f"agent {name}: {'updated' if self.apply else 'exists'} ({found['agent_id']}), model {self.llm}, "
                     f"prompt {prompt_len} characters")
            return found["agent_id"]
        if not self.apply:
            self.say(f"agent {name}: would create (model {self.llm}, prompt {prompt_len} characters)")
            return "guest_agent_pending"
        agent_id = self.eleven.request("POST", "/v1/convai/agents/create", payload)["agent_id"]
        self.say(f"agent {name}: created ({agent_id})")
        return agent_id

    def run(self, only: str | None = None) -> dict:
        """Everything, or with only='phone' or only='guest' one agent. Every payload is checked before anything is sent."""
        if only not in (None, "phone", "guest"):
            raise PushError("only is phone or guest")
        if not self.cfg.public_base.startswith("https://"):
            raise PushError("public_base must be the https address of the desk (set it in config.json)")
        with_phone, with_guest = only in (None, "phone"), only == "guest" or (only is None and self.guest_template is not None)
        if only == "guest" and self.guest_template is None:
            raise PushError("there is no guest prompt to push")
        if with_guest:
            self._guest_payload("webhook_pending")          # a bad guest prompt must stop the run before the phone agent is touched
        self.check_llm()
        result: dict = {}
        secret_id = tool_ids = None
        if with_phone:
            secret_id = self.ensure_secret()
        webhook_id = self.ensure_webhook()
        result["webhook_id"] = webhook_id
        if with_phone:
            tool_ids = self.ensure_tools(secret_id)
            result.update(secret_id=secret_id, tool_ids=tool_ids,
                          agent_id=self.ensure_agent(tool_ids, secret_id, webhook_id))
        if with_guest:
            result["guest_agent_id"] = self.ensure_guest_agent(webhook_id)
        if self.apply:
            config.update_config_json(self.cfg.state_dir, {key: result[key] for key in ("agent_id", "guest_agent_id") if key in result})
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Push {{CHIEF}}'s agents to ElevenLabs")
    parser.add_argument("--check", action="store_true", help="show what would change, change nothing")
    parser.add_argument("--only", choices=("phone", "guest"), help="push just one of the two agents")
    parser.add_argument("--tester", action="store_true", help="give the dashboard test window a tool token (25 minutes)")
    parser.add_argument("--llm", default=agent_config.LLM)
    parser.add_argument("--state-dir", default="/data/.hermes/voice-desk")
    parser.add_argument("--hermes-home", default="/data/.hermes")
    parser.add_argument("--agents-dir", default="/data/tools/voice-desk/agents")
    parser.add_argument("--style", default="/data/tools/voice-desk/STYLE.md")
    args = parser.parse_args(argv)
    cfg = config.load(args.state_dir, args.hermes_home)
    try:
        pusher = Pusher(Eleven(cfg.eleven_key), cfg, (Path(args.agents_dir) / "chief.prompt.md").read_text(),
                        Path(args.style).read_text(), llm=args.llm, apply=not args.check,
                        tester_token=make_tester_token(cfg) if args.tester and not args.check else "",
                        guest_template=(Path(args.agents_dir) / "chief-guest.prompt.md").read_text())
        pusher.run(args.only)
    except (PushError, ElevenError, ValueError, OSError) as exc:
        print(f"push failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
