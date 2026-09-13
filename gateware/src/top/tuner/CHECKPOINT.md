# TUNER pause checkpoint — September 13, 2026

Work is paused at the user's request. This file supersedes earlier "next step"
and pending-trial statements in the dated investigation documents. Active branch
is `codex/tuner`; latest implementation commit is `26d3891e`. No remote push is
implied. TUNER remains a working instrument name.

## Working features

- Shared renderer and four-input NSDF tuner, spiral and linear views; independent
  level meters. Selected build is 192 kHz; legacy pitch hardware is omitted.
- Oscillator calibration: upward -5..+5 V sweep, up to 121 semitone-spaced points,
  usable-range discovery, review/accept/discard and tuning advice. ACCEPT is RAM
  only; four PROFILES slots are saved separately. VERIFY and guarded local
  refinement work; corrected PLAY is a separate single-channel path.
- Standalone four-output nominal quantization, independent input routing (one
  input may feed several outputs), scales, root, transpose, 0 V note and mapping.
  Default routing is IN n to OUT n. No audio pitch detection or profile required.
- Nearest and Equal mapping; presets including 24 EDO; editable two-octave note
  patterns. One empty octave collapses to one-octave operation. Eight NOTES
  pattern slots and eight SETUPS slots; each setup contains all four channels.
  Settings edits/recall stop outputs; RUN is explicit. Out-of-range CV holds the
  last valid result; faults/stale data retain their separate safety behavior.
- Scala conversion/validated binary decoding exists offline, but device import,
  persistent imported microtonal scales, MIDI learning and USB hosting do not.

## Four-output synchronization and test evidence

`77baf571` introduced four lanes at 500 Hz each, calculating two per 1 ms
interrupt. The user heard possible stagger. `26d3891e` retained that CPU schedule
but shares input readings between batches and stages all four output voltages
until one common commit. Explicit safety disables remain immediate. The codec
path carries four values together through its FIFO; physical jack timing is
not established solely by the simulation or register ACKs.

- 174 regression tests passed, including staged-output behavior, DAC
  backpressure, ACKs, fault isolation and CAL priority.
- Live serial on the synchronized build: all four active; observed maximum
  batch 21629 cycles (~360.5 us at 60 MHz), below the 500 us guard. Observed
  maximum interrupt gap 121127 cycles (~2.019 ms), below the 5 ms guard.
  These are observed maxima, not a worst-case execution-time proof.
- First audio recording used different scales/mappings, which legitimately
  change notes at different CV thresholds. Second recording used matching
  reported settings. Four spectral tracks across 14 successive transitions
  showed no consistent sequential order; estimated transition spread was
  about 1–4 ms. The 1024-sample spectral window and individual oscillator
  responses mean those estimates do NOT measure DAC skew or prove zero skew.
- Next optional timing test: connect OUT0–3 to another Tiliqua running OSCIO,
  use identical quantizer settings and one LFO, trigger on a CV step, inspect
  all four edges near 1 ms/div if supported. Check scope sample/display
  resolution before making sub-millisecond claims; raw capture is preferable.

Local evidence (not repository fixtures): `/tmp/tuner-sync-regression.log`,
`/tmp/tuner-sync-build.log`, `/tmp/tuner-sync-matched-check.serial.log` and
`/tmp/tuner-sync-audio-check.serial.log`; these temporary files can expire.
User recordings: `New 2 2026-09-13 1709.wav` and `New 2 2026-09-13 1717.wav`.

## Qualified hardware and release build

Full synthesis/routing of the synchronized hardware passed:

| Resource/clock | Result |
|---|---:|
| LUT4 | 19312 / 24288 (79%) |
| EBR | 44 / 56 (78%) |
| DSP | 14 / 28 (50%) |
| Main clock | 65.85 MHz achieved / 60 MHz required |
| HDMI serializer | 406.17 / 371.33 MHz |
| Pixel clock | 87.72 / 74.25 MHz |
| Audio clock | 69.74 / 49.15 MHz |

CPU working RAM remains 32 KiB. Do not assume the remaining FPGA resources can
support every optional feature; retain CPU, memory and routed timing checks.
No spectrum renderer is planned as a prerequisite for feature completion.

Qualified `top.bit` SHA-256:
`48e9bd78f32593d57549807b9f8b8be57b51070f8220ceadc388c6fcf4049fcf`.
The documentation checkpoint build reuses this hardware with a newly tagged
firmware/archive. Normal release is R5, 1280x720p60 (unrotated), 192 kHz,
`spread_spectrum=0.0`. Circular display qualification is not claimed here.

From `gateware`, with the project's Python environment and FPGA/Rust tools on
PATH, build with `PYTHONPATH=src TILIQUA_TUNER_NSDF=1 TILIQUA_TUNER_SEED=17
python src/top/tuner/top.py build --hw r5`. Add `--fw-only` only when reusing
qualified, unchanged hardware. Never use it to qualify a gateware change.
Archives are under `gateware/build/tuner-r5/`. Preserve option storage; archives
contain bitstream, firmware and manifest, not a replacement options payload.
Bitstream slot 1 is distinct from calibration-profile slot 1.

## Resume priorities

1. Resolve physical CV timing only if needed; do not mistake differing scale
   thresholds or oscillator response for channel scheduling delay.
2. Consolidate multi-channel safety/storage regression coverage and UI clarity.
   QUANT's output selector selects a channel's settings; RUN controls the group.
3. Add validated user-controlled scale import/storage and computer-side authoring.
   Keep scale files independent of oscillator profiles and stopped during import.
4. Evaluate optional per-channel profile correction, MIDI learning/transposition,
   and USB support separately against resource limits. No commitment to fit all.
5. Revisit the wider interface after feature behavior is settled. Preserve the
   single renderer, panel numbering, explicit run/stop and save feedback.

Do not infer a saved profile's oscillator identity from old slot maps: the user
has overwritten test slots during development. Preserve all stored records.
