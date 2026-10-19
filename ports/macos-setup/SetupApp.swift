// AC-Recomp Setup: a self-guided builder for macOS. It checks the prerequisites, asks for the player's own dump and
// keys (paths only), and runs tools/acr_build.py from the kit bundled in Contents/Resources/kit with a live log.
// Built by scripts/make_dmg.py with swiftc; no Xcode project. The command line is assembled by
// tools/acr_setup_cmd.py (unit-tested), so this file only gathers choices and shows progress.
import AppKit
import CoreText
import SwiftUI

// MARK: - Paths

enum Paths {
    static let fm = FileManager.default
    static var home: URL { fm.homeDirectoryForCurrentUser }
    static var support: URL { home.appendingPathComponent("AC-Recomp", isDirectory: true) }
    static var kitCopy: URL { support.appendingPathComponent("kit", isDirectory: true) }
    static var defaultOut: URL { support.appendingPathComponent("build", isDirectory: true) }
    static var buildLog: URL { support.appendingPathComponent("setup-build.log") }

    /// The bundled kit (Contents/Resources/kit). ACR_SETUP_KIT overrides it for development.
    static var kit: URL {
        if let dev = ProcessInfo.processInfo.environment["ACR_SETUP_KIT"], !dev.isEmpty {
            return URL(fileURLWithPath: dev, isDirectory: true)
        }
        return Bundle.main.resourceURL!.appendingPathComponent("kit", isDirectory: true)
    }
    static var helper: URL { kit.appendingPathComponent("tools/acr_setup_cmd.py") }
    static var launcherAssets: URL { kit.appendingPathComponent("assets/launcher", isDirectory: true) }

    /// A Python able to run the helper (3.9 is enough). /usr/bin/python3 is only real once the CLT are installed.
    static func helperPython(cltInstalled: Bool) -> String? {
        for p in ["/opt/homebrew/bin/python3", "/usr/local/bin/python3"] where fm.isExecutableFile(atPath: p) {
            return p
        }
        return cltInstalled ? "/usr/bin/python3" : nil
    }
}

// MARK: - Process helpers

@discardableResult
func runCapture(_ exe: String, _ args: [String]) -> (Int32, String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: exe)
    p.arguments = args
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = Pipe()
    do { try p.run() } catch { return (-1, "") }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return (p.terminationStatus, String(decoding: data, as: UTF8.self))
}

// MARK: - Model

struct Prereq: Codable, Identifiable {
    let id: String
    let title: String
    let ok: Bool
    let required: Bool
    let detail: String
    let fix: String
}

enum Step: Int, CaseIterable {
    case welcome, prereqs, files, options, build, done
    var title: String {
        switch self {
        case .welcome: return "Welcome"
        case .prereqs: return "Prerequisites"
        case .files: return "Game files"
        case .options: return "Options"
        case .build: return "Build"
        case .done: return "Done"
        }
    }
}

let stageNames = ["preflight", "workspace", "upstream", "toolchain", "import", "control", "lift", "shaders",
                  "runtime", "build", "fonts", "data", "app"]

enum BuildState: Equatable { case idle, running, cancelling, failed(Int32), finished }

final class Model: ObservableObject {
    @Published var step: Step = .welcome
    @Published var accepted = false
    @Published var prereqs: [Prereq] = []
    @Published var checking = false
    @Published var cltInstalled = false

    @Published var nsp = UserDefaults.standard.string(forKey: "nsp") ?? "" { didSet { save("nsp", nsp) } }
    @Published var keys = UserDefaults.standard.string(forKey: "keys") ?? "" { didSet { save("keys", keys) } }
    @Published var titleKeys = UserDefaults.standard.string(forKey: "titleKeys") ?? "" {
        didSet { save("titleKeys", titleKeys) } }
    @Published var fonts = UserDefaults.standard.string(forKey: "fonts") ?? "" { didSet { save("fonts", fonts) } }
    @Published var out = UserDefaults.standard.string(forKey: "out") ?? Paths.defaultOut.path {
        didSet { save("out", out) } }
    @Published var renderRes = UserDefaults.standard.string(forKey: "renderRes") ?? "" {
        didSet { save("renderRes", renderRes) } }

    @Published var log: [String] = []
    @Published var state: BuildState = .idle
    @Published var stageIndex = 0
    @Published var stageName = ""
    @Published var stagesDone = Set<String>()
    @Published var movedApp: String?

