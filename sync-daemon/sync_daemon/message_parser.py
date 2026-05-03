"""
message_parser.py
Parse Claude Code JSONL session lines into structured :class:`ParsedMessage`
objects.

Supported line types (mirrors ConversationParser.swift):
  - ``user``          — user messages (text or content-array blocks)
  - ``assistant``     — assistant messages (text / tool_use / thinking blocks)
  - ``tool_result``   — tool call results (extracted from tool_result blocks)
  - ``thinking``      — extended thinking blocks embedded in assistant messages
  - ``summary``       — summarisation entry produced after compaction

System/meta messages (``<command-name>``, ``<local-command``, etc.) are
explicitly filtered out.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ── Enums ────────────────────────────────────────────────────────────────────

class MessageRole(str, Enum):
    USER      = "user"
    ASSISTANT = "assistant"
    TOOL      = "tool"
    THINKING  = "thinking"
    SUMMARY   = "summary"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ToolInput:
    """Key/value pairs of a tool invocation's input arguments."""
    name: str
    args: dict[str, str]


@dataclass
class ParsedMessage:
    """
    One parsed message extracted from a JSONL line.

    Attributes
    ----------
    uuid : str
        Unique identifier for this message.
    role : MessageRole
        Semantic role of the message.
    timestamp : datetime | None
        ISO-8601 timestamp if present in the JSONL line, else None.
    text : str | None
        Plain-text content (user text, assistant text, thinking text, summary).
    tool_use : ToolInput | None
        Tool call details if this is a tool-use block.
    tool_result : str | None
        Tool result content (truncated at 2000 chars to match Swift behaviour).
    is_error : bool
        True when a tool result was marked ``is_error``.
    is_interrupted : bool
        True when the request was interrupted by the user.
    is_meta : bool
        True when the Swift-side would mark this as a meta message.
    raw : dict
        The deserialised JSON dictionary for debugging / extension.
    """
    uuid: str = ""
    role: MessageRole = MessageRole.USER
    timestamp: datetime | None = None
    text: str | None = None
    tool_use: ToolInput | None = None
    tool_result: str | None = None
    is_error: bool = False
    is_interrupted: bool = False
    is_meta: bool = False
    raw: dict = field(default_factory=dict)

    def serialize(self) -> dict:
        """
        Mirror the JSON shape emitted by MessageRelay.swift so the server
        receives a consistent payload.
        """
        result: dict[str, Any] = {
            "id": self.uuid,
            "timestamp": (
                self.timestamp.isoformat()
                if self.timestamp
                else datetime.now(timezone.utc).isoformat()
            ),
        }

        if self.role == MessageRole.USER:
            result["type"] = "user"
            result["text"] = self.text or ""
        elif self.role == MessageRole.ASSISTANT:
            result["type"] = "assistant"
            result["text"] = self.text or ""
        elif self.role == MessageRole.TOOL:
            result["type"] = "tool"
            result["toolName"] = self.tool_use.name if self.tool_use else ""
            result["toolInput"] = self.tool_use.args if self.tool_use else {}
            if self.tool_result is not None:
                result["toolResult"] = self.tool_result
        elif self.role == MessageRole.THINKING:
            result["type"] = "thinking"
            result["text"] = self.text or ""
        elif self.role == MessageRole.SUMMARY:
            result["type"] = "summary"
            result["text"] = self.text or ""

        if self.is_interrupted:
            result["type"] = "interrupted"
            result["text"] = "[Interrupted by user]"

        return result

    def to_json(self) -> str:
        """Serialize to a JSON string (UTF-8)."""
        return json.dumps(self.serialize(), ensure_ascii=False)


# ── Helpers ───────────────────────────────────────────────────────────────────

_SYSTEM_PREFIXES = (
    "<command-name>",
    "<local-command",
    "<task-notification>",
    "<system-reminder>",
    "Caveat:",
    "[Request interrupted by user",
)


def _is_system_message(text: str) -> bool:
    return text.startswith(_SYSTEM_PREFIXES)


