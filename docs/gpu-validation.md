# GPU workstation validation

Milestone 7 separates historical performance evidence from the five-stem product
acceptance run. A run is complete only when its MVSep manifest contains all five
product stems and both guitar stems have non-empty Basic Pitch TAB JSON files.

## Recorded baseline: RTX 5090, two guitar heads

The following full-song run was reported from the workstation on 2026-10-27. It
is a useful capacity baseline, but it is not the five-stem acceptance run.

| Item | Observed value |
|---|---:|
| Input | `Gummy B - 石橋 (Official Audio).mp3` |
| Duration | 220.47 s |
| Selected heads | `acoustic-guitar`, `electric-guitar` |
| GPU | NVIDIA GeForce RTX 5090, 31.4 GiB |
| Runtime | Python 3.11.14, torch 2.11.0+cu130, CUDA 13.0, msst 0.1.0 |
| Model load | 13.44 s |
| Separation | 6.60 s |
| Real-time factor | 0.030 |
| Peak CUDA allocated | 1.42 GiB |
| Peak CUDA reserved | 1.78 GiB |

The target `gpu-worker` image remains Python 3.10, so its final smoke test must
be recorded separately rather than treating the Python 3.11 result as image
compatibility proof.

## Five-stem full-song acceptance run

Run from the repository root on the NVIDIA workstation:

```sh
INPUT='downloads/Gummy B - 石橋 (Official Audio).mp3'
OUTPUT='mvsep_output/Gummy B - 石橋 (Official Audio)'

python infer_mvsep_mega.py "$INPUT" --overwrite \
  --stems acoustic-guitar electric-guitar bass drums vocal

python basic_pitch_tab.py "$OUTPUT/acoustic-guitar.wav" \
  --output "$OUTPUT/acoustic-guitar.tab.json" \
  --midi-output "$OUTPUT/acoustic-guitar.mid"

python basic_pitch_tab.py "$OUTPUT/electric-guitar.wav" \
  --output "$OUTPUT/electric-guitar.tab.json" \
  --midi-output "$OUTPUT/electric-guitar.mid"

python validate_gpu_smoke.py "$OUTPUT/manifest.json" --require-tabs \
  --tab acoustic-guitar="$OUTPUT/acoustic-guitar.tab.json" \
  --tab electric-guitar="$OUTPUT/electric-guitar.tab.json"
```

Keep the validator's JSON output with the manifest. It records the environment,
RTF, load time, peak CUDA memory, TAB event counts, dropped note assignments,
and unresolved onset groups needed for the Milestone 7 decision.
