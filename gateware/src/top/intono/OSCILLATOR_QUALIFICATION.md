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

### WORNG ACRONYM: intermittent high-CV period change

With a Disting EX holding approximately +5 V on ACRONYM's V/oct input and its
sine output sent to IN0, two R5 Tiliquas independently reported frequent
~3030.7 Hz readings interspersed with ~3007–3017 Hz readings. A prior fixed
~+4.5 V test was much steadier. The second Tiliqua used its own ADC and the
same INTONO NSDF estimator, so the agreement alone did not distinguish a
source-side change from a shared estimator artifact.

A temporary `TILIQUA_INTONO_NSDF_TRACE=continuous-wave` firmware mode was then
flashed **only to Tiliqua #2**. It computes a rising-zero-crossing frequency
from the same immutable 674-sample native frame as each high-bank NSDF result;
it never changes the published pitch, CV outputs, or CAL decisions. In 97
paired frames, 88 were in the high-frequency cluster and nine below 3020 Hz.
The independent zero-crossing estimate followed every low event. The median
absolute difference was 0.109 Hz in the high cluster and 0.771 Hz in the low
cluster. For example, the paired readings included 3007.137/3007.485 Hz and
3031.097/3030.821 Hz (zero crossing/NSDF). Thus the intermittent apparent
period change is present in the captured audio itself, before the NSDF peak
selection or refinement. This does **not** yet establish whether ACRONYM's
oscillator, its +5 V CV source, or some aspect of their interaction is moving.
The next controlled test is to change only the fixed CV source, keeping the
ACRONYM settings and audio patch constant.

Replacing Disting EX #1's nominal +5 V with Disting EX #2's nominal +5 V did
not remove the period split. The center moved to about 3.10–3.13 kHz, as
expected from two differently calibrated voltage sources, but in an 86-frame
follow-up the lower cluster had 49 frames (median NSDF 3103.046 Hz) and the
upper 37 (median NSDF 3127.763 Hz). The paired zero-crossing medians were
3103.182 and 3127.735 Hz. Thus this is not peculiar to Disting #1's output.
Because both Disting units share a design and ACRONYM's sine is shaped from its
triangle core, the next least-disruptive isolation is to compare ACRONYM's
triangle output with the same CV and panel settings. If that remains split,
remove the V/oct cable and retune the oscillator near the same frequency to
separate CV-path behavior from the free-running core.

The triangle-core output produced the same two clusters with Disting #2 still
feeding +5 V: 98 paired frames split into 57 lower (median NSDF 3103.062 Hz,
zero crossing 3103.327 Hz) and 41 upper (3127.832/3127.845 Hz). The overall
median absolute NSDF/zero-crossing difference was 0.264 Hz. The sine
waveshaper is therefore not needed for this intermittent apparent period
change. The remaining controlled comparison is free-running triangle at a
similar pitch with V/oct unplugged.

With V/oct unplugged, the user brought the free-running triangle to roughly
3 kHz with coarse tuning at maximum. Of 97 paired frames, the NSDF median was
3007.619 Hz; the central 80% were tightly grouped from approximately 3007.5
to 3007.7 Hz, but intermittent readings reached 3025.867 Hz. The independent
zero-crossing estimator ranged from 3005.990 to 3025.324 Hz and followed the
higher events. Thus neither Disting CV source nor a connected V/oct cable is
required for an intermittent apparent period change. Because the coarse
control was at its end stop in this particular free-running test, the result
does not yet establish how the core behaves at a midrange tuning position or
exclude other oscillator modulation/sync connections and audio-path effects.

With V/oct still unplugged, the user backed the coarse control away from its
maximum and tuned the free-running triangle to roughly 2 kHz. All 97 paired
high-bank frames produced both estimates. NSDF ranged from 1994.526 to
2005.153 Hz; the zero-crossing estimate ranged from 1994.404 to 2005.368 Hz,
with a median absolute difference of 0.075 Hz. The lower and upper apparent
periods therefore persist at a lower pitch and away from the coarse end stop.
This rules out those two conditions as necessary causes, but the shared audio
capture path still needs a known-stable oscillator control at a comparable
frequency before attributing the variation to ACRONYM itself.

As an analog control at approximately the same pitch, the user replaced only
the IN0 audio patch with Pittsburgh Modular Local Parks' triangle at roughly
2 kHz. Over 103 paired frames the zero-crossing readings ranged from
2004.134 to 2007.618 Hz, and NSDF ranged from 2004.105 to 2007.602 Hz; their
median absolute difference was 0.071 Hz. This is a narrower, wandering
approximately 3.5 Hz span, rather than ACRONYM's two approximately 10 Hz
clusters at the lower-pitch free-running setting. The common capture path
therefore does not impose an identical split on every analog oscillator, but
this control is not a fixed-frequency reference. A stable digital oscillator
through the same cable/input would better isolate residual acquisition jitter.

Twin Waves' unmodulated digital sine was then patched to the same Tiliqua #2
IN0 input near 2 kHz. Over 103 paired frames, zero crossing ranged from
1998.686 to 2002.839 Hz, and NSDF ranged from 1998.553 to 2002.809 Hz;
their median absolute difference was 0.061 Hz. The approximately 4.2 Hz
apparent spread is comparable to Local Parks' wandering control, although
neither had ACRONYM's sharp, repeatable two-cluster separation. This shifts
attention to the shared acquisition/timebase or signal connection for the
smaller variation. A simultaneous second oscillator on another input can
test whether fractional pitch movement is correlated across channels.

With Twin Waves sine near 2 kHz on IN0 and Local Parks triangle near 2 kHz on
IN2, an 82-second simultaneous run collected 201 and 202 qualified high-bank
NSDF readings, respectively, with no acquisition faults. IN0 ranged from
1998.912 to 2005.126 Hz (standard deviation 1.059 Hz); IN2 ranged from
1998.670 to 2003.389 Hz (standard deviation 0.974 Hz). Nearest-time pairs
had a weak Pearson correlation of 0.087, with adjacent-pair shifts also weak
(approximately 0.02–0.16). The serial report schedule puts the channels about
202 ms apart, so this argues against a **slow** shared timebase drift but
cannot rule out faster common jitter. Feeding the *same* oscillator signal to
both channels through a buffered mult is the next direct separation of source
motion from channel-specific measurement noise.

The user then buffered-multed the **same** Twin Waves sine to IN0 and IN2.
Ordinary serialized reports, about 201 ms apart, remained uncorrelated, so a
temporary `continuous-pair` firmware diagnostic was flashed only to Tiliqua
#2. It services just the two native-rate inputs back-to-back and reports both
NSDF and independent zero-crossing estimates; it does not change the
production scheduler or calibration logic. In 1,245 fully qualified pairs,
the frame endpoints were a median 1,916 native samples (about 10 ms) apart.
Each channel's NSDF frequency had roughly 1.0 Hz standard deviation around
2001.05 Hz, but the cross-channel Pearson correlation was only 0.069 (zero
crossing: 0.062), including low correlations at adjacent-pair offsets. There
was negligible median channel bias (-0.017 Hz) but 1.396 Hz standard deviation
of their difference. Each channel's NSDF and zero-crossing estimates agreed
within a median 0.08 Hz. Thus a material part of the short-frame apparent
pitch spread is channel/frame-specific measurement variation rather than
actual Twin Waves pitch motion or slow common clock drift. It is not yet a
complete explanation for ACRONYM's much larger, distinct period clusters; the
same buffered two-input test with ACRONYM will distinguish those.

