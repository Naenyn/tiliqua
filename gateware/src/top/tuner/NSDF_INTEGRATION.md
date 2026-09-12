# NSDF integration trial

Branch: `codex/tuner-nsdf-integration`, based on `739cc7b4`. This is an opt-in
parallel hardware diagnostic, **not yet a replacement for the working tuner**.
The baseline display, detector, calibrator and PLAY/quantizer remain authoritative.
The experiment has no connection to output-voltage ownership or profile storage.

## Implemented

- Four live signed-16 input histories share one 4096-word memory.
- One pipelined multiplier performs the 769-tap Q17 FIR for four 192-to-6-kHz
  decimated channels. Saturation is explicit; clipped low-bank samples retain
  a flag in their history.
- Low-frequency history is a separate 4096 x 17 memory. Both histories publish
  their head only after the entire four-channel group has been written.
- Bounded two-pass snapshots compute a nearest-even integer mean and extrema,
  then stream a centered frame directly into score-engine RAM. A single-bit
  right shift protects signed-16 range when necessary. No CPU frame buffer.
- A sequence-age guard discards snapshots before overwrite, reserving one
  unpublished four-channel write batch. Cancellation discards partial frames.
- One shared direct NSDF engine handles 604/301 low-bank and 674/321 native-bank
  frame/last-lag configurations. Centered frame energy is exported without an
  additional multiplier.
- A diagnostic CSR holds one completed score frame until the next request.
  Firmware exports it non-blockingly over UART, alternating banks and channels.
  Packet metadata identifies rate, length, channel, sequence, energy, scaling
  and clipping. Normal capture/status UART output is suppressed in this build
  to prevent interleaved records.

`TILIQUA_TUNER_NSDF=1` enables both the gateware peripheral and matching firmware
through its build script. Without it, the existing tuner remains unchanged.
Diagnostic identity is now `0x4e534402` (source-moment registers added);
earlier score-only captures used `0x4e534401`. A mismatch is reported rather
than ignored.

## Validation so far

84 focused tests pass; five existing explicit expected failures remain in the
earlier spectral/aliased-waveform experiments. They are not new integration
failures. Tests include:

- Exact full-size FIR comparisons, all four channels, ring wrap, simultaneous
  native reads, saturation, stalled consumption and explicit overrun reporting.
- Positive/negative tie rounding, extreme DC offsets, output backpressure,
  read arbitration, overwrite/cancel/reuse, and insufficient-history errors.
- Continuous four-channel acquisition/filtering while a native snapshot feeds
  the score engine; every score agrees with exact integer reference arithmetic.
- Signed low-bank history and its complete score sequence, plus frame energy.
- Actual byte-wide CSR command writes and signed frozen-score readback.
- Strict serial framing and host selection/refinement for low through near-20-kHz
  synthesized sines; malformed and truncated packets are rejected.

The combined two-bank frontend before the final snapshot input register used
11 EBR, four DSP, 1151 LUT4 and 1156 FF in isolated synthesis. Its routed
out-of-context result was 64.30 MHz at a 60-MHz target. That is not a whole-SoC
timing claim. The first full SoC build used 45/56 EBR and 14/28 DSP and passed
final routing at 61.45 MHz main / 88.72 MHz pixel / 411.18 MHz serializer.
Because main-clock margin was small, the RAM-to-snapshot comparison path was
subsequently pipelined. **Final full-chip routing passes: 66.54 MHz main at
60 MHz, 86.24 MHz pixel at 74.25 MHz, 459.98 MHz serializer at 371.33 MHz, and
68.88 MHz audio clock at 49.152 MHz.** Seed 15, R5, normal 720p display.
Allocation remains 45/56 EBR and 14/28 DSP, including the baseline detector.

CPU RAM remains 32 KiB. The diagnostic keeps a 192-byte text buffer, not a
sample/score frame in CPU RAM. Static data is 1632 bytes and BSS eight bytes;
the linker's `.stack` section reserves the remaining RAM. This is **not** a
measured stack high-water result or a four-profile quantizer proof.

## Reproduction

From `gateware`, with the configured Python, Rust and FPGA toolchains:

```sh
PYTHONPATH=src TUNER_NSDF_TESTS=/path/to/nsdf-reference/gateware/tests python -m pytest -q tests/test_nsdf_acquisition.py tests/test_nsdf_snapshot.py tests/test_nsdf_frontend.py tests/test_nsdf_streaming_integration.py tests/test_nsdf_peripheral.py tests/test_nsdf_direct_rtl.py tests/test_nsdf_banked_probe.py tests/test_nsdf_shared_history.py tests/test_nsdf_trace_analysis.py tests/test_spectral_reference.py
PYTHONPATH=src TILIQUA_TUNER_NSDF=1 python src/top/tuner/top.py build --hw r5
python tests/nsdf_trace_analysis.py /path/to/serial.log
```

Archive name remains TUNER; normal display is 1280x720p60, audio 192 kHz.
Flash only an archive whose final routed clocks all pass; do not erase options.