    private var process: Process?
    private var buffer = Data()
    private var logHandle: FileHandle?

    init() {
        if let page = ProcessInfo.processInfo.environment["ACR_SETUP_PAGE"], let n = Int(page),
           let s = Step(rawValue: n) {
            step = s
            accepted = n > 0
        }
        if ProcessInfo.processInfo.environment["ACR_SETUP_AUTOSTART"] == "1" {
            DispatchQueue.main.async { self.startBuild() }
        }
    }

    private func save(_ key: String, _ value: String) { UserDefaults.standard.set(value, forKey: key) }

    var appPath: String { (out as NSString).appendingPathComponent("AC-Recomp.app") }
    var prereqsOK: Bool { !prereqs.isEmpty && prereqs.allSatisfy { $0.ok || !$0.required } }
    var filesOK: Bool { fileError == nil }
    /// The build folder must not be, contain or sit inside a kit folder (refreshing the kit deletes that folder).
    /// tools/acr_setup_cmd.py refuses the same overlap.
    var outError: String? {
        let o = URL(fileURLWithPath: (out as NSString).expandingTildeInPath).standardizedFileURL.resolvingSymlinksInPath().path
        if out.isEmpty { return "Choose a build folder." }
        for kit in [Paths.kitCopy, Paths.kit] {
            let k = kit.standardizedFileURL.resolvingSymlinksInPath().path
            if o == k || o.hasPrefix(k + "/") || k.hasPrefix(o + "/") {
                return "The build folder must not be, contain or be inside the setup kit folder (\(k))."
            }
        }
        return nil
    }

    var fileError: String? {
        let fm = FileManager.default
        if nsp.isEmpty { return "Choose your Astral Chain 1.0.0 NSP." }
        if !fm.fileExists(atPath: nsp) { return "The NSP no longer exists at that path." }
        if (nsp as NSString).pathExtension.lowercased() != "nsp" { return "Only .nsp dumps are supported." }
        if keys.isEmpty { return "Choose your keys file." }
        if !fm.fileExists(atPath: keys) { return "The keys file no longer exists at that path." }
        if !titleKeys.isEmpty && !fm.fileExists(atPath: titleKeys) { return "The title keys file no longer exists." }
        var dir: ObjCBool = false
        if !fonts.isEmpty && !(fm.fileExists(atPath: fonts, isDirectory: &dir) && dir.boolValue) {
            return "The fonts folder no longer exists."
        }
        return nil
    }

    // Prerequisites
    func refresh() {
        checking = true
        DispatchQueue.global(qos: .userInitiated).async {
            let clt = runCapture("/usr/bin/xcode-select", ["-p"]).0 == 0
            var rows: [Prereq] = []
            if let py = Paths.helperPython(cltInstalled: clt) {
                let (code, text) = runCapture(py, [Paths.helper.path, "check"])
                if code == 0, let decoded = try? JSONDecoder().decode([Prereq].self, from: Data(text.utf8)) {
                    rows = decoded
                }
            }
            if rows.isEmpty {
                rows = [Prereq(id: "clt", title: "Xcode Command Line Tools", ok: clt, required: true,
                               detail: clt ? "installed" : "not installed; install these first, then Check again",
                               fix: "xcode-select --install")]
            }
            DispatchQueue.main.async {
                self.cltInstalled = clt
                self.prereqs = rows
                self.checking = false
            }
        }
    }

    func install(_ row: Prereq) {
        if row.id == "clt" {
            // Apple's own installer dialog; no Terminal needed.
            _ = try? Process.run(URL(fileURLWithPath: "/usr/bin/xcode-select"), arguments: ["--install"])
            return
        }
        let alert = NSAlert()
        alert.messageText = "Install \(row.title)?"
        alert.informativeText = "Terminal will open and run:\n\n\(row.fix)\n\nIt may ask for your password. " +
            "When it finishes, come back here and press Check again."
        alert.addButton(withTitle: "Open Terminal")
        alert.addButton(withTitle: "Copy Command")
        alert.addButton(withTitle: "Cancel")
        switch alert.runModal() {
        case .alertFirstButtonReturn: openInTerminal(row.fix)
        case .alertSecondButtonReturn:
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(row.fix, forType: .string)
        default: break
        }
    }

