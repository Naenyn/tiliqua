# OSCIO serialized peak-capture optimization — 2026-09-13

## Outcome: rejected on 2026-09-14

The complete, burst-safe prototype saved only **two COMB cells and 45 FF**:
22,948 COMB / 12,053 FF, versus 22,950 / 12,098 in the working baseline.
BRAM and DSP counts remained 37 and 9. This does not justify the added state,
buffering, firmware polling, or timing risk. Its route was stopped after packing.

All prototype hardware, firmware, and synthesis-default changes were restored
to the smoke-tested implementation. Only the strengthened burst/invalid-payload
regression and this documentation remain from the experiment. Nothing was
flashed. The sections below describe rejected prototypes, not current code.

The restored package was verified against the smoke-tested archive:
bitstream SHA-256 `43bac2abd552592c15e156519032db2ac2774c96d56991c495530e790f6c559b`
and firmware SHA-256 `557bf5b4042647a9dc1a1b3c62a13a21135cfe9eed7c097774be72277a74fd2b`
both match exactly. Experimental build reports do not describe this retained
bitstream; use the correctness review's timing report for it.
The restored implementation plus the new burst/invalid-payload regression
passes 86 Python tests and 12 subtests; whitespace checks also pass.

Baseline: the hardware smoke-tested native-peaks/pagination build, bitstream
`43bac2abd552592c15e156519032db2ac2774c96d56991c495530e790f6c559b`.
Its resource counts were 22,950 COMB, 12,098 FF, 37 DP16KD, and 9 MULT18X18D.

## Implementation and precision

- One signed comparator replaces eight parallel comparisons. Minimum and maximum
  updates use the same comparison result; rewriting equal maxima is harmless.
- Eight native-width extrema words occupy a small distributed RAM instead of
  individual register banks. Snapshot outputs remain registered.
- The frequency detector exposes its existing captured input frame, avoiding a
  duplicate four-channel sample latch. Frequency arithmetic is unchanged.
- A shared 16-frame LUT-RAM input FIFO absorbs native ADC crossing bursts and
  releases frames at least 18 clocks apart to both observers. The raw stream
  can burst despite averaging 312 clocks per frame. A targeted test first
  reproduced lost interior burst peaks in the unbuffered prototype, then passed
  with this FIFO. The unbuffered prototype is not eligible for flashing.
- Updates take eight clocks. Snapshot copies take eight clocks and wait for an
  in-flight update. A one-frame pending flag covers arrivals during copying.
  Firmware waits for the new `extrema_busy` status bit before consuming outputs.
  Snapshot completion does not depend on new samples arriving.
- This requires at least 18 clocks between native frames, including arbitrary
  legal snapshot traffic; the supported 192 kHz stream provides about 312.
  The input FIFO enforces this cadence. This is a nonblocking observer: it does
  not stall audio or display processing. Sample-count frequency arithmetic
  remains native-rate even when buffered frames are processed closer together.

The burst-buffered prototype discarded no native sample bits or extrema. Its snapshot boundary could move
by a few system clocks while the current frame finishes; a frame arriving during
copying belongs to the next window. Thus snapshot timing is not cycle-identical
to the parallel design, but windows still cover every frame exactly once.
Frequency snapshots remain request-timed. Voltage scaling, level smoothing,
peak release, waveform reconstruction, and rendering are unchanged.

## Verification and build

- 90 Python regression tests and 12 subtests pass. Tests cover minimum cadence,
  192 kHz and 48 kHz spacing, multiple signed widths, one- and four-channel
  operation, window boundaries, empty snapshots, queued frames, and CSR reads.
  The CSR test poisons the native input payload between handshakes to verify
  that extrema reuse the captured frame rather than unstable source data.
- Release firmware compilation, formatting, and whitespace checks pass.
- The initial, unbuffered prototype's default synthesis reduced registers but increased total packed logic to
  23,496 COMB, so that candidate was not selected for flashing. An additional
  `synth_ecp5 -abc2` area-mapping pass reduces this to 22,820 COMB and 11,963 FF.
  BRAM and DSP counts remain 37 and 9. Against the smoke-tested baseline this
  saves 130 COMB and 135 FF, bringing combinational use from 94.49% to 93.95%.
  These resource figures are superseded: the necessary burst-buffering change
  requires a new area measurement. They are not figures for a releasable build.
- An OSCIO-specific `-abc2` default was trialed and verified in the generated
  build plan. It was removed with the rejected prototype. Normal build defaults
  are unchanged, and strict timing remains required.

## Timing experiments (not flashed)

The area-oriented design passes native/DSP/capture tests but has not yet passed
all routed clocks. Strict routing rejected these candidates:

| Seed | dvi5x MHz | dvi MHz | audio MHz | sync MHz |
| --- | ---: | ---: | ---: | ---: |
| 3 | 430.85 | 71.82 (FAIL) | 59.40 | 66.12 |
| 2 | 373.41 | 68.30 (FAIL) | 55.93 | 66.63 |

Required clocks are 371.33, 74.25, 49.15, and 60 MHz, respectively.
Both failures run from palette BRAM into the first TMDS encoding register, not
through peak capture. The encoder's combinational XOR/XNOR chain is an
opportunity for a separately tested equivalent rewrite; no production encoder,
pipeline, or clock changes have been made in this pass.

A selective synthesis experiment protected the video hierarchy from the extra
ABC pass. It was rejected after packing: 23,799 COMB, 11,987 FF, 34 BRAM, 9 DSP.
Its reduction in block RAM came at too high a logic cost. It was not routed or
flashed. Experimental scripts and reports are confined to the ignored build
directory.

The unbuffered seed-1 route was stopped after the burst regression made it
obsolete. The burst-safe version used strict timing, seed 2, ASQ 2/18, 192 kHz,
and spread spectrum disabled; its packing result is reported above. The powered
rack retains the smoke-tested baseline. No encoder changes were implemented.

A possible follow-up is to replace the encoder's recursive XOR/XNOR chain with
the equivalent prefix-parity identity:
`q_m[i] = parity(data[0..i]) XOR (use_xnor AND (i is odd))`.
A standalone arithmetic check matched all 256 byte values, but production HDL
equivalence testing and implementation still require approval for that scope.
