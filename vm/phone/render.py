#!/usr/bin/env python3
"""Fills in the names in the phone desk's files: copies a folder and replaces {{OWNER}}, {{CHIEF}}, {{TUTOR}}, {{ASSISTANT}}, {{COACH}}
and the way the chief addresses the owner ({{SIR}} at the start of a sentence, {{sir}} inside one). Any other {{...}} (the
ElevenLabs call variables such as {{now_text}}) is left exactly as it is.

  python3 render.py SRC DST [--setup /data/.hermes/hermes.json] [--name OWNER=Logan ...]

The names come from the setup file the installer keeps (the owner and the four agents); --name overrides one (the tests use it).
How the chief addresses the owner is `phone_address` in that file when it is set ("sir", "boss"), else the owner's first name.
"""
import argparse
import json
import pathlib
import re
import shutil
import sys

SUFFIXES = {".py", ".md", ".json", ".sh", ".txt", ".service"}
TOKENS = ("OWNER", "CHIEF", "TUTOR", "ASSISTANT", "COACH", "SIR", "sir")


def names_from_setup(path: str) -> dict[str, str]:
    setup = json.loads(pathlib.Path(path).read_text())
    by_role = {a.get("role"): a.get("name") for a in setup.get("agents", [])}
    owner = (setup.get("owner") or {}).get("name") or "the owner"
    address = (setup.get("phone_address") or owner).strip()
    return {"OWNER": owner, "CHIEF": by_role.get("chief") or "Chief", "TUTOR": by_role.get("tutor") or "Tutor",
            "ASSISTANT": by_role.get("assistant") or "Assistant", "COACH": by_role.get("coach") or "Coach",
            "sir": address, "SIR": address[:1].upper() + address[1:]}


def render_text(text: str, names: dict[str, str]) -> str:
    return re.sub(r"\{\{(%s)\}\}" % "|".join(TOKENS), lambda m: names[m.group(1)], text)


def render_tree(src: str, dst: str, names: dict[str, str]) -> None:
    src_path, dst_path = pathlib.Path(src), pathlib.Path(dst)
    if dst_path.exists():
        shutil.rmtree(dst_path)
    for item in src_path.rglob("*"):
        if "__pycache__" in item.parts:
            continue
        target = dst_path / item.relative_to(src_path)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if item.suffix in SUFFIXES:
                target.write_text(render_text(item.read_text(), names))
            else:
                shutil.copy2(item, target)
            target.chmod(item.stat().st_mode & 0o777)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("src")
    parser.add_argument("dst")
    parser.add_argument("--setup", default="/data/.hermes/hermes.json")
    parser.add_argument("--name", action="append", default=[], metavar="TOKEN=value")
    args = parser.parse_args(argv)
    names = {}
    if not args.name or len(args.name) < len(TOKENS):
        try:
            names = names_from_setup(args.setup)
        except (OSError, ValueError):
            if not args.name:
                print("render: can't read the setup file", args.setup, file=sys.stderr)
                return 1
    for item in args.name:
        key, _, value = item.partition("=")
        names[key] = value
    if "SIR" in names and "sir" not in names:
        names["sir"] = names["SIR"].lower() if names["SIR"].lower() == "sir" else names["SIR"]
    render_tree(args.src, args.dst, names)
    return 0


if __name__ == "__main__":
    sys.exit(main())
