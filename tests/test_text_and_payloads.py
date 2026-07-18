from __future__ import annotations

import json
from pathlib import Path

from aloud.text import to_gist, to_speech
from aloud.transcripts import assistant_text_from_payload, last_assistant_text


def test_text_cleaning_removes_code_tables_links_and_caps_length():
    markdown = """# Done

Here is [the result](https://example.com).

```python
print("secret")
```

| a | b |
| - | - |
| 1 | 2 |

Use `foo`.
"""

    spoken = to_speech(markdown, max_chars=80)

    assert "Done" in spoken
    assert "the result" in spoken
    assert "code block" in spoken
    assert "https://" not in spoken
    assert "foo" in spoken
    assert "|" not in spoken


def test_inline_code_preserves_commands_and_filenames():
    spoken = to_speech("Run `pytest tests/test_attention_events.py` and edit `src/aloud/hooks.py`.")

    assert "pytest tests/test_attention_events.py" in spoken
    assert "src/aloud/hooks.py" in spoken


def test_gist_uses_first_sentences_with_cap():
    text = "First sentence. Second sentence fits. Third sentence should not fit. " * 12

    assert to_gist(text, gist_chars=38) == "First sentence. Second sentence fits."


def test_payload_text_wins_before_transcript_parsing(tmp_path: Path):
    transcript = tmp_path / "claude.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "fallback"}]},
            }
        )
        + "\n"
    )

    payload = {
        "last_assistant_message": "payload **text**",
        "transcript_path": str(transcript),
    }

    assert assistant_text_from_payload(payload) == "payload **text**"


def test_transcript_fallback_understands_claude_and_codex(tmp_path: Path):
    claude = tmp_path / "claude.jsonl"
    claude.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Claude text"}]},
            }
        )
        + "\n"
    )
    codex = tmp_path / "codex.jsonl"
    codex.write_text(
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Codex text"}],
                },
            }
        )
        + "\n"
    )

    assert last_assistant_text(claude) == "Claude text"
    assert last_assistant_text(codex) == "Codex text"
