# NSDF hardware feasibility checkpoint

September 11, 2026. Experimental branch only; production gateware and firmware
are unchanged. This is **not a full SoC fit or a four-channel integration proof**.
It extends the prior desktop comparison by implementing the entire NSDF score
calculation (correlation, overlap energies, and division) in RTL. Filtering,
acquisition, frame centering, host peak selection, and scheduling remain outside
that RTL engine and are accounted for separately below.

## Decision

Follow-up resource audit: `RESOURCE_HEADROOM.md` attributes the current netlist,
tests a shared-history schedule, and documents the CPU RAM sizing cliff. Its
44-block eventual allocation is conditional, not a replacement for a full build.

Prioritize **direct shared NSDF**, not FFT-based NSDF, for integration work.
The FFT route can be faster but is less attractive in memory and numerical
precision. Do not add a spectrum display as a dependency of pitch detection.
Retain the current detector until the replacement passes integration and live
tracking tests; the experiments do not justify removing it yet.

## Measured arithmetic and resources

Actual existing FFT RTL ran forward and inverse transforms, with explicit
fixed-point power-spectrum quantization between them. No Hann window was used:
NSDF requires linear autocorrelation, so frames were zero-padded sufficiently
to prevent circular wraparound. Power scaling and energy normalization were
host models, not synthesized logic. Inverse power scaling keeps the inverse
transform in range. These measurements include two transforms, but the resource
figures are for one reused transform core, excluding its surrounding circuitry.

Ten probes per configuration: 20.37, 440.3, 7678.1, and 19953 Hz sines at two
levels; the real narrow pulse; and the attenuated modulated Blade below the
high bank's range. The last case is correctly rejected by the tested NSDF paths.

| Path | Maximum added frequency error in probe | EBR | DSP | LUT4 |
|---|---:|---:|---:|---:|
| FFT Q15, 2048 low / 1024 high | 8.362 cents | 16 for 2048 core | 4 | 678 |
| FFT Q15, both 1024 | 3.819 cents | 8 | 4 | 665 |
| FFT Q17, both 1024 | 1.480 cents | 11 | 4 | 651 |
| Direct Q20 NSDF score engine | 0.005561 cents | 2 | 3 | 537 |

"Added" compares against the floating-point reference selector on the same
preprocessed frame, not against independently measured pitch. In particular,
the short-window reference itself reports about 19940.96 Hz for the generated
19953-Hz sine: approximately -1.04 cents intrinsic interpolation bias remains.
Good fixed-point agreement does not eliminate that algorithmic error.

The direct engine has capacity 674 samples and lag 321, runtime frame length
and lag limit, a frozen frame, three pipelined signed 16-bit products, exact
wide correlation/energy accumulators, and a restoring divider yielding signed
Q20 scores. Samples must be centered and scaled into signed 16-bit range before
loading. The probe rounds the frame mean and halves only if needed to avoid
overflow. Peak selection is the unchanged host NSDF reference, not RTL.

Every emitted RTL score is checked against exact integer dot products and
division. Tests cover random inputs, signed rails, constant input, silence,
sinusoids, output stalls, runtime limits, and cancellation/reuse. A constant
frame produces NSDF=1; the selector must still reject it because it has no
nonzero-lag positive lobe following the zero-lag lobe. Mean removal and silence
handling cannot be omitted at integration.

Synthesis: 537 LUT4, 472 FF, 2 EBR, 3 DSP. Isolated ECP5-25k, CABGA256, speed 6
place-and-route: **69.37 MHz**, passing the 60-MHz constraint. This is not full
bitstream timing closure. No pin assignments here represent a deployable board.

## Time budget

Same configurable score engine, no output backpressure:

| Bank | Frame / sample rate | Last lag | Measured cycles per frame |
|---|---|---:|---:|
| Low | 604 / 6 kHz | 301 | 157493 |
| High | 674 / 192 kHz | 321 | 187243 |

Counts include calculation, normalization, score handshakes and finish, but not
sample loading, host selection, or waiting for new samples. Four channels,
both banks, 20 analyses/channel/second consume 27,578,880 cycles/second, or
45.965% of a dedicated 60-MHz score engine. Reading frames adds about 102,240
sample transfers/second before bus overhead. At 40 analyses/channel/second the
core alone approaches 92% duty; do not promise that rate with comfortable margin.

Low frames represent 100.67 ms of audio; high frames 3.51 ms. A 20-Hz analysis
cadence is not a 50-ms guarantee of low-note acquisition after a pitch change.
The display can refresh independently of the analysis cadence. Filter settling,
bank selection, clipping and confidence handling still require transition tests.

## Filtering and memory: planning estimates, not measured full hardware

`nsdf_filter_budget.py` specifies a candidate 192-to-6-kHz decimation filter:
769 taps, Kaiser 8.6, 2250-Hz cutoff, signed 18-bit Q17 coefficients. Quantized
response is within about 0.001 dB through 1500 Hz and below -74.39 dB from
3000 Hz upward. Group delay is 2 ms. Its absolute coefficient sum is about 1.65,
so full-scale transients require a wide accumulator and explicit saturation.
Frequency response alone does not establish the fixed-point streaming behavior.

A decimating implementation needs 18,456,000 products/second for four channels.
One separate pipelined DSP at 60 MHz is a plausible allocation (30.76% product
duty before overhead), not a measured filter implementation. It runs alongside
the three-DSP score engine; these duties are not competing uses of one engine.

Conservative memory allocation, without credit for removing existing logic:

