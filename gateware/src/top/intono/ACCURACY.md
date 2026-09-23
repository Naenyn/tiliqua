# Detector accuracy baseline — 2026-09-09

Hardware feedback after the DC correction: the user reports usable tracking
at approximately 0.036 Vpp. Waveform, frequency, noise and reference accuracy
were not recorded, so this is a useful observation, not a guaranteed input
sensitivity or accuracy specification.

The tuner still uses a hysteretic positive-crossing counter, not a general
fundamental-frequency estimator. Before replicating measurement state for four
channels, test the selected-channel algorithm at production sample rate.

## Reproduction and limits

From `gateware`, run
`PYTHONPATH=src .venv/bin/python tests/tuner_accuracy_probe.py`.
The probe simulates the actual `TunerPeripheral` at 192 kHz accepted-sample rate,
20 ms minimum pitch window, default hysteresis and DC-filter settings. Each
case starts from reset, runs for 220 ms, and records snapshots published between
120 and 220 ms. It reports first estimate latency and error against the known
synthetic frequency. These are short, deterministic cases with phase zero,
not an exhaustive stability study, hardware clock calibration, analog/noise
measurement or CPU-time benchmark. Quantized samples are integer ADC counts.

Correction to the earlier qualification scope: the default r5 build uses
48 kHz, not 192 kHz. The numerical baseline below is for the optional 192 kHz
mode. It must not be presented as measured accuracy of the default hardware
build. The integrated verifier tests added below explicitly cover both rates.

## Fault found and corrected

The former DC tracker accumulated `(sample - dc) >> 12` in whole counts. Small
positive corrections truncated to zero while negative corrections rounded
down. The resulting negative bias could prevent the waveform from reaching
the negative hysteresis band. Low-amplitude inputs could never lock or stop
updating after an initial estimate.

The corrected tracker accumulates fractional counts, then shifts only when
forming the DC estimate. This preserves the original filter time constant and
keeps the level/RMS path unchanged. No divider or additional multiplier is used.

## Results

Maximum absolute cents error in the observation interval:

| Signal | Peak counts | DC counts | Before | Corrected |
|---|---:|---:|---:|---:|
| Sine 32.7032 Hz | 4000 | 0 | 1.176 | 0.585 |
| Sine 65.4064 Hz | 4000 | 0 | 1.176 | 0.291 |
| Sine 110 Hz | 4000 | 0 | 0.451 | 0.210 |
| Sine 440 Hz | 4000 | 0 | 0.561 | 0.321 |
| Sine 1760 Hz | 4000 | 0 | 0.321 | 0.321 |
| Sine 7040 Hz | 4000 | 0 | 0.246 | 0.246 |
| Triangle/saw/square 440 Hz (each) | 4000 | 0 | 0.321 | 0.321 |
| Sine 110 Hz | 200 | 0 | No updates | 0.210 |
| Sine 110 Hz | 800 | 0 | No updates | 0.210 |
| Sine 110 Hz | 2000 | 0 | No updates | 0.210 |
| Sine 110 Hz | 2000 | -6000 | No updates | 1.112 |
| Sine 110 Hz | 2000 | +6000 | No updates | 1.202 |

All 14 corrected cases publish 3–5 estimates during the observation interval.
First estimate latency is 20.18–60.21 ms; the DC-offset cases take about 55 ms.
"No updates" means none in the final 100 ms, including cases that briefly
produced an earlier estimate. At 4000 counts/V, the 200-count case is 100 mVpp.
The larger residual errors after applying DC offsets include filter settling;
do not use these first observations as calibration measurements without a
settling/stability policy.

## Next qualification work

- Sweep initial phase, amplitude/DC transitions, clipping, noise and richer
  harmonic waveforms. Multiple positive crossings can still cause octave errors.
- Characterize lost-signal recovery and confidence before relying on this for
  automated oscillator calibration.
- Measure the real sample-clock contribution with an external reference.
- Prefer shared arithmetic with per-channel state for four-channel acquisition;
  qualify timing/resources before adopting four separate estimators.

Five permanent low-level/DC regression tests accompany the probe. Existing
channel-handoff, RMS, sine/DC and reference-tone tests remain required.

## Build qualification

All 12 regression cases pass. Full r5 non-circular timing passes: CPU
68.17/60 MHz, pixel 89.28/74.25, serializer 395.10/371.33, audio 70.03/12.29.
Resources: 13,292 logic cells (previous 13,437), 6,850 FF (+12), 24 EBR and
6 DSP (unchanged). Archive SHA256:
`10fcb77cc95faad765979b7c7e161fe0917ad9db5fe1d90772e9c7fe9288c882`.

## Long-silence recovery correction

