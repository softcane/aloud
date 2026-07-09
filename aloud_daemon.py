#!/usr/bin/env python3
"""Aloud daemon — keeps the voice model loaded so playback is instant.

Loads Kokoro once, then waits on a local socket for commands:

  speak <sid>  auto-cue for an armed session: speak the short GIST of the
               reply that session just finished. Fired by the Stop hook.
  full         speak the WHOLE most-recently-finished reply (the hotkey).
  play         alias for full.
  stop         stop any playback right now.
  forget       drop the audio + fingerprint (fired when you send a message).

Every text carries a fingerprint, so the one audio file is only reused when
it already holds exactly that text; otherwise it is rebuilt. Only ever
writes ONE audio file (core.WAV_OUT).
"""
import os
import socket
import subprocess
import sys

import numpy as np
import soundfile as sf
from kokoro import KPipeline

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aloud_core as core

SOCK = os.environ.get("ALOUD_SOCK", os.path.join(core.APP_HOME, "aloud.sock"))
DEVNULL = subprocess.DEVNULL

pipeline = KPipeline(lang_code="a")  # loaded ONCE, stays warm


def _read_sig():
    try:
        with open(core.SIG_OUT) as f:
            return f.read().strip()
    except OSError:
        return None


def _write_sig(sig):
    core._ensure_parent(core.SIG_OUT)
    with open(core.SIG_OUT, "w") as f:
        f.write(sig)


def synth(text):
    chunks = [a for _, _, a in pipeline(text, voice=core.VOICE, speed=core.SPEED)]
    if not chunks:
        return False
    core._ensure_parent(core.WAV_OUT)
    sf.write(core.WAV_OUT, np.concatenate(chunks), core.SAMPLE_RATE)
    return True


def stop():
    subprocess.run(["killall", "afplay"], stderr=DEVNULL, stdout=DEVNULL)


def notify(msg):
    subprocess.run(
        ["osascript", "-e", f'display notification "{msg}" with title "Aloud"'],
        stderr=DEVNULL, stdout=DEVNULL,
    )


def _play_text(text, quiet=False):
    """Stop anything playing, then speak this text — reusing the cached
    audio only when the fingerprint matches, else rebuilding it."""
    stop()  # never stack two voices
    if not text:
        if not quiet:
            notify("No reply to read yet.")
        return
    sig = core.signature(text)
    cached = os.path.exists(core.WAV_OUT) and _read_sig() == sig
    if not cached:
        if not synth(text):
            return
        _write_sig(sig)
    subprocess.Popen(["afplay", core.WAV_OUT])


def full():
    """The hotkey: speak the WHOLE reply of the session you last heard.
    Because we key off the session that actually spoke, a background tab
    finishing later cannot hijack this key."""
    text, _ = core.spoken_target()
    _play_text(text)


def speak(sid):
    """Auto-cue: speak the short gist of what an armed session just said,
    and remember that session so the hotkey reads ITS full reply. Silent
    if that session recorded nothing (never nags on tool-only turns)."""
    full_text = core.text_for(sid)
    if not full_text:
        return
    core.note_spoken(sid)
    _play_text(core.to_gist(full_text), quiet=True)


def forget():
    stop()
    for p in (core.WAV_OUT, core.SIG_OUT):
        try:
            os.remove(p)
        except OSError:
            pass


def handle(cmd):
    parts = cmd.strip().split()
    if not parts:
        return
    verb, arg = parts[0], (parts[1] if len(parts) > 1 else "")
    if verb == "speak" and arg:
        speak(arg)
    elif verb in ("full", "play"):
        full()
    elif verb == "stop":
        stop()
    elif verb == "forget":
        forget()


def main():
    os.makedirs(os.path.dirname(SOCK), exist_ok=True)
    if os.path.exists(SOCK):
        os.remove(SOCK)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    srv.listen(8)
    sys.stderr.write("aloud daemon ready\n")
    sys.stderr.flush()
    while True:
        conn, _ = srv.accept()
        try:
            data = conn.recv(256).decode("utf-8", "ignore")
            handle(data)
        finally:
            conn.close()


if __name__ == "__main__":
    main()
