# macOS MIDI Player

A small native macOS MIDI player for checking the output of `basic_pitch_tab.py`.
It uses AVFoundation. When `soundfonts/GeneralUserGSv1.471.sf2` is present, it
uses the same sound bank as Spotify's web demo. Otherwise it falls back to the
General MIDI sound bank bundled with macOS. No Homebrew or Python is required.

The default is Electric Piano 1 (program 4) with predicted pitch bends disabled
for a stable diagnostic preview. This matches the note-only MIDI playback path
observed in the Spotify demo on 2026-10-27. The synthesizer is still Apple's
sampler, not FluidSynth, so rendering is not guaranteed to sound identical.
Program/bank changes in the MIDI are ignored for consistent A/B comparisons;
each track has its own sampler. Input MIDI files are never modified.

## Requirements

- macOS 13 or newer (the current source was built with the macOS 27 SDK)
- Xcode Command Line Tools (`xcode-select --install`)

## Build

```sh
cd midi-player
make build
```

The executable is written to `midi-player/.build/midi-player`.

## Inspect a MIDI file without playing it

```sh
make inspect MIDI="../basic_pitch_output/example.mid"
```

## Play

```sh
make run MIDI="../basic_pitch_output/example.mid"
```

Or invoke the executable directly:

```sh
.build/midi-player ../basic_pitch_output/example.mid --rate 1.0 --loop

# Compare the original predicted bends; this can reveal bend-estimation jitter.
.build/midi-player ../basic_pitch_output/example.mid --pitch-bends

# Compare with clean guitar instead of the default electric piano.
.build/midi-player ../basic_pitch_output/example.mid --program 27
```

While it is running, enter:

- `p` to pause or resume
- `s 30` to seek to 30 seconds
- `r 0.75` to use 75% playback speed
- `l` to toggle looping
- `i` to show the current status
- `q` to quit

Pass `--soundfont /path/to/file.sf2` to test with a custom SF2 or DLS sound
bank. General MIDI program numbers are zero-based; useful guitar programs are
24 (nylon), 25 (steel), 26 (jazz), 27 (clean), and 29 (overdriven).

For noise filtering and TAB-constrained MIDI output, see
[`../docs/midi-refinement.md`](../docs/midi-refinement.md).