The previous detector retained its first crossing/cycle count after the
firmware's half-second stale-pitch threshold. On signal return it could include
the silent interval in the next elapsed-time measurement. Gateware now retires
both the unfinished observation and published pitch after the same half-second
without crossings. A returning crossing starts a new observation; it cannot
make the pre-silence pitch valid again. Voltage measurement is unaffected.

Fifteen regression cases pass, including first-reading recovery into both
higher and lower pitches, abrupt pitch steps, the low-level/DC cases, channel
changes and reference tone. The recovery/step tests use a 3200 Hz simulation
sample rate for quick deterministic periods; low-level tests use production
192 kHz. A paused sample stream does not advance sample age: this is an audio
sample timeout, not a wall-clock watchdog for a failed codec. Short gaps below
the timeout may still contaminate an observation, and abrupt pitch steps can
produce a transitional averaged reading before settling. Neither behavior is
yet a calibration-ready confidence/stability policy.

Full r5 non-circular build passes timing: CPU 68.45/60 MHz, pixel
86.42/74.25, serializer 429.55/371.33, audio 69.74/12.29. Resources:
13,522/24,288 logic cells (+230), 6,850 FF, 24/56 EBR and 6/28 DSP
(FF/EBR/DSP unchanged). Archive SHA256:
`3829e622eb3a2f42b1ec52a5735a601aefb81854225a7af91c3de170943533ca`.

Hardware feedback: the user confirmed that this recovery build works well.

## Waveform qualification

Run `PYTHONPATH=src .venv/bin/python tests/tuner_accuracy_probe.py --waveforms`
to reproduce the following production-rate simulations. They use the same
220 ms duration / final 100 ms observation interval as the baseline. Noise is
seed-0 uniform integer noise added to each sample, not measured analog noise.
Clipping is signed 16-bit saturation, not a model of the analog input stage.

| Signal | Maximum absolute error | First estimate |
|---|---:|---:|
| 110 Hz sine, 72 peak counts, four initial phases | 0.210 cents | 32.14–38.99 ms |
| 440 Hz pulse, 10% and 90% duty, 4000 peak counts | 0.321 cents | 22.73 ms |
| 440 Hz sine, 50000 peak counts before clipping | 0.321 cents | 22.73 ms |
| 440 Hz sine, 4000 peak counts, ±32 counts noise | 0.321 cents | 22.73 ms |
| 440 Hz sine, 200 peak counts, ±16 counts noise | 1.002 cents | 22.83 ms |
| 440 Hz sine plus 25% second harmonic | 0.321 cents | 22.73 ms |
| 440 Hz sine plus 75% or 150% second harmonic | **1200.120 cents** | 21.60–21.62 ms |

At nominal 4000 counts/V, 72 peak counts is 0.036 Vpp. The four initial
phases are 0.125, 0.375, 0.625 and 0.875 cycles. This supports the user's
low-level observation for clean signals but does not establish a noise-floor
or sensitivity guarantee. The moderate harmonic case and both strong harmonic
cases use 4000-count fundamental amplitude and phase-aligned sine harmonics.

The strong-harmonic cases contain a genuine 440 Hz fundamental, but the
crossing counter reports approximately 880 Hz. This is an algorithm limitation,
not sample-clock error or display jitter. Ten new passing-envelope cases and
two strict expected-failure fundamental tests preserve both sides of the
qualification. An unexpected pass must be reviewed when the algorithm changes.
No production source, firmware, timing or resource usage changes in this step.

### Consequence for the next detector step

Do not treat a stable crossing estimate as proof of the fundamental, especially
for calibration. Do not fix this by blindly halving the detected frequency:
that would make an actual 880 Hz sine incorrect. Qualify a bounded waveform
period-verification approach against these cases, real 880 Hz signals, phase
and waveform changes before choosing its hardware implementation. Measure its
sample-storage and processing costs with four-channel shared arithmetic in
mind. More expensive general-purpose spectral estimation is not yet justified
by these tests. Short-dropout rejection and calibration settling/confidence
remain separate unfinished requirements.

## Bounded waveform repetition verifier

The crossing counter remains the inexpensive pitch candidate source. An
independent `PeriodVerifier` captures raw signed samples through power-of-two
box averaging (2:1 at 48 kHz, 8:1 at 192 kHz), producing 2048 samples at
24 kHz. The box filter is inexpensive, not a high-rejection anti-alias filter.
Firmware submits the measured period in capture-sample Q8 units. No input
sample transfer or waveform processing is done on the CPU.

