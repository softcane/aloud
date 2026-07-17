from __future__ import annotations

import json
import plistlib
import subprocess

from aloud.installer import ATTENTION_HOOK_EVENTS, install


def fake_runner(_args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(_args, 0, "", "")


def test_install_is_idempotent_and_preserves_non_aloud_hooks(isolated_env):
    user_home = isolated_env.app_home.parents[2]
    claude = user_home / ".claude"
    codex = user_home / ".codex"
    hammerspoon = user_home / ".hammerspoon"
    claude.mkdir()
    codex.mkdir()
    hammerspoon.mkdir()
    (hammerspoon / "init.lua").write_text("-- keep my hammerspoon config\n")
    (claude / "commands").mkdir()
    (claude / "commands" / "aloud-on.md").write_text("custom command\n")
    (claude / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "*",
                            "hooks": [{"type": "command", "command": "echo keep"}],
                        }
                    ]
                }
            }
        )
    )

    backups = []
    for _ in range(2):
        result = install(
            isolated_env,
            runner=fake_runner,
            command_prefix=["/tmp/python", "-m", "aloud"],
            install_external_tools=False,
            start_services=False,
        )
        backups.extend(result.backups)

    settings = json.loads((claude / "settings.json").read_text())
    hooks = settings["hooks"]
    stop_commands = [hook["command"] for block in hooks["Stop"] for hook in block.get("hooks", [])]
    prompt_commands = [
        hook["command"] for block in hooks["UserPromptSubmit"] for hook in block.get("hooks", [])
    ]
    codex_hooks = json.loads((codex / "hooks.json").read_text())["hooks"]
    plist = plistlib.loads(isolated_env.launch_agent.read_bytes())

    assert stop_commands.count("echo keep") == 1
    assert sum("aloud hook event" in command for command in stop_commands) == 1
    assert sum("aloud hook prompt" in command for command in prompt_commands) == 1
    assert hooks["Stop"][-1]["hooks"][0]["async"] is False
    for event in ATTENTION_HOOK_EVENTS:
        claude_commands = [
            hook["command"] for block in hooks[event] for hook in block.get("hooks", [])
        ]
        codex_commands = [
            hook["command"] for block in codex_hooks[event] for hook in block.get("hooks", [])
        ]
        assert sum("aloud hook event" in command for command in claude_commands) == 1
        assert sum("aloud hook event" in command for command in codex_commands) == 1
    assert len(codex_hooks["UserPromptSubmit"]) == 1
    assert plist["ProgramArguments"] == ["/tmp/python", "-m", "aloud", "daemon"]
    assert (claude / "commands" / "aloud-on.md").exists()
    assert (codex / "prompts" / "aloud-off.md").exists()
    assert 'aloud .. " repeat"' in (hammerspoon / "init.lua").read_text()
    assert any(path.name.startswith("init.lua.bak-") for path in backups)
    assert any(path.name.startswith("aloud-on.md.bak-") for path in backups)
    assert len({path.name for path in backups}) == len(backups)
