from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

from aloud.config import Config
from aloud.hooks import prompt_hook, stop_hook
from aloud.registry import Registry


def test_registry_target_follows_spoken_session_not_newest(isolated_env):
    registry = Registry(isolated_env, Config())

    registry.record_stop({"session_id": "SID-A", "last_assistant_message": "Alpha reply."})
    registry.arm("SID-A")
    time.sleep(0.01)
    registry.record_stop({"session_id": "SID-B", "last_assistant_message": "Beta reply."})
    registry.note_spoken("SID-A")

    assert registry.spoken_target().text == "Alpha reply."
    assert registry.resolve_target().text == "Beta reply."


def test_session_ids_cannot_escape_session_directory(isolated_env):
    registry = Registry(isolated_env, Config())
    sid = "../bad/session"

    assert registry.record_stop({"session_id": sid, "last_assistant_message": "Safe."}) == sid

    files = list(isolated_env.sessions.glob("*.json"))
    assert len(files) == 1
    assert files[0].parent == isolated_env.sessions
    assert registry.text_for(sid) == "Safe."


def test_prompt_hook_blocks_control_phrase_and_writes_marker(isolated_env):
    decision = prompt_hook({"session_id": "SID-A", "prompt": "/aloud-on"}, isolated_env)

    assert decision and decision["decision"] == "block"
    assert (isolated_env.armed / "SID-A").exists()


def test_stop_hook_sends_speak_only_for_armed_session(isolated_env):
    short_socket = Path("/tmp") / f"aloud-test-{os.getpid()}.sock"
    isolated_env = type(isolated_env)(
        app_home=isolated_env.app_home,
        cache_home=isolated_env.cache_home,
        log_home=isolated_env.log_home,
        socket=short_socket,
        config=isolated_env.config,
        sessions=isolated_env.sessions,
        armed=isolated_env.armed,
        latest=isolated_env.latest,
        spoken=isolated_env.spoken,
        wav=isolated_env.wav,
        signature=isolated_env.signature,
        log=isolated_env.log,
        launch_agent=isolated_env.launch_agent,
    )
    isolated_env.socket.parent.mkdir(parents=True, exist_ok=True)
    received: list[str] = []
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(isolated_env.socket))
    server.listen(1)
    server.settimeout(3)

    def accept_once():
        conn, _ = server.accept()
        with conn:
            received.append(conn.recv(256).decode("utf-8"))

    thread = threading.Thread(target=accept_once)
    thread.start()
    try:
        prompt_hook({"session_id": "SID-A", "prompt": "aloud on"}, isolated_env)
        sid = stop_hook(
            {"session_id": "SID-A", "last_assistant_message": "Ready."},
            isolated_env,
        )
        thread.join(3)
    finally:
        server.close()
        isolated_env.socket.unlink(missing_ok=True)

    assert sid == "SID-A"
    assert received == ["speak SID-A"]
    assert json.loads((isolated_env.sessions / "SID-A.json").read_text())["text"] == "Ready."
