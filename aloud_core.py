#!/usr/bin/env python3
"""Aloud core — find a coding agent's last reply and turn it into speech.

Works with both Claude Code and Codex. Both run a Stop hook when a reply
finishes and both hand the hook a JSON payload with a session_id and a
transcript_path, so the same code serves either agent; the only thing that
differs is the transcript's on-disk shape, which last_assistant_text reads
for both.

Two ways to pick which reply to read:

1. The session registry (preferred). Each session runs a Stop hook
   (aloud_on_stop.py) that records its finished reply. The hotkey reads the
   most-recently-*completed* reply. This is accurate with many sessions
   open, because a Stop fires only when a reply finishes, unlike file
   timestamps which also change on tool output and background writes.

2. Newest transcript (fallback). If the hook is not installed yet, fall
   back to the most-recently-modified session file, across both agents.

Every reply gets a short fingerprint so the daemon can tell whether the
one audio file already matches the reply you asked for.
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECTS = os.path.expanduser("~/.claude/projects")     # Claude Code transcripts
CODEX_SESSIONS = os.path.expanduser("~/.codex/sessions")  # Codex rollout transcripts

APP_HOME = os.environ.get(
    "ALOUD_HOME",
    os.path.expanduser("~/Library/Application Support/Aloud"),
)
CACHE_HOME = os.environ.get(
    "ALOUD_CACHE_HOME",
    os.path.expanduser("~/Library/Caches/Aloud"),
)

SESSIONS = os.path.join(APP_HOME, "sessions")   # one small .json per session
LATEST = os.path.join(SESSIONS, "latest")       # newest-finished session (any session)
SPOKEN = os.path.join(SESSIONS, "spoken")       # the session whose voice is in your ear now
ARMED = os.path.join(SESSIONS, "armed")         # one empty marker file per armed session

VOICE = "af_bella"          # change to any Kokoro voice (see try_voices.py)
SPEED = 0.9                 # < 1.0 is slower / calmer
SAMPLE_RATE = 24000
MAX_CHARS = 1400            # cap the FULL read so a huge reply does not talk forever
GIST_CHARS = 240            # the short auto-spoken headline for an armed session

WAV_OUT = os.path.join(CACHE_HOME, "last.wav")    # the ONE audio file, reused
SIG_OUT = os.path.join(CACHE_HOME, "last.sig")    # fingerprint of what WAV_OUT holds

# keep the registry bounded
KEEP_SESSIONS = 40
MAX_AGE_SECONDS = 2 * 24 * 3600


def _ensure_parent(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _session_file_name(sid):
    """A session id is data from the agent. Keep it out of path syntax."""
    sid = str(sid or "")
    clean = re.sub(r"[^A-Za-z0-9_.-]", "_", sid).strip("._")
    if not clean:
        return ""
    if clean != sid:
        clean = clean[:120] + "-" + hashlib.sha1(sid.encode("utf-8")).hexdigest()[:12]
    return clean[:200]


# ---- reading transcripts ---------------------------------------------------

def newest_transcript():
    files = glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))
    files += glob.glob(os.path.join(CODEX_SESSIONS, "**", "*.jsonl"), recursive=True)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def _assistant_text(obj):
    """Assistant text from one transcript line, or '' if the line is not an
    assistant turn. Understands both agents' shapes:

      Claude Code: {"type":"assistant","message":{"content":[{"type":"text",...}]}}
      Codex:       {"type":"response_item",
                    "payload":{"type":"message","role":"assistant",
                               "content":[{"type":"output_text","text":...}]}}
    """
    if obj.get("type") == "assistant":              # Claude Code
        if obj.get("isSidechain"):                  # ignore subagent chatter
            return ""
        blocks = obj.get("message", {}).get("content", [])
        parts = [b.get("text", "") for b in blocks
                 if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p.strip())

    if obj.get("type") == "response_item":          # Codex
        p = obj.get("payload", {})
        if p.get("type") == "message" and p.get("role") == "assistant":
            parts = [b.get("text", "") for b in p.get("content", [])
                     if isinstance(b, dict) and b.get("type") in ("output_text", "text")]
            return "\n".join(p for p in parts if p.strip())

    return ""


def last_assistant_text(transcript_path):
    """Last assistant turn that actually contains spoken text (skips
    tool-only turns), for either agent's transcript."""
    text = None
    try:
        with open(transcript_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                spoken = _assistant_text(obj)
                if spoken.strip():
                    text = spoken
    except OSError:
        return None
    return text


def assistant_text_from_payload(payload):
    """Text supplied directly by a hook payload, if available.

    Both Claude Code and Codex now expose the final assistant text on Stop
    hooks. Prefer that stable hook field over transcript parsing; keep
    transcript parsing as a fallback for older payloads.
    """
    text = payload.get("last_assistant_message") or ""
    if isinstance(text, str) and text.strip():
        return text
    return ""


def to_speech(md):
    """Markdown -> plain prose a voice can read comfortably, length-capped."""
    if not md:
        return ""
    md = re.sub(r"```.*?```", " (code block) ", md, flags=re.DOTALL)
    md = re.sub(r"`[^`]*`", "", md)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"https?://\S+", "", md)
    md = re.sub(r"^\s*\|.*\|\s*$", "", md, flags=re.MULTILINE)  # table rows
    md = re.sub(r"[#>*_~`|]", "", md)
    md = re.sub(r"^\s*[-+]\s+", "", md, flags=re.MULTILINE)
    md = re.sub(r"\n{2,}", ". ", md)
    md = re.sub(r"\s+([.,!?;:])", r"\1", md)
    md = re.sub(r"[ \t]+", " ", md).strip()
    if len(md) > MAX_CHARS:
        md = md[:MAX_CHARS].rsplit(" ", 1)[0] + ". There is more on screen."
    return md