## Hardware trial and remaining gates

First physical trial, September 12, 2026: Local Parks sine into IN 0, set by the
user to approximately 880 Hz. Build `d637e584`. Complete serial frames report:

| Bank | Frequency | Clarity | Qualified / clipped |
|---|---:|---:|---|
| Native, first capture | 882.016 Hz | 0.999940 | yes / no |
| Native, repeat | 880.958 Hz | 0.999946 | yes / no |
| Low, repeat session | 881.408 Hz | 0.985023 | yes / no |

No diagnostic acquisition errors were reported in these captures. A near-silent IN 3
low-bank frame was unqualified (0.091 RMS counts). Complete tone
frames and that idle frame are retained in
`tests/fixtures/nsdf-local-parks-sine-880.json`, with a parser/qualification
regression test. Partial packets at connection boundaries were excluded.
The raw session logs are `/tmp/tuner-nsdf-localparks-880-serial.log` and
`/tmp/tuner-nsdf-localparks-880-repeat.log`.

These are successful basic capture/qualification results, **not a sub-cent
accuracy or stability claim**: there is no independent frequency reference,
and the banks were captured seconds apart. Repeated native readings differ by
about 1.06 Hz; this export alone cannot separate source variation from estimator
variation. Next physical case: a thin pulse at the same oscillator setting.

Later complete frames from the same session expose a qualification concern:
IN 1 native bank reports 15782.783 Hz, clarity 0.854231, at only 7.861 RMS
counts, and passes the current host gate. The user subsequently confirmed IN 1
carries the quantizer-test LFO (rate/waveform not measured), not an empty jack.
The low-bank frame has 114.141 RMS counts and no candidate. Other-channel records are retained in
`tests/fixtures/nsdf-local-parks-880-other-channel.json`. Do not claim all quiet
inputs are rejected or raise the amplitude floor without checking the signal
and preserving the previously demonstrated low-level sensitivity.

The offline bank model already compares native-frame RMS against 10% of
long-window source RMS. That guard is not present in this diagnostic decoder.
The captured low/native energy contrast is consistent with why it is needed,
but is not a validation: these exports are asynchronous and low-bank RMS is
not the model's source RMS. Obtain aligned source-energy metadata and test LFO
phases, transitions and quiet audio before enabling production arbitration.
Keep the LFO patched during subsequent trials as an out-of-band rejection case.

Second physical case: user switched Local Parks to pulse, with IN 1 LFO still
connected. Pulse duty cycle was not measured. Three-minute serial capture
`/tmp/tuner-nsdf-localparks-pulse-serial.log` contains no diagnostic acquisition
errors; complete IN 0/1 frames are preserved in
`tests/fixtures/nsdf-local-parks-pulse-880.json`.

- Native: 884.711892 Hz, clarity 0.928793, RMS 3109.699 counts.
- Low: 876.344458 Hz, clarity 0.970210, RMS 1067.079 counts.
- Both qualify, neither clips/scales. IN 1 candidates in this capture do not
  qualify; this does not erase the earlier LFO false-candidate observation.
- The roughly 16.45-cent cross-bank difference is NOT an accuracy pass. Frames
  are asynchronous, and no independent reference establishes pulse frequency.
  The low-bank longer-lag peaks give approximately 881.4–881.9 Hz at large
  multiples, demonstrating sensitivity to which peak is interpolated within
  this same frame. Current refinement tries only multiple 8 here and does not
  accept it; it does not search other strong multiples. The native frame has
  only about three cycles and no second-period peak within its lag limit.
  Investigate refinement/longer-baseline estimation offline before claiming
  precision on narrow pulses or expanding hardware resources. Do not widen
  acceptance thresholds merely to make this capture pass.

First compare exported estimates on a steady sine, then the previously captured
thin pulse, across low/mid/high pitches. Confirm no audio drops, metadata faults,
UI stalls or output behavior changes. The display still shows baseline pitch:
candidate estimates are decoded on the host for this trial.

Exports deliberately run much slower than the planned 20 analyses/channel/s.
This isolates numerical/capture correctness; it is **not a throughput proof**.
The two banks are exported at different times and reported separately, not
silently fused into one estimate. Guarded longer-lag refinement remains our
engineering extension, distinct from the paper's key-maxima selector.

Still required before replacement: target-CPU selector/refinement benchmarks,
bounded four-channel scheduling and double-buffered score handoff, fresh-frame
bank arbitration/transition tests, stack high-water checks, and physical
accuracy/latency qualification alongside calibration and quantized output.
Retire the old verifier only after that. No spectrum-display dependency and no
CPU RAM increase have been introduced.

## CPU selector diagnostic and pulse follow-up

The guarded fallback searches multiples 8 down to 2 (or the maximum available),
stopping at the first acceptable existing peak. The same confidence, ±1 sample
search, ten-cent agreement and frequency-range limits apply; there is no extra
correlation work. Legacy host `decode` remains the single-multiple baseline;
`select(..., fallback=True)` and `fw/src/nsdf_select.rs` implement the extension.
The captured low-bank pulse changes from 876.344458 to 880.807541 Hz. This does
not establish its true frequency or resolve the native-bank discrepancy.

