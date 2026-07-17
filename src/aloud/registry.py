from __future__ import annotations

import hashlib
import json
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aloud.attention import AttentionEvent
from aloud.config import Config, load_config
from aloud.paths import AppPaths, default_paths
from aloud.text import signature, to_speech
from aloud.transcripts import (
    assistant_text_from_payload,
    attention_events_from_transcript,
    last_assistant_text,
)


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

    def arm(self, session_id: str | None, transcript_path: str | None = None) -> None:
        name = session_file_name(session_id)
        if not name:
            return
        self.paths.armed.mkdir(parents=True, exist_ok=True)
        record = {"session": session_id, "transcript": transcript_path or "", "ts": time.time()}
        (self.paths.armed / name).write_text(json.dumps(record))

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
        return self._record_text(session_id, "text")

    def attention_for(self, session_id: str | None) -> str:
        return self._record_text(session_id, "attention")

    def priority_for(self, session_id: str | None) -> int:
        name = session_file_name(session_id)
        if not name:
            return 4
        try:
            record = json.loads((self.paths.sessions / f"{name}.json").read_text())
            return int(record.get("priority", 4))
        except (OSError, json.JSONDecodeError):
            return 4

    def record_stop(self, payload: dict[str, Any]) -> str | None:
        transcript = payload.get("transcript_path")
        text = assistant_text_from_payload(payload)
        if not text and transcript:
            text = last_assistant_text(transcript) or ""
        text = to_speech(text, 0)
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

    def record_attention(self, event: AttentionEvent) -> str | None:
        name = session_file_name(event.session_id)
        if not name or self._seen(event.session_id, event.dedupe_key):
            return None
        existing = self._record(event.session_id)
        if (
            existing
            and existing.get("turn")
            and existing.get("turn") == event.turn_id
            and int(existing.get("priority", 4)) <= event.priority
        ):
            self._mark_seen(event.session_id, event.dedupe_key)
            return None

        self.paths.sessions.mkdir(parents=True, exist_ok=True)
        record = {
            "text": event.full_text,
            "attention": event.speech_text,
            "priority": event.priority,
            "kind": event.kind,
            "dedupe": event.dedupe_key,
            "turn": event.turn_id,
            "ts": time.time(),
            "session": event.session_id,
            "source": event.source,
            "project": event.project,
            "transcript": event.transcript_path,
        }
        (self.paths.sessions / f"{name}.json").write_text(json.dumps(record))
        self._write_pointer(self.paths.latest, event.session_id)
        self._mark_seen(event.session_id, event.dedupe_key)
        self.prune()
        return event.session_id

    def record_armed_transcript_events(self) -> list[str]:
        recorded = []
        for session_id, transcript_path in self.armed_transcripts():
            for event in attention_events_from_transcript(
                transcript_path,
                session_id,
                self.config,
            ):
                if self.record_attention(event):
                    recorded.append(session_id)
        return recorded

    def note_spoken(self, session_id: str | None) -> None:
        if session_id:
            self._write_pointer(self.paths.spoken, session_id)

    def spoken_target(self) -> Target:
        target = self._pointer_target(self.paths.spoken)
        if target.text:
            return target
        return self.resolve_target()

    def spoken_attention_target(self) -> Target:
        target = self._pointer_target(self.paths.spoken, key="attention")
        if target.text:
            return target
        target = self._pointer_target(self.paths.latest, key="attention")
        if target.text:
            return target
        return self.spoken_target()

    def resolve_target(self) -> Target:
        target = self._pointer_target(self.paths.latest)
        if target.text:
            return target
        return Target("", "")

    def armed_transcripts(self) -> list[tuple[str, str]]:
        if not self.paths.armed.exists():
            return []
        sessions = []
        for marker in self.paths.armed.iterdir():
            try:
                record = json.loads(marker.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            session_id = str(record.get("session") or marker.name)
            transcript = str(record.get("transcript") or "")
            if session_id and transcript:
                sessions.append((session_id, transcript))
        return sessions

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

    def _record_text(self, session_id: str | None, key: str) -> str:
        record = self._record(session_id)
        if not record:
            return ""
        return record.get(key, "")

    def _record(self, session_id: str | None) -> dict[str, Any]:
        name = session_file_name(session_id)
        if not name:
            return {}
        try:
            record = json.loads((self.paths.sessions / f"{name}.json").read_text())
            return record if isinstance(record, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _pointer_target(self, pointer: Path, *, key: str = "text") -> Target:
        try:
            session_id = pointer.read_text().strip()
        except OSError:
            return Target("", "")
        text = self._record_text(session_id, key)
        if not text and key != "text":
            text = self.text_for(session_id)
        if not text:
            return Target("", "")
        return Target(text, signature(text))

    def _seen(self, session_id: str, event_signature: str) -> bool:
        name = session_file_name(session_id)
        return bool(name) and (self.paths.sessions / "seen" / name / event_signature).exists()

    def _mark_seen(self, session_id: str, event_signature: str) -> None:
        name = session_file_name(session_id)
        if not name:
            return
        directory = self.paths.sessions / "seen" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / event_signature).touch()

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
