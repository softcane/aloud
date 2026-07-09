# Aloud

Aloud reads Claude Code and Codex replies out loud on macOS.

Turn it on inside a session with `/aloud-on`. Aloud speaks a short summary after each reply. Press `Cmd + Ctrl + H` to hear the full reply, or `Cmd + Ctrl + .` to stop playback.

Aloud uses [Kokoro](https://github.com/hexgrad/kokoro) for local text to speech. `pip install .` installs the Kokoro Python package. Kokoro downloads its model files from Hugging Face the first time speech generation starts, then reuses the local cache. Agent replies are not sent to an external TTS service.

## Requirements

- macOS.
- Python 3.11 or 3.12. Kokoro does not publish wheels for Python 3.13+ yet.
- [Homebrew](https://brew.sh), used by `.venv/bin/aloud install` for `espeak-ng` and Hammerspoon if they are missing.
- Claude Code, Codex CLI, or both.

## Install

```bash
git clone https://github.com/softcane/aloud.git
cd aloud
python3.11 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/aloud install
```

Use a permanent directory, such as `~/code/aloud`. Do not install from `/tmp` unless you only want a throwaway test, because the background daemon points at the venv you install from.

If `git clone` says `destination path 'aloud' already exists`, either update that checkout:

```bash
cd aloud
git pull --ff-only
```

or clone into a new directory:

```bash
git clone https://github.com/softcane/aloud.git aloud-fresh
cd aloud-fresh
```

If you use the venv command above, run Aloud as `.venv/bin/aloud`. You can also activate the venv first and then run `aloud`:

```bash
. .venv/bin/activate
aloud doctor
```

`.venv/bin/aloud install` does this:

- writes a launchd plist for the background daemon;
- creates Aloud state, cache, and log directories under `~/Library`;
- installs Hammerspoon hotkeys;
- installs `/aloud-on` and `/aloud-off` for Claude Code and Codex;
- merges Aloud hooks into Claude Code and Codex settings.

The installer backs up existing hook settings before it edits them. Claude Code hooks go in `~/.claude/settings.json`. Codex hooks go in `~/.codex/hooks.json`.

After install, restart Claude Code or Codex. In Codex, run `/hooks` and trust the Aloud hooks when Codex asks. Hammerspoon also needs Accessibility permission in macOS System Settings.

## Use

Inside a Claude Code or Codex session:

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

Multiple sessions are tracked separately. If session A speaks, the full-reply hotkey reads session A even if session B finishes in the background.

## Commands

```bash
.venv/bin/aloud doctor
.venv/bin/aloud self-test --no-audio
.venv/bin/aloud voices
.venv/bin/aloud voices --play
.venv/bin/aloud daemon
.venv/bin/aloud hook prompt
.venv/bin/aloud hook stop
.venv/bin/aloud uninstall
```

`doctor` checks the local install. `self-test --no-audio` checks the registry and hook path without using Kokoro or audio hardware. `voices --play` uses Kokoro and your current macOS output device.

## Files

Aloud keeps mutable files out of the repo:

- config: `~/Library/Application Support/Aloud/config.json`
- socket and session registry: `~/Library/Application Support/Aloud/`
- WAV cache: `~/Library/Caches/Aloud/`
- daemon log: `~/Library/Logs/Aloud/daemon.log`
- launchd plist: `~/Library/LaunchAgents/io.aloud.daemon.plist`

Edit `config.json` to change the voice or speed, then restart the daemon:

```bash
launchctl unload ~/Library/LaunchAgents/io.aloud.daemon.plist
launchctl load -w ~/Library/LaunchAgents/io.aloud.daemon.plist
```

## Remove

```bash
.venv/bin/aloud uninstall
```

Uninstall removes the daemon plist, Aloud hotkeys, slash commands, and hook entries. It leaves state, cache, and logs in place so you can inspect them. Delete these manually if you want a full cleanup:

```bash
rm -rf ~/Library/Application\ Support/Aloud ~/Library/Caches/Aloud ~/Library/Logs/Aloud
```

## Development

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
.venv/bin/aloud doctor
.venv/bin/aloud self-test --no-audio
```

Before a release, also run live smoke tests in Claude Code and Codex CLI, then run one real audio smoke with your current default output device.

## Credits

Aloud depends on [Kokoro](https://github.com/hexgrad/kokoro) for local speech, [espeak-ng](https://github.com/espeak-ng/espeak-ng) for phonemization, and [Hammerspoon](https://www.hammerspoon.org) for hotkeys.

## License

MIT.
