# Automatic calibration — September 19, 2026

This is the current UI/workflow specification. It supersedes the manual
VERIFY/REFINE instructions in older investigation documents. The state machine
is host-tested and has completed an automatically verified Generate3 FUNDAMENTAL
hardware run. Dated validation below records its limits and subsequent changes;
one successful run is not broad oscillator qualification.

The graded acceptance-policy rationale and published-product comparison are in
[CALIBRATOR_COMPARISON.md](CALIBRATOR_COMPARISON.md). The first implementation
is now present, but its thresholds and partial-range behavior still require
physical qualification across the oscillator matrix.

## Simple workflow

An automatic paired refinement comparison that fails repeatability gets at most
one fresh local retry per run. It reacquires the local measurements and repeats
the paired tests on the unchanged curve; it does not restart acquisition or
relax the 0.75-cent repeatability limit. The retry counts toward eight attempts
and must reserve time for a complete recheck within the existing 15-minute
deadline. Persistent instability preserves the best checked curve. Serial
reports `AUTO UNSTABLE_RETRY=1/1` when used.

- TUNER observes audio inputs, with spiral and linear views.
- CAL selects the audio input, CV output, nominal 0 V note, and policy. RUN first seeks
  a stable measurable reference from 0 V upward, then starts an upward -5..+5 V
  measurement, automatically checks the resulting curve, then
  attempts guarded improvements when appropriate. RUN again cancels.
- AUTO is the default: it attempts the two-cent Precision objective, then may
  offer a safe Musical (at most 5 cents) or Character (at most 10 cents) result
  with an explicit grade. PRECISION accepts only Precision. FORGIVING uses
  wider acquisition/replay tolerances but does not relax ambiguity,
  monotonicity, routing, output-acknowledgement, or DAC safety.
- The review page reports grade, worst checked error, stability, and measured
  range. Unsafe automatic results cannot be accepted. Accepted version-four
  profile records retain this quality metadata; older records load as
  UNVERIFIED.
- PROFILES is reached from CAL. It offers eight oscillator slots and a
  read-only CHECK of an accepted/loaded profile. CHECK still drives the
  oscillator; "read-only" means it never changes the curve.
- SCALES edits the selected output's scale, notes, root, transpose and mapping.
  NOTES and SETUPS are child pages, not separate top-level modes.
- ROUTES selects input/output, optional quantization and optional correction.
  BIND snapshots the selected correction profile. RUN is available here only,
  and requires at least one processing stage. Quantization precedes correction.

Child-page headers return to the parent; all menus fit the existing eight-row
box. Navigation does not stop running operations. CAL reserves its input/output
through the entire automatic sequence, including transitions between stages.
Other nonconflicting routes may continue running.

## What automatic means

1. Find a measurable reference. If 0 V is below the 20-Hz detector floor,
   search upward on the same semitone-voltage grid through +5 V instead of
   failing. Measure an initial curve and discover its usable range, then return
   to the discovered reference for the drift check. Completion, cancellation,
   or failure still disables the output back to commanded calibrated zero.
2. Check at most 50 corrected pitches: both measured endpoints, 31 interior
   coverage probes, the measured zero-volt pitch when in range, and midpoints
   adjoining the eight strongest bends in the measured curve. Duplicate probes
   are removed. Perform the existing nine local repeat measurements at the
   worst checked location. This is explicitly a sampled check, not exhaustive.
3. Aim for at most 1.5 cents before declaring the sampled 2-cent target met,
   leaving 0.5 cents of empirical headroom for sequential-check variation.
   This margin is not a measured uncertainty bound or future accuracy guarantee.
   If error exceeds that completion aim and the local response is suitable, measure one
   additional interior point and independently check the local candidate.
4. Recheck the exact same frozen probe set across the range. Local paired
   candidate validation also checks both newly split intervals and neighboring
   intervals and must first demonstrate at least 0.5 cents of local gain.
   Retain that insertion only if the range-wide checked worst absolute error
   does not increase and the recheck's local repeats remain valid and repeatable.
   Another pitch becoming worst must not erase a demonstrated local improvement.
   Otherwise undo it and retain the last checked candidate. Serial retains both
   scores and the decision. Repeat only within the limits below.
5. Return output to commanded calibrated zero and present a review. ACCEPT
   replaces RAM only; SAVE in PROFILES is separate. Neither starts playback.

The 2-cent target is best effort, not a guaranteed specification. The reported
worst includes the individual local repeat means, not just the earlier probe
scan or endpoint-adjusted residual. All three repeated locations must also have
between-repeat variation no greater than 0.75 cents for a pass. A sampled pass
does not certify unmeasured pitches: narrow errors can fall between probes, even
when the measured anchors look smooth. CHECK retains the exhaustive 50-cent
grid for diagnostics/comparison. Even that grid is not continuous certification.
Noise, drift, boundaries or nonrepeatability can prevent refinement. Retuning
requires a new scan.

The accepted profile and saved slots remain untouched during work. Cancellation
keeps them. A timeout/fault cannot offer a candidate that never completed its
first check; after a successful check, a failed tentative improvement is rolled
back. An operation is bounded to eight improvement attempts and 15 minutes
total, not eight unbounded rescans. Before starting each improvement, reserve
time for 9 local measurements, up to 16 paired tests, the entire verification
grid and its 9 local measurements, one first-target retry, and 30 seconds of
transition margin. The reservation uses the existing five-second per-target
deadline, not optimistic observed speed. For 50 targets this is 7 minutes
35 seconds. Insufficient remaining time yields `REVIEW - NO TIME FOR FULL RECHECK`
with the best verified curve, without starting a tentative edit. The hard overall
deadline and rollback remain safeguards. This ceiling is not a promised duration
or a guarantee that all eight attempts can run. No flash writes happen inside the loop.

### Calibration-speed requirement