`tests/nsdf_refinement_probe.py` A/B compares 254 synthetic cases (including
quiet/DC-offset signals, noise, harmonic and intentionally aliased waveforms).
All selected results remain unchanged. Known aliased pulse/saw/square octave
errors remain; no claim is made to have solved these. Comparison log:
`/tmp/tuner-nsdf-refinement-comparison.jsonl`.
An additional sliding-window comparison of all eleven older 2048-sample real
captures found no consistent improvement from increasing the native lag limit
321 to 511. No gateware dimension was changed on that evidence.

The allocation-free Rust selector performs two score-memory scans plus at most
63 extra reads (maximum 707 native / 667 low reads). It uses scalar state, not
a score-sized array, logs, powers, or heap allocations. Host-compiled Rust is
compared with the double-precision model on real score captures, sliding real
waveform windows, sine phase/frequency sweeps, and noise/constant frames;
frequency differences must be below 0.005 cents with matching qualification.
This is numerical parity, not hardware tuning accuracy or a CPU-cycle proof.

The opt-in diagnostic emits `NSDF CPU` before each corresponding score frame:
`ch`, `low`, `seq`, `mhz` (milli-Hz), `raw` (unrefined milli-Hz), `ppm`
(clarity × 1,000,000), `ok` (independent bank gate), `cycles`, and `reads`.
Cycles use the existing free-running 60-MHz timer, with interrupts enabled;
measurements include intervening ISR time. No unavailable `mcycle` instruction
is used. Scores stay frozen throughout selection and export. Baseline tuning,
calibration and outputs remain authoritative; source-energy bank arbitration
is still NOT enabled. `ok` is not an accepted production pitch.

Firmware-only build passes with unchanged `.data` 1632 bytes and `.bss` 8 bytes,
zero heap and 32-KiB CPU RAM. Reserved stack space is not measured stack usage.
FPGA bitstream SHA-256 remains
`8646c2fbba1a503f20e54bbddce8ef13e187378f41c6220c9860d461dc2f9b01`;
the prior full-route timing/resource report still applies. Next hardware gate:
collect CPU estimates/cycles on pulse plus LFO while checking encoder/UI and
quantized playback responsiveness, before attempting continuous scheduling.

Physical CPU trial of `37e76401`: Local Parks pulse IN 0 and quantizer-test LFO
IN 1. Complete matched CPU/score records are saved in
`tests/fixtures/nsdf-cpu-pulse-lfo.json`; raw log is
`/tmp/tuner-nsdf-cpu-pulse-lfo.log`. Reports match the fallback host model,
including bank qualification, within f32 plus milli-Hz serial truncation error.
No acquisition errors appeared. IN 0: native 881.838 Hz / 13.303 ms, low
881.122 Hz / 17.289 ms. IN 1 candidates in this capture were rejected. This
does not resolve the earlier false-candidate concern or prove absolute accuracy.

**CPU performance gate FAILED.** Other frames took approximately 7–70 ms;
even this pulse alone spends about 30.6 ms across two banks. That is not
compatible with four-channel, two-bank analysis every 50 ms. Measurements are
elapsed timer cycles including interrupts, not isolated instruction costs.
Do not enable production scheduling or replace baseline pitch with this path.
Next optimization work must separate score-register access, float arithmetic,
and interrupt costs; skip sub-floor frames before scanning; investigate integer
peak screening and bounded score reuse before allocating RAM or expanding FPGA
logic. Keep calibration/quantizer ISR timing independent. The diagnostic does
not establish absence of audible glitches or full UI responsiveness.

Next firmware-only diagnostic keeps score scans in integer Q20 until the
strongest raw peak in a positive lobe has been chosen. It interpolates only
that peak, rather than converting every score and interpolating intermediate
contenders. Lag-range comparisons replace per-candidate frequency divisions.
These changes preserve model outputs in host-compiled parity tests, including
the real captures and search-range boundaries. Quiet/clipped frame rejection
now happens before any score reads, using exactly the prior >2-count RMS gate
(with proper scaling compensation). It does not raise the audio threshold.

An extra `NSDF IO` line, keyed by the same channel/bank/sequence, reports the
elapsed cycles, read count and wrapping checksum (`sum`, hex) for a separate
full score-memory sweep without peak calculations. This diagnostic overhead is
not included in `NSDF CPU cycles`, does not allocate a frame buffer, and is not
intended for production. Interrupts remain enabled in both measurements; do
not subtract the two timings as if they were isolated CPU instruction costs.
No new FPGA build or memory allocation is needed. The performance gate remains
failed until a new on-device measurement demonstrates adequate margin.

Physical follow-up of `6c9fddd7`, same pulse/LFO patch: the matched CPU, IO and
score records are in `tests/fixtures/nsdf-cpu-integer-screen.json`. CPU estimates
match the model; all IO checksums match the exported score words. No diagnostic
acquisition errors appeared. Measured elapsed times:

