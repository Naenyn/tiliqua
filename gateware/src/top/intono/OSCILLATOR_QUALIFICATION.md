# Oscillator compatibility qualification

## Scope — September 19, 2026

Bounded physical coverage before mixed calibration/quantization trials. Test
tuning reliability separately from calibration repeatability and correction.
Start with Generate3's simultaneous CORE/FUNDAMENTAL outputs, then Mother-32
(pitch offset), Waveplane (user-reported tracking trouble), Twin Waves,
Local Parks, Legion and Castor & Pollux II as time permits. These are planned
tests, not claims of compatibility. Check each module's documented pitch-input
limits before driving it; do not assume every input accepts -5..+5 V.

For each oscillator, establish simple-waveform low/mid/high behavior, compare
stationary alternative waveforms without retuning, then calibrate and check
repeatability where appropriate. Complex/modulated outputs are stress tests,
not an unconditional requirement to infer one intended pitch. A correction
curve cannot compensate for arbitrary nonrepeatable behavior. Internal
verification shares the detector and cannot establish independent absolute
accuracy. Capture reproducible failures before changing detector thresholds.

## Generate3 baseline on e3b1e805

Patch confirmed by user: OUT1 to Generate3 V/oct, CORE to IN1, FUNDAMENTAL to
IN2; Legion remains on IN0. No controls or outputs were changed by the host.
Serial reports CAL inactive, commanded output zero, with the previous test
candidate still at review. The read-only logger uses 115200 baud, DTR enabled,
RTS disabled, on the uniquely identified diagnostic bridge.

Approximately 60 seconds of steady-state telemetry:

| Input | Source | Mean frequency | Logged low-bank qualification | Frequency span |
|---|---|---:|---:|---:|
| IN0 | Legion | 522.88069 Hz | 145/145 | 0.235 cents |
| IN1 | Generate3 CORE | 59.99323 Hz | 146/146 | 0.519 cents |
| IN2 | Generate3 FUNDAMENTAL | 119.98716 Hz | 146/146 | 0.563 cents |
| IN3 | Unpatched | No qualified pitch | 0/145 | N/A |

Bank windows end at device ms 14614407–14614718 and each cover about 59–60 s.
Separate composite-publication checks show every logged IN0/IN1/IN2 report
qualified, and no qualified IN3 report. The ratio of mean composite frequencies
for FUNDAMENTAL and CORE differs from exactly 2:1 by about +0.0092 cents.
These channels are sampled at different times; this is a stationary mean-ratio
check, not a simultaneous phase/instantaneous-ratio measurement. Frequency span
includes oscillator behavior and detector variation, not isolated detector error.

Strict settled-parser checks found no bank conflicts in 656 captured reports.
All recorded scheduler fault counters were zero. Acquisition was about
9.77–9.79 jobs/s per bank; estimated selector/guard CPU was 3.61%, not total CPU
utilization or a worst-case bound. Native banks correctly reject these signals
below their 600-Hz range; this is not a loss of composite detection.

Local transcript (temporary):
`/tmp/tuner-gen3-core-fundamental-baseline-20260919.serial.log`.
Analysis uses `summarize_nsdf_schedule.py --last-seconds 60` and the strict
`analyze_comparisons` / `analyze_picks` parsers. Only decimated telemetry was
captured; no raw waveform export or independent frequency reference was used.

Retuning invalidates the previous oscillator calibration; that result is test
data, not a curve to reuse afterward.

## Generate3 near 1 kHz FUNDAMENTAL

User retuned the oscillator and confirmed it was stationary. Same build, patch
and continuous transcript; no output commands or firmware changes. Composite
report window: device ms 14956393–15016393 (60 seconds, after readiness).

| Input | Mean published frequency | Qualified reports | Published frequency span |
|---|---:|---:|---:|
| IN0 Legion | 522.86643 Hz | 145/145 | 0.215 cents |
| IN1 CORE | 500.30201 Hz | 145/145 | 0.478 cents |
| IN2 FUNDAMENTAL | 1000.63674 Hz | 145/145 | 0.993 cents |
| IN3 unpatched | No qualified pitch | 0/145 | N/A |

Mean-frequency octave deviation was +0.05663 cents. Both IN2 banks qualified
145/145 logged scheduler reports. Their logged settled-comparison disagreement
averaged +0.132 cents (native minus low), ranging -0.190 to +0.495 cents. No
settled conflicts appeared in 580 reports across all channels. All scheduler
fault counters remained zero. Approximately 10.87–10.89 acquisitions/s per bank;
selector/guard CPU estimate 4.94%. Publication and bank reports are at different
instants, so their means/spans need not match. The same decimation and
non-independent-accuracy caveats apply as to the first baseline.

This stationary trial passes the prior approximately 1-kHz trouble region.
Next: roughly 2.3 kHz FUNDAMENTAL (2.2–2.4 kHz is sufficient), testing the prior
upper low-bank-remnant failure region while CORE remains in the bank overlap.

## Generate3 near 2.3 kHz FUNDAMENTAL

Same patch/build, after user confirmed stationary tuning. Composite report
window: device ms 15189444–15249444, 60 seconds in the same transcript.

| Input | Mean published frequency | Qualified reports | Published frequency span |
|---|---:|---:|---:|
| IN0 Legion | 522.85108 Hz | 146/146 | 0.235 cents |
| IN1 CORE | 1149.18103 Hz | 146/146 | 0.791 cents |
| IN2 FUNDAMENTAL | 2298.35621 Hz | 145/145 | 0.673 cents |
| IN3 unpatched | No qualified pitch | 0/145 | N/A |

Mean-frequency octave deviation: -0.00440 cents. No settled conflicts in 582
reports. Both CORE banks qualified throughout; native-minus-low discrepancy
averaged -0.824 cents, range -1.121 to -0.602 cents. This repeatable bank
difference is recorded rather than claimed absent; it is not an independent
accuracy measurement. Published CORE uses native at this frequency.

FUNDAMENTAL's low bank proposed a raw candidate in all 145 logged observations,
but its energy guard rejected every one. Native remained qualified and the
published pitch did not fold downward. This directly exercises the upper-band
remnant rejection that motivated e3b1e805, without relaxing conflict thresholds.
No scheduler faults; approximately 10.84 acquisitions/s per bank and 5.77%
estimated selector/guard CPU. All prior telemetry/accuracy caveats apply.

Next: roughly 8 kHz FUNDAMENTAL (7.5–8.5 kHz is sufficient), retaining both
outputs to check the previously troublesome higher-frequency region.

## Generate3 near 8 kHz FUNDAMENTAL

Same build/patch, user-confirmed stationary tuning. Composite report window:
device ms 15511539–15571539, 60 seconds in the same transcript.

| Input | Mean published frequency | Qualified reports | Published frequency span |
|---|---:|---:|---:|
| IN0 Legion | 522.83517 Hz | 145/145 | 0.258 cents |
| IN1 CORE | 4005.29053 Hz | 145/145 | 0.889 cents |
| IN2 FUNDAMENTAL | 8010.59106 Hz | 145/145 | 0.936 cents |
| IN3 unpatched | No qualified pitch | 0/145 | N/A |

Mean-frequency octave deviation: +0.00216 cents. Both Generate3 native banks
qualified 145/145 logged scheduler observations. Both low banks rejected all
145 observations (neither raw qualification nor energy guard passed), as
appropriate above their operating range. No settled conflicts in 580 reports;
all scheduler fault counters remained zero. No recorded octave drop or
publication loss at the former approximately 8-kHz trouble region.

Acquisition was about 10.66–10.68 jobs/s per bank. Selector/guard CPU estimate
was 7.11%, higher than at the preceding frequency. The low-bank selector's
largest logged calls were 2.786 ms on CORE and 3.664 ms on FUNDAMENTAL despite
ultimately rejecting those banks. This cost is recorded for future resource
work, not represented as free rejection or total CPU use. No firmware change
was made during qualification. Decimated observations cannot establish
worst-case timing; the shared-clock octave comparison is not absolute accuracy.

Next: approximately 18 kHz FUNDAMENTAL, accepting 17–19 kHz rather than asking
for exact tuning. Keep below the 20-kHz detector boundary for this stationary
upper-range comparison.

## Upper-range failure found while approaching 16 kHz

User observed the IN2 numeric frequency falling from around 15.6 kHz to
approximately 7.9 kHz while the spiral marker appeared not to move. Serial
confirms this is not merely numeric formatting: in a stationary 15-second
tail, IN1 CORE published 7968.542 Hz (37/37 qualified reports), while IN2
FUNDAMENTAL published 7968.762 Hz (36/36). Both correspond to B8 +14.5 cents
at A4=440. Given the unchanged CORE/FUNDAMENTAL patch and octave relationship,
the expected FUNDAMENTAL is approximately 15937.1 Hz (B9 +14.5 cents), inferred
from CORE, not independently measured. This is a suspected high-frequency
period-doubling selection error; waveform/score capture is still required to
establish its cause. It must not be counted as an upper-range pass.

The stationary marker has a separate code explanation: `main.rs` clamps
spiral radial octave turns to eight (C8 and above), while the angular position
repeats every octave. B8 and B9 therefore map to the same radius and angle.
This conceals octave changes above the displayed radial range; the marker is
not independent evidence of a correct high-frequency estimate. No detector or
UI changes had been made at the time of this observation.

### Frozen waveform diagnosis and display correction

Full diagnostic exports reproduce every score and the frame energy exactly
from the exported centered samples. They are score-engine inputs, not untouched
ADC samples. Two successive captures give approximately 7.97 kHz for both
inputs. FUND's first NSDF maximum is about 0.89587 at 15.94 kHz; its second is
about 0.99992 at 7.97 kHz. The first misses the current 90%-of-strongest cutoff.
An offline 85% cutoff selects 15.94 kHz, but that changes the tradeoff for
legitimate weak fundamentals with strong second harmonics. Production policy
remains unchanged pending isolation; there is no unconditional octave doubling.

