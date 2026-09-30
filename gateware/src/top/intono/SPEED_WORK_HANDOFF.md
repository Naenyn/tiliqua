# INTONO calibration-speed handoff — 2026-09-30

Read this first when resuming the calibration-speed work in a new Codex chat. The user wants a fast, one-shot oscillator calibration that still corrects poorly tracking oscillators; Klavis CalTrans's roughly 20–30-second experience is the comparison. Do not sacrifice measured range, invent missing points, or silently accept a bad profile merely to reach that time. The user wants **exact, granular timings** for acquisition and every check/recovery pass. Keep working independently until physical testing is needed; do not stop after an analysis-only update.

## Natural oscillator origin — September 30, built and flashed

### First AUTO hardware run after this update

Captured `/tmp/intono-natural-auto-20260930.log` on #1. AUTO completed with an
acceptable CHARACTER review, 63 points from -666750 to +4500000 uV, E0 +10.8c
through A#5 +46.4c. Worst error 8.474c, stability 8.600c, final 45/45 targets.
Total **327670 ms (5m27.670s)**: acquisition 162088 ms, checking 165582 ms,
no refinement/recheck-category time. Completed passes: I 81138 ms (46/46),
B 14462 ms (7/7), B 14558 ms (7/7), F 55424 ms (45/45). Pass sums equal the
checking total. Two partial recoveries, two skipped local checks. Acquisition:
107 successful measurements / 56203 ms, 52 missing / 105855 ms, nine >=1s
successful points, no 16-window fallback. Point sums omit 30 ms overhead.
No serial-report truncation seen. Restored 0 V tuner ~33.961–33.964 Hz, qualified.
The user subsequently reported that the quantizer test worked well, with about
five octaves of usable pitch. This is user-observed practical coverage, not an
independent accuracy measurement at every note. The user requested that future
module help preserve the setup rule: set the lowest desired stable pitch at the
lowest pitch-CV voltage supported by the oscillator and available from Intono;
for positive-only inputs, use 0 V. This guidance is now recorded in README.md,
including reliable detection, fixed knob positions and range-limit caveats.

The user approved deriving the musical target from the oscillator's natural
pitch at 0 V with its tuning controls centered. A bound profile now sets the
route's 0 V note to the nearest measured note and scale root to that pitch class.
The exact measured pitch remains the physical reference for nominal 1 V/oct
fallback outside the profile and for reachable output limits. Corrected mapping
still uses the measured curve without applying the reference twice. Manual note
and root changes remain available; rebinding reapplies the natural defaults.

- Capture only a qualified measurement at exactly 0 V; never extrapolate a
  reference from a sweep that first found usable audio above zero. Keep the
  reference through curve trimming and save/load. Missing reference retains the
  previous manual-origin behavior.
- TUCP v5 stores the reference in the former reserved four bytes, keeping the
  same maximum record size. Versions 1–4 still load and can reuse an exact 0 V
  anchor. Legacy profiles without that anchor need a new scan for this feature.
- Serial reports include PHYSICAL_ZERO_MC for a bound reference. Calibration
  timing logs and accuracy checks remain unchanged. A checked retuning operation
  without recalibration is future work, not part of this update.
- Validation: 249 Rust tests, 56 targeted Python tests, plus a final rerun of all
  16 library-file tests after validator changes; successful R5 firmware build.
- Archive: `gateware/build/intono-adaptive-status-r5/intono-natural-origin-20260930-r5.tar.gz`
  SHA256 `dab5f026096fd53c4263bd4427ba2f02675d0853cef51a1b75d2e2902dcb4770`.
  Successfully flashed slot 1 on sole verified R5 DirtyJTAG E46534A193222B21;
  refresh DONE. Earlier archives and saved flash profiles were preserved.
- The user explicitly authorized interrupting the active quantizer and losing
  the unsaved RAM profile because they are away from the rack and can regenerate
  it. Do not ask them to stop playback or save that profile again for this flash.
- Next physical test: boot slot 1 if needed, load/bind a profile with an exact
  0 V anchor or rescan with fixed tuning controls. A ~34 Hz oscillator should
  default near C#1 with root C#. Sweep up/down across the calibrated boundary;
  check pitch, bypass/reentry status and batch cycles. Nominal extrapolation can
  still disagree with a poorly tracking oscillator beyond its measured range.

## Route range handling correction — September 30, built and flashed

The user tested the accepted Waveplane RAM profile with a 0..10 V LFO. The
quantizer stopped near 8 V. They approved profile bypass, continued quantization,
and the nearest reachable scale note at output limits, and requested build/flash.
Pre-flash serial confirmed Q1 STOPPED - INPUT AT RAIL at 8187000 uV, all routes
inactive, calibration inactive and MV=0. The accepted RAM profile had 63 points.
User was told that firmware refresh clears RAM: reload a saved profile or rescan.

- Playback falls back to nominal 1 V/oct after quantization only for
  PitchOutsideRange. Invalid profiles and other mapping faults still stop.
- Nominal routes use the existing -5..+8 V hardware guard, replacing the old
  +5 V software ceiling. Beyond output limits, select the nearest reachable
  degree with the configured scale, root, transpose and custom period, including
  equal-bin mapping. Continuous routes cap nominal voltage. If the limited note
  is inside the measured profile, retain its correction.
