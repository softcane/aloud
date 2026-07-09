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
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + ". There is more on screen."
    return text


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
