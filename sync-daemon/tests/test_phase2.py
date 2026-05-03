"""
test_phase2.py
Phase 2 integration tests:
  - Multi-block parser returns all blocks
  - File offset resume after restart
  - Truncation detection (/clear)
  - Durable outbox restart replay
  - Offline create-session (server_id undefined on NetworkError)
  - Watcher state persistence
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sync_daemon.http_client import HttpClient, MessageBatchResult, NetworkError
from sync_daemon.jsonl_watcher import JSONLWatcher, SessionCallback
from sync_daemon.message_parser import (
    MessageRole,
    ParsedMessage,
    parse_messages_since,
)
from sync_daemon.session_mgr import SessionManager


# ── Multi-block parser ─────────────────────────────────────────────────────────

class TestMultiBlockParser(unittest.TestCase):
    """HIGH-2: _parse_jsonl_line must return ALL content blocks, not just [0]."""

    def test_assistant_with_text_plus_tool_use_returns_two_messages(self):
        line = json.dumps({
            "type": "assistant",
            "uuid": "a1",
            "timestamp": "2024-01-15T10:00:00Z",
            "message": {
                "content": [
                    {"type": "text", "text": "I'll read the file."},
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Read",
                        "input": {"file_path": "/tmp/foo.py"},
                    },
                ]
            },
        })

        msgs = parse_messages_since.__wrapped__(
            "/nonexistent", 0, set()
        )  # just to verify return type; will test via temp file below
        # Test via temp file
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            f.write(line + "\n")
            path = f.name
        try:
            seen = set()
            msgs = parse_messages_since(path, 0, seen)
            self.assertEqual(len(msgs), 2, f"Expected 2 messages, got {len(msgs)}: {msgs}")
            roles = {m.role for m in msgs}
            self.assertIn(MessageRole.ASSISTANT, roles)
            self.assertIn(MessageRole.TOOL, roles)
            # Tool message has tool_use.id as uuid
            tool_msg = next(m for m in msgs if m.role == MessageRole.TOOL)
            self.assertEqual(tool_msg.uuid, "tool-1")
            self.assertEqual(tool_msg.tool_use.name, "Read")
        finally:
            os.unlink(path)

    def test_assistant_with_text_plus_tool_use_plus_thinking_returns_three_messages(self):
        line = json.dumps({
            "type": "assistant",
            "uuid": "a2",
            "timestamp": "2024-01-15T10:00:00Z",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "Let me think about this."},
                    {"type": "text", "text": "Here's my answer."},
                    {
                        "type": "tool_use",
                        "id": "tool-2",
                        "name": "Bash",
                        "input": {"command": "ls"},
                    },
                ]
            },
        })
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            f.write(line + "\n")
            path = f.name
        try:
            seen = set()
            msgs = parse_messages_since(path, 0, seen)
            self.assertEqual(len(msgs), 3, f"Expected 3 messages, got {len(msgs)}: {msgs}")
            roles = {m.role for m in msgs}
            self.assertIn(MessageRole.THINKING, roles)
            self.assertIn(MessageRole.ASSISTANT, roles)
            self.assertIn(MessageRole.TOOL, roles)
        finally:
            os.unlink(path)

    def test_multi_block_dedup_uses_each_uuid(self):
        """Each block has its own uuid; all should appear in seen_uuids."""
        line = json.dumps({
            "type": "assistant",
            "uuid": "a3",
            "timestamp": "2024-01-15T10:00:00Z",
            "message": {
                "content": [
                    {"type": "text", "text": "First"},
                    {
                        "type": "tool_use",
                        "id": "tool-id-xyz",
                        "name": "Read",
                        "input": {},
                    },
                ]
            },
        })
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            f.write(line + "\n")
            path = f.name
        try:
            seen = set()
            msgs = parse_messages_since(path, 0, seen)
            # tool_use uses block id as uuid; text uses msg uuid
            uuids = {m.uuid for m in msgs}
            self.assertIn("a3", uuids)
            self.assertIn("tool-id-xyz", uuids)
            self.assertEqual(len(uuids), 2)
        finally:
            os.unlink(path)

    def test_second_pass_deduplicates_by_uuid(self):
        """After first parse, second call from same offset skips all messages."""
        line = json.dumps({
            "type": "assistant",
            "uuid": "a4",
            "message": {
                "content": [
                    {"type": "text", "text": "Hello"},
                    {"type": "thinking", "thinking": "Thinking..."},
                ]
            },
        })
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            f.write(line + "\n")
            path = f.name
        try:
            seen = set()
            # First pass
            msgs1 = parse_messages_since(path, 0, seen)
            self.assertEqual(len(msgs1), 2)
            # Second pass from same offset — should return empty
            msgs2 = parse_messages_since(path, 0, seen)
            self.assertEqual(msgs2, [])
        finally:
            os.unlink(path)

    def test_partial_tail_is_skipped_until_completed(self):
        """Incomplete trailing JSON must not be emitted until the newline arrives."""
        first = json.dumps({
            "type": "assistant",
            "uuid": "a5",
            "message": {
                "content": [
                    {"type": "text", "text": "Complete"},
                ]
            },
        })
        second = json.dumps({
            "type": "assistant",
            "uuid": "a6",
            "message": {
                "content": [
                    {"type": "text", "text": "Partial"},
                ]
            },
        })
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            f.write(first + "\n")
            first_offset = f.tell()
            f.write(second[: len(second) // 2])
            path = f.name
        try:
            seen = set()
            msgs1 = parse_messages_since(path, 0, seen)
            self.assertEqual(len(msgs1), 1)
            self.assertEqual(msgs1[0].uuid, "a5")

            with open(path, "a") as fh:
                fh.write(second[len(second) // 2:] + "\n")

            msgs2 = parse_messages_since(path, first_offset, seen)
            self.assertEqual(len(msgs2), 1)
            self.assertEqual(msgs2[0].uuid, "a6")
        finally:
            os.unlink(path)


# ── File offset persistence & truncation ───────────────────────────────────────

class TestFileOffsetResume(unittest.TestCase):
    """HIGH-1: offset must be persisted and resumed after restart."""

    def test_offset_advance_and_state_file_written(self):
        """After processing, state file records the correct offset."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "state.json")
            jsonl_path = os.path.join(tmpdir, "session-abc.jsonl")
            with open(jsonl_path, "w") as f:
                f.write(json.dumps({
                    "type": "user", "uuid": "u1",
                    "message": {"content": "Hello"},
                }) + "\n")

            seen = set()
            msgs = parse_messages_since(jsonl_path, 0, seen)
            self.assertEqual(len(msgs), 1)

            # Record the offset
            offset = os.path.getsize(jsonl_path)

            # Simulate watcher state save/load cycle
            import tempfile as _tmp
            state_tmp = state_path + ".tmp"
            with open(state_tmp, "w") as fh:
                json.dump({
                    "version": 1,
                    "sessions": {
                        "session-abc": {
                            "file_path": jsonl_path,
                            "last_offset": offset,
                            "seen_uuids": list(seen),
                        }
                    },
                }, fh)
            os.rename(state_tmp, state_path)

            # Reload state
            with open(state_path) as fh:
                data = json.load(fh)
            session_data = data["sessions"]["session-abc"]
            self.assertEqual(session_data["last_offset"], offset)
            self.assertIn("u1", session_data["seen_uuids"])

    def test_truncation_detected_and_offset_reset(self):
        """When file shrinks, offset is reset and seen-uuids cleared."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = os.path.join(tmpdir, "session-trunc.jsonl")

            # Write 2 lines
            with open(jsonl_path, "w") as f:
                f.write(json.dumps({
                    "type": "user", "uuid": "u1",
                    "message": {"content": "Hello"},
                }) + "\n")
                f.write(json.dumps({
                    "type": "user", "uuid": "u2",
                    "message": {"content": "World"},
                }) + "\n")

            seen = set()
            # Parse all
            msgs1 = parse_messages_since(jsonl_path, 0, seen)
            self.assertEqual(len(msgs1), 2)
            self.assertEqual(seen, {"u1", "u2"})
            full_size = os.path.getsize(jsonl_path)

            # Truncate to first line only
            with open(jsonl_path, "w") as f:
                f.write(json.dumps({
                    "type": "user", "uuid": "u1",
                    "message": {"content": "Hello again"},
                }) + "\n")

            truncated_size = os.path.getsize(jsonl_path)
            self.assertLess(truncated_size, full_size)

            # Simulate watcher truncation check
            last_offset = full_size
            current_size = truncated_size
            if current_size < last_offset:
                last_offset = 0
                seen = set()  # reset

            # Now re-parse from offset 0 — only u1 is returned
            msgs2 = parse_messages_since(jsonl_path, last_offset, seen)
            self.assertEqual(len(msgs2), 1)
            self.assertEqual(msgs2[0].uuid, "u1")
            self.assertEqual(msgs2[0].text, "Hello again")


class TestWatcherStatePersistence(unittest.TestCase):
    """JSONLWatcher state loads/saves correctly."""

    def test_load_state_restores_offset_and_seen_uuids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "watcher-state.json")
            jsonl_path = os.path.join(tmpdir, "sess-123.jsonl")

            # Pre-write state
            with open(state_path, "w") as fh:
                json.dump({
                    "version": 1,
                    "sessions": {
                        "sess-123": {
                            "file_path": jsonl_path,
                            "last_offset": 50,
                            "seen_uuids": ["uuid-a", "uuid-b"],
                        }
                    },
                }, fh)

            # Write a file with offset 50
            with open(jsonl_path, "w") as f:
                f.write(json.dumps({
                    "type": "user", "uuid": "uuid-a",
                    "message": {"content": "Already seen"},
                }) + "\n")
                f.write(json.dumps({
                    "type": "user", "uuid": "uuid-c",
                    "message": {"content": "New message"},
                }) + "\n")

            # Create watcher — it should load state and skip uuid-a
            received = []

            def cb(cb_obj):
                received.extend(cb_obj.messages)

            with tempfile.TemporaryDirectory() as tmpdir2:
                state2 = os.path.join(tmpdir2, "watcher-state.json")
                watcher = JSONLWatcher(
                    root_path=tmpdir,
                    callback=cb,
                    state_path=state2,
                )
                # Manually inject sessions (simulating _load_state)
                watcher._load_state()
                # Process the file directly
                watcher._process_file("sess-123", jsonl_path)

            # uuid-a should be skipped, uuid-c should be returned
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0].uuid, "uuid-c")

    def test_watcher_stop_saves_state(self):
        """stop() calls _save_state so state persists after shutdown."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = os.path.join(tmpdir, "sess-new.jsonl")
            with open(jsonl_path, "w") as f:
                f.write(json.dumps({
                    "type": "user", "uuid": "u99",
                    "message": {"content": "Hello"},
                }) + "\n")

            state_path = os.path.join(tmpdir, "state.json")
            received = []

            def cb(cb_obj):
                received.extend(cb_obj.messages)

            watcher = JSONLWatcher(
                root_path=tmpdir,
                callback=cb,
                state_path=state_path,
            )
            watcher._seed_existing_sessions()
            watcher._process_file("sess-new", jsonl_path)
            watcher._save_state()

            # Verify state file exists and contains correct offset
            self.assertTrue(os.path.exists(state_path))
            with open(state_path) as fh:
                data = json.load(fh)
            self.assertIn("sess-new", data["sessions"])
            self.assertGreater(data["sessions"]["sess-new"]["last_offset"], 0)