def _parse_timestamp(raw: dict) -> datetime | None:
    ts = raw.get("timestamp")
    if ts is None:
        return None
    try:
        # ISO-8601 with fractional seconds: 2024-01-01T12:00:00.123456Z
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _coerce_string(value: Any) -> str:
    """Coerce a JSON value to a string (int/bool → str, else str or '')."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, int) or isinstance(value, float):
        return str(value)
    return ""


def _extract_text(content: Any) -> str | None:
    """
    Pull a text string from a ``content`` field, which may be:

    - a plain ``str``
    - a ``dict`` with a ``text`` key
    - an ``list`` of blocks (Claude Code array format)
    - ``None``
    """
    if content is None:
        return None
    if isinstance(content, str):
        if not _is_system_message(content):
            return content
        return None
    if isinstance(content, dict):
        # Occasionally content is wrapped as {"text": "..."}
        return content.get("text")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = block.get("text", "")
                if text and not _is_system_message(text):
                    return text
    return None


# ── Main incremental parser ────────────────────────────────────────────────────

def parse_messages_since(
    file_path: str,
    last_offset: int,
    seen_uuids: set[str],
) -> list[ParsedMessage]:
    """
    Read *only* the new bytes from *file_path* (starting at *last_offset*)
    and return any new :class:`ParsedMessage` objects.

    Incomplete lines (files not ending in ``\\n``) are left unread —
    their offset is *not* advanced — to avoid partial parse corruption.

    If the file is shorter than *last_offset*, the file was truncated
    (e.g. after a ``/clear``) and the function returns an empty list
    so the caller can reset state and call again from offset 0.

    Parameters
    ----------
    file_path : str
        Absolute path to the ``.jsonl`` file.
    last_offset : int
        Byte offset of the last successfully parsed line.
    seen_uuids : set[str]
        UUIDs already processed; newly parsed entries are appended to this set.

    Returns
    -------
    list[ParsedMessage]
    """
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            fh.seek(last_offset)
            new_bytes = fh.read()
    except OSError as exc:
        logger.warning("Could not read %s: %s", file_path, exc)
        return []

    if not new_bytes:
        return []

    # If the trailing chunk has no final newline, it may be a partially
    # written line — skip it and re-read next time.
    if not new_bytes.endswith("\n"):
        if "\n" in new_bytes:
            # Trim to last complete line and rewind offset
            last_nl = new_bytes.rindex("\n")
            new_bytes = new_bytes[: last_nl + 1]
            # Note: offset is NOT advanced here so the incomplete tail is re-read
        else:
            return []

    messages: list[ParsedMessage] = []

    for line in new_bytes.splitlines():
        if not line.strip():
            continue
        parsed = _parse_jsonl_line(line)
        if parsed is None:
            continue
        # _parse_jsonl_line returns list[ParsedMessage] for multi-block content,
        # a single ParsedMessage for simple content, or None (handled above)
        if isinstance(parsed, list):
            items = parsed
        else:
            items = [parsed]
        for item in items:
            if item.uuid in seen_uuids:
                continue
            seen_uuids.add(item.uuid)
            messages.append(item)

    return messages


# Expose __wrapped__ so tests can access the bare function via
# parse_messages_since.__wrapped__ (pytest-functest compatibility).
parse_messages_since.__wrapped__ = parse_messages_since


def _parse_jsonl_line(line: str) -> ParsedMessage | None:
    """
    Parse a single JSONL line into a :class:`ParsedMessage`.

    Handles:
      - ``type == "user"``  /  ``"assistant"``
      - ``type == "summary"``
      - ``type == "tool_result"``  (tool-use results embedded in message.content blocks)
      - ``type == "thinking"``     (thinking blocks embedded in message.content blocks)
    """
    try:
        raw: dict = json.loads(line)
    except json.JSONDecodeError:
        logger.debug("Skipping unparseable JSONL line: %s", line[:80])
        return None

    msg_type = raw.get("type")
    is_meta = raw.get("isMeta", False)
    msg_uuid = raw.get("uuid", "")
    timestamp = _parse_timestamp(raw)

    # ── tool_result ─────────────────────────────────────────────────────────
    if msg_type == "tool_result":
        return _parse_tool_result_line(raw, msg_uuid, timestamp, is_meta)

    # ── summary ─────────────────────────────────────────────────────────────
    if msg_type == "summary":
        text = raw.get("summary", "")
        return ParsedMessage(
            uuid=msg_uuid,
            role=MessageRole.SUMMARY,
            timestamp=timestamp,
            text=text,
            is_meta=is_meta,
            raw=raw,
        )

    # ── user / assistant ────────────────────────────────────────────────────
    if msg_type not in ("user", "assistant"):
        return None

    role = MessageRole.USER if msg_type == "user" else MessageRole.ASSISTANT
    message_dict = raw.get("message", {})

    # Detect interrupted requests
    if _line_contains_interrupted(line):
        return ParsedMessage(
            uuid=msg_uuid,
            role=role,
            timestamp=timestamp,
            is_interrupted=True,
            is_meta=is_meta,
            raw=raw,
        )

    # Parse content from message.message.content
    content = message_dict.get("content")

    # Plain string content
    if isinstance(content, str):
        if _is_system_message(content):
            return None
        return ParsedMessage(
            uuid=msg_uuid,
            role=role,
            timestamp=timestamp,
            text=content,
            is_meta=is_meta,
            raw=raw,
        )

    # Array-of-blocks content (Claude Code format)
    if isinstance(content, list):
        blocks = _parse_content_blocks(content, raw, msg_uuid, role, timestamp, is_meta)
        if not blocks:
            return None
        return blocks

    return None


def _parse_content_blocks(
    blocks: list[dict],
    raw: dict,
    msg_uuid: str,
    role: MessageRole,
    timestamp: datetime | None,
    is_meta: bool,
) -> list[ParsedMessage]:
    """Parse a list of content blocks from a user or assistant message."""
    messages: list[ParsedMessage] = []

    for block in blocks:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type")

        if block_type == "text":
            text = block.get("text", "")
            if not _is_system_message(text):
                messages.append(ParsedMessage(
                    uuid=msg_uuid,
                    role=role,
                    timestamp=timestamp,
                    text=text,
                    is_meta=is_meta,
                    raw=raw,
                ))

        elif block_type == "tool_use":
            tool_id = block.get("id", "")
            tool_name = block.get("name", "")
            raw_input: dict[str, Any] = block.get("input", {})
            tool_input = ToolInput(
                name=tool_name,
                args={k: _coerce_string(v) for k, v in raw_input.items()},
            )
            messages.append(ParsedMessage(
                uuid=tool_id,           # Use the block id (tool_use_id) as the message uuid
                role=MessageRole.TOOL,
                timestamp=timestamp,
                tool_use=tool_input,
                is_meta=is_meta,
                raw=raw,
            ))

        elif block_type == "tool_result":
            # tool_result blocks are usually extracted separately;
            # handle them here too in case they appear inline.
            content = block.get("content")
            if isinstance(content, str):
                tool_id = block.get("tool_use_id", "")
                is_error = block.get("is_error", False)
                messages.append(ParsedMessage(
                    uuid=tool_id,
                    role=MessageRole.TOOL,
                    timestamp=timestamp,
                    tool_result=_truncate(content, 2000),
                    is_error=is_error,
                    is_meta=is_meta,
                    raw=raw,
                ))

        elif block_type == "thinking":
            thinking = block.get("thinking", "")
            if thinking:
                messages.append(ParsedMessage(
                    uuid=f"{msg_uuid}-thinking",  # unique suffix to avoid collision with text block
                    role=MessageRole.THINKING,
                    timestamp=timestamp,
                    text=thinking,
                    is_meta=is_meta,
                    raw=raw,
                ))

    return messages


def _parse_tool_result_line(
    raw: dict,
    msg_uuid: str,
    timestamp: datetime | None,
    is_meta: bool,
) -> ParsedMessage | None:
    """
    Parse a top-level ``type == "tool_result"`` line.

    The Swift implementation extracts results from:
      - ``toolUseResult.stdout`` / ``stderr``
      - ``toolUseResult.content`` (also surfaced as ``message.content[0].content``)
      - ``toolName`` from the top level
    """
    tool_use_result = raw.get("toolUseResult", {})
    tool_name = raw.get("toolName", "")

    # Content may be embedded in the block's content array
    message_dict = raw.get("message", {})
    content_array = message_dict.get("content", [])
    content_str: str | None = None
    is_error = False
    tool_use_id = ""

    for block in content_array:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            content_str = block.get("content")
            is_error = block.get("is_error", False)
            tool_use_id = block.get("tool_use_id", "")
            break

    stdout = tool_use_result.get("stdout") or ""
    stderr = tool_use_result.get("stderr") or ""
    raw_content = tool_use_result.get("content")

    # Use stdout if no block-level content was found
    text = content_str if content_str else (raw_content or stdout)

    is_interrupted = is_error and (
        "Interrupted by user" in (text or "") or
        "user doesn't want to proceed" in (text or "")
    )

    return ParsedMessage(
        uuid=tool_use_id or msg_uuid,
        role=MessageRole.TOOL,
        timestamp=timestamp,
        tool_result=_truncate(text, 2000) if text else None,
        is_error=is_error,
        is_interrupted=is_interrupted,
        is_meta=is_meta,
        raw=raw,
    )


def _line_contains_interrupted(line: str) -> bool:
    return "[Request interrupted by user" in line


def _truncate(text: str | None, max_len: int) -> str | None:
    """Truncate a string to *max_len* characters, appending '...' if cut."""
    if text is None:
        return None
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
