from __future__ import annotations

from pathlib import Path

from aloud.attention import normalize_attention_event, summarize_completion
from aloud.config import Config
from aloud.daemon import Daemon
from aloud.hooks import event_hook, prompt_hook
from aloud.registry import Registry


class FakeSynth:
    def __init__(self):
        self.calls: list[str] = []

    def synthesize(self, text: str, output_path: Path) -> bool:
        self.calls.append(text)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake wav")
        return True


class FakePlayer:
    def __init__(self):
        self.active = False
        self.played: list[Path] = []
        self.stops = 0

    def play(self, path: Path) -> None:
        self.active = True
        self.played.append(path)

    def stop(self) -> None:
        self.active = False
        self.stops += 1

    def is_playing(self) -> bool:
        return self.active


def test_claude_ask_user_question_speaks_all_questions_options_and_recommendation():
    event = normalize_attention_event(
        {
            "source": "Claude",
            "hook_event_name": "PreToolUse",
            "tool_name": "AskUserQuestion",
            "session_id": "SID-A",
            "cwd": "/repo/aloud",
            "tool_input": {
                "questions": [
                    {
                        "question": "Which migration strategy should I use for the customer data?",
                        "options": [
                            {
                                "label": "Online migration",
                                "description": "No downtime for customers",
                                "recommended": True,
                            },
                            {
                                "label": "Maintenance window",
                                "description": "Simpler rollback",
                            },
                        ],
                    },
                    {"question": "Should I create a backup first?"},
                ],
                "allow_free_form": True,
            },
        }
    )

    assert event
    assert event.kind == "question"
    assert event.priority == 1
    assert "Claude aloud asks" in event.speech_text
    assert "Which migration strategy should I use for the customer data?" in event.speech_text
    assert "Should I create a backup first?" in event.speech_text
    assert (
        "Option 1: Online migration. No downtime for customers. Recommended." in event.speech_text
    )
    assert "Option 2: Maintenance window. Simpler rollback" in event.speech_text
    assert "Free-form answer is available." in event.speech_text


def test_codex_request_user_input_works_for_unknown_skill_names():
    event = normalize_attention_event(
        {
            "source": "Codex",
            "hook_event_name": "ToolCall",
            "tool_name": "request_user_input",
            "session_id": "SID-B",
            "cwd": "/tmp/unknown-skill-project",
            "skill": "brand-new-skill-name",
            "arguments": {
                "questions": [
                    {
                        "header": "Choice",
                        "question": "Pick a release path?",
                        "options": [
                            {"label": "Ship now", "description": "Uses current tests"},
                            {"label": "Hold", "description": "Wait for QA"},
                        ],
                    }
                ]
            },
        }
    )

    assert event
    assert event.kind == "question"
    assert "Codex unknown-skill-project asks" in event.speech_text
    assert "Pick a release path?" in event.speech_text
    assert "Ship now" in event.speech_text
    assert "brand-new-skill-name" not in event.speech_text


def test_plain_text_question_without_structured_tool_is_detected():
    event = normalize_attention_event(
        {
            "source": "Codex",
            "hook_event_name": "Stop",
            "session_id": "SID-C",
            "cwd": "/repo/aloud",
            "last_assistant_message": "I found two valid paths. Which one should I take?",
        }
    )

    assert event
    assert event.kind == "question"
    assert "Which one should I take?" in event.speech_text


def test_plan_permission_blocked_completion_and_redaction():
    plan = normalize_attention_event(
        {
            "source": "Claude",
            "hook_event_name": "PreToolUse",
            "tool_name": "ExitPlanMode",
            "session_id": "SID-D",
            "cwd": "/repo/aloud",
            "tool_input": {"plan": "Change the hook event path."},
        }
    )
    permission = normalize_attention_event(
        {
            "source": "Claude",
            "hook_event_name": "PermissionRequest",
            "tool_name": "Bash",
            "session_id": "SID-D",
            "cwd": "/repo/aloud",
            "reason": "Need to run the deploy command.",
            "command": "deploy --api-key=super-secret Authorization: Bearer abc123",
        }
    )
    blocked = normalize_attention_event(
        {
            "source": "Codex",
            "hook_event_name": "StopFailure",
            "session_id": "SID-E",
            "cwd": "/repo/aloud",
            "error": "Tool failed because input is missing.",
        }
    )
    completion = normalize_attention_event(
        {
            "source": "Codex",
            "hook_event_name": "Stop",
            "session_id": "SID-E",
            "cwd": "/repo/aloud",
            "last_assistant_message": "Outcome\nThe feature works.\n- Tests cover hooks.",
        },
        Config(gist_chars=80),
    )

    assert plan and plan.kind == "plan"
    assert "asks for plan approval" in plan.speech_text
    assert permission and permission.kind == "permission"
    assert plan.priority == 1
    assert permission.priority == 2
    assert "super-secret" not in permission.speech_text
    assert "Bearer abc123" not in permission.speech_text
    assert "abc123" not in permission.speech_text
    assert "[redacted]" in permission.speech_text
    assert blocked and blocked.kind == "blocked"
    assert completion and completion.kind == "completion"
    assert completion.requires_response is False
    assert "The feature works" in completion.full_text
    assert "Tests cover hooks" in completion.full_text
    assert "The feature works" in completion.speech_text