- Clipped ADC samples no longer stop the route. Use the represented sample;
  its true voltage beyond the rail is unknown. Status shows LIMITED - INPUT
  CLIPPED, LIMITED - OUTPUT RANGE, or PROFILE BYPASSED - NOMINAL CV. Normal
  mapping/status resumes automatically on reentry, even at the same note.
- Existing quantizer hysteresis remains. Continuous corrected/nominal boundary
  transitions can jump because their mappings differ. No curve extrapolation.
- Stale CV, ACK, output fault and deadline guards remain; ownership, calibration
  accuracy checks, averaging and timing logs are unchanged. Firmware-only change.
- Validation: 245 real Rust calibration/playback tests, 56 targeted Python tests
  (calibration/menu, library, hardware output guards and scheduler), successful
  R5 build, clean diff check. Coverage includes both rails, reentry, stale/faults,
  bypass, continuous output, sparse/transposed/equal-bin scales, corrected limited
  notes and bounded scale selection against an exhaustive nearest-degree reference.
- Archive: `gateware/build/intono-adaptive-status-r5/intono-route-limits-20260930-r5.tar.gz`
  SHA256 `87486915ec2ac90e539c0905140248bd837348c12f2fb78e07e3157728916cf1`.
  Earlier archives preserved. Successfully flashed slot 1 on sole verified R5
  DirtyJTAG E46534A193222B21; refresh DONE, saved options/profiles preserved.
  Five-second post-refresh serial check had no application output; boot slot 1
  may be needed. Port released.
- Next physical test: boot INTONO, reload/bind a saved profile or rescan, then
  sweep 0..10 V up and down across input and profile limits. Expect active route,
  a reachable scale note at the upper limit, nominal CV outside the profile and
  correction inside. Monitor Q status and maximum batch cycles. Multiple-route
  boundary workloads still need physical CPU qualification.

## Waveplane ~34 Hz FAST comparison — September 30, completed

User started FAST after34HzAUTO, with no reported retuning or wiringchange.
Same focused-input firmware. Log:
`gateware/build/intono-adaptive-status-r5/waveplane-34hz-focused-fast-20260930-serial.log`.
First captured acquisition25667ms. Final ACTIVE=false,MV=0; reader stopped,
port released; no profile accepted/saved. Report intact,OVERFLOW=0.

| Measurement | 34Hz AUTO | 34Hz FAST |
| --- | ---: | ---: |
| Total active ms | 357024 | 330334 |
| Acquisition ms | 165441 | 141399 |
| Checking ms | 191583 | 188935 |
| Measured observations / ms | 107 / 59613 | 107 / 35366 |
| Missing observations / ms | 52 / 105798 | 52 / 106003 |
| Measured points >=1s / AVG16 | 10 / 0 | 0 / 0 |
| Initial candidate anchors | 104 | 104 |
| Final anchors | 61 | 63 |
| Final voltage range V | -0.66675..4.33325 | -0.66675..4.5 |
| Worst checked error cents | 5.314 | 7.184 |
| Stability cents | 6.935 | 7.342 |
| Partial high recoveries / skippedlocal | 4 / 3 | 3 / 2 |

FAST26.690s (7.48%) shorter overall; acquisition24.042s shorter,checking2.648s
shorter. Same52missing attempts stillcost~106s. FAST measuredpointtime24.247s
shorter (40.67%), offset205ms longer missingtime;30ms acquisitionoverhead both.
Different finalextent and checkgrids mean these are not accuracy-equivalence
measurements. Worsecheckederror/stability supports keepingAUTO cautiousdefault;
FAST remains opt-in. BothCHARACTER acceptable=true,advisoryscore93%, not2cPrecision.

FAST exactpasssequence(ms,valid/attempted): I93422(47/47),B11355(7/7),
B10859(7/7),B16231(7/7),F57068(45/45). Sum188935ms;refine/recheck0.
Initialgrid1missing and upperinstability; combinedregion recovery near4695233uV,
then4666750,4583250uV. Final45/45 plus9/9local. Gridworst3.74c,
gridspan7.34c; localrepeatdifferences low3.88c,high6.09c,target5.09c.
RangeE0+10.8c..B5-48.4c;response933mV/oct. Completedzero34.000Hz qualified,
VPP8.641V,windowage208ms,endage95ms; subsequent33.998Hz.

This pair reinforces coarse measured-range discovery as the largest immediate
opportunity (~106s of failed observations in both policies), followed by fewer
small boundarytrims. Do not lower missingpointtimeouts indiscriminately: preserve
lowfrequency settling and detect usable islands with explicit measureddiscovery.

## Waveplane retuned to ~34 Hz AUTO — September 30, completed

User clarified Waveplane has one output, coarse knob tunes in octaves, and
signals become audible just above12o'clock. They retuned starting pitch to
approximately34Hz and started AUTO. Do not infer a selectable sine output.
Same focused-input firmware. Raw log:
`gateware/build/intono-adaptive-status-r5/waveplane-34hz-focused-auto-20260930-serial.log`.
First captured active status was acquisition86397ms; totals firmware-reported.
Final ACTIVE=false,MV=0; no profile accepted/saved. Capture stopped/port released.

- Total357024ms (5m57.024s), versus previous Waveplane442906ms:85882ms
  (19.39%) shorter, different tuning and range, not a firmware A/B benchmark.