def to_gist(text):
    """A one-line headline for the auto-spoken cue: the first sentence or
    two, capped short. If the reply is already short, speak the whole thing."""
    if not text:
        return ""
    if len(text) <= GIST_CHARS + 40:
        return text
    gist = ""
    for s in re.split(r"(?<=[.!?])\s+", text):
        if not gist:
            gist = s
        elif len(gist) + 1 + len(s) <= GIST_CHARS:
            gist += " " + s
        else:
            break
    return gist.strip() or text[:GIST_CHARS].rsplit(" ", 1)[0]


def signature(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


# ---- arming (which sessions speak on their own) ----------------------------

def arm(sid):
    if not sid:
        return
    os.makedirs(ARMED, exist_ok=True)
    name = _session_file_name(sid)
    if not name:
        return
    open(os.path.join(ARMED, name), "w").close()


def disarm(sid):
    try:
        name = _session_file_name(sid)
        if name:
            os.remove(os.path.join(ARMED, name))
    except OSError:
        pass


def is_armed(sid):
    name = _session_file_name(sid)
    return bool(name) and os.path.exists(os.path.join(ARMED, name))


def text_for(sid):
    """The full cleaned reply a given session recorded, or ''."""
    name = _session_file_name(sid)
    if not name:
        return ""
    try:
        with open(os.path.join(SESSIONS, name + ".json")) as f:
            return json.load(f).get("text", "")
    except (OSError, ValueError):
        return ""


# ---- the registry (written by the Stop hook) -------------------------------

def session_id_for(transcript_path, payload=None):
    if payload and payload.get("session_id"):
        return payload["session_id"]
    if not transcript_path:
        return None
    return os.path.splitext(os.path.basename(transcript_path))[0]


def record_stop(payload):
    """Called by aloud_on_stop.py when a session finishes a reply.
    Returns the session id (so the hook can auto-speak an armed session)
    or None when there was nothing worth recording."""
    tp = payload.get("transcript_path") or newest_transcript()
    text = assistant_text_from_payload(payload)
    if not text and tp:
        text = last_assistant_text(tp)
    text = to_speech(text)
    if not text:
        return None
    os.makedirs(SESSIONS, exist_ok=True)
    sid = session_id_for(tp, payload)
    name = _session_file_name(sid)
    if not name:
        return None
    rec = {"text": text, "ts": time.time(), "transcript": tp, "session": sid}
    with open(os.path.join(SESSIONS, name + ".json"), "w") as f:
        json.dump(rec, f)
    tmp = LATEST + ".tmp"
    with open(tmp, "w") as f:
        f.write(sid)
    os.replace(tmp, LATEST)   # atomic pointer swap
    _prune()
    return sid


def _prune():
    try:
        files = [
            os.path.join(SESSIONS, n)
            for n in os.listdir(SESSIONS)
            if n.endswith(".json")
        ]
    except OSError:
        return
    now = time.time()
    for p in files:
        try:
            if now - os.path.getmtime(p) > MAX_AGE_SECONDS:
                os.remove(p)
        except OSError:
            pass
    files = [p for p in files if os.path.exists(p)]
    files.sort(key=os.path.getmtime, reverse=True)
    for p in files[KEEP_SESSIONS:]:
        try:
            os.remove(p)
        except OSError:
            pass
    # Drop stale "armed" markers so a closed terminal does not leak one.
    try:
        for name in os.listdir(ARMED):
            m = os.path.join(ARMED, name)
            if now - os.path.getmtime(m) > MAX_AGE_SECONDS:
                os.remove(m)
    except OSError:
        pass


# ---- picking the reply to read ---------------------------------------------

def _pointer_target(pointer):
    """(text, sig) for the session named by a pointer file, or (None, None)."""
    try:
        with open(pointer) as f:
            sid = f.read().strip()
        text = text_for(sid)
        if text:
            return text, signature(text)
    except OSError:
        pass
    return None, None


def note_spoken(sid):
    """Record that this session's voice is the one now playing, so the
    full-reply hotkey reads THIS session, not whatever finished last in
    some other tab. Written by the daemon when it actually speaks."""
    if not sid:
        return
    os.makedirs(SESSIONS, exist_ok=True)
    tmp = SPOKEN + ".tmp"
    with open(tmp, "w") as f:
        f.write(sid)
    os.replace(tmp, SPOKEN)   # atomic pointer swap


def spoken_target():
    """(text, sig) for the FULL reply of the session you last heard.
    This is what the hotkey reads. Falls back to the newest reply only
    when nothing has spoken yet (e.g. no session armed)."""
    text, sig = _pointer_target(SPOKEN)
    if text:
        return text, sig
    return resolve_target()


def resolve_target():
    """Return (text, signature) for the newest-finished reply of ANY
    session; fall back to the newest transcript on disk. Used only as the
    fallback when no armed session has spoken yet."""
    text, sig = _pointer_target(LATEST)
    if text:
        return text, sig
    tp = newest_transcript()
    if not tp:
        return "", ""
    text = to_speech(last_assistant_text(tp))
    return text, signature(text)


# ---- cold speak (CLI fallback, no daemon) ----------------------------------

def speak(text):
    if not text:
        return
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    pipeline = KPipeline(lang_code="a")
    chunks = [audio for _, _, audio in pipeline(text, voice=VOICE, speed=SPEED)]
    if not chunks:
        return
    sf.write(WAV_OUT, np.concatenate(chunks), SAMPLE_RATE)
    subprocess.run(["afplay", WAV_OUT])


if __name__ == "__main__":
    body, _ = resolve_target()
    if "--print" in sys.argv:
        print(body)
    else:
        speak(body)