The verifier checks period multiples 1 through 4, in ascending order. Each
candidate compares 256 pairs spread over the available history, using Q8
linear interpolation for the delayed sample. A mean absolute residual no
greater than 5% of the observed peak-to-peak range passes; constant/tiny windows
do not pass. The first match wins. Threshold comparison uses shifts and adds,
not division. This is a bounded candidate heuristic, not an exhaustive period
search: a sufficiently weak fundamental may still be missed.

Six capture samples per crossing is the minimum admitted lag (4 kHz crossing
estimate at the normal capture rate). Below that lag interpolation is not
reliable enough; firmware retains the original unverified estimate. Candidates
that exceed available history also fail safely. No stable-result claim is made
for changing waveforms, impulses, noise or arbitrary polyphonic input.

The single read port and interpolation multiplier are sequentially scheduled.
The first place-and-route attempt failed the CPU clock constraint because
subtraction, multiply and add were in one cycle. These now occupy separate
clocked stages. Worst-case work is under 7300 system clocks (122 microseconds
at 60 MHz); simulation asserts this bound. Audio capture continues. A 32-sample
overwrite guard protects the latched history origin; if processing cannot
finish before those samples arrive, it aborts without a match. New requests
while busy are ignored. Channel changes and pitch expiration clear history
and results, with highest priority even in the middle of a calculation.

Firmware reads only completed results and caches them against channel and
candidate period, with approximately 6.8 cents of lag tolerance. A larger pitch
change bypasses the old correction. Capture warmup is about 85 ms; replacing a
waveform can require that history plus the 20 ms foreground schedule to settle.
The current display has no separate verification indicator. In particular,
`valid` still does NOT mean calibration-ready. This must be distinguished in
the measurement interface before automatic oscillator calibration is added.

Tests exercise the actual verifier RTL, not just the Python design probe:
clean notes, strong second harmonics, low-level signals, third/fourth candidate
multiples, insufficient/constant history, ongoing capture, request collisions,
overwrite abort and channel changes. Integrated CSR tests derive the candidate
from the actual crossing measurement at both 48 and 192 kHz; they check 440 Hz
with 75%/150% second harmonic, actual 880 Hz, a 72-count 110 Hz sine and a
7040 Hz bypass case. Each corrected integrated result is within 2 cents in
that tested snapshot. The two earlier expected failures remain appropriate
for the RAW crossing estimator; the new integrated tests must pass.

Four-channel planning: keep one verification arithmetic engine and schedule
independent channel histories; do not instantiate four copies by default.
Four 2048x16 histories would require eight EBR blocks total, but that shared
scheduler and four-channel acquisition are not implemented or timing-qualified
yet. Full four-channel end-to-end CPU bandwidth and UI cost remain unmeasured.

### Default-rate raw-counter baseline

The probe now accepts `--sample-rate 48000` (or `192000`). Re-running the
original 14 cases at 48 kHz gives maximum errors of 2.061, 0.880, 1.202,
1.443, 1.443 and 1.146 cents for the six 4000-count sines in increasing
frequency order. Triangle/saw/square at 440 Hz each give 1.443 cents. The
110 Hz, 200/800/2000-count zero-offset cases each give 0.120 cents.

The ±6000-count DC cases are still settling in this short observation window:
first reports arrive at 126.25–128.40 ms and maximum errors are 39.109–44.324
cents. The DC filter has a sample-count-based time constant, four times longer
in seconds at 48 kHz than at 192 kHz. These are raw crossing measurements;
the candidate verifier does not refine their fractional frequency or supply
a settling policy. This is an explicit next accuracy issue, not a qualified
calibration result or a regression caused by the verifier.

### Integrated build qualification

49 Python tests pass, with two explicit expected failures for the raw crossing
counter's harmonic ambiguity. Two host Rust cache-policy tests also pass.
The normal unrotated r5 build passes all clocks: CPU 63.17/60 MHz, pixel
86.75/74.25, serializer 445.04/371.33, audio 71.65/12.29. Final resources:
14,107/24,288 logic cells (+585), 7,228 FF (+378), 26/56 EBR (+2),
7/28 DSP (+1), relative to the installed long-silence-recovery build.
The tightest CPU-domain path is the existing PSRAM-to-CPU cache return path,
not verifier interpolation. Margin is modest: resource availability does not
guarantee that future additions will route at the required clock rate.

Archive SHA256:
`963d9157ffd1b85b0e720c38adfedc05d0ef72b87d01c1efe3e1eeda937c6935`.
The circular display build and full four-channel scheduler are not qualified
by this build. Options storage and option schema are unchanged.

## Basic-waveform scope and default-rate DC settling

