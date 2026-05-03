//
//  SessionCacheManager.swift
//  ClaudeIsland
//
//  Persists remote session info to local disk so sessions can be restored after disconnect.
//

import Foundation
import os.log

/// Persists session cache to local disk and loads it on reconnect.
final class SessionCacheManager: @unchecked Sendable {
    static let shared = SessionCacheManager()

    private let logger = Logger(subsystem: "com.codeisland", category: "SessionCache")
    private let cacheDir: URL

    /// What we persist per session
    struct Cache: Codable {
        let sessionId: String
        let cwd: String
        let projectName: String
        let remoteHost: String?
        let conversationSummary: String?
        let conversationFirstMessage: String?
        let conversationLatestMessage: String?
        let conversationLastTool: String?
        let lastActivity: Date

        init(from session: SessionState) {
            self.sessionId = session.sessionId
            self.cwd = session.cwd
            self.projectName = session.projectName
            self.remoteHost = session.remoteHost
            self.conversationSummary = session.conversationInfo.summary
            self.conversationFirstMessage = session.conversationInfo.firstUserMessage
            self.conversationLatestMessage = session.conversationInfo.latestUserMessage
            self.conversationLastTool = session.conversationInfo.lastToolName
            self.lastActivity = session.lastActivity
        }

        /// Apply this cache to fill conversationInfo on a restored session
        func apply(to session: inout SessionState) {
            session.conversationInfo = ConversationInfo(
                summary: conversationSummary,
                lastMessage: conversationLatestMessage,
                lastMessageRole: nil,
                lastToolName: conversationLastTool,
                firstUserMessage: conversationFirstMessage,
                latestUserMessage: conversationLatestMessage,
                lastUserMessageDate: nil
            )
            session.lastActivity = lastActivity
        }
    }

    private init() {
        let home = FileManager.default.homeDirectoryForCurrentUser
        self.cacheDir = home.appendingPathComponent(".claude/sessions", isDirectory: true)
        try? FileManager.default.createDirectory(at: cacheDir, withIntermediateDirectories: true)
    }

    /// Save cache for a session (call after processing a remote hook event)
    func save(_ session: SessionState) {
        guard session.remoteHost != nil else { return }  // Only cache remote sessions

        let cache = Cache(from: session)
        let file = cacheFile(for: cache.sessionId)

        do {
            let data = try JSONEncoder().encode(cache)
            try data.write(to: file, options: .atomic)
            logger.debug("Saved cache for \(session.sessionId.prefix(8))")
        } catch {
            logger.error("Failed to save session cache: \(error.localizedDescription)")
        }
    }

    /// Load cache for a session if it exists (call when creating a new session)
    func load(sessionId: String) -> Cache? {
        let file = cacheFile(for: sessionId)
        guard FileManager.default.fileExists(atPath: file.path) else { return nil }

        do {
            let data = try Data(contentsOf: file)
            let cache = try JSONDecoder().decode(Cache.self, from: data)
            logger.info("Loaded cache for \(sessionId.prefix(8)): summary=\(cache.conversationSummary?.prefix(30) ?? "nil")")
            return cache
        } catch {
            logger.error("Failed to load session cache: \(error.localizedDescription)")
            return nil
        }
    }

    /// Delete cache for a session (call when session is permanently removed)
    func delete(sessionId: String) {
        let file = cacheFile(for: sessionId)
        try? FileManager.default.removeItem(at: file)
        logger.debug("Deleted cache for \(sessionId.prefix(8))")
    }

    private func cacheFile(for sessionId: String) -> URL {
        cacheDir.appendingPathComponent("\(sessionId)_cache.json")
    }
}
