# Oscillator calibrator comparison and acceptance policy

## Scope — September 21, 2026

This document records the published behavior of comparable oscillator
calibrators and the resulting direction for TUNER. It separates documented
product behavior from inference. The proposed TUNER policy below is an approved
design direction, not yet implemented firmware behavior.

The comparison is limited by what manufacturers publish. In particular, most
products describe suitable waveforms and voltage coverage but do not publish
their internal pitch-estimator thresholds, verification density, or exact
pass/fail criteria. Absence of a published requirement is not evidence that the
implementation has no such requirement.

## Published comparison

### Klavis CalTrans

The CalTrans manual recommends a sine or square wave, with another simple wave
as an alternative. It requires pitch/phase modulation to be disabled. It
explicitly says calibration will not work with multiple zero crossings,
multiple simultaneous waves such as chords, stacking, unison or ring
modulation, modulation of shape/phase/frequency, phase/frequency-altering
processing, or unstable/retriggered amplitude.

The procedure stops when the signal is missing or inconsistent in frequency,
phase or level. A base frequency below 20 Hz is an error; a base above 80 Hz is
only a warning and calibration continues. CalTrans makes the best of the VCO's
available voltage/frequency range and reports partial coverage rather than
requiring a particular full-range result. No cents-based acceptance threshold
is published.

