# Intono diagnostic and dead-code review — 2026-10-06

Baseline: release candidate `intono-v1.0.0-RC1` / `321b159a`.
Work is isolated on `codex/intono-diagnostic-cleanup`; RC1 remains unchanged.

## Findings and corrections

1. **Quiet builds still performed unsolicited status work.** The NSDF
   `continuous-quiet` default disabled score telemetry, but `capture_trace`
   still formatted calibration progress/timings and scanned the SRAM stack
   watermark every five seconds. Its report occupied a 1,536-byte foreground
   buffer. Status reporting, its buffer, and stack painting/scanning are now
   compiled only with `TILIQUA_INTONO_STATUS_DIAGNOSTICS=1`. Verbose diagnostics
   imply this flag. The Profile Library packet service remains unconditional.
2. **Startup collected unused timing data.** Normal builds read the playback
   timer repeatedly and retained eight startup timestamps that only verbose
   reports consumed. Collection and retained timestamps now compile only in
   verbose mode; normal UI startup and reference/playback timers are unchanged.
3. **Output peak statistics were diagnostic-only.** Normal builds accumulated
   `max_cycles` and `max_gap` on every running output interrupt, although only
   verbose reports read them. These fields and updates are now verbose-only.
   Scheduling-gap, per-batch CPU-budget, combined CPU-budget, DAC heartbeat,
   and ownership checks remain active. The timer reads required by those
   guards have not been removed.
4. **Unused synchronous logger scaffolding remained.** `handlers::logger_init`,
   its static logger, and the `Serial0` wrapper had no caller. Removed them,
   ineffective startup `warn!` calls, and Intono's direct `log` dependency.
   Shared libraries still use logging, so `log` remains a transitive dependency.
   Also removed the unused `panic-halt` dependency: Intono already supplies its
   own bounded panic/trap handlers, which remain available in ordinary builds.
5. **Unused helper and misleading comments.** Removed the uncalled
   `pitch_units::nominal_volts` helper and its self-contained test. Updated
   comments describing the authoritative NSDF peripheral and scheduler as
   experimental-only. Compile out the baseline-comparison observer when score
   telemetry is off, rather than retaining a no-op API with unused arguments.
6. **Scheduler tests had stale build flags.** Nine existing tests expected
   telemetry but compiled without `tuner_nsdf_telemetry`. Added that flag to
   telemetry tests. The mock also recognized only the literal `continuous`
   mode, incorrectly treating `continuous-quiet` as a slow historical mode;
   it now uses the actual compilation cfg. Added four quiet-mode runs checking
   no UART output while the real scheduler continues acquiring and publishing
   valid/fresh pitch under simulated stalls and transitions.

## Deliberately retained

- `nsdf_trace` is the production pitch service, not merely a logger. Its
  scheduler, source-energy qualification, native/low-bank selection and
  sequence/freshness checks remain active without telemetry.
- The `experiment/` directory contains production NSDF RTL and the buffered
  librarian UART. It is a historical directory name; deleting it would break
  the instrument. Only its stale comments changed in this review.
- Optional waveform/pair/score exports and repeat-CV diagnostic modes remain
  explicit build-time tools, outside the ordinary production configuration.
  They retain qualification value and must not be mistaken for release builds.
- The display health counters and serializer reset correction remain in the
  unchanged RC1 FPGA circuit. No FPGA resource saving is claimed by this pass.
- Panic/trap reporting, linker SRAM/firmware bounds, output watchdogs and jack
  ownership are safety/operational code, not troubleshooting clutter.
- Archived qualification notes and test fixtures remain evidence. They are not
  included in firmware. Shared calibration/test APIs reported as unused by an
  individual build are not removed just to silence compiler warnings; unused
  linked functions are eliminated by the release linker/LTO.

## Measurements

| Item | RC1 | Cleanup |
| --- | ---: | ---: |
| Firmware payload | 326,752 bytes | 323,176 bytes |
| Remaining under 327,680-byte budget | 928 bytes | 4,504 bytes |
| Static SRAM `.data + .bss` | — | 8,164 bytes |
| Static SRAM-to-stack-top reservation | — | 24,604 bytes |
| Foreground runtime PSRAM section | — | 10,512 bytes |

Firmware savings: **3,576 bytes**. Static SRAM values are not runtime stack
high-water measurements. Removing the report buffer does not establish an exact
stack saving because compiler frame layout/lifetime reuse also affects that.

The firmware-only archive reuses RC1's exact `top.bit`, verified byte-for-byte.
Its inherited qualified timing is serializer416.49/371.33MHz, pixel81.93/74.25,
audio67.95/49.15 and CPU64.35/60. No new placement or FPGA timing run was needed:
only firmware and Python documentation comments changed.

## Validation and handoff

- 79 tests across scheduler/telemetry, quiet-mode acquisition, waveform tooling,
  calibration/live adapters and profile-library framing passed. After final
  conditional-compilation edits, all 33 scheduler tests passed again.
- Six multichannel, ownership and playback-clock checks passed (85 test entry
  points total; some run additional Rust fixture suites).
- Compact and verbose optional configurations passed embedded `cargo check`.
  These are compilation checks, not a guarantee that every diagnostic variant
  fits the release linker budget.
- Final normal R5 firmware release linked successfully with diagnostics unset;
  the 320 KiB firmware and 24 KiB static stack guards passed.
- Archive/disk/manifest CRCs, option reservation36,864 bytes, exact RC1 hardware
  identity, and synchronized phase-reset wiring verified. Normal firmware has
  no CAL STATUS, VIDEO BUFFER_GAPS, STACK UNUSED_BYTES or NSDF RUN report strings;
  bounded INTONO PANIC reporting remains. `git diff --check` passes.

Artifact (relative to gateware):
`build/intono-diagnostic-cleanup-r5/intono-diagnostic-cleanup-321b15-d-r5.tar.gz`.
Its `qualification.json` and saved `firmware.elf` record the final result.

The initial cleanup was flashed to slot 1 on 2026-10-06 (`Refresh: DONE`). Flash log: `/tmp/intono-diagnostic-cleanup-flash.log`. Hardware smoke testing should cover
startup, tuning, AUTO calibration, a multi-output route, and Profile Library
read/write before this cleanup is merged. No saved-record formats, slot counts,
profile storage allocation, quantizer math or calibration procedure changed.

## Follow-up display improvements (2026-10-07)

The final reviewed build includes palette-derived keyboard membership colors,
a retained completed CAL plot, and sparse Routes redraws with retained banks.
The CAL cache hardware passed all four clock constraints with seed 13; the
Routes firmware-only build reuses that exact qualified FPGA image. Its firmware
is 325,528 bytes with 2,152 bytes remaining under the 320 KiB limit. Routes adds
no framebuffer allocation or static paint storage. Native checks cover layered
partial repaint versus full rendering, removals/reordering, independent bank
invalidation, and CAL snapshot ownership. The user accepted the CAL navigation
improvement and the subsequently flashed Routes update, and requested merging
this work into `naenyn`. No saved-record formats were changed.

Final artifact: `build/intono-route-paint-r5/intono-route-paint-321b15-d-r5.tar.gz`.
Flashed to slot 1 with `Refresh: DONE`; user navigation review passed.
