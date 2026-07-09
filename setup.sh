#!/bin/bash
# Aloud installer for macOS. Run once from inside the project folder:
#   ./setup.sh
# It sets up the voice engine, the always-on helper, and the hotkeys.
# It backs up agent hook files before editing them.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
echo "Installing Aloud into: $DIR"

APP_HOME="$HOME/Library/Application Support/Aloud"
CACHE_HOME="$HOME/Library/Caches/Aloud"
LOG_HOME="$HOME/Library/Logs/Aloud"
mkdir -p "$APP_HOME" "$CACHE_HOME" "$LOG_HOME"

# 1. Voice pronunciation helper
if ! command -v brew >/dev/null; then
  echo "ERROR: Homebrew is required. Install it from https://brew.sh then re-run."
  exit 1
fi
command -v espeak-ng >/dev/null || brew install espeak-ng

# 2. Python 3.11 environment for the voice model (isolated in .venv)
if command -v uv >/dev/null; then
  uv venv --python 3.11 >/dev/null
  uv pip install --python "$DIR/.venv/bin/python" kokoro soundfile >/dev/null
else
  PY="$(command -v python3.11 || command -v python3.12 || command -v python3)"
  "$PY" -m venv .venv
  ./.venv/bin/pip install --upgrade pip >/dev/null
  ./.venv/bin/pip install kokoro soundfile >/dev/null
fi
chmod +x aloud
echo "Voice engine installed."

# 3. Always-on helper (starts at login, keeps the voice warm)
PLIST="$HOME/Library/LaunchAgents/io.aloud.daemon.plist"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>io.aloud.daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>$DIR/.venv/bin/python</string>
    <string>$DIR/aloud_daemon.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>$LOG_HOME/daemon.log</string>
  <key>StandardOutPath</key><string>$LOG_HOME/daemon.log</string>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST"
echo "Background helper started."

# 4. Hotkeys (Hammerspoon)
command -v hammerspoon >/dev/null 2>&1 || brew list --cask hammerspoon >/dev/null 2>&1 || brew install --cask hammerspoon
HS="$HOME/.hammerspoon/init.lua"
mkdir -p "$HOME/.hammerspoon"
if ! grep -q "Aloud hotkeys" "$HS" 2>/dev/null && ! grep -Fq "$DIR/aloud" "$HS" 2>/dev/null; then
  cat >> "$HS" <<EOF

-- BEGIN Aloud hotkeys
-- Cmd+Ctrl+H = hear the FULL reply, Cmd+Ctrl+. = stop
local aloud = "$DIR/aloud"
hs.hotkey.bind({"cmd","ctrl"}, "H", function() hs.execute(aloud .. " full") end)
hs.hotkey.bind({"cmd","ctrl"}, ".", function() hs.execute(aloud .. " stop") end)
hs.alert.show("Aloud hotkeys loaded")
-- END Aloud hotkeys
EOF
fi
open -a Hammerspoon || true

# 5. Slash commands (/aloud-on and /aloud-off) for whichever agents you have.
#    Same markdown works for both: Claude Code reads ~/.claude/commands,
#    Codex reads ~/.codex/prompts.
if [ -d "$HOME/.claude" ]; then
  mkdir -p "$HOME/.claude/commands"
  cp "$DIR/commands/aloud-on.md" "$DIR/commands/aloud-off.md" "$HOME/.claude/commands/"
  echo "Claude Code slash commands installed (/aloud-on, /aloud-off)."
fi
if [ -d "$HOME/.codex" ]; then
  mkdir -p "$HOME/.codex/prompts"
  cp "$DIR/commands/aloud-on.md" "$DIR/commands/aloud-off.md" "$HOME/.codex/prompts/"
  echo "Codex slash commands installed (/aloud-on, /aloud-off)."
fi

# 6. Agent hooks. Each installer is safe: backs up first, idempotent, writes
#    only valid JSON, and only touches its own hooks file.
if [ -d "$HOME/.claude" ]; then
  python3 "$DIR/install_hook.py"      # -> ~/.claude/settings.json
  echo "Claude Code hooks installed."
fi
if [ -d "$HOME/.codex" ]; then
  python3 "$DIR/install_codex.py"     # -> ~/.codex/hooks.json (config.toml untouched)
  echo "Codex hooks installed."
fi

cat <<EOF

One manual step is left, because macOS makes YOU do it:

  Grant the hotkey permission:
  System Settings > Privacy & Security > Accessibility > turn ON Hammerspoon.

Then restart your agent (Claude Code or Codex) so it loads the new hooks. To use it:
  - Run  /aloud-on   in the session you want to hear. Each reply speaks a
    short gist. Run  /aloud-off  to silence it.
  - Press Cmd+Ctrl+H to hear the WHOLE reply. Cmd+Ctrl+. stops the voice.
EOF