Source: [Klavis CalTrans manual V1.6](https://www.klavis.com/images/Klavis_-_CalTrans_manual_V16.pdf),
especially pages 8–10.

### Bastl Instruments 1983

The 1983 manual asks for a simple triangle, sine, pulse or saw waveform. Very
low starting frequencies can time out. Initial tuning measures two points per
octave, interpolates the remaining semitones, and is stated to take roughly one
to five seconds. Later tuning operations primarily compensate for drift.

Bastl publishes a two-cent precision claim and notes that different reference
tuners can disagree by one or two cents. It describes approximately five to six
cents as a barely noticeable difference for trained musicians. These are useful
benchmarks, but the manual does not say that every interpolated pitch is densely
verified within two cents before a calibration is accepted.

Source: [Bastl 1983 manual](https://bastl-instruments.com/content/files/manual-1983-web.pdf),
especially pages 6–8.

### Tubbutec µTune

Tubbutec documents common square, saw, triangle and sine waves as suitable for
its detector. It says waveforms with multiple zero crossings per period will not
work and recommends disabling FM during calibration.

The current manual describes an eleven-point manual VCO curve: the user records
0 V, then adjusts the command at each successive voltage to make the displayed
frequency difference as close to zero as oscillator drift allows. The result can
be saved even when exact zero is impractical; no automatic numerical rejection
threshold is published. µTune separately offers closed-loop auto-tuning whose
correction speed is adjustable: slower correction preserves more short-term
analogue character, while faster correction produces a more stable pitch.

Sources: [µTune product page](https://tubbutec.de/%C2%B5tune/) and
[µTune manual V2.0](https://tubbutec.de/files/uTune-user_manual-v.2.0.pdf),
especially pages 28–29.

### Expert Sleepers Silent Way and disting auto-calibrators

Silent Way recommends a direct, simple square, triangle or sine signal. The
disting NT auto-calibrator outputs voltages from -4 V through +6 V, measures the
resulting pitches, and draws the response curve, which the manual says should
ideally look straight. It then applies the correction continuously.

The published documentation does not specify a worst-error limit, mandatory
dense verification grid, repeatability threshold, or cents-based rule for
rejecting a completed curve.

Sources: [Silent Way manual](https://www.expert-sleepers.co.uk/downloads/silentway_2_5_0_manual.pdf)
and [disting NT manual V1.8](https://www.expert-sleepers.co.uk/downloads/manuals/disting_NT_user_manual_1.8.pdf),
Auto-calibrator section.

### Modulove Pitchkeeper

The currently published Pitchkeeper is a precision offset generator and motion
looper, not an oscillator-response calibrator. Its published specifications do
not provide an acceptance-policy comparison for this work.

Source: [Modulove Pitchkeeper](https://modulove.io/pitchkeeper/).

## Comparison with the current TUNER procedure

TUNER currently attempts substantially stronger qualification than the
published procedures above:

- automatic verification uses a targeted grid of corrected pitches plus a
  repeated local check at the worst measured region;
- the advertised objective is a two-cent worst checked error, with a 1.5-cent
  internal completion aim to leave empirical sequential-check headroom;
- local refinement requires repeated measurements to agree within 0.75 cent;
- acquisition normally requires a three-cent total stable-pitch spread;
- an unrepeatable interior verification target is fatal to the whole candidate,
  while only limited edge recovery is supported;
- refinement is bounded to eight attempts, 129 total stored points, and a
  fifteen-minute overall deadline.

The comparison does not show that these checks are wrong. It does show that our
current all-or-nothing result is stricter than the behavior manufacturers expose
to their users. Bastl's two-cent statement is the closest published numerical
benchmark, but it is a precision claim rather than a documented dense,
worst-case acceptance gate.

The products also reinforce an important limit: relaxing a cents threshold
cannot make an ambiguous pitch safe. Multiple period families, octave mistakes,
non-monotonic response, and unstable modulation can produce a plausible but
incorrect curve. CalTrans and µTune address that problem by requiring a simpler
calibration output. TUNER may support more difficult signals as a best effort,
but it must not silently turn ambiguity into calibration data.

## Approved direction for TUNER

Replace the single binary accuracy result with graded, transparent results while
retaining hard safety requirements.

### Hard requirements

These remain non-configurable:

- no accepted octave/subharmonic-family ambiguity;
- monotonically increasing measured pitch over an accepted segment;
- no invalid DAC command, missing output acknowledgement or output fault;
- no extrapolation across an unmeasured or demonstrably ambiguous region;
- sufficient contiguous measured range to be useful;
- honest reporting of measured coverage, failures and uncertainty.

Failure of a hard requirement is `UNSAFE`, not a lower accuracy grade.

### Result grades

The initial proposed grades are:

| Grade | Checked worst absolute error | Intended meaning |
|---|---:|---|
| Precision | at most 2 cents | Current accuracy objective |
| Musical | at most 5 cents | Useful general musical correction |
| Character | at most 10 cents | Best-effort result for difficult or characterful oscillators; explicit warning |
| Unsafe | not applicable | Ambiguous, non-monotonic, faulted, or insufficiently verified |

These boundaries are policy starting points, not established psychoacoustic or
metrological guarantees. Physical qualification across varied oscillators may
justify revising them. The saved profile should retain its grade, measured
voltage/pitch coverage, checked worst error, and observed stability so recall
does not lose the context in which it was accepted.

### Isolated failures and partial coverage

One difficult interior point must no longer automatically discard an otherwise
useful multi-octave candidate. The automatic procedure should:

1. retry the point with a longer bounded observation and a grade-appropriate
   stability allowance;
2. if it remains unmeasurable, split the candidate at the gap rather than
   interpolate through it;
3. independently verify the resulting contiguous regions;
4. offer the largest useful verified region, or allow the user to choose between
   multiple useful regions;
5. record the discarded gap and never describe it as calibrated.

This generalizes the current edge-trimming behavior to safe interior
segmentation. It follows CalTrans's useful principle of making the best of the
available range without pretending that unavailable coverage exists.

### User-facing policy

Prefer a small number of understandable presets over raw detector thresholds:

- `AUTO`: begin with precision requirements, retry difficult measurements with
  longer averaging, and return the best honestly graded safe profile;
- `PRECISION`: retain the current strict two-cent-oriented behavior;
- `FORGIVING`: permit longer averaging and Musical or Character results while
  preserving every hard safety requirement. A bounded estimator window may
  show up to ten cents of quarter-block variation and five cents of
  first-half/second-half drift; final independent replay must still remain
  within the ten-cent Character accuracy and stability ceilings.

The default should be `AUTO`. The review page must show the grade, usable range,
worst checked error and any segmented/discarded region before acceptance. A
lower grade must require explicit acceptance and must never be relabeled as a
precision result.

Measurement stability and corrected-pitch accuracy are separate quantities.
A stable but nonlinear oscillator is exactly what calibration should correct.
A detector reading that alternates between incompatible pitches is unsafe even
if a wide error allowance could numerically contain it. Implementation and UI
must keep those concepts separate.

## Implementation status

The first firmware implementation now follows this direction:

- CAL exposes `AUTO` (default), `PRECISION`, and `FORGIVING` policies;
- independent replay produces `PRECISION`, `MUSICAL`, `CHARACTER`, or `UNSAFE`
  from separate worst-error and stability measurements;
- AUTO tries the original two-cent target first but may offer an explicitly
  lower graded result; PRECISION accepts only the Precision grade; FORGIVING
  uses a ten-cent acquisition/replay policy but retains all hard safety gates;
- Unsafe automatic results cannot be accepted;
- the grade, checked error, and observed stability are stored in version-four
  profile records; versions one through three still load as `UNVERIFIED`;
- AUTO and FORGIVING may trim an unrepeatable interior failure and recheck the
  larger remaining contiguous region. Further failures may narrow that region
  again, with four destructive recoveries maximum. A failure is never bridged
  or interpolated through, and each new boundary triggers a fresh replay.

The current segmentation pass retains the larger side automatically. Selecting
between multiple disjoint useful regions remains future UI work. The presets
and grade thresholds are policy starting points pending
physical qualification across the oscillator matrix. The existing hard
ambiguity, monotonicity, routing, output-acknowledgement, and DAC-safety checks
are unchanged.
