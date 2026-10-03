# Intono cleanup and performance review — October 3, 2026

Baseline: `49675406` on `codex/intono-route-flow`. The accumulated UI, routing,
configuration, and MIDI learning work was committed before this review.

## Changes made

- Limit calibration profile traversal/hash work to calibration views. Previously,
  a stored profile was traversed every foreground iteration on tuner/routes too.
  Error-span calculation now runs only for the Error graph; Pitch does not use it.
  The calibration scene still invalidates when re-entered and when its data changes.
  No measurement, DAC, scan timing, quality threshold, or interrupt algorithm changes.
- Compute the visible route outputs once per flow navigation operation, rather
  than repeatedly for each potential node. Editors no longer construct an unused
  flow navigation order. Remove unreachable overview navigation and obsolete
  Transpose/Profile/Assign stages, now grouped into Pitch and Output/Profile.
  Persisted option indices and record formats remain unchanged.
- Remove the unreachable legacy Configs text renderer. The sparse route presenter
  already handles that page. Format the route navigation and presenter modules
  with rustfmt so control flow and ownership boundaries are easier to review.
- Correct the blocked config-save message to say SAVING, rather than LOADING.
  Flash access remains blocked during active operations.
- Remove unused imports/variables and gate experimental trace dependencies to
  their actual compilation mode. Retain operational video/scan/stack diagnostics.
- Repair standalone persistence tests missing their ownership dependency. Update
  the geometry comparison to exclude Configs, which now uses firmware sparse
  shapes rather than the retained legacy FPGA descriptors. Actual Configs geometry
  is tested by the real presenter fixture, including bounds and shape capacity.

## Math and logic checked

Reviewed fixed-point playback conversion and rounding, quantization followed by
manual/MIDI transpose, bounded output lookup, multi-output batching, route layout
validation, configured reservations versus active claims, setup encode/decode and
migration, and MIDI base learning/release state.

The normal ADC conversion has a native integer fast path; nonstandard conversion
uses wide arithmetic. Playback validates bounds and acknowledgement/freshness
before driving outputs. Configuration decoding validates CRC and layout before
replacement. Empty routes do not reserve inputs; nonempty stopped routes do.
Calibration can temporarily borrow stopped-route jacks through active claims.
Learning is canceled when its context changes; learned base notes are consumed
before foreground configuration is republished. Live transpose is not persisted.

No new arithmetic or calibration-procedure defect was identified in this pass.
Existing reference tests exercise calibration interpolation, range edges,
conversion, shifted quantization, corruption/migration, and channel/release logic.
Those tests support the reviewed paths; they do not prove physical timing.

## RAM and storage

Release ELF compared against the last Configs firmware:

| Allocation | Before | Review build |
| --- | ---: | ---: |
| Static SRAM (`.data` + `.bss`) | 7,940 bytes | 7,940 bytes |
| Reserved stack address range | 24,828 bytes | 24,828 bytes |
| Static calibration runtime in PSRAM | 7,048 bytes | 7,048 bytes |
| Firmware archive payload | 312,512 bytes | 312,112 bytes |

There is no heap allocation. The reserved stack range is **not** measured free
stack: main-loop frames and interrupts consume it. Hardware watermark capture
remains necessary, especially with calibration and multi-output routing.
Profile copies remain explicit bind/load/save operations rather than per-tick
copies. Scale masks are bounded eight-octave arrays; retaining 1–8 octaves with
one as default is appropriate. Compiled degree tables have at most 96 notes.

The review saves 400 firmware bytes; 15,568 bytes remain under the 327,680-byte
firmware limit. UI growth remains worth monitoring. FPGA logic is unchanged;
archive qualification verifies that `top.bit` matches the qualified image.

## Validation and remaining work

- 255 calibration/live/playback Rust tests passed.
- 97 scale/UI/setup fixture tests passed; 19 standalone setup/dependency tests passed.
- 35 real option/navigation tests and 53 presenter/dependency tests passed.
- 29 calibration/scale/import Python test cases passed (including Rust fixtures).
- 7 frame-exchange, shape, and multi-output Python simulation cases passed.
- Presenter capture inspected; `git diff --check` passed. Release build completed.

Some shared/experimental library code still produces dead-code warnings. This
pass avoids removing reusable calibration APIs solely because Intono does not
currently call them. The old RouteMidi fallback is retained for a generic menu
context; normal flow/config entry uses the sparse presenter.

Hardware follow-up: test navigation and Configs back paths, MIDI learn/latch/reset,
save/recall, CAL Pitch/Error switching after visiting other pages, AUTO scan, and
stack/interrupt timing. The intermittent colored horizontal flashes remain
unproven resolved; simulations and offline captures do not reproduce every HDMI
or PSRAM timing condition. No flashing was attempted overnight.

## Morning artifact

`build/intono-ux-midibase-r5/intono-cleanup-20261003-r5.tar.gz`
with matching `cleanup-firmware.elf` and `cleanup-validation.json` (archive hash,
source commit, payload size, bitstream identity, and test results). Flash only
when the user says the rack is ready for testing.

Final firmware source commit: `8b4ebe9e`. Archive SHA-256:
`feebc311a27d2f077457f602340dc124f991bfda61d338cc20bc956242873d73`.
The final archive has 312,112 firmware bytes and is verified to contain the same
FPGA bitstream as the qualified route-groups image. No flash was performed.