The briefly deployed 45-minute ceiling allowed a 24-minute qualification run,
but is not the intended normal user experience. Targeted checking restores the
15-minute hard ceiling; actual hardware speed/accuracy is not yet qualified.
Initial 121-position acquisition is unchanged. Longer duration is not evidence of superior
accuracy. The user reports dedicated calibrators completing in under a minute.
Aim for approximately one-minute normal calibration where signal/range permit;
feasibility across the full low-frequency range remains to be demonstrated.
Investigate adaptive settling/acquisition and targeted validation, retaining
freshness, repeatability, bounded retries, and safe output behavior. Keep
exhaustive full-range qualification available as an advanced diagnostic rather
than silently trading away correctness or presenting today's runtime as final.

## Point count and storage budget

The initial 121 positions provide semitone voltage spacing across ten volts.
That is a sensible baseline for a smooth oscillator response, not proof of
sufficient precision for every oscillator. We measure interpolation error and
place extra points where needed rather than increasing every scan's density.

There are eight additional point slots: at most 129 stored points. A limited
initial range may contain fewer than 121 anchors; the eight-attempt limit still
applies. Original anchors are never discarded to make room. If the bounded
refinement cannot meet the target, present the measured result rather than
silently claiming success or looping forever.

Eight oscillator profiles fit the existing 16-KiB profile journal alongside the
unchanged separate settings allocation. Each maximum TUCP v2 payload is 1,072
bytes: eight total 8,576 bytes before journal overhead. Repeated save/garbage
collection and interrupted collection of eight full records are tested. More
slots would require a fresh journal-capacity/recovery budget, not just a larger
menu number. Runtime playback still holds only four bound curves, not all eight
stored profiles. CPU RAM remains 32 KiB.

Existing profile keys and flash reservation are unchanged. Older v1/v2 profiles
remain readable. Firmware predating this change cannot read a 129-point record
or select slots 5–8; do not assume backward compatibility after downgrading.

## Development test-data policy — September 19

The user considers all current calibrations test data, not normal-use profiles,
until we are satisfied with the first release-candidate pass. An unsaved review
candidate does not require a save/discard confirmation before an otherwise
authorized flash. Record useful diagnostic results first. Continue preserving
saved slots by default; this is not a request to erase them unnecessarily.
Do not interrupt an active scan needed for diagnosis merely to flash sooner.
Revisit this policy when transitioning to release-candidate/normal-use data.

## Validation and next hardware check

### September 19: Generate3 low-note acquisition correction

The IN1/OUT1 serial capture found the apparent "failure at zero" actually
started at commanded -2.16675 V, around 26.68 Hz. Qualified readings covered
26.642–26.715 Hz (about 4.74 cents), exceeding the old 3-cent consecutive-window
limit. The timeout was mistaken for a range endpoint below zero; the final
zero check then misleadingly reported missing zero pitch. The final zero
reading itself matched the preflight within 0.06 cents. This does not establish
whether the variation originates in the oscillator, detection or both.

Below C3 (about 131 Hz), a failed tight-window acquisition now falls back to
sixteen non-overlapping measurement windows (initially eight; see retry below).
Raw span must stay within 8 cents;
quarter-block means must agree within 2 cents and half-block means within 1
cent. Fresh overlapping observations still participate in the raw-span guard,
so decimation cannot conceal alternating outliers. The initial 350 ms settling
time, 5-second point deadline, freshness checks and final zero-drift guard remain.
Automatic low-note verification uses the same bounded mean; diagnostics retain
the raw spread, not a smoothed spread. This is a repeatability heuristic, not a
statistical confidence interval or guarantee of sub-cent absolute accuracy.

Unstable qualified pitch is now distinct from a silent range endpoint. A range
ending before its zero anchor is also reported explicitly. Failure voltage is
latched before returning output to zero and included on screen and serial as
`CAL FAILED_AT_UV`; verification summaries include `AVERAGED`.

The firmware-only change retains the existing FPGA design, 32-KiB CPU RAM,
profile format, saved slots and flash reservation. Host tests cover captured
low-note variation, full simulated automatic operation, overlapping outlier
rejection, drift, missing/stale frames and failure-voltage reporting. Physical
Generate3 confirmation remains pending after flashing.

The first physical retry exposed an additional discovery boundary: at
-2.58325 V, pitch straddled the 20-Hz qualification floor before any usable
anchors were retained. The new instability error incorrectly stopped this
leading-range search. Discovery now retains its original skip behavior until
two responsive anchors exist, discarding a lone provisional anchor rather
than bridging a gap. Instability inside an established range still fails;
preflight and final zero checks are unchanged. The integration regression now
includes intermittent qualification at the floor instead of suppressing jitter
there. A fresh physical retry is required for this correction.

The next physical run crossed zero and reached +2.33325 V with 55 retained
points, then timed out on qualified but unstable pitch near 602 Hz. Serial
showed a wiring error in the software consumers: CAL inherited the live
display's native-bank preference above 600 Hz. Native observations included
600.030–604.197 Hz, while the concurrently computed low-bank readings in that
excerpt stayed at 602.006–602.112 Hz. The settled resolver already preferred
that longer window below 1 kHz, but CAL was not using it.

Active CAL/CHECK now explicitly uses the existing settled publication policy;
other inputs and live tuner display retain the fast motion policy. Both banks
still use their existing confidence, energy and freshness gates, and conflicting
qualified overlap candidates still invalidate a settled reading. Consumer
sequence and full-window age metadata follow the selected bank. This adds no
acquisition or hardware bank. `NSDF COMP` remains the live-display descriptor;
`NSDF PICK` shows the strict arbitration diagnostic (with logging-time ages).
Host scheduler tests exercise both paths with different bank estimates, and a
regression checks the actual CAL-only wiring. Physical confirmation is pending.

The following retry stopped at -1.75 V near 35.6 Hz. Periodic telemetry showed
mostly close readings but cannot establish what happened between logged frames.
Do not widen acceptance thresholds from this decimated trace. A diagnostic-only
follow-up retains the failed point's eligible qualified/unqualified counts,
tight-window count, averaging-window count, overlap skips, span/gap reset counts,
raw span, quarter/half mean differences, and actual retained pitches.
These are emitted as `CAL ACQUIRE` and `CAL AVG` after failure, before the sweep
object is discarded. Pitches/differences are in integer millicents; counts refer
to frames that passed the sweep's timestamp/route/sequence eligibility checks.
Counters reset for each voltage; averaging counters also reset after invalid
measurements. Logging does not change acquisition policy or extend a deadline.
The snapshot costs bounded firmware RAM only; no detector or FPGA change.

