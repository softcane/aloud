from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from aloud.config import Config
from aloud.text import signature, to_speech

PRIORITY = {
    "question": 1,
    "plan": 1,
    "permission": 2,
    "blocked": 3,
    "completion": 4,
}

QUESTION_TOOLS = {"AskUserQuestion", "request_user_input"}
PLAN_TOOLS = {"ExitPlanMode"}
PERMISSION_EVENTS = {"PermissionRequest", "Elicitation", "elicitation"}
BLOCKED_EVENTS = {"StopFailure"}
COMPLETION_EVENTS = {"Stop"}
SENSITIVE_KEYS = {
    "apikey",
    "authorization",
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "accesstoken",
}

QUOTED_SECRET_RE = re.compile(
    r"(?i)([\"']?\b(?:api[_-]?key|token|password|passwd|pwd|secret|access[_-]?token)"
    r"\b[\"']?\s*[:=]\s*[\"']?)([^\"'\s,;}]+)([\"']?)"
)
COMMAND_SECRET_RE = re.compile(
    r"(?i)(--?(?:api[_-]?key|token|password|passwd|pwd|secret|access[_-]?token)"
    r"\b(?:=|\s+))([^\s,;}]+)"
)
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(authorization)\b\s*[:=]\s*(?:Bearer|Basic)?\s*[^\s,;]+"),
    re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?i)\b("
        r"api[_-]?key|token|password|passwd|pwd|secret|access[_-]?token"
        r")\b\s*[:=]\s*([^\s,;]+)"
    ),
    re.compile(r"(?i)(sk-[A-Za-z0-9_-]{8,})"),
)


@dataclass(frozen=True)
class Option:
    label: str
    description: str = ""
    recommended: bool = False


@dataclass(frozen=True)
class AttentionEvent:
    kind: str
    source: str
    session_id: str
    project: str
    speech_text: str
    full_text: str
    priority: int
    dedupe_key: str
    turn_id: str = ""
    transcript_path: str = ""
    questions: tuple[str, ...] = ()
    options: tuple[Option, ...] = ()
    requires_response: bool = True


def normalize_attention_event(
    payload: dict[str, Any],
    config: Config | None = None,
) -> AttentionEvent | None:
    config = config or Config()
    event_name = _event_name(payload)
    tool_name = _tool_name(payload)

    if _is_user_interrupt(payload):
        return None
    if event_name in PERMISSION_EVENTS or _looks_like_permission(payload):
        return _permission_event(payload)
    if tool_name in QUESTION_TOOLS:
        return _question_event(payload, tool_name)
    if tool_name in PLAN_TOOLS:
        return _plan_event(payload)
    if event_name in BLOCKED_EVENTS or _looks_blocked(payload):
        return _blocked_event(payload)

    completion_text = _completion_text(payload)
    if completion_text:
        ordinary_question = _plain_text_question(completion_text)
        if ordinary_question:
            return _plain_question_event(payload, ordinary_question)
        if event_name in COMPLETION_EVENTS or payload.get("last_assistant_message"):
            return _completion_event(payload, completion_text, config)

    notification = _notification_text(payload)
    if event_name == "Notification" and notification:
        ordinary_question = _plain_text_question(notification)
        if ordinary_question:
            return _plain_question_event(
                {**payload, "last_assistant_message": notification},
                ordinary_question,
            )
        return _blocked_event({**payload, "message": notification})

    return None


def redacted(text: str) -> str:
    cleaned = QUOTED_SECRET_RE.sub(r"\1[redacted]\3", text)
    cleaned = COMMAND_SECRET_RE.sub(r"\1[redacted]", cleaned)
    for pattern in SECRET_PATTERNS:
        cleaned = pattern.sub(_redact_match, cleaned)
    return cleaned


def summarize_completion(text: str, config: Config | None = None) -> str:
    config = config or Config()
    cleaned = to_speech(text, 0)
    sections = _section_blocks(text)
    preferred = ("outcome", "summary", "result", "primary finding", "done")
    chosen = ""
    for heading in preferred:
        if sections.get(heading):
            chosen = to_speech(sections[heading], 0)
            break
    if not chosen:
        chosen = _first_meaningful_paragraph(cleaned)

    bullets = _important_bullets(text)[:3]
    final_question = _plain_text_question(text)
    parts = [chosen] if chosen else []
    parts.extend(bullets)
    if final_question and final_question not in " ".join(parts):
        parts.append(final_question)
    summary = " ".join(part.strip() for part in parts if part.strip())
    return _limit_summary(summary, config.gist_chars)


