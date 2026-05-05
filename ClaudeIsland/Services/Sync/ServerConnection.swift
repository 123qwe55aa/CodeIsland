//
//  ServerConnection.swift
//  ClaudeIsland
//
//  Manages the connection to a CodeLight Server.
//  Handles auth, Socket.io lifecycle, and reconnection.
//

import Combine
import Foundation
import os.log
import CodeLightCrypto
import CodeLightProtocol
import SocketIO

/// Connection state for a CodeLight Server
enum ServerConnectionState: Equatable, Sendable {
    case disconnected
    case connecting
    case authenticating
    case connected
    case error(String)
}

/// Result of a sessions fetch operation.
/// Allows callers to distinguish network/auth failures from empty results
/// without throwing, enabling UI to surface actionable error messages.
enum FetchSessionsResult: Equatable, Sendable {
    case success([RemoteSessionState])
    case notAuthenticated
    case networkError(String)
}

/// Manages connection to a single CodeLight Server instance.
@MainActor
final class ServerConnection: ObservableObject {

    static let logger = Logger(subsystem: "com.codeisland", category: "ServerConnection")

    @Published private(set) var state: ServerConnectionState = .disconnected

    private let serverUrl: String
    private let keyManager: KeyManager
    private var token: String?
    private(set) var deviceId: String?
    /// This Mac's permanent shortCode, populated by `registerDevice`. Lazy-allocated server-side.
    @Published private(set) var shortCode: String?
    private var manager: SocketManager?
    private var socket: SocketIOClient?
    private var crypto: MessageCrypto?

