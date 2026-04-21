//
//  HookInstaller.swift
//  ClaudeIsland
//
//  Auto-installs Claude Code hooks on app launch
//

import Foundation

struct HookInstaller {

    /// Install hook script and update settings.json on app launch
    static func installIfNeeded() {
        cleanupLegacyHooks()

        let claudeDir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".claude")
        let hooksDir = claudeDir.appendingPathComponent("hooks")
        let pythonScript = hooksDir.appendingPathComponent("codeisland-state.py")
        let settings = claudeDir.appendingPathComponent("settings.json")

        try? FileManager.default.createDirectory(
            at: hooksDir,
            withIntermediateDirectories: true
        )

        if let bundled = Bundle.main.url(forResource: "codeisland-state", withExtension: "py") {
            try? FileManager.default.removeItem(at: pythonScript)
            try? FileManager.default.copyItem(at: bundled, to: pythonScript)
            try? FileManager.default.setAttributes(
                [.posixPermissions: 0o755],
                ofItemAtPath: pythonScript.path
            )
        }

        updateSettings(at: settings)
    }

    private static func updateSettings(at settingsURL: URL) {
        var json: [String: Any] = [:]
        if let data = try? Data(contentsOf: settingsURL),
           let existing = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            json = existing
        }

        let python = detectPython()
        let command = "\(python) ~/.claude/hooks/codeisland-state.py"
        let hookEntry: [[String: Any]] = [["type": "command", "command": command]]
        let hookEntryWithTimeout: [[String: Any]] = [["type": "command", "command": command, "timeout": 86400]]
        let withMatcher: [[String: Any]] = [["matcher": "*", "hooks": hookEntry]]
        let withMatcherAndTimeout: [[String: Any]] = [["matcher": "*", "hooks": hookEntryWithTimeout]]
        let withoutMatcher: [[String: Any]] = [["hooks": hookEntry]]
        let preCompactConfig: [[String: Any]] = [
            ["matcher": "auto", "hooks": hookEntry],
            ["matcher": "manual", "hooks": hookEntry]
        ]

        var hooks = json["hooks"] as? [String: Any] ?? [:]

        let hookEvents: [(String, [[String: Any]])] = [
            ("UserPromptSubmit", withoutMatcher),
            ("PreToolUse", withMatcher),
            ("PostToolUse", withMatcher),
            ("PermissionRequest", withMatcherAndTimeout),
            ("Notification", withMatcher),
            ("Stop", withoutMatcher),
            ("SubagentStop", withoutMatcher),
            ("SessionStart", withoutMatcher),
            ("SessionEnd", withoutMatcher),
            ("PreCompact", preCompactConfig),
        ]

        for (event, config) in hookEvents {
            if var existingEvent = hooks[event] as? [[String: Any]] {
                let hasOurHook = existingEvent.contains { entry in
                    if let entryHooks = entry["hooks"] as? [[String: Any]] {
                        return entryHooks.contains { h in
                            let cmd = h["command"] as? String ?? ""
                            return cmd.contains("codeisland-state.py")
                        }
                    }
                    return false
                }
                if !hasOurHook {
                    existingEvent.append(contentsOf: config)
                    hooks[event] = existingEvent
                }
            } else {
                hooks[event] = config
            }
        }

        json["hooks"] = hooks

        if let data = try? JSONSerialization.data(
            withJSONObject: json,
            options: [.prettyPrinted, .sortedKeys]
        ) {
            try? data.write(to: settingsURL)
        }
    }

    /// Check if hooks are currently installed
    static func isInstalled() -> Bool {
        let claudeDir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".claude")
        let settings = claudeDir.appendingPathComponent("settings.json")

        guard let data = try? Data(contentsOf: settings),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let hooks = json["hooks"] as? [String: Any] else {
            return false
        }

        for (_, value) in hooks {
            if let entries = value as? [[String: Any]] {
                for entry in entries {
                    if let entryHooks = entry["hooks"] as? [[String: Any]] {
                        for hook in entryHooks {
                            if let cmd = hook["command"] as? String,
                               cmd.contains("codeisland-state.py") {
                                return true
                            }
                        }
                    }
                }
            }
        }
        return false
    }

    /// Uninstall hooks from settings.json and remove script
    static func uninstall() {
        let claudeDir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".claude")
        let hooksDir = claudeDir.appendingPathComponent("hooks")
        let pythonScript = hooksDir.appendingPathComponent("codeisland-state.py")
        let settings = claudeDir.appendingPathComponent("settings.json")

        try? FileManager.default.removeItem(at: pythonScript)

        guard let data = try? Data(contentsOf: settings),
              var json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              var hooks = json["hooks"] as? [String: Any] else {
            return
        }

        for (event, value) in hooks {
            if var entries = value as? [[String: Any]] {
                entries.removeAll { entry in
                    if let entryHooks = entry["hooks"] as? [[String: Any]] {
                        return entryHooks.contains { hook in
                            let cmd = hook["command"] as? String ?? ""
                            return cmd.contains("codeisland-state.py")
                        }
                    }
                    return false
                }

                if entries.isEmpty {
                    hooks.removeValue(forKey: event)
                } else {
                    hooks[event] = entries
                }
            }
        }

        if hooks.isEmpty {
            json.removeValue(forKey: "hooks")
        } else {
            json["hooks"] = hooks
        }

        if let data = try? JSONSerialization.data(
            withJSONObject: json,
            options: [.prettyPrinted, .sortedKeys]
        ) {
            try? data.write(to: settings)
        }
    }

    /// Strip hook entries from older app versions (Claude Island etc.) and
    /// delete their leftover scripts. Idempotent — safe to run every launch.
    /// Without this, users who installed a pre-rename build keep double-firing
    /// every Claude Code hook because both the old and new scripts are still
    /// wired up in settings.json.
    static func cleanupLegacyHooks() {
        let legacyScripts = ["claude-island-state.py"]

        let claudeDir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".claude")
        let hooksDir = claudeDir.appendingPathComponent("hooks")
        let settings = claudeDir.appendingPathComponent("settings.json")

        // 1. Delete the legacy script files on disk (no-op if missing).
        for name in legacyScripts {
            let path = hooksDir.appendingPathComponent(name)
            try? FileManager.default.removeItem(at: path)
        }

        // 2. Strip their entries out of settings.json hooks config.
        guard let data = try? Data(contentsOf: settings),
              var json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              var hooks = json["hooks"] as? [String: Any] else {
            return
        }

        func entryReferencesLegacy(_ entry: [String: Any]) -> Bool {
            guard let entryHooks = entry["hooks"] as? [[String: Any]] else { return false }
            return entryHooks.contains { hook in
                guard let cmd = hook["command"] as? String else { return false }
                return legacyScripts.contains { cmd.contains($0) }
            }
        }

        var mutated = false
        for (event, value) in hooks {
            guard var entries = value as? [[String: Any]] else { continue }
            let before = entries.count
            entries.removeAll(where: entryReferencesLegacy)
            guard entries.count != before else { continue }
            mutated = true
            if entries.isEmpty {
                hooks.removeValue(forKey: event)
            } else {
                hooks[event] = entries
            }
        }

        guard mutated else { return }

        if hooks.isEmpty {
            json.removeValue(forKey: "hooks")
        } else {
            json["hooks"] = hooks
        }

        if let newData = try? JSONSerialization.data(
            withJSONObject: json,
            options: [.prettyPrinted, .sortedKeys]
        ), !newData.isEmpty {
            try? newData.write(to: settings, options: .atomic)
        }
    }

    private static func detectPython() -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/which")
        process.arguments = ["python3"]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice

        do {
            try process.run()
            process.waitUntilExit()
            if process.terminationStatus == 0 {
                return "python3"
            }
        } catch {}

        return "python"
    }
}