def test_redaction_does_not_hide_plain_basic_text():
    event = normalize_attention_event(
        {
            "source": "Claude",
            "hook_event_name": "Stop",
            "session_id": "SID-RED",
            "cwd": "/repo/aloud",
            "last_assistant_message": "Outcome\nThis is a basic test harness.",
        }
    )

    assert event
    assert "basic test harness" in event.speech_text
    assert "[redacted]" not in event.speech_text


def test_routine_events_and_user_interrupts_remain_silent():
    routine = normalize_attention_event(
        {
            "source": "Claude",
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "session_id": "SID-F",
            "cwd": "/repo/aloud",
            "tool_input": {"file_path": "src/aloud/hooks.py"},
        }
    )
    interrupt = normalize_attention_event(
        {
            "source": "Codex",
            "hook_event_name": "StopFailure",
            "session_id": "SID-F",
            "cwd": "/repo/aloud",
            "error": "Interrupted by user.",
        }
    )

    assert routine is None
    assert interrupt is None


def test_registry_deduplicates_and_keeps_sessions_isolated(isolated_env):
    registry = Registry(isolated_env, Config())
    first = normalize_attention_event(
        {
            "source": "Codex",
            "hook_event_name": "Stop",
            "session_id": "SID-A",
            "cwd": "/repo/a",
            "last_assistant_message": "Outcome\nAlpha complete.",
        }
    )
    duplicate = normalize_attention_event(
        {
            "source": "Codex",
            "hook_event_name": "Notification",
            "session_id": "SID-A",
            "cwd": "/repo/a",
            "last_assistant_message": "Outcome\nAlpha complete.",
        }
    )
    second = normalize_attention_event(
        {
            "source": "Codex",
            "hook_event_name": "Stop",
            "session_id": "SID-B",
            "cwd": "/repo/b",
            "last_assistant_message": "Outcome\nBeta complete.",
        }
    )

    assert first and duplicate and second
    assert registry.record_attention(first) == "SID-A"
    assert registry.record_attention(duplicate) is None
    assert registry.record_attention(second) == "SID-B"
    registry.note_spoken("SID-A")

    assert registry.spoken_attention_target().text.startswith("Codex a completed.")
    assert registry.spoken_target().text == "Outcome\nAlpha complete."
    assert registry.resolve_target().text == "Outcome\nBeta complete."


def test_daemon_priority_repeat_full_and_chunking(isolated_env):
    registry = Registry(isolated_env, Config(max_chars=30, gist_chars=20))
    synth = FakeSynth()
    player = FakePlayer()
    daemon = Daemon(
        paths=isolated_env,
        config=Config(max_chars=30, gist_chars=20),
        registry=registry,
        synthesizer=synth,
        player=player,
    )
    completion = normalize_attention_event(
        {
            "source": "Codex",
            "hook_event_name": "Stop",
            "session_id": "SID-A",
            "cwd": "/repo/a",
            "last_assistant_message": "Outcome\n"
            + "This is a long completion that must be chunked for full playback.",
        },
        Config(max_chars=30, gist_chars=20),
    )
    permission = normalize_attention_event(
        {
            "source": "Claude",
            "hook_event_name": "PermissionRequest",
            "tool_name": "Bash",
            "session_id": "SID-B",
            "cwd": "/repo/b",
            "command": "ls",
        },
        Config(max_chars=30, gist_chars=20),
    )
    assert completion and permission
    registry.record_attention(completion)
    daemon.speak("SID-A")
    first_call_count = len(synth.calls)
    registry.record_attention(permission)
    daemon.speak("SID-B")

    permission_calls = synth.calls[first_call_count:]
    assert any("requests permission" in call for call in permission_calls)

    lower = normalize_attention_event(
        {
            "source": "Codex",
            "hook_event_name": "Stop",
            "session_id": "SID-A",
            "cwd": "/repo/a",
            "last_assistant_message": "Outcome\nAnother lower priority completion.",
        },
        Config(max_chars=30, gist_chars=20),
    )
    assert lower
    registry.record_attention(lower)
    before_lower_count = len(synth.calls)
    daemon.speak("SID-A")
    assert len(synth.calls) == before_lower_count

    question = normalize_attention_event(
        {
            "source": "Codex",
            "hook_event_name": "PreToolUse",
            "tool_name": "request_user_input",
            "session_id": "SID-A",
            "cwd": "/repo/a",
            "tool_input": {"question": "Which option should I use?"},
        },
        Config(max_chars=30, gist_chars=20),
    )
    assert question
    registry.record_attention(question)
    daemon.speak("SID-A")
    assert any("Which option" in call for call in synth.calls[before_lower_count:])

    daemon.repeat()
    repeat_calls = synth.calls[before_lower_count:]
    assert repeat_calls
    assert "Which option" in " ".join(repeat_calls)
    daemon.full()
    assert "Which option" in " ".join(synth.calls)


