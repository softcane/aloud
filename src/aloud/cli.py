from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from contextlib import suppress
from pathlib import Path

from aloud import __version__
from aloud.attention import normalize_attention_event
from aloud.config import ensure_config, load_config
from aloud.daemon import serve
from aloud.hooks import run_event_hook, run_prompt_hook, run_stop_hook
from aloud.installer import ATTENTION_HOOK_EVENTS, install, uninstall
from aloud.paths import default_paths
from aloud.registry import Registry
from aloud.socket_client import send_command

VOICES = [
    ("af_heart", "Heart, warm female voice"),
    ("af_bella", "Bella, soft female voice"),
    ("am_michael", "Michael, calm male voice"),
    ("am_puck", "Puck, bright male voice"),
]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aloud")
    parser.add_argument("--version", action="version", version=f"aloud {__version__}")
    sub = parser.add_subparsers(required=True)

    install_parser = sub.add_parser("install", help="install helper, hotkeys, commands, hooks")
    install_parser.set_defaults(func=cmd_install)

    uninstall_parser = sub.add_parser("uninstall", help="remove helper, hotkeys, commands, hooks")
    uninstall_parser.set_defaults(func=cmd_uninstall)

    doctor_parser = sub.add_parser("doctor", help="check local Aloud installation")
    doctor_parser.set_defaults(func=cmd_doctor)

    daemon_parser = sub.add_parser("daemon", help="run the Aloud daemon")
    daemon_parser.set_defaults(func=cmd_daemon)

    hook_parser = sub.add_parser("hook", help="run an agent hook")
    hook_sub = hook_parser.add_subparsers(required=True)
    hook_prompt = hook_sub.add_parser("prompt", help="run UserPromptSubmit hook")
    hook_prompt.set_defaults(func=lambda _args: run_prompt_hook())
    hook_stop = hook_sub.add_parser("stop", help="run Stop hook")
    hook_stop.set_defaults(func=lambda _args: run_stop_hook())
    hook_event = hook_sub.add_parser("event", help="run lifecycle event hook")
    hook_event.set_defaults(func=lambda _args: run_event_hook())

    full_parser = sub.add_parser("full", help="speak the full reply")
    full_parser.set_defaults(func=lambda _args: cmd_send("full", autostart=True))

    repeat_parser = sub.add_parser("repeat", help="repeat the most recent attention alert")
    repeat_parser.set_defaults(func=lambda _args: cmd_send("repeat", autostart=True))

    stop_parser = sub.add_parser("stop", help="stop playback")
    stop_parser.set_defaults(func=lambda _args: cmd_send("stop"))

    voices_parser = sub.add_parser("voices", help="list or preview Kokoro voices")
    voices_parser.add_argument(
        "--play",
        action="store_true",
        help="play sample text for each voice",
    )
    voices_parser.set_defaults(func=cmd_voices)

    self_test = sub.add_parser("self-test", help="run a local Aloud smoke test")
    self_test.add_argument("--no-audio", action="store_true", help="skip Kokoro and afplay")
    self_test.add_argument("--attention", action="store_true", help="exercise attention alerts")
    self_test.set_defaults(func=cmd_self_test)

    return parser


def cmd_install(_args: argparse.Namespace) -> int:
    result = install(command_prefix=[sys.executable, "-m", "aloud"])
    for message in result.messages:
        print(message)
    for backup in result.backups:
        print(f"backup: {backup}")
    print("Restart Claude Code or Codex. In Codex, run /hooks and trust the Aloud hooks if asked.")
    return 0


def cmd_uninstall(_args: argparse.Namespace) -> int:
    result = uninstall()
    for message in result.messages:
        print(message)
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    paths = default_paths()
    config = ensure_config(paths)
    checks = [
        ("config", paths.config.exists(), str(paths.config)),
        ("socket", paths.socket.exists(), str(paths.socket)),
        ("launch agent", paths.launch_agent.exists(), str(paths.launch_agent)),
        ("log directory", paths.log_home.exists(), str(paths.log_home)),
        ("cache directory", paths.cache_home.exists(), str(paths.cache_home)),
        ("espeak-ng", bool(shutil.which("espeak-ng")), "required by Kokoro phonemizer"),
        ("afplay", bool(shutil.which("afplay")), "macOS audio player"),
    ]
    if Path.home().joinpath(".claude").exists():
        checks.append(("Claude commands", claude_commands_installed(), "~/.claude/commands"))
        checks.append(("Claude hooks", claude_hooks_installed(), "~/.claude/settings.json"))
    if Path.home().joinpath(".codex").exists():
        checks.append(("Codex prompts", codex_prompts_installed(), "~/.codex/prompts"))
        checks.append(("Codex hooks", codex_hooks_installed(), "~/.codex/hooks.json"))

    failed = False
    print(f"Aloud config: voice={config.voice} speed={config.speed}")
    for name, ok, detail in checks:
        mark = "ok" if ok else "missing"
        print(f"{mark:7} {name}: {detail}")
        failed = failed or not ok
    return 1 if failed else 0


