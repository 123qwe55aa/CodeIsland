"""
test_http_client.py
Unit tests for http_client.py — verify JWT signing, auth headers,
create_session, send_messages, outbox enqueue/drain, error handling.
"""

import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import MagicMock, patch

from sync_daemon.http_client import (
    HttpClient,
    HttpError,
    NetworkError,
    ServerMessage,
    MessageBatchResult,
    SessionInfo,
    _make_jwt,
    _sign_payload,
    _b64url,
)


# ── JWT helpers ────────────────────────────────────────────────────────────────

class TestB64Url(unittest.TestCase):
    def test_basic(self):
        data = b"hello"
        result = _b64url(data)
        self.assertEqual(result, "aGVsbG8")

    def test_no_padding(self):
        data = b"abc"
        result = _b64url(data)
        self.assertNotIn("=", result)

    def test_url_safe(self):
        data = b"a/b+c=="
        result = _b64url(data)
        self.assertNotIn("+", result)
        self.assertNotIn("/", result)


class TestSignPayload(unittest.TestCase):
    def test_deterministic(self):
        sig1 = _sign_payload("payload", "secret")
        sig2 = _sign_payload("payload", "secret")
        self.assertEqual(sig1, sig2)

    def test_different_secret_different_sig(self):
        sig1 = _sign_payload("payload", "secret1")
        sig2 = _sign_payload("payload", "secret2")
        self.assertNotEqual(sig1, sig2)

    def test_valid_jwt_format(self):
        sig = _sign_payload("{}", "secret")
        parts = sig.split(".")
        self.assertEqual(len(parts), 3)


class TestMakeJwt(unittest.TestCase):
    def test_jwt_has_three_parts(self):
        token = _make_jwt("device-abc", "secret", 1000000)
        parts = token.split(".")
        self.assertEqual(len(parts), 3)

    def test_payload_contains_device_id(self):
        token = _make_jwt("my-device", "secret", 1000000)
        _, payload_b64, _ = token.split(".")
        # Add padding for base64 decoding
        payload_bytes = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload_json = json.loads(__import__("base64").urlsafe_b64decode(payload_bytes))
        self.assertEqual(payload_json["deviceId"], "my-device")
        self.assertNotIn("sub", payload_json)

    def test_expiry_is_1_hour_after_iat(self):
        token = _make_jwt("dev", "secret", 1000000)
        _, payload_b64, _ = token.split(".")
        payload_bytes = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload_json = json.loads(__import__("base64").urlsafe_b64decode(payload_bytes))
        self.assertEqual(payload_json["exp"], 1003600)


# ── HttpClient basics ──────────────────────────────────────────────────────────

