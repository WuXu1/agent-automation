"""Timings of a real call, from ElevenLabs' own record of it (the scripted checks need numbers, not impressions).

  python3 -m desk.report --latest [N] [--guest]    the last N conversations (default 1) of {{CHIEF}}'s phone agent, or of the guest agent
  python3 -m desk.report CONVERSATION_ID

Shows how long the call was, how many turns, how fast the model started answering (first-token latency per turn), and how long
each tool took. Nothing from the conversation's content is printed.
"""
from __future__ import annotations

import argparse
import statistics
import sys

from . import config
from .eleven import Eleven, ElevenError


def _turn_metric(turn: dict, name: str) -> float | None:
    metrics = turn.get("conversation_turn_metrics") or {}
    metrics = metrics.get("metrics", metrics)
    value = metrics.get(name)
    if isinstance(value, dict):
        value = value.get("elapsed_time")
    return float(value) if isinstance(value, (int, float)) else None


def _spread(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    return {"n": len(ordered), "median": statistics.median(ordered), "p90": ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))],
            "max": ordered[-1]}


def summarise(conversation: dict) -> dict:
    meta = conversation.get("metadata") or {}
    transcript = conversation.get("transcript") or []
    tools = [{"tool": r.get("tool_name"), "secs": r.get("tool_latency_secs", 0), "error": bool(r.get("is_error")),
              "abandoned": bool(r.get("is_error")) and "abandoned" in str(r.get("result_value") or "")}
             for turn in transcript for r in (turn.get("tool_results") or [])]
    return {
        "duration_secs": meta.get("call_duration_secs"),
        "user_turns": sum(1 for t in transcript if t.get("role") == "user" and (t.get("message") or "").strip()),
        "agent_turns": sum(1 for t in transcript if t.get("role") == "agent" and (t.get("message") or "").strip()),
        "llm_first_token": _spread([v for v in (_turn_metric(t, "convai_llm_service_ttfb") for t in transcript) if v is not None]),
        "llm_first_sentence": _spread([v for v in (_turn_metric(t, "convai_llm_service_ttf_sentence") for t in transcript)
                                       if v is not None]),
        "tools": tools,
        "ended": meta.get("termination_reason") or "",
        "cost": meta.get("cost"),
    }


def render(summary: dict, other: str = "{{OWNER}}") -> str:
    """`other` names the person on the line with {{CHIEF}}: {{OWNER}}, or whoever the guest agent rang."""
    def spread(label, s):
        return f"{label}: n/a" if not s else f"{label}: median {s['median']:.2f}s, p90 {s['p90']:.2f}s, max {s['max']:.2f}s ({s['n']} turns)"
    lines = [f"call {summary['duration_secs']}s, {summary['user_turns']} turns from {other}, {summary['agent_turns']} from {{CHIEF}}; "
             f"ended: {summary['ended'] or 'n/a'}; cost {summary['cost']}",
             spread("model first token", summary["llm_first_token"]), spread("model first sentence", summary["llm_first_sentence"])]
    for tool in summary["tools"]:
        flag = " (abandoned: the caller spoke while it ran)" if tool["abandoned"] else " (ERROR)" if tool["error"] else ""
        lines.append(f"tool {tool['tool']}: {tool['secs']:.1f}s" + flag)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="desk.report")
    parser.add_argument("conversation_id", nargs="?")
    parser.add_argument("--latest", nargs="?", const=1, type=int)
    parser.add_argument("--guest", action="store_true", help="the guest agent's conversations instead of {{CHIEF}}'s phone agent's")
    parser.add_argument("--state-dir", default="/data/.hermes/voice-desk")
    parser.add_argument("--hermes-home", default="/data/.hermes")
    args = parser.parse_args(argv)
    cfg = config.load(args.state_dir, args.hermes_home)
    eleven = Eleven(cfg.eleven_key)
    try:
        if args.conversation_id:
            ids = [args.conversation_id]
        else:
            agent_id = cfg.guest_agent_id if args.guest else cfg.agent_id
            listing = eleven.request("GET", f"/v1/convai/conversations?page_size={args.latest or 1}"
                                            + (f"&agent_id={agent_id}" if agent_id else ""))
            ids = [c["conversation_id"] for c in listing.get("conversations", [])]
        for cid in ids:
            print(f"--- {cid}")
            print(render(summarise(eleven.request("GET", f"/v1/convai/conversations/{cid}")), "the person rung" if args.guest else "{{OWNER}}"))
    except ElevenError as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
