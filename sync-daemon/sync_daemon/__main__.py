"""
__main__.py
sync-daemon entry point.

Usage::

    python -m sync_daemon [--config config.yaml]

Environment variables (override config file)::

    SYNC_DEVICE_ID   Device UUID
    SYNC_JWT_SECRET  JWT signing secret
    SYNC_SERVER_URL  Mio Server base URL
    SYNC_JSONL_PATH  Path to ~/.claude/projects directory
    SYNC_CONFIG      Path to config.yaml (default: ./config.yaml)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .http_client import HttpClient, Ed25519UnavailableError, NetworkError
from .jsonl_watcher import JSONLWatcher, SessionCallback
from .message_parser import ParsedMessage
from .session_mgr import SessionManager

logger = logging.getLogger("sync_daemon")


# ── Logging configuration ─────────────────────────────────────────────────────

def _configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(name)-20s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    # Suppress overly verbose third-party loggers
    for name in ("watchdog", "urllib3", "requests"):
        logging.getLogger(name).setLevel(logging.WARNING)


# ── Config ───────────────────────────────────────────────────────────────────

@dataclass
class Config:
    server_url: str
    jsonl_path: str
    ed25519_seed_file: str = "~/.claude/sync-daemon-seed.b64"
    poll_interval: float = 5.0
    outbox_path: str = "~/.claude/sync-daemon-outbox.jsonl"
    cache_path: str = "~/.claude/sync-daemon-sessions.json"
    watcher_state_path: str = "~/.claude/sync-daemon-watcher-state.json"


def load_config(path: Optional[str]) -> Config:
    """Load configuration from a YAML file and/or environment variables."""
    if path is None:
        path = os.environ.get("SYNC_CONFIG", "config.yaml")

    cfg: dict = {}
    if Path(path).exists():
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if raw:
            cfg = dict(raw)

    def get(key: str, env: Optional[str] = None) -> str:
        env_key = env or key.upper()
        return os.environ.get(env_key) or cfg.get(key) or ""

    server_url = get("serverUrl", "SYNC_SERVER_URL")
    if not server_url:
        sys.exit("ERROR: serverUrl is required (set SYNC_SERVER_URL env var or in config)")

    jsonl_path = get("jsonlPath", "SYNC_JSONL_PATH") or "~/.claude/projects"

    ed25519_seed_file = get("ed25519SeedFile", "SYNC_ED25519_SEED_FILE") or "~/.claude/sync-daemon-seed.b64"

    poll_interval = float(
        os.environ.get("SYNC_POLL_INTERVAL")
        or cfg.get("pollInterval", 5.0)
    )
    outbox_path = cfg.get("outboxPath", "~/.claude/sync-daemon-outbox.jsonl")
    cache_path = cfg.get("cachePath", "~/.claude/sync-daemon-sessions.json")
    watcher_state_path = cfg.get(
        "watcherStatePath", "~/.claude/sync-daemon-watcher-state.json"
    )

    return Config(
        server_url=server_url,
        jsonl_path=jsonl_path,
        ed25519_seed_file=ed25519_seed_file,
        poll_interval=poll_interval,
        outbox_path=outbox_path,
        cache_path=cache_path,
        watcher_state_path=watcher_state_path,
    )


# ── Message formatting (mirrors MessageRelay.swift) ───────────────────────────

def format_metadata(cwd: str, title: str, project_name: str) -> str:
    """Build the JSON metadata string sent on session creation."""
    return json.dumps({
        "path": cwd,
        "title": title,
        "projectName": project_name,
    }, separators=(",", ":"))


def _extract_project_name(file_path: str) -> str:
    """Derive a project name from the session file path."""
    # Expected: ~/.claude/projects/<project-dir>/<session-id>.jsonl
    parts = Path(file_path).parts
    try:
        idx = parts.index(".claude")
        if idx + 2 < len(parts):
            return parts[idx + 2]
    except ValueError:
        pass
    return Path(file_path).parent.name or "unknown"


# ── Sync logic ────────────────────────────────────────────────────────────────

def _build_payload(msg: ParsedMessage, cwd: str) -> dict:
    """Convert a ParsedMessage into the server API payload shape."""
    payload = msg.serialize()
    # Add the session's cwd for context
    payload["_cwd"] = cwd
    return payload


def _sync_messages(
    callback: SessionCallback,
    http: HttpClient,
    session_mgr: SessionManager,
) -> None:
    """
    Called by the watcher whenever a session file produces new messages.
    Handles creation, sending, and offline buffering.

    When the server is unreachable and no server session exists yet (never
    created), messages are buffered in the durable outbox WITHOUT a sessionId.
    On reconnection the outbox drain will first create the missing session(s)
    before replaying messages.
    """
    local_id = callback.session_id
    messages = callback.messages
    cwd = Path(callback.file_path).parent.name  # fallback; real cwd is per-session

    if not messages:
        return

    # ── Attempt to get/create server session ──────────────────────────────
    server_id: str | None = None
    try:
        mapping = session_mgr.get_or_create(
            local_id=local_id,
            tag=f"{http.device_id}-{local_id}",
            metadata=format_metadata(cwd, local_id, _extract_project_name(callback.file_path)),
        )
        server_id = mapping.server_id
    except NetworkError:
        logger.warning("Server unreachable — buffering %d messages for %s",
                       len(messages), local_id[:8])

    # ── Online: send messages if we have a server_id ──────────────────────
    if server_id is not None:
        api_messages = [
            {
                "content": json.dumps(_build_payload(msg, cwd), ensure_ascii=False),
                "localId": msg.uuid,
            }
            for msg in messages
        ]

        try:
            result = http.send_messages(server_id, api_messages)
            logger.info(
                "Synced %d/%d messages for session %s",
                len(result.messages), len(messages), local_id[:8],
            )
        except NetworkError:
            logger.warning("Network error — buffering %d messages for %s",
                           len(messages), local_id[:8])
            for msg in messages:
                http.enqueue_offline(
                    session_id=server_id,
                    local_id=msg.uuid,
                    content=json.dumps(_build_payload(msg, cwd)),
                )
        except Exception as exc:
            logger.error("Unexpected error syncing messages for %s: %s", local_id[:8], exc)
        return

    # ── Offline AND no server_id (never created): buffer without sessionId ──
    # The outbox stores {sessionId, localId, content}. sessionId=None here
    # signals that the session must be created before this message can be sent.
    # On restart, outbox entries with missing/None server_id will be grouped
    # and the session will be created first.
    for msg in messages:
        http.enqueue_offline(
            session_id="",  # empty = session not yet created on server
            local_id=msg.uuid,
            content=json.dumps(_build_payload(msg, cwd)),
        )


# ── Connectivity monitor ──────────────────────────────────────────────────────

def _check_connectivity(http: HttpClient) -> bool:
    """Ping the server root to determine if it is reachable."""
    try:
        resp = http._request("GET", "/")
        # Server is reachable if it responds (even 4xx means reachable, just no route)
        return resp.status_code < 500
    except NetworkError:
        return False


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="sync-daemon — sync Claude Code sessions to Mio Server",
    )
    parser.add_argument(
        "--config", "-c",
        help="Path to config.yaml (default: ./config.yaml, env: SYNC_CONFIG)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    args = parser.parse_args()

    _configure_logging(verbose=args.verbose)

    config = load_config(args.config)

    # ── HTTP client (Ed25519 auth, seed from file or Keychain) ───────────────────
    http = HttpClient(
        base_url=config.server_url,
        outbox_path=config.outbox_path,
        ed25519_seed_file=config.ed25519_seed_file,
    )

    # ── Authenticate with Ed25519 ─────────────────────────────────────────────
    try:
        http.authenticate()
        logger.info("sync-daemon starting — server=%s deviceId=%s",
                    config.server_url, (http.device_id or "???")[:12])
    except Ed25519UnavailableError as exc:
        logger.error("Ed25519 seed not available: %s", exc)
        logger.error("sync-daemon must run on the same Mac as CodeIsland with an unlocked Keychain.")
        sys.exit(1)
    except NetworkError as exc:
        logger.warning("Could not authenticate to server: %s — will retry on first request", exc)

    # ── Session manager ───────────────────────────────────────────────────────
    session_mgr = SessionManager(http, cache_path=config.cache_path)

    # ── Connectivity check ────────────────────────────────────────────────────
    connected = _check_connectivity(http)
    if not connected:
        logger.warning(
            "Server not reachable at %s — messages will be buffered for later delivery",
            config.server_url,
        )

    # ── Outbox drain on startup ─────────────────────────────────────────────
    # Handles messages buffered before a previous crash/restart.
    if http.has_outbox_pending:
        logger.info("Draining persisted outbox on startup")
        drained = session_mgr.try_drain_outbox()
        if drained > 0:
            logger.info("Outbox drained: %d messages delivered", drained)

    # ── Watcher ───────────────────────────────────────────────────────────────
    watcher = JSONLWatcher(
        root_path=config.jsonl_path,
        poll_interval=config.poll_interval,
        state_path=config.watcher_state_path,
        callback=lambda cb: _sync_messages(cb, http, session_mgr),
    )

    # ── Run loop ─────────────────────────────────────────────────────────────
    watcher.start()
    reconnect_delay = config.poll_interval
    max_reconnect_delay = 60.0

    try:
        while True:
            # Periodically attempt to drain outbox if we were offline
            if not connected and http.has_outbox_pending:
                if _check_connectivity(http):
                    logger.info("Server connectivity restored — draining outbox")
                    drained = session_mgr.try_drain_outbox()
                    if drained > 0:
                        logger.info("Outbox drained: %d messages delivered", drained)
                    connected = True
                    reconnect_delay = config.poll_interval
                else:
                    reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
                    time.sleep(reconnect_delay)
            elif not connected:
                time.sleep(config.poll_interval)
            else:
                time.sleep(config.poll_interval)

    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        logger.info("sync-daemon stopped")


if __name__ == "__main__":
    main()