    private func openInTerminal(_ command: String) {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("ac-recomp-setup", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let file = dir.appendingPathComponent("install-\(UUID().uuidString.prefix(8)).command")
        let script = """
        #!/bin/bash
        echo 'AC-Recomp Setup will run:'
        echo '  \(command.replacingOccurrences(of: "'", with: "'\\''"))'
        echo
        \(command)
        status=$?
        echo
        if [ $status -eq 0 ]; then echo 'Done. Return to AC-Recomp Setup and press Check again.'; \
        else echo "The command failed (exit $status)."; fi
        rm -f "$0"
        """
        try? script.write(to: file, atomically: true, encoding: .utf8)
        try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: file.path)
        NSWorkspace.shared.open([file], withApplicationAt: URL(fileURLWithPath: "/System/Applications/Utilities/Terminal.app"),
                                configuration: NSWorkspace.OpenConfiguration(), completionHandler: nil)
    }

    // Build
    func helperArgs(_ sub: String) -> [String] {
        var a = [Paths.helper.path, sub, "--nsp", nsp, "--keys", keys, "--out", out, "--kit", Paths.kitCopy.path]
        if !titleKeys.isEmpty { a += ["--title-keys", titleKeys] }
        if !fonts.isEmpty { a += ["--fonts", fonts] }
        if !renderRes.isEmpty { a += ["--render-res", renderRes] }
        if ProcessInfo.processInfo.environment["ACR_SETUP_DRY_RUN"] == "1" { a.append("--dry-run") }
        return a
    }

    func startBuild() {
        guard process == nil, let py = Paths.helperPython(cltInstalled: true) else { return }
        log = []
        stagesDone = []
        stageIndex = 0
        stageName = ""
        state = .running
        try? FileManager.default.createDirectory(at: Paths.support, withIntermediateDirectories: true)
        // Appended, so a resumed build keeps the earlier run's log.
        if !FileManager.default.fileExists(atPath: Paths.buildLog.path) {
            FileManager.default.createFile(atPath: Paths.buildLog.path, contents: nil)
        }
        logHandle = try? FileHandle(forWritingTo: Paths.buildLog)
        logHandle?.seekToEndOfFile()
        logHandle?.write(Data("\n=== AC-Recomp Setup build started \(Date()) ===\n".utf8))
        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = helperArgs("run")
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        p.environment = env
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        outputClosed = false
        exitStatus = nil
        pipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let data = h.availableData
            if data.isEmpty {
                h.readabilityHandler = nil
                DispatchQueue.main.async { self?.outputClosed = true; self?.finishIfDone() }
                return
            }
            DispatchQueue.main.async { self?.consume(data) }
        }
        p.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async {
                self?.exitStatus = proc.terminationStatus
                self?.finishIfDone()
                // The last lines (often the error) arrive at end of output; a stray child holding the pipe open
                // must not keep the page in "running" forever.
                DispatchQueue.main.asyncAfter(deadline: .now() + 3) { self?.outputClosed = true; self?.finishIfDone() }
            }
        }
        do {
            try p.run()
            process = p
            currentBuildPID = p.processIdentifier
            append("Building in \(out)")
        } catch {
            append("could not start the build: \(error.localizedDescription)")
            state = .failed(-1)
        }
    }

    func cancel() {
        guard let p = process, p.isRunning else { return }
        state = .cancelling
        append("Cancelling... finished stages are kept; Resume continues from here.")
        // The helper makes the build its own process group, so the whole tree (compilers too) gets the signal.
        kill(-p.processIdentifier, SIGINT)
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) { [weak self] in
            if let p = self?.process, p.isRunning { kill(-p.processIdentifier, SIGTERM) }
        }
    }

    private var outputClosed = false
    private var exitStatus: Int32?

    private func finishIfDone() {
        guard process != nil, outputClosed, let status = exitStatus else { return }
        finished(status)
    }

    private func consume(_ data: Data) {
        logHandle?.write(data)
        buffer.append(data)
        while let nl = buffer.firstIndex(of: 0x0A) {
            let line = String(decoding: buffer[buffer.startIndex..<nl], as: UTF8.self)
            buffer.removeSubrange(buffer.startIndex...nl)
            append(line)
        }
    }

    private func append(_ line: String) {
        parseStage(line)
        log.append(line)
        if log.count > 4000 { log.removeFirst(log.count - 3000) }
    }

    /// Lines like "[7/13] lift: recompile main ..." from tools/acr_build.py.
    func parseStage(_ line: String) {
        guard line.hasPrefix("["), let close = line.firstIndex(of: "]") else { return }
        let nums = line[line.index(after: line.startIndex)..<close].split(separator: "/")
        guard nums.count == 2, let i = Int(nums[0]) else { return }
        let rest = line[line.index(after: close)...].trimmingCharacters(in: .whitespaces)
        guard let colon = rest.firstIndex(of: ":") else { return }
        let name = String(rest[..<colon])
        guard stageNames.contains(name) else { return }
        if !stageName.isEmpty { stagesDone.insert(stageName) }
        stageIndex = i
        stageName = name
        if rest.contains("already done") { stagesDone.insert(name) }
    }

    private func finished(_ status: Int32) {
        if let rest = pipeRemainder() { append(rest) }
        try? logHandle?.close()
        logHandle = nil
        process = nil
        currentBuildPID = 0
        if status == 0 {
            stagesDone = Set(stageNames)
            state = .finished
            append("Finished. Your app is at \(appPath)")
            step = .done
        } else {
            let cancelled = state == .cancelling
            state = .failed(status)
            append(cancelled ? "Cancelled. Press Resume to continue; finished stages are skipped." :
                   "The build stopped (exit \(status)). Fix what the message above says, then press Resume.")
        }
    }

    private func pipeRemainder() -> String? {
        guard !buffer.isEmpty else { return nil }
        defer { buffer.removeAll() }
        return String(decoding: buffer, as: UTF8.self)
    }

    // Done
    func openApp() { NSWorkspace.shared.open(URL(fileURLWithPath: movedApp ?? appPath)) }

    func moveToApplications() {
        let fm = FileManager.default
        let system = URL(fileURLWithPath: "/Applications")
        let dest = (fm.isWritableFile(atPath: system.path) ? system
                    : Paths.home.appendingPathComponent("Applications", isDirectory: true))
        do {
            try fm.createDirectory(at: dest, withIntermediateDirectories: true)
            let target = dest.appendingPathComponent("AC-Recomp.app")
            if fm.fileExists(atPath: target.path) { try fm.trashItem(at: target, resultingItemURL: nil) }
            try fm.moveItem(at: URL(fileURLWithPath: appPath), to: target)
            movedApp = target.path
            NSWorkspace.shared.activateFileViewerSelecting([target])
        } catch {
            let alert = NSAlert(error: error)
            alert.runModal()
        }
    }
}

