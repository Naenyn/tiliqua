# OSCIO correctness and resource follow-up

Baseline: hardware-confirmed continuity fix, committed as `2ed89680` before
this pass. HDMI, clock generation, CPU selection, sample widths, and trace
rendering were left unchanged.

## Changes

- Frequency staleness now compares the existing elapsed-sample counter with a
  stored timeout limit instead of decrementing a second wide counter. The
  three-period timeout, saturation, and native-sample cadence are unchanged.
  Side-by-side simulation against the baseline matched every period, validity,
  and rapid-activity output across 2,500 four-channel frames, including irregular
  crossings, pauses, and deliberately shortened counters to exercise saturation.
- Activity windows and envelope blocks are scaled to native sample rate. This
  keeps the 192 kHz behavior and fixes 48 kHz builds classifying 20 Hz as rapid.
- The CV/LFO level filter retains its signed division remainder. Positive and
  negative DC steps now settle to the input count instead of exhibiting the
  previous negative bias (for example 1 V settling at 0.992 V). This is firmware
  only. It uses a wide intermediate for safe subtraction, not floating point.

## Measured resources

Same ASQ 2/18, 192 kHz, strict seed-3 build, spread spectrum disabled:

| Packed resource | Baseline | This pass |
| --- | ---: | ---: |
| TRELLIS_COMB | 22,672 | 22,521 |
| TRELLIS_FF | 11,806 | 11,806 |
| DP16KD | 37 | 37 |
| MULT18X18D | 9 | 9 |

This saves 151 combinational cells, about 0.62 percentage points of the FPGA's
24,288-cell capacity. It is a modest improvement, not a major area reduction.
Within the mapped frequency-detector hierarchy, LUT4 count falls from 1,532
to 1,299; LUT4 and packed TRELLIS_COMB counts are different accounting units.

Final routed timing passes every domain: dvi5x 426.26/371.33 MHz,
dvi 82.04/74.25 MHz, audio 59.61/49.15 MHz, sync 67.25/60.00 MHz
(achieved/required). The previous sync result was 63.01 MHz; the improvement
is measured for these particular routes, not a guarantee across seeds.

Archive: `oscio-2ed89680-resource-spread0-seed3-r5.tar.gz`.
Bitstream SHA-256:
`edc39f968ffda72156cf3b92c997013d39782ce79f059d1ba1c1a7b5f89fe406`.
The tag identifies the pre-pass checkpoint; this pass is still uncommitted.

## Verification

- 84 DSP, capture/raster, frequency, and CDC tests plus 12 subtests pass.
- New timeout tests cover the exact expiration sample and saturated limit.
- New activity tests cover 20 Hz and 80 Hz at 48 kHz and 192 kHz.
- The actual production voltage tracker and its new Rust unit test were compiled
  in an isolated native harness; DC steps, signed symmetry, reset, and three
  input fixed-point formats pass. Firmware release compilation and formatting
  checks pass. The entire firmware's host-incompatible test suite was not run.

## Further work, deliberately not bundled into this pass

- The subsequent correctness pass addresses short-display pagination, the
  repeatability/help mismatch, and native-rate peak capture. See
  `OSCIO_CORRECTNESS_REVIEW_2026-09-13.md` for its separate resource cost and
  verification; these additions are not part of the equivalence claim above.
- Repeated configuration writes and statistics snapshots remain CPU-side
  opportunities. They are unlikely to materially reduce FPGA logic.
- Larger area candidates are the frequency detector's channel-state muxes and
  display resampler/reconstruction state. Memory-backed or more serialized
  implementations need separate equivalence and throughput testing; retain the
  current working renderer as the baseline rather than combining that redesign
  with these corrections.
