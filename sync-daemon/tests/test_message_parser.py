"""
test_message_parser.py
Unit tests for message_parser.py — verify JSONL parsing, role detection,
tool_use extraction, system-message filtering, and serialize().
"""

import json
import os
import tempfile
import unittest
from datetime import datetime

from sync_daemon.message_parser import (
    MessageRole,
    ParsedMessage,
    ToolInput,
    _coerce_string,
    _is_system_message,
    _parse_timestamp,
    _truncate,
    parse_messages_since,
)


# ── MessageRole ────────────────────────────────────────────────────────────────

class TestMessageRole(unittest.TestCase):
    def test_values(self):
        self.assertEqual(MessageRole.USER.value, "user")
        self.assertEqual(MessageRole.ASSISTANT.value, "assistant")
        self.assertEqual(MessageRole.TOOL.value, "tool")
        self.assertEqual(MessageRole.THINKING.value, "thinking")
        self.assertEqual(MessageRole.SUMMARY.value, "summary")


# ── _is_system_message ─────────────────────────────────────────────────────────

class TestIsSystemMessage(unittest.TestCase):
    def test_command_name(self):
        self.assertTrue(_is_system_message("<command-name>/clear</command-name>"))

    def test_local_command(self):
        self.assertTrue(_is_system_message("<local-command>"))

    def test_task_notification(self):
        self.assertTrue(_is_system_message("<task-notification>"))

    def test_system_reminder(self):
        self.assertTrue(_is_system_message("<system-reminder>"))

    def test_caveat(self):
        self.assertTrue(_is_system_message("Caveat: some text"))

    def test_interrupted(self):
        self.assertTrue(_is_system_message("[Request interrupted by user"))

    def test_normal_text(self):
        self.assertFalse(_is_system_message("Hello world"))
        self.assertFalse(_is_system_message("What is 2+2?"))

    def test_edge_cases(self):
        self.assertFalse(_is_system_message(""))
        self.assertFalse(_is_system_message("<command>not a system prefix"))


# ── _coerce_string ─────────────────────────────────────────────────────────────

class TestCoerceString(unittest.TestCase):
    def test_string(self):
        self.assertEqual(_coerce_string("hello"), "hello")

    def test_int(self):
        self.assertEqual(_coerce_string(42), "42")

    def test_float(self):
        self.assertEqual(_coerce_string(3.14), "3.14")

    def test_bool_true(self):
        self.assertEqual(_coerce_string(True), "true")

    def test_bool_false(self):
        self.assertEqual(_coerce_string(False), "false")

    def test_none(self):
        self.assertEqual(_coerce_string(None), "")

    def test_list(self):
        self.assertEqual(_coerce_string(["a", "b"]), "")


# ── _parse_timestamp ────────────────────────────────────────────────────────────

class TestParseTimestamp(unittest.TestCase):
    def test_with_z_suffix(self):
        raw = {"timestamp": "2024-01-15T10:30:00.123456Z"}
        ts = _parse_timestamp(raw)
        self.assertIsInstance(ts, datetime)
        self.assertEqual(ts.year, 2024)
        self.assertEqual(ts.month, 1)
        self.assertEqual(ts.day, 15)

    def test_with_plus_offset(self):
        raw = {"timestamp": "2024-01-15T10:30:00.123456+00:00"}
        ts = _parse_timestamp(raw)
        self.assertIsInstance(ts, datetime)

    def test_missing(self):
        raw = {}
        self.assertIsNone(_parse_timestamp(raw))

    def test_malformed(self):
        raw = {"timestamp": "not-a-date"}
        self.assertIsNone(_parse_timestamp(raw))


# ── _truncate ──────────────────────────────────────────────────────────────────

class TestTruncate(unittest.TestCase):
    def test_short_string(self):
        self.assertEqual(_truncate("hello", 10), "hello")

    def test_exact_length(self):
        self.assertEqual(_truncate("hello", 5), "hello")

    def test_long_string(self):
        text = "a" * 100
        result = _truncate(text, 10)
        self.assertEqual(result, "aaaaaaa...")
        self.assertEqual(len(result), 10)

    def test_none_input(self):
        self.assertIsNone(_truncate(None, 10))

    def test_strips_whitespace(self):
        self.assertEqual(_truncate("  hello  ", 10), "hello")


# ── parse_messages_since (uses tempfile so tests work without pytest fixtures) ─

