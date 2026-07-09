#!/usr/bin/env python3
"""Safely add Aloud's two hooks to Codex.

  Stop             -> aloud_on_stop.py     (record each reply; speak if armed)
  UserPromptSubmit -> aloud_on_prompt.py   (arm/disarm; drop old audio)

Codex reads hooks from ~/.codex/hooks.json. Its schema matches Claude Code's
(a map of event name -> list of blocks, each with a "hooks" array of command
handlers) and it hands the same JSON payload (session_id, transcript_path) on
stdin, so the exact same hook scripts serve both agents.

Writes ONLY hooks.json — it never touches config.toml, so your model,
providers, and existing `notify` program are left alone.

Backs the file up first, is idempotent (running twice changes nothing), and
refuses to write anything but valid JSON. Run:  python3 install_codex.py
"""
import json
import os
import shlex
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CODEX_HOME = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
HOOKS = os.path.join(CODEX_HOME, "hooks.json")

STOP_CMD = f"python3 {shlex.quote(os.path.join(HERE, 'aloud_on_stop.py'))}"
PROMPT_CMD = f"python3 {shlex.quote(os.path.join(HERE, 'aloud_on_prompt.py'))}"


def entry(command, timeout):
    return {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}


def has_command(block_list, needle):
    for block in block_list:
        for h in block.get("hooks", []):
            if needle in h.get("command", ""):
                return True
    return False


def strip_ours(block_list, needle):
    """Drop any block that runs our script, so we can re-add the current one."""
    kept = []
    for block in block_list:
        cmds = " ".join(h.get("command", "") for h in block.get("hooks", []))
        if needle in cmds:
            continue
        kept.append(block)
    return kept


def main():
    if not os.path.isdir(CODEX_HOME):
        print(f"no Codex home at {CODEX_HOME}; skipping Codex hooks")
        return

    if os.path.exists(HOOKS):
        with open(HOOKS) as f:
            data = json.load(f)          # dies loudly if the file is broken
        backup = f"{HOOKS}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(HOOKS, backup)
        print(f"backed up -> {backup}")
    else:
        data = {}

    hooks = data.setdefault("hooks", {})
    changed = False

    for event, cmd, needle in (
        ("Stop", STOP_CMD, "aloud_on_stop.py"),
        ("UserPromptSubmit", PROMPT_CMD, "aloud_on_prompt.py"),
    ):
        block_list = hooks.get(event, [])
        pruned = strip_ours(block_list, needle)
        already = has_command(block_list, needle) and len(pruned) == len(block_list) - 1
        if not already:
            hooks[event] = pruned + [entry(cmd, 5)]
            changed = True
            print(f"set {event} hook")

    if not changed:
        print("Codex hooks already installed, nothing to do")
        return

    tmp = HOOKS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    json.load(open(tmp))                 # verify before swapping in
    os.replace(tmp, HOOKS)
    print(f"{HOOKS} updated")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAILED (hooks.json untouched): {e}", file=sys.stderr)
        sys.exit(1)