| Input/bank | Selection | Independent IO sweep | Result |
|---|---:|---:|---|
| IN 0 native | 1.226 ms | 0.260 ms | 882.454 Hz, qualified |
| IN 0 low | 10.419 ms | 0.244 ms | 881.060 Hz, qualified |
| IN 1 native | 2.800 ms | 0.262 ms | rejected |
| IN 1 low | 0.388 ms | 0.244 ms | no candidate |
| IN 2/3, both | 0.0045–0.0058 ms | 0.244–0.260 ms | gated before score reads |

The pulse's combined 11.645 ms remains too costly: four comparable active
inputs would spend about 46.6 ms of each 50-ms update period on selection alone.
Do not promote this implementation or interpret these sparse asynchronous
measurements as a four-channel throughput/latency qualification. Score-register
access is not the dominant observed cost; remaining interpolation/selection
arithmetic is the next optimization target. The raw log is
`/tmp/tuner-nsdf-int-screen-live.log`.

Next firmware diagnostic uses Q20 fixed-point lag and NSDF height throughout
selection and interpolation, with 64-bit intermediates for bounded products
and division. Final estimates alone convert to float for the existing report.
The first Q16-lag prototype missed the existing clarity-parity tolerance, so it
was replaced with Q20 rather than relaxing the tests. Model parity checks
(including range boundaries and real captures) and overflow-checked host Rust
pass. The early energy gate and confidence/octave guards remain unchanged.
Firmware build passes; `.data`/`.bss` remain 1632/8 bytes, with no new frame
buffer, heap or FPGA change. On-device timing for this fixed-point version is
still required. The performance gate remains open.

Physical fixed-point trial, `b54b9a34`, same patch: native pulse 881.621 Hz in
0.903 ms, low-bank pulse 881.024 Hz in 2.553 ms, combined 3.456 ms. IN 1 LFO
was rejected (2.534 ms native / 0.402 ms low). Quiet inputs were gated in
approximately 5–7 microseconds. Independent IO sweeps took 0.274–0.292 ms.
All complete CPU/IO/score triples agree on metadata, checksum, estimates and
qualification. No diagnostic acquisition errors appeared. Raw capture:
`/tmp/tuner-nsdf-fixedpoint-live.log`; retained fixture:
`tests/fixtures/nsdf-cpu-fixedpoint.json`.

This makes four comparable pulse inputs about 13.8 ms of a 50-ms update period
for CPU selection (roughly 28%), not a measured four-input throughput or worst
case. Both banks are asynchronous; this remains an algorithm-parity and timing
trial rather than independent pitch accuracy proof. Broader frequencies,
four-channel scheduling, source-energy arbitration, stack high-water and
calibration/quantizer coexistence still require qualification.

`tests/analyze_nsdf_cpu.py LOG` now validates complete CPU/IO/score triples and
reports timings directly. It verifies channel/bank/sequence identity, IO count
and wrapping checksum, read bounds, early gating, numerical parity and flags.
It excludes connection-boundary fragments and refuses diagnostic acquisition
errors. Tests cover malformed metadata/checksums/counts and wrong CPU estimates.

One further arithmetic change replaces the interpolation's software 64-bit
division with three native 32-bit divisions producing successive 9, 9 and 1
fraction bits. It computes exactly the same truncated Q20 shift: a local
maximum bounds the numerator by the denominator, and all intermediate shifts
fit u32 even at the maximum valid NSDF curvature. Boundary cases plus 100,000
deterministic fractions match the wide-integer reference with overflow checks
enabled. Other 64-bit products remain where needed to avoid overflow. No
arithmetic tolerance or pitch acceptance guard was widened. This additional
optimization's on-device timing is not yet measured.

Inspection of the target disassembly confirmed native `divu` for the fraction
steps but exposed a remaining `__divdi3` call for height correction divided by
2^22. At a local maximum the correction product is nonnegative, so an explicit
right shift is exactly equivalent and avoids this size-optimization artifact.
Another 10,000 bounded local maxima check lag and height against wide-division
reference arithmetic. This is confined to the NSDF selector; unrelated math
and compiler optimization settings remain untouched.

Physical native-division trial, `3814b173`, same pulse/LFO patch:
`tests/fixtures/nsdf-cpu-native-div.json` retains all eight complete matched
CPU/IO/score triples from `/tmp/tuner-nsdf-native-div-live.log`. The bounded
135-second capture completed and closed the serial reader. All estimates,
qualification flags, score checksums, metadata and read bounds match the host
model, with no reported acquisition errors.

| Input/bank | Selection | Result |
|---|---:|---|
| IN 0 native | 0.811 ms | 882.216 Hz, qualified |
| IN 0 low | 1.272 ms | 881.127 Hz, qualified |
| IN 1 native | 1.545 ms | 15819.849 Hz, **false candidate on the LFO** |
| IN 1 low | 0.404 ms | no candidate |
| IN 2/3, both | 0.0066–0.0070 ms | gated before score reads |

