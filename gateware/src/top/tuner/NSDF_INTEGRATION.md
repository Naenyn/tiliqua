# NSDF integration trial

Branch: `codex/tuner-nsdf-integration`, based on `739cc7b4`. This is an opt-in
parallel hardware diagnostic, **not yet a replacement for the working tuner**.
The baseline display, detector, calibrator and PLAY/quantizer remain authoritative.
The experiment has no connection to output-voltage ownership or profile storage.

## Implemented

- Four live signed-16 input histories share one 4096-word memory.
- One pipelined multiplier performs the 769-tap Q17 FIR for four 192-to-6-kHz
  decimated channels. Saturation is explicit; clipped low-bank samples retain
  a flag in their history.
- Low-frequency history is a separate 4096 x 17 memory. Both histories publish
  their head only after the entire four-channel group has been written.
- Bounded two-pass snapshots compute a nearest-even integer mean and extrema,
  then stream a centered frame directly into score-engine RAM. A single-bit
  right shift protects signed-16 range when necessary. No CPU frame buffer.
- A sequence-age guard discards snapshots before overwrite, reserving one
  unpublished four-channel write batch. Cancellation discards partial frames.
- One shared direct NSDF engine handles 604/301 low-bank and 674/321 native-bank
  frame/last-lag configurations. Centered frame energy is exported without an
  additional multiplier.
- A diagnostic CSR holds one completed score frame until the next request.
  Firmware exports it non-blockingly over UART, alternating banks and channels.
  Packet metadata identifies rate, length, channel, sequence, energy, scaling
  and clipping. Normal capture/status UART output is suppressed in this build
  to prevent interleaved records.

`TILIQUA_TUNER_NSDF=1` enables both the gateware peripheral and matching firmware
through its build script. Without it, the existing tuner remains unchanged.
Diagnostic identity is `0x4e534401`; a mismatch is reported rather than ignored.

## Validation so far

84 focused tests pass; five existing explicit expected failures remain in the
earlier spectral/aliased-waveform experiments. They are not new integration
failures. Tests include:

- Exact full-size FIR comparisons, all four channels, ring wrap, simultaneous
  native reads, saturation, stalled consumption and explicit overrun reporting.
- Positive/negative tie rounding, extreme DC offsets, output backpressure,
  read arbitration, overwrite/cancel/reuse, and insufficient-history errors.
- Continuous four-channel acquisition/filtering while a native snapshot feeds
  the score engine; every score agrees with exact integer reference arithmetic.
- Signed low-bank history and its complete score sequence, plus frame energy.
- Actual byte-wide CSR command writes and signed frozen-score readback.
- Strict serial framing and host selection/refinement for low through near-20-kHz
  synthesized sines; malformed and truncated packets are rejected.

The combined two-bank frontend before the final snapshot input register used
11 EBR, four DSP, 1151 LUT4 and 1156 FF in isolated synthesis. Its routed
out-of-context result was 64.30 MHz at a 60-MHz target. That is not a whole-SoC
timing claim. The first full SoC build used 45/56 EBR and 14/28 DSP and passed
final routing at 61.45 MHz main / 88.72 MHz pixel / 411.18 MHz serializer.
Because main-clock margin was small, the RAM-to-snapshot comparison path was
subsequently pipelined. **Final full-chip routing passes: 66.54 MHz main at
60 MHz, 86.24 MHz pixel at 74.25 MHz, 459.98 MHz serializer at 371.33 MHz, and
68.88 MHz audio clock at 49.152 MHz.** Seed 15, R5, normal 720p display.
Allocation remains 45/56 EBR and 14/28 DSP, including the baseline detector.

CPU RAM remains 32 KiB. The diagnostic keeps a 192-byte text buffer, not a
sample/score frame in CPU RAM. Static data is 1632 bytes and BSS eight bytes;
the linker's `.stack` section reserves the remaining RAM. This is **not** a
measured stack high-water result or a four-profile quantizer proof.

## Reproduction

From `gateware`, with the configured Python, Rust and FPGA toolchains:

```sh
PYTHONPATH=src TUNER_NSDF_TESTS=/path/to/nsdf-reference/gateware/tests python -m pytest -q tests/test_nsdf_acquisition.py tests/test_nsdf_snapshot.py tests/test_nsdf_frontend.py tests/test_nsdf_streaming_integration.py tests/test_nsdf_peripheral.py tests/test_nsdf_direct_rtl.py tests/test_nsdf_banked_probe.py tests/test_nsdf_shared_history.py tests/test_nsdf_trace_analysis.py tests/test_spectral_reference.py
PYTHONPATH=src TILIQUA_TUNER_NSDF=1 python src/top/tuner/top.py build --hw r5
python tests/nsdf_trace_analysis.py /path/to/serial.log
```

Archive name remains TUNER; normal display is 1280x720p60, audio 192 kHz.
Flash only an archive whose final routed clocks all pass; do not erase options.

## Hardware trial and remaining gates

First compare exported estimates on a steady sine, then the previously captured
thin pulse, across low/mid/high pitches. Confirm no audio drops, metadata faults,
UI stalls or output behavior changes. The display still shows baseline pitch:
candidate estimates are decoded on the host for this trial.

Exports deliberately run much slower than the planned 20 analyses/channel/s.
This isolates numerical/capture correctness; it is **not a throughput proof**.
The two banks are exported at different times and reported separately, not
silently fused into one estimate. Guarded longer-lag refinement remains our
engineering extension, distinct from the paper's key-maxima selector.

Still required before replacement: target-CPU selector/refinement benchmarks,
bounded four-channel scheduling and double-buffered score handoff, fresh-frame
bank arbitration/transition tests, stack high-water checks, and physical
accuracy/latency qualification alongside calibration and quantized output.
Retire the old verifier only after that. No spectrum-display dependency and no
CPU RAM increase have been introduced.
