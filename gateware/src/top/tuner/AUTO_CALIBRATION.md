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