After the user replaced the mult's source with ACRONYM's free-running triangle
near 2 kHz, 1,530 fully qualified back-to-back pairs showed **no** two-cluster
separation. IN0 NSDF ranged from 2004.580 to 2004.995 Hz; IN2 ranged from
2004.557 to 2005.082 Hz. The channel-difference standard deviation was only
0.079 Hz with virtually no median bias. The independent zero-crossing values
had wider tails (roughly 2004.0–2005.6 Hz), but their medians matched NSDF and
their correlation across inputs was 0.475. These measurements demonstrate that
this ACRONYM output can be stable and precisely trackable under the buffered
patch. The earlier direct-input split is not reproducible under the current
connection; changing only the mult/direct audio path while leaving tuning and
V/oct disconnected is the next isolation test. The diagnostic build changes
the NSDF request schedule as well as the patch, so any attribution must also
consider that changed timing.

The user then bypassed the mult, sending ACRONYM triangle directly to Tiliqua
#2 IN0 while keeping V/oct unplugged and the panel controls unchanged. Under
the paired diagnostic schedule, 1,687/1,687 IN0 frames qualified and NSDF
ranged only from 2004.822 to 2005.220 Hz (standard deviation 0.060 Hz); IN2,
now disconnected, had zero qualified frames. Restoring the original all-bank
schedule without changing this direct patch likewise produced 103 qualified
frames, NSDF 2005.022–2005.368 Hz (standard deviation 0.063 Hz). Therefore
neither the buffered mult nor the paired-only request schedule is necessary
for this stable state. The earlier approximately 10 Hz split has not been
reproduced after repatching; an unrecorded physical state, connection, or
transient remains possible. Do not call the disappearance a firmware fix.

With Tiliqua #2 OUT0 patched to ACRONYM V/oct and its triangle directly into
IN0, a subsequent full CAL run acquired 101 points. The first automatic replay
failed at approximately +0.162 V, then the partial-range recovery retained
the larger contiguous side (-5.000 through +0.083 V, 62 points). That
limited curve independently rechecked 45/45 targets and 9/9 local checks,
earning a CHARACTER grade (worst 5.15 cents, maximum observed span 9.53
cents). The user explicitly does **not** need to save this test profile.

Crucially, the failure at +0.162 V was `INCOMPLETE REPLAY`, not absent audio:
the serial diagnostic counted 105 detector frames, 98 valid/qualified, 22
fresh settled target-adjacent readings, and 13 of the required 16 independent
averaging windows within the five-second check deadline. The raw error span
was 5.898 cents with no span/gap resets. The temporary all-bank waveform
trace printed on every detector update during this run and may have worsened
the acquisition budget. A bounded extension now gives an otherwise stable,
target-adjacent, incomplete replay up to three additional seconds **at the
same CV**, preserving the already collected windows. It does not relax the
16-window acceptance or stability limits. The previous partial result must
not be represented as proof that ACRONYM tracks only five octaves.

On the first retest, verification advanced well past +0.162 V before trimming
from the high end. It eventually rejected a 70-point -5.00..+0.75 V preview
after four partial recoveries. At +1.174 V, all 16 independent windows were
present, but their raw error span was 20.174 cents and quarter-block means
differed by 14.968 cents; this is a different repeatability failure, not a
mere window shortage. However, investigation of the supposed "quiet" build
found that omitting `TILIQUA_INTONO_NSDF_TRACE` still defaulted to
`continuous`, which emits `NSDF RUN/PICK/COMP` for every channel. Therefore
that retest was **not** free of telemetry overhead. A distinct
`continuous-quiet` mode now retains the same production eight-slot NSDF
scheduler while suppressing per-frame serial reports; it is the new build
default. The next hardware comparison must run that actual quiet mode before
attributing the high-end variability to the oscillator or CV output.

The subsequent `continuous-quiet` retest completed acquisition with 101
contiguous points from -5 V to roughly +3.4 V. Its automatic verifier made
four high-side cuts, then rejected an 87-point -5.000..+2.167 V preview
after 227.5 seconds acquiring and 463.7 seconds checking. The final 47/47
targeted replay and 9/9 local check isolated a **repeatable interior error**:
the +2.000 and +2.08325 V anchors replayed at +0.25 and +0.21 cents, with
under 0.2-cent within-window spans, while the +2.04175 V midpoint replayed
at +17.69 cents on average across three interleaved visits (0.06-cent
between-visit spread). The 17.74-cent overall error is thus not well explained
by a lost signal or unstable read at that location. The cause of the response
nonlinearity remains unproven; it could be in the oscillator or CV path.

The automatic workflow previously classified every midpoint error above
10 cents as drift and trimmed the whole high-side range *before* considering
local refinement. A bounded policy fix now allows a repeatable, isolated
midpoint error up to 25 cents to enter the existing paired-candidate
refinement path. The candidate still must improve the original point without
regressing neighboring intervals and must pass a complete independent replay
before the user can accept it. Larger or unstable errors retain range-recovery
or rejection behavior. This fix is built but requires a hardware retest;
neither its efficacy nor a usable full-range ACRONYM profile is established.

In the first hardware run of that policy, acquisition again found 101 points.
Completed replay first isolated unsafe locations near +3.125 and +3.083 V,
then an **incomplete** replay at +1.711 V caused a larger trim to 81 points.
Thus this run never reached the previous +2.042 V hotspot. On the shorter
curve, the verifier did enter local refinement. One inserted point passed the
paired comparison and independent 46-target replay improved worst error from
13.70 to 12.47 cents. A second refinement attempt stopped; the final
82-point preview was correctly rejected (UNSAFE, 12.466-cent worst error,
10.542-cent stability). The large detailed serial report overflowed its
2 KiB buffer and fell back to a terse summary, obscuring the last local
failure. The fallback has now been extended to include worst pitch, local
three-point repeatability, and last refine/recheck results. This is a
diagnostic-only change has been built and flashed to Tiliqua #2 slot 1; it
does not alter acceptance. A new hardware run is needed to capture that
compact failure evidence.

A second ACRONYM triangle run again found high-side unsafe replay near
+3.208 and +3.083 V. A later `INCOMPLETE REPLAY` at +1.466 V was not a loss
of detector lock: 166/166 frames qualified, with 16 averaging windows and
37 settled target-near readings. Instead, those readings spanned 24.660
cents and their quarter-block means differed by 12.292 cents, so the
stability gate correctly withheld a result. The "incomplete" label is
misleading for this case; the data were abundant but too variable. This is
a distinct failure from the repeatable local interpolation errors and must
not be fixed by relaxing accuracy or acceptance thresholds.