- Acquisition165441ms, checking191583ms, refinement/recheck0.
  Prior184353/258553ms respectively: acquisition18912ms shorter,
  checking66970ms shorter.
- Sweep107 measured observations59613ms,52 missing105798ms,10 measured
  points >=1s,AVG16=0. Sums165411ms omit30ms overhead. Warnings52missing,
  1flat,0unstable/discontinuities. Initial candidate104anchors.
- Exact pass sequence(ms,valid/attempted): I94387(46/46),B9875(7/7),
  B7923(7/7),B8628(7/7),B12439(7/7),F58331(45/45).
  Sum191583ms,OVERFLOW=0,report intact. Four high-side partialrecoveries,
  skipped-local3. First full replay had1missing and many upper unstabletargets;
  combined gap/unstable region selection triggered near4696247uV. Later
  recovery targets4625000,4583250,4375504uV. Final freshreplay45/45 plus9local.
- Final61anchors,-666750..4333250uV. CHARACTER,acceptable=true,
  worst5.314c,stability6.935c,advisoryscore93%. Local repeatdifferences
  low3.81c,high3.05c,target3.00c. RangeE0+10.4c..G#5+36.4c,
  response933mV/octave. Prior56anchors,+250000..4833250uV,
  worst6.822c/stability9.047c. Retuning moved usable voltagecoverage to include0V.
- Early completed zero snapshots were invalid, then tuner qualified34.012Hz,
  VPP8.646V,windowage172ms,endage59ms. Do not describe this run as unable to
  qualify0V or assume immediate post-operation publication equals settledpitch.
- Missingpointtime alone105.798s (~29.6% total) remains a primary speed target.
  Changing tuning improvedcoverage/error/time but still exceeds5min goal.
  Next controlled FAST comparison could retain this tuning; larger algorithm
  improvement should target coarse range discovery plus fewer boundaryreplays
  without abandoning measured anchors or fresh independent confirmation.

## Waveplane focused-input AUTO — September 30, completed

User identifies oscillator as Dove Audio Waveplane, AUTO. Waveform/output and
pre-scan 0 V pitch were asked via pending question but not yet answered. Do not
assume sine, unchanged Acronym tuning, or absence of signal in missing region.
Same focused-input firmware. Raw serial log:
`gateware/build/intono-adaptive-status-r5/waveplane-focused-auto-20260930-serial.log`.
Capture began at acquisition40703ms; all final phase totals firmware-reported.
Reader stopped and port released. No profile accepted/saved by Codex.

- Total442906ms (7m22.906s): acquisition184353ms, checking258553ms;
  refinement/recheck0. ACTIVE=false, MV=0 at completion.
- Sweep96 measured observations49801ms,66 missing134523ms,7 measured
  points >=1s, AVG16=0. Sum184324ms omits29ms overhead. Characterization
  warnings63 missing,1 flat,0 unstable/discontinuities; those counts differ
  from sweep attempt accounting. Qualified points first appeared above0V.
- Exact pass sequence (ms, valid/attempted): I95643(47/47), B8869(7/7),
  B14543(7/7), F58831(47/47), B14336(7/7), F66331(46/46).
  Sum258553ms; OVERFLOW=0; no report truncation. Three partial high-side
  recoveries, skipped-local3. Rejected broad upper unstable region initially
  at5502505uV, followed by5500000uV then4875000uV.
- Final56 anchors,+250000..+4833250uV, CHARACTER acceptable=true,
  worst6.822c, stability9.047c, advisoryscore91%; gridworst4.67c,
  gridspan4.61c; final46/46 plus9/9 local repeats. Local repeat differences
  low7.75c,high9.05c,target8.08c contributed to final assessment.
  Measuredrange E0+17.2c..D#5+6.4c; response933mV/octave.
  Firmware advice: measured range starts above0V; low requests clamp.
- At completed0V, repeated tuner snapshots HZ=0,VALID=false,QUALIFIED=false
  while VPP roughly7.5..8.7V. This establishes present signal amplitude but
  no qualified pitch; it does not distinguish low frequency, waveform ambiguity,
  modulation or another cause. Need waveform and0V-pitch context before FAST
  comparison; consider obtaining a stable qualified tuner pitch first.
- Missing observations alone cost134.523s (30.4% of total). Together with
  full checking/recovery this prioritizes robust coarse range discovery and
  fewer repeated upper-boundary replays. Do not claim FAST solves missing
  points, lower confidence thresholds, or invent missing calibration anchors.

## Focused-input AUTO hardware result — September 30, completed

User started AUTO after focused-input candidate flash. Capture attached during
acquisition (~32 s), so phase totals are firmware-reported active time, not a
host stopwatch from RUN. Raw log:
`gateware/build/intono-adaptive-status-r5/acronym-focused-auto-20260930-serial.log`.
Final review confirmed ACTIVE=false, MV=0; no profile accepted/saved by Codex.
Serial reader stopped after completion. Report intact, timing OVERFLOW=0.

- Total 250647 ms (4m10.647s), versus previous AUTO 303669 ms: 53022 ms
  or 17.46% shorter. Previous FAST was 253243 ms, but a different policy/run.
- Acquisition 67648 ms versus 118373 ms: 50725 ms (42.85%) shorter.
  Sweep 122 measured observations / 46284 ms, 9 missing / 21332 ms,
  1 measured point >=1 s, no AVG16 fallback. Point totals omit 32 ms overhead.