class TestHttpClientDefaults(unittest.TestCase):
    def test_outbox_empty_initially(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        self.assertFalse(http.has_outbox_pending)


# ── Auth headers ───────────────────────────────────────────────────────────────

class TestAuthHeaders(unittest.TestCase):
    def test_bearer_token_present(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        headers = http._auth_headers()
        self.assertIn("Authorization", headers)
        self.assertTrue(headers["Authorization"].startswith("Bearer "))

    def test_content_type_json(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        headers = http._auth_headers()
        self.assertEqual(headers["Content-Type"], "application/json")


# ── send_messages ─────────────────────────────────────────────────────────────

class TestSendMessages(unittest.TestCase):
    def test_builds_correct_path(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with patch.object(http, "_request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {"messages": []}
            mock_req.return_value = mock_resp

            http.send_messages("server-session-123", [
                {"content": '{"id":"1","type":"user","text":"hi"}', "localId": "1"}
            ])

            mock_req.assert_called_once()
            call_args = mock_req.call_args
            self.assertEqual(call_args[0][0], "POST")
            self.assertEqual(call_args[0][1], "/v1/sessions/server-session-123/messages")

    def test_raises_http_error_on_4xx(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with patch.object(http, "_request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.ok = False
            mock_resp.status_code = 403
            mock_resp.text = "Forbidden"
            mock_req.return_value = mock_resp

            with self.assertRaises(HttpError) as ctx:
                http.send_messages("session-1", [])
            self.assertEqual(ctx.exception.status, 403)

    def test_parses_response_messages(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with patch.object(http, "_request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {
                "messages": [
                    {"id": "msg1", "seq": 10, "localId": "local1"},
                    {"id": "msg2", "seq": 11, "localId": "local2"},
                ]
            }
            mock_req.return_value = mock_resp

            result = http.send_messages("session-1", [
                {"content": "{}", "localId": "local1"},
                {"content": "{}", "localId": "local2"},
            ])

            self.assertIsInstance(result, MessageBatchResult)
            self.assertEqual(len(result.messages), 2)
            self.assertEqual(result.messages[0].seq, 10)
            self.assertEqual(result.messages[1].local_id, "local2")


# ── Outbox ────────────────────────────────────────────────────────────────────

class TestOutbox(unittest.TestCase):
    def test_enqueue_adds_to_outbox(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        self.assertFalse(http.has_outbox_pending)

        http.enqueue_offline("session-1", "local-1", '{"type":"user"}')
        self.assertTrue(http.has_outbox_pending)
        self.assertEqual(len(http._outbox), 1)
        self.assertEqual(http._outbox[0]["sessionId"], "session-1")

    def test_drain_outbox_clears_on_success(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        http.enqueue_offline("session-1", "local-1", "msg1")
        http.enqueue_offline("session-1", "local-2", "msg2")

        with patch.object(http, "send_messages") as mock_send:
            mock_send.return_value = MessageBatchResult(messages=[])
            drained = http.drain_outbox()

        self.assertEqual(drained, 2)
        self.assertEqual(len(http._outbox), 0)
        self.assertFalse(http.has_outbox_pending)

    def test_drain_outbox_keeps_on_failure(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        http.enqueue_offline("session-1", "local-1", "msg1")

        with patch.object(http, "send_messages") as mock_send:
            mock_send.side_effect = NetworkError("unreachable")
            drained = http.drain_outbox()

        self.assertEqual(drained, 0)
        self.assertEqual(len(http._outbox), 1)

    def test_drain_empty_outbox_returns_zero(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        self.assertEqual(http.drain_outbox(), 0)


# ── create_session ────────────────────────────────────────────────────────────

class TestCreateSession(unittest.TestCase):
    def test_calls_correct_endpoint(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with patch.object(http, "_request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {
                "id": "server-id-1",
                "tag": "device-session",
                "deviceId": "device",
                "metadata": '{"title":"test"}',
                "active": True,
            }
            mock_req.return_value = mock_resp

            result = http.create_session("device-session", '{"title":"test"}')

            mock_req.assert_called_once_with(
                "POST", "/v1/sessions",
                json={"tag": "device-session", "metadata": '{"title":"test"}'},
            )
            self.assertEqual(result.id, "server-id-1")

    def test_raises_http_error_on_failure(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with patch.object(http, "_request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.ok = False
            mock_resp.status_code = 500
            mock_resp.text = "Internal error"
            mock_req.return_value = mock_resp

            with self.assertRaises(HttpError) as ctx:
                http.create_session("tag", "{}")
            self.assertEqual(ctx.exception.status, 500)


# ── patch_session_metadata ─────────────────────────────────────────────────────

class TestPatchSessionMetadata(unittest.TestCase):
    def test_correct_path_and_body(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with patch.object(http, "_request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {"version": 3}
            mock_req.return_value = mock_resp

            result = http.patch_session_metadata("srv-123", '{"title":"new"}', 2)

            mock_req.assert_called_once_with(
                "PATCH",
                "/v1/sessions/srv-123/metadata",
                json={"metadata": '{"title":"new"}', "expectedVersion": 2},
            )
            self.assertEqual(result["version"], 3)


# ── fetch_sessions ─────────────────────────────────────────────────────────────

class TestFetchSessions(unittest.TestCase):
    def test_calls_get_v1_sessions_mine(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with patch.object(http, "_request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {"sessions": []}
            mock_req.return_value = mock_resp

            result = http.fetch_sessions()

            mock_req.assert_called_once_with("GET", "/v1/sessions/mine")
            self.assertEqual(result, [])

    def test_maps_session_fields_correctly(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with patch.object(http, "_request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {
                "sessions": [
                    {
                        "id": "sess-001",
                        "tag": "dev-session",
                        "deviceId": "device",
                        "metadata": '{"path":"/projects/foo","title":"foo"}',
                        "active": True,
                        "lastActiveAt": "2026-01-01T12:00:00Z",
                    }
                ]
            }
            mock_req.return_value = mock_resp

            result = http.fetch_sessions()

            self.assertEqual(len(result), 1)
            self.assertIsInstance(result[0], SessionInfo)
            self.assertEqual(result[0].id, "sess-001")
            self.assertEqual(result[0].tag, "dev-session")
            self.assertEqual(result[0].device_id, "device")
            self.assertEqual(result[0].active, True)
            self.assertEqual(result[0].last_active_at, "2026-01-01T12:00:00Z")

    def test_skips_sessions_missing_id(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with patch.object(http, "_request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {
                "sessions": [
                    {"id": "sess-001", "tag": "a"},
                    {"tag": "no-id"},  # missing id — should be skipped
                    {"id": "sess-002", "tag": "b"},
                ]
            }
            mock_req.return_value = mock_resp

            result = http.fetch_sessions()

            self.assertEqual(len(result), 2)
            ids = [s.id for s in result]
            self.assertIn("sess-001", ids)
            self.assertIn("sess-002", ids)
            self.assertNotIn("", ids)

    def test_returns_empty_on_non_ok_response(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with patch.object(http, "_request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.ok = False
            mock_resp.status_code = 503
            mock_req.return_value = mock_resp

            result = http.fetch_sessions()

            self.assertEqual(result, [])

    def test_returns_empty_on_network_error(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with patch.object(http, "_request") as mock_req:
            mock_req.side_effect = NetworkError("connection refused")

            result = http.fetch_sessions()

            self.assertEqual(result, [])

    def test_returns_empty_when_sessions_missing_from_response(self):
        http = HttpClient("https://api.example.com", "device", "secret")
        with patch.object(http, "_request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {}  # no "sessions" key
            mock_req.return_value = mock_resp

            result = http.fetch_sessions()

            self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