Pulse selection totals 2.083 ms versus 3.456 ms in the previous physical trial
and 30.592 ms initially. Four comparable inputs would take about 8.33 ms per
50-ms update period for selection alone; this is an extrapolation, not measured
four-channel scheduling or worst-case CPU utilization. Independent IO sweeps
remain 0.274–0.292 ms. Target disassembly contains native `divu` and multiply/
shift operations, with no software division call inside `nsdf_select::peak`.

The LFO's native frame has only 6.990 RMS counts, but clarity 0.816321 passes
the existing candidate guard. Its asynchronous low frame has 115.464 RMS
counts and no candidate. This reproduces the earlier qualification concern;
neither raising the global amplitude floor nor using this asynchronous RMS
ratio is a justified fix. A regression test explicitly retains the observation
without mistaking numerical agreement for physical correctness. Aligned
source-energy measurement and bank arbitration remain a production gate.

Next physical coverage should include low and high steady sines, while leaving
the LFO connected. No additional flash is needed for those captures. The working
baseline remains authoritative; none of these diagnostics owns CV outputs.

Physical low-sine trial, same `3814b173` firmware: user set Local Parks to
approximately 55 Hz on IN 0, with the LFO left on IN 1. Eight complete matched
records from `/tmp/tuner-nsdf-sine55-live.log` are retained in
`tests/fixtures/nsdf-cpu-sine55.json`. All CPU/model, metadata, checksum, gating
and read-bound checks pass; no acquisition error was reported. Low bank
qualifies 55.324 Hz in 0.733 ms (449 reads); native bank has no candidate and
takes 0.430 ms (322 reads). Combined selection is 1.163 ms. The LFO has no
qualified candidate in these particular records, which does not resolve the
previous captured false candidate. Quiet IN 2/3 frames are gated as expected.

This confirms basic low-sine handling and the intended bank qualification at
this setting, not absolute pitch accuracy or end-to-end latency. The user's
55-Hz setting is approximate, the banks are asynchronous, and low acquisition
still needs its roughly 101-ms sample window. Separately, known synthetic
55-Hz sines at 32 phases and amplitudes 72/14000 counts produce worst errors
0.105/0.018 cents in the host score model; all native-bank cases are rejected.
Those checks and the physical fixture are now regression tests. Next hardware
coverage: a steady high sine around 10 kHz, keeping the LFO patch unchanged.

Physical high-sine trial, same `3814b173` firmware and LFO patch: user set
IN 0 near 10 kHz. All eight complete CPU/IO/score triples from the bounded
135-second `/tmp/tuner-nsdf-sine10k-live.log` capture pass the report validator
and are retained in `tests/fixtures/nsdf-cpu-sine10k.json`. Native bank qualifies
10002.669 Hz, clarity 0.999690, in 0.842 ms (358 reads). Low bank rejects its
102.256-Hz candidate, clarity 0.331543, in 0.966 ms (368 reads). Combined
selection is 1.807 ms; independent IO sweeps remain 0.274–0.292 ms. Both LFO
records are unqualified in this session and quiet IN 2/3 records are gated.
No acquisition errors appeared. The previous LFO false-candidate regression
remains unresolved, not invalidated by this session's rejected candidates.

The known synthetic model is also tested at 9900/10000/10100 Hz, 32 phases
each, at amplitudes 72/14000 counts. All qualify, worst error under 0.033 cents;
the actual host-compiled Rust parity corpus now includes those frequencies.
Physical knob settings are not frequency references, so neither the displayed
precision nor model parity proves absolute hardware accuracy. This establishes
basic high-sine behavior and selection timing, not full-rate scheduling,
end-to-end latency, or the final 20-Hz/20-kHz endpoint qualification.

Physical upper-range trial, same `3814b173` firmware: Local Parks sine set
near 18.5 kHz, LFO still on IN 1. All eight complete CPU/IO/score triples from
`/tmp/tuner-nsdf-sine18500-live.log` pass validation and are retained in
`tests/fixtures/nsdf-cpu-sine18500.json`. Native bank qualifies 18529.872 Hz,
clarity 0.998121, in 1.070 ms (346 reads). Its unrefined estimate is
18539.908 Hz; guarded longer-lag refinement adjusts it without changing octave.
Low bank rejects its 42.288-Hz candidate (clarity 0.378122) in 1.309 ms,
460 reads. Combined selection is 2.379 ms. The two LFO frames are rejected;
quiet IN 2/3 frames are gated. No acquisition errors appeared. The bounded
capture completed and closed the reader. No firmware or FPGA change was needed.

Synthetic upper-range sine coverage now includes 18/18.5/19/19.9 kHz at
32 phases and 72/14000-count amplitudes. All model estimates qualify with
worst error below 0.152 cents; tests bound these new cases at 0.16 cents,
while retaining the existing tighter 0.04-cent bound near 10 kHz. Host-compiled
Rust parity also covers these added frequencies. The physical result is basic
upper-range qualification and timing evidence, not independent absolute
frequency accuracy, repeated-frame stability, or an exact 20-kHz endpoint test.
The known LFO false-candidate case, scheduling and arbitration gates remain.

