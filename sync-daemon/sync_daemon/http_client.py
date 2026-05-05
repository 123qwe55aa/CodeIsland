"""
http_client.py
Lightweight HTTP client for the Mio Server REST API.

Authenticated via Ed25519 challenge-response (same as CodeIsland Mac app).
The 32-byte Ed25519 seed is stored in macOS Keychain on the Mac that runs
CodeIsland. sync-daemon reads it from the same Keychain so both use the
same deviceId.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import time
import uuid
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


class Ed25519UnavailableError(Exception):
    """Raised when Ed25519 seed cannot be loaded from Keychain."""
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


# ── Ed25519 helpers ──────────────────────────────────────────────────────────

def _b64url(data: bytes | str) -> str:
    """Standard base64 encoder (no URL-safe, no strip) — matches Swift's base64EncodedString()."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    import base64
    return base64.b64encode(data).decode("ascii")


def _load_ed25519_seed_from_keychain() -> bytes:
    """
    Read the Ed25519 seed from macOS Keychain.
    Same service/account as CodeIsland: service=com.codeisland.keys,
    account=com.codeisland.keys.ed25519-seed.v1

    Raises Ed25519UnavailableError if the seed cannot be read.
    """
    import subprocess

    result = subprocess.run(
        [
            "security", "find-generic-password",
            "-s", "com.codeisland.keys",
            "-a", "com.codeisland.keys.ed25519-seed.v1",
            "-w",
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode == 0 and result.stdout.strip():
        seed_b64 = result.stdout.strip()
        from base64 import b64decode
        return b64decode(seed_b64)

    raise Ed25519UnavailableError(
        f"Could not read Ed25519 seed from Keychain (exit {result.returncode}). "
        "Is sync-daemon running on the same Mac as CodeIsland with an unlocked Keychain?"
    )


def _load_ed25519_seed_from_file(path: str) -> bytes:
    """Load Ed25519 seed from a file (base64-encoded)."""
    from base64 import b64decode
    with open(path, "r", encoding="utf-8") as f:
        return b64decode(f.read().strip())


def load_ed25519_seed(seed_file: str | None = None) -> bytes:
    """Load Ed25519 seed from file (preferred) or Keychain."""
    if seed_file:
        expanded = os.path.expanduser(seed_file)
        if os.path.exists(expanded):
            return _load_ed25519_seed_from_file(expanded)
    try:
        return _load_ed25519_seed_from_keychain()
    except Ed25519UnavailableError:
        raise Ed25519UnavailableError(
            f"Ed25519 seed not found at {os.path.expanduser(seed_file) if seed_file else '~/.claude/sync-daemon-seed.b64'} "
            "and Keychain access failed. Place base64-encoded seed at "
            "the path specified by --ed25519-seed-file, or run on the Mac with Keychain access."
        )


def _sign_with_ed25519_seed(seed: bytes, message: bytes) -> bytes:
    """Sign a message with an Ed25519 seed using cryptography library."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    signature = private_key.sign(message)
    return signature


# ── HTTP Client ───────────────────────────────────────────────────────────────

@dataclass
class HttpClient:
    """
    Typed HTTP client for the Mio Server API.

    Uses Ed25519 challenge-response authentication (same as CodeIsland Mac app).
    The seed is loaded from macOS Keychain so both sync-daemon and CodeIsland
    share the same deviceId on the server.
    """

    base_url: str
    outbox_path: str = f"~/.claude/sync-daemon-outbox-{os.getpid()}.jsonl"
    ed25519_seed_file: str = "~/.claude/sync-daemon-seed.b64"
    timeout: float = 30.0
    retry_attempts: int = 3
    retry_delay: float = 2.0

    # Auth state — set during authenticate()
    _ed25519_seed: bytes | None = field(default=None, repr=False)
    _auth_token: str | None = None
    _device_id: str | None = None

    # In-memory working set (subset of on-disk outbox, reloaded on init)
    _outbox: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._outbox_path = Path(os.path.expanduser(self.outbox_path))
        self._outbox_file_existed_before = self._outbox_path.exists()
        self._load_outbox()
        if self._outbox:
            self._outbox_file_existed_before = True
        self._load_outbox()

    # ── Ed25519 Auth ─────────────────────────────────────────────────────────

    def authenticate(self) -> None:
        """
        Perform Ed25519 challenge-response auth with the server.
        Sets _auth_token and _device_id on success.
        Raises NetworkError or Ed25519UnavailableError on failure.
        """
        if self._auth_token is not None:
            return  # already authenticated

        # Load seed from file or Keychain
        if self._ed25519_seed is None:
            seed_path = os.path.expanduser(self.ed25519_seed_file)
            self._ed25519_seed = load_ed25519_seed(seed_path if os.path.exists(seed_path) else None)
            logger.info("Loaded Ed25519 seed from %s", seed_path if os.path.exists(seed_path) else "Keychain")

        # Generate challenge and sign it
        challenge = uuid.uuid4().hex
        challenge_bytes = challenge.encode("utf-8")
        signature = _sign_with_ed25519_seed(self._ed25519_seed, challenge_bytes)

        # Build public key from seed
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        private_key = Ed25519PrivateKey.from_private_bytes(self._ed25519_seed)
        public_key_bytes = private_key.public_key().public_bytes(
            encoding=Encoding.Raw, format=PublicFormat.Raw
        )
        public_key_b64 = _b64url(public_key_bytes)

        # Call POST /v1/auth
        body = {
            "publicKey": public_key_b64,
            "challenge": _b64url(challenge_bytes),
            "signature": _b64url(signature),
        }

        import urllib.parse
        url = f"{self.base_url}/v1/auth"
        resp = requests.post(url, json=body, timeout=self.timeout)
        if resp.status_code != 200:
            raise NetworkError(f"Auth failed: HTTP {resp.status_code} {resp.text[:200]}")

        data = resp.json()
        token = data.get("token")
        device_id = data.get("deviceId")
        if not token or not device_id:
            raise NetworkError(f"Auth response missing token or deviceId: {resp.text[:200]}")

        self._auth_token = token
        self._device_id = device_id
        logger.info("Ed25519 auth succeeded, deviceId=%s", device_id[:12])

    @property
    def device_id(self) -> str | None:
        """Current deviceId (available after authenticate())."""
        return self._device_id

    # ── Auth header ─────────────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        if self._auth_token is None:
            self.authenticate()
        return {
            "Authorization": f"Bearer {self._auth_token}",
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
        GET /v1/sessions — fetch all sessions owned by this device.

        Returns a list of SessionInfo objects. Empty list on network or HTTP error.
        """
        try:
            # Ensure authenticated first
            if self._auth_token is None:
                self.authenticate()
            resp = self._request("GET", "/v1/sessions")
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
                        if all(k in entry for k in ("sessionId", "localId", "content")):
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
        """
        if not self._outbox:
            return 0

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
                self._rewrite_outbox([])
                if self._outbox_file_existed_before:
                    self._outbox.clear()
                return 0

        self._outbox.clear()
        try:
            os.remove(self._outbox_path)
        except OSError:
            pass
        return total_delivered

    @property
    def has_outbox_pending(self) -> bool:
        """True when there are un-drained messages in the outbox."""
        if not self._outbox:
            return False
        if not self._outbox_path.exists():
            return False
        try:
            with self._outbox_path.open("r", encoding="utf-8") as fh:
                return bool(fh.read().strip())
        except OSError:
            return False