from __future__ import annotations

import argparse
import json
import shutil
import sys
from contextlib import suppress
from pathlib import Path

from aloud import __version__
from aloud.config import ensure_config, load_config
from aloud.daemon import serve
from aloud.hooks import run_prompt_hook, run_stop_hook
from aloud.installer import install, uninstall
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

    full_parser = sub.add_parser("full", help="speak the full reply")
    full_parser.set_defaults(func=lambda _args: cmd_send("full", autostart=True))

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
    commands = []
    for blocks in data.get("hooks", {}).values():
        for block in blocks:
            commands.extend(hook.get("command", "") for hook in block.get("hooks", []))
    joined = "\n".join(commands)
    return "aloud hook prompt" in joined and "aloud hook stop" in joined


if __name__ == "__main__":
    raise SystemExit(main())
