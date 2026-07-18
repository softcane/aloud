from __future__ import annotations

from pathlib import Path

from aloud.cli import main
from aloud.config import Config
from aloud.daemon import Daemon
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
        self.played: list[Path] = []
        self.stops = 0

    def play(self, path: Path) -> None:
        self.played.append(path)

    def stop(self) -> None:
        self.stops += 1


def test_daemon_uses_fake_tts_and_player_for_speak(isolated_env):
    registry = Registry(isolated_env, Config())
    registry.record_stop({"session_id": "SID-A", "last_assistant_message": "A long enough reply."})
    synth = FakeSynth()
    player = FakePlayer()
    daemon = Daemon(
        paths=isolated_env,
        config=Config(),
        registry=registry,
        synthesizer=synth,
        player=player,
    )

    daemon.handle("speak SID-A")

    assert synth.calls == ["A long enough reply."]
    assert player.played == [isolated_env.wav]
    assert isolated_env.signature.exists()
    assert registry.spoken_target().text == "A long enough reply."


def test_self_test_no_audio_uses_registry_only(isolated_env, capsys):
    exit_code = main(["self-test", "--no-audio"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "self-test ok" in captured.out


def test_attention_self_test_no_audio_reports_required_summary(isolated_env, capsys):
    exit_code = main(["self-test", "--attention", "--no-audio"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert (
        captured.out.strip() == "attention self-test ok: completion, question, plan, permission, "
        "blocked, dedupe, priority, sessions"
    )
    session_records = list(isolated_env.sessions.glob("attention-self-test-a-*.json"))
    assert session_records