// MARK: - Look

enum Theme {
    static var titleFontName: String = "Helvetica-Bold"
    static let accent = Color(red: 0.36, green: 0.78, blue: 1.0)
    static let panel = Color.black.opacity(0.55)

    static func registerFonts() {
        let url = Paths.launcherAssets.appendingPathComponent("Baloo2-Bold.ttf")
        CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
        if let descs = CTFontManagerCreateFontDescriptorsFromURL(url as CFURL) as? [CTFontDescriptor],
           let first = descs.first,
           let name = CTFontDescriptorCopyAttribute(first, kCTFontNameAttribute) as? String {
            titleFontName = name
        }
    }

    static func title(_ size: CGFloat) -> Font { .custom(titleFontName, size: size) }
}

struct Background: View {
    var body: some View {
        GeometryReader { geo in
            ZStack {
                if let img = NSImage(contentsOf: Paths.launcherAssets.appendingPathComponent("title-bg.jpg")) {
                    Image(nsImage: img).resizable().aspectRatio(contentMode: .fill)
                        .frame(width: geo.size.width, height: geo.size.height).clipped()
                }
                LinearGradient(colors: [Color.black.opacity(0.62), Color.black.opacity(0.86)],
                               startPoint: .top, endPoint: .bottom)
            }
        }
        .ignoresSafeArea()
    }
}

struct PrimaryButton: ButtonStyle {
    var enabled = true
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.title(17))
            .padding(.horizontal, 22).padding(.vertical, 7)
            .background(RoundedRectangle(cornerRadius: 9)
                .fill(enabled ? Theme.accent.opacity(configuration.isPressed ? 0.7 : 0.95) : Color.gray.opacity(0.35)))
            .foregroundColor(enabled ? .black : .white.opacity(0.5))
    }
}

