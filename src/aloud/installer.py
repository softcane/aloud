from __future__ import annotations

import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

from aloud.config import ensure_config
from aloud.paths import AppPaths, default_paths

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]

ALOUD_NEEDLES = (
    "aloud hook prompt",
    "aloud hook stop",
    "aloud_on_prompt.py",
    "aloud_on_stop.py",
    "aloud forget",
)


@dataclass
class InstallResult:
    messages: list[str] = field(default_factory=list)
    backups: list[Path] = field(default_factory=list)

    def add(self, message: str) -> None:
        self.messages.append(message)


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def install(
    paths: AppPaths | None = None,
    *,
    runner: Runner = run_command,
    command_prefix: list[str] | None = None,
    install_external_tools: bool = True,
    start_services: bool = True,
) -> InstallResult:
    paths = paths or default_paths()
    command_prefix = command_prefix or [sys.executable, "-m", "aloud"]
    result = InstallResult()

    paths.ensure_runtime_dirs()
    ensure_config(paths)
    result.add(f"state directory: {paths.app_home}")
    result.add(f"cache directory: {paths.cache_home}")
    result.add(f"log file: {paths.log}")

    if install_external_tools:
        install_system_tools(runner, result)

    write_launch_agent(paths, command_prefix, result)
    if start_services:
        reload_launch_agent(paths, runner, result)
    else:
        result.add("launchd helper written but not started")
    install_hammerspoon(command_prefix, result, start_app=start_services)
    install_agent_commands(result)
    install_claude_hooks(command_prefix, result)
    install_codex_hooks(command_prefix, result)
    result.add("Codex users: run /hooks and trust the Aloud hooks if Codex asks.")
    return result


def uninstall(paths: AppPaths | None = None, *, runner: Runner = run_command) -> InstallResult:
    paths = paths or default_paths()
    result = InstallResult()
    runner(["launchctl", "unload", str(paths.launch_agent)])
    try:
        paths.launch_agent.unlink()
        result.add(f"removed {paths.launch_agent}")
    except OSError:
        pass
    remove_hammerspoon_block(result)
    remove_agent_commands(result)
    remove_claude_hooks(result)
    remove_codex_hooks(result)
    result.add("state/cache/log files were left in place; delete them manually if desired.")
    return result


def install_system_tools(runner: Runner, result: InstallResult) -> None:
    if not shutil.which("brew"):
        raise RuntimeError("Homebrew is required. Install it from https://brew.sh and retry.")
    if not shutil.which("espeak-ng"):
        runner(["brew", "install", "espeak-ng"])
        result.add("installed espeak-ng")
    if not hammerspoon_present():
        runner(["brew", "install", "--cask", "hammerspoon"])
        result.add("installed Hammerspoon")


def hammerspoon_present() -> bool:
    return bool(shutil.which("hammerspoon")) or Path("/Applications/Hammerspoon.app").exists()


def write_launch_agent(paths: AppPaths, command_prefix: list[str], result: InstallResult) -> None:
    paths.launch_agent.parent.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": "io.aloud.daemon",
        "ProgramArguments": [*command_prefix, "daemon"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardErrorPath": str(paths.log),
        "StandardOutPath": str(paths.log),
    }
    with paths.launch_agent.open("wb") as f:
        plistlib.dump(plist, f)
    result.add(f"wrote {paths.launch_agent}")


def reload_launch_agent(paths: AppPaths, runner: Runner, result: InstallResult) -> None:
    runner(["launchctl", "unload", str(paths.launch_agent)])
    completed = runner(["launchctl", "load", "-w", str(paths.launch_agent)])
    if completed.returncode == 0:
        result.add("started launchd helper")
    else:
        result.add("launchd helper was written but did not start")


