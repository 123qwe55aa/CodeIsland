//
//  SSHHelpers.swift
//  ClaudeIsland
//
//  Shared SSH utilities extracted from HookInstaller.
//  Used by NetworkMonitor and SSHHostsView for remote deployment.
//

import Foundation

/// Validates a hostname or IP address for SSRF prevention.
/// Returns nil if valid, or an error message if invalid.
func validateSSRFHost(_ host: String) -> String? {
    let ipv4Pattern = #"^(\d{1,3}\.){3}\d{1,3}$"#
    let hostnamePattern = #"^[a-zA-Z0-9]([a-zA-Z0-9.-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9.-]{0,61}[a-zA-Z0-9])?)*$"#

    if let ipv4Regex = try? NSRegularExpression(pattern: ipv4Pattern),
       ipv4Regex.firstMatch(in: host, range: NSRange(host.startIndex..., in: host)) != nil {
        let octets = host.split(separator: ".").compactMap { Int($0) }
        if octets.count == 4 && octets.allSatisfy({ $0 >= 0 && $0 <= 255 }) {
            return nil
        }
    }

    if let hostnameRegex = try? NSRegularExpression(pattern: hostnamePattern),
       hostnameRegex.firstMatch(in: host, range: NSRange(host.startIndex..., in: host)) != nil {
        return nil
    }

    return "Invalid host: \(host). Only IP addresses or hostnames are allowed."
}

/// Deploy relay script to a remote SSH host.
/// Returns error message on failure, nil on success.
func deployToSSHHost(
    host: SSHHost,
    macIP: String,
    psk: String,
    sshKeyPath: String?
) async -> String? {
    // Validate host to prevent SSRF
    if let error = validateSSRFHost(host.host) {
        return error
    }

    // Use direct path lookup instead of Bundle.main.url to avoid development build issues
    var relayScript: URL?
    if let resourcePath = Bundle.main.resourcePath {
        let resURL = URL(fileURLWithPath: resourcePath)
        let relayURL = resURL.appendingPathComponent("codeisland-ssh-relay.py")
        if FileManager.default.fileExists(atPath: relayURL.path) { relayScript = relayURL }
    }

    guard let relayPath = relayScript else {
        return "Could not find bundled codeisland-ssh-relay.py"
    }

    // Build SSH args
    var scpArgs = ["-o", "BatchMode=yes"]
    var sshArgs = ["-o", "BatchMode=yes"]

    if let keyPath = sshKeyPath ?? host.sshKeyPath {
        scpArgs += ["-i", keyPath]
        sshArgs += ["-i", keyPath]
    }

    if host.port != 22 {
        scpArgs += ["-P", "\(host.port)"]
        sshArgs += ["-p", "\(host.port)"]
    }

    let remoteDir = "~/.codeisland"
    let remoteUserHost = "\(host.user)@\(host.host)"

    // 1. Create remote directory
    let mkdirCmd = "mkdir -p \(remoteDir)"
    let (mkdirSuccess, mkdirStderr) = runSSHCommandWithOutput(args: sshArgs + [remoteUserHost, mkdirCmd], timeout: 30)
    if mkdirSuccess == nil {
        return "Failed to create remote directory on \(host.host): \(mkdirStderr ?? "unknown error")"
    }

    // 2. SCP relay script
    let (scpRelaySuccess, scpRelayStderr) = runSCPFile(
        localPath: relayPath.path,
        remotePath: "\(remoteUserHost):\(remoteDir)/codeisland-ssh-relay.py",
        args: scpArgs
    )
    if !scpRelaySuccess {
        return "Failed to upload relay script to \(host.host): \(scpRelayStderr ?? "unknown error")"
    }

    // 3. Make script executable
    let chmodCmd = "chmod +x \(remoteDir)/codeisland-ssh-relay.py"
    let (chmodSuccess, chmodStderr) = runSSHCommandWithOutput(args: sshArgs + [remoteUserHost, chmodCmd], timeout: 30)
    if chmodSuccess == nil {
        return "Failed to set permissions on \(host.host): \(chmodStderr ?? "unknown error")"
    }

    // 4. Verify Python on remote
    let pythonCheck = "which python3 || which python"
    let (pythonResult, pythonStderr) = runSSHCommandWithOutput(args: sshArgs + [remoteUserHost, pythonCheck], timeout: 30)
    guard pythonResult != nil else {
        return "Python not found on \(host.host): \(pythonStderr ?? "command failed")"
    }

    // 5. Generate config file using base64 to avoid shell injection.
    let relayHost = (host.connectionMode == .direct) ? macIP : "localhost"
    let configLines = [
        "RELAY_HOST=\(relayHost)",
        "RELAY_PORT=\(host.localPort)",
        "PSK=\(psk)"
    ]
    let configContent = configLines.joined(separator: "\n")
    let configBase64 = configContent.data(using: .utf8)!.base64EncodedString()
    let remoteConfig = "printf '\(configBase64)' | base64 -d > \(remoteDir)/relay.conf"

    // 6. Generate startup script using base64 to avoid shell injection
    let startupScript = """
    #!/bin/bash
    cd \(remoteDir)
    pkill -f codeisland-ssh-relay.py || true
    sleep 1
    nohup ./codeisland-ssh-relay.py > \(remoteDir)/relay.log 2>&1 &
    echo "Relay started with PID $!"
    """

    let startupBase64 = startupScript.data(using: .utf8)!.base64EncodedString()
    let remoteStart = "\(remoteConfig) && printf '\(startupBase64)' | base64 -d > \(remoteDir)/start-relay.sh && chmod +x \(remoteDir)/start-relay.sh && \(remoteDir)/start-relay.sh"

    let (startSuccess, startStderr) = runSSHCommandWithOutput(args: sshArgs + [remoteUserHost, remoteStart], timeout: 30)
    if startSuccess == nil {
        return "Failed to start relay on \(host.host): \(startStderr ?? "unknown error")"
    }

    return nil
}