- All checking 182999 ms versus 185296 ms: only 2297 ms shorter, due to
  six partial high-side recoveries versus one previously; skipped-local=3.
- Exact check pass sequence (ms, valid/attempted):
  I 40560 (44/44), B 11686 (7/7), B 11094 (7/7), B 11108 (7/7),
  F 34232 (45/45), B 7957 (7/7), B 6524 (7/7), B 12872 (7/7),
  F 46966 (45/45). Sum equals reported checking total. No refinement/recheck.
  I=initial full grid; B=regional boundary check; F=fresh full-range replay.
- Final 84 anchors, -4583250..2333250 uV (previous AUTO 82 anchors,
  -4583250..2166750 uV). CHARACTER, acceptable=true, score94% advisory,
  worst5.250c, stability6.256c, final45/45 plus9/9 local repeats.
  Previous AUTO worst4.652c, stability6.614c. This is not proof of identical
  accuracy or 2-cent Precision performance; different upper extent/grid.
- Initial candidate contained120 anchors and triggered upper-region recovery
  near5.08325V, then4.75V and4.278186V. Later instability recovery at2.875V,
  2.83325V,2.3753V. Latest scheduling exposes a larger initial candidate than
  earlier runs; investigate waveform ambiguity/qualification and recovery
  selection before attributing every change to oscillator behavior.
- First completed zero snapshot498.567Hz versus previous AUTO496.536Hz,
  approximately+7.1c; snapshots do not establish continuous drift or retuning.
- Next improvement: reduce repeated boundary search/replay work while preserving
  final independent confirmation; adaptive measured curve spacing remains the
  larger planned improvement. Detector scheduling gives clear acquisition speed
  benefit, but recovery consumes the potential gain in checking.

## Focused-input candidate — September 30, built and flashed

User clarified that TUNER is a read-only view of all inputs, while calibration
claims one input/output pair. No parallel scans. They approved the remaining
staged speed roadmap. The first next change isolates detector scheduling before
adaptive curve sampling or reducing boundary checks.

- New `nsdf_sampling.rs` plan: active CAL/CHECK/refinement services only the
  captured operation input, alternating native/low banks. Idle restores the
  existing eight-bank round robin. An in-flight frame retains its channel.
- Visible TUNER during an operation requests two focused bank visits for each
  background bank visit. All six other banks receive service every 18 requests.
  Faster requests do not count overlapping windows as independent observations.
- Passive tuner no longer hides CV-claimed inputs; claim conflicts between
  operations remain unchanged. Quantization uses separate raw CV sampling.
- Qualification, settling, averaging, final checks, FAST/AUTO distinctions and
  timing logs remain unchanged. Hardware accuracy and elapsed time unmeasured
  for this candidate; no performance claim yet.
- Validation: 65 targeted Python tests (scheduler, publication, resolver,
  device guards, firmware and calibration/menu), 241 real Rust calibration
  tests, 3 jack-ownership tests, and 16 library codec tests. R5 firmware-only build
  succeeded; `git diff --check` clean. Fixed a whitespace-sensitive source
  assertion in publication tests. Compile library fixture as a normal binary
  via its Python tests, not `rustc --test` (it is a codec stdin driver).
- Archive: `gateware/build/intono-adaptive-status-r5/intono-focused-input-20260930-r5.tar.gz`
  SHA256 `73aa8f9c45fcfc3e623543c724e23d4dc064a3245b4cfa5cb875242080aa3492`.
  Previous speed and baseline archives remain intact.
- Flashed slot 1 successfully, saved options preserved, sole verified #1
  DirtyJTAG `E46534A193222B21`. Pre-flash serial confirmed `ACTIVE=false`,
  `MV=0`, previous AUTO result 82 points. No scan started by Codex.
  A five-second post-refresh serial check produced no application output; user
  may need to select/boot INTONO slot 1. Serial port is released.
- Next: boot slot 1 if refresh returns to bootloader; attach serial before user
  starts AUTO. Stay on CAL for focused-input speed comparison. Keep oscillator
  tuning and wiring unchanged; compare time, range and error with AUTO below.
  Test passive TUNER separately. Then implement measured adaptive spacing with
  dense fallback and independent final confirmation; consider boundary probe
  reduction and zero-reference drift diagnosis after isolating this change.

## Same-candidate AUTO comparison — September 30, completed

The user next ran AUTO on the same flashed candidate. Capture confirmed
POLICY=AUTO. Raw log:
`gateware/build/intono-adaptive-status-r5/acronym-auto-20260930-serial.log`.
The serial port was released after completion. No profile was accepted/saved
by Codex. Both completed reports have no truncation and timing OVERFLOW=0.

| Measurement | FAST | AUTO |
| --- | ---: | ---: |
| Total active time | 253,243 ms | 303,669 ms |
| Acquisition | 86,851 ms | 118,373 ms |
| I: initial full grid | 67,134 ms (45/45) | 73,585 ms (46/46) |
| B: regional boundary check | 28,168 ms (7/7) | 28,440 ms (7/7) |
| F: fresh full-range check | 71,090 ms (45/45) | 83,271 ms (43/43) |
| All checking | 166,392 ms | 185,296 ms |
| Refinement / post-edit recheck | 0 / 0 | 0 / 0 |
| Final anchors | 82 | 82 |
| Final voltage endpoints | -4.58325 .. +2.16675 V | -4.58325 .. +2.16675 V |
| Partial recoveries / skipped local checks | 1 / 1 | 1 / 1 |
| Worst checked absolute error | 6.682c | 4.652c |
| Reported stability | 6.660c | 6.614c |
| Grade / advisory score | CHARACTER / 93% | CHARACTER / 93% |