The diagnostic retry failed at -2.33325 V: 49 qualified frames, zero unqualified,
24 overlap skips, and no span/gap resets. Raw span was 6.840 cents. The final
eight readings' half means differed by only 0.437 cents, but quarter means
(only two readings each) differed by 4.365 cents. This identifies the failing
guard, not whether the variation originates in detection or the oscillator.
The low-note fallback now retains sixteen non-overlapping windows: four per
quarter and eight per half. The 8-cent raw, 2-cent quarter, 1-cent half and
5-second deadline limits are unchanged. Tight-window acquisition is unchanged.
Tests replay a clearly synthetic repetition of that snapshot at every phase,
reject drift/outliers/overlap aliasing, and check full serial packet capacity.
This adds 32 bytes per averaging buffer/snapshot, with no new FPGA resources.
Physical confirmation of the longer-window policy remains pending.

The next physical run on `0fa8ad38` crossed zero and completed its initial
sweep with 74 anchors. Automatic verification then timed out at its first
target (commanded about -2.460 V, measured about 21.8 Hz). Logged qualified
readings drifted from 21.757 to 21.834 Hz during the check (roughly 6 cents).
The trace does not distinguish analog settling from estimator behavior.
Automatic full-range verification now permits one fresh five-second attempt
at the same initial target, without interrupting or changing its output CV.
Statistics are cleared and only newly settled windows count; stability limits
are unchanged. This applies only to the first target of Verify/Reverify, not
manual checks, later targets or local refinement. The total 15-minute operation
limit still applies. Failure after that retry still restores zero and keeps the
prior accepted profile. Serial reports the retry and, on timeout, the actual
commanded voltage, target, and retained averaging error diagnostics. Host tests
cover transient recovery, sustained drift, invalid/stale/cached/unqualified
readings, unchanged retry voltage and the ordinary subsequent-target deadline.
Physical confirmation of this verification retry remains pending.

The physical `d66264e3` retry completed its initial sweep with 72 anchors, but
failed both first-target verification attempts at -2.330750 V. Target was
1,850,000 millicents (~23.8023 Hz). The final attempt retained 16 windows from
52 observations (26 overlap skips), with no span/gap resets. Raw span was
7.121 cents, quarter-mean difference 3.285 cents, half-mean difference 0.172
cents. Retained errors in millicents were:
`854,1144,999,1726,4195,4339,4412,4195,4339,4992,4992,3541,2380,2162,1653,-818`.
Periodic telemetry shows a rise/fall pattern across both attempts, rather
than evidence that another fixed settling delay will solve it. Keep the
existing stability guards; the repeated small-block disagreement is real.

The existing 41 selector/model/captured-score tests passed. An additional
128-phase synthetic study at this exact target found -0.0196..+0.0183 cents
error at amplitude 14,000 counts and -0.1363..+0.2180 cents at amplitude 72.
The exact target is now included in the low-sine regression matrix. These
results do not prove the physical input path or oscillator is stable: no
independent waveform/frequency reference was captured for this failure.
Next hardware isolation: feed IN1 a steady ~24–25 Hz sine from a second
oscillator, without Tiliqua driving its V/oct, and log the tuner without a
calibration sweep. Compare that with Generate3 before altering thresholds
or enlarging the detector. Saved profiles remain unchanged.

The user supplied a steady Twin Waves sine near 25 Hz on IN1, while OUT1
remained connected to Generate3 with its controls unchanged. A fresh serial
capture on September 19 (`/tmp/tuner-twinwaves-25hz-0919.serial.log`) produced
125 qualified logged low-bank observations over 51.124 seconds: min 24.987 Hz,
mean 24.993448 Hz, max 25.000 Hz; 0.9005 cents peak-to-peak and 0.1766 cents
population standard deviation. The scheduler fault count remained zero.
These are periodically logged observations, not every detector frame and not
an absolute-frequency accuracy measurement. This establishes repeatable
low-frequency measurement for this independent source, but does not rule out
waveform-dependent error or distinguish Generate3 variation from output-CV
variation. Next isolation step: retain Twin Waves' tuning, connect OUT1 to
its V/oct instead, and run automatic calibration on IN1/OUT1. No detector or
stability-threshold change is justified by this comparison alone.

With OUT1 then connected to Twin Waves' V/oct and its tuning unchanged, the
automatic run on the same `d66264e3` firmware succeeded: 64 anchors from
-0.250 to +5.000 V, measured E0 +38.1c through G5 -15.3c; all 125 verification
targets plus the local follow-up completed. Final status was `READY - WITHIN
2C TARGET`, worst measured error -1.81 cents, zero improvement passes, and no
initial-target retry. Output returned to zero; result awaits explicit acceptance
in RAM, with no saved-slot write. This shows the workflow can complete with
this source; it is not a proof of absolute accuracy or of stable negative-range
CV output around -2.3 V. The next matched-range comparison is to retune Twin
Waves near 120 Hz at the current zero output, then repeat IN1/OUT1 calibration
without changing Generate3's controls. RUN replaces the unaccepted test result,
not a saved profile; the old result must not be reused after retuning.

That matched-range Twin Waves run also completed on unchanged `d66264e3`
firmware: 76 anchors from -2.583250 to +3.666750 V, measured E0 -33.9c
through F#6 +4.1c. All 149 verification targets and the local follow-up
completed, with worst measured error +1.62 cents, zero improvement passes,
and final status `READY - WITHIN 2C TARGET`. Output returned to zero and
the candidate remains unaccepted; no saved profile was written. In particular,
verification passed the negative-CV/low-frequency region where Generate3
failed. This argues against a source-independent failure in that region, but
does not distinguish Generate3 pitch variation, waveform-dependent estimator
error, or a source/load-dependent CV effect.