A least-squares six-harmonic fit to the IN2 capture gives approximately 2701
counts amplitude at 7.97 kHz and 12636 at 15.94 kHz. A repeat gives 2700/12638.
After unplugging CORE from IN1, the IN2 result remains 2700/12637 and 7.97 kHz;
IN1 becomes unqualified and nearly silent. No capture reports clipping. This
argues against CORE-to-FUND adjacent-input interference; it does not establish
whether the smaller component originates in Generate3 or the acquisition path.
The user independently reports Disting indicating B9/C at this setting.

Moving FUND alone to IN1 gives 7971.713 Hz with fitted amplitudes 2702/12677
counts (half-frequency/dominant). IN2 becomes quiet. The ambiguity follows
the signal across input channels; an IN2-specific fault is unlikely. Common
acquisition-path effects are not excluded. Independent waveform inspection is
the next isolation step before changing fundamental-selection preference.

The user subsequently inspected FUND through OSCIO on the same Tiliqua. A
small bump in the sine changed with Generate3's phase control; smoothing it
allowed the tuner to report about 18 kHz, while a small phase adjustment caused
an octave drop to about 9 kHz. This is an independent rendering/analysis path,
not an independent ADC measurement. It supports waveform-dependent ambiguity
and contradicts a simple hard 16-kHz detection ceiling. Do not infer an
incorrect patch, defective oscillator, or perfectly transparent input path.

A synthetic 18-kHz sine plus 9-kHz component reproduces the selection boundary
across 16 starting phases: at amplitude ratios 0.15/0.20 both cutoffs choose
18 kHz; at 0.23/0.25/0.28 the current 90% cutoff chooses 9 kHz and 85% chooses
18 kHz; at 0.30 both choose 9 kHz. The same signal is also a legitimate 9-kHz
fundamental with dominant second harmonic. Lowering the cutoff moves, but does
not resolve, that intended-pitch ambiguity. No production threshold change is
justified by this example alone. These are policy characterization tests, not
an assertion that the higher component must always be called the fundamental.

`tests/fixtures/generate3-upper-octave-capture.json` preserves the first native
CORE/FUND pair and `test_nsdf_upper_octave.py` characterizes the cutoff ambiguity.
The host full-wave reader now safely skips a connection beginning mid-frame,
without stitching frames or relaxing waveform/score parity validation.

The display correction shares one C0–C11 radial mapping between startup drawing,
incremental scene drawing, and all four markers. It retains the same inner/outer
radii; the rings are closer together. B8/B9 no longer collapse to the same
position. Removing the focused note's MIDI-127 clamp also permits correct
high-octave labels and cents. This requires no extra FPGA blocks or framebuffer.
Host geometry tests verify high-octave separation and background/marker mapping.

Validation: five Rust scene tests, 60 selector/capture/ambiguity tests, and 89
waveform/diagnostic/renderer integration tests pass. The normal continuous-trace
firmware builds successfully using the unchanged e3b1e805 FPGA bitstream
(SHA256 `ed4bee5082fee1d0a070c8f6bcd956958b37aec62d4645679a9e96d7df1ddcfb`),
R5, 192 kHz, 1280x720p60, spread spectrum 0.0. Detector policy remains 4.

## Generate3 FUND, smoother phase setting, near 18 kHz

After the user's scope/phase investigation: FUND is on IN1, CORE is disconnected,
Legion remains on IN0, IN2/IN3 are unpatched. The host made no oscillator-control
or DAC changes. The normal firmware with the display correction is running;
detector policy 4 is unchanged. The logger contains a user bitstream switch, so
analysis explicitly uses a contiguous 60-second interval in the latest boot,
not the concatenated earlier sessions. Local log:
`/tmp/tuner-high-ui-restored.serial.log`, device ms 401898–461869.

| Input | Mean published Hz | Qualified reports | Published span |
|---|---:|---:|---:|
| IN0 Legion | 522.75114 | 147/147 | 0.288 cents |
| IN1 FUND | 18002.47503 | 147/147 | 0.638 cents |
| IN2, IN3 unpatched | None | 0/147 each | N/A |

Strict resolver/comparison validation passes for this interval: no conflicts
in 588 reports, all scheduler fault counters zero. IN1 native qualifies 147/147;
its low bank qualifies 0/147. About 11.79 acquisitions/s per bank. Estimated
selector/guard CPU is 2.72%, not total CPU use. Different input population means
this is not a direct efficiency comparison against the previous two-output
Generate3 trial. All decimated-telemetry, oscillator-stability, and lack of an
independent absolute frequency reference caveats still apply. This is a pass
at this fixed phase setting, not blanket immunity to waveform octave ambiguity.

Before the next hardware scan, two new host tests exercise the actual live
automatic calibration adapter: an ideal 18-kHz-at-zero oscillator reaches a
verified, upper-limited candidate without adding points beyond 20 kHz; a
persistent octave drop above 15.9 kHz fails NOT TRACKING, returns output to zero,
preserves the prior active profile, and exposes no candidate for acceptance.
They simulate behavior, not Generate3's exact analogue response. Calibration,
ownership, and upper-octave characterization pytest suites pass (15 tests,
including the compiled Rust test suites).

Next physical step: CAL input 1 / output 1 with the current unchanged tuning.
This deliberately tests automatic upper-boundary handling and verification,
not maximum octave coverage: at 18 kHz zero, an ideal -5 V endpoint is 562.5 Hz
and the upper audible boundary occurs just above zero. A later wide-range scan
will require a lower zero-voltage pitch and a new profile; no existing curve
should be reused after retuning.

### Physical high-zero scan outcome: rejected octave drop

The user ran CAL IN1/OUT1 without touching Generate3 after the 18-kHz check.
Acquisition progressed from -5 V through zero, then failed NOT TRACKING at
+0.083250 V (point 61). Serial retained previous point 0 V / 13326196 milli-cents
(about 18010.16 Hz), rejected 0.083250 V / 12231737 milli-cents (9571.13 Hz):
a -1094.459-cent step. The failed acquisition recorded 49 qualified and zero
unqualified observations. Thus this was a persistent octave-sized selection
change, not absence of signal or an upper-range timeout. No automatic
verification ran and no new candidate was accepted; output returned to commanded
zero. Smoothing the waveform at one frequency did not guarantee octave selection
through the next voltage step. The ideal high-zero host test is not a physical
qualification pass.

Added a strictly descriptive `OCTAVE-SIZED DROP: CHECK SIGNAL` screen hint and
equivalent serial hint for an upward voltage step with a 900–1300-cent downward
reading. This neither attributes the cause to a specific module nor changes
selection, retries, curve acceptance, or existing failure status. Tests include
the exact observed rejected pair, bounds, same-voltage changes, missing prior
points, and preservation of the prior active calibration. The focused
calibration/selector/capture/ambiguity suites pass: 73 pytest cases, including
the compiled Rust suites.

### Generate3 CORE, approximately 600 Hz at zero: automatic review completed

Physical run captured in `/tmp/tuner-octave-hint-live.serial.log`: CORE to IN1,
OUT1 to V/oct, Legion on IN0. Before starting, 38/38 published CORE readings
qualified, averaging 600.1119 Hz with a 0.447-cent span. Controls remained fixed
during the scan. This tests CORE, not the phase-sensitive FUND waveform above.

Automatic calibration retained 115 points from -4.833250 to +4.666750 V,
E0 +45.2c through A9 -39.5c. It completed all 225 verification targets and the
nine-measurement local check, then returned output to commanded zero with a
reviewable candidate. Worst verification error was -3.87 cents: the run did
**not** meet the 2-cent target. No refinement was applied (0/8 passes). Acceptance
is still explicit; saved slots were unchanged.

The stop reason `LOCAL ERROR <1C - NO REFINE` refers to interpolation residual
after subtracting neighboring anchor errors. It does not establish sub-cent
absolute accuracy, disappearance of the -3.87-cent error, or oscillator drift.
The old automatic-review serial report omitted the worst target and local
absolute measurements, so those details cannot be recovered from this log.
Added compact review reporting for the worst target, maximum measurement span,
local absolute means/spans/repeatability, and explicitly endpoint-adjusted
residual. This is diagnostic only; detector and calibration policies are unchanged.
The retained frequency range is not a qualification of the full 20 Hz–20 kHz goal.

### UI follow-up agreed during qualification

The normal user workflow is automatic acquisition, verification, and bounded
refinement, followed by review/acceptance and optional save. A separate manual
verification is not a required completion step. The currently exposed
CAL → PROFILES → CHECK → RUN path is being used for engineering repeatability
tests, not endorsed as the final release interface. The user explicitly dislikes
nested menu navigation. Revisit main displays and menus together; keep manual
verification/refinement as advanced diagnostics rather than routine workflow.

### Repeat CHECK of accepted CORE profile

Same patch and tuning, no curve edits: manual diagnostic CHECK completed
225/225 targets, maximum within-target span 0.84 cents, worst signed error
-6.32 cents at G#9 -50.0c. Output returned to commanded zero. The nine-reading
local check was repeatable but confirmed absolute error, not an accuracy pass:

| Local measurement | Command (V) | Mean error (cents) | Between-repeat span (cents) |
|---|---:|---:|---:|
| Low anchor | +4.416750 | -6.46 | 0.20 |
| High anchor | +4.500000 | -5.97 | 0.09 |
| Interpolated target | +4.454000 | -5.97 | 0.09 |

Endpoint-adjusted interpolation residual was +0.27 cents (three passes
+0.30, +0.24, +0.26). All three absolute measurements were approximately
6 cents flat relative to the stored profile. Adding an interpolated point
is not justified by this small local residual. The cause of the common local
offset is not established: oscillator/output drift and acquisition bias remain
possibilities, and this self-measurement is not an independent absolute reference.
The original automatic run's worst target was not logged, so do not claim both
runs had the same worst location. This repeat failed the 2-cent accuracy goal.

