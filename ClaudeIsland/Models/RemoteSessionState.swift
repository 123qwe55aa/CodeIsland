//
//  RemoteSessionState.swift
//  ClaudeIsland
//
//  Session state model for sessions received from CodeServer.
//  These are remote sessions displayed in the UI alongside local sessions.
//

import Foundation

/// Session state for a session received from CodeServer (remote / CodeIsland sessions).
/// Displayed in the instances list alongside local SessionState entries.
struct RemoteSessionState: Equatable, Identifiable, Sendable {
    // MARK: - Identity

    /// Server-assigned session ID (unique across all devices)
    let sessionId: String

    /// The deviceId of the owner device (Mac) that created this session
    let ownerDeviceId: String

    /// Device name of the owner (e.g. "Toby's MacBook Pro")
    let ownerDeviceName: String

    // MARK: - Content

    /// Session tag (format: "{deviceId}-{localId}")
    let tag: String

    /// Parsed metadata object from the server
    var metadata: SessionMetadata

    // MARK: - State

    /// Whether this session is currently active on the server
    let isActive: Bool

    /// Last activity timestamp (ISO8601)
    let lastActiveAt: Date?

    // MARK: - Identifiable

    var id: String { sessionId }

    // MARK: - Initialization

    init(
        sessionId: String,
        ownerDeviceId: String,
        ownerDeviceName: String,
        tag: String,
        metadata: SessionMetadata,
        isActive: Bool,
        lastActiveAt: Date?
    ) {
        self.sessionId = sessionId
        self.ownerDeviceId = ownerDeviceId
        self.ownerDeviceName = ownerDeviceName
        self.tag = tag
        self.metadata = metadata
        self.isActive = isActive
        self.lastActiveAt = lastActiveAt
    }

    /// Parse from the raw server JSON response.
    /// Returns nil if required fields are missing.
    init?(from json: [String: Any]) {
        guard let sessionId = json["id"] as? String else { return nil }

        self.sessionId = sessionId
        self.ownerDeviceId = json["deviceId"] as? String ?? ""
        self.ownerDeviceName = json["deviceName"] as? String ?? "Unknown Device"
        self.tag = json["tag"] as? String ?? ""

        // Parse metadata JSON string
        if let metadataStr = json["metadata"] as? String,
           let data = metadataStr.data(using: .utf8),
           let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            self.metadata = SessionMetadata(from: dict)
        } else {
            self.metadata = SessionMetadata(from: json["metadata"] as? [String: Any] ?? [:])
        }

        self.isActive = json["active"] as? Bool ?? true

        if let lastActiveStr = json["lastActiveAt"] as? String {
            self.lastActiveAt = Self.parseISO8601(lastActiveStr)
        } else {
            self.lastActiveAt = nil
        }
    }

    /// Parse ISO8601 timestamp with optional fractional seconds
    private static func parseISO8601(_ str: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: str) ?? {
            // Try without fractional seconds
            let fallback = ISO8601DateFormatter()
            fallback.formatOptions = [.withInternetDateTime]
            return fallback.date(from: str)
        }()
    }

    // MARK: - Convenience

    /// Display title: title from metadata, or lastActiveAt relative string, or sessionId prefix
    var displayTitle: String {
        if !metadata.title.isEmpty {
            return metadata.title
        }
        if let date = lastActiveAt {
            return RelativeDateTimeFormatter().localizedString(for: date, relativeTo: Date())
        }
        return String(sessionId.prefix(8))
    }

    /// Project name from metadata or ownerDeviceName fallback
    var projectName: String {
        metadata.projectName.isEmpty ? ownerDeviceName : metadata.projectName
    }

    /// Whether the session has been idle for a long time
    var isStale: Bool {
        guard let date = lastActiveAt else { return false }
        return Date().timeIntervalSince(date) > 3600 // > 1 hour
    }
}

// MARK: - Session Metadata

/// Parsed session metadata fields from CodeServer
struct SessionMetadata: Equatable, Sendable {
    /// Working directory path
    var path: String

    /// User-visible title or summary
    var title: String

    /// Project name
    var projectName: String

    init(path: String = "", title: String = "", projectName: String = "") {
        self.path = path
        self.title = title
        self.projectName = projectName
    }

    init(from dict: [String: Any]) {
        self.path = dict["path"] as? String ?? ""
        self.title = dict["title"] as? String ?? ""
        self.projectName = dict["projectName"] as? String ?? ""
    }
}
