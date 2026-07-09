from __future__ import annotations

import hashlib
import json
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aloud.config import Config, load_config
from aloud.paths import AppPaths, default_paths
from aloud.text import signature, to_speech
from aloud.transcripts import assistant_text_from_payload, last_assistant_text, newest_transcript


@dataclass(frozen=True)
class Target:
    text: str
    signature: str


def session_file_name(session_id: str | None) -> str:
    sid = str(session_id or "")
    clean = re.sub(r"[^A-Za-z0-9_.-]", "_", sid).strip("._")
    if not clean:
        return ""
    if clean != sid:
        clean = clean[:120] + "-" + hashlib.sha1(sid.encode("utf-8")).hexdigest()[:12]
    return clean[:200]


class Registry:
    def __init__(self, paths: AppPaths | None = None, config: Config | None = None):
        self.paths = paths or default_paths()
        self.config = config or load_config(self.paths)

    def arm(self, session_id: str | None) -> None:
        name = session_file_name(session_id)
        if not name:
            return
        self.paths.armed.mkdir(parents=True, exist_ok=True)
        (self.paths.armed / name).touch()

    def disarm(self, session_id: str | None) -> None:
        name = session_file_name(session_id)
        if not name:
            return
        with suppress(OSError):
            (self.paths.armed / name).unlink()

    def is_armed(self, session_id: str | None) -> bool:
        name = session_file_name(session_id)
        return bool(name) and (self.paths.armed / name).exists()

    def text_for(self, session_id: str | None) -> str:
        name = session_file_name(session_id)
        if not name:
            return ""
        try:
            return json.loads((self.paths.sessions / f"{name}.json").read_text()).get("text", "")
        except (OSError, json.JSONDecodeError):
            return ""

    def record_stop(self, payload: dict[str, Any]) -> str | None:
        transcript = payload.get("transcript_path")
        if not transcript:
            fallback = newest_transcript()
            transcript = str(fallback) if fallback else None

        text = assistant_text_from_payload(payload)
        if not text and transcript:
            text = last_assistant_text(transcript) or ""
        text = to_speech(text, self.config.max_chars)
        if not text:
            return None

        sid = session_id_for(transcript, payload)
        name = session_file_name(sid)
        if not name:
            return None

        self.paths.sessions.mkdir(parents=True, exist_ok=True)
        record = {
            "text": text,
            "ts": time.time(),
            "transcript": transcript,
            "session": sid,
        }
        (self.paths.sessions / f"{name}.json").write_text(json.dumps(record))
        self._write_pointer(self.paths.latest, sid)
        self.prune()
        return sid

    def note_spoken(self, session_id: str | None) -> None:
        if session_id:
            self._write_pointer(self.paths.spoken, session_id)

    def spoken_target(self) -> Target:
        target = self._pointer_target(self.paths.spoken)
        if target.text:
            return target
        return self.resolve_target()

    def resolve_target(self) -> Target:
        target = self._pointer_target(self.paths.latest)
        if target.text:
            return target
        transcript = newest_transcript()
        if not transcript:
            return Target("", "")
        text = to_speech(last_assistant_text(transcript), self.config.max_chars)
        return Target(text, signature(text))

    def prune(self) -> None:
        if not self.paths.sessions.exists():
            return
        now = time.time()
        files = sorted(self.paths.sessions.glob("*.json"), key=lambda path: path.stat().st_mtime)
        for path in list(files):
            try:
                if now - path.stat().st_mtime > self.config.max_age_seconds:
                    path.unlink()
                    files.remove(path)
            except OSError:
                pass
        for path in list(reversed(files))[self.config.keep_sessions :]:
            with suppress(OSError):
                path.unlink()
        if self.paths.armed.exists():
            for marker in self.paths.armed.iterdir():
                try:
                    if now - marker.stat().st_mtime > self.config.max_age_seconds:
                        marker.unlink()
                except OSError:
                    pass

    def _pointer_target(self, pointer: Path) -> Target:
        try:
            session_id = pointer.read_text().strip()
        except OSError:
            return Target("", "")
        text = self.text_for(session_id)
        if not text:
            return Target("", "")
        return Target(text, signature(text))

    @staticmethod
    def _write_pointer(pointer: Path, session_id: str) -> None:
        pointer.parent.mkdir(parents=True, exist_ok=True)
        tmp = pointer.with_suffix(pointer.suffix + ".tmp")
        tmp.write_text(session_id)
        tmp.replace(pointer)


def session_id_for(
    transcript_path: str | None,
    payload: dict[str, Any] | None = None,
) -> str | None:
    if payload and payload.get("session_id"):
        return str(payload["session_id"])
    if not transcript_path:
        return None
    return Path(transcript_path).stem