Physical low-edge sine trial, same `3814b173` firmware and LFO patch: first
135-second capture `/tmp/tuner-nsdf-sine-lowedge-live.log` has seven complete
triples, including IN 0 low at 23.922 Hz, clarity 0.999997, 0.853 ms. The
following native frame was truncated and was not considered model-validated.
A separate 150-second capture `/tmp/tuner-nsdf-sine-lowedge-repeat.log` contains
eight complete triples, retained in `tests/fixtures/nsdf-cpu-sine-lowedge.json`.
No packet is stitched across the two sessions. All eight pass metadata,
checksum, score/model, gating and read-bound validation, with no acquisition
error. IN 0 native has no candidate in 0.435 ms (322 reads); low qualifies
23.950 Hz, clarity 0.999999, in 0.851 ms (604 reads), total selection 1.286 ms.
The two LFO records are unqualified; quiet channels are gated. The reader is
closed. These sparse, minutes-separated readings do not establish oscillator
stability or absolute accuracy, and neither capture is an exact 20-Hz test.

Synthetic 22/23.5/25-Hz sines at 32 phases and amplitudes 72/14000 counts all
qualify in the low bank; worst error is below 0.222 cents. New low-edge cases
are bounded at 0.25 cents, preserving the prior 55-Hz bound of 0.12 cents.
Native synthetic cases are all rejected, and host-compiled Rust parity includes
the added frequencies. No detector acceptance threshold changed.

`tests/capture_nsdf_cpu.py PORT` now provides a bounded, read-only serial capture
that ends once all four channels and both banks have complete validated records
(default maximum 180 seconds). It handles split reads, ignores boundary fragments,
fails on diagnostic errors and closes the port on success or failure. Output is
the raw protocol on stdout, with completion status on stderr. Tests cover
duplicate frames, incomplete coverage, corrupted records, split reads and port
closure. This host-only helper avoids cutting a required frame at an arbitrary
duration; it has not yet been used for a physical capture. For example, from
`gateware`: `PYTHONPATH=tests python tests/capture_nsdf_cpu.py /dev/cu.usbmodem83102`.

Basic physical coverage now includes approximately 24 Hz, 55 Hz, 880-Hz pulse,
10 kHz and 18.5 kHz. This supports proceeding to aligned source-energy guarding
and continuous four-channel scheduling; it does not waive the previously listed
production gates or establish full-band worst-case performance.

## Source-energy diagnostic integration

The new `NsdfSourceEnergy` measures raw sum and sum of squares over a rolling
40-block window, 512 native sample groups per block: 20480 samples, 106.667 ms.
One multiplier is shared across four channels. Packed ring entries use three
32-bit words per channel/block (signed sum, square low32/high8), 480 words total,
mapping to one EBR rather than a wide shallow array. There is no new CPU frame
buffer. Outputs publish atomically at block boundaries, retaining an exclusive
native sample-group sequence and readiness flag. Source windows update every
2.667 ms, not for each pitch request. Missing an input batch sets a sticky fault
and invalidates the measurements until reset. The worst input-group service
time is under 100 main-clock cycles, versus 312.5 cycles available at 192 kHz.

Exact simulation checks include full-size windows, ring replacement, signed
extremes, constant DC, alternating extremes, independent random samples, atomic
publication and overrun. Isolated synthesis: 1 EBR, 1 DSP, 788 LUT4, 1272 FF.
An initial synthesis unnecessarily mapped two constant address multiplications
to DSPs; explicit shifts/additions removed them. Isolated routed timing is
101.41 MHz at a 60-MHz target. These costs exclude CSR integration.

The peripheral now snapshots the selected channel's source moments on each
accepted analysis request. Byte-wide CSR tests check signed totals, split square
readback, frozen values despite continued acquisition, channel changes and
warm-up readiness. Identity changes to `0x4e534402`; firmware emits a preceding
`NSDF SOURCE` line with channel, bank, score sequence, source end sequence,
sample count, sum, squares, and status (bit0 ready, bit1 overrun, bits2..3 channel).
Existing CPU/IO/score triples remain contiguous. This firmware does NOT use
these moments to accept/reject pitch yet, and does not alter production pitch,
CV ownership, saved profiles or the quantizer interrupt.

`analyze_nsdf_source.py LOG` verifies matching frame identity, bounds, readiness,
source faults and physically possible moments. Native source age uses wrapping
sequence subtraction with an explicit maximum 512-sample allowance; the host
reports whether native-frame RMS exceeds max(2 counts, 10% of centered source
RMS). This is a provisional host diagnostic, not a proven hardware LFO fix.
Filtered-bank sample sequences have a different origin/rate: no alignment or
relative-energy decision is invented for them. Low-bank source alignment,
transient behavior and the 2% low-bank guard still need implementation/testing.
The capture helper's `--source` option requires a whole cycle with validated
source metadata, rather than stopping on CPU-only coverage. Protocol tests use
explicitly synthetic moments and are not presented as measured source energy.