def _question_event(payload: dict[str, Any], tool_name: str) -> AttentionEvent | None:
    source = _source(payload)
    session_id = _session_id(payload)
    if not session_id:
        return None
    project = _project(payload)
    data = _tool_data(payload)
    questions = _questions_from_tool(data)
    options = tuple(_options_from_tool(data))
    free_form = bool(data.get("allow_free_form") or data.get("free_form"))
    if not questions:
        return None
    speech = _question_speech(source, project, questions, options, free_form)
    full = "\n".join((*questions, *(_option_text(option) for option in options)))
    return _event(
        "question",
        source,
        session_id,
        project,
        speech,
        full,
        payload,
        questions=tuple(questions),
        options=options,
    )


def _plain_question_event(payload: dict[str, Any], question: str) -> AttentionEvent | None:
    source = _source(payload)
    session_id = _session_id(payload)
    if not session_id:
        return None
    project = _project(payload)
    speech = _question_speech(source, project, [question], (), False)
    return _event(
        "question",
        source,
        session_id,
        project,
        speech,
        question,
        payload,
        questions=(question,),
    )


def _plan_event(payload: dict[str, Any]) -> AttentionEvent | None:
    source = _source(payload)
    session_id = _session_id(payload)
    if not session_id:
        return None
    project = _project(payload)
    data = _tool_data(payload)
    plan = _first_text(data, "plan", "content", "text", "proposal")
    speech = _identity(source, project) + " asks for plan approval."
    if plan:
        speech += " " + redacted(to_speech(plan, 0))
    speech += " Approve or reject on screen."
    return _event("plan", source, session_id, project, speech, plan or speech, payload)


def _permission_event(payload: dict[str, Any]) -> AttentionEvent | None:
    source = _source(payload)
    session_id = _session_id(payload)
    if not session_id:
        return None
    project = _project(payload)
    data = _tool_data(payload)
    tool = _tool_name(payload) or _first_text(payload, "tool", "toolName", "name") or "a tool"
    reason = _first_text(payload, "reason", "message", "prompt") or _first_text(data, "reason")
    preview = (
        _first_text(payload, "command", "preview", "action")
        or _first_text(data, "command", "preview", "action", "query")
        or _json_preview(data)
    )
    parts = [_identity(source, project) + f" requests permission for {tool}."]
    if reason:
        parts.append(redacted(to_speech(reason, 0)))
    if preview:
        parts.append("Preview: " + redacted(to_speech(preview, 0)))
    parts.append("Approve or deny on screen.")
    speech = " ".join(parts)
    return _event("permission", source, session_id, project, speech, speech, payload)


def _blocked_event(payload: dict[str, Any]) -> AttentionEvent | None:
    source = _source(payload)
    session_id = _session_id(payload)
    if not session_id:
        return None
    project = _project(payload)
    text = (
        _first_text(payload, "error", "reason", "message", "last_assistant_message")
        or "The agent is blocked."
    )
    text = redacted(to_speech(text, 0))
    speech = _identity(source, project) + " is blocked or failed. " + text
    return _event("blocked", source, session_id, project, speech, text, payload)


def _completion_event(
    payload: dict[str, Any],
    text: str,
    config: Config,
) -> AttentionEvent | None:
    source = _source(payload)
    session_id = _session_id(payload)
    if not session_id:
        return None
    project = _project(payload)
    full = redacted(to_speech(text, 0))
    summary = redacted(summarize_completion(text, config))
    speech = _identity(source, project) + " completed. " + summary
    return _event(
        "completion",
        source,
        session_id,
        project,
        speech,
        full,
        payload,
        requires_response=False,
    )


def _event(
    kind: str,
    source: str,
    session_id: str,
    project: str,
    speech: str,
    full: str,
    payload: dict[str, Any],
    *,
    questions: tuple[str, ...] = (),
    options: tuple[Option, ...] = (),
    requires_response: bool = True,
) -> AttentionEvent:
    speech = redacted(to_speech(speech, 0))
    full = redacted(to_speech(full, 0))
    dedupe_source = {
        "kind": kind,
        "session": session_id,
        "full": full,
        "questions": questions,
        "options": [option.__dict__ for option in options],
        "turn": payload.get("turn_id") or payload.get("request_id") or "",
    }
    return AttentionEvent(
        kind=kind,
        source=source,
        session_id=session_id,
        project=project,
        speech_text=speech,
        full_text=full,
        priority=PRIORITY[kind],
        dedupe_key=signature(json.dumps(dedupe_source, sort_keys=True)),
        turn_id=str(payload.get("turn_id") or payload.get("request_id") or ""),
        transcript_path=str(payload.get("transcript_path") or ""),
        questions=questions,
        options=options,
        requires_response=requires_response,
    )