def cmd_daemon(_args: argparse.Namespace) -> int:
    serve()
    return 0


def cmd_send(command: str, *, autostart: bool = False) -> int:
    if send_command(command, autostart=autostart):
        return 0
    print("Aloud helper is not running.", file=sys.stderr)
    return 1


def cmd_voices(args: argparse.Namespace) -> int:
    if not args.play:
        for voice, label in VOICES:
            print(f"{voice}\t{label}")
        return 0

    from aloud.daemon import AfplayPlayer, KokoroSynthesizer

    paths = default_paths()
    config = load_config(paths)
    player = AfplayPlayer()
    for voice, label in VOICES:
        sample_config = type(config)(**{**config.__dict__, "voice": voice})
        synth = KokoroSynthesizer(sample_config)
        text = f"This is Aloud using {label}. Voice name {voice}."
        out = paths.cache_home / f"voice-{voice}.wav"
        if synth.synthesize(text, out):
            print(f"playing {voice}")
            player.stop()
            player.play(out)
    return 0


def cmd_self_test(args: argparse.Namespace) -> int:
    if args.attention:
        return cmd_attention_self_test(args)
    if args.no_audio:
        paths = default_paths()
        paths.ensure_runtime_dirs()
        ensure_config(paths)
        registry = Registry(paths)
        sid = "self-test"
        registry.arm(sid)
        recorded = registry.record_stop(
            {
                "session_id": sid,
                "last_assistant_message": "Aloud self test completed.",
            }
        )
        if recorded != sid or not registry.is_armed(sid):
            print("self-test failed: registry did not record armed session", file=sys.stderr)
            return 1
        registry.note_spoken(sid)
        target = registry.spoken_target().text
        registry.disarm(sid)
        for path in (paths.sessions / f"{sid}.json", paths.latest, paths.spoken):
            with suppress(OSError):
                path.unlink()
        if "Aloud self test completed" not in target:
            print("self-test failed: spoken target mismatch", file=sys.stderr)
            return 1
        print("self-test ok")
        return 0
    return cmd_send("full", autostart=True)


