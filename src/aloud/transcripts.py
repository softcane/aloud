from __future__ import annotations

import glob
import json
import os
from pathlib import Path
from typing import Any


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
