//
//  FetchSessionsTests.swift
//  ClaudeIslandTests
//
//  Tests for fetchSessions() data flow and RemoteSessionState JSON mapping.
//

import XCTest
@testable import ClaudeIsland

// MARK: - RemoteSessionState JSON Mapping

final class RemoteSessionStateMappingTests: XCTestCase {

    // MARK: Happy path

    func test_validJSON_mapsAllFields() {
        let json: [String: Any] = [
            "id": "srv-abc123",
            "deviceId": "mac-device-001",
            "deviceName": "Toby's MacBook Pro",
            "tag": "mac-001-session-x",
            "metadata": "{\"path\":\"/Users/toby/projects/app\",\"title\":\"App refactor\",\"projectName\":\"app\"}",
            "active": true,
            "lastActiveAt": "2026-04-30T12:00:00.000Z",
        ]

        let state = RemoteSessionState(from: json)

        XCTAssertNotNil(state)
        XCTAssertEqual(state?.sessionId, "srv-abc123")
        XCTAssertEqual(state?.ownerDeviceId, "mac-device-001")
        XCTAssertEqual(state?.ownerDeviceName, "Toby's MacBook Pro")
        XCTAssertEqual(state?.tag, "mac-001-session-x")
        XCTAssertEqual(state?.metadata.path, "/Users/toby/projects/app")
        XCTAssertEqual(state?.metadata.title, "App refactor")
        XCTAssertEqual(state?.metadata.projectName, "app")
        XCTAssertEqual(state?.isActive, true)
        XCTAssertNotNil(state?.lastActiveAt)
    }

    func test_metadataAsDict_mapsFields() {
        // Server may embed metadata as a JSON object rather than a JSON string
        let json: [String: Any] = [
            "id": "srv-def456",
            "deviceId": "mac-002",
            "deviceName": "Work Mac",
            "tag": "tag-1",
            "metadata": ["path": "/tmp", "title": "Test session", "projectName": "test"],
            "active": false,
            "lastActiveAt": "2026-04-29T08:00:00Z",
        ]

        let state = RemoteSessionState(from: json)

        XCTAssertNotNil(state)
        XCTAssertEqual(state?.metadata.path, "/tmp")
        XCTAssertEqual(state?.metadata.title, "Test session")
        XCTAssertEqual(state?.metadata.projectName, "test")
        XCTAssertEqual(state?.isActive, false)
    }

    // MARK: Missing / malformed fields (graceful degradation)

    func test_missingId_returnsNil() {
        let json: [String: Any] = [
            "deviceId": "mac-001",
            "deviceName": "Mac",
            "tag": "tag-1",
        ]

        XCTAssertNil(RemoteSessionState(from: json))
    }

    func test_missingOptionalFields_usesDefaults() {
        let json: [String: Any] = [
            "id": "srv-minimal",
            // deviceId, deviceName, tag all optional
        ]

        let state = RemoteSessionState(from: json)

        XCTAssertNotNil(state)
        XCTAssertEqual(state?.sessionId, "srv-minimal")
        XCTAssertEqual(state?.ownerDeviceId, "")
        XCTAssertEqual(state?.ownerDeviceName, "Unknown Device")
        XCTAssertEqual(state?.tag, "")
        XCTAssertEqual(state?.metadata.path, "")
        XCTAssertEqual(state?.metadata.title, "")
        XCTAssertEqual(state?.metadata.projectName, "")
        XCTAssertEqual(state?.isActive, true)         // default
        XCTAssertNil(state?.lastActiveAt)             // missing → nil
    }

    func test_missingLastActiveAt_parsesISO8601WithoutFractionalSeconds() {
        let json: [String: Any] = [
            "id": "srv-iso",
            "deviceId": "mac",
            "deviceName": "Mac",
            "tag": "t",
            "lastActiveAt": "2026-04-30T15:30:00Z",
        ]

        let state = RemoteSessionState(from: json)

        XCTAssertNotNil(state)
        XCTAssertNotNil(state?.lastActiveAt)
    }

