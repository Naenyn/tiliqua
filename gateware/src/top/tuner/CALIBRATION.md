# Calibration implementation boundary

## Current status and remaining scope

Current implementation: upward -5..+5 V acquisition with up to 121 points,
qualified usable-range limits, inverse piecewise-linear mapping, four named
profile slots, manual corrected-note output, POINTS/SCAN verification, serial
diagnostics, and explicitly accepted local refinement. Idle/cancel/fault output
handling is implemented. External pitch-CV corrected playback is not implemented.

Remaining agreed work:

- A bounded real-time input-CV to desired-pitch to corrected-output path,
  with explicit routing, arming, range policy and safe transitions. Share its
  mapping with the future quantizer, not the slow UI update loop.
- User-facing discovery results: usable voltage and pitch coverage, cautious
  tuning-adjustment recommendations, and Accept / Adjust and Rescan / Cancel.
  Existing sweep boundary handling is not that complete workflow. Tuning changes
  invalidate the measured relationship and require a new scan.
- Broader hardware qualification: low/high frequency coverage toward 20 Hz–20 kHz,
  more oscillator/routing combinations, persisted recall and fault paths. The
  Generate3 alternating-cycle high-frequency failure remains unresolved. The
  Disting/Tiliqua nominal-zero comparison does not establish an absolute voltage
  offset; no speculative output correction has been made.
- Continue stack/resource and latency checks as playback is integrated. The
  previous loading freeze is fixed in user testing, not a formal stack proof.

Latest fresh Twin Waves baseline: 90 stored points, 167 verification targets,
worst measured mean -1.72 cents. This is one hardware setup, not a product-wide
accuracy guarantee. User slot map: 1 original Generate3, 2 original Twin Waves,
3 refined Twin Waves, 4 fresh Twin Waves baseline.

The following sections are a chronological engineering log; early sizes,
ranges, pending steps and test counts describe their milestone, not today.

Four-channel tuning is hardware-confirmed. The first live calibration mode now
provides an explicitly started 0..2 V sweep and a RAM-only response profile.
Four named profile save/recall slots are now exposed; corrected performance CV
and quantization remain pending. A successful sweep is not full calibration
qualification. Earlier milestone descriptions below are historical.

`fw/src/calibration.rs` is an independently host-tested, allocation-free domain
module, now linked into the live firmware. It provides printable ASCII names
(24 bytes), up to 32 voltage/pitch pairs, explicit input/output route validation,
strictly increasing measured response, and inverse piecewise-linear mapping.
Pitch uses milli-cents in log-frequency space; voltage uses microvolts. Mapping
outside the measured range returns an error, not extrapolation. A profile uses
at most 304 bytes. Five host tests cover bounds, nonlinear interpolation,
overflow, names, route numbering and rejection without mutation.

These are initial implementation bounds, not a guarantee of calibration accuracy
or a finished storage format. More points or adaptive sampling may be needed to
meet the eventual tracking tolerance. Negative-slope and Hz/V oscillators are
not supported by this first increasing-response model.

## Sweep controller

`fw/src/calibration/sweep.rs` now implements the bounded acquisition protocol.
It owns a separate candidate profile, immutable route, a bounded increasing
voltage plan and an explicitly configured restoration voltage. The adapter must
acknowledge each output request by token before settling begins. Only fresh
measurements from the routed input, whose entire acquisition window starts
after settling, enter the stability check. Stability is measured over the total
pitch spread, not merely differences between adjacent samples. Bad quality
resets the run; unstable pitch restarts it; point deadlines include output-ack
time. Repeated cached UI readings cannot satisfy the fresh-sequence requirement.

Cancellation, failed tracking and timeout discard the candidate and request
restoration. Successful completion also requests restoration; a profile can be
taken exactly once and only after restoration acknowledgment. Restoration
requests remain pending until acknowledged: they are not claims that hardware
actually returned to a safe voltage. A live adapter needs its own output-error
reporting and watchdog policy. A zero restore voltage is not universally safe;
the caller explicitly supplies a permitted value for the configured patch.

Thirteen host tests pass, including a full 32-point sweep, rejection of stale
windows and wrong inputs, invalid-quality resets, cancellation during final
restoration, timeouts, bad acknowledgments, flat oscillator response and clock
reversal. The optimized host library compiles. The controller uses at most
576 bytes and does not allocate. The live adapter adds a retained last-good RAM
profile, keeping an unsuccessful candidate from replacing it.

## First live integration

Select CAL in the menu. Configure input and output separately from tuner focus.
Patch selected output to the oscillator's 1 V/oct input and its sine output to
the selected input. Set the oscillator near the middle of its range. With the
output at zero, roughly 100–500 Hz is a useful initial test: the +2 V sweep will
raise a normally tracking oscillator by two octaves. Select `run` to start;
select it again, leave CAL, or change either route to cancel.

Nine representable output points (0, 0.25, ... 2 V) are measured. Each point
waits at least 350 ms before accepting whole post-settling detector/level windows,
then requires five fresh pitches within 3 cents total spread. Each point has a
5-second deadline including output acknowledgment. The shared verifier is pinned
to the calibration input; unverified crossing estimates and near-digital-rail
levels do not qualify. This is a conservative initial policy for basic waves,
not a universal confidence classifier or analog clipping detector.

The selected measurement lane and verifier are invalidated when a new output
token is applied; other tuner lanes continue normally. New CSRs expose the
actual pitch/level window endpoints and sample clock. Freshness is based on
those windows and sequence numbers, not on repeated UI frames. Millisecond
conversion uses conservative age rounding. The caller's ISR clock is monotonic.

The CV hardware accepts only nonnegative 0..8000 calibrated counts (0..2 V at
4 counts/mV), acknowledges commands at DAC-stream advancement, and returns to
zero on missed CPU heartbeats (6,000,000 sync cycles, 100 ms at 60 MHz). A fault
requires an explicit disable before re-arming. Other outputs remain zero during
the sweep. The reference-tone feature is removed; idle outputs are always zero.
Completion/cancellation restores zero. Profile points are constructed only after
restoration is acknowledged. The result is lost on reboot. Save/reset operations
are not performed during a sweep, avoiding blocking flash operations while CV
is active. Hardware must still be tested; simulation cannot qualify analog DAC
accuracy, oscillator settling, or physical patching.

Qualified standard r5 archive SHA256:
`78bc8b9135d59e3917087cbe162b170e091e450ad8ca21fc88ec8ab0bd3f22f7`.
Flashed to slot 1 under the shared hardware lock, exit 0 and `Refresh: DONE`.
Saved options were preserved. Live analog qualification is pending user testing.
The user subsequently reported two apparently successful sweeps and an audible
pitch progression matching expectations. This confirms the basic workflow, not
yet voltage metrology, cancellation coverage or corrected-pitch accuracy.

## Next integration steps

1. Qualify the live sweep: actual output volts, correct routing, stable measured
   span, cancellation, missing input, and unchanged four-channel tuning. Check
   the resource/timing budget before expanding its range or output modes.
2. Keep an incomplete candidate separate from the last good profile. Define
   an explicit output policy on cancellation/completion and before re-patching
   the calibration audio input as performance CV. Tuner focus must never alter
   this routing. No other output source may own that output during a sweep.
3. Add versioned, validated profile serialization and an explicit name editor;
   confirm flash region ownership and power-loss behavior before any writes.
4. Feed desired pitch through the profile mapping for corrected CV. The future
   quantizer chooses pitch/scale first and uses the same mapping afterward.
   Preserve a separate, fast CV path: the 50 Hz tuner UI is not an appropriate
   update rate for quantized CV or note-change triggers.

## Pitch origin for corrected playback

The current sweep only records a RAM response and restores zero; it does not
apply the inverse mapping to incoming CV yet. A future performance input needs
an explicit pitch origin (for example, input 0 V means C3 or C4). This logical
input origin is distinct from the physical output voltage needed to make the
oscillator produce that note. The tuning knob changes the measured relationship.
There is no universal oscillator 0 V note. Mapping must reject requested pitches
outside the measured profile; the initial positive-only 0..2 V sweep cannot
provide correction over a full bipolar/multi-octave performance range.

One renderer, one CPU, and the current measurement bank remain shared. Profile
math needs no additional FPGA arithmetic or capture memory. Hardware output
conversion still needs to honor the module's own DAC calibration and limits.

## Corrected-note verification milestone

VERIFY applies the RAM profile's inverse mapping to an explicit note plus
cents offset. This is a manual corrected-pitch test, not incoming-CV playback.
Targets use fixed A4=440 Hz, like the calibration profile; the tuner's display
reference does not change this test. Notes appear as names and octaves, not
numeric semitone indices. PITCH sets the nominal 0 V note (default C4); VERIFY
shows the corresponding ideal 1 V/oct target voltage separately from the actual
profile-corrected output voltage. Changing that origin does not change the
absolute requested note or modify the measured profile. Selecting PITCH, like
any page outside VERIFY, stops the output; Run explicitly to restart.

