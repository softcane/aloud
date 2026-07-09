import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import aloud_core as core


ROOT = pathlib.Path(__file__).resolve().parents[1]


class TempCoreState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = {
            name: getattr(core, name)
            for name in (
                "APP_HOME",
                "CACHE_HOME",
                "SESSIONS",
                "LATEST",
                "SPOKEN",
                "ARMED",
                "WAV_OUT",
                "SIG_OUT",
            )
        }
        app = pathlib.Path(self.tmp.name) / "app"
        cache = pathlib.Path(self.tmp.name) / "cache"
        core.APP_HOME = str(app)
        core.CACHE_HOME = str(cache)
        core.SESSIONS = str(app / "sessions")
        core.LATEST = str(app / "sessions" / "latest")
        core.SPOKEN = str(app / "sessions" / "spoken")
        core.ARMED = str(app / "sessions" / "armed")
        core.WAV_OUT = str(cache / "last.wav")
        core.SIG_OUT = str(cache / "last.sig")
        self.addCleanup(self.restore_core)

    def restore_core(self):
        for name, value in self.old.items():
            setattr(core, name, value)

    def write_jsonl(self, name, rows):
        path = pathlib.Path(self.tmp.name) / name
        with path.open("w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        return str(path)


class CoreBehaviorTests(TempCoreState):
    def test_stop_payload_text_wins_over_transcript_fallback(self):
        transcript = self.write_jsonl(
            "claude.jsonl",
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "transcript fallback text"}
                        ]
                    },
                }
            ],
        )

        sid = core.record_stop(
            {
                "session_id": "SID-A",
                "transcript_path": transcript,
                "last_assistant_message": "stable payload **text**",
            }
        )

        self.assertEqual(sid, "SID-A")
        self.assertEqual(core.text_for("SID-A"), "stable payload text")

    def test_transcript_fallback_understands_claude_and_codex_shapes(self):
        claude = self.write_jsonl(
            "claude.jsonl",
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": "Claude **done**."}]
                    },
                }
            ],
        )
        codex = self.write_jsonl(
            "codex.jsonl",
            [
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Codex `done`."}],
                    },
                }
            ],
        )

        self.assertEqual(core.record_stop({"session_id": "C", "transcript_path": claude}), "C")
        self.assertEqual(core.record_stop({"session_id": "X", "transcript_path": codex}), "X")
        self.assertEqual(core.text_for("C"), "Claude done.")
        self.assertEqual(core.text_for("X"), "Codex.")

    def test_full_reply_target_follows_spoken_session_not_newest_session(self):
        core.record_stop({"session_id": "SID-A", "last_assistant_message": "Alpha reply."})
        core.arm("SID-A")
        time.sleep(0.01)
        core.record_stop({"session_id": "SID-B", "last_assistant_message": "Beta reply."})

        core.note_spoken("SID-A")
        spoken_text, _ = core.spoken_target()
        latest_text, _ = core.resolve_target()

        self.assertEqual(spoken_text, "Alpha reply.")
        self.assertEqual(latest_text, "Beta reply.")

    def test_session_ids_cannot_escape_the_session_directory(self):
        sid = "../bad/session"
        self.assertEqual(core.record_stop({"session_id": sid, "last_assistant_message": "Safe."}), sid)

        files = list(pathlib.Path(core.SESSIONS).glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].parent, pathlib.Path(core.SESSIONS))
        self.assertEqual(core.text_for(sid), "Safe.")


class HookAndInstallerTests(unittest.TestCase):
    def run_python(self, script, payload=None, env=None):
        data = None if payload is None else json.dumps(payload)
        return subprocess.run(
            [sys.executable, str(ROOT / script)],
            input=data,
            text=True,
            capture_output=True,
            env={**os.environ, **(env or {})},
            timeout=10,
            check=False,
        )

    def test_prompt_hook_blocks_arm_phrase_and_writes_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"ALOUD_HOME": tmp, "ALOUD_SOCK": str(pathlib.Path(tmp) / "missing.sock")}
            result = self.run_python(
                "aloud_on_prompt.py",
                {"session_id": "SID-A", "prompt": "/aloud-on"},
                env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["decision"], "block")
            self.assertTrue((pathlib.Path(tmp) / "sessions" / "armed" / "SID-A").exists())

    def test_stop_hook_sends_speak_only_for_armed_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            sock_path = pathlib.Path(tmp) / "aloud.sock"
            received = []

            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(str(sock_path))
            srv.listen(1)
            srv.settimeout(3)
            self.addCleanup(srv.close)

            def accept_once():
                conn, _ = srv.accept()
                with conn:
                    received.append(conn.recv(256).decode("utf-8"))

            thread = threading.Thread(target=accept_once)
            thread.start()

            env = {"ALOUD_HOME": tmp, "ALOUD_SOCK": str(sock_path)}
            self.run_python(
                "aloud_on_prompt.py",
                {"session_id": "SID-A", "prompt": "aloud on"},
                env,
            )
            result = self.run_python(
                "aloud_on_stop.py",
                {"session_id": "SID-A", "last_assistant_message": "Ready."},
                env,
            )
            thread.join(3)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(received, ["speak SID-A"])

    def test_installers_are_idempotent_in_temp_homes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            codex_home = home / ".codex"
            codex_home.mkdir()

            env = {**os.environ, "HOME": tmp}
            for _ in range(2):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "install_hook.py")],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

            env = {**os.environ, "CODEX_HOME": str(codex_home)}
            for _ in range(2):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "install_codex.py")],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

            claude = json.loads((home / ".claude" / "settings.json").read_text())
            codex = json.loads((codex_home / "hooks.json").read_text())

            self.assertEqual(len(claude["hooks"]["Stop"]), 1)
            self.assertEqual(len(claude["hooks"]["UserPromptSubmit"]), 1)
            self.assertEqual(len(codex["hooks"]["Stop"]), 1)
            self.assertEqual(len(codex["hooks"]["UserPromptSubmit"]), 1)

    def test_aloud_shell_command_uses_configured_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            sock_path = pathlib.Path(tmp) / "aloud.sock"
            received = []

            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(str(sock_path))
            srv.listen(1)
            srv.settimeout(3)
            self.addCleanup(srv.close)

            def accept_once():
                conn, _ = srv.accept()
                with conn:
                    received.append(conn.recv(256).decode("utf-8"))

            thread = threading.Thread(target=accept_once)
            thread.start()

            result = subprocess.run(
                [str(ROOT / "aloud"), "full"],
                capture_output=True,
                text=True,
                env={**os.environ, "ALOUD_SOCK": str(sock_path)},
                timeout=10,
                check=False,
            )
            thread.join(3)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(received, ["full"])


if __name__ == "__main__":
    unittest.main()