/// Run an SSH command and return stdout/stderr.
func runSSHCommandWithOutput(args: [String], timeout: Int) -> (stdout: String?, stderr: String?) {
    let p = Process()
    let stdoutPipe = Pipe()
    let stderrPipe = Pipe()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/ssh")
    p.arguments = args
    p.standardOutput = stdoutPipe
    p.standardError = stderrPipe
    do {
        try p.run()
        let timer = DispatchSource.makeTimerSource(queue: .global())
        timer.schedule(deadline: .now() + .seconds(timeout))
        timer.setEventHandler {
            if p.isRunning { p.terminate() }
        }
        timer.resume()
        p.waitUntilExit()
        let stdoutData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
        let stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
        let stdout = String(data: stdoutData, encoding: .utf8)
        let stderr = String(data: stderrData, encoding: .utf8)
        guard p.terminationStatus == 0 else { return (nil, stderr) }
        return (stdout, stderr)
    } catch let error as NSError {
        return (nil, "Process error: \(error.localizedDescription)")
    }
}

/// Run an SSH command (silent, success/failure only).
func runSSHCommand(args: [String], timeout: Int) -> Bool {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/ssh")
    p.arguments = args
    p.standardOutput = FileHandle.nullDevice
    p.standardError = FileHandle.nullDevice
    do {
        try p.run()
        let timer = DispatchSource.makeTimerSource(queue: .global())
        timer.schedule(deadline: .now() + .seconds(timeout))
        timer.setEventHandler {
            if p.isRunning { p.terminate() }
        }
        timer.resume()
        p.waitUntilExit()
        return p.terminationStatus == 0
    } catch {
        return false
    }
}

/// SCP a file to a remote host.
func runSCPFile(localPath: String, remotePath: String, args: [String]) -> (success: Bool, stderr: String?) {
    let p = Process()
    let stderrPipe = Pipe()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/scp")
    p.arguments = args + [localPath, remotePath]
    p.standardOutput = FileHandle.nullDevice
    p.standardError = stderrPipe
    do {
        try p.run()
        p.waitUntilExit()
        let stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
        let stderr = String(data: stderrData, encoding: .utf8)
        return (p.terminationStatus == 0, stderr)
    } catch let error as NSError {
        return (false, "Process error: \(error.localizedDescription)")
    }
}