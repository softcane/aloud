#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook. Runs when you send a message.

Two jobs:

1. Arming. If the message IS the phrase `aloud on` (or `aloud off`), this
   arms/disarms THIS session — the hook knows its own session_id, so there
   is no guessing which tab you meant. It then blocks the phrase so Claude
   never treats "aloud on" as a real request.

2. Cleanup. For any normal message, it tells the daemon to forget the
   current audio, so a fresh reply never plays yesterday's voice.

Standard library only. Never breaks the session.
"""
import json
import os
import re
import socket
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
APP_HOME = os.environ.get(
    "ALOUD_HOME",
    os.path.expanduser("~/Library/Application Support/Aloud"),
)

# Voice dictation is lossy, so accept the obvious homophones of "aloud".
_WAKE = r"(?:aloud|a loud|allowed)"
ARM_RE = re.compile(rf"^{_WAKE}\s+(on|listen|start)$")
OFF_RE = re.compile(rf"^{_WAKE}\s+(off|stop|quiet)$")


def _normalize(prompt):
    return re.sub(r"[^a-z]+", " ", prompt.lower()).strip()


def _tell_daemon(msg):
    sock = os.environ.get("ALOUD_SOCK") or os.path.join(APP_HOME, "aloud.sock")
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(1)
        c.connect(sock)
        c.sendall(msg.encode("utf-8"))
        c.close()
    except OSError:
        pass


def _block(reason):
    """Stop this phrase from reaching Claude; show a short note instead."""
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


try:
    import aloud_core as core

    payload = json.load(sys.stdin)
    sid = payload.get("session_id", "")
    phrase = _normalize(payload.get("prompt", ""))

    if ARM_RE.match(phrase):
        core.arm(sid)
        _block("🔊 Aloud is ON for this session. Each reply speaks a short "
               "gist; press Cmd+Ctrl+H for the whole thing. Say 'aloud off' "
               "to stop.")
    elif OFF_RE.match(phrase):
        core.disarm(sid)
        _tell_daemon("stop")
        _block("🔇 Aloud is OFF for this session.")
    else:
        _tell_daemon("forget")  # new message: drop the old audio
except SystemExit:
    raise
except Exception:
    pass  # a hook failing must never break the session
