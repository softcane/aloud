from __future__ import annotations

import glob
import json
import os
from pathlib import Path
from typing import Any

from aloud.attention import AttentionEvent, normalize_attention_event
from aloud.config import Config


def newest_transcript(home: Path | None = None) -> Path | None:
    home = home or Path.home()
    claude = glob.glob(str(home / ".claude" / "projects" / "*" / "*.jsonl"))
    codex = glob.glob(str(home / ".codex" / "sessions" / "**" / "*.jsonl"), recursive=True)
    files = [Path(path) for path in [*claude, *codex]]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def assistant_text_from_payload(payload: dict[str, Any]) -> str:
    text = payload.get("last_assistant_message") or ""
    if isinstance(text, str) and text.strip():
        return text
    return ""


def last_assistant_text(transcript_path: str | os.PathLike[str] | None) -> str | None:
    if not transcript_path:
        return None
    path = Path(transcript_path)
    text = None
    try:
        with path.open() as lines:
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                spoken = _assistant_text(obj)
                if spoken.strip():
                    text = spoken
    except OSError:
        return None
    return text


def attention_events_from_transcript(
    transcript_path: str | os.PathLike[str] | None,
    session_id: str,
    config: Config,
    *,
    start_offset: int = 0,
) -> list[AttentionEvent]:
    if not transcript_path:
        return []
    path = Path(transcript_path)
    events = []
    try:
        with path.open("rb") as lines:
            if start_offset > 0:
                lines.seek(start_offset)
            for raw_line in lines:
                line = raw_line.decode("utf-8", "ignore").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = _attention_payload(obj, session_id, path)
                if not payload:
                    continue
                event = normalize_attention_event(payload, config)
                if event:
                    events.append(event)
    except OSError:
        return []
    return events


def _assistant_text(obj: dict[str, Any]) -> str:
    if obj.get("type") == "assistant":
        if obj.get("isSidechain"):
            return ""
        blocks = obj.get("message", {}).get("content", [])
        parts = [
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(part for part in parts if part.strip())

    if obj.get("type") == "response_item":
        payload = obj.get("payload", {})
        if payload.get("type") == "message" and payload.get("role") == "assistant":
            parts = [
                block.get("text", "")
                for block in payload.get("content", [])
                if isinstance(block, dict) and block.get("type") in ("output_text", "text")
            ]
            return "\n".join(part for part in parts if part.strip())

    return ""


def _attention_payload(
    obj: dict[str, Any],
    session_id: str,
    transcript_path: Path,
) -> dict[str, Any] | None:
    base = {
        "source": _source_for_transcript(transcript_path),
        "session_id": session_id,
        "transcript_path": str(transcript_path),
        "cwd": _first_text(obj, "cwd", "working_directory", "project"),
        "turn_id": _turn_id(obj),
    }
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else obj
    name = _first_text(payload, "name", "tool_name", "toolName")
    item_type = _first_text(payload, "type", "event", "event_name")
    arguments = _arguments(payload)

    if name == "request_user_input":
        return {
            **base,
            "hook_event_name": "Transcript",
            "tool_name": name,
            "tool_input": arguments,
        }

    if "elicitation" in name.lower() or "elicitation" in item_type.lower():
        return {
            **base,
            "hook_event_name": "Elicitation",
            "tool_name": name or "elicitation",
            "tool_input": arguments,
            "message": _first_text(payload, "message", "reason", "prompt", "text"),
        }

    message = _first_text(payload, "message", "error", "reason", "text")
    status = _first_text(payload, "status", "outcome").lower()
    if item_type.lower() in {"error", "failure"} or status in {"failed", "error", "blocked"}:
        return {
            **base,
            "hook_event_name": "StopFailure",
            "error": message or status,
        }

    assistant_text = _assistant_text(obj)
    if assistant_text:
        return {
            **base,
            "hook_event_name": "Stop",
            "last_assistant_message": assistant_text,
        }

    return None


def _arguments(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("arguments", "args", "input", "params"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                loaded = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(loaded, dict):
                return loaded
    return {}


def _first_text(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _turn_id(obj: dict[str, Any]) -> str:
    for data in (obj, obj.get("payload")):
        if not isinstance(data, dict):
            continue
        value = _first_text(data, "turn_id", "request_id")
        if value:
            return value
        metadata = data.get("internal_chat_message_metadata_passthrough")
        if isinstance(metadata, dict):
            value = _first_text(metadata, "turn_id", "request_id")
            if value:
                return value
    return ""


def _source_for_transcript(transcript_path: Path) -> str:
    path = str(transcript_path)
    if ".claude" in path:
        return "Claude"
    if ".codex" in path:
        return "Codex"
    return "Agent"