Hardware test:

1. Run CAL again after loading (profiles remain RAM-only). Keep the same audio
   and V/oct patch and do not move the oscillator tuning knob afterward.
2. Open VERIFY, select a note within its displayed measured range, then
   press Run. The default C4 may be below the measured range of this oscillator.
3. Change note and cents while running. Compare measured Hz and signed cents
   error. Test intermediate notes as well as sweep points; this exercises the
   interpolation rather than merely replaying recorded voltages.
4. Run again or leave VERIFY to stop. An out-of-range target or output fault
   also stops and returns zero; selecting a valid target afterward does not
   re-arm automatically. Press Run explicitly to restart.

The retained profile now keeps its successful route separately from the next
sweep's route. A cancelled/failed sweep cannot silently reroute the old profile.
Targets are rounded to the nearest calibrated DAC count (250 microvolts).
Every changed target clears that detector lane via the existing command token.
Only qualified windows wholly after settling contribute to the error readout;
there is no automatic feedback adjustment hiding profile/interpolation error.
Output acknowledgments are bounded to 100 ms, and the existing hardware
watchdog remains active. Save/reset operations are ignored while output is
active. No additional gateware or renderer resources are required.

Validation: 18 Rust domain/live-adapter tests, including 97 corrected targets
across a nonlinear two-segment profile, route retention, missing acknowledgments,
faults, stale/unqualified measurements, range rejection and explicit re-arming.
The six Python calibration/output/frame tests pass. Standard 1280x720 firmware
build passes using the previously timing-qualified unchanged gateware.
Archive SHA256: `62dd7a85131ddc706116b5b813c8fbc48c0cac2489e6158d52a6547d4a8be7cb`.
Hardware corrected-pitch accuracy remains to be tested.

The user subsequently confirmed that an in-range C5 request produced roughly
522 Hz, with a varying cents readout. The earlier default C4 request was below
the measured range (oscillator near F#4 at zero), correctly stopping output.
This confirms corrected output operation, not yet multi-point accuracy.

Follow-up firmware replaces numeric note labels with note/octave names, adds
the explicit nominal 0 V origin, and distinguishes stopped output from waiting
for settled/qualified detection. Two pitch-unit host tests and all 18 existing
calibration host tests pass; firmware-only build passes, gateware unchanged.
Archive SHA256: `177ac7590cd5a505eac94b01b6cc94c04c657e63991da7acecc75f3f04163fc2`.

## Precision conversion correction

The Generate 3 tests exposed a firmware math defect: micromath 2.1.0's log2
uses an approximate reciprocal for arguments below one. Our frequency/reference
ratio takes that path below A4. At 357.8 Hz with A4=440, its pitch error was
approximately -191.67 cents. This contaminated both stored calibration pitches
and displayed deviations; apparent small errors did not establish absolute
accuracy. The old host adapter silently used standard f32 math and missed it.

All five production frequency-to-pitch conversions now use `pitch_math.rs`:
explicit exponent/mantissa normalization and a five-term centered atanh series,
without platform-dependent logarithm trait calls. The live-adapter tests import
that exact production module; their micromath placeholder is removed.
Calibration rounding also uses the shared module instead of a math trait.

Validation: 22 Rust tests (including 1,700,017 frequency/reference cases from
10 Hz to 24 kHz and A4 references 400..480 Hz in 5 Hz steps). Worst conversion
error against f64 reference is 0.001349 cents. Complete simulated sweeps and
corrected-note verification from 110, 267.9 and 357.8 Hz pass across quarter-semitone
steps (25 cents), including below/above A4. Ideal oscillator output error stays
below 0.16 cents including the 250 microvolt DAC-count rounding; this is a
software simulation bound, not a hardware accuracy claim. Six Python
calibration/output/frame tests and the standard firmware-only build pass.
FPGA logic, memory and timing are unchanged. Re-run calibration after loading;
old RAM profiles were made with the faulty conversion.

Archive SHA256: `9e58ee028835bcf773712270ee01309391453611f75950a630dd5d59dbb8a0f4`.

The user confirmed approximately +/-1 cent per requested note across the
measured 0..2 V range after this fix. This is the working hardware baseline,
based on TUNER's own readout, not an independent metrology specification.

## Sweep density and verification diagnostics

CAL's sweep row selects the existing 9-point plan or a new 25-point plan, both over 0..2 V.
The default remains 9 points. All voltages are first quantized to exact DAC
counts: the dense plan begins 0, 83.250, 166.750, 250.000 mV, etc. The live
adapter now renews the original command during settling, rather than rebuilding
it from the integer-millivolt display value. No guardrails, timing/quality
thresholds, or hardware voltage limits changed. The 32-point RAM capacity and
one-renderer architecture are unchanged. Configuration is snapshotted at start.

A successful profile suggests an in-range whole note only when the selected
VERIFY target is outside its bounds. The menu target is updated without starting
output. Failed/cancelled sweeps do not change the target. Existing valid targets
and their cents offsets are retained.

VERIFY retains instantaneous deviation and adds rolling MEAN/SPAN. Up to 16
distinct qualified pitch sequences at most 500 ms old contribute; at least 8
are required before a summary appears. SPAN is max minus min, not an accuracy
or confidence interval. Invalid data, target changes and stopping clear the
statistics. These values are display-only and never feed the output mapping.

Validation: 28 Rust tests plus six Python calibration/output/frame tests pass.
Both sweep plans complete in the live-adapter simulation, every enabled
heartbeat retains the exact planned count, suggested notes lie inside the
profile, and jitter statistics cannot change the DAC command. Precision math
regressions still pass. Firmware-only build passes with unchanged gateware.
The compiled foreground closure frame is 4,416 bytes (16 KiB main RAM);
this is the closure frame, not a claim about total worst-case call-stack use.
Archive SHA256: `46ab959e438f23aa74648a5ab3f6d34165cbf4a191a72d06710e1b4d8a76d29b`.

Menu follow-up: sweep density is now the third row of CAL, before Run. The
separate SWEEP page is removed; all four rows fit inside the existing menu
without scrolling, geometry/font changes or gateware changes. Editing density
keeps the calibration view visible. A running sweep retains its snapshotted
plan; a newly selected density applies to the next run. The moved density option
uses CAL's persistence key (an older saved SWEEP density defaults to 9 points
until selected/saved again); existing input/output keys remain unchanged.
Firmware build and 17 calibration/display Python tests pass.
Archive SHA256: `4ec895ce96ce249230cd45c0e3e0378c4d08ac70623bff2d2f9ba9fd5a0a1363`.

## Named profile persistence

PROFILES contains Slot (1–4), Name position, Letter, Save and Load. Names are
printable ASCII up to 24 characters; trailing spaces are trimmed. Editing is a
draft, not a mutation of the active curve. Save explicitly overwrites the chosen
slot and verifies an exact readback before reporting success. No save happens
on page entry, calibration completion or boot. Load never enables output;
invalid/empty records do not replace the active profile. Both operations reject
an active sweep/VERIFY. Status remains visible below the menu and resets when
the selected slot changes.

Version-1 records contain magic/version, original input/output route, logical
0 V note, name, point count, all voltage/pitch pairs and CRC32. Records are at
most 296 bytes. Decode validates length, checksum, name, route, origin, bounds
and strict monotonicity; version 1 supports only the current 0..2 V profile.
The positive-only format must be versioned when wider/bipolar ranges arrive.
Keys 0x54555031..34 are checked against current option keys before use.

Storage uses the existing 8 KiB options journal in slot 1 (no flash allocation
or gateware change). The shared persistence helper has a backwards-compatible
opt-in 384-byte scratch buffer for TUNER; existing constructors and callers
retain 32 bytes. TUNER's Settings/Reset now removes only its option keys and
navigation key, preserving profile records. Older firmware with the smaller
journal buffer may not read settings reliably once larger profile records exist.

Validation: 33 Rust calibration/codec/editor/controller tests, six Python
calibration/output/frame tests, plus three tests using the actual flash-journal
library and an 8 KiB simulated NOR device. Coverage includes four full-sized
records alongside 30 option records, 80 updates, interrupted programming and
confirmed garbage-collection/erase transitions, reopen, and option reset without
profile loss. Recovery returns either the prior or complete new record, never a
mixture in these simulations. Physical power-loss behavior still needs hardware
qualification. Firmware-only build passes; FPGA resources/timing are unchanged.

Hardware test: calibrate, name/save profile slot 1, reload TUNER, explicitly Load
that profile, and VERIFY several notes without moving the oscillator tuning knob.
The original patch and nominal 0 V origin should return; output must remain off
until VERIFY/Run. Also try an empty slot and confirm the good RAM profile remains.

