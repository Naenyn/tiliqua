# OSCIO frequency-detector state-memory experiment

## Outcome: not retained

The seed-3 strict build failed serializer timing, reaching 369.96 MHz against
371.33 MHz. The pixel clock passed at 74.29/74.25 MHz, audio at 60.36/49.15 MHz,
and sync at 61.80/60.00 MHz. The approximately 0.40-percentage-point logic saving
does not justify replacing the smoke-tested implementation with this route.
No timing constraints were relaxed, no shared core was modified, and nothing
was flashed. Another seed might behave differently; it was not attempted.

Production `frequency_detector.py` was restored byte-for-byte to its pre-pass
state. The prototype is retained only as `tests/reference_frequency_memory.py`,
with a cycle-equivalence test against production, for reproducibility. It is
not imported by the bitstream. These sections describe the rejected experiment.
The three equivalence tests passed again after restoring production and moving
the prototype into its test-only fixture. The existing build-directory bitstream
and firmware hashes still match the smoke-tested archive exactly.

## Scope

This experiment changes only the native frequency detector used by OSCIO.
The shared video encoder, clocks, CPU, audio path, renderer, firmware behavior,
and synthesis defaults are unchanged.

The hardware-confirmed baseline uses 22,950 COMB, 12,098 FF, 37 DP16KD,
and 9 MULT18X18D. Its archive is
`oscio-2ed89680-native-peaks-pagination-spread0-seed3-r5.tar.gz`.

## Implementation

Eight wide register arrays become small asynchronous-read, synchronous-write
memories: block extrema, envelope extrema, Schmitt thresholds, elapsed period,
and stale timeout. Small flags, activity state, and externally visible outputs
remain registered. Every stored value retains its original width and signedness.

The existing channel-processing schedule, tick priority, and snapshot-visible
outputs are unchanged. No additional serialization or input FIFO is introduced.
Reset-valid flags mask old RAM contents until each channel has been rewritten,
preserving the reset behavior of the old registers without physically clearing RAM.

This is a storage optimization, not a redesign of the existing input scheduler.
Stress equivalence verifies matching behavior on dense ticks; it does not claim
the existing scheduler processes every frame of an arbitrarily dense input stream.

## Verification and initial resource measurement

The retained register implementation is the reference for cycle-exact simulation.
Three comparisons cover one/four channels, 8/24-bit period counters, independent
channel signals, signed extremes, irregular ticks, idle intervals, and resets
during processing. All three passed (24,000 clocks each). The nine existing
frequency tests also passed, including exact timeout expiry and 48/192 kHz
activity classification.

The full regression also passed: 86 tests and 12 subtests, with 11 existing
Amaranth deprecation warnings. Whitespace checks passed.
The rebuilt firmware remains byte-identical to the baseline (SHA-256
`557bf5b4042647a9dc1a1b3c62a13a21135cfe9eed7c097774be72277a74fd2b`).

Packed resources are 22,852 COMB, 11,478 FF, 37 DP16KD, and 9 MULT18X18D:
98 fewer COMB and 620 fewer FF than the baseline, without additional block RAM
or multipliers. Combinational utilization falls from 94.49% to 94.09%.
The smaller RAMs use distributed FPGA memory, not DP16KD blocks.

The build used ASQ 2/18, 192 kHz, strict timing, seed 3, and
`spread_spectrum=0.0`. Final routed timing is reported above. The retained timing
report is `top-frequency-memory-spread0-seed3-rejected.tim` in the main
repository's ignored `gateware/build/oscio-r5/` directory. Generated RTL,
mapped netlists, and generic timing reports in the experimental worktree's
build directory describe the rejected experiment, not the working bitstream.
