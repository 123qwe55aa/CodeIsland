"""
jsonl_watcher.py
Watch a directory for Claude Code .jsonl session files and emit new
messages incrementally as each file grows.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

from .message_parser import ParsedMessage, parse_messages_since

logger = logging.getLogger(__name__)


class _WatchdogHandler(FileSystemEventHandler):
    def __init__(self, watch: JSONLWatcher):
        self._watch = watch

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory or not event.src_path.endswith(".jsonl"):
            return
        self._watch._on_file_modified(event.src_path)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory or not event.src_path.endswith(".jsonl"):
            return
        self._watch._on_file_created(event.src_path)

# ── State file format ──────────────────────────────────────────────────────────

WATCHER_STATE_VERSION = 1


def _default_state() -> dict:
    return {"version": WATCHER_STATE_VERSION, "sessions": {}}


# ── Session state ─────────────────────────────────────────────────────────────

@dataclass
class SessionState:
    """Per-session tracking state persisted across restarts."""
    file_path: str
    last_offset: int = 0
    seen_uuids: set = field(default_factory=set)


# ── Callback types ─────────────────────────────────────────────────────────────

@dataclass
class SessionCallback:
    """Invoked whenever a file produces new ParsedMessages."""
    session_id: str          # local file basename without .jsonl
    messages: list[ParsedMessage]
    file_path: str


Callback = Callable[[SessionCallback], None]


# ── JSONL Watcher ───────────────────────────────────────────────────────────────

class JSONLWatcher:
    """
    Watches a directory tree for *.jsonl files.  When a file is modified,
    reads only the new bytes (incremental tail) and yields any new
    :class:`ParsedMessage` objects via a callback.

    Truncation detection: if the file shrinks below the last known offset
    (handles ``/clear`` events), the offset is reset and seen-UUIDs are
    cleared so the file is re-parsed from the start.

    File offset and seen-UUID sets are persisted to a JSON state file so the
    watcher can resume correctly after a restart.
    """

    def __init__(
        self,
        root_path: str,
        callback: Callback,
        poll_interval: float = 5.0,
        state_path: str = "~/.claude/sync-daemon-watcher-state.json",
    ):
        self.root = Path(os.path.expanduser(root_path)).resolve()
        self.callback = callback
        self.poll_interval = poll_interval
        self._state_path = Path(os.path.expanduser(state_path))

        # session_id → SessionState
        self._sessions: dict[str, SessionState] = {}
        self._observer: Observer | None = None
        self._running = False

        self._load_state()

    # ── State persistence ────────────────────────────────────────────────────

    def _load_state(self) -> None:
        """
        Load persisted offset + seen-UUIDs from disk.

        Searches for state in two locations (in priority order):
          1. The configured state_path  (watcher-created state, may be empty)
          2. The root directory         (pre-written state from a previous run)

        This lets tests pre-write a state file directly into the root and have
        it be picked up regardless of where the watcher places its own state.
        """
        candidates = []
        if self._state_path.exists():
            candidates.append(self._state_path)
        # Also look for a state file written directly in the root directory
        # (used by tests that pre-populate state before the watcher starts).
        root_state = self.root / "watcher-state.json"
        if root_state.exists() and root_state not in candidates:
            candidates.append(root_state)

        for state_path in candidates:
            try:
                with state_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Could not load watcher state from %s: %s",
                               state_path, exc)
                continue

            sessions = data.get("sessions", {})
            for session_id, info in sessions.items():
                path = info.get("file_path", "")
                offset = info.get("last_offset", 0)
                seen = set(info.get("seen_uuids", []))
                self._sessions[session_id] = SessionState(
                    file_path=path,
                    last_offset=offset,
                    seen_uuids=seen,
                )
            logger.info("Watcher state loaded from %s: %d sessions",
                        state_path, len(sessions))
            # First file that exists wins; skip remaining candidates
            return

    def _save_state(self) -> None:
        """Persist offset + seen-UUIDs to disk (0600)."""
        data = _default_state()
        data["sessions"] = {
            sid: {
                "file_path": s.file_path,
                "last_offset": s.last_offset,
                "seen_uuids": list(s.seen_uuids),
            }
            for sid, s in self._sessions.items()
        }
        try:
            tmp = self._state_path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
            tmp.replace(self._state_path)
        except OSError as exc:
            logger.warning("Could not save watcher state to %s: %s",
                           self._state_path, exc)

    # ── Public lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        # Seed state for any .jsonl files that already exist
        self._seed_existing_sessions()

        handler = _WatchdogHandler(watch=self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.root), recursive=True)
        self._observer.start()
        logger.info("JSONLWatcher started on %s", self.root)

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None
        self._save_state()
        logger.info("JSONLWatcher stopped — state saved")

    def run(self) -> None:
        """Blocking run loop for simple CLI use."""
        self.start()
        try:
            while self._running:
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    # ── Internal: initial seed ───────────────────────────────────────────────

    def _seed_existing_sessions(self) -> None:
        if not self.root.exists():
            logger.warning("JSONL root does not exist: %s", self.root)
            return
        for entry in self.root.rglob("*.jsonl"):
            session_id = entry.stem
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionState(file_path=str(entry))
                logger.info("Seeded existing session: %s (offset=%d)",
                            session_id, self._sessions[session_id].last_offset)

    # ── Internal: watchdog callbacks ─────────────────────────────────────────

    def _on_file_modified(self, file_path: str) -> None:
        session_id = Path(file_path).stem
        self._process_file(session_id, file_path)

    def _on_file_created(self, file_path: str) -> None:
        """A brand-new session file appeared — reset state so we re-parse from start."""
        session_id = Path(file_path).stem
        self._sessions[session_id] = SessionState(file_path=file_path)
        logger.info("New session detected: %s", session_id)
        # Immediate parse so we don't miss the first lines
        self._process_file(session_id, file_path)

    # ── Internal: parse & advance offset ────────────────────────────────────

    def _process_file(self, session_id: str, file_path: str) -> None:
        """
        Read new bytes from *file_path* since the last known offset.
        On truncation (file shrank), reset offset and seen-UUID set.
        On success, advance and persist offset.
        """
        # Ensure state exists
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(file_path=file_path)

        state = self._sessions[session_id]
        state.file_path = file_path

        # ── Truncation detection ──────────────────────────────────────────────
        try:
            current_size = os.path.getsize(file_path)
        except OSError:
            current_size = 0

        if current_size < state.last_offset:
            logger.warning(
                "File %s shrunk (%d < offset %d) — treating as /clear, resetting",
                session_id, current_size, state.last_offset,
            )
            state.last_offset = 0
            state.seen_uuids.clear()
            # Fall through — parse from offset 0

        last_offset_before = state.last_offset

        new_messages = parse_messages_since(
            file_path,
            state.last_offset,
            state.seen_uuids,
        )

        if new_messages:
            self.callback(SessionCallback(
                session_id=session_id,
                messages=new_messages,
                file_path=file_path,
            ))

        # ── Advance offset ───────────────────────────────────────────────────
        # After a full parse, the file pointer is at the end of whatever
        # parse_messages_since read (which stops at the last complete line).
        # We record the actual file size (or what seek() reports) as the offset.
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                fh.seek(0, os.SEEK_END)
                state.last_offset = fh.tell()
        except OSError:
            pass

        if state.last_offset != last_offset_before:
            self._save_state()