| Item | EBR |
|---|---:|
| Existing bitstream | 33 |
| Measured score engine with frozen frame | 2 |
| Filter coefficients | 1 |
| Four filter input histories | 4 |
| Separate low and high histories for four channels | 8 |
| Double-buffered score handoff | 2 |
| **Planned total / device** | **50 / 56** |

DSP allocation would be 10 existing + 3 score + 1 filter = 14 / 28. Glue logic,
CPU cost, bus contention, and routing remain unmeasured. Six spare EBR is not
generous enough to treat future features as free. Investigate reusing each
filter's 769-sample native input history for the 674-sample high-bank snapshot:
that could remove four duplicate EBR and reduce the estimate to 46 / 56. Prove
read arbitration and snapshot consistency before crediting those savings.
The low-rate histories and frozen processing frame must remain independent.

## Required gates before a hardware trial

### End-to-end numerical model follow-up

`nsdf_banked_probe.py` now models the quantized FIR, rounded/saturated decimation,
integer frame centering, exact Q20 score arithmetic validated against the RTL,
reference peak selection, amplitude gates, and provisional bank arbitration.
The corpus is generated as 23000 genuine consecutive samples per case so the
filter has prehistory. This does not turn the 10.67-ms hardware recordings into
low-frequency test material. FIR streaming and CPU arithmetic are still not RTL.

The initial policy preferred the high bank only above 1200 Hz. That gave up to
5.430 cents sine error around 1037 Hz in the low bank: too few low-rate samples
per period for simple parabolic interpolation. Preferring a qualified high bank
throughout its >=600-Hz range reduced worst sine error to 1.147 cents.

An optional `--refine` extension then checks an already-computed NSDF peak near
up to eight times the selected lag. Its interpolated lag is divided by that
integer multiple. It must retain adequate clarity, stay in the bank range, and
agree within 10 cents with the original estimate; otherwise the original is
retained. No expected note, calibration voltage, prior pitch, or oscillator
setting is used. This is **our engineering extension, not the original paper's
algorithm**. It needs no additional correlation terms, but host selection cost
and continuous tracking behavior still need measurement.

254-case corpus, with the same cases but longer filter prehistory than the
earlier unbanked experiment. Worst absolute cents against generated frequency:

| Category | Cases | Native-priority model | With guarded refinement |
|---|---:|---:|---:|
| Sine, including phase/level/DC cases | 153 | 1.147 | 0.203 |
| Band-limited saw | 9 | 3.657 | 0.073 |
| Band-limited square | 9 | 2.991 | 0.068 |
| Band-limited 1% pulse | 9 | 6.197 | 0.110 |
| Strong second harmonic | 9 | 4.390 | 0.075 |
| Missing fundamental | 9 | 8.154 | 0.093 |
| Noisy sine | 9 | 0.836 | 0.836 |

Noise-only and silence are rejected. Six deliberately unbandlimited/aliased
saw, square and thin-pulse cases still give errors >50 cents. Two of these are
false low-bank results from a high-frequency 1% pulse. Retain that limitation;
the refinement is neither an octave-error remedy nor proof of reliable pitch
for arbitrary spectra. Real narrow-pulse results remain encouraging, but these
synthetic outcomes do not establish absolute live calibration accuracy.

Additional regression tests cover low/high bank boundaries, quiet/DC-offset
sines, input immutability, rejection, filter response and the known aliased
pulse expected failure. Combined focused suite: **50 passed, 5 expected failures**.
Reports: `/tmp/tuner-nsdf-banked-native-priority.jsonl` and
`/tmp/tuner-nsdf-banked-refined.jsonl`.

### Integration gates

1. Implement/test filtering, centering/saturation, history sharing and snapshots.
2. Test bank arbitration across overlapping ranges and out-of-range fundamentals;
   include transitions, narrow pulses, low levels, noise and modulation.
3. Measure host selection/interpolation and shared four-channel scheduling.
4. Validate the guarded longer-lag refinement on continuous transitions and
   physical signals; do not force results to an expected note/calibration step.
5. Build the complete bitstream, compare resource/timing reports, then flash for
   a focused hardware comparison. Do not claim integrated feasibility earlier.

## Reproduction

From this branch's `gateware`, use the project Python environment:

```
python -m pytest -q tests/test_nsdf_direct_rtl.py tests/test_spectral_reference.py
python tests/nsdf_direct_probe.py --nsdf-tests NSDF_GATEWARE/tests
PYTHONPATH=src python tests/nsdf_fft_precision_probe.py --nsdf-tests NSDF_GATEWARE/tests --compact
PYTHONPATH=src python tests/nsdf_fft_precision_probe.py --nsdf-tests NSDF_GATEWARE/tests --compact --fractional-bits 17
python tests/nsdf_filter_budget.py
python tests/nsdf_banked_probe.py --yin-tests YIN_GATEWARE/tests --nsdf-tests NSDF_GATEWARE/tests --refine
TUNER_NSDF_TESTS=NSDF_GATEWARE/tests python -m pytest -q tests/test_nsdf_banked_probe.py tests/test_nsdf_direct_rtl.py tests/test_spectral_reference.py
python tests/synthesize_nsdf_direct.py /tmp/nsdf-check --yosys /path/to/yosys
```

Development reports: `/tmp/tuner-nsdf-direct-shared-probe.jsonl`,
`/tmp/tuner-nsdf-direct-shared-synth.log`,
`/tmp/tuner-nsdf-direct-shared-timing.log`,
`/tmp/tuner-nsdf-fft-roundtrip.jsonl`,
`/tmp/tuner-nsdf-fft-roundtrip-compact15.jsonl`, and
`/tmp/tuner-nsdf-fft-roundtrip-compact17.jsonl`.
