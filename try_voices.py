#!/usr/bin/env python3
"""Hear several warm Kokoro voices back to back, so you can pick one.

Run:  .venv/bin/python try_voices.py
First run downloads the Kokoro model (~a few hundred MB) once.

When you find one you like, put its name in aloud_core.py (the VOICE line).
"""
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf
from kokoro import KPipeline

SAMPLE_RATE = 24000
SPEED = 0.9  # < 1.0 is slower / calmer

# a handful of the warmer English voices to compare
VOICES = [
    ("af_heart", "Heart, a warm female voice"),
    ("af_bella", "Bella, a softer female voice"),
    ("am_michael", "Michael, a calm male voice"),
    ("am_puck", "Puck, a brighter male voice"),
]

pipeline = KPipeline(lang_code="a")  # 'a' = American English


def say(voice, text):
    chunks = [a for _, _, a in pipeline(text, voice=voice, speed=SPEED)]
    if not chunks:
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, np.concatenate(chunks), SAMPLE_RATE)
        subprocess.run(["afplay", tmp.name])


def main():
    for voice, label in VOICES:
        sentence = (
            f"Hi. This is the aloud tool. "
            f"You are listening to {label}. "
            f"If you like this one, remember its name."
        )
        print(f"\n>>> Playing: {voice}  ({label})")
        try:
            say(voice, sentence)
        except Exception as e:
            print(f"    FAILED for {voice}: {e}", file=sys.stderr)
    print("\nDone. Put the name you liked in aloud_core.py (the VOICE line).")


if __name__ == "__main__":
    main()
