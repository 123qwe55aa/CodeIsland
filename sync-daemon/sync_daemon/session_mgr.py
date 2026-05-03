"""
session_mgr.py
Manages the mapping between local JSONL session IDs and server session IDs.

Responsibilities
~~~~~~~~~~~~~~~
- Cache the local-id → server-id mapping in memory and on disk.
- Lazily create server sessions on first message for a given local session.
- Provide offline resilience: when the server is unreachable, messages are
  buffered locally and replayed when connectivity is restored.

The on-disk cache is a simple JSON file keyed by local session ID.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .http_client import HttpClient, HttpError, NetworkError, SessionInfo

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class SessionMapping:
    """Association between a local (JSONL) session and its server counterpart."""
    local_id: str           # e.g. "a1b2c3d4" (UUID from .jsonl filename)
    server_id: str          # server-assigned ID returned by POST /v1/sessions
    tag: str                # session tag used for idempotent creation
    metadata: str           # JSON metadata string
    metadata_version: int = 0
    last_active_at: Optional[str] = None


# ── Session Manager ───────────────────────────────────────────────────────────

class SessionManager:
    """
    Manages local ↔ server session mapping with persistence and retry logic.

    Thread-safety: all public methods are safe to call from multiple threads.

    Parameters
    ----------
    http : HttpClient
        Shared HTTP client (holds auth token and outbox).
    cache_path : str
        Path to the JSON cache file (default ``~/.claude/sync-daemon-sessions.json``).
    """

    def __init__(
        self,
        http: HttpClient,
        cache_path: str = "~/.claude/sync-daemon-sessions.json",
    ):
        self._http = http
        self._cache_file = Path(os.path.expanduser(cache_path))
        self._cache_file.parent.mkdir(parents=True, exist_ok=True)

        # local_id → SessionMapping
        self._mappings: dict[str, SessionMapping] = {}
        self._lock = threading.RLock()

        self._load_cache()

    # ── Cache persistence ──────────────────────────────────────────────────

    def _load_cache(self) -> None:
        """Load cached mappings from disk."""
        if not self._cache_file.exists():
            return
        try:
            with self._cache_file.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load session cache from %s: %s",
                           self._cache_file, exc)
            return

        for entry in data.get("mappings", []):
            if not entry.get("local_id") or not entry.get("server_id"):
                continue
            self._mappings[entry["local_id"]] = SessionMapping(
                local_id=entry["local_id"],
                server_id=entry["server_id"],
                tag=entry.get("tag", ""),
                metadata=entry.get("metadata", ""),
                metadata_version=entry.get("metadata_version", 0),
                last_active_at=entry.get("last_active_at"),
            )
        logger.info("Session cache loaded: %d entries", len(self._mappings))

    def _save_cache(self) -> None:
        """Persist mappings to disk (0600)."""
        data = {
            "mappings": [
                {
                    "local_id": m.local_id,
                    "server_id": m.server_id,
                    "tag": m.tag,
                    "metadata": m.metadata,
                    "metadata_version": m.metadata_version,
                    "last_active_at": m.last_active_at,
                }
                for m in self._mappings.values()
            ]
        }
        try:
            tmp = self._cache_file.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.chmod(tmp, 0o600)
            tmp.replace(self._cache_file)
        except OSError as exc:
            logger.warning("Could not save session cache to %s: %s",
                           self._cache_file, exc)

    # ── Public API ──────────────────────────────────────────────────────────

    def get_or_create(
        self,
        local_id: str,
        tag: str,
        metadata: str,
    ) -> SessionMapping:
        """
        Return the cached mapping for *local_id*, creating a server session
        if one does not already exist.

        Parameters
        ----------
        local_id : str
            The session basename (UUID).
        tag : str
            A stable identifier (e.g. ``{deviceId}-{localId}``).
        metadata : str
            JSON string with session metadata (path, title, projectName).

        Returns
        -------
        SessionMapping
        """
        with self._lock:
            if local_id in self._mappings:
                mapping = self._mappings[local_id]
                if mapping.metadata != metadata:
                    mapping.metadata = metadata
                    mapping.metadata_version += 1
                mapping.last_active_at = _now_iso()
                return mapping

            # Create on server
            session_info = self._http.create_session(tag, metadata)
            mapping = SessionMapping(
                local_id=local_id,
                server_id=session_info.id,
                tag=tag,
                metadata=metadata,
                metadata_version=0,
                last_active_at=_now_iso(),
            )
            self._mappings[local_id] = mapping
            self._save_cache()
            return mapping

    def update_metadata(
        self,
        local_id: str,
        metadata: str,
    ) -> bool:
        """
        Patch the server-side metadata for the session identified by *local_id*.

        Returns True on success; False if no mapping exists or a version
        conflict (409) is detected.
        """
        with self._lock:
            mapping = self._mappings.get(local_id)
            if not mapping:
                return False

            try:
                result = self._http.patch_session_metadata(
                    server_session_id=mapping.server_id,
                    metadata=metadata,
                    expected_version=mapping.metadata_version,
                )
                mapping.metadata = metadata
                mapping.metadata_version = result.get("version", mapping.metadata_version + 1)
                self._save_cache()
                return True
            except HttpError as exc:
                if exc.status == 409:
                    logger.warning("Metadata version conflict for session %s", local_id)
                else:
                    logger.warning("Could not update metadata for %s: %s", local_id, exc)
                return False
            except NetworkError as exc:
                logger.warning("Network error updating metadata for %s: %s", local_id, exc)
                return False

    def record_server_id(self, local_id: str, server_id: str) -> None:
        """
        Restore a mapping after app restart (from persisted outbox).
        The tag and metadata fields are left as empty strings until the
        next explicit create/update call.
        """
        with self._lock:
            existing = self._mappings.get(local_id)
            if existing:
                existing.server_id = server_id
            else:
                self._mappings[local_id] = SessionMapping(
                    local_id=local_id,
                    server_id=server_id,
                    tag="",
                    metadata="",
                )
            self._save_cache()
            logger.info("Restored server session mapping: %s → %s", local_id[:8], server_id[:8])

    def try_drain_outbox(self) -> int:
        """
        Attempt to replay all outbox messages via the HTTP client.

        Returns the number of messages drained (0 if nothing pending or
        network error).
        """
        return self._http.drain_outbox()

    @property
    def mappings(self) -> dict[str, SessionMapping]:
        """Read-only copy of current mappings."""
        with self._lock:
            return dict(self._mappings)