def cmd_attention_self_test(args: argparse.Namespace) -> int:
    if not args.no_audio:
        return cmd_send("full", autostart=True)

    from aloud.daemon import Daemon

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
            self.stops = 0

        def play(self, _path: Path) -> None:
            self.active = True

        def stop(self) -> None:
            self.stops += 1
            self.active = False

        def is_playing(self) -> bool:
            return self.active

    paths = default_paths()
    paths.ensure_runtime_dirs()
    ensure_config(paths)
    registry = Registry(paths)
    synth = FakeSynth()
    player = FakePlayer()
    daemon = Daemon(paths=paths, registry=registry, synthesizer=synth, player=player)
    run_id = time.time_ns()
    sid_a = f"attention-self-test-a-{run_id}"
    sid_b = f"attention-self-test-b-{run_id}"
    for sid in (sid_a, sid_b):
        registry.arm(sid)

    def record_and_speak(payload: dict[str, object]) -> bool:
        event = normalize_attention_event(payload, registry.config)
        if not event:
            return False
        session_id = registry.record_attention(event)
        if session_id:
            daemon.speak(session_id)
            return True
        return False

    try:
        completion = record_and_speak(
            {
                "source": "Codex",
                "hook_event_name": "Stop",
                "session_id": sid_a,
                "cwd": "/tmp/aloud",
                "last_assistant_message": "Outcome\nCompletion worked.\n- Important result.",
            }
        )
        question = record_and_speak(
            {
                "source": "Codex",
                "hook_event_name": "PreToolUse",
                "tool_name": "request_user_input",
                "session_id": sid_a,
                "cwd": "/tmp/aloud",
                "tool_input": {
                    "questions": [
                        {
                            "question": "Which path should I use?",
                            "options": [
                                {"label": "Use local", "description": "Fast path"},
                                {
                                    "label": "Use remote (Recommended)",
                                    "description": "Safer path",
                                },
                            ],
                        }
                    ],
                    "allow_free_form": True,
                },
            }
        )
        plan = record_and_speak(
            {
                "source": "Claude",
                "hook_event_name": "PreToolUse",
                "tool_name": "ExitPlanMode",
                "session_id": sid_a,
                "cwd": "/tmp/aloud",
                "tool_input": {"plan": "Implement the checked path."},
            }
        )
        permission = record_and_speak(
            {
                "source": "Claude",
                "hook_event_name": "PermissionRequest",
                "tool_name": "Bash",
                "session_id": sid_a,
                "cwd": "/tmp/aloud",
                "reason": "Needs permission.",
                "command": "deploy --token=secret-value",
            }
        )
        player.active = False
        daemon.current_priority = None
        blocked = record_and_speak(
            {
                "source": "Codex",
                "hook_event_name": "StopFailure",
                "session_id": sid_b,
                "cwd": "/tmp/aloud-other",
                "error": "The agent is blocked on missing input.",
            }
        )
        duplicate_payload = {
            "source": "Codex",
            "hook_event_name": "StopFailure",
            "session_id": sid_b,
            "cwd": "/tmp/aloud-other",
            "error": "The agent is blocked on missing input.",
        }
        duplicate_first = normalize_attention_event(duplicate_payload, registry.config)
        dedupe = bool(duplicate_first and registry.record_attention(duplicate_first) is None)

        before_priority = synth.calls[-1]
        low_event = normalize_attention_event(
            {
                "source": "Codex",
                "hook_event_name": "Stop",
                "session_id": sid_b,
                "cwd": "/tmp/aloud-other",
                "last_assistant_message": "Outcome\nLower priority completion.",
            },
            registry.config,
        )
        if low_event:
            low_sid = registry.record_attention(low_event)
            if low_sid:
                daemon.speak(low_sid)
        priority = synth.calls[-1] == before_priority

        sessions = registry.text_for(sid_a) and registry.text_for(sid_b)
        no_secret = all("secret-value" not in call for call in synth.calls)
        checks = (completion, question, plan, permission, blocked, dedupe, priority, sessions)
        if all((*checks, no_secret)):
            print(
                "attention self-test ok: completion, question, plan, permission, "
                "blocked, dedupe, priority, sessions"
            )
            return 0
        print("attention self-test failed", file=sys.stderr)
        return 1
    finally:
        registry.disarm(sid_a)
        registry.disarm(sid_b)


def claude_commands_installed() -> bool:
    root = Path.home() / ".claude" / "commands"
    return (root / "aloud-on.md").exists() and (root / "aloud-off.md").exists()


def codex_prompts_installed() -> bool:
    root = Path.home() / ".codex" / "prompts"
    return (root / "aloud-on.md").exists() and (root / "aloud-off.md").exists()


def claude_hooks_installed() -> bool:
    path = Path.home() / ".claude" / "settings.json"
    return hooks_file_contains_aloud(path)


def codex_hooks_installed() -> bool:
    path = Path.home() / ".codex" / "hooks.json"
    return hooks_file_contains_aloud(path)


def hooks_file_contains_aloud(path: Path) -> bool:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    hooks = data.get("hooks", {})
    prompt_commands = []
    for block in hooks.get("UserPromptSubmit", []):
        prompt_commands.extend(hook.get("command", "") for hook in block.get("hooks", []))
    if not any("aloud hook prompt" in command for command in prompt_commands):
        return False
    for event in ATTENTION_HOOK_EVENTS:
        event_commands = []
        for block in hooks.get(event, []):
            event_commands.extend(hook.get("command", "") for hook in block.get("hooks", []))
        if not any("aloud hook event" in command for command in event_commands):
            return False
    commands = []
    for blocks in hooks.values():
        for block in blocks:
            commands.extend(hook.get("command", "") for hook in block.get("hooks", []))
    joined = "\n".join(commands)
    return "aloud hook prompt" in joined and "aloud hook event" in joined


if __name__ == "__main__":
    raise SystemExit(main())
