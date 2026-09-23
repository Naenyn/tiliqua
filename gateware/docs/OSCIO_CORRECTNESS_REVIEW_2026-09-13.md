# OSCIO correctness follow-up — 2026-09-13

This follows the resource pass documented in
`OSCIO_RESOURCE_REVIEW_2026-09-13.md`, on top of checkpoint `2ed89680`.

## Corrections

- CV/LFO uses two-channel pages on rectangular logical displays shorter than
  688 pixels, with no circular insets. Each lane needs 172 pixels for its
  statistics bitmap and separators. Rotation is included in the decision.
  The 720x720 circular-safe layout is unchanged. The channel selector appears
  for either kind of paginated layout; no new display-specific build is needed.
- Help describes frequency as the latest rising-crossing interval, not a
  repeatability guarantee. Irregular signals can produce changing readings.
  Help scroll distance is regenerated to match the updated text.
- A native-rate four-channel extrema accumulator observes every accepted input
  frame before display resampling/cleanup. An atomic snapshot freezes the
  signed minimum and maximum of each channel and begins a fresh window. A
  coincident native sample belongs to the completed window exactly once.
  Empty windows are marked invalid; frozen values stay stable while CPU reads.
- Firmware merges these extrema into the existing slowly released peak hold,
  preserving its 1 kHz release cadence and level averaging. The first snapshot
  on entry drains scope-mode history rather than displaying old peaks.

Native capture preserves the input fixed-point width; voltage display conversion
is unchanged. Peaks between ADC samples remain unobservable, and low/high are
released peak holds, not permanent extrema or cycle-synchronized measurements.
This improves the statistics, not the display renderer or waveform sampling rate.

## Verification

- 86 Python regression tests and 12 subtests pass, including DSP, capture,
  frequency, CDC, native extrema, and real CSR snapshot/read integration.
- Randomized extrema testing covers signed endpoints, one-sample pulses,
  simultaneous snapshot/sample, adjacent snapshots, and empty windows.
- Eight production Rust layout/tracker tests pass in an isolated native harness
  with geometry types stubbed. These cover short rectangles, the threshold,
  circular and landscape layouts, native peaks, DC averaging, and generation.
  The complete bare-metal firmware host test suite was not run.
- Release firmware compiles and `cargo fmt --check` passes.

## Build result

Configuration: ASQ 2/18, 192 kHz native sampling, seed 3,
`spread_spectrum=0.0`, strict timing. Every routed clock passes:

| Domain | Achieved MHz | Required MHz |
| --- | ---: | ---: |
| dvi5x | 448.43 | 371.33 |
| dvi | 79.61 | 74.25 |
| audio | 59.64 | 49.15 |
| sync | 61.95 | 60.00 |

Packed resources are 22,950 COMB, 12,098 FF, 37 DP16KD, and 9 MULT18X18D.
Compared with the preceding resource pass, this adds 429 COMB and 292 FF;
BRAM and DSP counts are unchanged. This is a correctness improvement with an
area cost (94.5% combinational capacity used), not another area optimization.

Archive: `oscio-2ed89680-native-peaks-pagination-spread0-seed3-r5.tar.gz`.
Bitstream SHA-256:
`43bac2abd552592c15e156519032db2ac2774c96d56991c495530e790f6c559b`.
Firmware size: 176,228 bytes. The archive tag names the pre-pass checkpoint;
the corrections remain uncommitted pending hardware feedback.
Flashed successfully to slot 7 (`Refresh: DONE`). The user subsequently
reported that a quick hardware smoke test looked good.
