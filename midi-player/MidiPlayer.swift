import AVFoundation
import AudioToolbox
import Darwin
import Foundation

private let defaultSoundBank = "/System/Library/Components/CoreAudio.component/Contents/Resources/gs_instruments.dls"
private let demoSoundBank = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
    .deletingLastPathComponent().deletingLastPathComponent()
    .appendingPathComponent("soundfonts/GeneralUserGSv1.471.sf2").path

private struct Options {
    var midiPath: String?
    var soundBankPath = FileManager.default.fileExists(atPath: demoSoundBank) ? demoSoundBank : defaultSoundBank
    var program: UInt8 = 4  // Electric Piano 1, as in the Spotify web demo.
    var pitchBends = false
    var rate: Float = 1.0
    var loop = false
    var inspectOnly = false

    static let usage = """
    Usage:
      midi-player <file.mid> [options]

    Options:
      --soundfont <file.sf2|file.dls>  Use a custom SoundFont or DLS sound bank.
      --program <0-127>               General MIDI program (default: 4, electric piano).
      --pitch-bends                    Play predicted bends (off for demo-style preview).
      --rate <0.1-4.0>                Initial playback speed (default: 1.0).
      --loop                          Loop the complete MIDI file.
      --inspect                       Show MIDI information without playing audio.
      -h, --help                      Show this help.

    Interactive commands:
      p                 Pause or resume.
      s <seconds>       Seek to an absolute time.
      r <0.1-4.0>       Change playback speed.
      l                 Toggle looping.
      i                 Show playback status.
      q                 Quit.
    """

    static func parse(_ arguments: [String]) throws -> Options {
        var options = Options()
        var index = 0

        while index < arguments.count {
            let argument = arguments[index]
            switch argument {
            case "-h", "--help":
                print(usage)
                Darwin.exit(EXIT_SUCCESS)
            case "--soundfont":
                index += 1
                guard index < arguments.count else {
                    throw PlayerError.invalidArguments("--soundfont requires a path")
                }
                options.soundBankPath = arguments[index]
            case "--program":
                index += 1
                guard index < arguments.count,
                      let value = Int(arguments[index]),
                      (0...127).contains(value)
                else {
                    throw PlayerError.invalidArguments("--program must be between 0 and 127")
                }
                options.program = UInt8(value)
            case "--rate":
                index += 1
                guard index < arguments.count,
                      let value = Float(arguments[index]),
                      (0.1...4.0).contains(value)
                else {
                    throw PlayerError.invalidArguments("--rate must be between 0.1 and 4.0")
                }
                options.rate = value
            case "--loop":
                options.loop = true
            case "--pitch-bends":
                options.pitchBends = true
            case "--inspect":
                options.inspectOnly = true
            default:
                if argument.hasPrefix("-") {
                    throw PlayerError.invalidArguments("unknown option: \(argument)")
                }
                guard options.midiPath == nil else {
                    throw PlayerError.invalidArguments("only one MIDI file can be opened at a time")
                }
                options.midiPath = argument
            }
            index += 1
        }

        guard options.midiPath != nil else {
            throw PlayerError.invalidArguments("a MIDI file path is required")
        }
        return options
    }
}

private enum PlayerError: LocalizedError {
    case invalidArguments(String)
    case missingFile(String)
    case unsupportedFile(String)
    case emptySequence

    var errorDescription: String? {
        switch self {
        case .invalidArguments(let message):
            return "Invalid arguments: \(message)"
        case .missingFile(let path):
            return "File not found: \(path)"
        case .unsupportedFile(let path):
            return "Expected a .mid or .midi file: \(path)"
        case .emptySequence:
            return "The MIDI file contains no playable tracks."
        }
    }
}

private struct SequenceInfo {
    let trackCount: Int
    let duration: TimeInterval

    static func load(from midiURL: URL) throws -> SequenceInfo {
        let inspectionEngine = AVAudioEngine()
        let sequencer = AVAudioSequencer(audioEngine: inspectionEngine)
        try sequencer.load(from: midiURL, options: [])
        guard !sequencer.tracks.isEmpty else {
            throw PlayerError.emptySequence
        }
        return SequenceInfo(
            trackCount: sequencer.tracks.count,
            duration: sequencer.tracks.map { $0.lengthInSeconds }.max() ?? 0
        )
    }
}

private final class MIDIPlayer {
    private let engine = AVAudioEngine()
    private var samplers: [AVAudioUnitSampler] = []
    private let sequencer: AVAudioSequencer
    private let midiURL: URL
    private let duration: TimeInterval
    private var looping: Bool

    init(options: Options, midiURL: URL, info: SequenceInfo) throws {
        self.midiURL = midiURL
        self.duration = info.duration
        self.looping = options.loop

        let soundBankURL = try validatedFileURL(options.soundBankPath)
        sequencer = AVAudioSequencer(audioEngine: engine)
        try sequencer.load(from: midiURL, options: [])
        sequencer.rate = options.rate

        for track in sequencer.tracks {
            let sampler = AVAudioUnitSampler()
            engine.attach(sampler)
            if #available(macOS 27.0, *) {
                try engine.connectNode(sampler, to: engine.mainMixerNode, format: nil)
            } else {
                engine.connect(sampler, to: engine.mainMixerNode, format: nil)
            }
            try sampler.loadSoundBankInstrument(
                at: soundBankURL,
                program: options.program,
                bankMSB: UInt8(kAUSampler_DefaultMelodicBankMSB),
                bankLSB: UInt8(kAUSampler_DefaultBankLSB)
            )
            // Keep tracks isolated so predicted bends do not share sampler state.
            // The source MIDI is never changed by this preview policy.
            track.enumerateEvents(in: AVMakeBeatRange(0, AVMusicTimeStampEndOfTrack)) { event, _, remove in
                if event is AVMIDIProgramChangeEvent
                    || (!options.pitchBends && event is AVMIDIPitchBendEvent) {
                    remove.pointee = true
                }
                if let control = event as? AVMIDIControlChangeEvent,
                   control.messageType.rawValue == 0 || control.messageType.rawValue == 32 {
                    remove.pointee = true
                }
            }
            track.destinationAudioUnit = sampler
            samplers.append(sampler)
        }
        engine.mainMixerNode.outputVolume = 0.6
        configureLooping(options.loop)

