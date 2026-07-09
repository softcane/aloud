#!/usr/bin/env python3
"""Safely add Aloud's two hooks to ~/.claude/settings.json.

  Stop             -> aloud_on_stop.py     (record each reply; speak if armed)
  UserPromptSubmit -> aloud_on_prompt.py   (arm/disarm; drop old audio)

The Stop hook is async (it must not slow Claude). The prompt hook is
synchronous, because it needs to block the phrase "aloud on" from reaching
Claude when you use it to arm the session.

Backs the file up first, is idempotent (running twice changes nothing),
migrates the older `aloud forget` entry if present, and refuses to write
anything but valid JSON. Run:  python3 install_hook.py
"""
import json
import os
import shlex
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.expanduser("~/.claude/settings.json")

STOP_CMD = f"python3 {shlex.quote(os.path.join(HERE, 'aloud_on_stop.py'))}"
PROMPT_CMD = f"python3 {shlex.quote(os.path.join(HERE, 'aloud_on_prompt.py'))}"

# Any UserPromptSubmit block mentioning one of these is an old/ours Aloud
# entry, dropped and replaced so re-running always lands on the current one.
UPS_OURS = ("aloud_on_prompt.py", "aloud forget")


def entry(command, timeout, is_async):
    return {
        "matcher": "*",
        "hooks": [{"type": "command", "command": command,
                   "timeout": timeout, "async": is_async}],
    }


def has_command(hook_list, needle):
    for block in hook_list:
        for h in block.get("hooks", []):
            if needle in h.get("command", ""):
                return True
    return False


def strip_ours(hook_list):
    """Drop any Aloud-owned blocks so we can re-add the current one."""
    kept = []
    for block in hook_list:
        cmds = " ".join(h.get("command", "") for h in block.get("hooks", []))
        if any(n in cmds for n in UPS_OURS):
            continue
        kept.append(block)
    return kept


def main():
    if os.path.exists(SETTINGS):
        with open(SETTINGS) as f:
            data = json.load(f)          # dies loudly if the file is broken
        backup = f"{SETTINGS}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(SETTINGS, backup)
        print(f"backed up -> {backup}")
    else:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        data = {}

    hooks = data.setdefault("hooks", {})
    changed = False

    stop_list = hooks.setdefault("Stop", [])
    if not has_command(stop_list, "aloud_on_stop.py"):
        stop_list.append(entry(STOP_CMD, 5, True))
        changed = True
        print("added Stop hook (record reply; speak it if the session is armed)")

    # Rebuild the prompt hook so re-running migrates the old `aloud forget`
    # entry to the current synchronous aloud_on_prompt.py.
    ups_list = hooks.setdefault("UserPromptSubmit", [])
    pruned = strip_ours(ups_list)
    already = has_command(ups_list, "aloud_on_prompt.py") and len(pruned) == len(ups_list) - 1
    if not already:
        hooks["UserPromptSubmit"] = pruned + [entry(PROMPT_CMD, 5, False)]
        changed = True
        print("set UserPromptSubmit hook (arm/disarm + drop old audio)")

    if not changed:
        print("hooks already installed, nothing to do")
        return

    tmp = SETTINGS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    json.load(open(tmp))                 # verify before swapping in
    os.replace(tmp, SETTINGS)
    print("settings.json updated")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAILED (settings.json untouched): {e}", file=sys.stderr)
        sys.exit(1)