### Temporary direction/settling diagnostic build

`TILIQUA_TUNER_REPEAT_DIAGNOSTIC=1` changes only manual CHECK → RUN into a
36-step, read-only diagnostic. Automatic CAL keeps its normal scan. This build
is specific to the accepted CORE curve above: the middle probe is +4.454000 V,
with the two bracketing stored points as neighbors and 0 V as the interleaved
reference. Do not use a different oscillator/profile and interpret it as the
same experiment. Omit the flag to restore normal CHECK behavior.

For each of two rounds, each of the three probes is approached from below and
above by approximately 1/12 V. Each approach begins with a reference measurement.
All 36 requests are validated against the loaded profile before output is armed;
no extrapolation is allowed. Each step waits 2000 ms plus the acquisition window
before accumulating qualified data, retains the existing 5-second timeout and
freshness/stability/acknowledgment gates, and can be stopped with RUN. Successful
completion, timeout, and output fault return the command to zero. Curve data and
saved slots are never modified. Serial emits separate directional means,
first/last errors, repeat ranges, and reference readings. The screen labels this
REPEAT, not a full-range accuracy pass. This test takes roughly two minutes.

Host tests exercise all request bounds/directions, settling, completion,
signal-loss timeout, output fault, cancellation, immutable profile data, and the
serial packet budget. Calibration and ownership suites pass (8 pytest cases,
including compiled Rust suites). The firmware-only R5 192-kHz 720p build succeeds,
using the existing FPGA image and spread spectrum 0.0. Automatic review now
headlines `OUTSIDE ACCURACY TARGET` when the checked result misses 2 cents,
while keeping the detailed local stop reason below. The exact CORE profile must
be saved before flashing this diagnostic; the previously completed run is RAM-only
unless the user has explicitly saved it.

### Physical direction/settling diagnostic outcome

User saved the accepted CORE curve to slot 4, then loaded it after the diagnostic
flash and started CHECK. `/tmp/tuner-repeat-diagnostic-live.serial.log` confirms
IN1/OUT1, the same 115-point range, and completion of all 36 steps with output
commanded zero. No profile modifications were performed.

| Probe voltage | Mean approached from below | Mean approached from above |
|---|---:|---:|
| +4.416750 V | -6.47c | -6.47c |
| +4.454000 V | -6.05c | -6.02c |
| +4.500000 V | -5.95c | -5.99c |

Each directional result contains two visits; between-visit ranges were
0.01–0.03 cents. The 12 interleaved zero-volt reference measurements averaged
+0.07 cents, with first +0.94, last -0.07, and total range 1.15 cents.
Longer settling did not remove the local high-frequency discrepancy; the tested
approach-direction difference was at most 0.04 cents. These results disfavor
short settling or immediate direction dependence as the explanation for the
approximately six-cent discrepancy. They do not rule out drift since initial
acquisition, longer-term history, or frequency-dependent acquisition error.
No global correction or extra curve point is justified by these data alone.
Next comparison: a fresh automatic acquisition with unchanged patch/controls,
keeping slot 4 as the original baseline, followed by this same repeat check on
the new accepted RAM curve. Automatic CAL is unchanged in the diagnostic build.

### Fresh automatic CORE calibration after repeat check

Captured in `/tmp/tuner-repeat-fresh-cal.serial.log`. The first user start in
this transcript was another 36-step repeat diagnostic; it again measured the
old curve approximately six cents flat locally. The subsequent confirmed
`AUTO PHASE=MEASURING RANGE` run is the fresh automatic calibration. Keep these
operations distinct when analyzing this log.

The fresh sweep retained 115 points, -4.833250..+4.666750 V, E0 +44.4c through
A9 -45.2c. It completed 225 verification targets with worst +3.74 cents at
F#9 -50.0c and maximum within-target span 1.71 cents. Local means were -0.57c
at the low anchor, +0.20c at the high anchor, and +3.62c at the target;
endpoint-adjusted residual +3.92c. Their between-repeat ranges were respectively
0.15c, 0.05c, and 0.08c. Unlike the old curve's common local offset, this
supports a repeatable interpolation defect at this new worst location.

Automatic refinement attempted one correction, passed its local validation,
and began a full-range recheck. The overall 15-minute limit expired before that
recheck finished. Firmware returned output to commanded zero and rolled back
the unverified correction, exposing the fully checked 115-point fresh baseline
for review, not the refined curve. Status: `STOPPED - CALIBRATION TIME LIMIT`;
best worst remains +3.74c. Saved slot 4 remains the old baseline. This is neither
a completed refinement qualification nor a pass of the two-cent target.
The full-range timing budget must be revisited before promising automatic
refinement across this range; do not simply remove the safety bound.

### Repeat diagnostic on the fresh accepted CORE curve

Same log, after fresh candidate acceptance (no slot-4 reload): all 36 steps
completed and output returned to commanded zero. The serial profile endpoints
and target pitches confirm the fresh curve was used. Commands are identical to
the old-curve experiment; stored target pitches changed with reacquisition.

| Probe voltage | From below, mean error | From above, mean error |
|---|---:|---:|
| +4.416750 V | +0.06c | +0.22c |
| +4.454000 V | +0.32c | +0.51c |
| +4.500000 V | +0.18c | +0.38c |

Each directional mean contains two visits. The largest between-visit range is
0.24 cents; the largest directional-mean difference is 0.20 cents. The twelve
zero-volt reference measurements average +0.23 cents, range 0.35 cents.
Reacquisition therefore removed the approximately six-cent discrepancy at the
tested voltages without a global offset, extra local point, or detector change.
This supports a mismatch between the older curve and the current measured
response, but does not distinguish physical drift from original acquisition
bias. These local checks are not independent absolute accuracy validation and
do not erase the fresh full-range +3.74-cent worst error at another location.

### Automatic time-budget follow-up

The premature 15-minute stop led to a bounded budget change: 45-minute total
ceiling, unchanged eight-attempt cap and five-second verification deadlines.
Before starting any tentative refinement, reserve its complete worst-case
measurement budget (including full recheck and local validation); for 225
targets, 22 minutes 10 seconds. If unavailable, review the best checked curve
without starting an edit. Hard expiry still rolls back an unverified candidate.
Tests cover reservation boundaries, clock regression, refusal preserving both
accepted and checked curves, and expiry during recheck undoing the tentative
point. Calibration/ownership suites pass (8 pytest cases including Rust suites).

The firmware-only normal build restores standard CHECK scanning by setting
`TILIQUA_TUNER_REPEAT_DIAGNOSTIC=0`. R5, 192 kHz, unrotated 1280x720p60,
spread spectrum 0.0; no FPGA hardware changes. Saved profile slots remain intact;
the unsaved fresh test curve is intentionally discarded for the next automatic
calibration test. Build log: `/tmp/tuner-auto-budget-build.log`.

### Physical 45-minute-budget run: completed, borderline accuracy

`/tmp/tuner-auto-budget-live.serial.log`, CORE IN1 / OUT1. Serial phase
timestamps place the complete operation at approximately 24 minutes 12 seconds
(status messages are sampled, not exact transition timestamps): acquisition
about 111 s; initial verification about 423 s; first local refinement 35 s;
full recheck 424 s; second refinement 30 s; final full recheck 429 s.

Worst full-grid errors improved +4.03 → +2.77 → +1.97 cents over two accepted
refinements. Final candidate: 117 points, -4.833250..+4.666750 V, E0 +45.4c
through A9 -45.2c; final verification 225/225, worst G9 -50.0c, maximum span
1.23 cents. Output returned to commanded zero; candidate awaits acceptance,
saved slots unchanged. The time-budget change allowed both rechecks to finish.

Important qualification: final local repeats measured target mean +2.17c,
low anchor +0.14c and high anchor +0.11c; endpoint-adjusted residual +2.06c.
Target between-repeat range was only 0.05c. Firmware currently reports
`READY - WITHIN 2C TARGET` based on the +1.97c grid result before considering
these local repeats. Treat this as borderline, not a robust sub-two-cent
accuracy pass. Stopping/headline criteria must incorporate the already-measured
local absolute target error rather than ignoring contradictory repeat evidence.

The user explicitly objected to long calibration times. This 24-minute result
confirms the need for a faster default procedure, not a claim of superiority
to dedicated calibrators. Approximately 21 minutes were spent in three full-grid
verification passes; the two local refinements together took about one minute.
This breakdown identifies repeated exhaustive verification as the primary
optimization target while preserving safety and honest qualification.

### Targeted automatic verification (2026-09-19, hardware qualification pending)

The next firmware uses at most 50 sorted, deduplicated verification pitches:
33 evenly spaced coverage points including both endpoints, the measured
zero-volt reference when in range, and midpoints around up to eight strongest
measured curve bends. Refinements reuse this original probe set so before/after
scores are comparable. Manual CHECK retains the exhaustive 50-cent grid.
Both display and serial explicitly identify the automatic result as sampled;
an unsampled narrow error can be missed. No detector or FPGA logic changes.

Acceptance now includes the worst individual local repeat mean (including
anchor checks), and requires local repeatability within 0.75 cents. A regression
test covers the observed +1.97c grid / +2.17c repeat contradiction. Local
endpoint-adjusted residuals are not substituted for absolute error.

The automatic ceiling returns to 15 minutes. The existing conservative
reservation requires 7m35s for a complete 50-target refinement attempt, compared
with 22m10s for 225 targets. This is a timeout budget, not expected duration.
Settling, fresh measurement windows, and stability gates are unchanged.

Host tests cover bounds, ordering, exact probe reuse, completion, and shared
diagnostic-plan storage. Across 48 synthetic smooth-bend curves, the largest
underestimate versus the dense grid was 0.210 cents. A separate deliberately
narrow-error fixture demonstrates a miss; these models do not establish physical
accuracy. The next physical run must measure duration and then compare the
sampled result with exhaustive CHECK. Acquisition alone took about 111 seconds
in the preceding run, so a sub-minute total is not yet achieved.