    /// Dedicated session for sync HTTP calls. Uses a short timeout and respects
    /// system proxy so Railway is reachable from regions that require a proxy tunnel.
    private let syncSession: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 15
        config.timeoutIntervalForResource = 45
        config.waitsForConnectivity = false
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        // Respect macOS system proxy (used by 小火箭 etc.)
        config.connectionProxyDictionary = [:]
        return URLSession(configuration: config)
    }()

    /// Called when an RPC request arrives from the phone
    var onRpcCall: ((String, String, @escaping (String) -> Void) -> Void)?

    /// Called when a user message arrives from another device (phone)
    var onUserMessage: ((String, String, String?, String?) -> Void)?  // (serverSessionId, messageText, claudeUuid, cwd)

    /// Called when an iPhone unpairs this Mac. Payload: source iPhone's deviceId.
    var onLinkRemoved: ((String) -> Void)?

    /// Called when an iPhone requests a remote session launch. Payload: (presetId, projectPath, requestedByDeviceId).
    var onSessionLaunch: ((String, String, String) -> Void)?

    var isConnected: Bool { state == .connected }

    init(serverUrl: String, keyManager: KeyManager = KeyManager(serviceName: "com.codeisland.keys")) {
        self.serverUrl = serverUrl.trimmingCharacters(in: .whitespacesAndNewlines)
        self.keyManager = keyManager
        self.token = keyManager.loadToken(forServer: serverUrl)
    }

    // MARK: - Authentication

    func authenticate() async throws {
        state = .authenticating
        print("[Sync] authenticate: starting")
        fflush(stdout)

        let _ = try keyManager.getOrCreateIdentityKey()

        let challenge = UUID().uuidString
        let challengeData = Data(challenge.utf8)
        let signature = try keyManager.sign(challengeData)
        let publicKey = try keyManager.publicKeyBase64()

        let request = AuthRequest(
            publicKey: publicKey,
            challenge: challengeData.base64EncodedString(),
            signature: signature.base64EncodedString()
        )

        guard !serverUrl.isEmpty else {
            Self.logger.warning("Cannot authenticate: empty server URL")
            state = .error("No server URL configured")
            print("[Sync] authenticate: FAIL empty serverUrl")
            fflush(stdout)
            return
        }

        guard let url = URL(string: "\(serverUrl)/v1/auth") else {
            Self.logger.warning("Cannot authenticate: invalid server URL: \(self.serverUrl)")
            state = .error("Invalid server URL")
            print("[Sync] authenticate: FAIL invalid URL: \(self.serverUrl)")
            fflush(stdout)
            return
        }
        print("[Sync] authenticate: calling \(url.absoluteString)")
        fflush(stdout)
        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = try JSONEncoder().encode(request)

        let (data, response) = try await syncSession.data(for: urlRequest)
        print("[Sync] authenticate: got response, status=\((response as? HTTPURLResponse)?.statusCode ?? -1)")
        fflush(stdout)

        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            state = .error("Auth failed")
            print("[Sync] authenticate: FAIL http error")
            fflush(stdout)
            return
        }

        let authResponse = try JSONDecoder().decode(AuthResponse.self, from: data)
        guard let ed25519Token = authResponse.token, let macDeviceId = authResponse.deviceId else {
            state = .error("No token received")
            print("[Sync] authenticate: FAIL no token in response")
            fflush(stdout)
            return
        }

        self.token = ed25519Token
        self.deviceId = macDeviceId
        try keyManager.storeToken(ed25519Token, forServer: serverUrl)
        Self.logger.info("Authenticated with /v1/auth token, deviceId=\(macDeviceId)")
        print("[Sync] authenticate: SUCCESS, token=\(ed25519Token.prefix(8))... deviceId=\(macDeviceId)")
        fflush(stdout)
    }

    // MARK: - Socket.io Connection

    func connect() {
        guard let token else {
            Self.logger.warning("Cannot connect: no auth token")
            return
        }

        state = .connecting

        guard let url = URL(string: serverUrl) else {
            Self.logger.warning("Cannot connect: invalid server URL: \(self.serverUrl, privacy: .public)")
            state = .error("Invalid server URL")
            return
        }
        // Reconnect backoff: was capped at 5s with no jitter. After a network
        // blip every Mac in the field would all hit the server in lockstep
        // every 5s — a small thundering herd. Cap at 30s + use the library's
        // built-in randomization to spread attempts.
        manager = SocketManager(socketURL: url, config: [
            .log(false),
            .path("/v1/updates"),
            .connectParams(["token": token, "clientType": "user-scoped"]),
            .reconnects(true),
            .reconnectWait(2),
            .reconnectWaitMax(30),
            .randomizationFactor(0.5),
            .forceWebsockets(true),
            .extraHeaders(["Authorization": "Bearer \(token)"]),
        ])

        socket = manager?.defaultSocket

        socket?.on(clientEvent: .connect) { [weak self] _, _ in
            Task { @MainActor in
                self?.state = .connected
                Self.logger.info("Socket connected to \(self?.serverUrl ?? "")")
            }
        }

        socket?.on(clientEvent: .disconnect) { [weak self] _, _ in
            Task { @MainActor in
                self?.state = .disconnected
                Self.logger.info("Socket disconnected")
            }
        }

        socket?.on(clientEvent: .error) { [weak self] data, _ in
            Task { @MainActor in
                let msg = (data.first as? String) ?? "Unknown error"
                self?.state = .error(msg)
                Self.logger.error("Socket error: \(msg)")
            }
        }

        // Handle RPC calls from phone
        socket?.on("rpc-call") { [weak self] data, ack in
            guard let dict = data.first as? [String: Any],
                  let method = dict["method"] as? String,
                  let params = dict["params"] as? String else { return }

            self?.onRpcCall?(method, params) { result in
                ack.with(["ok": true, "result": result] as [String: Any])
            }
        }

        // Handle messages from other devices (phone → terminal)
        socket?.on("update") { [weak self] data, _ in
            guard let dict = data.first as? [String: Any],
                  let type = dict["type"] as? String,
                  type == "new-message",
                  let sessionId = dict["sessionId"] as? String,
                  let msgDict = dict["message"] as? [String: Any],
                  let content = msgDict["content"] as? String else { return }

            // Filter out message types that originate from CodeIsland itself (assistant,
            // tool, thinking, etc.) to avoid echo loops. We keep "user" (plain text from
            // phone) and "key" (control key events from phone). Plain text with no JSON
            // envelope is also treated as user content.
            if let jsonData = content.data(using: .utf8),
               let parsed = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
               let msgType = parsed["type"] as? String {
                let phoneOriginated = Set(["user", "key", "read-screen"])
                if !phoneOriginated.contains(msgType) { return }
            }
            let sessionTag = dict["sessionTag"] as? String
            let sessionPath = dict["sessionPath"] as? String

            // Plain text = message from phone (not JSON-serialized by MessageRelay)
            Task { @MainActor in
                Self.logger.info("Received user message from phone for session \(sessionId.prefix(8))...")
                self?.onUserMessage?(sessionId, content, sessionTag, sessionPath)
            }
        }

        // iPhone unpaired this Mac → clean up local state
        socket?.on("link-removed") { [weak self] data, _ in
            guard let dict = data.first as? [String: Any],
                  let sourceDeviceId = dict["sourceDeviceId"] as? String else { return }
            Task { @MainActor in
                Self.logger.info("link-removed from iPhone \(sourceDeviceId.prefix(8), privacy: .public)")
                self?.onLinkRemoved?(sourceDeviceId)
            }
        }

        // iPhone requested a remote session launch → spawn cmux subprocess
        socket?.on("session-launch") { [weak self] data, _ in
            guard let dict = data.first as? [String: Any],
                  let presetId = dict["presetId"] as? String,
                  let projectPath = dict["projectPath"] as? String,
                  let requestedBy = dict["requestedByDeviceId"] as? String else { return }
            Task { @MainActor in
                Self.logger.info("session-launch from iPhone \(requestedBy.prefix(8), privacy: .public): preset=\(presetId, privacy: .public) path=\(projectPath, privacy: .public)")
                self?.onSessionLaunch?(presetId, projectPath, requestedBy)
            }
        }

        socket?.connect()
    }

    func disconnect() {
        socket?.disconnect()
        manager = nil
        socket = nil
        state = .disconnected
    }

    // MARK: - Sending

    /// Send a session message (encrypted content) to the server
    func sendMessage(sessionId: String, content: String, localId: String? = nil) {
        guard isConnected else { return }

        var payload: [String: Any] = ["sid": sessionId, "message": content]
        if let localId { payload["localId"] = localId }

        socket?.emitWithAck("message", payload).timingOut(after: 30) { _ in }
    }

    /// Send session-alive heartbeat
    func sendAlive(sessionId: String) {
        guard isConnected else { return }
        socket?.emit("session-alive", ["sid": sessionId] as [String: Any])
    }

    /// Send session-end
    func sendSessionEnd(sessionId: String) {
        guard isConnected else { return }
        socket?.emit("session-end", ["sid": sessionId] as [String: Any])
    }

    /// Ack successful consumption of a blob so the server can delete it immediately.
    func sendBlobConsumed(blobId: String) {
        guard isConnected else { return }
        socket?.emit("blob-consumed", ["blobId": blobId] as [String: Any])
    }

    /// Push the capability snapshot to the server so the phone can fetch it.
    func uploadCapabilities(_ snapshot: CapabilitySnapshot) async {
        guard let token else { return }
        guard let data = try? JSONEncoder().encode(snapshot) else { return }
        guard let url = URL(string: "\(serverUrl)/v1/capabilities") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = data
        _ = try? await syncSession.data(for: request)
    }

    /// Download a blob by ID. Returns (data, mime) or throws.
    func downloadBlob(blobId: String) async throws -> (Data, String) {
        guard let token else { throw URLError(.userAuthenticationRequired) }
        guard let url = URL(string: "\(serverUrl)/v1/blobs/\(blobId)") else { throw URLError(.badURL) }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await syncSession.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw NSError(domain: "CodeIsland.Blob", code: (response as? HTTPURLResponse)?.statusCode ?? -1,
                          userInfo: [NSLocalizedDescriptionKey: "Blob download failed"])
        }
        let mime = (http.value(forHTTPHeaderField: "Content-Type") ?? "image/jpeg").split(separator: ";").first.map { String($0).trimmingCharacters(in: .whitespaces) } ?? "image/jpeg"
        return (data, mime)
    }

    /// Update session metadata
    func updateMetadata(sessionId: String, metadata: String, expectedVersion: Int) {
        guard isConnected else { return }
        socket?.emitWithAck("update-metadata", [
            "sid": sessionId,
            "metadata": metadata,
            "expectedVersion": expectedVersion,
        ] as [String: Any]).timingOut(after: 10) { _ in }
    }

    /// Register as RPC handler for a method
    func registerRpc(method: String) {
        guard isConnected else { return }
        socket?.emit("rpc-register", ["method": method] as [String: Any])
    }

    // MARK: - HTTP API

    /// Create or load a session on the server
    func createSession(tag: String, metadata: String) async throws -> [String: Any] {
        return try await postJSON(path: "/v1/sessions", body: ["tag": tag, "metadata": metadata])
    }

    /// Fetch sessions from the server, returning a typed Result.
    ///
    /// Returns ``.success([])`` when sessions list is empty or response lacks the `sessions` key.
    /// Returns ``.notAuthenticated`` when no auth token is available.
    /// Returns ``.networkError(msg)`` on URLSession failure.
    ///
    /// **No crashes on failure.** Callers can distinguish all three cases.
    func fetchSessions() async -> FetchSessionsResult {
        guard let token else {
            Self.logger.warning("fetchSessions: no auth token")
            return .notAuthenticated
        }

        do {
            let res = try await getJSON(path: "/v1/sessions")
            print("[fetchSessions] raw response: \(res)")
            guard let array = res["sessions"] as? [[String: Any]] else {
                Self.logger.warning("fetchSessions: unexpected response shape — no 'sessions' key")
                return .success([])
            }
            let sessions = array.compactMap { RemoteSessionState(from: $0) }
            Self.logger.info("fetchSessions: received \(sessions.count) sessions")
            return .success(sessions)
        } catch {
            Self.logger.error("fetchSessions failed: \(error.localizedDescription)")
            return .networkError(error.localizedDescription)
        }
    }

    /// Fetch sessions returning `[RemoteSessionState]` (errors mapped to empty array).
    ///
    /// Convenience overload for callers that prefer a simple `[T]` return type
    /// and do not need to act on the failure reason.
    func fetchSessions() async -> [RemoteSessionState] {
        // Disambiguate: explicitly use the FetchSessionsResult overload
        let result: FetchSessionsResult = await self.fetchSessions()
        switch result {
        case .success(let sessions):
            return sessions
        case .notAuthenticated:
            Self.logger.warning("fetchSessions: not authenticated")
            return []
        case .networkError(let msg):
            Self.logger.warning("fetchSessions: network error — \(msg)")
            return []
        }
    }

    // MARK: - ServerSessionFetcher conformance
    func fetchRemoteSessions() async -> [RemoteSessionState] {
        // Disambiguate: explicitly use the FetchSessionsResult overload
        let result: FetchSessionsResult = await self.fetchSessions()
        switch result {
        case .success(let sessions):
            return sessions
        case .notAuthenticated:
            Self.logger.warning("fetchRemoteSessions: not authenticated")
            return []
        case .networkError(let msg):
            Self.logger.warning("fetchRemoteSessions: network error — \(msg)")
            return []
        }
    }

    /// Fetch message history for a session from the server.
    func fetchSessionMessages(sessionId: String) async -> [ChatMessage] {
        do {
            let res = try await getJSON(path: "/v1/sessions/\(sessionId)/messages")
            if let array = res["messages"] as? [[String: Any]] {
                print("[fetchSessionMessages] response keys: \(res.keys), count: \(array.count)")
                let msgs = array.compactMap { ChatMessage(from: $0) }
                print("[fetchSessionMessages] parsed \(msgs.count) messages")
                return msgs
            } else {
                print("[fetchSessionMessages] no 'messages' key in response: \(res)")
            }
        } catch {
            Self.logger.error("fetchSessionMessages failed: \(error.localizedDescription)")
        }
        return []
    }

    // MARK: - HTTP Helpers

    private func postJSON(path: String, body: [String: Any]) async throws -> [String: Any] {
        Self.logger.warning("postJSON: serverUrl=|\(self.serverUrl)| path=|\(path)|")
        let combined = "\(serverUrl)\(path)"
        Self.logger.warning("postJSON: combined=|\(combined)|")
        guard let url = URL(string: combined) else {
            Self.logger.warning("postJSON: invalid URL: serverUrl=\(self.serverUrl, privacy: .public), path=\(path, privacy: .public)")
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, _) = try await syncSession.data(for: request)
        return try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
    }

    private func putJSON(path: String, body: [String: Any]) async throws {
        guard let url = URL(string: "\(serverUrl)\(path)") else {
            Self.logger.warning("putJSON: invalid URL")
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        _ = try await syncSession.data(for: request)
    }

    private func getJSON(path: String) async throws -> [String: Any] {
        Self.logger.warning("getJSON: serverUrl=\(self.serverUrl, privacy: .public), path=\(path, privacy: .public)")
        guard let url = URL(string: "\(serverUrl)\(path)") else {
            Self.logger.warning("getJSON: invalid URL")
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        print("[getJSON] request.url=\(url.absoluteString) token prefix=\(token?.prefix(8) ?? "nil")")
        fflush(stdout)
        do {
            let (data, response) = try await syncSession.data(for: request)
            print("[getJSON] response status=\((response as? HTTPURLResponse)?.statusCode ?? -1) data length=\(data.count)")
            fflush(stdout)
            let result = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
            print("[getJSON] parsed keys=\(result.keys)")
            fflush(stdout)
            return result
        } catch {
            print("[getJSON] ERROR: \(error)")
            fflush(stdout)
            throw error
        }
    }

    private func deleteRequest(path: String) async throws {
        guard let url = URL(string: "\(serverUrl)\(path)") else {
            Self.logger.warning("deleteRequest: invalid URL")
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let (_, response) = try await syncSession.data(for: request)
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            throw URLError(.badServerResponse)
        }
    }

    // MARK: - Multi-device pairing API

    /// Register this Mac with the server. Lazy-allocates and returns a permanent shortCode.
    /// Idempotent — call on every launch.
    func registerDevice(name: String, kind: String) async {
        Self.logger.warning("registerDevice: serverUrl=\(self.serverUrl, privacy: .public), name=\(name, privacy: .public), kind=\(kind, privacy: .public)")
        let body = ["name": name, "kind": kind]
        Self.logger.warning("registerDevice body: \(body, privacy: .public)")
        do {
            let res = try await postJSON(path: "/v1/devices/me", body: ["name": name, "kind": kind])
            if let code = res["shortCode"] as? String {
                self.shortCode = code
                Self.logger.info("Registered as \(kind) '\(name)', shortCode=\(code, privacy: .public)")
            } else {
                Self.logger.warning("Device registered but no shortCode returned (kind=\(kind, privacy: .public))")
            }
        } catch {
            Self.logger.error("registerDevice failed: \(error.localizedDescription)")
        }
    }

    /// Upload this Mac's launch presets (full replace).
    func uploadPresets(_ presets: [[String: Any]]) async {
        do {
            try await putJSON(path: "/v1/devices/me/presets", body: ["presets": presets])
        } catch {
            Self.logger.error("uploadPresets failed: \(error.localizedDescription)")
        }
    }

    /// Upload this Mac's known project paths.
    func uploadProjects(_ projects: [[String: String]]) async {
        do {
            try await putJSON(path: "/v1/devices/me/projects", body: ["projects": projects])
        } catch {
            Self.logger.error("uploadProjects failed: \(error.localizedDescription)")
        }
    }

    // MARK: - Linked devices management

    /// A device linked to this Mac (typically an iPhone).
    struct LinkedDeviceInfo: Identifiable {
        let id: String       // deviceId
        let name: String
        let kind: String     // "iphone", "mac"
        let createdAt: String
    }

    /// Fetch all devices linked to this Mac.
    func fetchLinkedDevices() async -> [LinkedDeviceInfo] {
        do {
            guard let url = URL(string: "\(serverUrl)/v1/pairing/links") else { return [] }
            var request = URLRequest(url: url)
            if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
            let (data, _) = try await syncSession.data(for: request)
            guard let array = try JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { return [] }
            return array.compactMap { dict in
                guard let id = dict["deviceId"] as? String,
                      let name = dict["name"] as? String else { return nil }
                let kind = dict["kind"] as? String ?? "unknown"
                let createdAt = dict["createdAt"] as? String ?? ""
                return LinkedDeviceInfo(id: id, name: name, kind: kind, createdAt: createdAt)
            }
        } catch {
            Self.logger.error("fetchLinkedDevices failed: \(error.localizedDescription)")
            return []
        }
    }

    /// Unlink a paired device. Server cascade-deletes push tokens if no links remain.
    func unlinkDevice(_ deviceId: String) async throws {
        try await deleteRequest(path: "/v1/pairing/links/\(deviceId)")
        Self.logger.info("Unlinked device \(deviceId)")
    }
}