def test_armed_codex_transcript_monitor_uses_exact_session_path(isolated_env, tmp_path):
    armed_transcript = tmp_path / "armed.jsonl"
    other_transcript = tmp_path / "other.jsonl"
    armed_transcript.write_text(
        '{"type":"response_item","payload":{"type":"function_call",'
        '"internal_chat_message_metadata_passthrough":{"turn_id":"TURN-1"},'
        '"name":"request_user_input","arguments":"{\\"question\\":\\"Use the armed path?\\",'
        '\\"options\\":[{\\"label\\":\\"Yes\\",\\"description\\":\\"Only this session\\"}]}"}}\n'
        '{"type":"response_item","payload":{"type":"function_call_output",'
        '"internal_chat_message_metadata_passthrough":{"turn_id":"TURN-1"},'
        '"output":"{\\"answers\\":{}}"}}\n'
        '{"type":"response_item","payload":{"type":"message","role":"assistant",'
        '"internal_chat_message_metadata_passthrough":{"turn_id":"TURN-1"},'
        '"content":[{"type":"output_text","text":"Asked."}]}}\n'
    )
    other_transcript.write_text(
        '{"type":"response_item","payload":{"type":"function_call",'
        '"name":"request_user_input","arguments":"{\\"question\\":\\"Wrong session?\\",'
        '\\"options\\":[{\\"label\\":\\"No\\"}]}"}}\n'
    )
    registry = Registry(isolated_env, Config())
    registry.arm("SID-ARMED", str(armed_transcript))

    recorded = registry.record_armed_transcript_events()

    assert recorded == ["SID-ARMED"]
    assert "Use the armed path?" in registry.attention_for("SID-ARMED")
    assert "Wrong session?" not in registry.attention_for("SID-ARMED")


def test_registry_does_not_fall_back_to_global_newest_transcript(isolated_env, tmp_path):
    transcript = tmp_path / "newest.jsonl"
    transcript.write_text(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"Global text"}]}}\n'
    )
    registry = Registry(isolated_env, Config())

    assert registry.record_stop({"session_id": "SID-NO-TEXT"}) is None
    assert registry.resolve_target().text == ""


def test_hook_event_requires_armed_session_and_off_suppresses_later_events(isolated_env):
    prompt_hook({"session_id": "SID-A", "prompt": "aloud on"}, isolated_env)
    spoken = event_hook(
        {
            "source": "Codex",
            "hook_event_name": "Stop",
            "session_id": "SID-A",
            "cwd": "/repo/aloud",
            "last_assistant_message": "Outcome\nReady.",
        },
        isolated_env,
    )
    prompt_hook({"session_id": "SID-A", "prompt": "aloud off"}, isolated_env)
    suppressed = event_hook(
        {
            "source": "Codex",
            "hook_event_name": "Stop",
            "session_id": "SID-A",
            "cwd": "/repo/aloud",
            "last_assistant_message": "Outcome\nShould stay quiet.",
        },
        isolated_env,
    )

    assert spoken == "SID-A"
    assert suppressed is None


def test_summary_is_deterministic_short_and_outcome_first():
    text = """Details before the useful section.

Outcome
The migration finished and the tests passed.
- Added hook coverage.
- Preserved existing controls.
- Verified no audio path.
- Ignored extra detail.
"""

    first = summarize_completion(text, Config(gist_chars=110))
    second = summarize_completion(text, Config(gist_chars=110))

    assert first == second
    assert first.startswith("The migration finished")
    assert len(first) <= 150