### First targeted physical run: faster, outside 2-cent target

`/tmp/tuner-targeted-check-live.serial.log`, Generate3 CORE IN1 / OUT1,
unchanged tuning. All 35 selected pytest regression cases passed before the
slot-1 flash; serial resumed on `/dev/cu.usbmodem83102`.

Sampled phase timestamps: acquisition 220983..331789 ms (~111 s), initial
45-pitch check and local repeats to 417378 (~86 s), first refinement to
447644 (~30 s), same-pitch recheck to 538556 (~91 s), second refinement to
568869 (~30 s). Total approximately 5m48s, versus the preceding 24m12s run.
These are different calibration runs/results, not an equal-accuracy benchmark.

Worst checked error improved +4.89c to +2.55c after the first accepted edit.
The second edit stopped at its local no-gain gate, preserving the 116-point
best checked candidate. Final status `REFINE NO GAIN - ORIGINAL` refers to
rolling back that attempt, not losing the first improvement. Candidate range
-4.833250..+4.666750 V, E0 +44.4c through A9 -45.3c. Output commanded zero;
saved profiles unchanged; candidate awaits user acceptance in RAM.

Retained sampled grid worst +2.53c; worst including individual local repeats
+2.55c at B5 +0.5c. Local aggregate target +2.36c, repeat range 0.30c;
anchors -0.29c and -0.17c. This is explicitly outside the 2-cent target.
Exhaustive CHECK of this exact candidate is the next hardware comparison;
unsampled errors remain unknown. No flash or retuning before that comparison.

### Exhaustive comparison of the 116-point targeted result

The user accepted the candidate in RAM and ran PROFILES / CHECK without
retuning or flashing. Same transcript as above. The first sampled active status
was at 779161 ms (already 1/225); the grid completed by 1207040 ms and local
checks/output-zero status by 1217264 ms: roughly 7m20s total, with a small
unobserved start interval from periodic reporting.

All 225 targets completed. Grid worst +1.94c at G9 -50.0c, maximum within-target
span 1.06c. The subsequent nine local measurements had target aggregate +2.20c,
between-repeat range 0.09c, span 0.44c. Low/high anchors +0.24c/+0.41c;
endpoint-adjusted residual +1.85c is not the absolute error. Therefore the
grid-only result must not be described as a robust within-2c pass.

No large unsampled error was exposed on this physical curve. B5 measured
+1.76c in the later dense scan versus approximately +2.5c earlier, showing that
small differences between sequential runs cannot be attributed solely to
sampling. This is useful evidence for the faster default, not proof that it
will detect every narrow defect or that absolute external accuracy is within
two cents. Output is commanded zero; the accepted RAM curve and saved slots
were not changed by CHECK.

### Follow-up reporting and timing build

Manual CHECK now uses the same local-inclusive worst error as automatic review,
retaining `VERIFY GRID_WORST_C` separately on serial. The shared accuracy label
requires complete local checks and repeatability, and never equates completion
with a pass. Regression coverage includes the observed +1.94c grid / +2.20c
local contradiction, an incomplete check, and a passing check; reporting must
not mutate the profile and must fit the bounded serial packet.

Refinement rejection distinguishes worse results from insufficient gain; both
say BEST KEPT rather than the ambiguous ORIGINAL. Tests cover the two reasons
and unstable repeats. Automatic serial telemetry adds four bounded per-phase
millisecond counters, accumulating repeated attempts and freezing at review.
No acquisition delays, averaging windows, stability limits, pitch detector, or
FPGA logic were changed. Further speed work must preserve the difficult
Generate3 low-note qualification rather than simply shortening its averaging.

### Reporting build: slot-4 reload and physical CHECK validated

User saved the 116-point candidate to slot 4 before flashing. Reporting build
passed all 35 selected pytest cases, flashed slot 1 successfully, and resumed
serial at `/tmp/tuner-check-report-live.serial.log`. Slot 4 reloaded on IN1 /
OUT1; 225/225 targets and all nine local repeats completed without timeout.

Grid worst +2.34c at G9 -50.0c; local target aggregate +2.63c with repeat range
0.15c and span 0.28c. The revised headline correctly reports the worst individual
repeat, +2.70c, alongside the separate grid result. Final accuracy label:
`OUTSIDE 2C OR NOT REPEATABLE` (here the error magnitude exceeds 2c, while repeats
are stable). Maximum grid span 0.94c. Output returned to commanded zero.

This physically validates the reporting correction and saved-profile reload,
not an accuracy improvement: measurement and correction behavior were unchanged.
The difference from the preceding +1.94c grid / +2.20c local result is between
sequential runs and is not evidence of a detector or calibration-code regression.
It also does not identify the cause of that variation. Profile remains unchanged.

### Tight-signal verification shortcut (physical qualification pending)

Low-note verification previously always waited for sixteen independent windows,
including clean stable inputs. The new path permits eight independent windows
only if every observed qualified post-settle reading stays within 1c. Overlapping
frames still participate in that span guard but cannot fill the eight-window
requirement. An excursion exceeding 1c latches the shortcut off until the
estimator is cleared for a new target/acquisition; internal span/gap resets do
not re-enable it. The existing sixteen-window estimator and block agreement
checks remain unchanged for the fallback. Initial sweep acquisition is unchanged.

Tests cover independent/overlapping frames, ordinary and reset-inducing spikes,
clear/rearm, and a live-adapter comparison: a tight synthetic low note completes
before 2.5s while a +/-2c waveform retains at least sixteen independent windows
and takes at least 1.2s longer. Existing captured Generate3 averaging regressions
also pass. This is a speed hypothesis to qualify physically against saved slot 4,
not proof of equivalent accuracy for every modulation pattern. Settling and
measurement freshness requirements remain unchanged.

### Tight verification physical comparison: useful time reduction

Built and flashed slot 1 after all 35 selected pytest cases passed. User loaded
the same slot-4 curve and ran CHECK with unchanged patch/tuning. Transcript:
`/tmp/tuner-tight-check-live.serial.log`. First active periodic status at 507204
ms already had 2/225 targets; output-zero completion was at 847339 ms. Allowing
for the unobserved start gives approximately 5m45s versus about 7m32s for the
preceding long-window check, roughly a quarter faster. This is sampled timing,
not a precise start-to-stop benchmark.

225/225 grid targets and nine local repeats completed without timeout. Grid
worst remained +2.34c at G9 -50.0c. Local aggregate +2.61c, repeat range 0.15c,
span 0.30c; worst individual repeat +2.68c (previously +2.70c). Maximum grid
span 0.96c. Low-range worst was about -1.81c versus -1.96c previously. This
comparison shows no obvious accuracy regression on this CORE waveform; it
does not qualify all waveforms or modulation patterns. Accuracy label correctly
remained outside 2c. Curve and saved slots unchanged, output commanded zero.

Next hardware step: a complete automatic CAL run on IN1/OUT1 without retuning,
to exercise acquisition, sampled checking, bounded refinement and phase timing
together. Slot 4 retains the comparison baseline.

### Complete automatic run with tight-window verification

Same `/tmp/tuner-tight-check-live.serial.log`. Phase timers: acquisition
110508 ms, initial checking 73131 ms, refinement 62295 ms, rechecking 146170 ms;
total 392104 ms (6m32s). Two local proposals passed their paired tests. The first
was kept; the second was rolled back by the range-wide gain policy. Retained
116-point candidate: -4.833250..+4.666750 V, E0 +43.1c through A9 -45.0c.
Checked worst +2.55c at F#9 +39.7c; grid +2.23c; local aggregate +2.54c with
repeat range 0.02c. Output zero; saved slots unchanged. No within-2c pass.

The rejected recheck score was not retained in this firmware, so its exact
reason cannot be established beyond failing the policy. Code inspection and
tests expose an overly restrictive case: a locally proven correction can be
rejected merely because a different pitch becomes worst and the global maximum
improves by less than 0.5c. The next policy retains the independent >=0.5c local
gain requirement, but uses strict global non-regression plus valid/repeatable
local checks for retention. A tied global maximum is allowed only after that
paired local proof. Even 0.01c worsening is rejected. Incomplete local checks
or missing tentative-point proof reject retention. Attempt/time bounds remain.

Serial now retains old/new checked errors and the keep/rollback decision.
This policy change is motivated by a tested case, not a claim that the missing
score from the preceding physical run necessarily represented such a case.

### Revised recheck policy: automatic physical run, September 20

`/tmp/tuner-recheck-policy-live.serial.log`, IN1/OUT1, unchanged Generate3 CORE
patch and tuning. Acquisition 111552 ms, initial check 74230 ms, two local
refinements 63076 ms, two rechecks 148322 ms: total 397180 ms (6m37.18s).
First recheck kept +5.12c -> +2.80c; second kept +2.80c -> +2.00c (rounded).
Both exceed the old 0.5c global-gain requirement, so this run does not physically
exercise the newly allowed tied/smaller-gain case or prove that policy change
caused success. Exact decision telemetry now survives review as intended.

Final status `READY - SAMPLED CHECK WITHIN 2C`, 45/45 sampled targets,
117-point candidate, -4.833250..+4.666750 V, E0 +43.8c through A9 -45.0c.
Grid worst +1.95c; worst including individual local repeats rounds to +2.00c
at B5 +0.4c. Local aggregate target +1.96c, repeat range 0.07c, span 0.35c;
anchors +0.04c/-0.01c. This is a borderline sampled pass, not robust evidence
of absolute +/-2c accuracy or a certificate of unsampled pitches. Output zero,
candidate awaiting acceptance, saved slots unchanged. Next: accept in RAM and
run exhaustive CHECK without retuning; slot 4 remains the earlier baseline.

### Exhaustive follow-up: borderline sampled pass did not persist

