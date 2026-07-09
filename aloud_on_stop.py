#!/usr/bin/env python3
"""Claude Code Stop hook. Runs when a session finishes a reply.

Always records that session's cleaned reply into the registry. If the
session was armed (you typed `aloud on` in it), it also nudges the daemon
to speak a short gist out loud — so an armed session talks on its own and
there is never any guessing about which tab you meant.

Standard library only, so it runs on plain system python3 (no venv, fast).
Never raises: a hook must not disturb Claude Code.
"""
import json
import os
import socket
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
APP_HOME = os.environ.get(
    "ALOUD_HOME",
    os.path.expanduser("~/Library/Application Support/Aloud"),
)


def _tell_daemon(msg):
    """Fire-and-forget one line to the daemon. Silent if it is down."""
    sock = os.environ.get("ALOUD_SOCK") or os.path.join(APP_HOME, "aloud.sock")
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(1)
        c.connect(sock)
        c.sendall(msg.encode("utf-8"))
        c.close()
    except OSError:
        pass


try:
    import aloud_core as core

    payload = json.load(sys.stdin)
    sid = core.record_stop(payload)
    if sid and core.is_armed(sid):
        _tell_daemon(f"speak {sid}")
except Exception:
    pass  # a hook failing must never break the session
