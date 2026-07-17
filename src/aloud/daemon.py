from __future__ import annotations

import os
import socket
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol

from aloud.config import Config, load_config
from aloud.paths import AppPaths, default_paths
from aloud.registry import Registry
from aloud.text import signature, speech_chunks, to_gist


class Synthesizer(Protocol):
    def synthesize(self, text: str, output_path: os.PathLike[str] | str) -> bool: ...


class Player(Protocol):
    def play(self, path: os.PathLike[str] | str) -> None: ...

    def stop(self) -> None: ...


@dataclass
class KokoroSynthesizer:
    config: Config

    def __post_init__(self) -> None:
        import numpy as np
        import soundfile as sf
        from kokoro import KPipeline

        self._np = np
        self._sf = sf
        self._pipeline = KPipeline(lang_code="a")

    def synthesize(self, text: str, output_path: os.PathLike[str] | str) -> bool:
        chunks = [
            audio
            for _, _, audio in self._pipeline(
                text,
                voice=self.config.voice,
                speed=self.config.speed,
            )
        ]
        if not chunks:
            return False
        output = os.fspath(output_path)
        os.makedirs(os.path.dirname(output), exist_ok=True)
        self._sf.write(output, self._np.concatenate(chunks), self.config.sample_rate)
        return True


class AfplayPlayer:
    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None

    def play(self, path: os.PathLike[str] | str) -> None:
        self._process = subprocess.Popen(["afplay", os.fspath(path)])

    def stop(self) -> None:
        subprocess.run(
            ["killall", "afplay"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        self._process = None

    def wait(self) -> None:
        if self._process is not None:
            self._process.wait()
            self._process = None

    def is_playing(self) -> bool:
        return self._process is not None and self._process.poll() is None


class Daemon:
    def __init__(
        self,
        paths: AppPaths | None = None,
        config: Config | None = None,
        registry: Registry | None = None,
        synthesizer: Synthesizer | None = None,
        player: Player | None = None,
    ):
        self.paths = paths or default_paths()
        self.config = config or load_config(self.paths)
        self.registry = registry or Registry(self.paths, self.config)
        self.synthesizer = synthesizer or KokoroSynthesizer(self.config)
        self.player = player or AfplayPlayer()
        self.current_priority: int | None = None

    def handle(self, command: str) -> None:
        parts = command.strip().split(maxsplit=1)
        if not parts:
            return
        verb = parts[0]
        arg = parts[1] if len(parts) > 1 else ""
        if verb == "speak" and arg:
            self.speak(arg)
        elif verb in ("full", "play"):
            self.full()
        elif verb == "repeat":
            self.repeat()
        elif verb == "stop":
            self.player.stop()
            self.current_priority = None
        elif verb == "forget":
            self.forget()

    def full(self) -> None:
        self._play_text(self.registry.spoken_target().text, priority=0)

    def repeat(self) -> None:
        self._play_text(self.registry.spoken_attention_target().text, priority=0)

    def speak(self, session_id: str) -> None:
        full_text = self.registry.text_for(session_id)
        if not full_text:
            return
        priority = self.registry.priority_for(session_id)
        attention_text = self.registry.attention_for(session_id)
        if not self._should_play(priority):
            return
        self.registry.note_spoken(session_id)
        self._play_text(
            attention_text or to_gist(full_text, self.config.gist_chars),
            quiet=True,
            priority=priority,
        )

    def forget(self) -> None:
        self.player.stop()
        self.current_priority = None
        for path in (self.paths.wav, self.paths.signature):
            with suppress(OSError):
                path.unlink()

    def _play_text(self, text: str, quiet: bool = False, priority: int = 4) -> None:
        if not self._should_play(priority):
            return
        self.player.stop()
        self.current_priority = priority
        if not text:
            if not quiet:
                notify("No reply to read yet.")
            return
        chunks = speech_chunks(text, self.config.max_chars)
        if len(chunks) > 1:
            self._play_chunks(chunks)
            return
        sig = signature(text)
        cached = self.paths.wav.exists() and self._read_signature() == sig
        if not cached:
            if not self.synthesizer.synthesize(text, self.paths.wav):
                return
            self.paths.signature.parent.mkdir(parents=True, exist_ok=True)
            self.paths.signature.write_text(sig)
        self.player.play(self.paths.wav)

    def _play_chunks(self, chunks: list[str]) -> None:
        for index, chunk in enumerate(chunks, 1):
            out = self.paths.cache_home / f"last-{index}.wav"
            if not self.synthesizer.synthesize(chunk, out):
                return
            self.player.play(out)
            wait = getattr(self.player, "wait", None)
            if callable(wait):
                wait()

    def _should_play(self, priority: int) -> bool:
        is_playing = getattr(self.player, "is_playing", None)
        active = bool(is_playing()) if callable(is_playing) else False
        if not active or self.current_priority is None:
            return True
        return priority <= self.current_priority

    def _read_signature(self) -> str | None:
        try:
            return self.paths.signature.read_text().strip()
        except OSError:
            return None


def notify(message: str) -> None:
    subprocess.run(
        ["osascript", "-e", f'display notification "{message}" with title "Aloud"'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def serve(paths: AppPaths | None = None) -> None:
    paths = paths or default_paths()
    paths.ensure_runtime_dirs()
    if paths.socket.exists():
        paths.socket.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(paths.socket))
    server.listen(8)
    sys.stderr.write("aloud daemon ready\n")
    sys.stderr.flush()
    daemon = Daemon(paths=paths)
    while True:
        conn, _ = server.accept()
        try:
            data = conn.recv(256).decode("utf-8", "ignore")
            daemon.handle(data)
        finally:
            conn.close()
