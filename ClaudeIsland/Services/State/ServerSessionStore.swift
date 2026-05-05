import Foundation
import Combine

// MARK: - Notification Names

extension Notification.Name {
    static let serverSessionsDidUpdate = Notification.Name("serverSessionsDidUpdate")
}

// MARK: - Server Session Store

/// Simple non-isolated store — fetches remote sessions and broadcasts via NotificationCenter.
/// Lives on Mac — fetches sessions created by sync-daemon on other devices.
final class ServerSessionStore: @unchecked Sendable {

    static let shared = ServerSessionStore()

    // Snapshot of last fetched sessions
    private(set) var sessions: [RemoteSessionState] = []

    private var fetchTask: Task<Void, Never>?

    private init() {}

    // MARK: - Public

    /// Force an immediate fetch.
    func fetchNow() {
        fetchTask?.cancel()
        fetchTask = Task { [weak self] in
            await self?.doFetch()
        }
    }

    // MARK: - Private

    private func doFetch() async {
        guard let connection = SyncManager.shared.connection else {
            print("[ServerSessionStore] no connection, skipping fetch")
            return
        }

        let result: [RemoteSessionState] = await connection.fetchSessions()
        print("[ServerSessionStore] got \(result.count) sessions")

        self.sessions = result
        NotificationCenter.default.post(name: .serverSessionsDidUpdate, object: nil, userInfo: ["sessions": result])
    }
}