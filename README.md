# Aloud

Aloud reads Claude Code and Codex replies aloud on macOS.

Turn it on with `/aloud-on` in any session. Aloud speaks a short summary after each assistant reply. Use `Cmd + Ctrl + H` for the full reply, or `Cmd + Ctrl + .` to stop playback.

Aloud uses [Kokoro](https://github.com/hexgrad/kokoro) for local text-to-speech. The Python package installs Kokoro. Kokoro downloads its model files the first time speech generation starts, then reuses the local cache. Aloud does not send agent replies to an external TTS service.

## Requirements

- macOS.
- Python 3.11 or 3.12.
- [Homebrew](https://brew.sh).
- Claude Code, Codex CLI, or both.

## Install

```bash
git clone https://github.com/softcane/aloud.git
cd aloud
python3.11 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/aloud install
```

Restart Claude Code or Codex after install. In Codex, open `/hooks` and trust the Aloud hooks. In macOS System Settings, give Hammerspoon Accessibility permission for the hotkeys.

The installer:

- creates the Aloud config, cache, log, and session directories;
- starts a launchd daemon for speech generation;
- installs Hammerspoon hotkeys;
- installs `/aloud-on` and `/aloud-off`;
- merges Aloud hooks into Claude Code and Codex settings;
- writes timestamped backups before editing hook settings.

## Use

Inside Claude Code or Codex:

```text
/aloud-on
```

Aloud arms only that session. Later replies in that session speak a short summary. The agent does not receive `/aloud-on` as a prompt.

Controls:

- `/aloud-off`: stop speaking this session.
- `Cmd + Ctrl + H`: speak the full reply from the last session Aloud spoke.
- `Cmd + Ctrl + .`: stop playback.
- `.venv/bin/aloud full`: speak the full reply from a terminal.
- `.venv/bin/aloud stop`: stop playback from a terminal.

Multiple sessions are tracked separately. If session A speaks, the full-reply hotkey reads session A even if session B finishes later.

## Commands

```bash
.venv/bin/aloud doctor
.venv/bin/aloud self-test --no-audio
.venv/bin/aloud voices
.venv/bin/aloud voices --play
.venv/bin/aloud uninstall
```

`doctor` checks the installed files and hooks. `self-test --no-audio` checks the registry without using Kokoro or audio hardware. `voices --play` previews Kokoro voices on the current macOS output device.

## Files

Aloud writes mutable files under `~/Library`:

- config: `~/Library/Application Support/Aloud/config.json`
- socket and session registry: `~/Library/Application Support/Aloud/`
- WAV cache: `~/Library/Caches/Aloud/`
- daemon log: `~/Library/Logs/Aloud/daemon.log`
- launchd plist: `~/Library/LaunchAgents/io.aloud.daemon.plist`

Edit `config.json` to change voice, speed, or retention settings.

```bash
launchctl unload ~/Library/LaunchAgents/io.aloud.daemon.plist
launchctl load -w ~/Library/LaunchAgents/io.aloud.daemon.plist
```

## Uninstall

```bash
.venv/bin/aloud uninstall
```

Uninstall removes the launchd plist, Hammerspoon hotkeys, slash commands, and hook entries. It leaves state, cache, and logs in place for inspection.

To remove those files too:

```bash
rm -rf ~/Library/Application\ Support/Aloud ~/Library/Caches/Aloud ~/Library/Logs/Aloud
```

## Development

```bash
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
.venv/bin/aloud doctor
.venv/bin/aloud self-test --no-audio
```

Before release, also run live smoke tests in Claude Code and Codex CLI, then run one real audio smoke on the current macOS output device.

## Credits

Aloud depends on [Kokoro](https://github.com/hexgrad/kokoro) for local speech, [espeak-ng](https://github.com/espeak-ng/espeak-ng) for phonemization, and [Hammerspoon](https://www.hammerspoon.org) for hotkeys.

## License

MIT.
