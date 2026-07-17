from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aloud.paths import default_paths  # noqa: E402


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ALOUD_HOME", str(home / "Library" / "Application Support" / "Aloud"))
    monkeypatch.setenv("ALOUD_CACHE_HOME", str(home / "Library" / "Caches" / "Aloud"))
    monkeypatch.setenv("ALOUD_LOG_HOME", str(home / "Library" / "Logs" / "Aloud"))
    monkeypatch.setenv(
        "ALOUD_SOCK",
        str(home / "Library" / "Application Support" / "Aloud" / "aloud.sock"),
    )
    old_codex_home = os.environ.get("CODEX_HOME")
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    paths = default_paths()
    yield paths
    if old_codex_home is None:
        monkeypatch.delenv("CODEX_HOME", raising=False)
