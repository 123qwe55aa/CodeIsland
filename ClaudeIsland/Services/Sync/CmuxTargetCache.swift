//
//  CmuxTargetCache.swift
//  ClaudeIsland
//
//  In-memory cache for cmux workspace/surface IDs keyed by process PID.
//  Entries expire after 5 minutes to avoid stale process lookups.
//

import Foundation

final class CmuxTargetCache: @unchecked Sendable {
    static let shared = CmuxTargetCache()
    private var cache: [Int: (workspaceId: String, surfaceId: String?)] = [:]
    private var timestamps: [Int: Date] = [:]
    private let lifetime: TimeInterval = 300 // 5 minutes

    private init() {}

    func get(_ pid: Int) -> (workspaceId: String, surfaceId: String?)? {
        guard let ts = timestamps[pid], Date().timeIntervalSince(ts) < lifetime else {
            cache.removeValue(forKey: pid)
            timestamps.removeValue(forKey: pid)
            return nil
        }
        return cache[pid]
    }

    func set(_ pid: Int, target: (workspaceId: String, surfaceId: String?)) {
        cache[pid] = target
        timestamps[pid] = Date()
    }
}