After shortening to a candidate ending below that location, an independent
46/46 replay found another very repeatable midpoint error at +1.29175 V:
+10.20 cents at the midpoint, +0.14/+0.17 cents at its neighboring points,
and only 0.04-cent between-visit variation at the midpoint. The full local
correction overshot from +10.23 to -11.52 cents in the paired trial and was
properly rejected. The resulting 78-point profile was UNSAFE (10.239-cent
worst error, 17.346-cent stability), and nothing was accepted or saved.

One bounded half-step backtracking trial is now permitted when a full
correction *repeatedly overshoots the original target in the opposite
direction*. That trial reruns the same paired target/neighbor checks; a
passing trial still needs the existing full independent recheck before a
profile can be accepted. No new quality allowance is introduced. Host tests
cover the observed +10/-11.5-cent overshoot and a successful half-step, but
hardware behavior remains to be tested.

For the next isolation check, idle serial status now includes the selected
input's numeric tuner frequency, qualification, level, sequence and age.
This allows a fixed external CV source to hold ACRONYM near the troublesome
5.5 kHz region while comparing pitch stability, without waiting for another
full calibration sweep. Serial recovery text also distinguishes an explicitly
unstable replay from a check that merely lacked enough measurements.

With Tiliqua OUT0 disconnected from ACRONYM V/oct and a fixed external
approximately +1.5 V source substituted, the ACRONYM triangle remained on
Tiliqua #2 IN0. A clean 60-second idle-tuner sample returned 11/11 valid,
qualified readings: median 5506.682 Hz, 5506.530–5506.877 Hz, only 0.109
cents total spread and 0.036 cents standard deviation. The previous unstable
calibration replay near this frequency spanned 24.660 cents across 16
measurement windows. Therefore the ACRONYM plus Tiliqua pitch detector is
capable of stable measurement at this pitch under a fixed external CV.
This does **not** yet identify whether Tiliqua's output is unstable when held,
or whether the oscillator/control path needs more settling after a sweep
step. A fixed Tiliqua-output route is the next discriminating comparison.

That comparison used a steady Disting CV into Tiliqua #2 IN2, ROUTES OUT0
configured to source IN2 with chromatic quantization and no oscillator
correction, and OUT0 patched to ACRONYM V/oct. IN2 read approximately +1.451 V.
During 65 seconds with ACRONYM triangle on IN0, all 18 idle-tuner reports
were valid and qualified: median 5356.715 Hz, range 5356.556–5356.851 Hz,
0.095-cent total spread and 0.029-cent standard deviation. This demonstrates
that Tiliqua OUT0 can hold a steady pitch in this static route, comparable
to the direct external-CV test. It does not establish its behavior immediately
after each calibration step. The remaining likely distinction is the step,
settling, or measurement sequence; the oscillator itself and the CV output
cannot yet be singled out as the cause of the transient replay variation.

The next ACRONYM triangle run used the same patch and AUTO policy on Tiliqua
#2. Acquisition found 101 points before the oscillator stopped supplying
usable higher-range points, then finished its -5..+8 V characterization.
Automatic replay independently completed each progressively shortened check,
but found unsafe results around +3.208, +3.083, +2.958, and +2.431 V. At its
four-recovery checkpoint the remaining 90-point preview covered -5.000 to
+2.417 V and still graded UNSAFE: 48/48 targets checked, worst +19.445 cents
at D9 -35.3c, maximum within-target spread 15.158 cents. It was correctly
blocked from acceptance and saving. The run spent 225.9 seconds acquiring and
469.7 seconds checking, a conspicuously long and unsuccessful experience.

This run did not trigger the new per-window *unstable timeout* capture: its
checks completed, but the completed checks were inaccurate or variable enough
to fail the grade. The rejected-review serial report exposed only aggregate
quality because `Automatic::best` was empty, even though the final `Scan` and
its nine local repeat checks remained in RAM. The report now includes those
rejected-candidate local measurements, including the serial fallback path.
Host regression covers this reporting; it requires a new hardware run to
reveal whether the limiting +2.43 V area is a repeatable response kink,
within-target drift, or both. No accuracy/stability acceptance limits have
been relaxed, and no ACRONYM profile was accepted or saved.

The next run moved the identical ACRONYM triangle patch to Tiliqua #1
(OUT0 to V/oct, triangle to IN0). Acquisition again found 101 points and
completed the -5..+8 V characterization. Four independent replay recoveries
trimmed the high side around +3.125, +3.083, +2.958, and +2.430 V. The
remaining 90-point candidate covered about -5 to +2.417 V; its 46/46
targeted replay and 9/9 interleaved local check completed, but it was
correctly rejected. The local check's critical midpoint was +2.2085 V:
its three visit means spanned 40.76 cents although each visit's own
within-window span was at most 0.14 cents. Its neighboring +2.16675 and
+2.250 V points were almost exactly on target and repeated within 0.02
cents each. This independently reproduces a sharply localized,
between-visit change on both Tiliquas; it does not yet establish whether
the cause is the oscillator's CV response, a direction/settling effect,
or pitch-estimator behavior. The report now records the nine local readings
in visit order, so a future run can distinguish those possibilities without
inferring direction from aggregates. No profile was accepted or saved.

With that visit-order diagnostic on Tiliqua #1, another unchanged ACRONYM
triangle run again acquired 101 points and recovered its high-side range to
a 93-point candidate. Its last 47-target replay completed, but the grid's
worst target (12,422,050 millicents) measured +29.34 cents. The local check
then commanded the *same profile pitch and voltage* (+2.4325 V) three more
times, yielding -18.11, -18.11, and -18.13 cents. The two surrounding
anchors (+2.41675 and +2.500 V) stayed near -0.03 cents and repeated within
0.03 cents. Thus the grid and local phases disagreed by about 47.46 cents
at the same target, despite the three close-step local visits being steady.
It is unsafe to interpret this as a fixed, correctable curve kink; the
measurement depends on the preceding scan/step history or some other
unobserved state. The automatic run correctly stopped at `REVIEW - MORE
RANGE SEARCH?`, zeroed the output, and did not accept or save the profile.

Calibration quality now includes the grid-to-local discrepancy as a stability
term, and completion requires it to fit the policy's stability limit. The
serial report names that discrepancy explicitly, and host regression covers
the observed 47-cent contradiction. The cause remains unproven: possible
settling/approach behavior in the oscillator or CV path, or a measurement
state effect. Do not relax accuracy limits or insert a refinement point on
the basis of these conflicting readings.

The subsequent UI change reports `REVIEW - CHECKS DISAGREE` at a bounded
range-search checkpoint when the grid/local discrepancy exceeds 10 cents,
while keeping the rejected preview and the user's explicit option to search
a smaller range. This message does not authorize acceptance or overwrite a
stored profile. It is tested on the host but has not yet been flashed or
verified on hardware.

