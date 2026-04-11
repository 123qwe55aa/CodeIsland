//
//  TmuxSessionMatcher.swift
//  ClaudeIsland
//
//  Matches tmux panes to session files by sampling visible text.
//  Also provides tmux target caching for cmux PID lookups (5-minute TTL).
//

import Foundation

/// Cache entry for cmux workspace/surface IDs keyed by PID
private struct CmuxTargetCacheEntry {
    let target: (workspaceId: String, surfaceId: String?)
    let expires: Date
}

/// Thread-safe cmux target cache with 5-minute TTL.
/// Uses NSLock for thread-safety so it can be accessed from nonisolated contexts.
final class CmuxTargetCache: @unchecked Sendable {
    static let shared = CmuxTargetCache()

    private var cache: [Int: CmuxTargetCacheEntry] = [:]
    private let lock = NSLock()
    private let ttlSeconds: TimeInterval = 300  // 5 minutes

    func get(_ pid: Int) -> (workspaceId: String, surfaceId: String?)? {
        lock.lock()
        defer { lock.unlock() }
        guard let entry = cache[pid], entry.expires > Date() else {
            cache.removeValue(forKey: pid)
            return nil
        }
        return entry.target
    }

    func set(_ pid: Int, target: (workspaceId: String, surfaceId: String?)) {
        lock.lock()
        defer { lock.unlock() }
        cache[pid] = CmuxTargetCacheEntry(target: target, expires: Date().addingTimeInterval(ttlSeconds))
    }

    func remove(_ pid: Int) {
        lock.lock()
        defer { lock.unlock() }
        cache.removeValue(forKey: pid)
    }

    func prune() {
        lock.lock()
        defer { lock.unlock() }
        let now = Date()
        cache = cache.filter { $0.value.expires > now }
    }
}

/// Matches tmux panes to Claude session files by sampling pane content
actor TmuxSessionMatcher {
    static let shared = TmuxSessionMatcher()

    private init() {}

    /// Find the session ID for a tmux pane by matching visible text to session files
    /// - Parameters:
    ///   - target: The tmux target (session:window.pane)
    ///   - projectDir: The project directory containing session files
    /// - Returns: The session ID if found with high confidence
    func findSessionId(forTarget target: TmuxTarget, projectDir: URL) async -> String? {
        guard let tmuxPath = await TmuxPathFinder.shared.getTmuxPath() else {
            return nil
        }

        guard let paneContent = await capturePaneContent(tmuxPath: tmuxPath, target: target) else {
            return nil
        }

        let snippets = extractSnippets(from: paneContent)
        guard snippets.count >= 2 else {
            return nil
        }

        guard let sessionFiles = try? FileManager.default.contentsOfDirectory(
            at: projectDir,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        ).filter({ $0.pathExtension == "jsonl" && !$0.lastPathComponent.hasPrefix("agent-") }) else {
            return nil
        }

        var bestMatch: (sessionId: String, score: Int)?

        for sessionUrl in sessionFiles {
            let sessionId = sessionUrl.deletingPathExtension().lastPathComponent
            let score = countMatchingSnippets(snippets: snippets, inFile: sessionUrl)

            if score > 0 && (bestMatch == nil || score > bestMatch!.score) {
                bestMatch = (sessionId, score)
            }
        }

        if let match = bestMatch, match.score >= 2 {
            return match.sessionId
        }

        return nil
    }

    // MARK: - Cmux Cache Helpers

    /// Look up cached cmux target for a PID (5-minute TTL)
    func getCachedCmuxTarget(forPid pid: Int) -> (workspaceId: String, surfaceId: String?)? {
        return CmuxTargetCache.shared.get(pid)
    }

    /// Cache a cmux target for a PID
    func cacheCmuxTarget(forPid pid: Int, target: (workspaceId: String, surfaceId: String?)) {
        CmuxTargetCache.shared.set(pid, target: target)
    }

    // MARK: - Private Methods

    private func capturePaneContent(tmuxPath: String, target: TmuxTarget) async -> String? {
        do {
            let output = try await ProcessExecutor.shared.run(tmuxPath, arguments: [
                "capture-pane", "-t", target.targetString, "-p", "-S", "-500"
            ])
            return output.isEmpty ? nil : output
        } catch {
            return nil
        }
    }

    private func extractSnippets(from content: String) -> [String] {
        var snippets: [String] = []

        let lines = content.components(separatedBy: "\n")

        for line in lines {
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            guard trimmed.count >= 25 else { continue }

            let firstChar = trimmed.first ?? " "
            if "+-|>⏺─━═[]{}()".contains(firstChar) { continue }
            if trimmed.hasPrefix("//") || trimmed.hasPrefix("/*") { continue }

            let letterCount = trimmed.filter { $0.isLetter }.count
            guard letterCount > trimmed.count / 3 else { continue }

            let snippet = String(trimmed.prefix(80))
            snippets.append(snippet)
        }

        guard snippets.count > 0 else { return [] }

        if snippets.count <= 5 {
            return snippets
        }

        var sampled: [String] = []
        let step = snippets.count / 5
        for i in stride(from: 0, to: snippets.count, by: max(1, step)) {
            sampled.append(snippets[i])
            if sampled.count >= 5 { break }
        }

        return sampled
    }

    private func countMatchingSnippets(snippets: [String], inFile fileUrl: URL) -> Int {
        guard let handle = try? FileHandle(forReadingFrom: fileUrl) else {
            return 0
        }
        defer { try? handle.close() }

        let fileSize = (try? handle.seekToEnd()) ?? 0
        let readSize: UInt64 = min(100000, fileSize)
        if fileSize > readSize {
            try? handle.seek(toOffset: fileSize - readSize)
        } else {
            try? handle.seek(toOffset: 0)
        }

        guard let data = try? handle.readToEnd(),
              let content = String(data: data, encoding: .utf8) else {
            return 0
        }

        var matchCount = 0
        for snippet in snippets {
            if content.contains(snippet) {
                matchCount += 1
            }
        }

        return matchCount
    }
}