def _question_speech(
    source: str,
    project: str,
    questions: Iterable[str],
    options: tuple[Option, ...],
    free_form: bool,
) -> str:
    parts = [_identity(source, project) + " asks:"]
    parts.extend(redacted(question.strip()) for question in questions if question.strip())
    for index, option in enumerate(options, 1):
        label = option.label.strip()
        description = option.description.strip()
        option_text = f"Option {index}: {label}"
        if description:
            option_text += f". {description}"
        if option.recommended:
            option_text += ". Recommended."
        parts.append(redacted(option_text))
    if free_form:
        parts.append("Free-form answer is available.")
    return " ".join(parts)


def _questions_from_tool(data: dict[str, Any]) -> list[str]:
    questions: list[str] = []
    raw_questions = data.get("questions")
    if isinstance(raw_questions, list):
        for item in raw_questions:
            if isinstance(item, dict):
                question = _first_text(item, "question", "prompt", "text", "header")
                if question:
                    questions.append(question)
            elif isinstance(item, str) and item.strip():
                questions.append(item)
    question = _first_text(data, "question", "prompt", "text")
    if question:
        questions.insert(0, question)
    return _dedupe_text(questions)


def _options_from_tool(data: dict[str, Any]) -> list[Option]:
    options: list[Option] = []
    option_sources: list[Any] = []
    if isinstance(data.get("options"), list):
        option_sources.extend(data["options"])
    if isinstance(data.get("choices"), list):
        option_sources.extend(data["choices"])
    for question in data.get("questions", []) if isinstance(data.get("questions"), list) else []:
        if isinstance(question, dict):
            for key in ("options", "choices"):
                if isinstance(question.get(key), list):
                    option_sources.extend(question[key])

    for item in option_sources:
        if isinstance(item, str):
            options.append(Option(label=item))
            continue
        if not isinstance(item, dict):
            continue
        label = _first_text(item, "label", "title", "value", "id", "name")
        description = _first_text(item, "description", "desc", "text", "subtitle")
        recommended = bool(item.get("recommended") or item.get("isRecommended"))
        if not recommended and "(recommended)" in label.lower():
            recommended = True
        if label:
            options.append(Option(label=label, description=description, recommended=recommended))
    return _dedupe_options(options)


def _plain_text_question(text: str) -> str:
    cleaned = to_speech(text, 0)
    candidates = re.findall(r"([^.!?\n][^?\n]{3,}\?)", cleaned)
    if not candidates:
        return ""
    question = candidates[-1].strip()
    for sentence in reversed(re.split(r"(?<=[.!])\s+", question)):
        if sentence.endswith("?"):
            question = sentence.strip()
            break
    if len(question.split()) < 3:
        return ""
    return question


def _completion_text(payload: dict[str, Any]) -> str:
    text = payload.get("last_assistant_message") or payload.get("assistant_message") or ""
    if isinstance(text, str):
        return text
    return ""


def _notification_text(payload: dict[str, Any]) -> str:
    return _first_text(payload, "message", "reason", "prompt", "text")


def _source(payload: dict[str, Any]) -> str:
    raw = _first_text(payload, "source", "platform", "client")
    if raw:
        lowered = raw.lower()
        if "claude" in lowered:
            return "Claude"
        if "codex" in lowered:
            return "Codex"
        return raw.strip().title()
    if payload.get("transcript_path") and ".claude" in str(payload["transcript_path"]):
        return "Claude"
    if payload.get("transcript_path") and ".codex" in str(payload["transcript_path"]):
        return "Codex"
    return "Agent"


