import Foundation
import Combine

// MARK: - Remote Session Load State

enum RemoteSessionLoadState: Equatable {
    case idle
    case loading
    case loaded([RemoteSessionState])
    case error(String)
}

// MARK: - Server Session Monitor

/// Monitors remote sessions from the sync-daemon server.
/// Lives on Mac — fetches sessions created by sync-daemon on other devices
/// and displays them in the instances list alongside local sessions.
@MainActor
final class ServerSessionMonitor: ObservableObject {

    static let shared = ServerSessionMonitor()

    // MARK: - Published State

    @Published private(set) var loadState: RemoteSessionLoadState = .idle
    @Published private(set) var sessions: [RemoteSessionState] = []

    private var refreshTimer: Timer?

    // MARK: - Init

    private init() {
        // Fetch after a short delay to let SyncManager finish connecting
        Task {
            try? await Task.sleep(nanoseconds: 3_000_000_000) // 3 seconds
            self.fetchNow()
        }

        // Also fetch immediately once SyncManager is already connected
        if SyncManager.shared.connection != nil && SyncManager.shared.connection?.isConnected == true {
            Task {
                try? await Task.sleep(nanoseconds: 500_000_000) // 0.5 seconds
                self.fetchNow()
            }
        }
    }

    // MARK: - Public

    func fetchNow() {
        loadState = .loading

        Task {
            do {
                let fetched = try await self.fetchFromServer()
                self.sessions = fetched
                self.loadState = .loaded(fetched)
                print("[ServerSessionMonitor] UI updated: \(fetched.count) sessions")
                fflush(stdout)
            } catch {
                self.loadState = .error(error.localizedDescription)
            }
        }
    }

    // MARK: - Private

    private func fetchFromServer() async throws -> [RemoteSessionState] {
        guard let connection = SyncManager.shared.connection else {
            throw ServerSessionMonitorError.notConnected
        }
        return await connection.fetchSessions()
    }
}

// MARK: - Error

enum ServerSessionMonitorError: Error, LocalizedError {
    case notConnected

    var message: String {
        switch self {
        case .notConnected:
            return "Not connected to server"
        }
    }

    var errorDescription: String? { message }
}