Archive SHA256: `79ba29297c9fe2181cd4f39fcacb490de7d3b92e88fae2aac350ce6f248e343d`.

### Calibration menu consolidation and explicit profile confirmation

Removed the standalone PITCH page, which fell back to the tuner scene. CAL now
contains input, output, sweep, 0v note, and run; VERIFY leads directly to PROFILES.
The existing five-row menu supports this without changing the renderer. Moving
the option changes its settings key, so the standalone saved 0 V preference
defaults to C4 until set again or restored by loading a profile. Profile records
and their stored 0 V note are unchanged and remain compatible.

Successful profile Save displays `SAVED SLOT n - READBACK OK` only after exact
record readback; Load displays `LOADED SLOT n - OUTPUT OFF` after validation and
installation in RAM. The active name, point count, and routing remain visible
below the confirmation. To confirm persistence independently of the current RAM
curve, reload TUNER before explicitly loading the saved slot, then use VERIFY.

Firmware-only build and six calibration/output/frame regression tests pass;
the calibration fixture includes 33 Rust tests. FPGA image/timing unchanged.
Archive SHA256: `4e32a108d870137cdc1018001839dd262a8e4f0371514c4fd1bfedcbb8e7d30c`.

## Automatic read-only verification scan

VERIFY now has a MANUAL/SCAN mode selector. Run remains explicit in both modes.
SCAN tests the 50-cent grid inside the measured profile and C0..C8 UI bounds,
including whole notes and halfway points. No extrapolation or new output range
is introduced. The manual note/cents settings do not steer a running scan.

Each target uses the same inverse profile and exact-count output heartbeat as
manual VERIFY. At least eight distinct qualified measurements in the existing
500 ms statistics window are required, with at most 3 cents total spread. Scan
freshness allows the full 100 ms output-ack deadline before 350 ms of settling;
entire pitch windows must follow that interval and window endpoints must be no
more than 100 ms old. A five-second per-target deadline stops missing, stale,
cached or unstable signals. Output fault, absent acknowledgment, mode change,
page exit and a second Run stop output. Completion also requests output zero.

The bounded aggregate retains tested/total count, largest absolute mean error
(shown with its original sign and target), and maximum accepted pitch spread.
Partial results are not complete qualification; there is no automatic pass/fail
threshold, curve update or flash write. Results remain in RAM until replaced by
a new verification/calibration/recall or reboot. Physical accuracy still depends
on the same detector, ADC/DAC calibration, stable oscillator and unchanged patch;
this is not independent voltage or frequency metrology.

Validation: 38 Rust tests, including a complete 49-target simulation with exact
DAC command/routing checks and immutable profile, fractional range boundaries,
fault/timeout/cancellation and invalid-sample cases. Twelve Python calibration,
output, frame and instrument-scene tests pass. Firmware-only build reuses the
qualified FPGA image; no additional FPGA resources. Compiled foreground closure
frame is 4,432 bytes (not total worst-case stack); main RAM has 432 bytes of
static data/BSS and 15,952 bytes allocated to stack.

Archive SHA256: `08ebea4112a1d18763712f63ae921a562c06d2be955545c75e959c650e83fc04`.
Hardware test: load or calibrate with the original audio/CV patch, select
VERIFY / mode SCAN / Run. Expect approximately 48–49 targets for a two-octave
response, a retained error summary, and output zero at completion.

## Low-end discrepancy investigation / stored-point replay

User reports repeatable roughly -5 cents at F#4 -50 cents, corrected output
displayed as 0.012 V, with manual mean about -5 cents and span 1.62 cents.
This reproduces outside the automatic scan. No confirmed cause yet. Inverse
interpolation uses widened integer arithmetic with microvolt rounding; output
rounding is to 250 microvolt counts, about 0.15 cents maximum rounding error at
ideal 1 V/oct, insufficient to explain this discrepancy alone. The sweep waits
for matching command acknowledgment and whole post-settling measurement windows;
no special zero-voltage arithmetic branch was found.

Added POINTS verification mode to replay the exact stored voltages, including
zero, against their stored (possibly fractional-note) pitches. It bypasses inverse
interpolation entirely and retains first/second point errors plus worst error
and voltage. Same watchdog, freshness, stability, timeouts and explicit Run as
SCAN. Switching between SCAN and POINTS stops output. Neither curve nor acquisition
policy changed without evidence. Existing profiles and storage format unchanged.

Tests: 100,000 near-zero interpolation/DAC-rounding cases stay within 0.152 cents
for an ideal linear response. A deliberately biased first point demonstrates
how a +5-cent endpoint recording error can produce a 4–5-cent negative error
near 12 mV; this is a sensitivity test, not a diagnosis of the physical cause.
Live simulations replay every exact 9/25-point DAC count, retain an injected
-5-cent endpoint discrepancy, preserve the curve and stop on mode change.
Six Python calibration/output/frame tests (40 underlying Rust tests) pass.
Firmware-only build; FPGA image and timing unchanged.

Archive SHA256: `9ee6ab6d5a4666c5302e224c350e81dfa7a329989d9221e5495ef7dfd393ae65`.
Next hardware evidence: reload the existing saved profile, run VERIFY/POINTS,
report P0 and P1 and worst error/voltage. Do not recalibrate or retune before
this comparison, which would replace the evidence being investigated.

## Next range: -5 to +5 V (foundation only, not enabled)

User selected -5..+5 V as the next supported output envelope. This is nominally
ten octaves for a 1 V/oct oscillator, not a guarantee of ten measurable octaves
at the current knob position. A precision adder used to shift the envelope must
remain in the same configuration during calibration and playback.

The host-only `calibration/bipolar.rs` foundation defines symmetric representable
voltage plans: 41 quarter-volt points or 121 nominal semitone-spaced points. It
generates points by index instead of retaining another large array and provides
bounded signed payload conversion with symmetric nearest-count rounding.
Tests exhaust all 65,536 payloads, both plans, signed extremes and rounding
around every permitted count. It is intentionally not linked into live firmware.

Remaining integration before enabling/flash:

1. Signed hardware command validation for +/-20,000 counts; verify negative
   payload propagation through the existing calibrated DAC stream and watchdog.
2. Acquire zero first, explore each direction independently, and report the
   contiguous measurable range. Distinguish a range boundary from lost signal
   or output fault. Return to zero between directions; never silently extrapolate.
3. Expand the candidate/profile capacity with a measured RAM/stack budget,
   keeping negative-side results sorted without overwriting the last good curve.
4. Version profile records and qualify flash capacity/garbage collection for
   four full profiles plus settings. Do not simply enlarge records in the old
   journal or reinterpret its geometry; preserve legacy saved profiles.
5. Remove the C0..C8 verification-plan cap where detector capability permits,
   support longer low-frequency acquisition windows, and verify both display
   and output bounds. Full FPGA build/timing qualification precedes hardware use.

No installed behavior or saved-profile format changes in this foundation step.

### Bipolar controller, signed guard, and expanded-storage qualification

Added the signed -20,000..+20,000-count hardware guard. The interface retains
the 16-bit two's-complement bit pattern through the existing ASQ DAC assignment.
An exhaustive gateware simulation covers every 16-bit payload and confirms
out-of-range shutdown, fault latching, explicit rearm, route identity and negative
output watchdog expiry. The live firmware still commands only its old 0..2 V
range; this guard alone does not enable bipolar calibration in the menu.

The independent bipolar controller acquires zero, explores downward, rechecks
zero, explores upward, then rechecks zero again before final disable. An
unmeasurable edge is retained as a limited range only if the origin remains
reproducible; missing origin, changed origin, nonmonotonic measured response,
output acknowledgment failure and clock reversal reject the candidate. The
caller supplies origin tolerance and acquisition policy. This is measured-range
discovery, not a claim to identify an oscillator's electrical input limits.
Candidate points remain sorted and cannot be taken until final disable is
acknowledged. Full dense acquisition stores 121 points; controller size stays
below 1,280 bytes in the host test. Live target stack use still needs checking.

The new host-only version-2 codec supports 121 points in 1,008 bytes, including
name, route, 0 V note, endpoint-limited flags and CRC. It reads old version-1
records without modifying them. Invalid counts, bounds, ordering, routes, names,
flags, lengths and checksums are rejected rather than repaired.

Proposed storage separates the existing 8 KiB journal from a new 16 KiB expanded
profile journal. Tests using the actual sequential-storage implementation pass
with four full 1,008-byte records and 100 updates, plus interrupted GC/write
recovery. The legacy 8 KiB remains byte-for-byte unchanged. This layout is not
yet reserved in the production manifest or used by the firmware; no device
storage has been migrated. All five flash-journal tests and 50 calibration Rust
tests pass, together with seven Python calibration/output/frame regressions.

Remaining live integration: reserve and validate the expanded window, reuse one
flash owner with explicit journal selection, fall back to legacy reads, connect
the new curve/controller to CAL and VERIFY, and check compiled memory use. Do
not expose a +/-5 V menu until all of those pieces are connected.

