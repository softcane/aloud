from __future__ import annotations

import hashlib
import re


def to_speech(markdown: str | None, max_chars: int = 1400) -> str:
    if not markdown:
        return ""
    text = re.sub(r"```.*?```", " (code block) ", markdown, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"^\s*\|.*\|\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[#>*_~`|]", "", text)
    text = re.sub(r"^\s*[-+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + ". There is more on screen."
    return text


def speech_chunks(text: str, max_chars: int) -> list[str]:
    if not text:
        return []
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]
    chunks = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break
        chunk = remaining[:max_chars]
        split_at = max(chunk.rfind(". "), chunk.rfind("? "), chunk.rfind("! "), chunk.rfind(" "))
        if split_at < max_chars // 2:
            split_at = max_chars
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return chunks


def to_gist(text: str | None, gist_chars: int = 240) -> str:
    if not text:
        return ""
    if len(text) <= gist_chars + 40:
        return text
    gist = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if not gist:
            gist = sentence
        elif len(gist) + 1 + len(sentence) <= gist_chars:
            gist += " " + sentence
        else:
            break
    return gist.strip() or text[:gist_chars].rsplit(" ", 1)[0]


def signature(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
