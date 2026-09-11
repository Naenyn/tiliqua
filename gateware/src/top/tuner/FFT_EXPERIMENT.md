# FFT / spectral experiment checkpoint

Branch `codex/tuner-fft-experiment`, branched independently from working
`ebdf7a28`. No production files changed; no replacement detector flashed.
YIN remains at `2865ac0b`; NSDF comparison code at `5e9b81ff`.

## Implemented

- `tests/spectral_reference.py`: independent spectral harmonic-fit experiment.
  Hann window, 4x-or-greater power-of-two padding, log-magnitude quadratic peaks,
  up to 24 peaks, candidate fundamentals from peak/1..8, harmonic assignments
  through 64, weighted frequency fit, coprime harmonic check, energy-coverage
  qualification. These are fixed engineering heuristics, not a probability.
- `tests/compare_detectors.py`: the same 254 signed-16-bit 192-kHz signals passed
  to spectral, NSDF, and full-rate YIN steps 2–5; exact shared corpus from YIN
  branch above. This excludes YIN's multirate improvements and the production
  firmware qualification chain: it must NOT be called a full system ranking.
- `tests/detector_transition_probe.py`: 100 identical phase-continuous step
  frames. Every candidate reacquires within 10 cents after full window replacement.
- `tests/fft_precision_probe.py`: actual existing FFT RTL, not a quantized ideal
  model; 12 cases including quiet signals, optional block normalization and
  output backpressure. It verifies complex output error <4 LSB and records cycles.
- `tests/synthesize_fft_candidate.py`: existing `tiliqua.dsp.fft.FFT`, unchanged,
  measured standalone. Two new live recordings retained as repeatable fixtures.

Sources for the spectral ideas (not a claim to reproduce their full algorithms):
Julius O. Smith, *Spectral Audio Signal Processing*, quadratic spectral peak
interpolation and fundamental estimation from spectral peaks:
https://www.dsprelated.com/freebooks/sasp/Quadratic_Interpolation_Spectral_Peaks.html
https://www.dsprelated.com/freebooks/sasp/Fundamental_Frequency_Estimation_Spectral.html

## Numerical results, not general accuracy guarantees

Worst absolute cents among qualified cases in each category:

| Category | Spectral | NSDF | Full-rate YIN |
|---|---:|---:|---:|
| Sine (153 cases) | 9.791 | 1.080 | 1.082 |
| Strong second (9) | 5.617 | 4.286 | 4.289 |
| Missing fundamental (9) | 5.957 | 8.228 | 8.230 |
| Noisy sine (9) | 3.367 | 2.464 | 84.369 |
| Bandlimited saw (9) | 0.135 | 2.710 | 2.712 |
| Bandlimited square (9) | 0.079 | 1.069 | 1.070 |
| Bandlimited 1% pulse (9) | 0.019 | 3.878 | 3.874 |

All reject the single noise and silence cases. Directly sampled unbandlimited
waveforms produce four spectral and five NSDF >50-cent failures; full-rate YIN
has those five plus one noisy-sine failure. In particular, the 997.1-Hz 1% pulse
produces an octave error in both time-domain references but not this spectral
candidate. Physical narrow-pulse recordings are needed before concluding that
this represents a useful improvement with the real ADC/oscillator chain.

With a 100.02-ms identical frame, stable <10-cent step recovery (sampled every
5 ms) was:

| Step Hz | Spectral ms | NSDF ms | YIN ms |
|---|---:|---:|---:|
| 110.7 -> 440.3 | 70 | 85 | 100 |
| 440.3 -> 110.7 | 55 | 20 | 100 |
| 997.1 -> 7678.1 | 75 | 75 | 90 |
| 7678.1 -> 997.1 | 75 | 100 | 100 |

This is an offline observation, not a scheduling/latency guarantee. Refusals and
intermediate estimates remain in the JSONL output. Neither acquisition time nor
windows were tuned independently per candidate.

Three real captures (sine, saw-like rich wave, previous alternating-cycle failure)
produce spectral estimates 1064.226, 1063.976 and 7675.967 Hz. All qualify, as do
the corresponding NSDF and YIN estimates. They have no independent ground truth.
The 2048-sample native captures support the restricted 200–20kHz search only.

## Actual FPGA cost and precision

Existing FFT, SQ(1,15), synthesized with Yosys 0.68+48:

| Transform | LUT4 | FF | DSP | EBR |
|---|---:|---:|---:|---:|
| 1024 | 665 | 578 | 4 | 8 |
| 2048 | 678 | 602 | 4 | 16 |