The full unrotated r5 build with placement seed 15 passes final routed timing:
serializer 439.75 MHz (371.33 required), pixel 90.82 MHz (74.25 required), CPU
69.22 MHz (60 required), and audio 69.72 MHz (12.29 required). Seed 14 narrowly
failed serializer timing; no clock requirements were relaxed. The standard
target now defaults to seed 15; the circular target remains unchanged.
Resources: 17,858/24,288 logic cells, 8,849 flip-flops, 25/56 block RAMs and
10/28 multipliers. Seven additional serializer/bus regression tests pass.
Archive SHA-256:
`624258c52b6b8d6c595b5a2aa0e1fa50f32bd8d0ff1dd8ec30521f93e3cb057a`.
This foundation build was not flashed: the live calibration remains 0..2 V,
and the next hardware test should exercise the integrated bipolar workflow.

### Live bipolar integration (built, not yet flashed)

CAL now uses the zero/down/zero/up/zero controller and retains a sorted measured
profile up to 121 points. VERIFY encodes signed output counts and scans the
measured pitch range rather than clipping its plan to the manual note menu.
Limited-range completion is labeled explicitly; failed/cancelled acquisition
retains the prior profile. Origin rechecks use a 3-cent tolerance; the acquisition
deadline remains 5 seconds per point, so voltage coverage is not a promise of
ten measurable octaves for every oscillator or detector waveform.

Production profile records are now version 2 (1,008 bytes maximum), with legacy
version-1 reads. The archive reserves 24 KiB: the unchanged first 8 KiB remains
the options/legacy journal, and the next 16 KiB holds new profile records. One
flash owner/scratch buffer accesses both with checked explicit windows. New
profile reads fall back to legacy only for absent keys; new profile saves never
rewrite the legacy journal. The flash command generator skips the entire
options reservation unless explicitly asked to erase it.

Qualification: 53 Rust calibration/live-adapter tests, six actual flash-journal
tests, and 15 Python output/calibration/serializer/bus/flash tests pass (the five
flash tests were rerun after correcting their logical-versus-sector-aligned
end-address assertion). Firmware-only rebuild uses the seed-15 timing-qualified
FPGA image. Archive SHA-256:
`65440585718f03eb6e1912c6438e7a06c60ec36b05f59e0c1732054958df8740`.

Stack inspection: main retains 1,152 bytes, run 64 bytes, perpetual closure
5,536 bytes, load_profile 4,112 bytes, save_profile 3,120 bytes. Acquisition tick
has a separate 3,120-byte frame, not nested with profile I/O. Borrowing the one
runtime flash buffer removed 1,136 retained bytes from run; isolating acquisition
temporaries reduced the perpetual closure by 1,120 bytes. These are individual
compiler frame sizes, not a proven whole-program high-water mark. No flash yet.

The user questions retaining both densities; recommendation is to simplify to
121 points only. The current unflashed build still exposes both choices.

### 121-point-only hardware handoff

User approved removing the density choice. CAL now has input, output, 0v note
and run only. Every live acquisition uses semitone voltage spacing (up to 121
points), and old persisted density options are ignored. Existing legacy profile
records remain readable, including smaller point counts. All 53 calibration
tests pass with the live full/partial-range tests using the fixed dense plan.
The perpetual frame is now 5,488 bytes; other frames above remain unchanged.

Built using the previously qualified seed-15 FPGA image and flashed the standard
1280x720 TUNER archive to slot 1 under `/tmp/tiliqua-flash.lock`. No competing
flasher was present; flashing exited successfully. Commands wrote only bitstream,
firmware and manifest, not either profile/options journal. Archive SHA-256:
`b5ab0b2aca6092593abb0eee6eb41fa0302c5f8a9e1b418497846b30ee300383`.
Hardware validation pending: CAL acquisition, VERIFY POINTS, and named-profile
save/recall with the bipolar measured range. Limited-range completion can be
normal when the oscillator/detector cannot cover all ten nominal octaves.

### CAL menu correction after density removal

The first 121-only build retained positional label/format overrides from the
five-row CAL menu: zero_note was labeled sweep, and run was labeled/formatted
as zero_note. Corrected the overrides to the four-row order and added a structural
regression test tying field order, labels and note formatting together. Both
menu/calibration Python tests pass (including 53 Rust tests). Corrected archive:
`a4fca8177fe350c5239fdf0c34f78526b73c23847afd26562f095396dfcc0210`.
Flashed successfully to slot 1 under the shared lock; journals preserved.

### Slow-pitch VERIFY collection

User confirmed the low-end timeout was in VERIFY, not CAL. Inspection found
that the eight-distinct-reading minimum could not fit a 500 ms rolling window
when readings arrive slower than roughly 71 ms. Scan statistics now retain up
to 4 seconds; the eight-reading minimum, 3-cent stability check, fresh/qualified
measurement checks and 5-second target timeout remain unchanged. Manual
statistics still use 500 ms. The live adapter regression covers 100, 250 and
450 ms publication intervals; 54 Rust calibration tests pass through the two
Python calibration/menu tests. Built archive SHA-256:
`92d29d9ac6dce0c65f660a61c464f6ac7338ca94813ea07ebe022566f6ff493a`.

### Adaptive verifier capture — overnight build, not flashed

The reported +2 V / 4 kHz endpoint exposed a fixed capture-rate limit: the
24 kHz verifier requires at least six samples per candidate period. The shared
2048-sample verifier now has four capture modes (24 kHz, full codec rate,
6 kHz and 1.5 kHz), selected by firmware with overlapping hysteresis bands.
Changing rate clears both capture history and cached qualification. Register
0x64 selects the mode; verify_info reports the actual capture divisor.
The matching threshold and minimum candidate lag are unchanged.

At the default 48 kHz codec rate the upper qualification limit is approximately
8 kHz, not an unrestricted ten-octave range. The 192 kHz codec configuration
can qualify higher frequencies, but is not the standard artifact built here.
RTL tests cover 2.5 Hz through 7.9 kHz at 48 kHz and through 24 kHz at 192 kHz;
these are waveform-qualification tests, not an absolute pitch-accuracy guarantee.
The exact cause of the reported -4.4 V endpoint is still unconfirmed.

Measurement freshness now uses the older of the pitch/level timestamps.
VERIFY retains statistics across repeated cached frames, counts only distinct
qualified measurements, and requires a fresh measurement before accepting a
scan result. Invalid or unqualified measurements still clear the collection.
Slow-reading regressions now simulate timestamp aging between publications.

The standard 1280x720 r5 seed-15 build passes: CPU 68.01/60 MHz, pixel
89.59/74.25 MHz, serializer 414.77/371.33 MHz, audio 65.99/12.29 MHz.
Resources: 18,167 LUTs, 8,862 FFs, 25/56 EBR and 10/28 multipliers. Compared
with the preceding build this adds 309 LUTs and 13 FFs, no EBR or multipliers.
No hardware validation or flashing: the rack is powered off.

Final regression run: 40 Python tests passed, including the 54-test Rust
calibration fixture; the three standalone firmware verification-policy tests
also passed. Firmware was rebuilt after the freshness fixes against the new
timing-qualified FPGA image. The perpetual closure remains 5,488 bytes and run
64 bytes (individual frame inspection, not a whole-program stack bound).
Final archive SHA-256:
`27fbebbfe2e5df53a8328681a255c6f26e2489cc611f23739fdf1e4a9a26b3b1`.
Next hardware check: acquire a fresh CAL profile with unchanged oscillator
tuning, record both measured endpoints, then run VERIFY POINTS and RANGE.

### 192 kHz build for the 20 Hz–20 kHz target

User tested the adaptive 48 kHz image: -4.33 V to an upper endpoint in the
6 kHz range. TUNER now defaults to 192 kHz codec sampling (local CLI default;
other bitstreams unchanged). Full-rate capture provides 9.6 samples/cycle at
20 kHz. The shared verifier retains its six-sample guard and matching threshold.
Firmware now allows a full history refill plus eight UI frames before rotating
the verifier to another channel, and resets that dwell after a capture-rate
change. Non-selected lanes retain descriptors in their own capture scale.
Ordinary four-lane crossing measurements remain continuous; harmonic
qualification is still sequential and may take longer for slow inputs.

Validation: 16 sine accuracy cases at 192 kHz (20, 20.37, 55, 997, 7040,
16000, 19753 and 20000 Hz at two phases) pass with less than 2 cents simulated
error. The 47-test verifier/multichannel/calibration/output suite passes;
four integrated capture-CSR cases pass, including newly added 20 Hz and 20 kHz
192 kHz cases. Three firmware policy tests pass. This does not establish
absolute hardware accuracy or universal waveform qualification.

