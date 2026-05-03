"""
test_session_mgr.py
Unit tests for session_mgr.py — verify cache load/save, get_or_create,
update_metadata, record_server_id.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from sync_daemon.http_client import HttpClient, SessionInfo, NetworkError
from sync_daemon.session_mgr import SessionManager, SessionMapping


class TestSessionMapping(unittest.TestCase):
    def test_defaults(self):
        m = SessionMapping(
            local_id="abc",
            server_id="xyz",
            tag="device-abc",
            metadata="{}",
        )
        self.assertEqual(m.metadata_version, 0)
        self.assertIsNone(m.last_active_at)


class TestSessionManagerCache(unittest.TestCase):
    def test_load_cache_empty_dir(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = os.path.join(tmpdir, "cache.json")
            sm = SessionManager(http, cache_path=cache)
            self.assertEqual(sm.mappings, {})

    def test_load_cache_with_entries(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = os.path.join(tmpdir, "cache.json")
            with open(cache, "w") as fh:
                json.dump({
                    "mappings": [
                        {
                            "local_id": "session-1",
                            "server_id": "srv-1",
                            "tag": "device-session-1",
                            "metadata": '{"title":"Test"}',
                            "metadata_version": 2,
                        },
                    ]
                }, fh)

            sm = SessionManager(http, cache_path=cache)
            mappings = sm.mappings
            self.assertEqual(len(mappings), 1)
            self.assertEqual(mappings["session-1"].server_id, "srv-1")
            self.assertEqual(mappings["session-1"].metadata_version, 2)

    def test_save_cache_roundtrip(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = os.path.join(tmpdir, "cache.json")
            sm = SessionManager(http, cache_path=cache)

            with patch.object(http, "create_session") as mock_create:
                mock_create.return_value = SessionInfo(
                    id="srv-new",
                    tag="device-new",
                    device_id="device",
                    metadata="{}",
                )
                sm.get_or_create("new-session", "device-new", "{}")

            # Reload from disk
            sm2 = SessionManager(http, cache_path=cache)
            self.assertIn("new-session", sm2.mappings)
            self.assertEqual(sm2.mappings["new-session"].server_id, "srv-new")


class TestSessionManagerGetOrCreate(unittest.TestCase):
    @patch.object(HttpClient, "create_session")
    def test_cached_hit_returns_without_network_call(self, mock_create):
        http = HttpClient("https://api.example.com", "device", "secret")
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = os.path.join(tmpdir, "cache.json")
            with open(cache, "w") as fh:
                json.dump({
                    "mappings": [
                        {
                            "local_id": "existing",
                            "server_id": "srv-existing",
                            "tag": "device-existing",
                            "metadata": "{}",
                        }
                    ]
                }, fh)

            sm = SessionManager(http, cache_path=cache)
            result = sm.get_or_create("existing", "device-existing", "{}")

            self.assertEqual(result.server_id, "srv-existing")
            mock_create.assert_not_called()

    @patch.object(HttpClient, "create_session")
    def test_cache_miss_creates_server_session(self, mock_create):
        http = HttpClient("https://api.example.com", "device", "secret")
        mock_create.return_value = SessionInfo(
            id="srv-new", tag="device-new", device_id="device", metadata="{}",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = os.path.join(tmpdir, "cache.json")
            sm = SessionManager(http, cache_path=cache)

            result = sm.get_or_create("new-session", "device-new", '{"title":"Test"}')

            mock_create.assert_called_once_with(
                "device-new",
                '{"title":"Test"}',
            )
            self.assertEqual(result.server_id, "srv-new")

    @patch.object(HttpClient, "create_session")
    def test_metadata_version_incremented_on_metadata_change(self, mock_create):
        http = HttpClient("https://api.example.com", "device", "secret")
        mock_create.return_value = SessionInfo(
            id="srv-1", tag="device-1", device_id="device", metadata="old",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = os.path.join(tmpdir, "cache.json")
            sm = SessionManager(http, cache_path=cache)

            mapping1 = sm.get_or_create("s1", "device-s1", '{"title":"v1"}')
            self.assertEqual(mapping1.metadata, '{"title":"v1"}')
            self.assertEqual(mapping1.metadata_version, 0)

            # Same server session, updated metadata
            mapping2 = sm.get_or_create("s1", "device-s1", '{"title":"v2"}')
            self.assertEqual(mapping2.metadata, '{"title":"v2"}')
            self.assertEqual(mapping2.metadata_version, 1)


class TestRecordServerId(unittest.TestCase):
    def test_creates_new_mapping(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = os.path.join(tmpdir, "cache.json")
            sm = SessionManager(http, cache_path=cache)
            sm.record_server_id("local-1", "srv-1")
            self.assertEqual(sm.mappings["local-1"].server_id, "srv-1")

    def test_updates_existing_mapping(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = os.path.join(tmpdir, "cache.json")
            with open(cache, "w") as fh:
                json.dump({
                    "mappings": [
                        {
                            "local_id": "local-1",
                            "server_id": "old-srv",
                            "tag": "",
                            "metadata": "{}",
                        }
                    ]
                }, fh)

            sm = SessionManager(http, cache_path=cache)
            sm.record_server_id("local-1", "new-srv")
            self.assertEqual(sm.mappings["local-1"].server_id, "new-srv")


if __name__ == "__main__":
    # Support for unittest.mock.patch when used as decorator with class method
    from unittest.mock import patch
    import sys
    # Make patch available in globals for test classes
    globals()["patch"] = patch
    unittest.main()