The next hardware check should avoid another full calibration until the
contradiction is isolated. With the ACRONYM triangle still patched to IN0,
hold its V/oct input at one fixed external CV near the problematic +2.43 V
region and observe the tuner/serial frequency for at least several seconds.
Then approach that same voltage once from below and once from above, without
retuning or changing the waveform. Compare steady readings and the first
second after each change. This separates a static high-frequency detector
problem from a direction/settling effect. An external source's actual
voltage need not equal its nominal setting for this *repeatability* test;
record the source and setting. Do not save a calibration profile on the
basis of this diagnostic alone. A separate short controlled CV-step replay
can follow if static readings are stable.

At fixed Disting EX CV near nominal +2.5 V, ACRONYM triangle stayed qualified
around 10.77–10.80 kHz. The slow drift was under a few cents over several
minutes, not a 47-cent jump. Controlled +2.0→+2.5 and +3.0→+2.5 V returns
showed immediate agreement between the NSDF pitch and an independent
rising-zero-crossing estimate computed on the same immutable audio frame
(paired reports approximately every 400 ms). The return frames were already
at the steady +2.5 V cluster, with no observed large transient. This does
not exclude a sub-frame event or behavior peculiar to Tiliqua's DAC steps,
but it argues against a general high-frequency NSDF or ACRONYM instability.

For the next isolation, the temporary `continuous-wave` firmware adds an
idle-tuner-only serial CV probe on OUT0. It is opt-in: ASCII `d`, `a`, `b`,
`c`, `e` command +2.00000, +2.41675, +2.43250, +2.50000, +3.00000 V;
`x` stops it. Each enabled command expires and zeros the output after 30
seconds, and leaving the idle tuner stops it. The probe uses the calibration
output hardware path but does not create or modify a profile. It must not be
left in the eventual release build; it is compiled only for the paired-wave
diagnostic mode. The build succeeded and was flashed to Tiliqua #1 slot 1
with option storage preserved. Hardware command reception is confirmed below.

The idle-tuner serial probe was hardware-checked on Tiliqua #1 with OUT0 to
ACRONYM V/oct and its triangle output to IN0. ASCII `c` moved the measured
pitch from about 1997.6 Hz at idle zero to 11129.3 Hz, and `x` restored the
idle pitch and zeroed the output. The two independent estimators agreed.
The subsequent 5-second-per-step sequence exposed a direction-dependent
result at the *same* commanded count value: `a` (9667 counts) held about
10528.7 Hz; `b` (9730 counts) approached from `a` remained at about
10528.7 Hz; `c` (10000 counts) held about 11130.5 Hz; `b` approached from
`c` held about 10821.3 Hz; returning to `a` restored about 10528.7 Hz;
and a second `a`→`b` again remained near 10528.7 Hz. NSDF and independent
zero-crossing estimates agreed on every step, and the readings were stable
through the whole dwell. The two observed `b` states differ by roughly
47.4 cents, closely matching the original grid/local contradiction. The
probe was explicitly stopped and its output zeroed. The cause is not yet
localized: a missed/incorrect CV command, analog output behavior, or an
ACRONYM CV-response memory effect remain possible. Measure the physical
OUT0 voltage during both approaches before changing calibration policy.

With OUT0 buffered/multed to an external voltage monitor and ACRONYM, a
second 12-second-per-step `a`→`b`→`c`→`b` replay was filmed. The monitor's
top-left reading was approximately 2.445–2.446 V at `a`, 2.459–2.461 V at
the first `b`, 2.529–2.530 V at `c`, and 2.457–2.460 V at the second `b`.
Thus the small `a`→`b` commanded CV increment did appear at the monitored
branch, and the two visits to `b` measured nearly the same voltage. Absolute
monitor offsets (~+0.03 V) are not used as evidence because its calibration
and the mult's loading have not been established. In this patched test the
audio stayed at ~10.837 kHz at `a` and both `b` visits, while `c` produced
~11.475 kHz. The monitor and pitch observations rule out a completely
missing small step *at the monitored node*, but do not yet prove the same
voltage reached ACRONYM's V/oct jack; the exact mult topology is being
confirmed. Also, the earlier direction-dependent `b` pitch was not
reproduced after changing the patch/load. Do not average the two historical
pitch readings into a correction point. The user confirmed the topology is
Tiliqua OUT0 → buffered mult → separate outputs to the Disting voltage
monitor and ACRONYM V/oct. Therefore the Disting reading does not directly
measure the particular mult output feeding ACRONYM. Swapping those two mult
outputs is the next non-destructive isolation test.

After swapping the two cables at the buffered mult's outputs, a second
video of the previously unmonitored output showed about 2.444 V at `a`,
2.460 V at the first `b`, 2.529 V at `c`, and 2.460 V at the second `b`.
The simultaneous tuner telemetry was ~10.861 kHz at `a` and both `b`
visits, and ~11.499 kHz at `c`. Both buffered outputs therefore show the
small CV increment, but neither routing makes ACRONYM's measured pitch
respond to that increment. This makes a fault isolated to one buffered
output unlikely. It still does not prove the voltage exactly at ACRONYM's
jack, nor explain why an earlier direct-patch run had distinct `b` pitch
states. A temporary firmware probe now offers additional 10-mV-spaced
commands between `b` and `c` to locate the response threshold; the
firmware-only build was flashed with option storage preserved, pending a
local sweep after boot.

The first fine local sweep used 3-second dwell steps from +2.41675 through
+2.50000 V and back. The reported pitch looked staircase-like: about
10.676–10.679 kHz across +2.4325–2.45 V, a jump to ~10.986 kHz at
+2.46 V, then ~10.989 kHz at +2.49 V and a jump to ~11.314 kHz at
+2.50 V; descending transitions occurred at different commands. The
first +2.41675 V command appeared not to reach the oscillator at all.
Consequently this run is **not** sufficient evidence of oscillator CV
quantization or hysteresis: commands may have been missed, and only the
earlier `a`/`b`/`c` commands were independently voltage-monitored. The
temporary probe was extended to transmit a one-byte, high-bit serial ACK
only after the hardware calibration-output token becomes active. Firmware
with this ACK was built and flashed; the local sweep must be repeated after
the user boots INTONO and the host must require matching ACKs before
assigning a pitch reading to a command.

The ACK-gated repeat on Tiliqua #1 completed with **every command
acknowledged on its first transmission**. Four steady NSDF WAVE frames per
step gave about 10.8234 kHz from `a` (+2.41675 V) through `q` (+2.45 V),
11.1325 kHz from `r` (+2.46 V) through `u` (+2.49 V), and 11.4602 kHz at
`c` (+2.50 V). Descending from `c`, `u` initially remained at 11.4603 kHz,
`t` through `r` returned to about 11.1326 kHz, and `q` through `a` to about
10.8235 kHz. The first upward transition is about 48.8 cents, and the
second about 50.2 cents, much larger than the 12-cent ideal change
over 10 mV at 1 V/oct. This repeat removes *missed software commands* as
an explanation of the staircase: the DAC-side output controller accepted
each step. It still does **not** prove that physical voltage at ACRONYM's
V/oct jack moved smoothly on the intermediate 10-mV commands. The earlier
buffered-monitor videos show correct-sized increments at `a`, `b`, `c` on
both mult outputs, but did not capture `q` through `u`. An independently
monitored fine sweep is the next discriminating test. The serial probe sent
`x` and returned OUT0 to zero after the run. Do not accept a calibration
profile based on this staircase.