Accepted the 117-point result in RAM, unchanged patch/tuning, same transcript.
225/225 targets and nine local repeats completed. Dense-grid worst +2.48c at
B5 +0.0c; local target aggregate +2.48c (repeat range 0.07c, span 0.38c), worst
individual repeat +2.52c. Adjacent anchors +0.12c/+0.03c. Maximum grid span
0.91c. Final label correctly outside 2c; output zero; no profile mutation.

The previous sampled worst was B5 +0.4c, so this is not clear evidence of a
narrow error between widely separated samples. Timing variation and slightly
different target placement are confounded; neither cause is established.
Regardless, a borderline sampled pass did not ensure a later dense pass.

Next build introduces an empirical 0.5c automatic-completion margin: continue
safe bounded refinement toward 1.5c before declaring the sampled 2c target met.
Manual CHECK still reports against 2c; raw measured errors are unchanged.
Serial distinguishes TARGET_C=2.0 and AIM_C=1.5. The margin is not a calibrated
uncertainty estimate and cannot guarantee future accuracy. Existing rejection,
rollback, capacity, pass-count and time limits may still stop above that aim.
Tests cover positive/negative boundary values and ensure manual criteria stay
unchanged. Slot 4 remains the earlier comparison baseline.

### Completion-margin build: bounded run retained best curve

`/tmp/tuner-completion-margin-live.serial.log`, unchanged CORE IN1/OUT1.
Acquisition 113529 ms, check 75178 ms, three local refinement attempts 95697 ms,
two range rechecks 150157 ms: total 434561 ms (7m14.56s). Kept +5.12 -> +2.78
-> +2.03 cents. Third local proposal was worse and rejected before another
range recheck. Final status `REFINE WORSE - BEST KEPT`; retained 117-point
candidate, -4.833250..+4.666750 V, E0 +44.5c through A9 -45.0c.
Local aggregate target +1.99c, repeat range 0.08c; anchors -0.07c/-0.23c.
Output commanded zero, saved profiles unchanged, candidate awaiting acceptance.

The 1.5c aim was not achieved. Because the retained error was also above the
old 2c stopping threshold, this run does not establish a benefit from the new
completion margin. The independent rejection guard successfully retained the
best checked curve. Further tiny-threshold tuning on this single CORE signal
is not justified by this evidence. Next qualification should use FUND on IN1
with OUT1 still driving the same oscillator, retaining slot 4 as the CORE
baseline. This requires the user's physical repatch; do not flash or retune
merely to repeat the same CORE experiment.

### FUND calibration: repeatable upper-range octave-selection failure

User changed CORE to FUND on IN1, leaving OUT1 and tuning unchanged, then ran
CAL. Same completion-margin serial transcript. Acquisition failed after
101018 ms, point 105/121, +3.750000 V. Previous accepted point +3.666750 V,
13080812 millicents; rejected observation 11985131 millicents: a -1095.681c
step where the nominal voltage increment implies about +100c. Acquisition
diagnostics QUAL=49, UNQUAL=0, TIGHT=4, AVERAGING=false; this is qualified
non-monotonic tracking, not a low-note averaging timeout or refinement failure.
No automatic check/refinement began. Output returned to commanded zero and no
new completed profile was produced; saved slots remain intact.

Consistent with the previously captured phase-sensitive FUND upper-octave
ambiguity, but this run did not capture a new waveform or simultaneous CORE
reference at the failure. Do not automatically double the observation, widen
tracking tolerances, or call the earlier points a verified complete profile.
Next diagnostic requires physical setup: retain FUND on IN1, add CORE on IN2,
and reproduce the upper-frequency drop on the tuner without running calibration.
This separates a detector octave switch from an actual oscillator-frequency
change before any further detector change is justified.

### Simultaneous FUND / CORE boundary reproduction

User retained FUND on IN1 and connected CORE to IN2, then held the controls.
The completion-margin live transcript at uptime 1097132..1099186 ms shows
IN1 alternating between approximately 15824 Hz and 7913 Hz while IN2 remains
approximately 7913 Hz. The effect persists later in the same transcript.
Both native readings are qualified, with no reported detector faults. This
supports a FUND octave-selection switch rather than a halving of CORE pitch;
it does not by itself establish which component should be called fundamental.

Built and flashed temporary full-wave diagnostic firmware (same FPGA, slot 1,
1280x720p60, spread_spectrum=0.0) to capture the unchanged signals and replay
their exact integer detector scores. Build/flash logs:
`/tmp/tuner-fund-core-wave-{build,flash}.log`; capture transcript:
`/tmp/tuner-fund-core-wave.serial.log`. No threshold change is justified solely
by the live frequency ratio.

All eight channel/bank waveform exports validated exact energy and score replay.
IN1 native selects 7917.038 Hz at cutoff .90: longer-period refined clarity
.9992068; cutoff .85 selects 15834.076 Hz, shorter-period clarity .8993118.
IN2 CORE selects 7916.252 Hz with either cutoff, clarity .9998527. Thus this
fresh capture reproduces the existing boundary fixture: FUND's first-period
candidate sits immediately below the relative cutoff. A global cutoff change
would move the ambiguity boundary and regress the documented strong-second-
harmonic cases, not resolve intended-pitch ambiguity. Restore normal continuous
firmware after capture; no production selector thresholds changed.

### Phase-adjusted paired capture

User barely adjusted PHASE and reported stable 15.8 kHz. A 30-second live
window contains 74 FUND readings, all 15787.277..15795.238 Hz; 74 CORE readings
remain 7894.263..7897.508 Hz. Full diagnostic capture again validates all eight
channel/bank exports. FUND now selects 15794.636 Hz, first-period clarity
.9208190 (previous .8993118); CORE selects 7896.236 Hz. The small phase change
moves FUND across the selection boundary without an octave change in CORE.

Six-harmonic least-squares fits to the captured centered samples give the
half-frequency/dominant amplitude ratio .20439 before versus .18147 after.
These are same-device acquisition observations, not proof of signal origin or
independent oscillator accuracy. Do not infer a defective oscillator or fix
this by unconditional doubling/global cutoff relaxation.

Retained native captures in `tests/fixtures/generate3-phase-boundary.json` and
added a replay regression for the before/after ratios. Temporary logs:
`/tmp/tuner-phase-adjusted.serial.log` and matching build/flash logs; normal
continuous firmware restored using `/tmp/tuner-phase-restore-*` logs.

### Phase-adjusted FUND calibration: boundary moved, not eliminated

User lowered coarse tuning to roughly 600 Hz on FUND, retained phase, then ran
IN1 / OUT1 calibration with CORE still on IN2. Transcript:
`/tmp/tuner-phase-restored-live.serial.log`. Acquisition failed at point116/121,
+4.833250 V after115192 ms; previous +4.750000 V pitch13177266 millicents
(16525.596 Hz), rejected12088250 millicents (8809.848 Hz), step-1089.016c.
QUAL50, UNQUAL0, TIGHT0, AVERAGINGfalse. No automatic verification/refinement
started. Output returned to commanded zero; no completed new profile.

Crucially, paired live reports show CORE rising normally from approximately
8262 Hz to8810 Hz while FUND changes from approximately16524 Hz to8810 Hz.
This distinguishes the FUND octave-choice discontinuity from actual downward
oscillator tuning. The adjusted phase extends the higher-component selection
range but does not guarantee it across frequency. Do not repeat phase-tweaking
scans indefinitely or save this discontinuity as a calibration correction.
CORE is the demonstrated reliable calibration source for this oscillator;
FUND remains a retained phase-sensitive robustness case.

### CORE comparison at unchanged phase/tuning: completed automatic calibration

User selected IN2 / OUT1 without changing patch or controls. Same
`/tmp/tuner-phase-restored-live.serial.log`. Acquisition completed107 points
in127374 ms, crossing FUND's failed upper region. First48-target automatic
check worst-3.99c. First refinement passed its local proof and same-target
recheck, improving checked worst to+1.79c; kept. Second refinement worsened
its local result and was rejected (`REFINE WORSE - BEST KEPT`).

Final review:108 points, -3833250..5000000 uV, E0+42.3c..D#9-0.8c;
worst B5+2.8c target, grid/checked error+1.79c. Nine local observations:
low mean-.09c/span.19c/repeat.19c; high-.07c/.65c/.14c;
target+1.68c/.28c/.03c. Endpoint-adjusted+1.75c is not absolute error.
Phase times127374+79075+64535+79238=350222 ms (5m50.222s).
Meets2c on sampled checks, not the1.5c completion margin and not an exhaustive
range certificate. Output commanded zero; candidate awaits user acceptance,
not saved automatically. This supports CORE as the reliable calibration source
on this patch and validates retaining the earlier curve after local regression.

### Accepted CORE dense check and retained refinement diagnostics

User accepted the108-point curve, ran PROFILES/CHECK, then explicitly saved it
to slot4. Dense check completed213/213 targets without tracking failures.
Grid worst+2.16c at B5; checked worst including local observations+2.26c.
Local target mean+2.24c/span.38c/between-pass discrepancy.05c. Bracket endpoints:
1666750uV mean-.01c,1750000uV mean-.14c. Endpoint-relative residual+2.34c
(passes+2.33,+2.37,+2.32), not absolute accuracy. Result correctly reports
outside2c; this is a repeatable local residual, not a broad oscillator failure.
Do not claim the earlier48-target+1.79c check certifies all pitches.

Inspection found automatic review clears the refinement object before its
paired comparison can be reported. Added a fixed-size retained diagnostic:
`AUTO REFINE_TEST MC=... OLD_C=... NEW_C=... MAX_REPEAT_C=...`.
It selects the paired test with the largest increase in absolute error and
reports the largest repeat discrepancy across all paired tests. Emitted only
after complete paired validation, retained through recheck/review, and reset
for a new automatic run. No detector, acceptance threshold, curve mathematics,
FPGA, or storage-format changes. Unit/integration checks cover partial results,
regression identification, retention, and fixed serial packet headroom.
Build/flash logs `/tmp/tuner-refinement-summary-{build,flash}.log`.