Seed-15 final timing: CPU 64.88/60 MHz, pixel 87.64/74.25 MHz, serializer
441.70/371.33 MHz, audio 69.43/49.15 MHz. Resources: 17,861 LUTs, 8,874 FFs,
25 EBR, 10 multipliers. Perpetual closure frame: 5,504 bytes (16-byte increase).
Firmware-only repack includes the scheduling fix after full FPGA qualification.
Archive SHA-256:
`196ed9b6a970dbf5ed08e9631afd4a8474b2fdea06e46c533b5ac1cbc43b9ef7`.
Flashed successfully to slot 1 under the shared lock after checking for other
flashers. Only bitstream, firmware and manifest were written; journals retained.
Hardware endpoint/accuracy testing is pending.

### Zero recheck recovery and diagnostic

User reported -4.33 V / about 50 Hz, then FAILED - ZERO PITCH CHANGED on
returning to zero. The preceding archive was already the 192 kHz build, not
48 kHz. Inspection found that the first stable off-origin cluster caused an
immediate failure after the ordinary settling interval, even with most of the
5-second deadline remaining. A live regression reproduces that behavior with
an 8-cent temporary offset lasting 1.5 seconds after returning from negative CV.
This is a reproduced failure mechanism, not proof of the rack's actual cause.

The recheck now requires each of its five fresh qualified samples to be within
the unchanged 3-cent origin tolerance. Out-of-tolerance readings reset the
collection and allow recovery until the existing deadline; persistent drift
still fails, disables the output and retains the old profile. CAL shows the
latest ZERO CHECK difference in cents, including after failure. No compensation
or re-anchoring is applied to hide drift. All 55 Rust calibration tests pass,
including temporary recovery, persistent failure and diagnostic values.

Firmware rebuilt explicitly with --fs-192khz against the unchanged qualified
FPGA image (bitstream CRC 3023771414; audio PLL 49.152 MHz). Archive SHA-256:
`ef90648227ea3a82de5d5627d82e944ca9d4a9f87211cfc342d8fc9eee241f85`.
Flashed successfully to slot 1 under the shared lock; no competing flasher,
and neither settings nor profile storage was erased. Hardware confirmation
is pending; if failure recurs, capture the displayed ZERO CHECK deviation.

### Retained tracking-failure evidence

User reached about +3 V / 8 kHz, then FAILED - NOT TRACKING; zero check -2.50c
was within tolerance. This error occurs when a new point cannot be inserted
into the strictly increasing voltage/pitch curve; its cause is not established.
The sweep now retains the rejected point and adjacent accepted endpoint before
discarding its candidate. CAL displays PREV and FAIL as signed voltages plus
note/octave/cents, and PITCH STEP as a signed cent difference. These diagnostics
survive output restoration and subsequent idle frames, and clear on a new run.
Acquisition thresholds and failure behavior are unchanged.

The 56-test Rust calibration suite (via two Python tests) passes, including
upward octave-drop and downward flat-pitch rejection, exact retained voltages,
pitch differences, preservation of the old profile and disabled output. Firmware
was repacked with the unchanged qualified 192 kHz FPGA. Perpetual frame is
5,552 bytes; this is an individual frame size, not a full stack bound.
Archive SHA-256:
`28770b4d5c66dfee3ffec7e7ab8a05d3c7b1266ccd389a6a8bf4c12f1754f375`.
Flashed successfully to slot 1 under the shared lock, with no competing flasher.
Settings/profile journals were not erased. Next check: reproduce the failed CAL
sweep and photograph PREV, FAIL, PITCH STEP and ZERO CHECK together.

### Ascending acquisition and octave-drop isolation

Photos established a -4.34c zero-return difference on one run; another showed
+2.9167 V / B8 -49.1c followed by +3 V / C8 -47.7c, a -1098.61c step.
That is consistent with a one-octave discrepancy but does not establish whether
the raw crossing detector, verifier or incoming waveform caused it. Eighteen
additional actual-verifier RTL sine cases (7.6–20 kHz, including dense checks
around 8 kHz, amplitudes 4000 and 20000 counts) all return factor 1. The hardware
octave failure is therefore not yet reproduced or claimed fixed.

The controller now performs a zero-signal preflight, then one strictly ascending
-5…+5 V pass. The preflight pitch is not inserted into the curve. Unmeasurable
leading points are skipped after their bounded measurement deadline; once
acquisition starts, the first missing point ends the contiguous range. Zero
must have been measured during that pass; the final repeatability check uses
that point, retaining the 3-cent tolerance and five fresh qualified readings.
The final output-disable acknowledgement still gates publication. Searching
unmeasurable low points may take 5 seconds per point; worst-case acquisition is
longer than the former outward scan, intentionally keeping confidence unchanged.

Non-monotonic candidate points now retry only within their original deadline.
No point is inserted, skipped or octave-corrected to force monotonicity. Persistent
failure still restores zero and keeps the old profile. Transient failures that
recover clear their diagnostic. Failure UI adds RAW frequency / applied divisor
from the last reading of the rejected cluster, to distinguish raw-detector errors
from verifier octave division. This is a representative reading, not the cluster
mean shown by the stored PREV/FAIL pitch values.

Validation: 58 Rust calibration tests via the two Python calibration/menu tests,
three firmware verifier-policy tests and 18 new high-level verifier RTL cases
pass. Firmware-only build uses the unchanged timing-qualified 192 kHz FPGA;
the perpetual frame is 5584 bytes (individual frame, not a full stack bound).
Archive SHA-256:
`f47fc71001e1d104f5b6f40227a07e1f0a144c25ed68292144d11e1e38146536`.
Flashed successfully to slot 1 under the shared lock after checking for competing
flashers. Profile/settings journals preserved. Hardware validation remains:
repeat CAL and capture the RAW/divisor line if the octave rejection recurs.

### False octave division: retained verifier evidence

The next photos show RAW 7678.01 Hz /2 at +2.9167 V, with a -1098-cent
rejected step. CAL has failed, not completed; no new profile is available to
VERIFY. This establishes the applied division, but does not establish why the
first candidate was rejected. The exact frequency at two amplitudes, plus four
phases with continuing capture and a finite crossing-window lag, all qualify as
factor 1 in RTL simulation. No detector fix is claimed from those passing tests.

The verifier now retains the first candidate's accumulated absolute error and
peak-to-peak span in two read-only registers (0x68 and 0x6c). Firmware snapshots
them before requesting another check. The failure screen retains capture-sample
lag/divisor and 1X mismatch percentage (threshold still 5%) alongside RAW/factor.
This adds no sample memory or multipliers and does not loosen calibration
qualification or force monotonicity. A subsequent failing hardware photo is
needed to distinguish a capture-scale discrepancy from actual mismatch.

CAL without a completed profile now says so explicitly instead of claiming an
unsaved RAM profile. VERIFY refuses manual, points and range modes without both
a completed profile and its route. Existing completed profiles remain preserved
across failed replacement scans.

Validation: 67 Python checks pass (including the wrapper for 62 Rust tests).
Full r5 192 kHz / unrotated 1280x720 build passes seed-15 timing: CPU
68.97/60 MHz, pixel 91.83/74.25 MHz, serializer 406.17/371.33 MHz, audio
68.39/49.152 MHz. Memory remains 25/56 EBR and multipliers 10/28; 8926 FF.
The perpetual foreground stack frame is 5664 bytes (individual frame only,
not a full nested/interrupt stack bound), main remains 1152 bytes.
Archive SHA-256:
`475c0cc804e9df81003492861056580f8566e3f6f06012d3ed72bc2be5484246`.
Flashed successfully to slot 1 under the shared lock; option/profile storage
was not erased. Hardware investigation of the false division remains open.

### Residual-margin candidate selection

The next hardware photo reports lag 25.020 samples, capture divisor 1, RAW
7674.02 Hz /2, and first-candidate mismatch 5.04%. The capture scale agrees
with 192 kHz. A hard first-match threshold can reject a slightly noisy one-period
comparison and accept a barely better two-period comparison, falsely halving
the reported pitch. A deterministic noisy-sine RTL regression reproduces that
failure (old factor 2, corrected factor 1). This models the threshold failure,
not the still-unmeasured physical source of the rack waveform's mismatch.

