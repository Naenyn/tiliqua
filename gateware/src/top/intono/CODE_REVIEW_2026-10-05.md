# Intono and librarian review — 2026-10-05

Reviewed the current working tree on `codex/intono-profile-manager`, including
recent uncommitted UI, Scala, profile-library, and bulk-write work. This report
separates tonight's corrections from those earlier feature changes. No hardware
was flashed or exercised; the rack was powered down.

## Corrections

- **Librarian names:** invalid text could disappear on redraw or tab changes,
  leaving an older valid record available for writing. Calibration, scale, and
  config names now share one handler. Invalid drafts survive navigation and
  prevent exporting/writing stale values. Valid names apply locally as typed.
  Subsequent keyboard or Scala interval edits retain the latest name.
- **Serial connection lifecycle:** EOF or a failed reader could reject a request
  while leaving the UI connected. Reader failures now mark the device closed,
  notify the UI, and release the port. Further requests fail immediately.
  Cleanup is idempotent when manual disconnect and stream failure coincide.
- **Calibration slot preview:** successful librarian writes now invalidate the
  selected calibration slot's cached caption. The foreground refreshes it without
  changing the active RAM calibration. An uncertain flash result also triggers
  a refresh rather than leaving a potentially stale name.
- **Named config saves:** scale and config envelopes now share a writer which
  computes the final checksum once, avoiding the previous config re-checksum.
- **Firmware budget guard:** linking now rejects firmware larger than the existing
  320 KiB budget. Previously that check existed only in the pre-flash procedure,
  allowing an oversized archive to be built.
- **Librarian redraw cost:** pending-change counts no longer clone every changed
  profile. Byte snapshots are still taken when preparing an actual bulk write.
- **Keyboard rendering:** thick black-key borders are drawn in one pass. The old
  implementation repainted almost the entire key to add its second border pixel.
  Pixel comparison tests cover both keyboard heights and verify identical output
  with no duplicate pixel visits.
- **Page-indicator hardware:** fixed horizontal spans replace a 2,048-word ROM
  used only for six page boxes. The four-cycle overlay latency is unchanged.
  Pixel tests cover all six pages and the vertical fill/border transitions.

## Review coverage and remaining constraints

Inspected profile framing and bounded storage, write verification and bulk-write
failure handling, calibration/scale record validation, quantizer boundary math,
route ownership/reference-output behavior, drawing paths, and memory placement.
The existing numerical, calibration, ownership and interrupted-journal tests
remain the main regression coverage for these paths. No additional mathematical
or ownership defect was established in this pass; this is not a proof that all
hardware behavior is correct.

Large calibration and transfer buffers remain in the reserved foreground PSRAM
region, rather than being added to interrupt state or the real-time stack. The
linker still enforces at least 24 KiB between static SRAM data and the stack top.
Actual worst-case stack high-water must be checked on the rack; static headroom
is not a runtime stack measurement. Saved-record layouts and storage allocation
are unchanged by this review.

Firmware flash-slot capacity remains the tightest software limit.
Further significant savings should target measured large code/table contributors,
not reduce calibration buffers or stack reserves speculatively.

## Validation

- 24 librarian tests: record/Scala bounds, CRC corruption, transport, bulk order,
  partial failure, reader EOF/error and idempotent disconnect.
- 231 host Rust tests across navigation, route rendering, Scala rendering,
  profile transfer and journal suites.
- 101 Python test entry points across display, calibration, scale, ownership,
  UART, UI geometry, help, four-output playback, timer, archive and library tests;
  several entry points run additional Rust fixture suites.
- Browser demo check: an invalid calibration name survives a tab round trip and
  disables export; correcting it restores export. Renaming a scale then toggling
  a key preserves its name. This used disposable demo state, not device data.
- Updated stale test expectations for the hidden single-octave pager, retained
  Options drawing, existing 36 KiB storage allocation, and multiline timer calls.
- Full R5 FPGA build with seed 22 and strict timing; final firmware packaged with
  that matching hardware. All four final clock constraints pass.

## Measured build comparison

Same R5 target, seed 22, 1280×720p60, 192 kHz audio and disabled spread spectrum.
Baseline: `intono-keyboard-layout-r5`; reviewed build: `intono-review-oct05-r5`.

| Resource | Before | After | Change |
|---|---:|---:|---:|
| Firmware bytes / 327,680 | 327,536 | 327,040 | −496 |
| Firmware headroom | 144 | 640 | +496 |
| FPGA block RAM / 56 | 51 | 50 | −1 |
| FPGA logic cells / 24,288 | 22,050 | 22,210 | +160 |
| FPGA flip-flops / 24,288 | 12,259 | 12,262 | +3 |
| DSP multipliers / 28 | 14 | 14 | unchanged |
| Static SRAM bytes | 8,164 | 8,164 | unchanged |
| Static SRAM-to-stack-top margin | 24,604 | 24,604 | unchanged |

The pager trades 160 logic cells (0.66% of device capacity) for one block RAM,
leaving six free blocks instead of five. This is a memory saving, not a reduction
in every FPGA resource. Final clock results: CPU 65.53 MHz ≥ 60, display 78.29 MHz
≥ 74.25, display serializer 468.16 MHz ≥ 371.33, external/audio 69.09 MHz ≥ 49.15.

Archive: `build/intono-review-oct05-r5/intono-review-oct05-d6e635-d-r5.tar.gz`
(relative to `gateware/`). The archive includes the reviewed firmware and new
matching bitstream. `review-qualification.json` beside it records hashes and
final timing results. It has not been flashed.

## Tomorrow's hardware checks

Launch the new archive, inspect page indicators and key borders, then smoke-test
calibration and a multi-output route. While viewing a saved calibration slot,
rename/write it in the librarian and confirm the caption refreshes while the RAM
profile remains unchanged. Test unplug/reconnect with local edits and a bulk
write, including read-back verification. No automatic flashing was performed.

## Imported-scale navigation follow-up

Imported interval plots now remain cached independently in both display banks.
Moving the selection no longer clears and repaints the 408×36 plot strip
(29,376 pixel writes for the two fills alone). Unchanged retained controls also
skip painting. Installing a new interval table or changing surfaces invalidates
the cache; leaving the page still erases the strip.

Navigation LEDs follow visible page and control order rather than stored option
indices. Child pages use their parent page LED; menus longer than eight controls
repeat the eight jack LEDs. Warning dialog actions follow their displayed order.

To stay within the existing 320 KiB firmware guard, empty drawing caches use a
zero sentinel and four stopped quantizer engines are constructed once from the
shared constructor. Guarded storage rejects use before initialization. Engine
construction runs after startup returns and before interrupts are enabled,
keeping the approximately 12 KiB startup and 10 KiB construction stack frames
separate. Existing diagnostics and saved-storage layout remain intact.