A second ACK-gated fine sweep was run while the user recorded the external
Disting monitor. Each command dwelled for six seconds; all 13 steps were
acknowledged. Pitch stayed near 10.839 kHz at `b`/`q`, jumped to about
11.149 kHz at `r` and stayed there through `u`, then jumped to about
11.477 kHz at `c`. On the descent, `u` initially held the high value,
`t` through `r` returned to about 11.149 kHz, and `q`/`b` returned to
about 10.839 kHz. `x` restored the idle pitch to about 2.001 kHz. The
user's voltage-monitor video is needed before deciding whether physical
CV also forms a staircase; these pitch readings alone do not distinguish
the output analog path from ACRONYM's V/oct response.

The user requested a repeat because the camera missed that replay. The
identical 13-step, six-second-per-command sequence was rerun, with every
command again acknowledged. On the ascent the levels were approximately
10.841 kHz (`b`, `q`), 11.150 kHz (`r` through `u`), and 11.478 kHz
(`c`). Descending `u` remained high; `t` through `q` remained at the middle
plateau; only `b` returned to the low plateau. In particular, descending
`q` differed from the previous run, consistent with a threshold close to
that commanded voltage and possible state/approach dependence. `x` restored
the idle pitch to about 2.001 kHz. Await the new external voltage video
before attributing this to the oscillator or Tiliqua analog CV path.

The second recording (`ED9738CD-5927-4041-B489-00978746D0AE.MP4`)
shows the Disting's top-left voltage monitor while this replay ran. Its
readout traverses many distinct intermediate values, rising in roughly
10-mV increments from the mid-2.4-V region to about 2.528 V and then
descending again. In contrast, the simultaneously logged audio pitch has
only three plateaus. The video's start is not frame-synchronized to the
serial command timestamps, and the monitor has its own update/settling
time; use the **continuous sequence of intermediate voltages**, not an
exact video-frame-to-command pairing, as evidence. The recorded branch
therefore does not have a matching coarse voltage staircase. Together with
the earlier output-swap videos, this makes Tiliqua's command path or a
single faulty buffered output a poor explanation of the 50-cent pitch
steps. The monitor is still on a separate buffered-mult output, so the
voltage directly at ACRONYM's V/oct jack has not been measured. The next
useful control is to repeat the same fine CV sweep with ACRONYM tuned much
lower (roughly two octaves) without changing the CV patch: if the steps
disappear, the phenomenon is associated with its high-frequency operating
region; if they remain, inspect the jack/patch and test another oscillator
with the identical CV path. No calibration profile was accepted or saved.

The user then lowered only ACRONYM's coarse tuning to about 499.5 Hz at
idle/0 V and left the CV/audio patch in place. In the same ACK-gated
`b,q,r,s,t,u,c,u,t,s,r,q,b` replay, every command was acknowledged and
the combined tuner pitch rose **smoothly**: 2750.67, 2790.06, 2810.11,
2830.36, 2851.14, 2872.11, and 2893.35 Hz on the ascent. Descending
`u,t,r,q,b` returned within about 0.1 Hz of their ascent readings;
descending `s` was 2826.46 Hz versus 2830.36 Hz on ascent and deserves
one more repeat before treating that small deviation as real. The run
ended with `x` to zero OUT0. Thus the same CV commands and patch support
fine, continuous pitch changes at this lower tuning. The high-frequency
staircase is frequency-region dependent. This does not yet separate an
ACRONYM high-frequency/core or patch interaction from a high-frequency
pitch-estimator artifact; earlier native-frame zero-crossing agreement
helps but is not independent physical audio instrumentation. Keep the
profile rejection safeguard and do not average across the high-range
plateaus.

As a host-side control, the production Rust NSDF selector was exercised on
synthetic 192-kHz triangle frames swept in 12-cent steps across the same
10.84–11.5-kHz neighborhood, with eight starting phases. All 64 estimates
were qualified and within 0.3 cent of their known input frequency
(`test_synthetic_high_triangle_fine_steps_do_not_staircase`). A clean
triangle does not acquire the observed staircase merely because of the
selector's high-frequency lag resolution. This test cannot rule out an
artifact caused by ACRONYM's *actual* high-frequency waveform. To resolve
that, capture the physical audio independently or export a native sample
frame at adjacent commanded CV points before altering calibration policy.

With ACRONYM retuned to about 2.0 kHz at idle, an ACK-gated alternating
`q,r,q,r` check at +2.450/+2.460 V reproduced the high-range step twice.
At `q`, the independent rising-zero-crossing period estimate on each raw
ADC frame was about 10,855 Hz; at `r` it was about 11,165 Hz. The NSDF
selector gave the same respective frequencies. The ratio is approximately
48.7 cents, versus the 12 cents expected for a 10-mV step at 1 V/oct.
The raw-wave estimator does not use the NSDF lag choice, so this is not
solely an NSDF peak-selection jump. Both estimators still consume the same
ADC signal, not a separate physical audio instrument. The test sent `x`
to zero OUT0, and the idle audio reading returned to roughly 2.0 kHz.
OSCIO's whole-sample period counter is too coarse at about 11 kHz to
resolve a normal 10-mV pitch step, so it should not be used as the arbiter
of this discrepancy. The actionable conclusion for calibration is to
retain the discontinuity/rejection safeguard pending an independent
waveform or at-jack CV measurement; averaging across the step would hide
an approximately 37-cent *excess* over the ideal step.

