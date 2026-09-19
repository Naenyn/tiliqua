# Automatic calibration — September 18, 2026

This is the current UI/workflow specification. It supersedes the manual
VERIFY/REFINE instructions in older investigation documents. Hardware testing
of this automatic controller is pending; its state machine is host-tested.

## Simple workflow

- TUNER observes audio inputs, with spiral and linear views.
- CAL selects the audio input, CV output and nominal 0 V note. RUN starts an
  upward -5..+5 V measurement, automatically checks the resulting curve, then
  attempts guarded improvements when appropriate. RUN again cancels.
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

1. Measure an initial curve and discover its usable range.
2. Check corrected pitches on a 50-cent grid within that range, including the
   existing local repeatability measurements at the worst location.
3. If error exceeds 2 cents and the local response is suitable, measure one
   additional interior point and independently check the local candidate.
4. Recheck the full range. Retain the insertion only if worst absolute error
   improves by at least 0.5 cents. Otherwise undo it and retain the last fully
   checked candidate. Repeat only while useful and within the limits below.
5. Return output to commanded calibrated zero and present a review. ACCEPT
   replaces RAM only; SAVE in PROFILES is separate. Neither starts playback.

The 2-cent target is best effort, not a guaranteed specification. A 50-cent
verification grid samples the response; it cannot certify every intermediate
pitch. Noise, drift, range boundaries or a nonrepeatable response can prevent
refinement. The result explains why it stopped. Retuning requires a new scan.

The accepted profile and saved slots remain untouched during work. Cancellation
keeps them. A timeout/fault cannot offer a candidate that never completed its
first check; after a successful check, a failed tentative improvement is rolled
back. An operation is bounded to eight improvement attempts and 15 minutes
total, not eight unbounded rescans. No flash writes happen inside the loop.

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