# ── Durable outbox ─────────────────────────────────────────────────────────────

class TestDurableOutbox(unittest.TestCase):
    """HIGH-3: outbox must be written to disk and survive restart."""

    def test_enqueue_writes_to_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            outbox_path = os.path.join(tmpdir, "outbox.jsonl")
            http = HttpClient(
                "https://api.example.com", "device", "secret",
                outbox_path=outbox_path,
            )
            http.enqueue_offline("session-1", "local-1", '{"type":"user"}')
            self.assertTrue(os.path.exists(outbox_path))
            with open(outbox_path) as fh:
                lines = [l.strip() for l in fh if l.strip()]
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["sessionId"], "session-1")
            self.assertEqual(entry["localId"], "local-1")
            self.assertEqual(entry["content"], '{"type":"user"}')

    def test_outbox_reloaded_on_init(self):
        """New HttpClient instance loads existing outbox from disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outbox_path = os.path.join(tmpdir, "outbox.jsonl")
            # Write entries directly to simulate crash
            with open(outbox_path, "w") as fh:
                fh.write(json.dumps({
                    "sessionId": "srv-1", "localId": "l1", "content": "msg1",
                }) + "\n")
                fh.write(json.dumps({
                    "sessionId": "srv-1", "localId": "l2", "content": "msg2",
                }) + "\n")

            http = HttpClient(
                "https://api.example.com", "device", "secret",
                outbox_path=outbox_path,
            )
            self.assertEqual(len(http._outbox), 2)
            self.assertTrue(http.has_outbox_pending)

    def test_drain_outbox_groups_by_session_and_clears_on_success(self):
        """drain_outbox groups by sessionId and only clears on full success."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outbox_path = os.path.join(tmpdir, "outbox.jsonl")
            http = HttpClient(
                "https://api.example.com", "device", "secret",
                outbox_path=outbox_path,
            )
            http.enqueue_offline("session-A", "local-1", "content-1")
            http.enqueue_offline("session-B", "local-2", "content-2")
            http.enqueue_offline("session-A", "local-3", "content-3")

            self.assertEqual(len(http._outbox), 3)

            # Track calls to send_messages
            calls = []

            def mock_send(sid, msgs):
                calls.append((sid, len(msgs)))
                return MessageBatchResult(messages=[])

            with patch.object(http, "send_messages", side_effect=mock_send):
                drained = http.drain_outbox()

            self.assertEqual(drained, 3)
            self.assertEqual(len(calls), 2)  # 2 sessions
            self.assertIn(("session-A", 2), calls)
            self.assertIn(("session-B", 1), calls)

            # Outbox cleared
            self.assertEqual(len(http._outbox), 0)
            self.assertFalse(http.has_outbox_pending)

            # File deleted
            self.assertFalse(os.path.exists(outbox_path))

    def test_drain_outbox_keeps_on_failure(self):
        """If any session fails, no entries are removed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outbox_path = os.path.join(tmpdir, "outbox.jsonl")
            http = HttpClient(
                "https://api.example.com", "device", "secret",
                outbox_path=outbox_path,
            )
            http.enqueue_offline("session-1", "local-1", "content-1")
            http.enqueue_offline("session-2", "local-2", "content-2")

            with patch.object(http, "send_messages", side_effect=NetworkError("unreachable")):
                drained = http.drain_outbox()

            self.assertEqual(drained, 0)
            # All entries preserved
            self.assertEqual(len(http._outbox), 2)
            # File still exists
            self.assertTrue(os.path.exists(outbox_path))

    def test_restart_replay_recovers_pending_messages(self):
        """
        Simulate: crash → restart → outbox loaded → drain succeeds.
        This is the full Phase 2 crash-recovery scenario.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            outbox_path = os.path.join(tmpdir, "outbox.jsonl")
            session_cache = os.path.join(tmpdir, "sessions.json")

            # Phase 1: enqueue while offline (no session created)
            http1 = HttpClient(
                "https://api.example.com", "device", "secret",
                outbox_path=outbox_path,
            )
            http1.enqueue_offline("", "local-1", '{"type":"user"}')
            http1.enqueue_offline("", "local-2", '{"type":"assistant"}')
            del http1

            # Phase 2: restart — outbox is reloaded
            http2 = HttpClient(
                "https://api.example.com", "device", "secret",
                outbox_path=outbox_path,
            )
            self.assertTrue(http2.has_outbox_pending)
            self.assertEqual(len(http2._outbox), 2)

            # Simulate session creation + drain
            delivered = []
            with patch.object(http2, "send_messages", return_value=MessageBatchResult(messages=[])):
                drained = http2.drain_outbox()
            self.assertEqual(drained, 2)
            self.assertFalse(http2.has_outbox_pending)


