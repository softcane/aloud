from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from aloud.paths import AppPaths


@dataclass(frozen=True)
class Config:
    voice: str = "af_bella"
    speed: float = 0.9
    sample_rate: int = 24000
    max_chars: int = 1400
    gist_chars: int = 240
    keep_sessions: int = 40
    max_age_seconds: int = 2 * 24 * 3600


def load_config(paths: AppPaths) -> Config:
    if not paths.config.exists():
        return Config()
    try:
        data = json.loads(paths.config.read_text())
    except (OSError, json.JSONDecodeError):
        return Config()
    defaults = asdict(Config())
    defaults.update({key: value for key, value in data.items() if key in defaults})
    return Config(**defaults)


def ensure_config(paths: AppPaths) -> Config:
    paths.app_home.mkdir(parents=True, exist_ok=True)
    config = load_config(paths)
    if not paths.config.exists():
        paths.config.write_text(json.dumps(asdict(config), indent=2) + "\n")
    return config