struct SecondaryButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold))
            .padding(.horizontal, 14).padding(.vertical, 6)
            .background(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.45)))
            .background(RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(configuration.isPressed ? 0.2 : 0.06)))
            .foregroundColor(.white)
    }
}

// MARK: - Views

struct ContentView: View {
    @EnvironmentObject var m: Model

    var body: some View {
        ZStack {
            Background()
            HStack(spacing: 0) {
                Sidebar().frame(width: 200)
                VStack(alignment: .leading, spacing: 0) {
                    page.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    NavBar()
                }
                .padding(28)
                .background(RoundedRectangle(cornerRadius: 16).fill(Theme.panel))
                .padding(.vertical, 22).padding(.trailing, 22)
            }
        }
        .foregroundColor(.white)
        .frame(minWidth: 900, minHeight: 620)
        .preferredColorScheme(.dark)
    }

    @ViewBuilder var page: some View {
        switch m.step {
        case .welcome: WelcomePage()
        case .prereqs: PrereqPage()
        case .files: FilesPage()
        case .options: OptionsPage()
        case .build: BuildPage()
        case .done: DonePage()
        }
    }
}

struct Sidebar: View {
    @EnvironmentObject var m: Model
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                if let icon = NSImage(contentsOf: Paths.launcherAssets.appendingPathComponent("AC-Recomp.png")) {
                    Image(nsImage: icon).resizable().frame(width: 42, height: 42).cornerRadius(9)
                }
                VStack(alignment: .leading, spacing: -4) {
                    Text("AC-Recomp").font(Theme.title(22))
                    Text("Setup").font(Theme.title(15)).foregroundColor(Theme.accent)
                }
            }
            .padding(.bottom, 18)
            ForEach(Step.allCases, id: \.rawValue) { s in
                HStack(spacing: 10) {
                    ZStack {
                        Circle().fill(s.rawValue < m.step.rawValue ? Theme.accent :
                                      s == m.step ? Color.white : Color.white.opacity(0.18))
                            .frame(width: 22, height: 22)
                        if s.rawValue < m.step.rawValue {
                            Image(systemName: "checkmark").font(.system(size: 11, weight: .bold)).foregroundColor(.black)
                        } else {
                            Text("\(s.rawValue + 1)").font(.system(size: 11, weight: .bold))
                                .foregroundColor(s == m.step ? .black : .white.opacity(0.7))
                        }
                    }
                    Text(s.title).font(Theme.title(16))
                        .foregroundColor(s == m.step ? .white : .white.opacity(0.6))
                }
            }
            Spacer()
            Text("v" + ((Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String) ?? "dev")).font(.system(size: 11)).foregroundColor(.white.opacity(0.45))
        }
        .padding(.top, 34).padding(.leading, 24).padding(.bottom, 24)
        .frame(maxHeight: .infinity, alignment: .topLeading)
    }
}

struct NavBar: View {
    @EnvironmentObject var m: Model
    var body: some View {
        HStack {
            if m.step != .welcome && m.step != .done && m.state != .running && m.state != .cancelling {
                Button("Back") { m.step = Step(rawValue: m.step.rawValue - 1)! }.buttonStyle(SecondaryButton())
            }
            Spacer()
            switch m.step {
            case .welcome:
                Button("Continue") { m.step = .prereqs; m.refresh() }
                    .buttonStyle(PrimaryButton(enabled: m.accepted)).disabled(!m.accepted)
            case .prereqs:
                Button("Continue") { m.step = .files }
                    .buttonStyle(PrimaryButton(enabled: m.prereqsOK)).disabled(!m.prereqsOK)
            case .files:
                Button("Continue") { m.step = .options }
                    .buttonStyle(PrimaryButton(enabled: m.filesOK)).disabled(!m.filesOK)
            case .options:
                Button("Continue") { m.step = .build }
                    .buttonStyle(PrimaryButton(enabled: m.outError == nil)).disabled(m.outError != nil)
            case .build, .done:
                EmptyView()
            }
        }
        .padding(.top, 14)
    }
}

struct PageTitle: View {
    let title: String
    let subtitle: String
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(Theme.title(32))
            Text(subtitle).font(.system(size: 14)).foregroundColor(.white.opacity(0.75))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.bottom, 18)
    }
}