Both final full checks included nine local repeats. AUTO status was
`REVIEW - USABLE GRADED RESULT`, ACTIVE=false, MV=0. Its single high-side trim
was selected at 2,187,453 microvolts. The final worst grid error was -4.65c
near C7 -32.1c; local target mean -4.60c, repeat 0.04c. Local high endpoint
repeatability 1.63c prevented the tighter paired-refinement requirement.

AUTO sweep point costs: 122 measured observations **96,846 ms**, nine missing
observations **21,495 ms**, nine measured points >=1s, one completed AVG16
acquisition point. Sum **118,341 ms**, 32 ms less than the acquisition phase.
FAST saved **31,522 ms / 26.6%** of acquisition and **50,426 ms / 16.6%**
overall in this pair. The remaining 18,904 ms difference came from checking;
both policies use the same verification rules, so that difference is not a
deliberate faster-check setting. Their curvature-selected pitch grids differ.

AUTO produced a 2.030c smaller measured worst error, with almost unchanged
stability and exactly the same retained CV range. This supports keeping AUTO
as the cautious default and FAST as an explicit tradeoff, but is not proof
that fewer samples caused that accuracy difference: first completed-review
zero-frequency monitors were 495.108 Hz (FAST) and 496.536 Hz (AUTO), about
**+4.99c drift** between readings. They are snapshots, not continuous drift
measurements or proof of retuning. Sequential drift and different target
grids limit the comparison. Both grades remain CHARACTER rather than Precision.

The recovery improvements are effective in both policies in these runs:
each needed one partial recovery rather than the prior run's nine. Checks
still occupy 61% of AUTO's total time, so replay/estimator timing remains the
largest target for future improvement. Boundary checking alone costs about
28s, but removing it would be a new algorithm change requiring validation;
do not silently delete confirmation coverage to hit a time target. Broader
oscillator qualification and repeatability comparisons remain outstanding.

## First hardware FAST run — September 30, completed

After flashing the candidate below, the user booted INTONO and ran ACRONYM
with POLICY=FAST. Serial capture confirmed the policy and completed result.
Raw log: `gateware/build/intono-adaptive-status-r5/acronym-fast-20260930-serial.log`.
No report truncation; pass-timing OVERFLOW=0. Capture was stopped and the serial
port released after the final result. No profile was accepted or saved by Codex.

**Total active calibration time: 253,243 ms (4m13.243s).**

| Phase/pass | Exact ms | Coverage |
| --- | ---: | --- |
| Acquisition | 86,851 | 120 candidate anchors before recovery |
| I: initial full grid | 67,134 | 45/45; unstable upper targets |
| B: regional boundary check | 28,168 | 7/7 grid, followed by local repeats |
| F: fresh full-range check | 71,090 | 45/45 grid plus 9/9 local repeats |
| Checks total | 166,392 | Sum of the three exact pass durations |
| Refinement / post-refinement recheck | 0 / 0 | No attempted edit |

One partial recovery, high side only, selected at 2,188,357 microvolts;
one nine-visit local check was skipped after the already-unstable initial grid.
Final retained **82 points, -4.58325 .. +2.16675 V**, grade **CHARACTER**,
worst checked absolute error **6.682c**, stability **6.660c**, score **93%**.
Status: `REVIEW - USABLE GRADED RESULT`, ACTIVE=false, MV=0.
The final grid worst was +5.32c; a local repeat increased the checked worst to
6.682c. Local low endpoint repeatability was 5.42c, so a curve edit was not
supported by the tighter repeatability requirement. No Precision claim.

Sweep point costs: 122 measured observations **65,470 ms**, nine missing
observations **21,349 ms**, one measured point >=1s, zero completed AVG16
acquisition points. Observations include reference phases. Their 86,819 ms
sum is 32 ms below acquisition due to transition/restore overhead. Verification
may still use AVG16; the acquisition counter does not describe replay estimators.

Compared with the older 420,462 ms run, this was 167,219 ms / **39.8% shorter**
with identical retained endpoints and count, but a higher worst error
(6.682c versus 2.86c) and lower reported stability span (6.660c versus 9.23c).
Compared with the most recent 577,992 ms run, it was 324,749 ms / **56.2% shorter**,
one recovery versus nine, and retained one fewer anchor / one semitone less at
the high end (+2.16675 versus +2.25 V). That run's worst/stability were
3.924c / 9.222c. The final zero-output monitor here was around 495 Hz;
older notes describe tuning near 500 Hz. Target grids also differ (45 vs 44).
These are individual runs, not a controlled proof of unchanged accuracy or a
way to attribute every timing gain specifically to the three-estimate option.

**Next comparison at the time (now completed above):** AUTO on this same candidate with tuning/patch unchanged,
captured from before RUN. This separates the acquisition-count choice from
the recovery improvements present in both policies. A repeat FAST run or
independent CHECK can then assess variability and reproducibility. Do not
declare FAST qualified for equal accuracy from this one result.