### Diagnostic rerun: transient comparison instability

IN2/OUT1 rerun acquired107 points; first47-target check checked worst-3.86c
at C9+32.5c (grid-3.57c). First refinement rejected for paired repeatability:
maximum discrepancy.87c, above unchanged.75c limit. The retained least-improved
pair MC11925061 was old+.06c/new+.07c; it is not necessarily the pair with the
maximum repeat discrepancy. Local acquisition target mean-3.73c, endpoints
-.23/-.24c, residual-3.50c. Phase times133161+80754+33075=246990ms.
Transcript `/tmp/tuner-refinement-summary-live.serial.log`. Saved slot4 baseline
is unchanged; the new unrefined candidate is inferior and disposable.

Implemented one bounded fresh local retry only for `REFINE COMPARE UNSTABLE`.
No threshold relaxation, octave correction, full sweep restart or unvalidated
curve edit. Retry counts toward pass cap, requires unchanged candidate state
and completed baseline, and reserves the full attempt/recheck budget. Host
integration covers transient recovery and persistent failure; policy tests cover
deadline, pass cap, prior retry, tentative edits, incomplete baseline and wrong
phase. Diagnostic packet headroom remains tested. Hardware validation pending.
Build/flash logs `/tmp/tuner-refine-retry-{build,flash}.log`.

### Bounded-retry build hardware run: stable rejection explained

Same IN2/OUT1 patch; `/tmp/tuner-refine-retry-live.serial.log`.
Acquisition107 points completed. First47-target check worst-3.74c; first local
comparison maximum repeat discrepancy.18c, so no retry needed. Recheck kept
the inserted point, improving checked worst to+1.69c (grid+1.53c) at B5+2.4c.
Second refinement rejected as worse: retained paired test MC8268667 changed
old+.13c to new-.57c; maximum repeat discrepancy only.17c. This is a stable
local regression observation, not another unstable-comparison event. The
summary does not retain every pair or both global paired maxima, so it alone
does not identify which of the two regression guards rejected the proposal.

Retained108-point candidate; final local low mean+.04c/span.13c/repeat.05c,
high-.13c/1.00c/.13c, target+1.62c/.30c/.13c; relative residual+1.70c.
Phase times133580+79089+68444+80881=361994ms (6m01.994s).
Meets2c on sampled checks only; prior dense+2.26c baseline remains evidence
against claiming full-range2c certification. No detector failure. No instability
retry occurred: live recovery branch remains unexercised, despite host tests
for transient recovery/persistent failure. Do not rerun indefinitely merely
to provoke noise. Candidate awaits acceptance; saved slot4 remains unchanged.

User subsequently confirmed acceptance/save: slot4 now holds this latest
108-point Generate3 CORE candidate (automatic sampled worst+1.69c). The earlier
slot4 curve with dense checked worst+2.26c was replaced; do not attribute that
dense result to this exact latest curve. Generate3 investigation is paused at
this documented limitation; next planned oscillator qualification is Mother-32.

### Upward reference search and Waveplane limited-repeatability runs

The calibration sweep now searches upward from 0 V in semitone steps when the
initial oscillator frequency is below the detector's usable range. This is a
bounded search only; the stored curve remains a monotonically acquired -5 V to
+5 V subset, and a missing reference is not silently converted into a profile.
The default calibration route is now IN0 / OUT0.

Two Dove Audio Waveplane runs exercised this behavior. The first acquired 58
usable points but lost qualified pitch during automatic verification near
+2.03 V. The repeat acquired the same 58-point usable range through +5 V and
passed that earlier target, but later lost pitch at corrected output +3.961 V
(failed target 6347072 millicents). Immediately before the second loss the
low-bank detector repeatedly qualified approximately 319.4 Hz; it then produced
no qualified result, with one isolated 1327.892 Hz native candidate rejected by
the existing qualification guard. Acquisition took 189247 ms and verification
stopped after 85315 ms. The different failure positions do not support a
deterministic firmware boundary. Both curves were correctly rejected and no
saved profile changed. Treat Waveplane as a deliberately difficult tracking
case pending independent confirmation of its usable CV/pitch range.

A later AUTO-policy regression run retained 83 survey anchors after 63 missing
low-range positions and one unstable high-range position. Replay found separate
unstable boundaries and safely narrowed the candidate from roughly +0.25..+7.75
V to approximately +2.50..+5.33 V. A further interior check near +3.2085 V
(about 183 Hz) still drifted: sixteen independent errors ranged from -0.31c to
-6.67c, with 11.90c total span, 5.28c quarter-block disagreement and 2.64c
half-block drift. All 204 detector frames were valid and qualified, so this was
oscillator motion rather than signal loss. Firmware correctly rejected the
candidate after the then-current one-recovery-per-boundary limit. This run
motivated bounded repeated segmentation: retain the larger contiguous side,
restart verification, and allow at most four destructive recoveries without
weakening the ten-cent Character stability grade.

### WMD Legion: successful conventional analog control

With Legion sine on IN0 and OUT0 driving V/oct, upward search found the usable
low endpoint around -3.58 V. Acquisition retained 105 points through +5 V in
125129 ms. The 47-target sampled verification plus nine local observations
completed in 80095 ms with no refinement required. Local absolute means were
-0.16c at the low bracket, +0.25c at the high bracket and +0.84c at the target;
within-window spans were 0.35c, 0.42c and 0.37c, and between-repeat ranges were
0.49c, 0.18c and 0.08c. The endpoint-adjusted residual was +0.79c (not an
absolute-error claim). Final status was `READY - SAMPLED CHECK WITHIN 2C`.
This validates the upward-start search and IN0/OUT0 default on a conventional
analog VCO while preserving the distinction between sampled verification and
full-range certification.

### Castor & Pollux II: positive-only V/oct input

Castor & Pollux II held its panel-set pitch (approximately 278.3 Hz) throughout
the negative half of Tiliqua's sweep, then reset downward at the start of its
positive V/oct response.  The guarded dead-zone logic retained one provisional
plateau point, discarded it only after the downward reset proved the plateau,
and then acquired a monotonic 60-point curve from +0.08325 V through +5 V.  It
did not manufacture flat calibration points or grant a general octave-drop
exception.  The measured +0.08325 V boundary is honest hardware behavior from
this run: the oscillator still held its panel pitch at exactly 0 V and changed
at the next semitone-grid voltage.

The 46-target automatic check completed with a sampled worst of -2.32c.  A
local refinement proposal was rejected after its paired comparison remained
unrepeatable on the one bounded retry (`MAX_REPEAT_C=0.80`); the original curve
was preserved.  Local means were -0.29c at the low bracket, -0.36c at the high
bracket and -1.79c at the target, with an endpoint-adjusted residual of -1.47c
(not an absolute-error claim).  Acquisition/check/refinement times were
108851/104608/61025 ms.  This qualifies positive-only range discovery and safe
refinement rejection, but does not establish a sampled-within-2c release claim.

Profiles whose measured lower boundary is nonnegative and `limited_low` now
report `POSITIVE-CV INPUT; LOW REQUESTS CLAMP`.  Replay clamps requests below
that boundary rather than extrapolating through the oscillator's ignored
negative-CV region.  A follow-up implementation automatically extends the
upward pass to the hardware-safe +8 V ceiling only after the negative plateau
and downward reset prove a positive-only input.  Ordinary bipolar and nominal
unprofiled output remain bounded to -5..+5 V.  The extended C&P2 path and its
approximately eight-octave result still require hardware validation.

The physical extended-range rerun validated that path. The negative sweep held
one plateau anchor through 0 V, the oscillator reset into normal tracking above
zero, and characterization continued beyond +5 V as designed. A single flat
observation established the oscillator's actual upper tracking boundary near
+6 V; the scan still probed through +8 V rather than assuming that limit.
The resulting 72-point profile spanned +0.083 through +6.000 V, measured a
conventional 1008 mV/octave response, and completed all 47 sampled targets plus
nine local checks without recovery or trimming. It graded `MUSICAL`: 2.07 cents
worst sampled error and 4.16 cents stability. Low/high local repeat ranges were
0.86/0.19 cents. This qualifies both guarded positive-only discovery and the
conditional +8 V survey extension; replay clamps below the measured boundary
and does not extrapolate above the oscillator's detected +6 V limit.

### Acid Rain Chainsaw: ensemble outputs and replay-edge recovery

Chainsaw has no single-oscillator audio output: each active voice always sums
seven waves, distributed across its stereo outputs. Minimum detune places those
waves in unison but does not bypass the ensemble. With OUT0 driving V/O 1, its
saw output did not produce a calibratable response: IN0 retained at most four
contiguous points and IN1 at most three. Both were rejected before automatic
verification by the one-octave / thirteen-anchor minimum.

The square setting was substantially more trackable. It acquired a contiguous
64-point response from approximately +2.2 V through +7.5 V, about 5.25 octaves.
Automatic sampled verification then reproduced two targets but timed out near
the lower measured boundary at corrected output +2.29175 V. This is evidence
of a marginal detector boundary, not evidence that the stored interior curve
is inaccurate. The candidate was correctly rejected by the flashed build.

The subsequent implementation adds bounded automatic replay-edge recovery.
Only an initial verification failure among the first or last three targeted
checks is eligible. It removes measured anchors through that failed voltage,
restarts the full sampled check, and reports the edit over serial. It may retry
twice and remove at most four anchors total; it never fabricates points,
extrapolates, edits an accepted profile, trims an interior failure, trims a
refinement recheck, or retain fewer than thirteen anchors. Host coverage passes,
but the Chainsaw square path still requires a hardware rerun before it can be
called qualified.

The target-guided rerun did not qualify Chainsaw's square ensemble. Acquisition
reported 53 missing and 43 unstable survey points, retained 26 candidate anchors
and safely stopped verification at +2.25 V. Across 203 fresh detector frames,
the reported candidates spanned 49.05–1028.57 Hz and never formed the required
eight-reading cluster around the independently commanded target. This is a
persistent multi-period ambiguity, not a reason to weaken the detector. The UI
now names this bounded failure `FAILED - AMBIGUOUS WAVEFORM`; the prior accepted
profile remains untouched.