Next isolation: measure Generate3's fundamental near 24–25 Hz with its V/oct
input unpatched, using IN1 and the tuner only. This deliberately requires
retuning Generate3 and invalidates reuse of its previous calibration curves.
Compare the serial repeatability with the independent Twin Waves 25-Hz control
before changing stability guards. A stable result would redirect investigation
toward driven-CV behavior; an unstable result would still require distinguishing
actual pitch variation from measurement error, not labeling the oscillator bad.

The unpatched Generate3 fundamental control is now captured in the same serial
log, device timestamps 4,000,005–4,059,921 ms. All 147 logged low-bank frames
were qualified, with zero scheduler faults. Frequency was 24.967–25.047 Hz,
mean 25.007612 Hz: 5.5384 cents peak-to-peak and 1.7586 cents population standard
deviation over 59.916 seconds. Variation persists without any Tiliqua output
connected to its V/oct, so driven output CV is not necessary to reproduce it.
This still does not identify actual frequency variation versus waveform/input
path/estimator effects. Next compare its CORE triangle at unchanged tuning and
with V/oct still disconnected; do not relax calibration acceptance from this
periodically logged data alone.

Switching only Generate3's output from FUNDAMENTAL to CORE, with tuning
unchanged and V/oct unpatched, produced a substantially steadier result.
Device timestamps 4,181,219–4,240,946 ms contain 147 qualified low-bank frames,
zero faults: 24.988–24.996 Hz, mean 24.990973 Hz, 0.5542 cents peak-to-peak
and 0.1069 cents population standard deviation over 59.727 seconds. The
fundamental control's span was approximately ten times larger. This points
toward the waveform/output path interacting with measurement rather than
general core-frequency instability; it does not identify the exact mechanism
or independently establish absolute accuracy. An offline 128-phase clean
signal check at 25.0076 Hz found only 0.0413 cents span for a sine and 0.0348
for a triangle (14,000-count amplitude, existing 604-sample low-bank model).
Neither ideal-signal result accounts for the measured fundamental variation.

Next functional hardware check: retain CORE into IN1, connect OUT1 to
Generate3 V/oct, tune near 120 Hz at zero output, and run automatic calibration.
This tests the same negative-CV region with the steadier waveform without
changing the detector, stability guards, or firmware. A successful CORE run
would establish a usable Generate3 calibration path, not close investigation
of the fundamental output's waveform-dependent behavior.