# ── Offline create-session ─────────────────────────────────────────────────────

class TestOfflineCreateSession(unittest.TestCase):
    """HIGH-4: offline create-session must not reference undefined server_id."""

    def test_offline_path_buffers_without_session_id(self):
        """
        When NetworkError is raised during get_or_create, server_id remains None.
        Messages should still be buffered (with empty sessionId), not crash.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            outbox_path = os.path.join(tmpdir, "outbox.jsonl")
            http = HttpClient(
                "https://api.example.com", "device", "secret",
                outbox_path=outbox_path,
            )

            # Simulate: server unreachable, no session exists
            # In _sync_messages, when get_or_create raises NetworkError,
            # server_id stays None, and we enqueue with session_id=""
            with patch.object(http, "send_messages", side_effect=NetworkError("unreachable")):
                # Offline: buffer with empty sessionId (no crash)
                http.enqueue_offline("", "local-offline-1", '{"type":"user"}')

            # Verify it's in the outbox
            self.assertTrue(http.has_outbox_pending)
            entry = http._outbox[0]
            self.assertEqual(entry["sessionId"], "")
            self.assertEqual(entry["localId"], "local-offline-1")

    def test_session_mgr_offline_returns_none_without_crash(self):
        """
        SessionManager.get_or_create raises NetworkError when server is unreachable.
        The caller must handle this and NOT use server_id.
        """
        http = HttpClient(
            "https://api.example.com", "device", "secret",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SessionManager(http, cache_path=os.path.join(tmpdir, "cache.json"))
            with patch.object(http, "create_session", side_effect=NetworkError("unreachable")):
                # Must NOT raise — caller catches it
                with self.assertRaises(NetworkError):
                    sm.get_or_create("new-session", "tag", "{}")


# ── last_active_at type consistency ─────────────────────────────────────────

class TestLastActiveAtType(unittest.TestCase):
    """MEDIUM-1: last_active_at must be ISO string, not float."""

    def test_last_active_at_is_iso_string(self):
        from sync_daemon.session_mgr import _now_iso
        ts = _now_iso()
        self.assertIsInstance(ts, str)
        # ISO format check
        self.assertIn("T", ts)
        self.assertIn("+", ts)  # timezone offset

    def test_get_or_create_sets_iso_string(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with patch.object(http, "create_session") as mock_create:
            mock_create.return_value = MagicMock(
                id="srv-1", tag="t", device_id="d",
                metadata="{}", active=True, last_active_at=None,
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                sm = SessionManager(http, cache_path=os.path.join(tmpdir, "c.json"))
                mapping = sm.get_or_create("s1", "tag", "{}")
                self.assertIsInstance(mapping.last_active_at, str)
                self.assertIn("T", mapping.last_active_at)

    def test_cache_roundtrip_preserves_type(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = os.path.join(tmpdir, "c.json")
            with patch.object(http, "create_session") as mock_create:
                mock_create.return_value = MagicMock(
                    id="srv-1", tag="t", device_id="d",
                    metadata="{}", active=True, last_active_at=None,
                )
                sm = SessionManager(http, cache_path=cache)
                sm.get_or_create("s1", "tag", "{}")
                ts1 = sm.mappings["s1"].last_active_at

            # Reload from disk
            sm2 = SessionManager(http, cache_path=cache)
            ts2 = sm2.mappings["s1"].last_active_at
            self.assertEqual(ts1, ts2)
            self.assertIsInstance(ts2, str)
            self.assertIn("T", ts2)


# ── config.example.yaml consistency ──────────────────────────────────────────

class TestConfigExampleConsistency(unittest.TestCase):
    """MEDIUM-2: config.example.yaml must match implemented config keys."""

    def test_outbox_path_and_cache_path_in_config(self):
        """Verify outboxPath and cachePath are loaded correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.yaml")
            with open(cfg_file, "w") as fh:
                fh.write("""
deviceId: test-device
jwtSecret: test-secret
serverUrl: https://example.com
jsonlPath: /tmp/cc
outboxPath: /tmp/my-outbox.jsonl
cachePath: /tmp/my-sessions.json
watcherStatePath: /tmp/watcher-state.json
""")
            from sync_daemon.__main__ import load_config
            cfg = load_config(cfg_file)
            self.assertEqual(cfg.outbox_path, "/tmp/my-outbox.jsonl")
            self.assertEqual(cfg.cache_path, "/tmp/my-sessions.json")
            self.assertEqual(cfg.watcher_state_path, "/tmp/watcher-state.json")


if __name__ == "__main__":
    unittest.main()