1024 routed on 25k ECP5 speed 6 with final reported 79.83 MHz, passing 60 MHz.
These are isolated numbers. Current baseline synthesis has 33/56 EBR blocks;
adding a 1024 transform leaves 15, a 2048 transform leaves seven, BEFORE adding
filters, histories, spectra or scheduling. Replacements could reclaim some
baseline memory, but that has not been designed or counted. Larger spectral
analysis needs either multirate analysis, external-memory architecture, or a
different precision/refinement strategy, not just a bigger on-chip FFT.

Important mismatch: the desktop full-range spectral reference zero-pads 19204
samples to 131072 points. Its results are NOT achievable by simply installing
the 1024-point core. The latter is only a reusable kernel feasibility measurement.

RTL probe used 65886 clocks per 1024 transform including load, output and stalls,
about 1.10 ms at 60 MHz. Two bands x four channels x 20 updates/s would consume
10.54 million such clocks for forward transforms alone. Autocorrelation also
needs inverse transforms; filtering and all other work remain additional.

At 20.37 Hz / 6 kHz sample rate and amplitude 72 ADC codes, unscaled FFT peak
measurement adds 18.62 cents of fixed-point error. Scaling the quantized block
left by seven bits before windowing reduces that contribution to 0.069 cents.
This is inexpensive in concept but requires block peak detection/storage.
The remaining total 1.636-cent error is largely the short spectrum's interpolation
bias. Across the four tested quiet frequencies normalization kept additional
fixed-point error below 0.07 cents. This does not test inverse-transform or
power-spectrum precision, clipping robustness, filtering, or a complete detector.

## Next hardware evidence

September 11 narrow-pulse follow-up completed: two further 2048-sample native
captures retained as `tuner-live-pulse-pair-sine-1063.json` and
`tuner-live-narrow-pulse-1063.json`. Captured pulse width is approximately 71.6 us,
7.61% duty, measured at the midpoint of the 1st/99th-percentile signal levels and
using median interpolated edge intervals. This includes the acquisition chain's
bandwidth effects; it is not an independent oscilloscope measurement.

At identical 200–20000 Hz search bounds, sine/pulse estimates respectively:

| Method | Sine Hz | Pulse Hz |
|---|---:|---:|
| Spectral | 1063.345 | 1063.481 |
| NSDF | 1063.382 | 1063.676 |
| YIN steps 2–5 | 1063.439 | 1063.285 |
| Recorded raw baseline | 1062.909 | 1063.712 |

All candidates qualify both recordings with no octave error. The baseline header
records factor 1 on both. This is a useful passing real-waveform case, not proof
of absolute accuracy or continuous tracking stability. The pulse is narrower
than the earlier saw-like capture but not the 1% synthetic failure case; it does
not establish a winner. Spectral processing identifies 22 matched peaks on it.

Use existing TUNER -> FOCUS 0 -> CAPTURE; no new firmware required. Record a
narrow pulse near 1 kHz, ideally alongside the same oscillator's sine/basic
waveform without moving its pitch controls. Keep output settings untouched.
The goal is to test real small-duty-cycle behavior, not obtain a different
calibration curve. Serial captures are sufficient; no photographs needed.

Do not choose or deploy a winner yet. A small FFT remains plausible as an
optional shared spectral feature, not an earned replacement for the working
tuner. Tuner/calibrator/independent multichannel quantizer capacity takes priority.

## Reproduction

Use the project's Python environment (NumPy/SciPy/Amaranth/pytest) and `PYTHONPATH=src`
for RTL probes. Commands below run from this branch's `gateware` directory.

```
python -m pytest -q tests/test_spectral_reference.py
python tests/compare_detectors.py --yin-tests YIN_GATEWARE/tests --nsdf-tests NSDF_GATEWARE/tests
python tests/detector_transition_probe.py --yin-tests YIN_GATEWARE/tests --nsdf-tests NSDF_GATEWARE/tests
python tests/fft_precision_probe.py
python tests/synthesize_fft_candidate.py /tmp/fft-check --size 1024 --yosys /path/to/yosys
```

Development reports are `/tmp/tuner-all-detectors.jsonl`,
`/tmp/tuner-detector-transitions.jsonl`, `/tmp/tuner-fft-precision-normalized.jsonl`,
`/tmp/tuner-fft-1024-synth.log`, `/tmp/tuner-fft-1024-timing.log`, and
`/tmp/tuner-fft-2048-synth.log`. Sources and fixtures are committed; reports can
be regenerated. Known low-sine and aliasing failures are strict expected failures.