Important interpretation correction: the
[official Generate3 manual](https://joranalogue.com/generate-3/manual),
version 2023-09-12, section 9,
states that CORE is one octave below FUNDAMENTAL and bypasses its phase
modulator. Section 12 explicitly recommends FUNDAMENTAL for tuning. The earlier
sequential ~25-Hz measurements must therefore NOT be treated as proven
same-frequency waveform comparisons. If tuning really remained unchanged,
similar reported frequencies suggest an octave-selection issue or another
unresolved difference in the test, not proof of oscillator instability.
Next isolate this by reading CORE and FUNDAMENTAL simultaneously on IN1/IN2,
with V/oct unpatched and modulation/sync inputs unpatched. Confirm their 2:1
relationship before drawing a stronger conclusion from the serial variation.
The successful CORE calibration remains valid evidence for that output only;
it does not validate FUNDAMENTAL or justify ignoring its failure.

That CORE calibration completed on `d66264e3`: 75 anchors from -2.583250
to +3.583250 V (E0 -46.1c through F6 +46.5c), all 147 verification targets
and the local follow-up passed, worst measured error -0.99 cents, no improvement
passes. Final status is `READY - WITHIN 2C TARGET`; output zero and candidate
awaiting acceptance. This confirms the low-frequency Generate3 workflow works
with CORE under the unchanged stability limits, not that FUNDAMENTAL is fixed.

The same trace exposed a separate upper-bank boundary defect. At commanded
+3.666750 V, native measured about 1521 Hz while low reported about 761 Hz;
both qualified, so settled arbitration correctly rejected the disagreement and
discovery ended the range. The selector had discarded peaks outside a bank's
range *before* choosing the first strong key maximum, allowing a later multiple
of the real period to masquerade as a valid lower tone. Synthetic sine and
triangle regressions reproduce this near 1500 Hz with actual production Rust
selection and arbitration; both tests failed before the correction.

Selection now finds the first peak above the unchanged relative-height cutoff
across the available key maxima, then rejects it if outside the bank's range.
It does not substitute a later period to fit the range. Weak early maxima still
allow a stronger in-range period. Confidence, energy, source guards, freshness,
settled disagreement and calibration stability limits are unchanged. This is
firmware only, retaining the same two score scans/read bound and no new buffer.
Archived CPU/score-report validators explicitly retain the old selection policy
to preserve historical evidence; current production tests separately replay
those same scores against the updated model. Physical confirmation beyond the
1500-Hz boundary remains pending on a new build; do not flash over the current
unsaved review candidate without arranging acceptance/save or discard first.

Validation for the correction: 192 host regressions passed, including the
production selector/arbitration boundary cases, historical capture validation,
motion, ownership, quantization, persistence and automatic-calibration tests.
Build `2ea8160c` is R5, 192 kHz, unrotated 1280x720, spread spectrum 0.0.
Firmware is 237,104 bytes (392 bytes smaller); FPGA SHA-256 remains
`4a366828b96013f60160b42eac8ed9392dfe05f83e5894650a8dd8369bf3dd6d`.
CPU RAM remains 32 KiB, static/stack boundary 0x1808 and stack top 0x8000.
After explicit permission to discard the unsaved CORE test result, slot 1
flashing completed with `Refresh: DONE`; saved-profile allocation is unchanged.
Next hardware check is a fresh CORE calibration at unchanged oscillator tuning
to verify that acquisition crosses the old ~1500-Hz cutoff and still meets the
automatic accuracy checks.

### Simultaneous Generate3 CORE / FUNDAMENTAL check

On `2ea8160c`, with V/oct unpatched, CORE into IN1 and FUNDAMENTAL into IN2,
the serial capture at device timestamps 263,033–322,760 ms confirms the
expected octave relationship. CORE: 147/147 qualified logged observations,
24.982–24.992 Hz, mean 24.987497 Hz, 0.6929-cent span, 0.1419-cent population
standard deviation. FUNDAMENTAL: 148/148 qualified, 49.968–49.988 Hz, mean
49.975899 Hz, 0.6928-cent span, 0.1437-cent standard deviation. No scheduler
faults. Ratio of means is 2.000036 (0.0314 cents from an exact octave); these
are asynchronously logged frames, not phase-aligned or independently verified
absolute-frequency measurements. FUNDAMENTAL is repeatable at ~50 Hz here.
This does not settle the earlier ~25-Hz FUNDAMENTAL failure.

An offline sensitivity probe offers a hypothesis, not a physical diagnosis:
604 low-bank samples of a fixed 25-Hz sine plus a 1%-amplitude 12.5-Hz component
produce about 3.36 cents of phase-dependent estimate span (3% gives 10.09 cents).
At 50 Hz with the corresponding 25-Hz component, the same model stays near
0.039 cents span because a later full repeating period is available to the
existing refinement. The 25-Hz double period exceeds the current 301-lag
low-bank limit. The probe uses rounded 14,000-count amplitude, relative
subharmonic phase 0.7 radians, and 64 phases across two nominal sine periods.
No such component has yet been measured in Generate3's physical output.
Do not infer that it exists from this synthetic example or enlarge hardware
on that assumption. Next test lowers FUNDAMENTAL on IN2 to ~25 Hz; CORE then
falls below the 20-Hz qualification floor, so losing its displayed pitch is
expected rather than a new failure. No calibration sweep is needed for this
steady-source comparison.

The steady FUNDAMENTAL-only low-note check on IN2 reproduced the issue on
`2ea8160c`: 147/147 qualified logged frames, no faults, at device timestamps
408,096–467,902 ms. Range 24.956–25.038 Hz, mean 24.996088 Hz, span 5.6791 cents,
population standard deviation 1.7636 cents. CORE is now below the supported
20-Hz range, as expected. This confirms repeatability of the frequency-dependent
symptom with V/oct disconnected; it does not prove its waveform mechanism.

The existing `TILIQUA_INTONO_NSDF_TRACE=full` firmware diagnostic can export
immutable NSDF score frames and aligned source moments on the unchanged FPGA.
It is a temporary diagnostic, not the production continuous scheduler: leave
it on the idle tuner page and do not run CAL/ROUTES. Normal live pitch display
is not supported in this mode. Restore the normal continuous build afterward.
New diagnostic CPU reports include `policy=1` for range-after-peak selection;
unversioned historical reports retain range-first interpretation. Host validation
rejects unknown versions and mismatched CPU/score results. The 192-byte line
buffer is unchanged and its maximum-length report remains covered by tests.
These exports are correlation scores, not raw audio; conclusions must respect
that limitation. No new detector, score buffer or FPGA resources are introduced.

The `5dfa3abe` full-mode run validated 131 complete frames, including 16
FUNDAMENTAL/IN2 low-bank frames retained in
`tests/fixtures/nsdf-gen3-fundamental-25-scores.json`. All 16 are unclipped,
source-guarded and CPU/host-consistent, spanning 24.957–25.031 Hz. Production
`2ea8160c` was restored after capture (`Refresh: DONE`). Exploratory host fits
of a sine plus weak half-frequency and/or second-harmonic terms do not uniquely
explain the variation; do not identify physical leakage or alter calibration
thresholds from those fits.

The next diagnostic extends full-mode exports with `NSDF WAVE` records of the
exact centered/scaled samples used for each score frame. It reuses the idle
score-engine RAM B port: no extra capture memory, multiplier or CPU frame buffer.
Address bit 10 selects samples; ordinary score addressing is unchanged. Gateware
identity is now `0x4e534404` and matching firmware is required. Readback is zero
during loading/computation, cancellation/fault, or beyond the valid frame length.
Normal continuous firmware does not export samples. Full mode stays diagnostic
only and must not run calibration/routes. Host validation requires matching
frame identity, exact energy and bit-exact replay of every exported score before
using the samples as evidence. These are filtered/centered estimator inputs,
not untouched ADC samples, and do not provide an independent frequency truth.

Waveform diagnostic `e3d46971` passed routed timing at 66.37 MHz system
(60 MHz required), 87.90 MHz pixel, 434.97 MHz serializer and 65.29 MHz audio.
EBR remains 44/56 and multipliers 14/28. All 252 host regressions passed;
19 separately gated long-running tests were skipped. The two temporary test
failures during fixture-format migration were corrected and the full suite
rerun. Flash completed with `Refresh: DONE`. Six IN2 low-bank waveform/score
pairs are retained in `tests/fixtures/nsdf-gen3-fundamental-25-wave.json`.
Their energies and every score replay bit-exactly, ruling out mismatched
waveform/score records as an explanation of their pitch variation.

On those SAME six measured frames, the existing 301-lag selector reports
24.954–25.019 Hz (4.5036 cents span). Host-only recomputation through lag 501
lets its existing refinement compare the two-cycle repetition: 24.985898–
24.992595 Hz, 0.46394 cents span. No samples were tiled or invented. The
waveforms exhibit small alternating-cycle differences; harmonic least-squares
fits find repeatable half-frequency and 1.5x components around 0.75% and 0.9%
of the main component. Fits are exploratory, not independent frequency truth
or proof of which analogue circuit introduces the differences.

Do NOT deploy a blind longer-lag change: a synthetic 50-Hz signal with these
small alternating components regresses from <0.05c error to >0.5c when the
largest accepted multiple becomes odd. A regression test retains this warning.
Any correction must select an appropriate repeating interval, retain range and
confidence safeguards, cover the 20-Hz boundary, and be resource/timing-budgeted.
The low-note waveform evidence is a strong direction, not a completed fix.
Production `2ea8160c` was restored successfully after capture, and live serial
measurements resumed with zero scheduler faults. Next physical control is
FUNDAMENTAL near 21–22 Hz with the same unmodulated, V/oct-unpatched setup.

### Bounded low-bank repeating-interval correction (September 19)

The user set FUNDAMENTAL near 20.94 Hz, at approximately the lowest available
AUDIO-mode tuning. No lower tuning or mode change is required. Seven additional
matched physical waveform/score frames are retained in
`tests/fixtures/nsdf-gen3-fundamental-21-wave.json`. Every score and energy
replays exactly. Original estimates span 7.2724 cents. Recomputing lags through
601 from those same 604 captured samples and selecting the strongest qualified
repeating interval reduces the span to 0.5372 cents. This is repeatability,
not an independently measured absolute-accuracy claim.

The production correction uses 674 samples in the existing sample RAM and
extends only low-bank scores through lag 621. At 20 Hz the double-period
comparison now retains 74 overlapping samples. Initial pitch selection still
uses the original first 301 lags: the additional short-overlap peaks cannot
compete for the initial pitch or fabricate a lower fundamental. Refinement
checks the existing maximum of seven nearby multiple-period candidates,
selecting the greatest interpolated score (longer interval wins ties) rather
than blindly accepting the longest. Native-bank policy is unchanged. Confidence,
bank limits, 10-cent refinement agreement and calibration stability thresholds
are unchanged. Exact frequency-floor edge behavior remains a limitation: a raw
estimate just below 20 Hz is rejected rather than coerced into range.

Low-window support increases from 100.67 to 112.33 ms. Publication explicitly
accounts for that window when checking fresh/settled calibration evidence.
Score RAM grows from 512 to 1024 words: one additional EBR is expected, with
no additional multiplier or CPU frame buffer. Gateware identity `0x4e534405`
and serial selection policy 2 distinguish this geometry from old captures.
Final whole-device resource, timing and physical repeatability qualification
must be recorded after building/testing; host evidence alone is insufficient.

Regression coverage includes both exact physical captures through the actual
Rust selector, 448 synthetic alternating-cycle cases (seven frequencies,
two amplitudes and 32 phases), the 440-case moving-tone grid, bank-boundary
folding, UART export integrity, settled-window ages and full-size RTL scores.
The low hardware computation is explicitly bounded below 6 ms in simulation
at 60 MHz, within its 10 ms scheduling slot. This excludes CPU selection time,
which must also be measured on the installed production scheduler.

Serial sessions can now be summarized reproducibly from `gateware` with
`python tests/summarize_nsdf_schedule.py /path/to/session.log --last-seconds 60`.
The read-only tool reports per-bank qualified observations, frequency spread,
update rates, faults and selector/guard CPU work. It rejects malformed or mixed
boot sessions rather than silently joining them. Frequency spread is only a
repeatability metric when the input is stationary, not proof of absolute
accuracy; serial sampling cannot establish an all-frame dropout rate or a
worst-case runtime. No device firmware or resource cost is added by this tool.

Build `1e586139` completed full synthesis/routing and was flashed successfully
to **slot 1**, preserving the 24576-byte options region (`Refresh: DONE`, exit
zero). It is TUNER, R5, 192 kHz, unrotated 1280x720p60, spread spectrum 0.0.
Final clocks pass: system 66.12/60 MHz, pixel 90.32/74.25 MHz, serializer
420.34/371.33 MHz, audio 68.12/49.152 MHz. Allocation is 19347 LUT4, 45/56 EBR,
14/28 DSP; CPU working RAM remains 32 KiB. Firmware is 238336 bytes in PSRAM.
Bitstream SHA256: `4133237a11029b013e415b0367bc882e2fd35386d3bd57ee67b15b95a079667b`.

Validation: 257 tests passed, 19 separately gated long-running tests skipped;
the updated bank-boundary suite and publication/scheduler suite were rerun
separately (45 and 27 passes). An additional real-CSR test passes for every
low-bank score, proving addresses 512–621 do not alias earlier scores or sample
readback. The serial summary tool has seven passing tests.

**Physical after-flash confirmation is pending.** The rack stayed powered but
the installed bootloader reports `cold_boot: false`, returns to its selection
menu and has not started TUNER. No bootloader/EEPROM changes were made to bypass
that behavior. User is asleep; do not claim the new detector was measured live.
First resume action: select TUNER slot 1, leaving the patch/tuning unchanged.
Record a stationary 60-second IN2 low-bank control near 20.94 Hz. CORE/IN1 is
below 20 Hz and is expected to remain unqualified. Only then repatch OUT1 to
Generate3 V/oct and retune for a fresh FUNDAMENTAL calibration/automatic check.

Host coverage includes complete automatic operation, navigation during work,
successful refinement, rejection of full-range regressions, cancellation,
deadline and output-fault rollback, profile serialization, journal recovery and
actual menu labels/navigation. The broader 178-test regression suite passes,
including the live adapter's 140 Rust subtests.

On hardware, run CAL once with the existing calibration patch and stable sine.
Confirm that measuring, checking and any justified improvement proceed without
manual VERIFY/REFINE selections, ending at review with output zero. Accept and
save only after reviewing it. A curve already within 2 cents should finish
without an improvement pass. Then test concurrency with unrelated routes.

See [USB storage](USB_STORAGE.md) for removable-library work that is not yet
enabled in this build.

### Live low-note confirmation (September 19, after bootloader selection)

The user selected TUNER after the overnight flash, leaving the stationary patch
unchanged: Generate3 CORE into IN1, FUNDAMENTAL into IN2, V/oct unpatched. Serial
reconnected at 115200 through `/dev/cu.usbmodem83102`. Transcript:
`/tmp/tuner-gen3-low-repeat-after.serial.log` (single boot, continuing logger).
The summary ending at device time 233012 ms uses the preceding 60 seconds;
IN2 low-bank observations span device times 173335–232803 ms:

- 145/145 logged observations qualified; 20.913–20.964 Hz, mean 20.917283 Hz.
- Spread 4.2168 cents; standard deviation 0.6552 cents. The prior build's
  stationary control measured 8.9299 cents spread and 3.2152 cents standard
  deviation. This is a substantial repeatability improvement, but occasional
  excursions remain; the live result does not reproduce the sub-cent spread
  of the finite offline waveform captures. Neither measurement establishes
  independent absolute accuracy or excludes drift between sessions.
- All eight banks measured approximately 11.97–11.99 acquisitions/s, with zero
  scheduler faults. Combined selector/guard CPU measured 4.0522% (previous
  control 3.9335%); this excludes other firmware work. Maximum reported low-bank
  acquisition time was 5 ms; IN2 selector/guard time was at most 0.78745 ms.
- IN0 low bank remained qualified in 146/146 observations with 0.1953-cent
  spread near 523 Hz. IN1 CORE remained unqualified as expected below 20 Hz.

The figures describe decimated serial observations, not all acquired frames or
worst-case timing. `tests/test_nsdf_schedule.py` passed all 21 tests, including
the summary parser. No additional firmware change or flash was made for this
measurement. Next physical test: patch OUT1 to Generate3 V/oct, retain
FUNDAMENTAL on IN2, retune to a useful midrange, and run automatic calibration
with input 2/output 1. Calibration success remains unconfirmed on this build;
do not weaken the stability guards to turn the remaining excursions into an
apparent pass.

### FUNDAMENTAL automatic run and native handoff correction (September 19)

With FUNDAMENTAL on IN2, CORE on IN1, and OUT1 driving V/oct, the user retuned
near 120 Hz at zero and started CAL. Build `1e586139` passed low-range discovery
and zero, collected 77 anchors, then automatically checked 135 of 151 targets
before timing out. Output returned to zero. This is **not** a verified profile.
The complete run spans `/tmp/tuner-gen3-low-repeat-after.serial.log` and
`/tmp/tuner-gen3-cal-low-repeat-check.serial.log`; the reader was restarted
between them to extend its recording deadline, without rebooting the device.

Two remaining detector limitations were observed:

1. At +3.833 V, native reported about 1703 Hz while low reported about 853 Hz.
   Both qualified, so strict settled arbitration rejected them and ended the
   discovered range. This is not evidence of the oscillator's upper limit.
   A pure synthetic sine reproduces the problem at 1650–1800 Hz: the first
   out-of-band maximum clears absolute confidence but parabolic peak-height
   bias places it below the relative 90% cutoff. Skipping it selects a later
   multiple. Expanded sine/triangle tests fail on the prior selector.
2. Verification timed out at target 8350000 millicents (B5 +50c), commanded
   3088500 microvolts, immediately above the 1-kHz settled-bank handoff. Both
   banks qualified and agreed within the unchanged cross-bank tolerance, but
   native varied roughly 1015.97–1018.18 Hz in representative logged samples
   while low stayed around 1015.45–1015.56 Hz. The empty `VERIFY AVG` diagnostic
   is the unused low-note averaging path, **not** proof of absent pitch here.
   The native 321-lag limit cannot compare two cycles near 1 kHz.

The next candidate rejects a low-bank frame when an earlier out-of-band key
maximum already clears the absolute confidence gate, even if it misses the
relative cutoff. Weak early peaks remain skippable. Native selection and the
cross-bank disagreement tolerance are not bypassed to accept an octave error.
The native score engine also computes through lag 621 using its existing
674-sample frame and already allocated score RAM. Initial selection stays
bounded to lag 321 (301 in low); only the existing seven bounded refinement
neighborhoods use the extra scores. Both banks prefer the strongest repeating
interval, avoiding an odd multiple when alternating cycles are present.
Hardware identity becomes `0x4e534406`, diagnostic selector policy 3; historical
policies remain explicitly decoded with their original behavior.

Simply extending low-bank preference above 1 kHz was considered and rejected:
a controlled 1400-Hz alternating-cycle probe incurred roughly 15 cents of
low-bank bias. The chosen native correction instead passes 960 controlled
frequency/amplitude/phase cases from 980 Hz through 19.9 kHz, with <0.2-cent
full-level and <0.5-cent low-level errors. These are synthetic tests, not new
physical accuracy claims. The 103-test targeted host suite passes. Hardware
simulation, full build/routing, measured resource cost and physical recheck
are still required before claiming the candidate qualified. No calibration
stability threshold, acquisition deadline or profile acceptance rule changed.

Candidate `537c4a29` has now passed full synthesis/routing, 268 regression tests
(19 optional long-running tests skipped), and the separate 16-test RTL/wave
suite. Native computation stays below 6 ms in its 10-ms hardware slot while
four-channel acquisition continues. Final timing passes: system 67.04/60 MHz,
pixel 85.70/74.25 MHz, serializer 443.85/371.33 MHz, audio 66.75/49.152 MHz.
Allocation is 20116/24288 TRELLIS_COMB, 45/56 EBR and 14/28 DSP; RAM and DSP
block counts are unchanged. Firmware is 237952 bytes; CPU working RAM remains
32 KiB. The archive is TUNER, R5, 192 kHz, unrotated 1280x720p60, spread spectrum
0.0. Bitstream SHA256:
`09128577b73f37aefa0e8e8420a67799e30083fbc41d07e903f5327ac5c56ae1`.

The failing handoff also had occasional low-bank excursions: over device
times 1078500–1082400 ms, both banks qualified 10/10 logged observations, with
3.7567-cent native and 3.1937-cent low spread. The low bank was not uniformly
stable across the whole timeout. Physical calibration and live CPU/scheduler
measurements on the new candidate remain required; no completed verified
Generate3 FUNDAMENTAL profile is claimed yet.

The candidate was flashed successfully to slot 1 (exit zero, `Refresh: DONE`),
without erasing the 24576-byte options/profile region. Flash transcript:
`/tmp/tuner-native-repeat-flash.log`. The next boot/run is logged separately to
`/tmp/tuner-native-repeat-537c4a29.serial.log`. Select TUNER, retain FUNDAMENTAL
on IN2 / CORE on IN1 / OUT1 to V/oct and the current approximately 120-Hz zero
tuning, then rerun CAL input 2 / output 1 without adjusting the oscillator.

### Automatic FUNDAMENTAL verification passed; remaining filter boundary

The rerun on `537c4a29` completed with FUNDAMENTAL on IN2, CORE on IN1 and OUT1
driving V/oct, unchanged approximately 120-Hz zero tuning. Serial confirms:

```
CAL STATUS READY - WITHIN 2C TARGET ACTIVE=false IN=2 OUT=1 MV=0 POINT=82 COUNT=82
AUTO PHASE=REVIEW RESULT PASSES=0/8 STATUS=READY - WITHIN 2C TARGET
AUTO BEST_WORST_C=+1.39 TARGET_C=2.0 VERIFIED=161/161
```

It passed the previous +3.833-V range cutoff and the approximately 1017-Hz
verification timeout. This is successful automatic internal verification,
not independently measured absolute accuracy. No improvement pass was needed.
The result remains a test candidate; acceptance and flash saving are separate.

Range discovery still stopped at +4.250 V: native measured roughly 2274 Hz
while the low bank qualified roughly 754 Hz. Strict settled arbitration
correctly rejected the conflict. The old FIR's 2250-Hz cutoff retains about
46% amplitude at that frequency, despite the low selector ending at 1500 Hz.
Subsequent discrete correlation maxima can then masquerade as a low pitch.
The source is not known to have reached its upper limit.

The next correction retains 769 taps, the same 2-ms filter delay, existing
histories and arithmetic, but moves the FIR cutoff to 1750 Hz. Response stays
within 0.01 dB through 1 kHz, retains >85% amplitude through the 1500-Hz overlap,
and is below 2.2% amplitude above 2200 Hz. The low relative RMS gate tightens
from 2% to 5% of aligned, DC-removed source RMS, to reject transition-band
remnants mixed with weak subharmonics. The absolute >2-count floor is unchanged;
this is not an absolute input-level increase. Native's 10% relative gate,
both banks' confidence limits, disagreement rejection, calibration stability
limits and acceptance rules are unchanged. Very weak fundamentals amid strong
out-of-band energy may now be rejected; no universal complex-waveform claim.

A 1650-Hz cutoff was rejected after regressing a 1490-Hz 1%-duty pulse case.
The selected 1750-Hz candidate passes the new complete quantized-FIR/production
Rust selector/guard/resolver tests: dense upper-band pure and alternating-cycle
tones, quiet/full-level in-range sines, triangles, saws and selected 50%, 5%, 1%
pulses. A denser 1%-pulse handoff comparison preserves all previously accurate
cases and improves others, while explicitly retaining existing failures on
severely undersampled ideal pulses. The first 88-test host suite passes.
These are synthetic regression results, not a physical range qualification.

Hardware identity becomes `0x4e534407`; diagnostic policy 4 retains policy 3's
selector and score geometry but identifies the stricter energy gate. Host
decoders preserve the 2% rule for archival policies 0–3 and test that the same
3%-RMS frame passes the old gate and fails the new one. A full routed build,
broader tests and a fresh physical scan are required before declaring this
remaining upper-range issue fixed.

Candidate `e3b1e805` subsequently passed 276 regression tests (19 optional long
tests skipped), including hardware acquisition/score simulations. Full routing
passes: system 65.85/60 MHz, pixel 89.84/74.25 MHz, serializer 432.90/371.33 MHz,
audio 70.31/49.152 MHz. RAM/DSP remain 45/56 EBR and 14/28 DSP; CPU working RAM
remains 32 KiB. Logic mapped to 19442/24288 LUT4 (20668 TRELLIS_COMB), versus
18894 LUT4 (20116 TRELLIS_COMB) in the preceding full build. The 548-LUT change
is 2.26 percentage points of the FPGA, not a zero-cost claim despite unchanged
buffer/tap/arithmetic architecture. Firmware is 237944 bytes in PSRAM.
Bitstream SHA256:
`ed4bee5082fee1d0a070c8f6bcd956958b37aec62d4645679a9e96d7df1ddcfb`.
The build remains R5, 192 kHz, unrotated 1280x720p60, spread spectrum 0.0.

Flashed to slot 1 successfully (`Refresh: DONE`, exit zero), preserving the
24576-byte options/profile region. Flash log: `/tmp/tuner-filter-flash.log`.
Fresh serial log: `/tmp/tuner-filter-e3b1e805.serial.log`. Next physical test is
CAL input 2 / output 1 on the unchanged Generate3 FUNDAMENTAL patch and tuning;
confirm range discovery passes +4.25 V and automatic checking still completes.

### Filtered handoff physical run: full positive voltage range verified

The next `e3b1e805` run completed on the unchanged Generate3 FUNDAMENTAL IN2 /
CORE IN1 / OUT1 patch. The original logger's one-hour timeout had expired;
the read-only logger was reconnected during automatic checking. The new log
does not contain range discovery itself, but the final review confirms its
retained endpoints:

```
CAL STATUS REFINE NO GAIN - ORIGINAL ACTIVE=false IN=2 OUT=1 MV=0 POINT=92 COUNT=92
AUTO PHASE=REVIEW RESULT PASSES=1/8 STATUS=REFINE NO GAIN - ORIGINAL
AUTO BEST_WORST_C=+2.23 TARGET_C=2.0 VERIFIED=181/181
CAL REVIEW POINTS=92 LOW_UV=-2583250 HIGH_UV=5000000
CAL REVIEW LOW=E0 -48.8c HIGH=A#7 +45.1c
```

All 181 corrected targets completed. The previous +4.25-V cutoff no longer
occurred on this run; the retained curve reaches the requested +5 V. The
low-voltage endpoint remains limited by measurable pitch at this oscillator
tuning, rather than guaranteeing coverage to -5 V. This is not a 20-kHz
qualification: the highest measured pitch here is around 3.8 kHz.

Worst signed verification error was +2.23 cents, slightly outside the best-effort
2-cent target. One local refinement attempt found no gain and preserved the
original fully checked candidate. No full-range recheck of an inserted point
was started and no improvement is claimed. This verifies completion and safe
fallback, not successful refinement or independently measured absolute accuracy.
The candidate is available for explicit ACCEPT; no saved profile was changed.

Transcript: `/tmp/tuner-filter-e3b1e805-cal.serial.log` (temporary evidence).
No nonzero scheduler fault counters appear in the captured portion. A 30-second
post-run window measured about 3.59% CPU for selector/guard work only; it does
not measure total CPU utilization or worst-case execution time. No firmware
change or reflash was needed after this run. Mixed CAL/ROUTES operation and
broader oscillator/frequency qualification remain separate physical tests.