Full normal-display/192-kHz build, seed15, passes FINAL routing: main 66.76 MHz
at 60 MHz; pixel 86.18 at 74.25; serializer 401.61 at 371.33; audio 67.36 at
49.152. Total 46/56 EBR and 15/28 DSP, versus previous 45/14. The preliminary
placement timing failed before routing; only the final routed figures above
qualify this artifact. CPU RAM remains 32 KiB. No claim of measured stack
high-water or continuous four-channel throughput is made. New source metadata
still needs physical validation after loading this diagnostic build.

First physical source-moment trial, `eb9fab10`, Local Parks sine around 24 Hz
on IN 0 and the existing LFO on IN 1. The new capture helper with `--source`
completed a validated four-channel/two-bank cycle and closed the port normally.
Raw log `/tmp/tuner-nsdf-source-low-live.log`; retained complete records in
`tests/fixtures/nsdf-cpu-source-low.json`. All eight windows have 20480 samples,
ready status, matching channel/score identity, valid moments, and no overrun.
CPU/model, score checksum and read-bound checks also pass. Native source ages
are 272–440 sample groups (1.42–2.29 ms), within the explicit 512-sample bound.

The LFO reproduces a raw qualified 15787.669-Hz false candidate, clarity 0.800875.
Native-frame centered RMS is 8.992 counts, versus 144.502 counts for its matched
long source window. The existing 10% relative-energy rule therefore rejects
this captured candidate on the host (ratio about 6.22%). This is the first
physical aligned-source evidence for the proposed safeguard, not a blanket
LFO-rejection proof. The source has a large mean level; DC removal from the
moments is essential, rather than comparing uncentered RMS values.

IN 0 low qualifies 23.969 Hz in 0.911 ms; native has no candidate in 0.435 ms.
The sine source RMS is 7791/8062 counts in the asynchronous native/low records.
No low-bank relative-energy decision is made yet because its sequence alignment
still needs explicit implementation. Quiet IN 2/3 records are gated. A retained
regression verifies the real LFO counterexample would be rejected while the raw
CPU qualification stays unchanged. Firmware still makes no new pitch decision.
Next useful physical test is a native-band sine around 880 Hz (then attenuated),
to verify this guard does not suppress legitimate quiet audio. Full-rate
scheduling, transition behavior and production integration remain outstanding.

Previously attenuated 880-Hz follow-up on the same installed `eb9fab10` build completed
all eight source/CPU/IO/score records. Retained fixture:
`tests/fixtures/nsdf-cpu-source-880.json`; raw log:
`/tmp/tuner-nsdf-source-880-live.log`. Native IN 0 qualifies 881.144 Hz in
0.870 ms, frame RMS 7944.404 versus centered source RMS 7978.556 counts.
The host-only native relative-energy guard passes it. Low IN 0 qualifies
881.093 Hz in 1.319 ms; this asynchronous agreement is not independent
frequency-accuracy evidence. No low-bank relative-energy decision is made.
Native source ages are 138–284 groups, all within the 512-group bound.
IN 1 native is unqualified and also fails the host relative guard; quiet
IN 2/3 are gated. The next physical test is attenuation of this same sine.

User correction: this 880-Hz capture was NOT full level. The attenuation used
earlier for Blade-wave testing was still in place; its Vpp was not specified.
Retain the measured digital counts above without inferring full-scale level.

The analyzer now discards a connection prefix before the first SOURCE header,
matching the capture helper. This capture began partway through a record;
that CPU-only prefix was excluded, not stitched to later metadata. Acquisition
errors even in the prefix and missing SOURCE records inside the retained
capture remain failures, with regression coverage. No firmware change or
flash was required for this capture, parser correction, or added regressions.

Further attenuation trial: user reports approximately 0.075 Vpp at ~880 Hz,
same Local Parks sine IN 0 and LFO IN 1. `nsdf-cpu-source-quiet075.json`
retains eight validated records from `/tmp/tuner-nsdf-source-quiet075-live.log`.
All source windows ready, no overruns, native ages 7–502 groups. Native sine
qualifies 880.440 Hz in 0.857 ms with frame RMS 99.477 and source RMS 98.540
counts; the host 10% relative-energy safeguard passes. Low sine qualifies
881.218 Hz in 1.274 ms (no low-bank relative guard yet). These asynchronous
readings differ by about 1.53 cents; without an independent reference or
simultaneous frames, this does not establish absolute accuracy or its cause.

The same capture contains another raw qualified LFO false candidate at
15787.521 Hz: native RMS 8.088 versus source RMS 124.068 counts, rejected by
the host safeguard. Quiet IN 2/3 are gated. Regressions retain both quiet-sine
preservation and LFO rejection, including Rust/model parity over the scores.
This is sparse physical evidence, not a proof across levels, LFO phases,
transients or all frequencies. Installed firmware remains `eb9fab10`; the
guard is not enabled on-device. Next engineering work remains low-bank source
alignment and transition validation before continuous scheduling/integration.