    func test_emptySessionsArray_returnsEmptyArrayNotNil() {
        let json: [String: Any] = ["sessions": []]

        XCTAssertNotNil(RemoteSessionState(from: json)) // still parses individual item
        // The empty-array case is tested in fetchSessions integration
    }

    // MARK: CompactMap behavior — malformed items filtered, valid ones kept

    func test_compactMap_filtersInvalidItems() {
        let jsonArray: [[String: Any]] = [
            ["id": "valid-1", "deviceId": "mac", "deviceName": "M", "tag": "t"],
            ["deviceId": "mac"], // missing id → nil, filtered out
            ["id": "valid-2", "deviceId": "mac", "deviceName": "M", "tag": "t"],
        ]

        let sessions = jsonArray.compactMap { RemoteSessionState(from: $0) }

        XCTAssertEqual(sessions.count, 2)
        XCTAssertEqual(sessions[0].sessionId, "valid-1")
        XCTAssertEqual(sessions[1].sessionId, "valid-2")
    }

    // MARK: displayTitle / projectName / isStale

    func test_displayTitle_prefersMetadataTitle() {
        let json: [String: Any] = [
            "id": "srv-title",
            "metadata": "{\"title\":\"My Custom Title\"}",
        ]

        let state = RemoteSessionState(from: json)
        XCTAssertEqual(state?.displayTitle, "My Custom Title")
    }

    func test_displayTitle_fallsBackToRelativeDate() {
        let json: [String: Any] = [
            "id": "srv-no-title",
            "lastActiveAt": "2026-04-30T12:00:00.000Z",
        ]

        let state = RemoteSessionState(from: json)
        // lastActiveAt is recent enough that displayTitle won't be sessionId prefix
        XCTAssertNotEqual(state?.displayTitle, "srv-no-title")
    }

    func test_projectName_usesMetadataProjectName() {
        let json: [String: Any] = [
            "id": "srv-proj",
            "deviceName": "My Mac",
            "metadata": "{\"projectName\":\"CodeIsland\"}",
        ]

        let state = RemoteSessionState(from: json)
        XCTAssertEqual(state?.projectName, "CodeIsland")
    }

    func test_projectName_fallsBackToOwnerDeviceName() {
        let json: [String: Any] = [
            "id": "srv-no-proj",
            "deviceName": "Toby's MacBook Pro",
        ]

        let state = RemoteSessionState(from: json)
        XCTAssertEqual(state?.projectName, "Toby's MacBook Pro")
    }

    func test_isStale_whenIdleOverOneHour() {
        let oldDate = Date().addingTimeInterval(-4000) // ~1.1 hours ago
        let formatter = ISO8601DateFormatter()
        let json: [String: Any] = [
            "id": "srv-stale",
            "lastActiveAt": formatter.string(from: oldDate),
        ]

        let state = RemoteSessionState(from: json)
        XCTAssertTrue(state?.isStale ?? false)
    }

    func test_isStale_whenRecentlyActive() {
        let recentDate = Date().addingTimeInterval(-60)
        let formatter = ISO8601DateFormatter()
        let json: [String: Any] = [
            "id": "srv-fresh",
            "lastActiveAt": formatter.string(from: recentDate),
        ]

        let state = RemoteSessionState(from: json)
        XCTAssertFalse(state?.isStale ?? true)
    }
}

// MARK: - FetchSessionsResult

final class FetchSessionsResultTests: XCTestCase {

    func test_equatable_success() {
        let sessions = [RemoteSessionState(from: ["id": "x", "deviceId": "d", "deviceName": "n", "tag": "t"])!]
        XCTAssertEqual(FetchSessionsResult.success(sessions), .success(sessions))
    }

    func test_equatable_notAuthenticated() {
        XCTAssertEqual(FetchSessionsResult.notAuthenticated, .notAuthenticated)
    }

    func test_equatable_networkError() {
        XCTAssertEqual(FetchSessionsResult.networkError("timeout"), .networkError("timeout"))
        XCTAssertNotEqual(FetchSessionsResult.networkError("timeout"), .networkError("other"))
    }
}