def _session_id(payload: dict[str, Any]) -> str:
    for key in ("session_id", "sessionId", "conversation_id", "conversationId", "thread_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    transcript = payload.get("transcript_path")
    if isinstance(transcript, str) and transcript.strip():
        return transcript.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return ""


def _project(payload: dict[str, Any]) -> str:
    for key in ("project", "project_name", "workspace", "cwd", "working_directory", "session_name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.rstrip("/").rsplit("/", 1)[-1]
    return ""


def _identity(source: str, project: str) -> str:
    return " ".join(part for part in (source, project) if part)


def _event_name(payload: dict[str, Any]) -> str:
    return _first_text(payload, "hook_event_name", "event", "event_name", "type")


def _tool_name(payload: dict[str, Any]) -> str:
    value = _first_text(payload, "tool_name", "toolName", "name")
    if value:
        return value
    for container in ("tool", "request", "payload"):
        nested = payload.get(container)
        if isinstance(nested, dict):
            value = _first_text(nested, "name", "tool_name", "toolName")
            if value:
                return value
    return ""


def _tool_data(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("tool_input", "toolInput", "arguments", "args", "input", "params", "payload"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                loaded = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(loaded, dict):
                return loaded
    request = payload.get("request")
    if isinstance(request, dict):
        for key in ("arguments", "input", "params"):
            value = request.get(key)
            if isinstance(value, dict):
                return value
    return {}


def _first_text(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return ""


def _json_preview(data: dict[str, Any]) -> str:
    if not data:
        return ""
    try:
        return json.dumps(_redacted_json_value(data), sort_keys=True)
    except TypeError:
        return ""


def _redacted_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted_items = {}
        for key, nested in value.items():
            if _is_sensitive_key(str(key)):
                redacted_items[key] = "[redacted]"
            else:
                redacted_items[key] = _redacted_json_value(nested)
        return redacted_items
    if isinstance(value, list):
        return [_redacted_json_value(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return normalized in SENSITIVE_KEYS


def _option_text(option: Option) -> str:
    text = option.label
    if option.description:
        text += " " + option.description
    if option.recommended:
        text += " Recommended."
    return text


def _dedupe_text(values: list[str]) -> list[str]:
    seen = set()
    kept = []
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        if normalized and normalized not in seen:
            kept.append(normalized)
            seen.add(normalized)
    return kept


def _dedupe_options(options: list[Option]) -> tuple[Option, ...]:
    seen = set()
    kept = []
    for option in options:
        key = (option.label, option.description, option.recommended)
        if key not in seen:
            kept.append(option)
            seen.add(key)
    return tuple(kept)


def _section_blocks(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = ""
    buffer: list[str] = []
    for line in text.splitlines():
        stripped = re.sub(r"^#+\s*", "", line.strip()).strip(":")
        if not stripped:
            continue
        normalized = stripped.lower()
        if len(stripped) <= 40 and normalized in {
            "outcome",
            "summary",
            "result",
            "primary finding",
            "done",
        }:
            if current and buffer:
                sections[current] = " ".join(buffer)
            current = normalized
            buffer = []
            continue
        if current:
            buffer.append(stripped)
    if current and buffer:
        sections[current] = " ".join(buffer)
    return sections


def _first_meaningful_paragraph(text: str) -> str:
    for paragraph in re.split(r"\n\s*\n|(?<=\.)\s{2,}", text):
        candidate = paragraph.strip()
        if candidate and candidate.lower() not in {"done", "summary", "result"}:
            return candidate
    return text.strip()


def _important_bullets(text: str) -> list[str]:
    bullets = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^[-*]\s+\S", stripped):
            bullets.append(re.sub(r"^[-*]\s+", "", stripped))
    return [to_speech(bullet, 0) for bullet in bullets if bullet.strip()]


def _limit_summary(text: str, target_chars: int) -> str:
    if not text:
        return ""
    if len(text) <= target_chars + 40:
        return text
    trimmed = text[:target_chars].rsplit(" ", 1)[0].strip()
    return trimmed.rstrip(".") + "."


def _looks_like_permission(payload: dict[str, Any]) -> bool:
    text = " ".join(
        _first_text(payload, key)
        for key in ("message", "reason", "permission", "approval")
        if _first_text(payload, key)
    ).lower()
    return any(word in text for word in ("permission", "approve", "approval", "allow"))


def _looks_blocked(payload: dict[str, Any]) -> bool:
    text = " ".join(
        _first_text(payload, key) for key in ("status", "error", "reason", "message")
    ).lower()
    return any(word in text for word in ("blocked", "failed", "failure", "error"))


def _is_user_interrupt(payload: dict[str, Any]) -> bool:
    text = " ".join(
        _first_text(payload, key) for key in ("status", "error", "reason", "message")
    ).lower()
    return "user interrupt" in text or "interrupted by user" in text or "user aborted" in text


def _redact_match(match: re.Match[str]) -> str:
    if len(match.groups()) >= 2:
        return f"{match.group(1)}=[redacted]"
    if match.group(0).lower().startswith(("bearer", "basic")):
        return match.group(0).split()[0] + " [redacted]"
    return "[redacted]"