struct WelcomePage: View {
    @EnvironmentObject var m: Model
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            PageTitle(title: "Welcome to AC-Recomp",
                      subtitle: "This assistant builds AC-Recomp, a native macOS recompilation of Astral Chain, on " +
                                "your own Mac from your own copy of the game.")
            Bullet(icon: "shippingbox", text: "Nothing from the game is included: no code, data, shaders, fonts, " +
                   "keys or firmware. This app holds only the open-source build tools.")
            Bullet(icon: "opticaldisc", text: "You need your own legally dumped Astral Chain 1.0.0 (base game, no " +
                   "update) as an NSP, and your own console's keys (and title keys if your dump needs them).")
            Bullet(icon: "lock.shield", text: "Your key files are passed to the build tool by path only; this app " +
                   "never opens, copies or uploads them.")
            Bullet(icon: "clock", text: "The first build needs about 25 GB of free space, an internet connection " +
                   "and 30 to 90 minutes. You can cancel and resume at any time.")
            Bullet(icon: "exclamationmark.triangle", text: "You are responsible for the game, keys and system " +
                   "files you supply. Do not share anything the build produces. Not affiliated with Nintendo or " +
                   "PlatinumGames. Early preview: expect crashes.")
            Toggle(isOn: $m.accepted) {
                Text("I own the game and will use my own legally obtained dump and keys.")
                    .font(.system(size: 13, weight: .semibold))
            }
            .toggleStyle(.checkbox)
            .padding(.top, 8)
        }
    }
}

struct Bullet: View {
    let icon: String
    let text: String
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon).font(.system(size: 16)).foregroundColor(Theme.accent).frame(width: 22)
            Text(text).font(.system(size: 13.5)).fixedSize(horizontal: false, vertical: true)
        }
    }
}

struct PrereqPage: View {
    @EnvironmentObject var m: Model
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            PageTitle(title: "Prerequisites",
                      subtitle: "The build uses Apple's command-line tools, Homebrew libraries and the .NET 10 SDK. " +
                                "Install anything missing (top to bottom), then press Check again.")
            if m.prereqs.isEmpty {
                HStack { ProgressView().controlSize(.small); Text("Checking...") }
            }
            ForEach(m.prereqs) { row in
                HStack(spacing: 12) {
                    Image(systemName: row.ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .font(.system(size: 20)).foregroundColor(row.ok ? .green : .orange)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(row.title).font(.system(size: 14, weight: .semibold))
                        Text(row.detail).font(.system(size: 12)).foregroundColor(.white.opacity(0.65))
                            .lineLimit(2).truncationMode(.middle)
                    }
                    Spacer()
                    if !row.ok {
                        Button("Install") { m.install(row) }.buttonStyle(SecondaryButton())
                    }
                }
                .padding(.vertical, 8).padding(.horizontal, 12)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color.white.opacity(0.06)))
            }
            HStack {
                Button(m.checking ? "Checking..." : "Check again") { m.refresh() }
                    .buttonStyle(SecondaryButton()).disabled(m.checking)
                if !m.prereqs.isEmpty && !m.prereqsOK {
                    Text("Installs open in Terminal so you can see and approve every command.")
                        .font(.system(size: 12)).foregroundColor(.white.opacity(0.6))
                    Spacer()
                    Button("Skip (advanced)") { m.step = .files }
                        .buttonStyle(.link).font(.system(size: 12))
                        .help("Continue anyway; the build's own preflight check still stops on anything missing.")
                }
            }
            .padding(.top, 6)
        }
        .onAppear { if m.prereqs.isEmpty { m.refresh() } }
    }
}

struct PathRow: View {
    let label: String
    let hint: String
    @Binding var path: String
    var directory = false
    var optional = false
    var types: [String] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(label).font(.system(size: 14, weight: .semibold))
                if optional { Text("optional").font(.system(size: 11)).foregroundColor(.white.opacity(0.5)) }
            }
            HStack {
                Text(path.isEmpty ? "Not chosen" : path)
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundColor(path.isEmpty ? .white.opacity(0.45) : .white)
                    .lineLimit(1).truncationMode(.middle)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 10).padding(.vertical, 6)
                    .background(RoundedRectangle(cornerRadius: 7).fill(Color.white.opacity(0.07)))
                Button("Choose...") { choose() }.buttonStyle(SecondaryButton())
                if optional && !path.isEmpty {
                    Button("Clear") { path = "" }.buttonStyle(SecondaryButton())
                }
            }
            Text(hint).font(.system(size: 11.5)).foregroundColor(.white.opacity(0.6))
        }
    }

    func choose() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = !directory
        panel.canChooseDirectories = directory
        panel.canCreateDirectories = directory
        panel.allowsMultipleSelection = false
        panel.message = label
        if !path.isEmpty { panel.directoryURL = URL(fileURLWithPath: (path as NSString).deletingLastPathComponent) }
        if panel.runModal() == .OK, let url = panel.url { path = url.path }
    }
}