User field feedback on the verifier build: sine, triangle, saw and ordinary
square waves behave as expected. Some harmonically rich Local Parks outputs
work, but blade, binary and very thin pulse settings do not. No captured samples
or exact oscillator settings are available, so the supplied product description
is context, not a reproduction fixture. The user explicitly accepts reliable
basic-waveform tuning with best-effort complex-waveform handling. Do not expand
to a costly general-purpose estimator merely to cover every waveshaper output.
The described blade's octave relationship and binary/atonal output also mean
output periodicity need not identify the oscillator's internal core frequency.

The default DC-filter coefficient now scales with sample rate: shift 10 at
48 kHz and shift 12 at 192 kHz, both approximately 21.3 ms. Explicit shift
overrides are retained for tests. This changes only the crossing detector's DC
tracker, not the raw voltage/RMS measurement or the waveform verifier. No new
multiplier or sample memory is introduced.

In the default-rate 110 Hz, 2000-peak-count, ±6000-count offset cases, first
estimates now arrive at 54.19–54.88 ms (previously 126.25–128.40 ms).
Maximum errors in the 120–220 ms observation interval are 1.202–1.443 cents
(previously 39.109–44.324). These are synthetic test results, not a hardware
accuracy specification. Tests cover both signs at both codec rates, four
initial phases of a 72-count 32.7032 Hz sine at 48 kHz, and live DC steps.
Live-step assertions allow 120 ms for settling, then check every published
reading for the following 100 ms. Initial/transitional readings are still not
calibration-qualified.

A separate synthetic 48 kHz, 440 Hz pulse probe at 4000 peak counts tracks
1%/99% duty with maximum 1.443 cents error, but fails at 0.5%/99.5% duty.
At 0.5%, the short pulse lasts only about 0.55 ADC sample intervals; the
discrete input can miss pulses, and the fixed hysteresis adds another limit.
This is not a model of Local Parks or its analog input filtering. Lowering
hysteresis indiscriminately would trade this limitation for more noise-induced
crossings; it is not part of the present change. Use a basic waveform for tuning
and eventually calibration when the complex output does not track reliably.

Qualification: 57 regression tests plus two separate live-step tests pass;
the two raw-counter harmonic cases remain expected failures. Full r5 standard
build passes CPU 65.96/60 MHz, pixel 89.15/74.25, serializer 391.39/371.33,
audio 71.78/12.29. Resources: 14,168 logic cells (+61), 7,226 FF (-2),
26 EBR and 7 DSP (unchanged from the verifier build). Only TUNER instantiates
this peripheral in production sources; no other bitstream was edited.
Archive SHA256:
`6a93a499ca0df6a6a4d36e1bb89b550420a707ede08da48a3826dc9d634aa5e2`.
Built but NOT flashed: the user powered down the rack. Hardware qualification
of this settling change is pending. The installed verifier build remains the
previous `963d9157...` archive. Future calibration still needs an explicit
settling/confidence policy; this coefficient change does not provide one.

## Four-channel acquisition milestone

The DC-settling build above was subsequently flashed and the user confirmed
responsive tuning, including a DC-offset test. Production now instantiates four
independent crossing/DC/level lanes. The foreground read-bank selector does not
reset acquisition. One harmonic verifier rotates through the channels, eight UI
frames per visit (nominally 160 ms; 640 ms round trip). It discards history on
each switch. Complex-waveform corrections therefore have higher latency than
basic tuning; cached corrections remain scoped to channel and matching lag.

The independent-lane regression drives four different periods and amplitudes,
checks each RMS and period, changes read/verification selectors without resetting
measurements, and silences only one channel while the other three keep updating.
The unchanged single-lane detector/verifier suite passes 34 tests. Display and
multichannel tests pass 16 tests; cached-scene host tests pass four tests.
The final instrument-scene, shared-renderer and atomic-frame suite passes
another 17 tests. The initial display run exposed three legacy brightness
expectations; retaining legacy intensity while coloring production sprites
resolved them, and the complete display suite was rerun successfully.

The standard r5 build uses 17,269 logic cells (71%), 8,411 FF, 26 EBR and 10 DSP.
Final timing passes CPU 68.59/60 MHz, pixel 88.06/74.25 MHz, serializer
412.54/371.33 MHz and audio 70.10/12.29 MHz. This is not an unlimited resource
budget: future calibration/quantization should reuse the measurement lanes,
CPU and renderer rather than add independent instrument pipelines.
Archive SHA256: `753f7074ab93b23fec594a94bbee80d21cb03cd393bac86f9070e48295676935`.
Simultaneous four-channel hardware behavior remains to be tested.
This archive was flashed successfully to standard slot 1 under the shared
hardware lock (`Refresh: DONE`, exit 0); saved options were not overwritten.
The user subsequently confirmed this four-channel build works perfectly.
