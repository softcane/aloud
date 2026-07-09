# Aloud

Aloud reads Claude Code and Codex replies out loud on your Mac.

Run `/aloud-on` in a session. When the agent replies, Aloud speaks a short summary. Press `Cmd + Ctrl + H` for the full reply, or `Cmd + Ctrl + .` to stop playback.

Aloud uses [Kokoro](https://github.com/hexgrad/kokoro), an open text-to-speech model. Setup installs Kokoro into a local `.venv` and downloads the voice model the first time the helper starts. After that, speech generation runs locally. Your agent replies are not sent to an external TTS service.

After setup, Aloud is self-contained on your Mac apart from normal updates you choose to run.

## Requirements

- macOS on Apple Silicon or Intel.
- [Homebrew](https://brew.sh).
- Claude Code, Codex, or both.

## Install

```bash
git clone https://github.com/softcane/aloud.git
cd aloud
./setup.sh
```

Setup does four things:

- installs `espeak-ng`, Kokoro, and `soundfile`;
- starts a launchd helper that keeps Kokoro loaded;
- adds Hammerspoon hotkeys;
- installs `/aloud-on` and `/aloud-off` plus hooks for Claude Code and Codex.

Setup backs up agent settings before editing them. It writes Claude Code hooks to `~/.claude/settings.json` and Codex hooks to `~/.codex/hooks.json`. It does not edit Codex `config.toml`.

macOS needs one manual step: open System Settings, go to Privacy & Security, then Accessibility, and enable Hammerspoon. Restart Claude Code or Codex after setup so the agent reloads its hooks. In Codex, review and trust the new hooks if Codex asks.

## Use

In the session you want to hear:

```text
/aloud-on
```

Aloud arms that session. The agent does not see the command as a request. Each later reply in that session speaks a short summary.

- `Cmd + Ctrl + H`: speak the full reply from the session you last heard.
- `Cmd + Ctrl + .`: stop playback.
- `/aloud-off`: silence that session.

When you send the next prompt, Aloud deletes the old cached audio so the next reply cannot replay stale text.

## Multiple Sessions

Each session arms itself. If session A speaks a summary, `Cmd + Ctrl + H` reads session A's full reply even if session B finishes later in the background.

If two armed sessions finish together, the newer summary interrupts the older one. The full-reply hotkey then follows the newer voice.

## Files Aloud Writes

- `~/Library/Application Support/Aloud`: session registry and socket.
- `~/Library/Caches/Aloud`: one cached WAV file and its fingerprint.
- `~/Library/Logs/Aloud/daemon.log`: helper log.
- `~/Library/LaunchAgents/io.aloud.daemon.plist`: launchd helper.

Session records are capped at 40 and pruned after two days.

## Kokoro Voices

Hear the bundled voice choices:

```bash
.venv/bin/python try_voices.py
```

Pick a voice name, edit `VOICE` in `aloud_core.py`, then restart the helper:

```bash
launchctl unload ~/Library/LaunchAgents/io.aloud.daemon.plist
launchctl load ~/Library/LaunchAgents/io.aloud.daemon.plist
```

`SPEED` in `aloud_core.py` controls pacing. Values below `1.0` speak slower.

## How It Works

Claude Code and Codex run the same two hooks:

- `aloud_on_prompt.py` arms or disarms the current session and blocks the control phrase from reaching the agent.
- `aloud_on_stop.py` records the cleaned assistant reply and asks the helper to speak when the session is armed.

The hooks use only the Python standard library. The daemon, `aloud_daemon.py`, keeps Kokoro loaded, turns text into `last.wav`, and plays it with `afplay`.

## Troubleshooting

Check the helper:

```bash
launchctl list | grep aloud
```

Read the log:

```bash
cat ~/Library/Logs/Aloud/daemon.log
```

Test playback without the hotkey:

```bash
./aloud full
```

If hotkeys do nothing, confirm Hammerspoon has Accessibility permission.

## Remove

Unload the helper:

```bash
launchctl unload ~/Library/LaunchAgents/io.aloud.daemon.plist
```

Then remove:

- `~/Library/LaunchAgents/io.aloud.daemon.plist`
- the Aloud block in `~/.hammerspoon/init.lua`
- `~/.claude/commands/aloud-on.md` and `~/.claude/commands/aloud-off.md`
- `~/.codex/prompts/aloud-on.md` and `~/.codex/prompts/aloud-off.md`
- the Aloud hook entries in `~/.claude/settings.json` and `~/.codex/hooks.json`
- `~/Library/Application Support/Aloud`
- `~/Library/Caches/Aloud`
- `~/Library/Logs/Aloud`

The installers leave timestamped settings backups.

## Credits

Aloud depends on [Kokoro](https://github.com/hexgrad/kokoro) for local text-to-speech and [Hammerspoon](https://www.hammerspoon.org) for hotkeys.

## License

MIT.
