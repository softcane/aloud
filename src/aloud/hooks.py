from __future__ import annotations

import json
import re
import sys
from contextlib import suppress
from typing import Any

from aloud.paths import AppPaths, default_paths
from aloud.registry import Registry
from aloud.socket_client import send_command

WAKE = r"(?:aloud|a loud|allowed)"
ARM_RE = re.compile(rf"^{WAKE}\s+(on|listen|start)$")
OFF_RE = re.compile(rf"^{WAKE}\s+(off|stop|quiet)$")


def normalize_prompt(prompt: str) -> str:
    return re.sub(r"[^a-z]+", " ", prompt.lower()).strip()


def prompt_hook(payload: dict[str, Any], paths: AppPaths | None = None) -> dict[str, str] | None:
    paths = paths or default_paths()
    registry = Registry(paths)
    session_id = payload.get("session_id", "")
    phrase = normalize_prompt(payload.get("prompt", ""))
    if ARM_RE.match(phrase):
        registry.arm(session_id)
        return {
            "decision": "block",
            "reason": (
                "Aloud is ON for this session. Each reply speaks a short gist; "
                "press Cmd+Ctrl+H for the whole thing. Say 'aloud off' to stop."
            ),
        }
    if OFF_RE.match(phrase):
        registry.disarm(session_id)
        send_command("stop", paths)
        return {"decision": "block", "reason": "Aloud is OFF for this session."}
    send_command("forget", paths)
    return None


def stop_hook(payload: dict[str, Any], paths: AppPaths | None = None) -> str | None:
    paths = paths or default_paths()
    registry = Registry(paths)
    session_id = registry.record_stop(payload)
    if session_id and registry.is_armed(session_id):
        send_command(f"speak {session_id}", paths)
    return session_id


def run_prompt_hook() -> int:
    try:
        decision = prompt_hook(json.load(sys.stdin))
        if decision:
            print(json.dumps(decision))
    except Exception:
        pass
    return 0


def run_stop_hook() -> int:
    with suppress(Exception):
        stop_hook(json.load(sys.stdin))
    return 0
