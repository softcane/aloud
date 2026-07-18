# Aloud

Local text-to-speech for Claude Code and OpenAI Codex on macOS.

Aloud reads coding-agent replies and alerts aloud with Kokoro. It tells you when
an agent asks a question, needs approval, gets blocked, or finishes a reply. Each
Claude Code or Codex session stays separate, so you choose which conversations
can speak.

Speech generation runs on your Mac. Aloud sends no reply text to a hosted
text-to-speech service.

## Why use Aloud

- Leave the terminal in the background while an agent works.
- Hear questions and approval requests before they stall a task.
- Get a short spoken summary, then request the full response when you need it.
- Keep agent replies on your machine during speech generation.

Aloud keeps routine tool calls silent. Questions take priority over completion
messages, and a new prompt stops stale playback.

## Install

Aloud requires macOS, Python 3.11 or 3.12, Homebrew, and Claude Code or Codex.

```bash
brew install python@3.11 pipx
pipx ensurepath
pipx install --python python3.11 git+https://github.com/softcane/aloud.git
aloud install
aloud doctor
```

Restart Claude Code and Codex after installation. In Codex, run `/hooks` and
trust the Aloud hooks if prompted. Give Hammerspoon Accessibility permission to
use the keyboard shortcuts.

## Use

Type this inside a Claude Code or Codex session:

```text
aloud on
```

Aloud now speaks alerts and a short gist of each completed reply in that session.

| Command | Action |
| --- | --- |
| `aloud off` | Disable Aloud for the current session |
| `aloud full` | Read the full response from the last spoken session |
| `aloud repeat` | Repeat the last question, approval request, or alert |
| `aloud stop` | Stop playback |
| `aloud voices` | List the supported voice choices |
| `aloud voices --play` | Preview each voice |

Claude Code also installs `/aloud-on` and `/aloud-off`. Codex installs
`/prompts:aloud-on` and `/prompts:aloud-off` after it reloads prompts.

### Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Cmd+Ctrl+H` | Read the full response |
| `Cmd+Ctrl+J` | Repeat the last alert |
| `Cmd+Ctrl+.` | Stop playback |

## How Aloud works

```text
Claude Code or Codex
        │ hooks and local transcript events
        ▼
  Event normalizer
        │ classify, redact, summarize, deduplicate
        ▼
  Session registry
        │ local JSON record + "speak <session-id>" command
        ▼
  Aloud daemon
        │ Unix socket
        ▼
  Kokoro → WAV → macOS afplay
```

### 1. Aloud arms one session

The `UserPromptSubmit` hook catches `aloud on` before the coding agent receives
it. Aloud writes a small marker containing the session ID, transcript path, and
current transcript position. Other sessions remain quiet.

`aloud off` removes that marker and stops playback.

### 2. Hooks capture useful events

Aloud installs hooks for questions, plan approval, permission requests,
elicitation, failures, notifications, and completed replies. The daemon also
checks armed transcripts once per second, which covers events that appear only
in the local transcript.

Aloud turns each event into a common internal format. It cleans Markdown,
removes URLs and code bodies, redacts common credential patterns, and creates a
short completion summary. A signature prevents duplicate hook and transcript
events from speaking twice.

The priority order is:

1. Questions and plan approval
2. Permission requests
3. Failures and blocked tasks
4. Completed replies

A higher-priority event can interrupt a lower-priority message.

### 3. Hooks send a session ID

Hooks save the prepared text in the local session registry. They send a short
command such as `speak 019abc...` through a Unix socket. They do not load the
speech model or push the full response through the socket.

The daemon keeps Kokoro loaded between events. This avoids paying the model
startup cost for each message.

## Kokoro integration

Aloud uses the `kokoro` Python package through one American English pipeline:

```python
KPipeline(lang_code="a")
```

For each message, Aloud passes the cleaned text, selected voice, and speech
speed to Kokoro. Kokoro converts the text into phonemes and produces one or more
audio arrays. Aloud joins those arrays with NumPy, writes a 24 kHz WAV file with
`soundfile`, then asks macOS `afplay` to play it.

Aloud splits long responses near sentence boundaries. For short responses, it
uses a hash of the spoken text to reuse the last WAV file when possible.

The default speech settings are:

| Setting | Default |
| --- | --- |
| Voice | `af_bella` |
| Speed | `0.9` |
| Sample rate | `24000` Hz |
| Spoken gist | About `240` characters |
| Synthesis chunk | Up to `1400` characters |

Available voice shortcuts include `af_heart`, `af_bella`, `am_michael`, and
`am_puck`.

### Local speech and first-run downloads

Kokoro performs speech inference on your machine. On first use, the Kokoro
package may download its model and selected voice files from Hugging Face. It
caches those assets for later use. Aloud does not send the text being spoken to
a remote inference API.

The current integration uses American English and does not request Apple's MPS
device, so Kokoro runs on the CPU on macOS.

## Privacy and local state

Aloud stores its mutable files under `~/Library`:

| Path | Contents |
| --- | --- |
| `~/Library/Application Support/Aloud/config.json` | Voice, speed, and retention settings |
| `~/Library/Application Support/Aloud/sessions/` | Armed-session markers and recent event text |
| `~/Library/Caches/Aloud/` | Generated WAV files and cache signatures |
| `~/Library/Logs/Aloud/daemon.log` | Daemon output |
| `~/Library/LaunchAgents/io.aloud.daemon.plist` | macOS background-service definition |

Aloud redacts common API key, token, password, and authorization patterns from
attention events before storage and speech. The redactor covers common formats;
review sensitive output before enabling speech.

By default, Aloud keeps up to 40 session records for two days. Edit
`config.json` to change the voice, speed, chunk sizes, or retention limits.

## Check the installation

```bash
aloud doctor
aloud self-test --no-audio
aloud self-test --attention --no-audio
```

`aloud doctor` checks the daemon socket, launch agent, hooks, cache directories,
`espeak-ng`, and the macOS audio player.

## Uninstall

```bash
aloud uninstall
pipx uninstall aloud
rm -rf ~/Library/Application\ Support/Aloud ~/Library/Caches/Aloud ~/Library/Logs/Aloud
```

`aloud uninstall` removes hooks, prompt shortcuts, hotkeys, and the launchd
service. It leaves state, cache, and log files in place until you remove them.

## License

MIT
