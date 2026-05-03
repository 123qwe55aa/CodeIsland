//
//  ServerSessionStore.swift
//  ClaudeIsland
//
//  Actor-based store for remote sessions received from CodeServer.
//  Manages loading, error, and empty states for UI binding.
//

import Combine
import Foundation
import os.log

/// Load state for remote sessions from the server.
enum RemoteSessionLoadState: Equatable, Sendable {
    case idle
    case loading
    case loaded([RemoteSessionState])
    case error(String)

    var sessions: [RemoteSessionState] {
        if case .loaded(let s) = self { return s }
        return []
    }

    var isLoading: Bool {
        if case .loading = self { return true }
        return false
    }

    var errorMessage: String? {
        if case .error(let msg) = self { return msg }
        return nil
    }

    var isEmpty: Bool {
        if case .loaded(let s) = self { return s.isEmpty }
        return false
    }
}

/// Actor-based store for remote sessions from CodeServer.
/// Provides async loading with publishable state for SwiftUI observation.
actor ServerSessionStore {
    static let logger = Logger(subsystem: "com.codeisland", category: "ServerSessionStore")

    static let shared = ServerSessionStore()

    // MARK: - State

    private(set) var loadState: RemoteSessionLoadState = .idle

    /// Publisher for UI observation (nonisolated for Combine access from any context)
    private nonisolated(unsafe) let stateSubject = CurrentValueSubject<RemoteSessionLoadState, Never>(.idle)

    /// Public publisher
    nonisolated var statePublisher: AnyPublisher<RemoteSessionLoadState, Never> {
        stateSubject.eraseToAnyPublisher()
    }

    // MARK: - Configuration

    /// Fetch interval (default: 60 seconds)
    private var fetchInterval: TimeInterval = 60

    /// Refresh timer task
    private var refreshTask: Task<Void, Never>?

    // MARK: - Fetch

    /// Fetch sessions from the server via the given connection.
    /// Replaces current state atomically.
    func fetch(using connection: ServerSessionFetcher) async {
        guard case .idle = loadState else {
            // Already loading or errored — allow refresh anyway
            await refresh(using: connection)
            return
        }

        loadState = .loading
        stateSubject.send(loadState)

        let sessions = await connection.fetchRemoteSessions()

        loadState = .loaded(sessions)
        stateSubject.send(loadState)
        Self.logger.info("Remote sessions loaded: \(sessions.count)")
    }

    /// Force-refresh sessions (ignores idle check, preserves error state).
    func refresh(using connection: ServerSessionFetcher) async {
        let sessions = await connection.fetchRemoteSessions()

        loadState = .loaded(sessions)
        stateSubject.send(loadState)
        Self.logger.info("Remote sessions refreshed: \(sessions.count)")
    }

    /// Fetch with error handling — sets error state on failure.
    func fetchWithErrorHandling(using connection: ServerSessionFetcher) async {
        loadState = .loading
        stateSubject.send(loadState)

        let sessions = await connection.fetchRemoteSessions()
        loadState = .loaded(sessions)
        stateSubject.send(loadState)
        Self.logger.info("Remote sessions loaded: \(sessions.count)")
    }

    // MARK: - Periodic Refresh

    /// Start periodic refresh every `interval` seconds.
    func startPeriodicRefresh(interval: TimeInterval = 60, using connection: ServerSessionFetcher) {
        fetchInterval = interval
        stopPeriodicRefresh()

        refreshTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self = self else { break }
                await self.refresh(using: connection)
                try? await Task.sleep(nanoseconds: UInt64(interval * 1_000_000_000))
            }
        }
        Self.logger.info("Periodic refresh started (interval: \(interval)s)")
    }

    /// Stop periodic refresh.
    func stopPeriodicRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
    }

    // MARK: - State Management

    /// Reset to idle state (clears data).
    func reset() {
        loadState = .idle
        stateSubject.send(loadState)
    }

    /// Get a snapshot of current sessions.
    func currentSessions() -> [RemoteSessionState] {
        loadState.sessions
    }
}

/// Protocol for objects that can fetch remote sessions.
/// Implemented by ServerConnection (which is @MainActor).
@MainActor
protocol ServerSessionFetcher {
    func fetchRemoteSessions() async -> [RemoteSessionState]
}

/// Extend ServerConnection to conform when it gains the method
extension ServerConnection: ServerSessionFetcher {}

// MARK: - View Model Wrapper

/// @MainActor observable object wrapping ServerSessionStore for SwiftUI.
@MainActor
final class ServerSessionMonitor: ObservableObject {
    static let logger = Logger(subsystem: "com.codeisland", category: "ServerSessionMonitor")

    static let shared = ServerSessionMonitor()

    @Published private(set) var loadState: RemoteSessionLoadState = .idle
    @Published private(set) var sessions: [RemoteSessionState] = []

    private var cancellables = Set<AnyCancellable>()
    private var store: ServerSessionStore { ServerSessionStore.shared }

    init() {
        Task {
            await store.statePublisher
                .receive(on: DispatchQueue.main)
                .sink { [weak self] state in
                    self?.loadState = state
                    self?.sessions = state.sessions
                }
                .store(in: &cancellables)
        }
    }

    /// Trigger a fetch now.
    func fetchNow() async {
        guard let conn = SyncManager.shared.connection else {
            loadState = .error("Not connected to server")
            return
        }
        await store.fetchWithErrorHandling(using: conn)
    }

    /// Force refresh sessions.
    func refresh() async {
        guard let conn = SyncManager.shared.connection else { return }
        await store.refresh(using: conn)
    }

    /// Start periodic refresh from SyncManager's connected state.
    func startAutoRefresh() async {
        guard let conn = SyncManager.shared.connection else { return }
        await store.startPeriodicRefresh(interval: 60, using: conn)
    }

    /// Stop auto-refresh.
    func stopAutoRefresh() {
        Task {
            await store.stopPeriodicRefresh()
        }
    }
}
