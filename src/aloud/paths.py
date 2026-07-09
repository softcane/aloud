from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    app_home: Path
    cache_home: Path
    log_home: Path
    socket: Path
    config: Path
    sessions: Path
    armed: Path
    latest: Path
    spoken: Path
    wav: Path
    signature: Path
    log: Path
    launch_agent: Path

    def ensure_runtime_dirs(self) -> None:
        for path in (self.app_home, self.cache_home, self.log_home, self.sessions, self.armed):
            path.mkdir(parents=True, exist_ok=True)


def default_paths(env: dict[str, str] | None = None) -> AppPaths:
    env = env or os.environ
    home = Path(env.get("HOME", str(Path.home()))).expanduser()
    app_home = Path(
        env.get("ALOUD_HOME", str(home / "Library" / "Application Support" / "Aloud"))
    ).expanduser()
    cache_home = Path(env.get("ALOUD_CACHE_HOME", str(home / "Library" / "Caches" / "Aloud")))
    log_home = Path(env.get("ALOUD_LOG_HOME", str(home / "Library" / "Logs" / "Aloud")))
    socket = Path(env.get("ALOUD_SOCK", str(app_home / "aloud.sock"))).expanduser()
    sessions = app_home / "sessions"
    return AppPaths(
        app_home=app_home,
        cache_home=cache_home.expanduser(),
        log_home=log_home.expanduser(),
        socket=socket,
        config=app_home / "config.json",
        sessions=sessions,
        armed=sessions / "armed",
        latest=sessions / "latest",
        spoken=sessions / "spoken",
        wav=cache_home.expanduser() / "last.wav",
        signature=cache_home.expanduser() / "last.sig",
        log=log_home.expanduser() / "daemon.log",
        launch_agent=home / "Library" / "LaunchAgents" / "io.aloud.daemon.plist",
    )