A later square-output AUTO run under the graded policy converted that bounded
failure into a useful profile without weakening detection. Characterization
retained 102 measured anchors after 55 expected low/sub-audio misses and found
no unstable, flat, or discontinuous survey positions. Four bounded replay
recoveries removed the marginal low region; the final candidate retained 94
points from +0.250 through +8.000 V. All 48 sampled targets and nine local
checks completed. It measured a conventional 984 mV/octave response and graded
`CHARACTER`: 3.43 cents worst sampled error and 7.45 cents stability. Local
repeat ranges remained below one cent even though within-target spans were
about seven cents, consistent with the permanent seven-voice ensemble output.
This is a successful bounded calibration of Chainsaw's square path, not a
precision claim; low requests clamp to the measured +0.250 V boundary.

### Pittsburgh Modular Local Parks: sine baseline

With Local Parks' sine output on IN0, modulation disabled, and OUT0 driving
V/oct, AUTO retained 111 anchors from -1.167 through +8.000 V after 46 expected
sub-audio misses. It measured a conventional 998 mV/octave response and needed
no range recovery or trimming. All 48 sampled targets and nine local checks
completed. The result graded `PRECISION`: 1.84 cents worst sampled error and
2.89 cents stability. Low/high/target local repeat ranges were
0.22/0.23/0.39 cents. A tentative local refinement provided no reliable gain,
so the verified original curve was correctly retained. At this panel tuning
the measured high endpoint was F#9 rather than 20 kHz, hence the optional
higher-tuning advice; that coverage note does not invalidate the profile.

The same patch and panel tuning were then repeated with a static, moderately
complex Blade output and modulation disabled. Characterization retained 111
anchors after 36 missing and eight unstable low-region observations. One
bounded low-edge recovery left a coherent 107-point curve, and all 47 sampled
targets plus nine local checks completed. Accuracy remained plausible at
4.60 cents worst, but the 11.65-cent maximum stability span exceeded the
ten-cent Character ceiling; the high local bracket alone spanned 16.84 cents.
A tentative refinement changed its paired local result from -0.68 to -0.92
cents and was correctly rejected as no gain. The candidate was not offered for
use. This establishes a useful waveform-dependent boundary on one oscillator:
the sine output is Precision, while this static Blade setting is measurable but
not repeatable enough for a safe static correction profile.

At the same tuning, a static approximately 50% pulse/square output reproduced
the sine's 111-point -1.167 through +8.000 V interval and the same 998
mV/octave response, with no recovery or trimming. All 47 sampled targets and
nine local checks completed. It graded `MUSICAL`: 1.92 cents worst sampled
error and 4.12 cents stability. Local low/high/target repeat ranges were
0.58/0.96/0.27 cents. The richer waveform therefore cost some stability versus
the Precision sine baseline but did not distort the inferred V/oct response.

With the same panel tuning and modulation disabled, a static narrow pulse was
still calibratable, but over a shorter range. The survey recorded 56 missing
positions (mostly below the audio floor and above the high-frequency limit)
and three unstable high-end readings, with no flat regions or discontinuities.
AUTO retained 80 anchors from -1.000 through +5.58325 V and measured a
conventional 997 mV/octave response. All 46 targeted checks and nine local
checks completed. It graded `CHARACTER`, acceptable for use in RAM, at 3.32
cents worst sampled error and 8.60 cents stability. Local low/high/target
repeat ranges were 0.78/0.39/0.58 cents. This is worse than the static square
and sine baselines but does not lose the fundamental throughout the retained
range. The upper range is detector-limited for this narrow-pulse setting; the
graded result must not be presented as full -5..+8 V coverage. Acquisition and
check took 237274 ms and 130164 ms, respectively. The disposable candidate
was not saved.

### WMD Legion: extended-range confirmation

A later full -5..+8 V survey on Legion retained 108 points from -5.000 V through
approximately +6.91675 V. Thirteen high-edge survey positions were missing;
there were no unstable, flat, or discontinuous observations. All 48 targeted
automatic verification samples completed. The sampled worst was -2.46c, while
the nine-point local comparison was repeatable enough to report
`LOCAL ERROR <1C - NO REFINE`; maximum observed span was 1.78c. The measured
response was 1002 mV/octave and classified conventional. Acquisition and check
took 154625 ms and 69173 ms respectively. This confirms safe upper-range
discovery and replay on a straightforward VCO; sampled shared-detector checks
remain distinct from independent absolute certification.

### Instruo Ts-L: sine-output survey

With Ts-L sine on IN0 and OUT0 driving 1 V/oct, the full survey retained 110
points from -5.000 V through approximately +7.08325 V. It reported nine missing
high-edge positions, no unstable or flat observations, and one discontinuity.
All 49 targeted automatic verification samples completed with sampled worst
-1.52c. The nine local observations had low/high/target means of
-0.69c/-0.99c/-1.22c; their spans were 0.63c/1.35c/0.90c. The low comparison's
1.08c between-pass discrepancy exceeded the unchanged repeatability bound, so
the firmware safely retained the measured curve without refinement and reported
`REFINE NOT REPEATABLE`. Maximum span across the sampled check was 7.74c.

The fitted response was 974 mV/octave and classified conventional. Acquisition
and check took 163849 ms and 72850 ms. This is a successful sampled tracking
result with a localized repeatability warning, not independent absolute or
dense full-range certification. The disposable candidate was not saved.

### Instruo Ts-L: stationary folded-output stress test

Without changing the Ts-L pitch controls or OUT0-to-1-V/oct route, the audio
input moved from sine to a moderately folded stationary output. Signal remained
present at the ADC throughout the test, but the complete -5..+8 V survey
retained zero anchors: all 157 survey positions were missing. The acquisition
observed 191 valid-but-unqualified detector frames, no qualified frames, and
reported a bounded waveform-wide failure only after completing the commanded
range. The UI now distinguishes this signature as
`FAILED - AMBIGUOUS WAVEFORM`, rather than incorrectly describing it as a lost
reference pitch. This rules out a localized voltage-range boundary for that
fold setting.

A temporary full-score diagnostic firmware was built and flashed, but produced
no debug-UART records after reboot; it was abandoned without changing detector
policy, and the normal continuous four-channel firmware was restored. The
survey evidence supports safe rejection of this particular stationary folded
shape, but does not yet identify which guard or period family rejected it.

At a subsequently reduced fold setting where the normal tuner again published
a stable pitch, the full survey retained 120 points from approximately
-3.16675 V through +8.000 V. Twenty-one low-edge positions were missing, with
no unstable, flat, or discontinuous observations. Edge recovery trimmed one
additional low point. All 47 targeted verification samples completed; sampled
worst error was -1.01c and maximum span was 6.94c. The nine local observations
had low/high/target means of -0.08c/-0.09c/-0.31c, with between-pass
discrepancies of 0.33c/0.74c/0.63c, so no refinement was needed. The measured
response was 975 mV/octave and classified conventional. Acquisition and check
took 164365 ms and 91071 ms. This establishes a useful operating boundary:
the detector safely rejects the heavier stationary fold while calibrating the
milder, tuner-qualified fold to within the sampled two-cent target.

A follow-up near the visible tuning boundary completed the same full-range
survey but was not calibratable. It accumulated 55 missing positions, 16
unstable positions, two discontinuities and two bounded period-family
corrections. The retained candidate collapsed to 25 points, and replay at
approximately +5.125 V alternated between 4015.59 Hz and 8050.00 Hz despite
209 of 212 detector frames remaining qualified. This is an adjacent-period
ambiguity, not silence or an output timeout. The automatic path continues to
zero the output and preserve the prior profile; the UI now reports
`FAILED - AMBIGUOUS WAVEFORM` for this one-octave family-spread signature.

### WGD Modular Peach: stationary digital-estimate jitter

Two otherwise clean OSC1 sine surveys each retained 59 anchors and found the
same flat upper boundary at +5 V. Automatic replay stopped at different points:
approximately +1.792 V on the first run and +0.613 V on the repeat. Both stops
had essentially continuous fresh, valid detector data and no audible tracking
break. The latter reported roughly 143.75--144.43 Hz, a bounded estimator span
just over the three-cent instantaneous-settling limit. Because the failure did
not repeat at one voltage and remained within one period family, it is treated
as stationary digital pitch/period quantization rather than a bad curve.

Automatic target-guided replay now permits the existing sixteen-window bounded
average at all pitches. It retains the eight-cent raw-span ceiling and requires
quarter-block means within two cents and half-block means within one cent.
Manual verification and the normal tuner remain unchanged. A physical repeat
is still required before recording Peach as qualified.

The first physical repeat passed both earlier stop points, then stopped around
+2.875 V (about 710 Hz). The detector remained fresh and in the commanded
period family, but adjacent fine-period estimates covered about 19 cents and
repeatedly reset the eight-cent averaging window. Automatic target-guided replay
therefore permits a 25-cent raw estimator span while retaining the same strict
quarter- and half-block agreement tests. This wider bound is not used by manual
verification or low-note acquisition. Another physical repeat is required.

That repeat passed the previous +2.875 V stop, but correctly stopped near
+3.375 V (about 1.01 kHz). Sixteen independent windows filled across a 22.66c
raw span, while quarter-block means differed by 8.62c and the two half means by
4.53c. The detector itself ranged from 1006.24 to 1023.09 Hz. This is temporal
motion consistent with the module's dual-unison architecture or residual OSC2
content, not stationary period quantization. The safety bound remains unchanged;
this signature is now reported as `FAILED - UNSTABLE PITCH` instead of a generic
timeout.