## Overnight continuation — candidate ready, not flashed

**Morning flash completed — September 30:** The user powered the rack and
authorized flashing. Verified the sole connected R5 DirtyJTAG serial was
`E46534A193222B21` (#1). Pre-flash debug serial on `/dev/cu.usbmodem83102`
reported `CAL STATUS READY - RUN IN MENU ACTIVE=false ... MV=0`. Flashed
`intono-speed-candidate-20260930-r5.tar.gz` into **slot 1**; bitstream,
firmware and manifest writes completed successfully and device refresh
completed. Option storage was excluded from the write commands, preserving
saved options/profiles. Hardware calibration comparisons remain pending.
The overnight "not flashed" statements below describe the earlier state.

The user went to bed and explicitly deferred flashing/testing until morning.
**No hardware was accessed or flashed in this continuation.** Existing dirty
work was preserved; no commits, resets or branch changes were made.

Implemented and host-tested:

1. **CAL → POLICY → FAST**: three agreeing fresh acquisition estimates instead
   of five. AUTO remains the default. FAST otherwise uses AUTO's tolerances,
   semitone grid, range search, settling guard, 16-window fallback, independent
   verification, refinement, grading and recovery rules. The two-estimate
   sub-audio exception is unchanged. Menu still fits its existing nine rows.
   This is an experimental choice for well-behaved oscillators, not a relaxed
   accuracy certificate. It may miss transient variation or cause more rework.
2. **Combine missing and unstable grid faults in one range selection.** The
   previous code selected around missing points while retaining already-known
   unstable targets from the same pass. Recovery now excludes both together,
   including a local-repeat-only gap when present, and retains the widest
   contiguous span of real measured anchors. It still performs boundary and
   fresh whole-range checks before offering an automatically graded result.
   It does not discard all large pitch errors: repeatable curve errors retain
   their opportunity for measured refinement.
3. **Skip nine futile local repeats after an already-unsafe grid.** Only initial
   Verify/recovery checks with >10c grid spread, available recovery budget,
   no saved best/undo, and non-PRECISION policy qualify. Region recovery already
   takes precedence over those repeats. Healthy grids, PRECISION, post-edit
   rechecks and the final certificate retain their full local repeats.
4. **Protect timing logs when the serial report overflows.** Factored the
   unchanged sweep/pass/category timing lines into `serial_report::timing` and
   call it first in the abbreviated fallback too. Added
   `AUTO SPEED POLICY=... SKIPPED_LOCAL_CHECKS=...` to distinguish modes and
   count the shortcut. Maximum 24-pass timing output fits within 1024 bytes,
   including maximum-width numeric fields; the serial buffer stays 2048 bytes.
   Existing 24-pass capacity and explicit OVERFLOW counter remain unchanged.

Validation: **241 Rust calibration/live tests passed**, **7 calibration/menu
Python tests passed**, **16 library/profile-file Python tests passed**.
R5 firmware-only build succeeded with `spread_spectrum=0.0`. New tests cover
mixed faults on both sides, a local-only gap combined with instability,
shortcut eligibility, a complete I → B → F recovery with final nine repeats,
FAST rejecting a biased acquisition, and timing capacity/overflow.

Deterministic simulated performance, 80 ms publication cadence, 120 ms windows,
500 Hz nominal zero pitch (these are **not hardware timings**):

| Simulated oscillator | AUTO acquisition | FAST acquisition | Check, either mode |
| --- | ---: | ---: | ---: |
| Ideal 1 V/oct | 99,280 ms | 79,920 ms | 61,760 ms |
| Smooth curved response, exponent V + 0.006 V² | 95,120 ms | 75,760 ms | 62,240 ms |

Both modes retained the identical 119 measured anchors and Precision grade in
each case, with identical verification plans (44 and 49 grid targets respectively)
plus nine local repeats. This is about 20% less acquisition time and 12% less
total simulated time. It does **not** establish ACRONYM speed, drift behavior,
or a 20–30-second end-to-end result.

Build directory: `/Users/naenyn/git/tiliqua/gateware/build/intono-adaptive-status-r5/`.

- **Morning candidate:** `intono-speed-candidate-20260930-r5.tar.gz`
  (also copied at the normal `intono-adaptive-status-b2cb7e-d-r5.tar.gz` path).
  Archive SHA-256: `f57d44b40a847ca7a2db6d22525b21c5ea86200c7006dfe4a959738f41e4765f`.
  Firmware size 296,176 bytes; firmware SHA-256:
  `8dc4c578ff5a396bf6b9fc3367f12288e58e2575fb8b85e59920ce9c0b3743cc`.
- **Preserved previous instrumentation-only build:**
  `intono-timing-baseline-20260930-r5.tar.gz`.
  Archive SHA-256: `437f1a995dda6c9198e77235075911ee29edace323c2480cb217010034a38aca`.
  This older build still has the potential serial fallback timing omission.
- Both archives contain the exact same existing R5 `top.bit`. Firmware grew
  by 800 bytes; no serial-buffer growth or additional profile copies.

**Morning procedure:** identify #1 and confirm stopped/zero as below, flash the
named candidate, capture serial before running AUTO on ACRONYM, then compare
FAST with unchanged oscillator tuning/patch. Also compare both on a well-behaved
oscillator. Check total time, exact I/B/F/R pass sequence, skipped-local count,
measured/missing costs, retained range/anchors, worst error and stability; use
the independent PROFILES CHECK where useful. Keep AUTO as the recommendation
until those measurements support FAST. No empirical claim about the cause of
the previous nine trims is possible yet: this session addressed demonstrated
code redundancies, not a new hardware trace.

## Checkout and safety

- Working directory: `/Users/naenyn/git/tiliqua`; branch: `codex/intono-adaptive-calibration` (verify with `git branch --show-current`). Use this checkout, not a worktree.
- This is a substantially **dirty, ongoing** branch: dozens of modified INTONO source/docs/tests and untracked `cv_probe.rs` and a generated VexiiRiscv Verilog file. Preserve all existing work. Do not reset, switch branches, clean, commit, or overwrite unrelated changes without considering them.
- Tiliqua **#1**, hardware R5, INTONO slot **1** is the development target. The user has said test calibration profiles may be lost. Tiliqua #2 has sometimes been connected; never flash based only on slot number. Verify exactly one intended DBG/flasher before any flash.
- Latest known sole DirtyJTAG serial for #1: `E46534A193222B21`. At the end of the prior chat, `openFPGALoader --scan-usb` found **no** flasher and `/dev` showed only `cu.usbmodemSN234567892`. The new timing build was therefore **built but not flashed**. Do not assume the DBG cable/rack is currently connected. Recheck; if necessary ask the user to reconnect #1 DBG and disconnect #2 DBG. Never guess which device is #1 when both appear.
- Historically the debug serial port was `/dev/cu.usbmodem83102` at 115200, but USB port assignment may change. Identify it again after cable changes. A serial reader can use `screen <port> 115200` or pyserial. Do not leave another process holding the port when reconnecting. The user values serial capture over photos.
- Flash only slot 1 and verify hardware identity. Preserve saved options/profiles if the flash workflow offers a choice. The user explicitly authorized interrupting playback and losing the unsaved RAM profile for the natural-origin update above; stopping the route is not a prerequisite for that authorized flash. Future sessions should consider current playback state without requesting redundant approval when interruption is already authorized.

## What was measured

The older ACRONYM sine run with shortened fixed guard but no sparse silent-gap stride: acquisition **180,607 ms**, checking/recovery **239,855 ms**, total **420,462 ms** (7m00.462s). Retained 82 points, −4.58325 to +2.16675 V; 91% CHARACTER, worst 2.86 cents, stability 9.23 cents, 44/44 final check.

The latest run after sparse silent-gap scanning and 7-target regional boundaries: acquisition **116,724 ms** (1m56.724s), checking/recovery **461,268 ms** (7m41.268s), total **577,992 ms** (9m37.992s). It took **nine partial recoveries**; final retained profile 83 points, −4.58325 to +2.25 V, 91% CHARACTER, worst 3.924 cents, stability 9.222 cents, 44/44 final check. Acquisition improved by about 64 s but repeated checks more than erased that gain. The old firmware logged only aggregate CHECK time; any earlier estimate for an individual pass was *not exact* and must not be presented as such.

The latest characterization initially measured a broad response reaching about +5.5 V, but repeated replays progressively removed the upper edge. This is why optimizing only the sweep will not make end-to-end calibration fast. Avoid declaring the sparse stride a successful overall speed improvement based on this one run.

## Current measurement algorithm and speed costs

- Sweep plan: semitone-spaced voltage commands (about 83.333 mV) across hardware-safe −5 to +8 V, up to 157 nominal positions; 0 V reference search and a final 0 V check are additional logical phases. The sweep can end early after four missing high-end readings beyond a previously established ~18 kHz response.
- At a normal point, acquisition requires **five fresh, closely agreeing detector estimates**, or **three with opt-in FAST policy**. Those estimates are not necessarily non-overlapping/independent; the fallback requires **16 non-overlapping windows** when the fast path does not qualify. Below ~20 Hz the fast path can use two estimates. Compare FAST against extra failed checks/recovery, not acquisition time alone.
- Current acquisition guard is **75 ms after acknowledged CV**; `SCAN_WINDOW_START_MS=175` and `SCAN_READY_MS=225` include the allowed output acknowledgement. Point timeout is 5 s; leading silent discovery can advance after 2 s. Do not remove the no-signal timeout altogether.
- After four consecutive silent semitone points beyond an established usable curve, the current code probes at quarter-volt spacing (stride 3), returning to semitone spacing on qualified audio. It never fills skipped points with interpolation.
- Automatic check has a targeted grid and local repeat, followed as needed by regional boundary probes and whole retained-range rechecks. Up to 16 partial recoveries are permitted. The regional boundary plan was reduced from 19 to 7 targets. A profile must still get a fresh whole-range check before automatic certification.
- No whole-operation wall-clock deadline is currently imposed. Individual measurement deadlines and a finite recovery/refinement budget remain. The user explicitly rejected premature whole-scan time limits.

Relevant files: `fw/src/calibration_live.rs`, `fw/src/calibration/bipolar_sweep.rs`, `fw/src/calibration/automatic.rs`, `fw/src/calibration/verification_scan.rs`, `fw/src/calibration/averaging.rs`, `fw/src/serial_report.rs`, `fw/src/capture_trace.rs`. `AUTO_CALIBRATION.md` and `OSCILLATOR_QUALIFICATION.md` contain fuller history; some dated paragraphs describe older builds.

## Previous timing-only build (superseded by the candidate above)

The last turn added timing instrumentation and **compiled it but did not flash it**:

- `AUTO CHECK_PASSES_MS` reports each completed automatic check as `<kind>:<milliseconds>:<tested>/<total>`. Kinds: `I` initial full check, `F` subsequent full check, `B` boundary/regional check, `R` post-refinement recheck. It retains up to 24 passes and reports `OVERFLOW` thereafter. The existing `AUTO TIME_MS ACQUIRE=... CHECK=... REFINE=... RECHECK=...` still reports category totals.
- `CAL SWEEP_TIMING` reports counts and accumulated milliseconds for measured versus missing/timeout points, number of points taking at least 1 s, and count reaching the 16-window averaging path. Those point sums need not exactly equal the full acquisition phase because they omit transition/restore overhead. The counters include origin discovery and final reference check, not only retained profile points.
- Code was host-tested: `rustc --edition=2021 --test gateware/tests/tuner_calibration_live_fixture.rs -o /tmp/intono-calibration-tests && /tmp/intono-calibration-tests --quiet` returned **235 passed**. `git diff --check` passed. Firmware-only R5 build succeeded with `spread_spectrum=0.0`.
- Archive ready at `/Users/naenyn/git/tiliqua/gateware/build/intono-adaptive-status-r5/intono-adaptive-status-b2cb7e-d-r5.tar.gz` (about 563 KiB). This archive contains the newly instrumented firmware and existing R5 bitstream. After any edits, rebuild before flashing.
- The serial report buffer is `String<2048>` in `capture_trace.rs`; check that the new compact pass line is actually visible and not replaced by `SERIAL REPORT TRUNCATED` on a long run. If it truncates, prioritize timing over verbose older diagnostics or enlarge cautiously after checking RAM. The prior chat did not validate this on hardware.

## Build, test, flash, capture

From `/Users/naenyn/git/tiliqua`:

```sh
rustc --edition=2021 --test gateware/tests/tuner_calibration_live_fixture.rs -o /tmp/intono-calibration-tests
/tmp/intono-calibration-tests --quiet
git diff --check
```

From `/Users/naenyn/git/tiliqua/gateware` (use the existing PDM environment, not Homebrew `python3`/global pytest):

```sh
pdm intono build --hw r5 --artifact-name intono-adaptive-status --fw-only --spread-spectrum 0.0
openFPGALoader --scan-usb
pdm flash archive build/intono-adaptive-status-r5/intono-adaptive-status-b2cb7e-d-r5.tar.gz --slot 1 --noconfirm
```

`pdm` may require elevated filesystem access to its cache lock under `~/Library/Caches/pyapp`; `openFPGALoader`/flash require USB access. In the previous chat, `pdm intono build ... --fw-only` succeeded after escalation. `--fw-only` relies on the existing `top.bit` under this artifact name; a new artifact name without a prior bitstream will fail. Keep `--spread-spectrum 0.0`: the user previously saw HDMI instability without it. Read scan output and ensure only #1's expected DirtyJTAG is present before running the flash command. Do not flash if `--scan-usb` lists no device or ambiguous devices.

After flash, the user will need to boot INTONO slot 1 if it returns to the bootloader, then start one CAL → RUN with ACRONYM sine directly into Tiliqua #1 IN0 and Tiliqua OUT0 directly to ACRONYM V/oct, with ACRONYM tuning fixed near 500 Hz at 0 V and no other ACRONYM CV/sync modulation. Attach serial *before* the run. All profiles in this session are tests; no need to ask the user to save one unless preserving a particular curve is essential for a specific follow-up. Do not ask for another scan until the new build is known to be flashed and logging.

For the next report, give a per-pass table or concise sequence with exact milliseconds from `AUTO CHECK_PASSES_MS`, along with measured/missing-point sweep totals, count of >1s points, and total wall time. Make clear that the pass labels describe the firmware's check type and that measured+missing sums omit overhead. If report is truncated, fix logging before repeating the hardware scan.

## Next decisions

1. Follow the morning candidate procedure above once hardware identity is certain; collect one AUTO ACRONYM run and calculate where the time really goes. The user specifically wants exact timings rather than intuition.
2. Benchmark opt-in **FAST** against AUTO, keeping the 16-window fallback and independent final verification. Assess both acquisition speed and the number of check failures/recoveries. Do not lower confidence thresholds blindly.
3. If missing points dominate, analyze where silent/ambiguous regions consume 2–5 s and whether a coarser *discovery* pass followed by denser sampling only in a candidate usable range would retain coverage more efficiently. Distinguish seeking range from building the final calibration curve.
4. If check passes dominate (as the previous run suggests), eliminate redundant regional/full replays or use one complete replay to identify all unreliable regions and select the largest contiguous measured span once, then do one independent confirmation. Preserve user-visible quality and no invented data. Inspect `recover_completed`, `recover_grid_regions`, `regional_check`, and the conditions that caused nine edge trims. Verify on at least ACRONYM and a well-behaved oscillator before claiming improvement.
5. Longer term, a 20–30 s target likely requires a two-stage adaptive strategy rather than simply trimming fixed guards or reducing five to three readings. This is a hypothesis, not a measured result.

Do not assume CalTrans's internal algorithm is known; the 20–30 s number is the user's experience, not a published implementation fact.