struct FilesPage: View {
    @EnvironmentObject var m: Model
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            PageTitle(title: "Your game files",
                      subtitle: "Choose your own dump and keys. Only their paths are passed to the build tool.")
            PathRow(label: "Astral Chain 1.0.0 (.nsp)", hint: "Base game, no update. XCI dumps must be converted first.",
                    path: $m.nsp)
            PathRow(label: "Keys", hint: "From your own console.", path: $m.keys)
            PathRow(label: "Title keys", hint: "Only if your dump needs it.", path: $m.titleKeys, optional: true)
            PathRow(label: "Shared fonts folder", hint: "The six .bfttf files from your own console's firmware. " +
                    "Without it, open-licensed Noto Sans replacements are used (no button icons or CJK text).",
                    path: $m.fonts, directory: true, optional: true)
            if let e = m.fileError, !m.nsp.isEmpty || !m.keys.isEmpty {
                Text(e).font(.system(size: 12, weight: .semibold)).foregroundColor(.orange)
            }
        }
    }
}

struct OptionsPage: View {
    @EnvironmentObject var m: Model
    let resolutions = [("", "Stock (1600x900)"), ("1920x1080", "1920x1080"), ("2560x1440", "2560x1440"),
                       ("3200x1800", "3200x1800"), ("3840x2160", "3840x2160")]
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PageTitle(title: "Options", subtitle: "The defaults are right for most players.")
            PathRow(label: "Build folder", hint: "About 25 GB. AC-Recomp.app reads your imported game files and " +
                    "keeps your saves here, by absolute path: keep this folder after setup.",
                    path: $m.out, directory: true)
            HStack {
                Button("Use default") { m.out = Paths.defaultOut.path }.buttonStyle(SecondaryButton())
                Text(Paths.defaultOut.path).font(.system(size: 11, design: .monospaced))
                    .foregroundColor(.white.opacity(0.5)).lineLimit(1).truncationMode(.middle)
            }
            if m.out.contains(" ") {
                Text("This path contains spaces. The build is only tested in folders without spaces; the " +
                     "default is safest.")
                    .font(.system(size: 12, weight: .semibold)).foregroundColor(.orange)
            }
            if let e = m.outError {
                Text(e).font(.system(size: 12, weight: .semibold)).foregroundColor(.orange)
            }
            Divider().background(Color.white.opacity(0.3))
            Text("Experimental").font(Theme.title(20))
            VStack(alignment: .leading, spacing: 2) {
                Text("60 fps").font(.system(size: 13, weight: .semibold))
                Text("Both frame rates are built. Choose 30 or 60 fps later in AC-Recomp's Settings (Frame rate); " +
                     "60 fps is experimental.")
                    .font(.system(size: 11.5)).foregroundColor(.white.opacity(0.6))
            }
            HStack {
                Text("Render resolution").font(.system(size: 13, weight: .semibold))
                Picker("", selection: $m.renderRes) {
                    ForEach(resolutions, id: \.0) { r in Text(r.1).tag(r.0) }
                }
                .labelsHidden().frame(width: 200)
            }
            Text("Higher internal resolutions are tested through the opening only and use more memory.")
                .font(.system(size: 11.5)).foregroundColor(.white.opacity(0.6))
        }
    }
}