The ACRONYM triangle was then multed to a second, independently sampled
Tiliqua (#2 IN0) while remaining on #1 IN0. At 0 V, #2 reported a qualified
pitch near 2.0 kHz with about 9.1 Vpp. During an ACK-gated `q,r,q,r`
repeat, both tuners agreed at each six-second hold:

| OUT0 command | Tiliqua #1 (Hz) | Tiliqua #2 (Hz) |
| --- | ---: | ---: |
| `q`, +2.450 V | 10,857.5–10,858.3 | 10,857.949 / 10,858.032 |
| `r`, +2.460 V | 11,167.8–11,168.3 | 11,168.099 |
| `q`, +2.450 V | 10,857.2–10,857.6 | 10,857.983 |
| `r`, +2.460 V | 11,167.6–11,168.2 | 11,167.759 |

All four DAC-side commands were acknowledged, and `x` zeroed OUT0 afterward.
This corroborates a real period/frequency step in ACRONYM's audio, rather
than an artifact unique to #1's ADC, NSDF selector, or sample clock. Both
Tiliquas still use the same estimator implementation, but #1's separate
raw-frame zero-crossing estimate and the synthetic continuous-triangle
regression provide orthogonal checks against a shared peak-selection bug.
Earlier voltage-monitor videos showed fine CV increments at the buffered
mult, but not directly at ACRONYM's V/oct jack. A jack-level measurement or
an alternate oscillator on the same CV path would be needed to distinguish
an ACRONYM-specific high-range response from a remaining jack/patch issue.
The calibration must not smooth or accept the large local step as a normal
1 V/oct curve.

WMD Legion was then substituted for ACRONYM, with its triangle multed to
both Tiliqua audio inputs and its V/oct fed by the same buffered OUT0 path.
Both tuners read about 2.0 kHz at idle/0 V. The same acknowledged
`q,r,q,r` comparison gave about 11,223 Hz at +2.450 V and 11,302 Hz at
+2.460 V, on both devices and on both visits. This is approximately
12.1 cents: the expected 1 V/oct change over 10 mV. The test ended with
`x` zeroing OUT0. The CV source, mult and two audio detectors can therefore
resolve a normal fine step in this frequency neighborhood. ACRONYM's
behavior is source-specific under the tested setup, though voltage directly
at its V/oct jack remains unmeasured.

Compensability depends on what happens *inside* the 10-mV interval. A
continuous but steep response can be represented by more closely spaced
anchors and inverse interpolation. A true jump leaves an interval of pitches
with no corresponding voltage, which no static calibration curve can play
exactly; the correct behavior is to identify and report that gap, not invent
values or average it away. Map this interval at the 250-microvolt DAC count
resolution, in both voltage directions, before changing profile acceptance.

**Multi-device flashing caution:** with both R5 DBG cables connected,
openFPGALoader's DirtyJTAG `--busdev-num` option did not provide a reliable
way to identify which Tiliqua the archive flasher would actually write. The
attempted serial-targeted flash was followed by no probe ACK on #1, a reset
on #2, and an ambiguous identical manifest readback from both requested bus
addresses. Do not rely on `--busdev-num` for this backend. The safe retry was
performed only after unplugging #2 DBG and checking `--scan-usb` showed the
single remaining #1 debugger (`E46534A193222B21`); slot 1 was then flashed
without erasing option storage. Confirm a new probe ACK on #1 before running
the fine-count diagnostic.

The 250-microvolt count sweep resolved the ACRONYM transition. On an upward
pass, the measured triangle stayed near 10,859 Hz through +2.45725 V and
jumped to about 11,169 Hz at +2.45750 V: roughly **48.7 cents for one DAC
count**. On the downward pass it remained near 11,169 Hz through +2.45125 V
and fell to about 10,859 Hz at +2.45100 V. A long hold at the *same*
+2.45500 V stayed near 10,860 Hz for nine seconds when approached from below,
but near 11,170 Hz for nine seconds when approached from above. Repeating the
below approach restored the lower pitch. All commands were ACKed and the
output was zeroed after each diagnostic. This is a stable hysteresis window
of about 6.25 mV, not merely slow settling. No single-valued static inverse
curve can play every pitch in the skipped ~49-cent interval, and averaging
the two states would invent a pitch the oscillator did not produce. The
calibrator must treat such a region as unsafe, retain a separately verified
contiguous span if possible, and disclose its reduced range. Retuning the
oscillator may move the problematic region outside the desired playing span.

The targeted replay now reserves a bounded probe at the midpoint of the
steepest measured acquisition interval. A host regression models the
48.8-cent jump between semitone-spaced anchors, proves the new target falls
inside the unreachable pitch gap, and proves the existing completed-replay
recovery trims the pending high range without authorizing acceptance before
a fresh check. This is still a sampled safeguard, not exhaustive proof of
continuity; the hardware needs a full CAL run to validate it on ACRONYM.

The first hardware CAL run with that targeted probe never reached replay:
the final zero-volt reference check timed out after a full -5..+8 V
characterization. Its last observed zero error was only -0.88 cent, but it
had accumulated three rather than the required five consecutive tight pitch
readings. The old timeout mislabeled this as "REFERENCE PITCH CHANGED" because
it tested only whether *any* zero pitch had been observed. The reference
check now gets one bounded 2.5-second recovery margin when qualified readings
are already within tolerance and nearly sufficient; if it still fails there,
the result is called unstable pitch. A genuinely out-of-tolerance reference
does not get that margin and remains a pitch-changed failure.

On the next full hardware run, the zero check genuinely measured -8.24 cents
after returning from +8 V and correctly refused the profile. With output
disabled at 0 V, the independent raw zero-crossing and NSDF diagnostic
readings alternated between approximately 1,995.5 and 2,005.8 Hz over many
seconds, a roughly nine-cent two-state difference. Thus the variable zero
check was not explained by the DAC's absolute-accuracy specification above
+5 V alone. Its cause remains to be isolated with a separate, stable 0 V CV
source feeding ACRONYM while its audio remains on the same Tiliqua input.

That control used a Disting EX 0 V output instead of Tiliqua OUT0, with
ACRONYM triangle still on #1 IN0 and its tuning untouched. Across 61
qualified raw-frame readings over 25 seconds, the rising-crossing estimator
spanned approximately 1,935.1–1,946.1 Hz and NSDF matched it
(1,935.8–1,946.0 Hz). The absolute pitch moved because the Disting's 0 V
need not equal Tiliqua's 0 V, but the same two-band alternation persisted.
That strongly disfavors Tiliqua's CV output as its cause. Further controls
are no-CV at ACRONYM and, if needed, direct audio to IN0 without the mult.

With ACRONYM's V/oct cable completely unplugged, 60 raw-wave measurements
over 25 seconds still spanned 1,995.1–2,006.0 Hz; NSDF agreed within the
same two bands. The center now matches the Tiliqua-zero neighborhood again,
but the alternation persists without *any* external CV. The remaining
simple routing control is ACRONYM triangle directly into Tiliqua #1 IN0,
bypassing the audio mult and the second input. If it persists there, this
particular output/settings combination cannot support a 3-cent stable
calibration reference at the present coarse tuning, regardless of curve
fitting or zero-check timing.

That direct-audio control was run with V/oct still unplugged and all ACRONYM
controls unchanged. Sixty qualified raw-wave readings over 25 seconds spanned
1,995.072–2,005.839 Hz (9.318 cents); NSDF independently spanned
1,995.36–2,005.81 Hz. The two-band variation therefore does not require
the audio mult or second Tiliqua input either. Next compare ACRONYM's sine
output at the same settings, directly into #1 IN0, to distinguish a
triangle-output/waveform issue from variation shared by both outputs. These
controls identify the signal path but do not yet prove which circuit or
oscillator setting produces the variation.

With only the audio cable moved to ACRONYM's sine output, still direct into
#1 IN0 and with V/oct unplugged, 60 qualified raw readings over 25 seconds
spanned 1,995.048–2,006.085 Hz (9.55 cents); NSDF spanned
1,995.402–2,005.885 Hz. The same variation on both oscillator outputs
disfavors a triangle-specific waveform/detector interaction. A separate
oscillator around 2 kHz on the same direct input is the next control needed
before attributing the variation to ACRONYM's core or settings rather than
the receiving/measurement path.

WMD Legion was then connected directly to the same #1 IN0, near 2 kHz and
without a V/oct cable. Sixty qualified raw readings over 25 seconds spanned
1,999.988–2,001.530 Hz (1.33 cents); NSDF spanned 2,000.006–2,001.592 Hz.
The 9.5-cent variation therefore follows the tested ACRONYM setup rather
than this Tiliqua input or the detector in general. It may still originate
in ACRONYM's settings, other connected modulation, its power environment,
or the oscillator itself; these tests do not identify that internal cause.
Do not loosen the 3-cent reference-stability gate or average away the two
states to force a calibration. Report unstable pitch and offer a fresh scan
once the oscillator's unmodulated reference is stable.

A subsequent panel photo showed ACRONYM's V/oct, sync, through-zero PM and
other visible input jacks empty. The external-modulation explanation is thus
not supported by the visible patch. WORNG's ACRONYM manual describes the
sine as waveshaped from the triangle core, consistent with both outputs
sharing the same measured variation. A no-CV measurement near 500 Hz is the
next control for whether this depends on the present ~2-kHz tuning rather
than being a persistent feature of the module or its environment.

With ACRONYM sine direct into #1 IN0 and no CV, the user retuned the same
module to about 500 Hz. The fast-bank raw-wave trace was inapplicable there
(only two crossings per short buffer), so the qualified low-bank NSDF output
was used instead: 61 readings over 25 seconds spanned 500.157–500.406 Hz,
or 0.86 cent; the independent first-peak estimate agreed closely. The
module can supply a stable reference at this lower tuning. Next keep those
knob settings and apply an external +2 V to reach ~2 kHz, distinguishing a
pitch-region dependency from the previous coarse/fine settings.

With those ~500-Hz knobs unchanged, a Disting EX supplied +2.0 V to
ACRONYM's V/oct, producing approximately 1,945 Hz. Sixty qualified
high-bank raw-wave readings over 25 seconds spanned 1,944.763–1,946.493 Hz
(1.54 cents). The ~9.5-cent variation at ~2 kHz is therefore not inherent
to that audio frequency; it depends on the previous knob/CV operating
condition. No individual control or internal circuit has been isolated.
The stable ~500-Hz baseline is suitable for a new full calibration attempt,
keeping the two-state jump safeguard active and avoiding any acceptance of
unverified pitch gaps.

A full CAL with those lower knob settings, ACRONYM sine direct to #1 IN0 and
Tiliqua #1 OUT0 direct to V/oct, completed acquisition and zero-reference
checking and entered targeted verification. It returned a **usable graded**
candidate spanning -4.58325 to +2.00000 V (80 acquisition points). All 43
targeted verification points were measured, but the worst residual was
6.83 cents and the local high-end repeatability span was 9.12 cents;
the current safety policy did not certify the unsampled pitches. Nothing
was saved as a production profile. On the TUNER page, a temporary serial
hold at exactly +2.000 V on OUT0 made the same direct ACRONYM sine alternate
between 2,004.889 and 2,015.911 Hz (9.49 cents) in 43 readings. By
contrast, Disting EX +2 V had produced a stable 1,944.763–1,946.493 Hz
under the same knob settings. The absolute pitches differ by roughly
60 cents, so the two nominal +2 V sources likely did not deliver identical
voltage at ACRONYM; this comparison alone cannot establish DAC noise.
OUT0 was explicitly zeroed after the probe. A new temporary, exact-count
serial window of ±10.75 mV around +2 V will map whether the instability is
localized in voltage, as the earlier +2.455-V hysteresis was.

The exact-count window was flashed in a firmware-only build with the same
HDMI bitstream and `spread_spectrum=0.0`, after a one-device DBG scan. At
the unchanged ~500-Hz knobs, direct OUT0 → ACRONYM V/oct and sine → #1 IN0,
an upward 5-mV grid measured: +1.990 V ≈ 1,995.03 Hz, +1.995 V ≈ 2,005.22
Hz, +2.000 V alternating ≈ 2,005/2,015 Hz (9.44-cent span), +2.005 V
≈ 2,015.61 Hz, and +2.010 V ≈ 2,026.01 Hz. Each non-boundary hold varied
by less than one cent over 14–15 wave readings. Reversing the steps gave
the same bands and again a 9.33-cent spread at exactly +2.000 V. The two
bands are reproducible near a narrow voltage threshold, but this grid does
not demonstrate direction-dependent hysteresis at that threshold. Both the
native-wave rising-crossing estimate and NSDF agreed on each band, though
both analyze the same short input frames; an independent long-window or
external frequency measurement would be needed to rule out shared
waveform/window effects conclusively. OUT0 was zeroed after both passes.

Finer 0.25-mV probing localized the mixed readings: +1.997 and +1.998 V
remained tightly near 2,005.2–2,005.6 Hz; occasional high-band readings
appeared by +1.999 V; at +1.99975 to +2.00025 V both bands and some
intermediate estimates appeared; +2.0005 V was mostly near 2,015.6 Hz.
The probe stopped on a missing ACK at +2.001 V and sent `x` in its cleanup
path. The tuner then showed a qualified 500.3–500.5 Hz baseline, confirming
the output returned to zero. These data narrow the unstable interval to
roughly 1.5 mV but do not yet prove whether ACRONYM's physical pitch jumps
or the short-window measurement responds nonlinearly to a waveform change.

The user then routed OUT0 through a buffered mult, with separate branches
to ACRONYM V/oct and a Disting EX voltage monitor. At the same nominal
+2.000-V raw DAC command, 49 native-wave readings over 20 seconds were
2,036.776–2,037.701 Hz (0.79 cent), versus the ~2,005/2,015-Hz alternation
with OUT0 patched directly. The routing moved the absolute pitch by tens of
hertz and away from the narrow threshold; it does **not** by itself prove
that direct OUT0 was noisy. In the user's 27-second voltage-monitor video,
the Disting's top-left numeric reading held at approximately +2.025 V during
the nominal +2.000-V raw-count command, then returned to approximately
+0.005 V after the output was zeroed. No switching between displayed voltage
values was visible at the monitor's resolution. This is the buffered branch,
not an independent measurement of the direct OUT0-to-ACRONYM patch or of
the ACRONYM jack; the probe command also bypasses the normal calibrated
voltage conversion. The video therefore does not identify which element
caused the earlier narrow pitch boundary. The serial probe sent `x` after
the hold.

With the same ~500-Hz coarse/fine setting and direct OUT0-to-V/oct patch,
the later adaptive scan acquired 120 usable points after nine low/high
no-signal skips. Repeated independent checks narrowed the candidate and
exposed a localized upper-range discrepancy. The user accepted a
105-point, **user-kept (not certified)** RAM curve covering -4.58325 to
+4.00000 V. Its automatic targeted grid covered 44/44 notes; the worst
residual was +14.69 cents at A8 -27.4 cents. A nine-visit local check
around +3.80250 V found the low and high neighbors at +3.79175 and
+3.83325 V individually stable within 0.15 cent, but the center repeated
at +14.67 cents residual. This is a repeatable failure of the *current
correction* at that command, not proof of a globally unusable oscillator.

A separate, denser read-only CHECK on that RAM curve completed its entire
207/207-target grid without missing any target. The worst grid error was
+18.45 cents at A8 (command +3.82075 V), and the largest within-target
span was 18.61 cents in the upper register. The follow-up nine-visit local
check timed out after 7/9 visits at the same +3.82075 V command, where
fresh settled detector readings spanned 6,987.96–7,115.67 Hz and the
available center repeats disagreed by 31.19 cents. Thus the old firmware's
`SCAN TIMEOUT` status concealed a completed grid and an **incomplete local
check**. A firmware change now preserves the completed grid, records
unresolved local visits explicitly, and labels grid/local progress
separately. After flashing that change and loading saved profile slot 3, a
second read-only CHECK completed all 207 grid targets and all nine local
visits, with no missing targets. Its worst error was +18.55 cents at A8;
the grid's maximum within-target span was 18.61 cents. The interleaved
local visits at +3.82075 V repeated +18.52, +18.49, and +18.49 cents at
the center (0.15-cent within-window span; 0.03-cent between-repeat range),
while the neighboring low and high targets averaged +0.11 and -0.04 cents.
The firmware correctly reported `OUTSIDE 2C OR NOT REPEATABLE`. The repeated
center error is a narrow *profile residual* that may be correctable; the large
grid span means other upper-range behavior remains less certain. A local
refinement or bounded range cut must be independently checked before it is
called a precision calibration. Do not attribute the upper-register
alternation solely to ACRONYM without an independent pitch measurement at
the commanded voltage.

The advanced CHECK → IMPROVE action was restored to the UI for a paired
single-anchor experiment on saved profile slot 3. With the same ACRONYM
patch, it acquired nine local visits and validated 20 alternating original
and candidate requests. The candidate was offered in RAM, not committed:
the worst of its paired test targets improved only from 18.30 to 15.35 cents.
Two neighboring pitches remained approximately +15 cents sharp, so one
anchor did not capture the full width of the upper-range bend. This is a
reason to test successive measured anchors or a targeted denser acquisition,
not to conclude that poorly tracking oscillators are out of scope. The
original saved slot 3 remains available for comparison.

The user accepted that first refinement in RAM only and reran the full
read-only CHECK. The 106-point candidate completed all 207 grid targets and
all nine local visits with no missing measurements. The worst residual moved
from A8 +18.55 cents to B8 -16.73 cents at a +3.98500-V command. Three
interleaved B8 visits repeated -16.47, -16.49, and -16.45 cents after
neighbor adjustment, with only 0.02-cent between-repeat range. The adjacent
+3.91675-V and +4.00000-V targets averaged -0.26 and -0.24 cents. The
single-anchor candidate corrected part of one high-end bend but left a
second narrow residual near the upper endpoint; the useful next test is a
second measured anchor, not a claim of full-range precision. Slot 3 remains
the untouched baseline curve.

In the subsequent one-shot AUTO trial, acquisition retained 95 measured
anchors after one unstable high-range segment and missing readings beyond
roughly +5.5 V. Its first targeted check completed 44/44 pitches with a
-9.17-cent worst residual. A paired local candidate proceeded to an
independent 44/44 recheck and improved the worst magnitude to +8.65 cents;
the final retained curve had 96 points and a CHARACTER grade. The +8.65-cent
target repeated within about 0.02 cent locally, so this is a consistent
residual, not evidence of a wildly inconsistent oscillator region. The
automatic run ended after a second refinement attempt; its status was
`REVIEW - USABLE GRADED RESULT`. The exact underlying stop reason was not
preserved by that firmware, so the next build records it separately rather
than speculating from the status label. The result demonstrates graded
retention, not yet the desired precision on ACRONYM.

The following repeat run characterized 120 points, then trimmed its high edge
in four complete 44-target passes (roughly +5.08, +4.96, +4.79, then +4.75 V).
This repeated full-range replay was the dominant avoidable cost. The
subsequent local refinement produced a tentative 112-point candidate; its
full recheck reduced worst error from -23.96 to -21.46 cents but failed the
other acceptance conditions. The firmware correctly rolled back the edit and
reported `REVIEW - RECHECK REJECTED`, with an UNSAFE 23.96-cent residual. The
specific failed condition was not separately logged, so this is not proof of
oscillator non-repeatability. The next build probes only the new edge during
intermediate range recovery, then performs one full check before review.

The first regional-recovery hardware run characterized 106 points. Three
successive high-edge trims used 19-target half-volt checks instead of three
whole-profile replays, then returned to a complete check. A later regional
check had a missing local target. The firmware stopped at `SCAN DONE - MISSING
TARGETS` and discarded the diagnostic candidate. That was not a measured
grade of the remaining curve: the regional recovery guard excluded completed
local checks, and the status path hid the missing target. The follow-up build
allows a repeatably missing local target to trigger a bounded contiguous trim,
retains incomplete diagnostics if no recovery remains, and prohibits accepting
any result with missing targets.

With that fix, the next ACRONYM run retained 91 acquisition points and checked
44/44 targets without missing readings. Its worst residual was -8.32 cents at
about +2.79175 V. Interleaved local repeats at this target had just 0.01-cent
between-visit range; adjacent measured anchors were about +0.2 cents. The
second *acquisition* of that identical trio for refinement rejected as `REFINE
NOT REPEATABLE`; the retained check was graded UNSAFE due 13.75-cent maximum
within-window span. Automatic refinement now reuses the already-repeatable
local trio to propose a measured anchor, but still requires a separate paired
old/new validation and full independent recheck.

The next build characterized 120 points, used three short high-edge checks
near +5.083, +4.750, and +4.244 V, then checked 45/45 pitches on the retained
106-point range. Paired refinement produced a tentative 107th point and
reached full recheck, but one of 45 targets lacked qualified pitch. The
result correctly remained unverified, yet review displayed 107 points while
its 18.97-cent grade came from the *pre-edit* 106-point curve. This exposed a
rollback bug: an incomplete recheck was treated as an initial range-review
checkpoint. The fix rolls the tentative point back before showing the prior
checked curve and records the first missing recheck voltage on serial. This
corrected path has host coverage; its next hardware run is pending.

The next ACRONYM run retained 120 anchors and completed all 44 sampled check
targets. Near +5.01675 V, the grid read about +56.56 cents while three later
visits at that same commanded CV averaged -14.14 cents (0.09-cent
between-repeat range): a 70.69-cent grid/local disagreement. This is not a
consistent profile residual to fit. The run stopped at `REVIEW - GRID/LOCAL
DISAGREE` without trimming, because the recovery branch deferred to local
refinement while the refinement gate then rejected the earlier disagreement.
The control flow now prioritizes contiguous range recovery when an initial
grid/local revisit disagrees by more than 10 cents. It still probes the newly
cut boundary region and requires a subsequent full-range check. The precise
cause of the discrepant high-register first reading remains unproven.