class _TempFileMixin:
    """Creates a temp JSONL file via setUp, cleans up in tearDown."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._fd, self._path = tempfile.mkstemp(suffix=".jsonl")
        os.close(self._fd)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, content: str):
        with open(self._path, "w", encoding="utf-8") as fh:
            fh.write(content)

    def _append(self, content: str):
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(content)


class TestParseMessagesSince(_TempFileMixin, unittest.TestCase):
    def test_empty_file(self):
        self._write("")
        seen = set()
        msgs = parse_messages_since(self._path, 0, seen)
        self.assertEqual(msgs, [])

    def test_missing_file(self):
        seen = set()
        msgs = parse_messages_since("/nonexistent/file.jsonl", 0, seen)
        self.assertEqual(msgs, [])

    def test_user_message_plain_string(self):
        line = json.dumps({
            "type": "user", "uuid": "u1",
            "timestamp": "2024-01-15T10:00:00Z",
            "message": {"content": "Hello Claude"},
        })
        self._write(line + "\n")

        seen = set()
        msgs = parse_messages_since(self._path, 0, seen)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].uuid, "u1")
        self.assertEqual(msgs[0].role, MessageRole.USER)
        self.assertEqual(msgs[0].text, "Hello Claude")

    def test_assistant_message_with_text_block(self):
        line = json.dumps({
            "type": "assistant", "uuid": "a1",
            "timestamp": "2024-01-15T10:00:00Z",
            "message": {"content": [{"type": "text", "text": "Here is my answer."}]},
        })
        self._write(line + "\n")

        seen = set()
        msgs = parse_messages_since(self._path, 0, seen)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].uuid, "a1")
        self.assertEqual(msgs[0].role, MessageRole.ASSISTANT)
        self.assertEqual(msgs[0].text, "Here is my answer.")

    def test_tool_use_block(self):
        line = json.dumps({
            "type": "assistant", "uuid": "a2",
            "timestamp": "2024-01-15T10:00:00Z",
            "message": {
                "content": [{
                    "type": "tool_use",
                    "id": "tool-id-123",
                    "name": "Bash",
                    "input": {"command": "ls -la"},
                }]
            },
        })
        self._write(line + "\n")

        seen = set()
        msgs = parse_messages_since(self._path, 0, seen)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].uuid, "tool-id-123")
        self.assertEqual(msgs[0].role, MessageRole.TOOL)
        self.assertIsInstance(msgs[0].tool_use, ToolInput)
        self.assertEqual(msgs[0].tool_use.name, "Bash")
        self.assertEqual(msgs[0].tool_use.args["command"], "ls -la")

    def test_thinking_block(self):
        line = json.dumps({
            "type": "assistant", "uuid": "a3",
            "timestamp": "2024-01-15T10:00:00Z",
            "message": {
                "content": [{"type": "thinking", "thinking": "Let me think about this..."}]
            },
        })
        self._write(line + "\n")

        seen = set()
        msgs = parse_messages_since(self._path, 0, seen)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].role, MessageRole.THINKING)
        self.assertEqual(msgs[0].text, "Let me think about this...")

    def test_summary_type(self):
        line = json.dumps({
            "type": "summary", "uuid": "s1",
            "timestamp": "2024-01-15T10:00:00Z",
            "summary": "This conversation covered...",
        })
        self._write(line + "\n")

        seen = set()
        msgs = parse_messages_since(self._path, 0, seen)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].role, MessageRole.SUMMARY)
        self.assertEqual(msgs[0].text, "This conversation covered...")

    def test_tool_result_type(self):
        line = json.dumps({
            "type": "tool_result", "uuid": "tr1",
            "timestamp": "2024-01-15T10:00:00Z",
            "toolName": "Bash",
            "toolUseResult": {"stdout": "file.txt\n"},
            "message": {
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "tool-use-id-1",
                    "content": "file.txt\n",
                    "is_error": False,
                }]
            },
        })
        self._write(line + "\n")

        seen = set()
        msgs = parse_messages_since(self._path, 0, seen)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].role, MessageRole.TOOL)
        self.assertEqual(msgs[0].uuid, "tool-use-id-1")
        self.assertIn("file.txt", msgs[0].tool_result or "")

    def test_system_message_filtered(self):
        line = json.dumps({
            "type": "user", "uuid": "u2",
            "message": {"content": "<command-name>/clear</command-name>"},
        })
        self._write(line + "\n")

        seen = set()
        msgs = parse_messages_since(self._path, 0, seen)
        self.assertEqual(msgs, [])

    def test_is_meta_not_filtered(self):
        line = json.dumps({
            "type": "user", "uuid": "u3", "isMeta": True,
            "message": {"content": "some meta text"},
        })
        self._write(line + "\n")

        seen = set()
        msgs = parse_messages_since(self._path, 0, seen)
        self.assertEqual(len(msgs), 1)
        self.assertTrue(msgs[0].is_meta)

    def test_incremental_tail(self):
        line1 = json.dumps({"type": "user", "uuid": "u1", "message": {"content": "First"}})
        line2 = json.dumps({"type": "user", "uuid": "u2", "message": {"content": "Second"}})
        self._write(line1 + "\n" + line2 + "\n")

        offset = len(line1) + 1
        seen = set()
        msgs = parse_messages_since(self._path, offset, seen)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].uuid, "u2")

    def test_duplicate_uuid_skipped(self):
        line = json.dumps({"type": "user", "uuid": "u1", "message": {"content": "Hello"}})
        self._write(line + "\n")

        seen = {"u1"}
        msgs = parse_messages_since(self._path, 0, seen)
        self.assertEqual(msgs, [])
        self.assertEqual(seen, {"u1"})  # unchanged

    def test_partial_line_at_end_skipped(self):
        line1 = json.dumps({"type": "user", "uuid": "u1", "message": {"content": "Hello"}})
        partial = '{"type": "user", "uuid": "u2", "message": {"content": "Incomplete'
        self._write(line1 + "\n" + partial)  # no trailing newline

        seen = set()
        msgs = parse_messages_since(self._path, 0, seen)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].uuid, "u1")

    def test_interrupted_message(self):
        line = json.dumps({
            "type": "assistant", "uuid": "a4",
            "message": {"content": "[Request interrupted by user]"},
        })
        self._write(line + "\n")

        seen = set()
        msgs = parse_messages_since(self._path, 0, seen)
        self.assertEqual(len(msgs), 1)
        self.assertTrue(msgs[0].is_interrupted)

    def test_tool_result_truncated(self):
        long_result = "x" * 3000
        line = json.dumps({
            "type": "tool_result", "uuid": "tr2",
            "toolName": "Bash",
            "toolUseResult": {"stdout": long_result},
            "message": {
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "tool-id-trunc",
                    "content": long_result,
                    "is_error": False,
                }]
            },
        })
        self._write(line + "\n")

        seen = set()
        msgs = parse_messages_since(self._path, 0, seen)
        self.assertEqual(len(msgs), 1)
        self.assertIsNotNone(msgs[0].tool_result)
        self.assertLessEqual(len(msgs[0].tool_result), 2000)
        self.assertTrue(msgs[0].tool_result.endswith("..."))

    def test_int_input_coerced_to_string(self):
        line = json.dumps({
            "type": "assistant", "uuid": "a5",
            "message": {
                "content": [{
                    "type": "tool_use", "id": "t1", "name": "Read",
                    "input": {"numLines": 50, "file_path": "/tmp/foo.py"},
                }]
            },
        })
        self._write(line + "\n")

        seen = set()
        msgs = parse_messages_since(self._path, 0, seen)
        self.assertEqual(msgs[0].tool_use.args["numLines"], "50")
        self.assertEqual(msgs[0].tool_use.args["file_path"], "/tmp/foo.py")


# ── ParsedMessage.serialize ──────────────────────────────────────────────────────

class TestParsedMessageSerialize(unittest.TestCase):
    def test_user_serialize(self):
        msg = ParsedMessage(uuid="u1", role=MessageRole.USER, text="Hello")
        s = msg.serialize()
        self.assertEqual(s["type"], "user")
        self.assertEqual(s["text"], "Hello")
        self.assertEqual(s["id"], "u1")

    def test_assistant_serialize(self):
        msg = ParsedMessage(uuid="a1", role=MessageRole.ASSISTANT, text="Here is the answer")
        s = msg.serialize()
        self.assertEqual(s["type"], "assistant")
        self.assertEqual(s["text"], "Here is the answer")

    def test_tool_serialize(self):
        msg = ParsedMessage(
            uuid="tool-id", role=MessageRole.TOOL,
            tool_use=ToolInput(name="Bash", args={"command": "ls"}),
            tool_result="file.txt\n",
        )
        s = msg.serialize()
        self.assertEqual(s["type"], "tool")
        self.assertEqual(s["toolName"], "Bash")
        self.assertEqual(s["toolInput"]["command"], "ls")
        self.assertIn("file.txt", s["toolResult"])

    def test_thinking_serialize(self):
        msg = ParsedMessage(uuid="a1", role=MessageRole.THINKING, text="Let me think...")
        s = msg.serialize()
        self.assertEqual(s["type"], "thinking")
        self.assertEqual(s["text"], "Let me think...")

    def test_interrupted_overrides_type(self):
        msg = ParsedMessage(uuid="a1", role=MessageRole.ASSISTANT, is_interrupted=True)
        s = msg.serialize()
        self.assertEqual(s["type"], "interrupted")
        self.assertEqual(s["text"], "[Interrupted by user]")

    def test_to_json(self):
        msg = ParsedMessage(uuid="u1", role=MessageRole.USER, text="Hi")
        j = msg.to_json()
        parsed = json.loads(j)
        self.assertEqual(parsed["id"], "u1")
        self.assertEqual(parsed["type"], "user")


# ── __init__ defaults ──────────────────────────────────────────────────────────

class TestParsedMessageDefaults(unittest.TestCase):
    def test_defaults(self):
        msg = ParsedMessage()
        self.assertEqual(msg.uuid, "")
        self.assertEqual(msg.role, MessageRole.USER)
        self.assertIsNone(msg.timestamp)
        self.assertIsNone(msg.text)
        self.assertIsNone(msg.tool_use)
        self.assertIsNone(msg.tool_result)
        self.assertFalse(msg.is_error)
        self.assertFalse(msg.is_interrupted)
        self.assertFalse(msg.is_meta)
        self.assertEqual(msg.raw, {})


if __name__ == "__main__":
    unittest.main()
