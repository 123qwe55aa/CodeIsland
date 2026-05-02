//
//  NetworkMonitor.swift
//  ClaudeIsland
//
//  Monitors network changes and updates relay configurations when IP changes.
//

import Foundation
import Combine
import Network
import os.log

@MainActor
final class NetworkMonitor: ObservableObject {
    static let shared = NetworkMonitor()

    @Published private(set) var currentIP: String?
    @Published private(set) var isNetworkAvailable = false

    private let monitor = NWPathMonitor()
    private let monitorQueue = DispatchQueue(label: "com.codeisland.networkmonitor")
    private var pollingTimer: Timer?
    private let logger = Logger(subsystem: "com.codeisland", category: "NetworkMonitor")

    private init() {}

    func start() {
        // Monitor network path changes
        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                self?.isNetworkAvailable = path.status == .satisfied
                await self?.checkIPChange()
            }
        }
        monitor.start(queue: monitorQueue)

        // Also poll every 30s as backup for IP drift detection
        pollingTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            Task { @MainActor in
                await self?.checkIPChange()
            }
        }

        // Initial check
        Task { await checkIPChange() }

        logger.info("NetworkMonitor started")
    }

    func stop() {
        monitor.cancel()
        pollingTimer?.invalidate()
        pollingTimer = nil
        logger.info("NetworkMonitor stopped")
    }

    private func checkIPChange() async {
        guard let newIP = await getMacIP() else { return }
        if newIP != currentIP {
            let oldIP = currentIP
            currentIP = newIP
            logger.info("IP changed: \(oldIP ?? "nil") -> \(newIP)")
            await updateAllDirectHosts(newIP: newIP)
        }
    }

    private func getMacIP() async -> String? {
        for iface in ["en0", "en1", "en2", "en3"] {
            let result = await Task.detached(priority: .utility) { () -> String? in
                let pipe = Pipe()
                let process = Process()
                process.executableURL = URL(fileURLWithPath: "/sbin/ifconfig")
                process.arguments = [iface]
                process.standardOutput = pipe
                process.standardError = FileHandle.nullDevice
                do {
                    try process.run()
                    process.waitUntilExit()
                    let data = pipe.fileHandleForReading.readDataToEndOfFile()
                    if let output = String(data: data, encoding: .utf8) {
                        let pattern = #"inet (\d+\.\d+\.\d+\.\d+)"#
                        if let regex = try? NSRegularExpression(pattern: pattern),
                           let match = regex.firstMatch(in: output, range: NSRange(output.startIndex..., in: output)),
                           let range = Range(match.range(at: 1), in: output) {
                            let ip = String(output[range])
                            if ip != "127.0.0.1" { return ip }
                        }
                    }
                } catch { return nil }
                return nil
            }.value
            if let ip = result { return ip }
        }
        return nil
    }

    private func updateAllDirectHosts(newIP: String) async {
        let hosts = await SSHHostRegistry.shared.currentHosts()
        for host in hosts where host.connectionMode == .direct {
            await updateRelayConfig(host: host, newIP: newIP)
        }
    }

    private func updateRelayConfig(host: SSHHost, newIP: String) async {
        logger.info("Updating relay config for \(host.user)@\(host.host) to IP \(newIP)")

        // Build SSH args
        var sshArgs = [
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=15",
            "-o", "StrictHostKeyChecking=accept-new"
        ]
        if let keyPath = host.sshKeyPath {
            sshArgs += ["-i", keyPath]
        }
        if host.port != 22 {
            sshArgs += ["-p", "\(host.port)"]
        }

        let remoteUserHost = "\(host.user)@\(host.host)"

        // Update relay.conf via SSH - use sed to replace RELAY_HOST value, then HUP the relay
        let updateCmd = "sed -i.bak 's/^RELAY_HOST=.*/RELAY_HOST=\(newIP)/' ~/.codeisland/relay.conf && pkill -HUP -f codeisland-ssh-relay.py || true"

        let (result, stderr) = await Task.detached {
            HookInstaller.runSSHCommandWithOutput(
                args: sshArgs + [remoteUserHost, updateCmd],
                timeout: 30
            )
        }.value

        if result != nil {
            logger.info("Relay config updated for \(host.host)")
        } else {
            logger.error("Failed to update relay config for \(host.host): \(stderr ?? "unknown")")
        }
    }
}