Keep the immediate factor-1 path when its residual is <=5%. Otherwise evaluate
the bounded 1x..4x candidates using one common amplitude reference (the first
candidate's span). The best residual must still pass the 5% gate. Choose the
shortest candidate within 1/128 of peak-to-peak amplitude of that best residual:
0.78125 percentage points, implemented as 2*span for 256 comparison pairs.
Thus a near-tie does not justify octave division. A selected shorter candidate
can have up to 5.78125% residual, but only with an independently passing longer
candidate nearby in residual. This is waveform similarity, not cents tolerance.
Clear harmonic differences still select 2x/3x/4x; excessive noise is rejected.

Candidate storage/comparison adds logic but no EBR, multiplier or divider.
The maximum remains four candidates and under 7300 sync clocks. Reaching a
history bound selects among candidates already measured; clear/overwrite still
abort without publishing a factor. CAL's pitch stability, monotonicity,
freshness, zero-return and output-disable/publication checks are unchanged.

Validation: the threshold-cliff regression first failed with old factor 2, then
passed with factor 1. The larger suite passes 116 tests with two pre-existing
expected raw-crossing harmonic failures; an additional low-frequency history-
boundary test passes separately. The suite includes the 62 Rust calibration
tests. Full r5 192 kHz / unrotated 1280x720 seed-15 timing passes: CPU
68.24/60 MHz, pixel 89.91/74.25 MHz, serializer 423.73/371.33 MHz, audio
68.75/49.152 MHz. Nextpnr reports 17537/24288 LUT4s, 9049 FF, 25/56 EBR,
10/28 multipliers. Archive SHA-256:
`88b3cd938d7ee5c8247295d0047774bcf46734740a9386c986d5ad525c84aaf3`.
Hardware validation remains: repeat CAL, check its achieved range, then VERIFY
the completed profile. Simulation fixes the demonstrated selection failure;
the physical source of the measured residual has not been established.
Flashed successfully to slot 1 under the shared lock, preserving option/profile
storage. Flash log: `/tmp/tuner-residual-selection-flash.log`.

### Pre-stop waveform capture

Hardware still selects /2 at lag 25.012, RAW 7678.01 Hz, first residual 5.08%.
The residual-margin regression is not a reproduction of the physical cause.
Do not increase acceptance thresholds again without observing the samples.

On the first rejected CAL point, firmware arms a diagnostic latch. Capture
continues during the normal bounded recovery attempts. The next lane clear
(normally output-stop) freezes the existing 2048-sample verifier memory before
the clear, retaining its write head. A recovered point cancels the diagnostic.
The readback multiplexes the existing memory read port, adding no sample RAM.
This is recent history at the rejected voltage, not necessarily the exact
earlier window whose score was shown. Words export oldest-first as signed 16-bit
hex, with sample rate, capture divisor and candidate lag metadata.

After CAL stops, a non-blocking UART pump runs each 5ms UI tick, at most 64
bytes per call and without spinning on TX readiness. A one-byte UART may take
roughly a minute to export all samples. A 180-second deadline releases capture
if no reader is present; starting CAL/VERIFY also releases it. The waveform
verifier is paused while this diagnostic memory is held; crossing/level lanes
and UI continue. The synchronous global UART logger remains disabled.

`tests/capture_tuner.py --output /tmp/tuner-capture.json` discovers the sole
1209:c0ca Tiliqua serial device with DTR asserted and RTS low. The apfbug
bridge requires DTR to forward UART bytes; DTR low discards them. It accepts only a
complete framed 2048-word capture, otherwise reports an error. No automatic
calibration start or output-voltage command is introduced.

Validation: 71 verifier/calibration Python tests pass, including preservation of
all 2048 samples across wraparound and subsequent clears, and release without
stale qualification. Full 192 kHz/unrotated 720p seed-15 build passes CPU
70.30/60 MHz, pixel 91.01/74.25 MHz, serializer 439.95/371.33 MHz and audio
65.79/49.152 MHz. 17482 LUT4, 9076 FF, unchanged 25 EBR/10 multipliers.
Foreground stack frame 5840 bytes (not a full nested stack proof).
Final firmware repack includes the 5ms non-blocking export schedule and
180-second timeout. SHA-256:
`8010e366711c3fb6cf42f0a0c7b5fe2f820d736e267de51fb2c3535fdd68eb94`.
Flashed successfully to slot 1 under the shared lock, preserving profiles and
options. USB capture listener started on the identified Tiliqua device.

Diagnostic follow-up: the first reader incorrectly left DTR low; the corrected
reader also timed out without a complete capture. Added a repeating idle
`CAPTURE READY` heartbeat to establish the transport before another scan and
extended the host listener's default lifetime to one hour. Also corrected the
freeze trigger: `cal.changed` does not fire on disable. An armed diagnostic now
freezes on the disable command itself, before the DAC returns to zero. A
peripheral-level regression covers this without relying on a channel switch.

Validation of this follow-up: 72 verifier/calibration tests plus the mocked
serial-handshake/parser test pass. Full build final clocks: CPU 66.77/60 MHz,
pixel 86.01/74.25 MHz, serializer 438.40/371.33 MHz, audio 68.70/49.152 MHz;
25 EBR and 10 multipliers. Final firmware repack SHA-256
`86c48de4e9a9389e4d526f4f16294b698ce29054a675bb38667b4cef216cf630`.
Flashed slot 1 successfully; settings/profiles retained. Waiting for the
physical UART heartbeat before requesting another CAL run.

### Physical waveform received

The ready heartbeat was received and the next failed CAL exported all 2048
samples. Fixture: `tests/fixtures/tuner-alternating-cycle-capture.json`.
Header: 192000 Hz, divisor 1, lag 6402/256, raw 7676.013 Hz, selected factor 2.
Offline normalized residuals for 1/2/3/4 periods are
5.04147%, 0.13939%, 5.02542%, 0.21875%. Replaying the physical samples through
RTL reproduces factor 2 and matches the software first-error and span exactly.
Thus this is not an FPGA-only interpolation/scoring error. Adjacent cycles
in the captured input differ; alternate cycles repeat very closely. This does
not establish whether the variation originates in the oscillator or acquisition
path. Do not assume a stable nominal V/oct source has identical cycles, nor
silently weaken qualification to force an expected calibration curve.
Next hardware isolation: compare a second sine source near the same frequency
and/or inspect the original source independently. No detector thresholds or
calibration acceptance limits changed after receiving this waveform.

### Idle output zero investigation

Twin Waves photos show 1001.24 Hz with Disting EX nominal zero and 1064.78 Hz
with idle Tiliqua OUT 1: +106.52 cents, equivalent to +88.77 mV at ideal
1 V/oct. This is a relative inference, not an absolute voltage measurement.
TUNER's gateware commands calibrated zero on every inactive output. Startup
used the same load-or-default path as XBEAM, but hid EEPROM fallback because
the blocking logger is disabled. Added non-blocking idle UART reporting of
EEPROM/default selection and OUT 1 gain/offset plus stored/hardware fractional
bits, preserving the same loading behavior. No EEPROM writes or compensating
offset were introduced. Direct jack-voltage measurement requested before any
correction. Firmware-only build and three host wrapper tests pass; flashed
slot 1, SHA-256
`bc7cefaf8e2424ae8b52946c84125b975af4fbd7252a76eeb31abf17b36d0fb5`.

After output-zero diagnosis, planned scan changes: distinguish low-end
plateaus from internal tracking faults, discover usable range before precise
acquisition, and present valid candidate coverage with Accept/Adjust & Rescan/
Cancel. Preserve saved profiles and block acceptance of unverified curves.

### Leading audible plateau discovery

UART confirmed `CAL SOURCE EEPROM OUT1 A=29555 B=54 FBITS=15 HWBITS=15`:
stored calibration loaded, with matching fractional precision. The user's
Disting input monitor remained near -0.026 V both disconnected and connected
to idle Tiliqua OUT 1. This does not corroborate the inferred +88.77 mV offset;
neither the unplugged baseline nor the pitch comparison establishes absolute
jack voltage. Output coefficients remain unchanged.

Twin Waves capture `/tmp/tuner-zero-followup-capture.json` contains 2048 samples
at 24 kHz, approximately 79.29 Hz; software selects the first period with
0.0873% mismatch. This supports separating its low-end plateau from the
Generate 3 high-frequency alternating-cycle failure.

Acquisition now holds a single starting point provisionally. Consecutive
qualified pitches within 10 cents (or the configured stability tolerance if
larger) replace that point and mark the lower range limited. A responsive
positive step establishes the curve; thereafter existing strict monotonic
checks still apply. A missing leading measurement clears the provisional
point instead of bridging a gap. All-flat scans and initial octave drops
still fail. This is lower-boundary discovery within the existing upward pass,
not yet the separate discovery/accept/rescan workflow. No additional FPGA
resources or sample buffers are used. Host tests cover noisy leading plateaus,
all-flat rejection, interior flat/octave failures, initial octave failure,
and provisional gaps. Firmware archive SHA-256:
`3cf5dd1ecd80c0ba17d32479d39b0bf9c6b501cdc2773deaa6092f7856010058`.

### Serial result visibility

The next Twin Waves run failed at displayed point 91/121; the user reported
OUT 0.000 V after restoration, not the rejected voltage. The serial reader
received repeated calibration-source heartbeats but no waveform export.
Thus transport was alive; the precise reason for the absent capture is not
yet established. Added repeated non-blocking CAL STATUS, rejected/previous
points, detector and verifier details, plus explicit capture timeout or
incomplete-history status. Host reader now saves a `.serial.log` transcript
and supports `--monitor` to continue after a waveform export. Firmware-only
build and calibration/reader tests pass. Flashed slot 1, archive SHA-256:
`bc7dfd8dd8358308bdf5241d136ecf384a47aff138c27d0b18f6fd79b31cff1e`.
No detector thresholds or output calibration coefficients changed.

### Confirmed upper plateau

The serial-status build exported the full Twin Waves waveform successfully.
It rejected +3.416750 V at 12307533 millicents, after +3.333250 V at
12307624 millicents: -0.091 cent, with raw frequency 10000.000 Hz and factor 1.
The captured waveform independently selects factor 1 (0.324% mismatch).
This is consistent with an upper pitch ceiling, not the earlier Generate 3
octave-selection failure. Local evidence is saved in
`/tmp/tuner-serial-status-capture.json` and its `.serial.log` transcript.

Upper-boundary handling now requires three successive qualified, stable
measurements at increasing voltages, all within 10 cents of the SAME last
retained pitch. Only applies after tracking has been established and zero
has been measured, on the positive side of the sweep. Probe points are not
stored. Confirmation ends the contiguous curve as limited-high and still
requires the final zero check and output-disable acknowledgment. An octave
drop, resumed pitch movement after a flat spot, missing probe measurement,
or insufficient remaining voltage steps fails instead of silently bridging
the questionable region. This bounds the usable range; it does not assert
that an oscillator can never resume tracking at a higher voltage.

Tests include an end-to-end live-controller model with a -4 V CV floor and
10 kHz pitch ceiling, noisy upper plateaus, incomplete/unqualified probes,
and existing transient/persistent tracking fault safeguards. These changes
are firmware-only; shared hardware and output calibration are unchanged.
Build and flash completed successfully to slot 1. Archive SHA-256:
`929d0087307952b8b521b2d8476ed312d2a82f94062bea545a3e61fdc41003ab`.

Hardware validation: Twin Waves calibration completed limited-range with 91
retained points. POINTS verified 91/91, worst -1.27 cents at -3.2500 V;
P0 +0.00, P1 -0.07 cents. SCAN verified 168/168, worst +7.57 cents at
D#9 +0.0 cents, max span 1.80 cents. The latter is near the upper pitch
ceiling; successful stored-point replay does not establish accurate
interpolation across the final partially clamped interval. That endpoint
interpolation remains to investigate; no accuracy fix is claimed here.

Added read-only serial verification summaries: mode, tested/total, completion,
worst signed error and pitch, stored voltage for POINTS, first two errors,
maximum span, current target/error/statistics, zero recheck, and profile
voltage/pitch endpoints. Reports repeat using the existing non-blocking
transport; no additional FPGA resources. Formatter is exercised by host
tests for both scan modes and absent results. Host transcripts retain these
lines automatically. The fixed report buffer grows by 512 bytes; an overflow
is explicitly reported instead of silently presenting a truncated summary.
Firmware build and slot-1 flash succeeded; archive SHA-256:
`3afce2f3ef2b3432772854384364e52dbc001d1cde2537ded3f74234c1336560`.

### Saturated endpoint interpolation

Repeated serial SCAN: 168/168 complete, worst +7.57 cents at D#9,
max span 2.08 cents. Before the final region, the reported worst remained
-2.69 cents at G2 -50 cents. Transcript:
`/tmp/tuner-verify-followup-capture.serial.log`.

A host model (1000 Hz at zero, ideal exponential tracking clipped to 10 kHz)
reproduces roughly +7.6 cents at D#9 when the 3.333250 V saturated point is
retained. Exact point replay cannot expose this error: the interpolated
interval crosses an unknown clipping knee. After three plateau confirmations,
acquisition now removes the saturated anchor, ending at its preceding point.
This deliberately sacrifices one voltage-grid step rather than claiming
accurate interpolation through the knee. Saved profiles are not rewritten;
new acquisition is required. Finer boundary acquisition remains future work.

The regression first failed with the old retained endpoint, then passed with
the fix. All half-semitone targets in the resulting modeled profile, including
DAC quantization and independent logarithmic evaluation, remain within 0.2
cents in the idealized model; this is not a hardware accuracy claim.
Calibration and serial host tests pass, including 72 Rust fixture tests.
Firmware-only build and slot-1 flash succeeded; archive SHA-256:
`1a675dd9eba133c310c4ff1b0d9f610fa1539165df42f67d4050a182f74baf4a`.

Hardware check on this build completed with 90 retained points, output range
-4.166750 to +3.250000 V, pitch D#2 +41.0 cents through D#9 -11.3 cents.
Zero recheck was -0.96 cent. VERIFY SCAN completed 167/167 targets, worst
-3.01 cents at G2 -50 cents, maximum span 1.79 cents. First errors were
-1.14 and -0.77 cents. Output returned to zero. Transcript:
`/tmp/tuner-ceiling-check-capture.serial.log`.
The previous D#9 +0-cent target is now outside the claimed usable range;
this validates conservative range exclusion, not improved tuning at 10 kHz.
The remaining low-register error is roughly consistent with previous runs
(-2.58 to -2.69 cents near the same target) and has not been corrected.

### Low-register investigation

Production detector RTL simulation at 95.209 Hz, 192 kHz sampling, clean
sine amplitude 19500 counts: four settled updates averaged -0.008 cents,
maximum absolute error 0.33 cents. Log `/tmp/tuner-low-register-probe.log`.
This short synthetic check does not reproduce the physical -3-cent error
and does not rule out waveform, output, drift, or acquisition differences.
Do not apply a compensating offset from that single hardware result.

Added read-only serial details for the worst interpolated target: requested
and DAC-quantized command in microvolts, surrounding stored voltage/pitch
points, and estimated rounding contribution on that segment. This estimate
is not physical jack-voltage accuracy. Tests cover exact knots, positive
and negative rounding, and absence of fabricated results before measurement.
Firmware-only build succeeds; awaiting preservation of the user's existing
RAM profile before flashing so the same curve can be examined after reload.
User confirmed saving the current curve in calibration profile slot 2.
Flashed the diagnostic update to bitstream slot 1, preserving profile storage.
Archive SHA-256:
`631c533abacea53433a994164e19c796b2148febe6410c5d38da5a7d116ef214`.
Serial monitor reconnected; next comparison uses recalled profile 2 without
retuning or reacquiring the curve.

### Automatic local verification follow-up

Recalled-profile SCAN completed 167 targets with worst -2.37 cents at
G2 -50 cents, maximum span 2.06 cents. The surrounding stored commands
were -3.583250 V and -3.500000 V; the target command was -3.551250 V.
Estimated DAC rounding contribution was only +0.013 cents. Transcript:
`/tmp/tuner-local-error-capture.serial.log`.

SCAN now automatically remeasures the two stored endpoints surrounding its
worst target, then the target itself. POINTS remains unchanged. The screen
shows LOCAL CHECK progress; serial reports each measured mean/span and the
target error after subtracting the voltage-weighted endpoint errors.
This is diagnostic only: sequential measurements can still include drift,
and neither the profile nor output correction is modified by these results.
Existing settling, fresh-sample, quality, timeout, and cancellation checks
apply to all three follow-up measurements. Completion returns output to zero.

Host calibration and serial tests pass (three pytest wrappers), including
local residual arithmetic, full-scan follow-up, profile preservation, timeout,
and leaving VERIFY safely. Firmware-only 192 kHz / unrotated 720p build and
bitstream-slot-1 flash succeeded; profile slot 2 is preserved. Archive SHA-256:
`d9c003669ad7a86631e73eea6d289cdb376c67078386756326e2913e9e28875b`.
Serial capture is `/tmp/tuner-local-check-capture.serial.log`; physical
follow-up results are pending recalled-profile VERIFY SCAN.

Physical recalled-profile SCAN completed 167/167, worst -2.15 cents at
G2 -50 cents, maximum scan span 1.80 cents. Automatic local check completed
3/3 and returned output to zero:

- Lower stored endpoint -3.583250 V: mean -1.31 cents, span 1.27 cents.
- Upper stored endpoint -3.500000 V: mean -1.41 cents, span 0.00 cents.
- Target -3.551250 V: mean -3.22 cents, span 1.29 cents.
- Endpoint-adjusted target error: -1.88 cents.

Thus the target has an additional local residual beyond the roughly
-1.35-cent endpoint offset during this follow-up. Its initial scan error
and remeasurement differ by 1.07 cents; a single sequential triplet does
not establish pure interpolation curvature or justify a compensating offset.
Zero reported span is not proof of physical noiselessness. Preserve the
profile; any refinement should use independently validated measurements
rather than applying this one residual as a correction.

### Repeated local checks

The follow-up now measures nine fresh settled windows: LOW/TARGET/HIGH,
HIGH/TARGET/LOW, LOW/TARGET/HIGH. Repeating the target between endpoints
and reversing the middle pass exposes repeatability and order sensitivity.
Serial reports each location's average error, maximum within-window span,
between-repeat mean range (REPEAT_C), each pass's endpoint-adjusted residual,
and the average residual. These remain diagnostics, not profile corrections.
In particular, the endpoint adjustment is voltage-weighted, not a claim to
remove temporal drift. The profile is unchanged; all completion, timeout,
and cancellation paths retain output-zero behavior.

Host tests pass (three pytest wrappers), including distinct per-pass biases,
measurement order, incomplete-result rejection, and timeout/cancel during
both the first and last pass. The full scan fixture checks profile preservation
and a serial result under 768 bytes. Firmware-only build and bitstream-slot-1
flash succeeded; no new FPGA hardware. Archive SHA-256:
`8cb09407c3f963dc16f7717c8fc1c022a46f9e0fe00792e161c75ef582183085`.
Serial transcript: `/tmp/tuner-local-repeat-capture.serial.log`.
Next hardware check: recall profile 2, then VERIFY SCAN without retuning.

Repeated hardware check completed 167/167 plus 9/9 local windows, output
returned to zero. Scan worst -2.21 cents at G2 -50 cents; maximum span 2.68.
Local lower/upper/target average errors: -1.34 / -1.25 / -3.13 cents.
Between-repeat mean ranges: 0.05 / 0.22 / 0.16 cents respectively.
Endpoint-adjusted residuals: -1.84, -1.70, -1.94 cents (average -1.83).
This supports a repeatable local departure from the stored linear segment;
it does not isolate oscillator transfer curvature from detector/output effects.
In particular, the roughly -1.3-cent endpoint bias remains separate.

Added `Profile::refined_with` as non-live groundwork: it builds a separate
candidate from an already qualified interior voltage/pitch measurement,
preserving all original anchors, bounds, flags, name, and the 121-point cap.
It refuses duplicate voltages, pitch reversals, full tables and range extension.
Tests cover source immutability, unchanged outside segments, storage round-trip,
and independent validation targets in a smooth synthetic curvature model.
The model's maximum residual falls from about 2 cents to about 0.5 cents;
this is not a hardware claim. Three pytest wrappers pass.

No live caller exists yet, no diagnostic is converted into a correction,
and no saved profile is changed. Next integration must acquire a qualified
point, stage the candidate separately, validate independently (including
neighboring intervals), and require acceptance before replacing a profile.
Full 121-point tables must report no refinement capacity, not silently drop
anchors. Existing-profile endpoint drift must not be disguised as curvature.

### Live staged refinement

VERIFY now offers REFINE, ACCEPT and DISCARD after RUN. The five-row menu
viewport scrolls to keep the selected item visible; geometry and renderer
hardware are unchanged. Start with a completed SCAN (including local checks),
then choose REFINE. It reacquires nine settled endpoint/target windows rather
than reusing the old scan measurements. Only one interior point is proposed
per operation; repeated operations require a new scan after acceptance.

Qualification requires a same-sign local residual of at least 1 cent, no more
than 0.75 cent spread between pass residuals or location means, endpoint bias
within 3 cents, and target error within 10 cents. Larger endpoint bias requests
recalibration. The new point uses its absolute measured pitch, not the
endpoint-adjusted diagnostic residual. The original anchors remain untouched.

The separate candidate is compared against the original at two new pitches
on either side of the inserted point and the midpoint of each adjacent
untouched segment, when available. These are not the fitted point or the old
target. Each target runs original/candidate/candidate/original with independent
settled windows. A candidate is offered only if repeat measurements agree
within 0.75 cent, no tested pitch worsens by more than 0.5 cent, at least one
interior test improves by 0.5 cent, and the tested worst absolute error does
not increase. This is local validation, not a full-range accuracy guarantee.

Completion and faults stop output. ACCEPT is refused until output-disable
acknowledgment and only replaces the RAM profile; saving remains explicit.
DISCARD preserves the original. Missing pitch, stale/unstable windows,
missing acknowledgment, output fault, mode change and cancellation invalidate
an active candidate. Full tables refuse refinement; nothing is silently removed.
Serial reports progress, each paired comparison, repeat spread and worst errors.

Host tests cover the nonlinear acquisition/validation path, route and signed
commands, original immutability throughout, explicit acceptance/discard,
pending output-disable acknowledgment, failure paths in both phases, capacity,
drift/noise rejection, no-gain/regression rejection, and serial bounds.
Three pytest wrappers pass; production firmware-only build succeeds.

Compiled-memory review prompted separating sweep and verification stack frames:
the tick dispatcher tail-jumps, verification uses 272 bytes, refinement record
2096 bytes, and candidate construction 1072 bytes. Foreground retained frame
is 9040 bytes; main 1168 and run 80 bytes. These are individual frame checks,
not a formal full call-tree/interrupt bound. The sweep frame is not nested
under refinement. Existing 16-KiB main RAM and FPGA hardware remain unchanged.
Archive SHA-256:
`fa23cf1703904f036e928c2dbab4a2df7c05df7ab86cdee65ec30f89d5bf1451`.
Slot-1 flash completed with Refresh DONE; profile storage preserved. Serial
monitor reconnected to `/tmp/tuner-refinement-live-capture.serial.log`.
Hardware acceptance is pending: recall profile 2, VERIFY SCAN, REFINE,
inspect comparison and choose ACCEPT or DISCARD. Saving remains a separate
user action; preserve slot 2 as the baseline during initial comparison.

### Loading freeze / compact candidate correction

User reported a freeze when loading profile 2 on the first live-refinement
build. Serial stopped during the initial status report, without a successful
load report. Stack exhaustion is the leading diagnosis, not a hardware-proven
trace: the 9040-byte foreground frame plus 4112-byte load frame and nested
journal/interrupt work had insufficiently audited headroom. Earlier review
focused on refinement and missed the existing loading path.

Refinement now retains one proposed Point, not a second Profile. Candidate
voltages are evaluated as a virtual insertion using the same integer rounding;
only explicit acceptance materializes the full profile. Tests compare virtual
and materialized results at every integer target across three signed/unsigned
voltage offsets, including out-of-range targets. A size regression enforces
Refinement <=768 bytes on the host. All live workflow tests still pass.

Profile decoding is now a separate non-inlined phase, keeping its profile
temporaries out of the frame invoking the flash journal. Compiled foreground
frame is 8048 bytes (was 9040), load_profile 1056 (was 4112), decode_profile
3088, and refinement record 176 (was 2096). Loading and decoding frames still
nest; the key gain is separating decoder temporaries from journal-read calls.
These remain individual frame measurements, not a complete stack proof.
No persistent calibration or EEPROM bytes were edited. Tests and firmware-only
192 kHz / 720p build pass. Archive SHA-256:
`adb0e6cbc300a95048e97cd50e2df6bb32f76348a399318ee1ff3597f6c6fe7d`.
Flash to bitstream slot 1 completed with Refresh DONE. Serial reader is
connected at `/tmp/tuner-refinement-memory-capture.serial.log`. First hardware
check is loading profile 2 and confirming responsiveness, before any scan.

### Hardware refinement acceptance and fresh-baseline verification

Loading succeeded after the compact-candidate correction. Refinement completed
9 acquisition and 16 independent comparison windows. Interior errors improved
from -3.61 to -1.28 cents and -3.65 to -1.64 cents; neighboring comparisons
were -3.85/-3.85 and -3.15/-3.26. Acceptance produced 91 RAM points.
The following 167-target scan completed, worst -3.73 cents at F#2. Local
stored endpoints read -2.41/-2.56 cents, indicating an offset relative to the
stored measurements as well as a local residual; its physical cause is not
isolated. Do not assume every changed residual is stationary curvature.

A fresh calibration produced 90 points, -4.166750 to +3.250000 V. Its scan
completed 167/167 plus nine follow-up windows, worst -1.72 cents at C#9 -50c,
maximum within-window span 2.66 cents. First-point errors were -0.33/+0.07c.
Local endpoint means were -0.11/+0.23c, target -1.34c, adjusted residual
-1.43c; individual pass residuals -0.82/-1.80/-1.67c exceed the existing
0.75c repeatability allowance. These observations do not justify another
correction point without fresh qualification. Serial evidence remains in
`/tmp/tuner-refinement-memory-capture.serial.log`.

User's calibration-slot map (distinct from bitstream slot 1):
1 original Generate3; 2 original Twin Waves; 3 refined Twin Waves;
4 newest Twin Waves baseline. Preserve these slots; no automatic profile writes.

Completed local checks now show the existing refinement acquisition gate's
advice on-screen and over serial. The gate is shared with live refinement to
prevent divergent thresholds. Advice is local, not a full-range certificate;
REFINE still reacquires measurements and validates independent targets before
offering acceptance. No algorithm thresholds or profile format changed.