struct BuildPage: View {
    @EnvironmentObject var m: Model
    var progress: Double { Double(m.stagesDone.count) / Double(stageNames.count) }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            PageTitle(title: "Build", subtitle: statusText)
            ProgressView(value: progress).tint(Theme.accent)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 74), spacing: 6)], alignment: .leading, spacing: 6) {
                ForEach(stageNames, id: \.self) { s in
                    Text(s)
                        .font(.system(size: 10.5, weight: .semibold))
                        .padding(.horizontal, 6).padding(.vertical, 3)
                        .background(Capsule().fill(m.stagesDone.contains(s) ? Theme.accent.opacity(0.85) :
                                                   s == m.stageName && m.state == .running ? Color.white.opacity(0.35) :
                                                   Color.white.opacity(0.08)))
                        .foregroundColor(m.stagesDone.contains(s) ? .black : .white)
                }
            }
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 1) {
                        ForEach(Array(m.log.enumerated()), id: \.offset) { i, line in
                            Text(line).font(.system(size: 11, design: .monospaced))
                                .foregroundColor(line.hasPrefix("error") ? .orange : .white.opacity(0.85))
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading).id(i)
                        }
                    }
                    .padding(8)
                }
                .background(RoundedRectangle(cornerRadius: 8).fill(Color.black.opacity(0.55)))
                .onChange(of: m.log.count) { n in if n > 0 { proxy.scrollTo(n - 1, anchor: .bottom) } }
            }
            HStack {
                switch m.state {
                case .running:
                    Button("Cancel") { m.cancel() }.buttonStyle(SecondaryButton())
                case .cancelling:
                    HStack { ProgressView().controlSize(.small); Text("Cancelling...") }
                case .idle:
                    Button("Start build") { m.startBuild() }.buttonStyle(PrimaryButton())
                case .failed:
                    Button("Resume") { m.startBuild() }.buttonStyle(PrimaryButton())
                case .finished:
                    Button("Continue") { m.step = .done }.buttonStyle(PrimaryButton())
                }
                Spacer()
                Button("Show log file") { NSWorkspace.shared.activateFileViewerSelecting([Paths.buildLog]) }
                    .buttonStyle(SecondaryButton())
            }
        }
    }

    var statusText: String {
        switch m.state {
        case .idle: return "Ready. Finished stages from an earlier run are skipped, so this also resumes a build."
        case .running: return m.stageName.isEmpty ? "Starting..." :
            "Stage \(m.stageIndex) of \(stageNames.count): \(m.stageName)"
        case .cancelling: return "Stopping after the current step..."
        case .failed(let c): return "Stopped (exit \(c)). Read the last lines below, fix the problem, then Resume."
        case .finished: return "Finished."
        }
    }
}

struct DonePage: View {
    @EnvironmentObject var m: Model
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PageTitle(title: "AC-Recomp is ready", subtitle: "Your build is at \(m.movedApp ?? m.appPath).")
            HStack(spacing: 12) {
                Button("Open AC-Recomp") { m.openApp() }.buttonStyle(PrimaryButton())
                if m.movedApp == nil {
                    Button("Move to Applications") { m.moveToApplications() }.buttonStyle(SecondaryButton())
                }
                Button("Show build folder") {
                    NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: m.out)])
                }.buttonStyle(SecondaryButton())
            }
            Bullet(icon: "externaldrive", text: "Keep the build folder: the app reads your game files and saves " +
                   "from \(m.out)/data.")
            Bullet(icon: "hand.raised", text: "Everything the build produced comes from your own dump. Do not " +
                   "share the app or the build folder.")
            Bullet(icon: "arrow.clockwise", text: "To change options or update, open AC-Recomp Setup again and " +
                   "build into the same folder; finished stages are reused.")
        }
    }
}

// MARK: - App

/// The running build's process group leader, so quitting the app also stops the build (it resumes next time).
var currentBuildPID: pid_t = 0

final class AppDelegate: NSObject, NSApplicationDelegate {
    // Mid-build, closing the window keeps the build running; the Dock icon brings the window back.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { currentBuildPID == 0 }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard currentBuildPID > 0 else { return .terminateNow }
        let alert = NSAlert()
        alert.messageText = "Stop the build and quit?"
        alert.informativeText = "Finished stages are kept; open AC-Recomp Setup again and press Start build to " +
            "continue from where it stopped."
        alert.addButton(withTitle: "Keep Building")
        alert.addButton(withTitle: "Stop and Quit")
        return alert.runModal() == .alertSecondButtonReturn ? .terminateNow : .terminateCancel
    }

    func applicationWillTerminate(_ notification: Notification) {
        if currentBuildPID > 0 { kill(-currentBuildPID, SIGINT) }
    }
}

@main
struct SetupApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = Model()

    init() { Theme.registerFonts() }

    var body: some Scene {
        WindowGroup("AC-Recomp Setup") {
            ContentView().environmentObject(model)
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentSize)
    }
}