### Offline endpoint alignment and transition qualification (2026-09-12)

Rack powered off at user request: no serial access or flash during this work.
The low-bank count starts after FIR warmup, so `low_sequence * 32` alone is
not its native endpoint. Acquisition already labels each filtered batch with
its actual exclusive native endpoint. The frontend now publishes that label
atomically with the four-channel low history head, then freezes it on the same
edge as the selected snapshot. Native snapshots freeze the native history
sequence instead. CSR offset 60 exposes `frame_native_end`; identity is now
`0x4e534403` and firmware requires that version. SOURCE lines append
`frame_end`, remaining within the existing 192-byte nonblocking UART buffer.
No additional audio/score buffers, multiplier, or CPU RAM were introduced.

Host analysis preserves old fixtures without inventing their missing endpoint.
For new low-bank records, signed wrapping endpoint separation must lie within
plus/minus 512 native groups before reporting the provisional 2% relative RMS
guard. The source window can lead the filtered endpoint because FIR execution
takes time, or trail it because moments publish every 512 samples. This is
bounded temporal proximity, NOT identical sample support: 604 low samples with
a 769-tap FIR cover 20064 native samples, versus 20480 for source moments.
Production use still needs physical validation and bank-arbitration decisions.

RTL tests cover both unchanged and shifted decimation origins using 5/37-tap
filters, verify exact scores, and verify CSR endpoint stability while input
continues during readout. Existing full 769-tap acquisition tests cover the
actual filter's published native labels. Host tests cover explicit endpoints,
stale/mismatched metadata, legacy compatibility and UART worst-case length.
Synthetic actual-coefficient FIR tests preserve quiet 24/55/880/1400-Hz sines
with and without DC offset. A 14000-to-100-count amplitude step exposes an
intentional limitation: the native relative guard temporarily vetoes quiet
audio until loud history ages out; settling is bounded by 20992 native groups
(109.33 ms). This is not a claim of instantaneous quiet-signal response.

The new guard remains host-only. Baseline tuner/calibrator/quantizer pitch and
output ownership are unchanged. Tomorrow's first test is a complete SOURCE
capture with the new endpoint field, then quiet low-frequency sine and an
amplitude transition. Continuous scheduling and production promotion should
follow those checks, not bypass them.

Qualification: 103 focused tests plus 8 added stopband cases plus 35 full-filter,
snapshot, shared-history, direct-score and live-acquisition tests pass (146
distinct cases). The stopband cases cover 3/10/18.5/19.9 kHz at amplitudes
100/14000 counts with DC; this is synthetic energy rejection, not measured
hardware pitch accuracy. Endpoint wraparound tests also pass.

Full r5 normal-display 192-kHz synthesis has 46/56 EBR and 15/28 DSP, unchanged.
Seeds 15 and 16 failed final serializer timing (361.01 and 349.77 MHz against
371.33 MHz); these are NOT qualified artifacts. Seed 17 passes all final clocks:
main 65.00/60 MHz, pixel 89.74/74.25, serializer 436.87/371.33, audio
71.13/49.152. Use `TILIQUA_TUNER_SEED=17` for this experiment's normal-display
build. Final report `/tmp/tuner-nsdf-endpoint-seed17.tim`; same synthesized
netlist as `/tmp/tuner-nsdf-endpoint-build.log`. Failed route paths were serializer
register-to-output routing, not the added timestamp or arithmetic.
Packed bitstream SHA256:
`b79653b788d1c8a4043bc0510ff2e2e3f39554540a12e82e66132d05aa3ab929`.
Firmware .data=1632, .bss=8, heap=0 and reserved stack=31128 bytes; CPU RAM
remains 32 KiB (reserved stack is not measured high-water). Hardware remains
unflashed until the user powers up the rack and resumes testing.

Physical endpoint validation after flashing `1f0cb525` to slot 1, normal display,
profiles preserved: `tests/fixtures/nsdf-cpu-endpoint-880.json` retains all eight
complete records from `/tmp/tuner-nsdf-endpoint-880-live.log`. Quiet ~880-Hz sine
IN 0 and LFO IN 1 retained. All timestamps, moments, CPU/model comparisons,
checksums and read bounds pass; explicit native offsets range -32 to +327
groups. The negative low-bank offset is expected and now represented correctly.
Native sine qualifies 879.400 Hz in 0.850 ms, low sine 879.494 Hz in 1.199 ms;
frame/source RMS are approximately 99 counts in both records. Both host energy
guards pass. Asynchronous agreement is not independent absolute accuracy.
LFO native is unqualified and fails the energy guard; low has no candidate even
though its energy guard passes. Energy is an additional veto, never a substitute
for pitch qualification. Quiet unused channels are gated. Next physical check:
quiet ~55-Hz sine, then amplitude transitions. Firmware remains diagnostic-only.