def install_hammerspoon(
    command_prefix: list[str],
    result: InstallResult,
    *,
    start_app: bool = True,
) -> None:
    init = Path.home() / ".hammerspoon" / "init.lua"
    init.parent.mkdir(parents=True, exist_ok=True)
    existing = init.read_text() if init.exists() else ""
    block = hammerspoon_block(command_prefix)
    updated = replace_marked_block(
        existing,
        "-- BEGIN Aloud hotkeys",
        "-- END Aloud hotkeys",
        block,
    )
    if updated != existing:
        if init.exists():
            result.backups.append(backup_file(init))
        init.write_text(updated)
        result.add("installed Hammerspoon hotkeys")
    if start_app:
        subprocess.run(
            ["open", "-a", "Hammerspoon"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def hammerspoon_block(command_prefix: list[str]) -> str:
    command = shlex.join(command_prefix)
    escaped = command.replace("\\", "\\\\").replace('"', '\\"')
    return (
        "\n-- BEGIN Aloud hotkeys\n"
        "-- Cmd+Ctrl+H = hear the full reply, Cmd+Ctrl+. = stop\n"
        f'local aloud = "{escaped}"\n'
        'hs.hotkey.bind({"cmd","ctrl"}, "H", function() hs.execute(aloud .. " full") end)\n'
        'hs.hotkey.bind({"cmd","ctrl"}, ".", function() hs.execute(aloud .. " stop") end)\n'
        'hs.alert.show("Aloud hotkeys loaded")\n'
        "-- END Aloud hotkeys\n"
    )


def remove_hammerspoon_block(result: InstallResult) -> None:
    init = Path.home() / ".hammerspoon" / "init.lua"
    if not init.exists():
        return
    existing = init.read_text()
    updated = remove_marked_block(existing, "-- BEGIN Aloud hotkeys", "-- END Aloud hotkeys")
    if updated != existing:
        init.write_text(updated)
        result.add("removed Hammerspoon hotkeys")


def install_agent_commands(result: InstallResult) -> None:
    for target in (Path.home() / ".claude" / "commands", Path.home() / ".codex" / "prompts"):
        if not target.parent.exists():
            continue
        target.mkdir(parents=True, exist_ok=True)
        for name in ("aloud-on.md", "aloud-off.md"):
            content = files("aloud.commands").joinpath(name).read_text()
            write_text_with_backup(target / name, content, result)
        result.add(f"installed slash commands in {target}")


def remove_agent_commands(result: InstallResult) -> None:
    for target in (
        Path.home() / ".claude" / "commands" / "aloud-on.md",
        Path.home() / ".claude" / "commands" / "aloud-off.md",
        Path.home() / ".codex" / "prompts" / "aloud-on.md",
        Path.home() / ".codex" / "prompts" / "aloud-off.md",
    ):
        try:
            target.unlink()
            result.add(f"removed {target}")
        except OSError:
            pass


def install_claude_hooks(command_prefix: list[str], result: InstallResult) -> None:
    settings = Path.home() / ".claude" / "settings.json"
    if not settings.parent.exists():
        result.add("no Claude Code home found; skipped Claude hooks")
        return
    data = load_json_file(settings)
    if settings.exists():
        result.backups.append(backup_file(settings))
    hooks = data.setdefault("hooks", {})
    hooks["Stop"] = replace_hook_blocks(
        hooks.get("Stop", []),
        claude_entry([*command_prefix, "hook", "stop"], timeout=5, is_async=False),
    )
    hooks["UserPromptSubmit"] = replace_hook_blocks(
        hooks.get("UserPromptSubmit", []),
        claude_entry([*command_prefix, "hook", "prompt"], timeout=5, is_async=False),
    )
    write_json_atomic(settings, data)
    result.add("installed Claude Code hooks")


def install_codex_hooks(command_prefix: list[str], result: InstallResult) -> None:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    if not codex_home.exists():
        result.add("no Codex home found; skipped Codex hooks")
        return
    hooks_path = codex_home / "hooks.json"
    data = load_json_file(hooks_path)
    if hooks_path.exists():
        result.backups.append(backup_file(hooks_path))
    hooks = data.setdefault("hooks", {})
    hooks["Stop"] = replace_hook_blocks(
        hooks.get("Stop", []),
        codex_entry([*command_prefix, "hook", "stop"], timeout=5),
    )
    hooks["UserPromptSubmit"] = replace_hook_blocks(
        hooks.get("UserPromptSubmit", []),
        codex_entry([*command_prefix, "hook", "prompt"], timeout=5),
    )
    write_json_atomic(hooks_path, data)
    result.add("installed Codex hooks")


def remove_claude_hooks(result: InstallResult) -> None:
    settings = Path.home() / ".claude" / "settings.json"
    if not settings.exists():
        return
    data = load_json_file(settings)
    hooks = data.get("hooks", {})
    for event in ("Stop", "UserPromptSubmit"):
        hooks[event] = strip_aloud_blocks(hooks.get(event, []))
    backup_file(settings)
    write_json_atomic(settings, data)
    result.add("removed Claude Code hooks")


def remove_codex_hooks(result: InstallResult) -> None:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    hooks_path = codex_home / "hooks.json"
    if not hooks_path.exists():
        return
    data = load_json_file(hooks_path)
    hooks = data.get("hooks", {})
    for event in ("Stop", "UserPromptSubmit"):
        hooks[event] = strip_aloud_blocks(hooks.get(event, []))
    backup_file(hooks_path)
    write_json_atomic(hooks_path, data)
    result.add("removed Codex hooks")


def claude_entry(command: list[str], timeout: int, is_async: bool) -> dict[str, Any]:
    return {
        "matcher": "*",
        "hooks": [
            {
                "type": "command",
                "command": shlex.join(command),
                "timeout": timeout,
                "async": is_async,
            }
        ],
    }


def codex_entry(command: list[str], timeout: int) -> dict[str, Any]:
    return {"hooks": [{"type": "command", "command": shlex.join(command), "timeout": timeout}]}


def replace_hook_blocks(
    existing: list[dict[str, Any]],
    new_entry: dict[str, Any],
) -> list[dict[str, Any]]:
    return [*strip_aloud_blocks(existing), new_entry]


def strip_aloud_blocks(existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = []
    for block in existing:
        commands = " ".join(hook.get("command", "") for hook in block.get("hooks", []))
        if any(needle in commands for needle in ALOUD_NEEDLES):
            continue
        kept.append(block)
    return kept


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        return {}
    return json.loads(path.read_text())


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    json.loads(tmp.read_text())
    tmp.replace(path)


def write_text_with_backup(path: Path, content: str, result: InstallResult) -> None:
    if path.exists() and path.read_text() != content:
        result.backups.append(backup_file(path))
    path.write_text(content)


def backup_file(path: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    index = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.bak-{stamp}-{index}")
        index += 1
    shutil.copy2(path, backup)
    return backup


def replace_marked_block(text: str, begin: str, end: str, block: str) -> str:
    stripped = remove_marked_block(text, begin, end).rstrip()
    return f"{stripped}\n{block}" if stripped else block.lstrip()


def remove_marked_block(text: str, begin: str, end: str) -> str:
    pattern = re.compile(rf"\n?{re.escape(begin)}.*?{re.escape(end)}\n?", re.DOTALL)
    return pattern.sub("\n", text).strip() + ("\n" if text.strip() else "")