The published Peach firmware supports that interpretation. Its DAC sample is
always the sum of OSC1 and OSC2; the OSC2 term is multiplied by an integer level
mapped directly from the OSC2-level ADC. Likewise, OSC2 detune is derived
directly from a second ADC. A physical control resting at its minimum therefore
silences or exactly unisons OSC2 only if the corresponding ADC actually reaches
zero. Even a small nonzero endpoint leaves a weak, slightly detuned second
oscillator in the supposedly single-sine output and can produce the measured
slow pitch motion.

Two subsequent full physical repeats retained 59 anchors over a detected
0.000--4.833 V usable interval and measured conventional responses of 988 and
989 mV/octave. Both completed all 47 targeted replay checks, but neither met the
two-cent acceptance target: sampled worst errors were +4.77c and +4.83c, with
maximum within-target spans of 23.39c and 23.62c. The nine-point local checks
were individually much more repeatable, showing that no single static curve can
remove the longer-timescale motion. Peach is therefore a useful bounded
time-varying/multi-oscillator rejection case, but its summed output is not
qualified as a precision calibration source in this configuration. The
candidate profiles were disposable and were not saved.

A later AUTO repeat exercised the graded-policy path. Characterization found
only four unstable survey positions, then the first targeted replay isolated
and removed a non-repeatable upper edge. The recovered candidate retained 44
points from 0.000 through +3.583 V and measured 989 mV/octave. All 48 targeted
checks and all nine local checks completed. Its best verified curve was
`CHARACTER`: 7.35 cents worst sampled error and 5.85 cents stability, with
low/high local means of +0.13/+0.22 cents and repeat ranges of 0.26/0.15 cents.
The target-local mean remained -7.17 cents. A tentative refinement improved
its paired local comparison from -1.63 to -1.29 cents, but the full recheck
encountered a non-repeatable high-region excursion and correctly rolled back
to the verified Character curve. This confirms that graded calibration can
retain a useful bounded Peach profile without claiming precision performance.

### dps.coffee 22 deaf chinchillas: sub-audio verification boundary

The complete -5..+8 V survey retained 121 anchors after eleven missing
low-edge observations and reported no unstable, flat, or discontinuous survey
points. Its first targeted replay point was nevertheless only about 2.27 Hz.
The detector continued to report a valid and qualified pitch, but only eleven
fresh periods arrived during the bounded check; seven independent averages
filled, one short of the required eight. Two semitone-at-a-time edge retries
could not reasonably reach the audio band and the disposable candidate was
safely rejected.

This is not an oscillator-tracking or detector failure. Automatic release
verification now intersects the measured profile with the product's stated
20 Hz--20 kHz operating range. Characterization may retain descriptive points
outside that interval, but sub-audio or ultrasonic endpoints no longer consume
bounded verification time or prevent certification of the useful audio-range
curve. The exact A4=440 boundaries are fixed at 1,548,682 and 13,507,623
millicents; 184 host tests cover the clipped, sorted targeted plan.

The physical rerun with that change retained 121 anchors after twelve missing
low-edge observations. Verification began near the interpolated 20 Hz boundary
instead of the measured 2.27 Hz endpoint and completed all 38 audio-range
targets without edge recovery. The sampled worst error was -3.79c and maximum
span was 3.49c. Local low/high/target means were -1.52c/-2.16c/-1.28c, but
between-repeat ranges of 1.94c/1.31c/1.28c correctly prevented a static curve
refinement. The response measured 979 mV/octave and was conventional. At the
tested panel tuning, +8 V reached only about E9 (roughly 10--11 kHz), so the UI
correctly recommended higher oscillator tuning before a full 20 kHz coverage
claim. Acquisition and sampled check took 194056 ms and 47783 ms.

After raising the oscillator's base tuning by approximately one octave, a
second full-range run retained all 121 anchors except one low-edge observation
and again reported no unstable, flat, or discontinuous survey points. The
stored descriptive curve extended from roughly D-3 at -4.917 V through E10 at
+8 V, so it covered the complete 20 Hz--20 kHz verification interval. All 39
targeted checks completed. Sampled worst error was +3.12c at C4 +33.3c and the
largest within-target span was 4.76c. Local low/high/target means were
+0.81c/+1.23c/+0.48c; repeat ranges of 3.46c/0.96c/1.30c correctly prevented
a non-repeatable static refinement. The measured response was 978 mV/octave
and conventional. Acquisition and sampled check took 176707 ms and 49915 ms.

This higher setting proves full product-band coverage, while the first setting
shows that the same oscillator can still produce a useful partial-band profile.
Both runs remain just outside the strict two-cent sampled release target, so 22
deaf chinchillas is presently a stable, well-behaved calibration source but not
yet a sub-two-cent qualification pass for this detector and averaging policy.

A later AUTO run validated the graded-policy behavior at the higher tuning.
Characterization retained 117 measured anchors after 40 expected sub-audio
misses. Targeted replay isolated a non-repeatable low edge and recovered a
98-point candidate spanning -0.333 through +7.750 V (B1 through D#10), with a
conventional 979 mV/octave response. All 48 sampled targets and nine local
checks completed. Accuracy was Musical-class at 3.20 cents worst, but the
7.79-cent maximum stability span made the combined result `CHARACTER`. Local
repeat ranges were 2.05/1.97/2.64 cents at low/high/target checks. The profile
was therefore correctly offered as a usable graded result rather than either a
precision claim or a failed calibration. This physical run also confirmed that
the review UI no longer retains a misleading transient failure label after
automatic recovery leaves an acceptable curve.

### Dove Audio WTF: current wavetable setting is not static enough

The first WTF run completed the full -5..+8 V characterization pass, but only
78 of the 157 surveyed positions survived into the candidate curve. It recorded
22 unstable positions, with instability concentrated below roughly -2.7 V and
again above roughly +7.1 V; there were no missing, flat, or discontinuous
positions. The retained middle interval was coherent enough to complete 47
targeted replay positions up to the final high check.

At approximately +6.833 V and 7.6 kHz, however, the last target ranged from
7572.39 to 7703.86 Hz. Eleven independent averages had errors spanning about
23 cents, so the automatic verifier timed out, zeroed the output, and preserved
the prior profile. This is a useful correct rejection rather than a silent-input
failure. A second run using the simplest available fixed waveform, with window
position and modulation held static, is needed to distinguish an inherent WTF
tracking limit from the selected wavetable/window configuration.

The fixed-waveform repeat on the NSDF-only build reproduced the same boundary
as the immediately preceding permanent-NSDF run. Both retained 101 anchors
and failed automatic replay as `FAILED - UNSTABLE PITCH` at corrected outputs
of +4.1455 V and +4.1445 V respectively. Their failed targets differed by
only 0.475 cents. The first survey reported 41 missing and 11 unstable
positions; the repeat reported 41 missing and 13 unstable positions, with no
flat or discontinuous observations in either run. Acquisition/check times
were 282651/71688 ms and 296947/74095 ms. Zero checks were +0.47c and -0.84c.
This close physical repeat after deleting the legacy detector rules out a
silent fallback to that detector as the cause. It establishes a repeatable
WTF operating boundary for this panel/wavetable setting; it does not by itself
separate oscillator motion from NSDF estimator sensitivity.

The first physical run with graded calibration policy retained 102 survey
anchors after 41 missing and 13 unstable observations. AUTO used independent
replay failures to bound both ends of the repeatable region, then restarted a
fresh targeted verification after each boundary change. The final candidate
contained 44 points from +0.58325 V through +4.16675 V, spanning about 3.58
octaves. All 48 verification targets and all nine local checks completed.
Sampled worst error was 3.02 cents and stability was 6.32 cents, producing an
acceptable `CHARACTER` grade rather than either a precision claim or a total
rejection. The low/high/target local means were -0.98c/+0.79c/-2.12c, with
repeat ranges of 0.98c/0.18c/1.58c. The response measured 984 mV/octave and
was conventional. Acquisition and verification took 289304 ms and 261781 ms.

This run demonstrates the intended distinction between calibration quality
and oscillator usability: a complex oscillator may yield a useful, explicitly
graded middle range even when its full electrical sweep is not repeatable. The
saved-slot state remains unchanged until the user explicitly accepts and saves
the disposable result.

### Dove Audio Waveplane: repeatability exceeds the Character ceiling

Two AUTO runs found a broad measurable interval but could not isolate a
repeatable static subrange. The first retained 83 survey anchors after 63
missing and one unstable observation. Successive replay recovery reduced the
candidate from approximately +0.25..+7.75 V to +2.50..+5.33 V, then failed
near +3.2085 V (about 183 Hz) with an 11.90-cent raw span. The second retained
76 anchors and used all four bounded partial-region recoveries, successively
narrowing 76 -> 47 -> 42 -> 35 -> 29 anchors. It still failed near +4.53075 V:
the sixteen independent errors covered 8.68 cents, with quarter/half drift of
4.86/3.86 cents. This is distributed temporal motion rather than one defective
electrical boundary.

FORGIVING was then adjusted to permit up to five cents of half-window drift
during target acquisition while preserving the ten-cent Character-grade final
ceiling. The first physical run acquired 94 anchors and ultimately retained 62,
but the completed candidate was rejected by the final accuracy/stability gate;
its zero check was +0.35 cents. A clean repeat acquired and retained 93 anchors,
reported 63 missing positions and one flat observation, completed all 47 main
verification targets plus local checks, and was again rejected by the same
quality gate. Its zero check was +1.02 cents. The coherent 93/93 point count
rules out missing output or an accidental range collapse: the measured curve
was usable throughout replay, but its final error or repeatability exceeded the
ten-cent Character safety ceiling.

The exact final metric was lost because the expanded graded/local diagnostic
exceeded the original 1536-byte serial packet. The packet is now 2048 bytes and
has a compact status/grade fallback, so a future run can report the precise
excess without risking another blank diagnostic. No further physical Waveplane
run is required merely to establish the present conclusion: under this patch
and panel setting it is measurably responsive but not safely representable by a
static Character-grade correction curve.
