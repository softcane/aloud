# Aloud

Hear Claude Code and Codex replies and alerts on macOS.

Aloud runs as a local helper. Turn it on in a session, and it speaks when the
agent needs you or finishes a reply. Speech uses Kokoro locally. Aloud does not
send replies to a hosted text-to-speech service.

## Speaks When

- Claude Code or Codex asks a question or shows choices.
- The agent asks for plan approval, permission, or elicitation.
- The agent becomes blocked or fails.
- The agent completes a reply.

Aloud keeps sessions separate, redacts common secret values, and keeps routine
tool calls silent.

## Install

Requirements: macOS, Python 3.11 or 3.12, Homebrew, Claude Code or Codex.

```bash
brew install python@3.11 pipx
pipx ensurepath
pipx install --python python3.11 git+https://github.com/softcane/aloud.git
aloud install
aloud doctor
```

Restart Claude Code and Codex after install. In Codex, run `/hooks` and trust
the Aloud hooks if asked. Give Hammerspoon Accessibility permission for hotkeys.

## Use

In a Claude Code or Codex session:

```text
aloud on
```

Controls:

- `aloud off`: stop and disable Aloud for this session.
- `aloud full`: speak the full response for the last spoken session.
- `aloud repeat`: repeat the last attention alert.
- `aloud stop`: stop playback.
- `Cmd+Ctrl+H`: full response.
- `Cmd+Ctrl+J`: repeat.
- `Cmd+Ctrl+.`: stop.

Claude Code also gets `/aloud-on` and `/aloud-off`. Codex gets
`/prompts:aloud-on` and `/prompts:aloud-off` after it reloads prompts.

## Check

```bash
aloud doctor
aloud self-test --no-audio
aloud voices
```

## Files

Aloud stores mutable files under `~/Library`:

- `~/Library/Application Support/Aloud/config.json`
- `~/Library/Application Support/Aloud/`
- `~/Library/Caches/Aloud/`
- `~/Library/Logs/Aloud/daemon.log`
- `~/Library/LaunchAgents/io.aloud.daemon.plist`

Edit `config.json` to change voice, speed, and retention.

## Uninstall

```bash
aloud uninstall
pipx uninstall aloud
rm -rf ~/Library/Application\ Support/Aloud ~/Library/Caches/Aloud ~/Library/Logs/Aloud
```

`aloud uninstall` removes hooks, commands, prompt shortcuts, hotkeys, and the
launchd plist. It leaves state files unless you remove them.

## Develop

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
```

## License

MIT
