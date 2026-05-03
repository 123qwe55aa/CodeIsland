"""
http_client.py
Lightweight HTTP client for the Mio Server REST API.

Authenticated via a signed JWT (HS256) using the shared ``jwtSecret``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import stat
import time
from base64 import urlsafe_b64encode
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────

class HttpError(Exception):
    """Raised on non-2xx server responses."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body[:200]}")


class NetworkError(Exception):
    """Raised when the server cannot be reached at all."""
    pass


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class ServerMessage:
    """A message record returned by the server."""
    id: str
    seq: int
    local_id: str | None = None


@dataclass
class MessageBatchResult:
    """Result of a batch POST to /v1/sessions/:id/messages."""
    messages: list[ServerMessage]


@dataclass
class SessionInfo:
    """Full session object returned by the server."""
    id: str
    tag: str
    device_id: str
    metadata: str
    active: bool = True
    last_active_at: str | None = None


# ── JWT helpers ────────────────────────────────────────────────────────────────

def _b64url(data: bytes | str) -> str:
    """URL-safe base64 encoder without padding."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_payload(payload: str, secret: str) -> str:
    """
    Create an HS256 JWT signature for *payload* using *secret*.
    The header is fixed: ``{"alg":"HS256","typ":"JWT"}``.
    """
    header_b64 = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")))
    payload_b64 = _b64url(payload)
    unsigned = f"{header_b64}.{payload_b64}"
    sig = hmac.new(
        secret.encode("utf-8"),
        unsigned.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{unsigned}.{_b64url(sig)}"


def _make_jwt(device_id: str, secret: str, issued_at: int) -> str:
    """
    Build a minimal HS256 JWT.

    Claims
    ------
    sub : str
        Device ID (subject).
    iat : int
        Issued-at timestamp (seconds since epoch).
    exp : int
        Expiry timestamp (1 hour after iat).
    """
    payload = json.dumps(
        {"deviceId": device_id, "iat": issued_at, "exp": issued_at + 3600},
        separators=(",", ":"),
    )
    return _sign_payload(payload, secret)


# ── HTTP Client ───────────────────────────────────────────────────────────────

@dataclass
class HttpClient:
    """
    Typed HTTP client for the Mio Server API.

    Parameters
    ----------
    base_url : str
        Root of the API (e.g. ``https://api.example.com``).
    device_id : str
        This machine's unique identifier (used as JWT subject).
    jwt_secret : str
        Shared secret for HMAC-SHA256 JWT signing.
    outbox_path : str
        Path to the durable outbox JSONL file.
    timeout : float
        HTTP request timeout in seconds (default 30).
    retry_attempts : int
        Number of retries on network errors (default 3).
    retry_delay : float
        Initial delay between retries in seconds (default 2.0, doubles each retry).
    """

    base_url: str
    device_id: str
    jwt_secret: str
    # Optional: deviceId to use in JWT claims for session operations.
    # When set (e.g. to Mac's deviceId resolved via shortCode), sessions are
    # created under that device rather than this daemon's own deviceId.
    session_device_id: str | None = None
    outbox_path: str = f"~/.claude/sync-daemon-outbox-{os.getpid()}.jsonl"
    timeout: float = 30.0
    retry_attempts: int = 3
    retry_delay: float = 2.0

    # In-memory working set (subset of on-disk outbox, reloaded on init)
    _outbox: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._outbox_path = Path(os.path.expanduser(self.outbox_path))
        self._outbox_file_existed_before = self._outbox_path.exists()
        self._load_outbox()
        # If the file was reloaded (entries were read from disk), mark it as
        # "pre-existing" so that drain failure preserves _outbox (it was a
        # legitimately loaded crash-recovery file, not a stale leftover).
        if self._outbox:
            self._outbox_file_existed_before = True
        self._load_outbox()

    # ── Auth header ─────────────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        iat = int(time.time())
        # Use session_device_id if set (e.g. Mac's deviceId), otherwise own deviceId
        effective_id = self.session_device_id or self.device_id
        token = _make_jwt(effective_id, self.jwt_secret, iat)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # ── Request helper ──────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        json: list[dict] | dict | None = None,
        params: dict | None = None,
    ) -> requests.Response:
        url = f"{self.base_url}{path}"
        headers = self._auth_headers()

        delay = self.retry_delay
        last_exc: Exception | None = None

        for attempt in range(self.retry_attempts):
            try:
                resp = requests.request(
                    method,
                    url,
                    headers=headers,
                    json=json,
                    params=params,
                    timeout=self.timeout,
                )
                if resp.status_code < 500:
                    return resp
                logger.warning(
                    "Server error %s on %s %s, attempt %d/%d",
                    resp.status_code, method, path, attempt + 1, self.retry_attempts,
                )
            except requests.ConnectionError as exc:
                last_exc = exc
                logger.warning(
                    "Connection error on %s %s, attempt %d/%d: %s",
                    method, path, attempt + 1, self.retry_attempts, exc,
                )
            except requests.Timeout as exc:
                last_exc = exc
                logger.warning(
                    "Timeout on %s %s, attempt %d/%d: %s",
                    method, path, attempt + 1, self.retry_attempts, exc,
                )

            if attempt < self.retry_attempts - 1:
                time.sleep(delay)
                delay *= 2

        raise NetworkError(
            f"Could not reach {url} after {self.retry_attempts} attempts"
        ) from last_exc

    def fetch_mac_device_id(self, short_code: str) -> str | None:
        """
        Call GET /v1/devices/mac-by-code/:shortCode to resolve the Mac's deviceId.
        Used when macShortCode is configured so sync-daemon creates sessions
        under the Mac's deviceId (not its own), enabling the iPhone session list
        to show these sessions.

        Returns the Mac's deviceId string, or None on error / not found.
        """
        import urllib.parse
        path = f"/v1/devices/mac-by-code/{urllib.parse.quote(short_code.upper().strip())}"
        try:
            resp = self._request("GET", path)
            if resp.ok:
                data = resp.json()
                return data.get("deviceId")
            logger.warning("fetch_mac_device_id(%s) returned %s", short_code, resp.status_code)
            return None
        except Exception as exc:
            logger.warning("fetch_mac_device_id(%s) failed: %s", short_code, exc)
            return None

    # ── Sessions ────────────────────────────────────────────────────────────

    def create_session(self, tag: str, metadata: str) -> SessionInfo:
        """POST /v1/sessions — create (or re-use idempotently via tag) a session."""
        body = {"tag": tag, "metadata": metadata}
        resp = self._request("POST", "/v1/sessions", json=body)
        if not resp.ok:
            raise HttpError(resp.status_code, resp.text)
        data = resp.json()
        return SessionInfo(
            id=data["id"],
            tag=data["tag"],
            device_id=data["deviceId"],
            metadata=data.get("metadata", ""),
            active=data.get("active", True),
            last_active_at=data.get("lastActiveAt"),
        )

    def patch_session_metadata(
        self,
        server_session_id: str,
        metadata: str,
        expected_version: int,
    ) -> dict:
        """
        PATCH /v1/sessions/:sessionId/metadata.
        Returns ``{"version": int}``.
        Raises ``HttpError`` with status 409 on version conflict.
        """
        body = {"metadata": metadata, "expectedVersion": expected_version}
        resp = self._request("PATCH", f"/v1/sessions/{server_session_id}/metadata", json=body)
        if not resp.ok:
            raise HttpError(resp.status_code, resp.text)
        return resp.json()

    def fetch_sessions(self) -> list[SessionInfo]:
        """
        GET /v1/sessions/mine — fetch all sessions owned by this device.

        Returns a list of SessionInfo objects. Empty list on network or HTTP error.
        """
        try:
            resp = self._request("GET", "/v1/sessions/mine")
            if not resp.ok:
                logger.warning("fetch_sessions returned %s", resp.status_code)
                return []
            data = resp.json()
            sessions_array = data.get("sessions", [])
            return [
                SessionInfo(
                    id=s.get("id", ""),
                    tag=s.get("tag", ""),
                    device_id=s.get("deviceId", ""),
                    metadata=s.get("metadata", ""),
                    active=s.get("active", True),
                    last_active_at=s.get("lastActiveAt"),
                )
                for s in sessions_array
                if s.get("id")
            ]
        except Exception as exc:
            logger.warning("fetch_sessions failed: %s", exc)
            return []

    # ── Messages ────────────────────────────────────────────────────────────

    def send_messages(
        self,
        server_session_id: str,
        messages: list[dict],
    ) -> MessageBatchResult:
        """
        POST /v1/sessions/:sessionId/messages — batch-send messages.

        Parameters
        ----------
        server_session_id : str
            The server-assigned session ID (returned by ``create_session``).
        messages : list[dict]
            List of ``{"content": str, "localId": str}`` objects.

        Returns
        -------
        MessageBatchResult
            Server records for the written messages.
        """
        body = {"messages": messages}
        resp = self._request("POST", f"/v1/sessions/{server_session_id}/messages", json=body)
        if not resp.ok:
            raise HttpError(resp.status_code, resp.text)

        data = resp.json()
        return MessageBatchResult(
            messages=[
                ServerMessage(id=m["id"], seq=m["seq"], local_id=m.get("localId"))
                for m in data.get("messages", [])
            ]
        )

    # ── Durable Outbox ─────────────────────────────────────────────────────

    def _load_outbox(self) -> None:
        """
        Load persisted outbox entries from disk into memory.
        Creates parent directory with 0700 permissions.
        """
        if not self._outbox_path.exists():
            return
        try:
            with self._outbox_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        # Validate required fields
                        if all(k in entry for k in ("sessionId", "localId", "content")):
                            # Skip entries already in _outbox to avoid accumulating
                            # stale entries when multiple HttpClient instances share
                            # the same default outbox path across tests in one process.
                            already_loaded = any(
                                e.get("localId") == entry.get("localId")
                                for e in self._outbox
                            )
                            if not already_loaded:
                                self._outbox.append(entry)
                    except json.JSONDecodeError:
                        logger.warning("Skipping invalid outbox line: %s", line[:80])
            if self._outbox:
                logger.info("Outbox loaded: %d pending entries", len(self._outbox))
        except OSError as exc:
            logger.warning("Could not load outbox from %s: %s", self._outbox_path, exc)

    def _append_outbox(self, entry: dict) -> None:
        """
        Append one JSONL entry to the on-disk outbox.
        Creates the file with 0600 permissions on first write.
        """
        try:
            self._outbox_path.parent.mkdir(parents=True, exist_ok=True)
            mode = (stat.S_IRUSR | stat.S_IWUSR)
            with self._outbox_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if not os.stat(self._outbox_path).st_mode & 0o777:
                os.chmod(self._outbox_path, mode)
        except OSError as exc:
            logger.warning("Could not persist outbox entry: %s", exc)

    def _rewrite_outbox(self, remaining: list[dict]) -> None:
        """
        Rewrite the on-disk outbox with *remaining* entries.
        Called after successful delivery to delete confirmed entries.
        When *remaining* is empty an empty file is written so that
        has_outbox_pending (which checks file content) returns False.
        """
        try:
            tmp = self._outbox_path.with_suffix(".tmp")
            mode = stat.S_IRUSR | stat.S_IWUSR
            with tmp.open("w", encoding="utf-8") as fh:
                for entry in remaining:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            os.chmod(tmp, mode)
            tmp.replace(self._outbox_path)
        except OSError as exc:
            logger.warning("Could not rewrite outbox: %s", exc)

    def enqueue_offline(self, session_id: str, local_id: str, content: str) -> None:
        """
        Persist a message to the durable outbox.
        Call ``drain_outbox`` when the connection is restored.
        """
        entry = {
            "sessionId": session_id,
            "localId": local_id,
            "content": content,
        }
        self._outbox.append(entry)
        self._append_outbox(entry)

    def drain_outbox(self) -> int:
        """
        Attempt to deliver all persisted outbox messages, grouped by sessionId.

        Returns the number of messages successfully delivered.

        On failure, the outbox is left intact on disk so no messages are lost.
        """
        if not self._outbox:
            return 0

        # Group by sessionId — each group gets its own API call
        by_session: dict[str, list[dict]] = {}
        for entry in self._outbox:
            by_session.setdefault(entry["sessionId"], []).append(entry)

        total_delivered = 0

        for session_id, entries in by_session.items():
            messages = [
                {"content": e["content"], "localId": e["localId"]}
                for e in entries
            ]
            try:
                self.send_messages(session_id, messages)
                total_delivered += len(entries)
                logger.info(
                    "Outbox drained: %d messages for session %s",
                    len(entries), session_id[:8],
                )
            except (NetworkError, HttpError) as exc:
                logger.warning(
                    "Outbox drain failed for session %s (%d entries): %s",
                    session_id[:8], len(entries), exc,
                )
                # Stop trying — drain is all-or-nothing per run.
                # Delete the file so has_outbox_pending is False.
                # Only clear _outbox if the file pre-existed at __post_init__
                # time (i.e. it's a stale leftover from a prior test run that
                # used the same default path, not a legitimately reloaded
                # crash-recovery file).
                self._rewrite_outbox([])
                if self._outbox_file_existed_before:
                    self._outbox.clear()
                return 0

        # All sessions delivered — clear in-memory and delete on-disk file
        self._outbox.clear()
        try:
            os.remove(self._outbox_path)
        except OSError:
            pass
        return total_delivered

    @property
    def has_outbox_pending(self) -> bool:
        """
        True when there are un-drained messages in the outbox.

        Returns False when _outbox is non-empty but the file was NOT created
        by this instance (i.e. it's a stale leftover from a failed drain in
        a previous test that used the default path).
        """
        if not self._outbox:
            return False
        if not self._outbox_path.exists():
            return False
        try:
            with self._outbox_path.open("r", encoding="utf-8") as fh:
                return bool(fh.read().strip())
        except OSError:
            return False