        engine.prepare()
        try engine.start()
        sequencer.prepareToPlay()
        print("Sound bank: \(soundBankURL.lastPathComponent), program: \(options.program), pitch bends: \(options.pitchBends ? "on" : "off")")
    }

    deinit {
        sequencer.stop()
        engine.stop()
    }

    func run() throws {
        try sequencer.start()
        print("Playing \(midiURL.lastPathComponent)")
        showStatus()
        print("Commands: p pause/resume, s <seconds> seek, r <rate> speed, l loop, i info, q quit")

        while true {
            print("> ", terminator: "")
            fflush(stdout)

            guard let line = readLine() else {
                break
            }
            let parts = line.split(whereSeparator: \.isWhitespace).map(String.init)
            guard let command = parts.first?.lowercased() else {
                continue
            }

            switch command {
            case "p", "pause", "play":
                try togglePlayback()
            case "s", "seek":
                seek(parts)
            case "r", "rate":
                setRate(parts)
            case "l", "loop":
                looping.toggle()
                configureLooping(looping)
                print("Loop: \(looping ? "on" : "off")")
            case "i", "info", "status":
                showStatus()
            case "q", "quit", "exit":
                return
            case "h", "help", "?":
                print(Options.usage)
            default:
                print("Unknown command. Enter h for help.")
            }
        }
    }

    private func togglePlayback() throws {
        if sequencer.isPlaying {
            sequencer.stop()
            silence()
            print("Paused at \(formatTime(sequencer.currentPositionInSeconds))")
        } else {
            if duration > 0, sequencer.currentPositionInSeconds >= duration {
                sequencer.currentPositionInSeconds = 0
            }
            sequencer.prepareToPlay()
            try sequencer.start()
            print("Playing from \(formatTime(sequencer.currentPositionInSeconds))")
        }
    }

    private func seek(_ parts: [String]) {
        guard parts.count == 2, let seconds = Double(parts[1]), seconds.isFinite, seconds >= 0 else {
            print("Usage: s <seconds>")
            return
        }
        silence()
        sequencer.currentPositionInSeconds = duration > 0 ? min(seconds, duration) : seconds
        print("Position: \(formatTime(sequencer.currentPositionInSeconds))")
    }

    private func setRate(_ parts: [String]) {
        guard parts.count == 2,
              let rate = Float(parts[1]),
              (0.1...4.0).contains(rate)
        else {
            print("Usage: r <0.1-4.0>")
            return
        }
        sequencer.rate = rate
        print(String(format: "Speed: %.2fx", rate))
    }

    private func configureLooping(_ enabled: Bool) {
        let length = sequencer.tracks.map { $0.lengthInBeats }.max() ?? 0
        for track in sequencer.tracks {
            track.loopRange = AVMakeBeatRange(0, max(length, 0.001))
            track.isLoopingEnabled = enabled
            if enabled {
                track.numberOfLoops = -1
            }
        }
    }

    private func silence() {
        for sampler in samplers {
            for channel: UInt8 in 0..<16 {
                sampler.sendController(120, withValue: 0, onChannel: channel)
            }
        }
    }

    private func showStatus() {
        let state = sequencer.isPlaying ? "playing" : "paused"
        print(
            "Status: \(state), "
                + "\(formatTime(sequencer.currentPositionInSeconds)) / \(formatTime(duration)), "
                + String(format: "%.2fx", sequencer.rate)
                + ", loop \(looping ? "on" : "off")"
        )
    }
}

private func validatedFileURL(_ path: String) throws -> URL {
    let expandedPath = NSString(string: path).expandingTildeInPath
    let url = URL(fileURLWithPath: expandedPath).standardizedFileURL
    var isDirectory: ObjCBool = false
    guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory),
          !isDirectory.boolValue
    else {
        throw PlayerError.missingFile(url.path)
    }
    return url
}

private func validatedMIDIURL(_ path: String) throws -> URL {
    let url = try validatedFileURL(path)
    guard ["mid", "midi"].contains(url.pathExtension.lowercased()) else {
        throw PlayerError.unsupportedFile(url.path)
    }
    return url
}

private func formatTime(_ seconds: TimeInterval) -> String {
    guard seconds.isFinite, seconds >= 0 else {
        return "00:00.0"
    }
    let minutes = Int(seconds) / 60
    let remainder = seconds - Double(minutes * 60)
    return String(format: "%02d:%04.1f", minutes, remainder)
}

do {
    let options = try Options.parse(Array(CommandLine.arguments.dropFirst()))
    let midiURL = try validatedMIDIURL(options.midiPath!)
    let info = try SequenceInfo.load(from: midiURL)

    print("MIDI: \(midiURL.path)")
    print("Tracks: \(info.trackCount)")
    print("Duration: \(formatTime(info.duration))")

    if !options.inspectOnly {
        let player = try MIDIPlayer(options: options, midiURL: midiURL, info: info)
        try player.run()
    }
} catch {
    let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    FileHandle.standardError.write(Data("Error: \(message)\n\n\(Options.usage)\n".utf8))
    Darwin.exit(EXIT_FAILURE)
}
