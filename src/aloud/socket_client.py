from __future__ import annotations

import socket
import subprocess

from aloud.paths import AppPaths, default_paths


def send_command(
    command: str,
    paths: AppPaths | None = None,
    *,
    timeout: float = 1,
    autostart: bool = False,
) -> bool:
    paths = paths or default_paths()
    if not paths.socket.exists() and autostart:
        subprocess.run(
            ["launchctl", "load", "-w", str(paths.launch_agent)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(str(paths.socket))
        client.sendall(command.encode("utf-8"))
        client.close()
    except OSError:
        return False
    return True
